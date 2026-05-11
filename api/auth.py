"""
Hermes Web UI -- Authentication and authorization helpers.

Supports:
1. Legacy single-password mode (HERMES_WEBUI_PASSWORD/settings.json hash).
2. Multi-user mode backed by STATE_DIR/users.db (api.users).
"""
import hashlib
import hmac
import http.cookies
import json
import logging
import os
import secrets
import tempfile
import threading
import time

from api.config import STATE_DIR, load_settings
from api.users import (
    create_auth_session,
    invalidate_auth_session,
    is_multi_user_mode,
    users_count,
    verify_api_token,
    verify_auth_session,
    verify_user_password,
)

logger = logging.getLogger(__name__)


# Default session TTL — 30 days. Kept as a module-level constant for backwards
# compatibility with downstream code and regression tests that import it.
# At runtime, prefer ``_resolve_session_ttl()`` which honours the env var and
# settings.json overrides; this constant is the floor / fallback.
SESSION_TTL = 86400 * 30  # 30 days


def _resolve_session_ttl() -> int:
    """Resolve session TTL from env > settings > default.

    Priority mirrors get_password_hash(): HERMES_WEBUI_SESSION_TTL env var
    first, then settings.json, falling back to ``SESSION_TTL`` (30 days).
    Clamped to [60s, 1 year] to prevent runaway cookies or self-lockout.
    """
    env_v = os.getenv('HERMES_WEBUI_SESSION_TTL', '').strip()
    if env_v.isdigit():
        val = int(env_v)
        if 60 <= val <= 86400 * 365:
            return val
    s = load_settings()
    v = s.get('session_ttl_seconds')
    if isinstance(v, int) and 60 <= v <= 86400 * 365:
        return v
    return SESSION_TTL


# ── Public paths (no auth required) ─────────────────────────────────────────
PUBLIC_PATHS = frozenset({
    '/login', '/health', '/favicon.ico', '/sw.js',
    '/api/auth/login', '/api/auth/status',
    '/setup-admin',
    '/manifest.json', '/manifest.webmanifest',
})

COOKIE_NAME = 'hermes_session'

_SESSIONS_FILE = STATE_DIR / '.sessions.json'


def _load_sessions() -> dict[str, float]:
    """Load persisted sessions from STATE_DIR, pruning expired entries.

    Returns an empty dict on any read or parse error so startup is never
    blocked by a corrupt or missing sessions file.
    """
    try:
        if _SESSIONS_FILE.exists():
            data = json.loads(_SESSIONS_FILE.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('malformed sessions file — expected dict')
            now = time.time()
            return {t: exp for t, exp in data.items()
                    if isinstance(t, str) and isinstance(exp, (int, float)) and exp > now}
    except Exception as e:
        logger.debug("Failed to load sessions file, starting fresh: %s", e)
    return {}


def _save_sessions(sessions: dict[str, float]) -> None:
    """Atomically persist sessions to STATE_DIR/.sessions.json (0600).

    Uses a temp file + os.replace() so a crash mid-write never leaves a
    truncated file.  Mirrors the same pattern as .signing_key persistence.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix='.sessions.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(sessions, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _SESSIONS_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Failed to persist sessions: %s", e)


# Active sessions: token -> expiry timestamp (persisted across restarts via STATE_DIR)
_sessions = _load_sessions()

# ── Login rate limiter ──────────────────────────────────────────────────────
_LOGIN_ATTEMPTS_FILE = STATE_DIR / '.login_attempts.json'
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 60  # seconds


def _load_login_attempts() -> dict[str, list[float]]:
    """Load persisted login attempts from STATE_DIR, pruning expired entries."""
    try:
        if _LOGIN_ATTEMPTS_FILE.exists():
            data = json.loads(_LOGIN_ATTEMPTS_FILE.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('malformed login-attempts file — expected dict')
            now = time.time()
            attempts: dict[str, list[float]] = {}
            for ip, raw_times in data.items():
                if not isinstance(ip, str) or not isinstance(raw_times, list):
                    continue
                fresh = [
                    float(t)
                    for t in raw_times
                    if isinstance(t, (int, float)) and now - float(t) < _LOGIN_WINDOW
                ]
                if fresh:
                    attempts[ip] = fresh
            return attempts
    except Exception as e:
        logger.debug("Failed to load login attempts file, starting fresh: %s", e)
    return {}


def _save_login_attempts(attempts: dict[str, list[float]]) -> None:
    """Atomically persist login attempts to STATE_DIR/.login_attempts.json (0600)."""
    try:
        _LOGIN_ATTEMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_LOGIN_ATTEMPTS_FILE.parent, suffix='.login_attempts.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(attempts, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _LOGIN_ATTEMPTS_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Failed to persist login attempts: %s", e)


_login_attempts = _load_login_attempts()  # ip -> [timestamp, ...]
_tls = threading.local()


def _check_login_rate(ip: str) -> bool:
    """Return True if the IP is allowed to attempt login."""
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    # Prune old attempts
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    if attempts:
        _login_attempts[ip] = attempts
    else:
        _login_attempts.pop(ip, None)
    _save_login_attempts(_login_attempts)
    return len(attempts) < _LOGIN_MAX_ATTEMPTS


def _record_login_attempt(ip: str) -> None:
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts.append(now)
    _login_attempts[ip] = attempts
    _save_login_attempts(_login_attempts)


def _signing_key():
    """Return a random signing key, generating and persisting one on first call."""
    key_file = STATE_DIR / '.signing_key'
    try:
        if key_file.exists():
            raw = key_file.read_bytes()
            if len(raw) >= 32:
                return raw[:32]
    except Exception:
        logger.debug("Failed to read or access signing key file, using in-memory key")
    # Generate a new random key
    key = secrets.token_bytes(32)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(key)
        key_file.chmod(0o600)
    except Exception:
        logger.debug("Failed to persist signing key, using in-memory key only")
    return key


def _hash_password(password):
    """PBKDF2-SHA256 with 600k iterations (OWASP recommendation).
    Salt is the persisted random signing key, which is secret and unique per
    installation. This keeps the stored hash format a plain hex string
    (no format change to settings.json) while replacing the predictable
    STATE_DIR-derived salt from the original implementation."""
    salt = _signing_key()
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    return dk.hex()


def get_password_hash() -> str | None:
    """Return the active password hash, or None if auth is disabled.
    Priority: env var > settings.json."""
    env_pw = os.getenv('HERMES_WEBUI_PASSWORD', '').strip()
    if env_pw:
        return _hash_password(env_pw)
    settings = load_settings()
    return settings.get('password_hash') or None


def is_auth_enabled() -> bool:
    """True if auth is required for non-public routes."""
    if is_multi_user_mode():
        return True
    return get_password_hash() is not None


def verify_password(plain, username: str | None = None) -> bool:
    """Verify password in legacy or multi-user mode."""
    if is_multi_user_mode():
        if not username:
            return False
        try:
            return verify_user_password(username, plain) is not None
        except ValueError:
            return False
    expected = get_password_hash()
    if not expected:
        return False
    return hmac.compare_digest(_hash_password(plain), expected)


def create_session(user_id: int | None = None) -> str:
    """Create a new auth session. Returns signed cookie value."""
    if is_multi_user_mode():
        if user_id is None:
            raise ValueError("user_id is required in multi-user mode")
        token = create_auth_session(int(user_id), _resolve_session_ttl())
    else:
        token = secrets.token_hex(32)
        _sessions[token] = time.time() + _resolve_session_ttl()
        _save_sessions(_sessions)
    sig = hmac.new(_signing_key(), token.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{token}.{sig}"


def _prune_expired_sessions():
    """Remove all expired session entries to prevent unbounded memory growth."""
    now = time.time()
    expired = [t for t, exp in _sessions.items() if now > exp]
    if expired:
        for token in expired:
            _sessions.pop(token, None)
        _save_sessions(_sessions)


def verify_session(cookie_value):
    """Verify a signed session cookie.

    Returns:
      - user dict in multi-user mode
      - bool in legacy mode
    """
    if not cookie_value or '.' not in cookie_value:
        return False
    token, sig = cookie_value.rsplit('.', 1)
    expected_sig = hmac.new(_signing_key(), token.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected_sig):
        return False
    if is_multi_user_mode():
        return verify_auth_session(token)
    _prune_expired_sessions()  # legacy lazy cleanup
    expiry = _sessions.get(token)
    if not expiry or time.time() > expiry:
        _sessions.pop(token, None)
        return False
    return True


def invalidate_session(cookie_value) -> None:
    """Remove a session token."""
    if cookie_value and '.' in cookie_value:
        token = cookie_value.rsplit('.', 1)[0]
        if is_multi_user_mode():
            invalidate_auth_session(token)
            return
        if token in _sessions:
            _sessions.pop(token, None)
            _save_sessions(_sessions)


def parse_cookie(handler) -> str | None:
    """Extract the auth cookie from the request headers."""
    cookie_header = handler.headers.get('Cookie', '')
    if not cookie_header:
        return None
    cookie = http.cookies.SimpleCookie()
    try:
        cookie.load(cookie_header)
    except http.cookies.CookieError:
        return None
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel else None


def get_current_user() -> dict | None:
    current = getattr(_tls, "current_user", None)
    return current if isinstance(current, dict) else None


def clear_current_user() -> None:
    _tls.current_user = None


def _set_current_user(handler, user: dict | None) -> None:
    if isinstance(user, dict):
        handler.current_user = user
        _tls.current_user = user
    else:
        if hasattr(handler, "current_user"):
            handler.current_user = None
        _tls.current_user = None


def _extract_bearer(handler) -> str | None:
    header = str(handler.headers.get("Authorization", "")).strip()
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    return token or None


def _auth_error(handler, parsed, message: str = "Authentication required", status: int = 401) -> bool:
    if parsed.path.startswith('/api/'):
        handler.send_response(status)
        handler.send_header('Content-Type', 'application/json')
        handler.end_headers()
        payload = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        handler.wfile.write(payload)
    else:
        handler.send_response(302)
        import urllib.parse as _urlparse

        _path_with_query = parsed.path or '/'
        if parsed.query:
            _path_with_query += '?' + parsed.query
        _next = _urlparse.quote(_path_with_query, safe='/')
        handler.send_header('Location', 'login?next=' + _next)
        handler.end_headers()
    return False


def _as_authenticated_user(user: dict, *, auth_type: str, scopes=None) -> dict:
    out = dict(user)
    out["auth_type"] = auth_type
    out["is_admin"] = str(user.get("role")) == "admin"
    out["token_scopes"] = set(scopes or [])
    return out


def user_has_scope(user: dict | None, scope: str) -> bool:
    if not isinstance(user, dict):
        return False
    if user.get("auth_type") != "token":
        return True
    scopes = user.get("token_scopes") or set()
    if not isinstance(scopes, set):
        scopes = set(scopes)
    if "admin" in scopes:
        return True
    return scope in scopes


def check_auth(handler, parsed) -> bool:
    """Check if request is authorized. Returns True if OK.
    If not authorized, sends 401 (API) or 302 redirect (page) and returns False."""
    clear_current_user()
    if hasattr(handler, "current_user"):
        handler.current_user = None

    # First-run setup mode: no user DB entries and no legacy password.
    # Keep legacy bootstrap compatibility when HERMES_WEBUI_PASSWORD/settings
    # is configured before creating multi-user accounts.
    setup_mode = (users_count() == 0 and get_password_hash() is None)
    if setup_mode:
        setup_public = {
            "/setup-admin",
            "/api/setup/admin",
            "/api/auth/status",
            "/api/auth/login",
            "/health",
            "/favicon.ico",
            "/sw.js",
            "/manifest.json",
            "/manifest.webmanifest",
        }
        if parsed.path.startswith("/static/") or parsed.path in setup_public:
            return True
        if parsed.path == "/login":
            handler.send_response(302)
            handler.send_header("Location", "/setup-admin")
            handler.end_headers()
            return False
        if parsed.path.startswith("/api/"):
            handler.send_response(403)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(b'{"error":"Admin setup required"}')
            return False
        handler.send_response(302)
        handler.send_header("Location", "/setup-admin")
        handler.end_headers()
        return False

    # Public paths don't require auth
    if parsed.path in PUBLIC_PATHS or parsed.path.startswith('/static/') or parsed.path.startswith('/session/static/'):
        return True

    # Legacy mode without password: allow all requests.
    if not is_multi_user_mode() and not is_auth_enabled():
        return True

    # Multi-user mode: Authorization header token first, then cookie session.
    if is_multi_user_mode():
        bearer = _extract_bearer(handler)
        if bearer:
            token_ctx = verify_api_token(bearer)
            if token_ctx:
                user = token_ctx.get("user") or {}
                if user.get("status") != "active":
                    return _auth_error(handler, parsed, "Account is disabled", status=403)
                _set_current_user(
                    handler,
                    _as_authenticated_user(
                        user,
                        auth_type="token",
                        scopes=token_ctx.get("scopes") or set(),
                    ),
                )
                return True
        cookie_val = parse_cookie(handler)
        if cookie_val:
            user = verify_session(cookie_val)
            if isinstance(user, dict):
                if user.get("status") != "active":
                    return _auth_error(handler, parsed, "Account is disabled", status=403)
                _set_current_user(handler, _as_authenticated_user(user, auth_type="cookie"))
                return True
        return _auth_error(handler, parsed)

    # Legacy single-password mode.
    cookie_val = parse_cookie(handler)
    if cookie_val and verify_session(cookie_val):
        return True
    return _auth_error(handler, parsed)


def set_auth_cookie(handler, cookie_value) -> None:
    """Set the auth cookie on the response."""
    cookie = http.cookies.SimpleCookie()
    cookie[COOKIE_NAME] = cookie_value
    cookie[COOKIE_NAME]['httponly'] = True
    cookie[COOKIE_NAME]['samesite'] = 'Lax'
    cookie[COOKIE_NAME]['path'] = '/'
    cookie[COOKIE_NAME]['max-age'] = str(_resolve_session_ttl())
    # Set Secure flag when connection is HTTPS
    if getattr(handler.request, 'getpeercert', None) is not None or handler.headers.get('X-Forwarded-Proto', '') == 'https':
        cookie[COOKIE_NAME]['secure'] = True
    handler.send_header('Set-Cookie', cookie[COOKIE_NAME].OutputString())


def clear_auth_cookie(handler) -> None:
    """Clear the auth cookie on the response."""
    cookie = http.cookies.SimpleCookie()
    cookie[COOKIE_NAME] = ''
    cookie[COOKIE_NAME]['httponly'] = True
    cookie[COOKIE_NAME]['path'] = '/'
    cookie[COOKIE_NAME]['max-age'] = '0'
    handler.send_header('Set-Cookie', cookie[COOKIE_NAME].OutputString())
