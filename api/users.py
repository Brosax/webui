"""Hermes Web UI -- Multi-user identity, sessions, and API tokens."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from api.config import STATE_DIR, load_settings, save_settings

logger = logging.getLogger(__name__)

USERS_DB = STATE_DIR / "users.db"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ROLE_VALUES = {"admin", "user"}
STATUS_VALUES = {"active", "disabled"}
PASSWORD_ITERATIONS = 600_000


def _utc_now() -> float:
    return float(time.time())


def _connect() -> sqlite3.Connection:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(USERS_DB), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            profile_name TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            trace_audit INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            token_prefix TEXT NOT NULL,
            name TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            scopes_json TEXT NOT NULL,
            expires_at REAL,
            revoked_at REAL,
            last_used_at REAL,
            created_at REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_tokens_user_id ON api_tokens(user_id)"
    )

    # Migration: add trace_audit column if missing (existing databases)
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "trace_audit" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN trace_audit INTEGER NOT NULL DEFAULT 0")
    except sqlite3.Error:
        pass


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return dk.hex()


def _user_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "display_name": str(row["display_name"]),
        "role": str(row["role"]),
        "status": str(row["status"]),
        "profile_name": str(row["profile_name"]),
        "trace_audit": int(row["trace_audit"]) if "trace_audit" in row.keys() else 0,
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def validate_username(raw: str) -> str:
    username = str(raw or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Invalid username: lowercase letters, numbers, hyphens, underscores only"
        )
    return username


def normalize_scopes(raw_scopes) -> list[str]:
    if raw_scopes is None:
        return ["chat", "files"]
    if isinstance(raw_scopes, str):
        values = [p.strip().lower() for p in raw_scopes.split(",")]
    elif isinstance(raw_scopes, list):
        values = [str(p).strip().lower() for p in raw_scopes]
    else:
        raise ValueError("scopes must be a list or comma-separated string")
    allowed = {"chat", "files", "admin"}
    deduped = []
    for value in values:
        if not value:
            continue
        if value not in allowed:
            raise ValueError(f"Unsupported scope: {value}")
        if value not in deduped:
            deduped.append(value)
    if not deduped:
        deduped = ["chat", "files"]
    return deduped


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, username, display_name, role, status, profile_name, created_at, updated_at
            FROM users
            ORDER BY id ASC
            """
        ).fetchall()
    return [_user_from_row(r) for r in rows]


def users_count() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return int(row["c"] if row else 0)


def is_multi_user_mode() -> bool:
    try:
        return users_count() > 0
    except Exception:
        logger.debug("is_multi_user_mode check failed", exc_info=True)
        return False


def get_user_by_id(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, role, status, profile_name, created_at, updated_at
            FROM users
            WHERE id = ?
            """,
            (int(user_id),),
        ).fetchone()
    return _user_from_row(row)


def get_user_by_username(username: str) -> dict | None:
    uname = validate_username(username)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, role, status, profile_name, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (uname,),
        ).fetchone()
    return _user_from_row(row)


def _ensure_profile_exists(profile_name: str) -> None:
    if not profile_name or profile_name == "default":
        return
    try:
        from api.profiles import get_hermes_home_for_profile

        target_home = Path(get_hermes_home_for_profile(profile_name))
        if target_home.exists():
            return
    except Exception:
        pass
    try:
        from api.profiles import create_profile_api

        create_profile_api(profile_name)
    except Exception:
        # Last fallback: create minimal directory under ~/.hermes/profiles/<name>.
        try:
            from api.profiles import get_hermes_home_for_profile

            home = Path(get_hermes_home_for_profile(profile_name))
            home.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.debug("Failed to ensure profile exists for %s", profile_name, exc_info=True)


def _personal_workspace_for_username(username: str) -> Path:
    return (STATE_DIR / "users" / username / "workspace").resolve()


def ensure_personal_workspace(username: str) -> str:
    uname = validate_username(username)
    ws = _personal_workspace_for_username(uname)
    ws.mkdir(parents=True, exist_ok=True)
    return str(ws)


def create_user(
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
    status: str = "active",
    profile_name: str | None = None,
) -> dict:
    uname = validate_username(username)
    role_v = str(role or "user").strip().lower()
    if role_v not in ROLE_VALUES:
        raise ValueError("role must be admin or user")
    status_v = str(status or "active").strip().lower()
    if status_v not in STATUS_VALUES:
        raise ValueError("status must be active or disabled")
    if not str(password or ""):
        raise ValueError("password is required")
    profile = str(profile_name or uname).strip().lower()
    if not USERNAME_RE.fullmatch(profile):
        raise ValueError("profile_name must match username format")
    disp = str(display_name or uname).strip() or uname
    salt_hex = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt_hex)
    now = _utc_now()
    with _connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO users (
                    username, display_name, role, status, profile_name,
                    password_hash, password_salt, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uname,
                    disp,
                    role_v,
                    status_v,
                    profile,
                    pw_hash,
                    salt_hex,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT id, username, display_name, role, status, profile_name, created_at, updated_at
                FROM users WHERE username = ?
                """,
                (uname,),
            ).fetchone()
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as e:
            conn.execute("ROLLBACK")
            text = str(e).lower()
            if "users.username" in text:
                raise ValueError("username already exists") from e
            if "users.profile_name" in text:
                raise ValueError("profile_name already bound") from e
            raise ValueError("failed to create user") from e
    _ensure_profile_exists(profile)
    ensure_personal_workspace(uname)
    return _user_from_row(row)


def update_user(
    user_id: int,
    *,
    display_name: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> dict:
    updates = {}
    if display_name is not None:
        value = str(display_name).strip()
        if not value:
            raise ValueError("display_name cannot be empty")
        updates["display_name"] = value
    if role is not None:
        role_v = str(role).strip().lower()
        if role_v not in ROLE_VALUES:
            raise ValueError("role must be admin or user")
        updates["role"] = role_v
    if status is not None:
        status_v = str(status).strip().lower()
        if status_v not in STATUS_VALUES:
            raise ValueError("status must be active or disabled")
        updates["status"] = status_v
    if not updates:
        user = get_user_by_id(int(user_id))
        if not user:
            raise ValueError("user not found")
        return user
    updates["updated_at"] = _utc_now()
    columns = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [int(user_id)]
    with _connect() as conn:
        cur = conn.execute(f"UPDATE users SET {columns} WHERE id = ?", values)
        if cur.rowcount <= 0:
            raise ValueError("user not found")
    user = get_user_by_id(int(user_id))
    if not user:
        raise ValueError("user not found")
    if user.get("status") == "disabled":
        invalidate_user_sessions(int(user_id))
    return user


def set_user_password(user_id: int, new_password: str) -> None:
    if not str(new_password or ""):
        raise ValueError("password is required")
    salt_hex = secrets.token_hex(16)
    pw_hash = _hash_password(new_password, salt_hex)
    now = _utc_now()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE users
            SET password_hash = ?, password_salt = ?, updated_at = ?
            WHERE id = ?
            """,
            (pw_hash, salt_hex, now, int(user_id)),
        )
        if cur.rowcount <= 0:
            raise ValueError("user not found")
    invalidate_user_sessions(int(user_id))


def verify_user_password(username: str, password: str) -> dict | None:
    uname = validate_username(username)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, role, status, profile_name,
                   password_hash, password_salt, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (uname,),
        ).fetchone()
    if row is None:
        return None
    expected = str(row["password_hash"])
    salt_hex = str(row["password_salt"])
    actual = _hash_password(str(password or ""), salt_hex)
    if not hmac.compare_digest(actual, expected):
        return None
    user = _user_from_row(row)
    if user.get("status") != "active":
        return None
    return user


def create_auth_session(user_id: int, ttl_seconds: int) -> str:
    raw_token = secrets.token_hex(32)
    now = _utc_now()
    exp = now + max(60, int(ttl_seconds))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (token_hash, user_id, expires_at, last_seen_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_hash_token(raw_token), int(user_id), exp, now, now),
        )
    return raw_token


def verify_auth_session(raw_token: str) -> dict | None:
    now = _utc_now()
    token_hash = _hash_token(str(raw_token or ""))
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.user_id AS user_id,
                s.expires_at AS expires_at,
                u.id AS id,
                u.username AS username,
                u.display_name AS display_name,
                u.role AS role,
                u.status AS status,
                u.profile_name AS profile_name,
                u.trace_audit AS trace_audit,
                u.created_at AS created_at,
                u.updated_at AS updated_at
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if float(row["expires_at"]) <= now:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
            return None
        if str(row["status"]) != "active":
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
            return None
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
    return _user_from_row(row)


def invalidate_auth_session(raw_token: str) -> None:
    if not raw_token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_hash_token(raw_token),))


def invalidate_user_sessions(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (int(user_id),))


def list_tokens_for_user(user_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, token_prefix, name, scopes_json, expires_at, revoked_at, last_used_at, created_at
            FROM api_tokens
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (int(user_id),),
        ).fetchall()
    result = []
    for row in rows:
        try:
            scopes = json.loads(row["scopes_json"]) if row["scopes_json"] else []
        except Exception:
            scopes = []
        result.append(
            {
                "id": int(row["id"]),
                "prefix": str(row["token_prefix"]),
                "name": str(row["name"]),
                "scopes": scopes,
                "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None,
                "revoked_at": float(row["revoked_at"]) if row["revoked_at"] is not None else None,
                "last_used_at": float(row["last_used_at"]) if row["last_used_at"] is not None else None,
                "created_at": float(row["created_at"]),
            }
        )
    return result


def create_api_token(
    *,
    user_id: int,
    name: str,
    scopes,
    expires_at: float | None = None,
) -> dict:
    token_name = str(name or "").strip() or "token"
    token_scopes = normalize_scopes(scopes)
    raw = "hwu_" + secrets.token_urlsafe(32)
    prefix = raw[:12]
    now = _utc_now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO api_tokens (
                token_hash, token_prefix, name, user_id, scopes_json,
                expires_at, revoked_at, last_used_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?)
            """,
            (
                _hash_token(raw),
                prefix,
                token_name,
                int(user_id),
                json.dumps(token_scopes, ensure_ascii=True),
                float(expires_at) if expires_at is not None else None,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT id, token_prefix, name, scopes_json, expires_at, revoked_at, last_used_at, created_at
            FROM api_tokens
            WHERE token_hash = ?
            """,
            (_hash_token(raw),),
        ).fetchone()
    data = {
        "id": int(row["id"]),
        "prefix": str(row["token_prefix"]),
        "name": str(row["name"]),
        "scopes": json.loads(row["scopes_json"]) if row["scopes_json"] else [],
        "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None,
        "revoked_at": None,
        "last_used_at": None,
        "created_at": float(row["created_at"]),
        "token": raw,
    }
    return data


def revoke_api_token(token_id: int, *, user_id: int | None = None) -> bool:
    now = _utc_now()
    if user_id is None:
        where = "id = ?"
        params = (int(token_id),)
    else:
        where = "id = ? AND user_id = ?"
        params = (int(token_id), int(user_id))
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE api_tokens SET revoked_at = ? WHERE {where}",
            (now, *params),
        )
        return cur.rowcount > 0


def verify_api_token(raw_token: str) -> dict | None:
    if not raw_token:
        return None
    now = _utc_now()
    token_hash = _hash_token(str(raw_token))
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                t.id AS token_id,
                t.user_id AS token_user_id,
                t.name AS token_name,
                t.scopes_json AS scopes_json,
                t.expires_at AS token_expires_at,
                t.revoked_at AS token_revoked_at,
                u.id AS id,
                u.username AS username,
                u.display_name AS display_name,
                u.role AS role,
                u.status AS status,
                u.profile_name AS profile_name,
                u.trace_audit AS trace_audit,
                u.created_at AS created_at,
                u.updated_at AS updated_at
            FROM api_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if row["token_revoked_at"] is not None:
            return None
        if row["token_expires_at"] is not None and float(row["token_expires_at"]) <= now:
            return None
        if str(row["status"]) != "active":
            return None
        conn.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
            (now, int(row["token_id"])),
        )
    try:
        scopes = normalize_scopes(json.loads(row["scopes_json"]) if row["scopes_json"] else [])
    except Exception:
        scopes = ["chat", "files"]
    return {
        "user": _user_from_row(row),
        "token": {
            "id": int(row["token_id"]),
            "name": str(row["token_name"]),
            "scopes": scopes,
        },
        "scopes": set(scopes),
    }


def get_shared_skills_dir() -> Path:
    raw = os.getenv("HERMES_SHARED_SKILLS_DIR", "").strip()
    base = Path(raw).expanduser() if raw else (STATE_DIR / "shared_skills")
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def get_shared_workspace_rules() -> list[dict]:
    settings = load_settings()
    raw = settings.get("shared_workspaces", [])
    if not isinstance(raw, list):
        return []
    rules = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        if not path:
            continue
        mode = str(entry.get("mode") or "read_write").strip().lower()
        if mode not in {"read_only", "read_write"}:
            mode = "read_write"
        try:
            resolved = str(Path(path).expanduser().resolve())
        except Exception:
            continue
        name = str(entry.get("name") or "").strip() or Path(resolved).name
        rules.append({"path": resolved, "name": name, "mode": mode})
    return rules


def upsert_shared_workspace_rule(path: str, name: str | None = None, mode: str = "read_write") -> dict:
    """Add or update a shared workspace rule. Returns the updated rule."""
    if mode not in {"read_only", "read_write"}:
        mode = "read_write"
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception as e:
        raise ValueError(f"Invalid path: {path}") from e

    settings = load_settings()
    raw = settings.get("shared_workspaces", [])
    if not isinstance(raw, list):
        raw = []

    # Normalize mode
    mode = str(mode).strip().lower()
    if mode not in {"read_only", "read_write"}:
        mode = "read_write"

    # Find existing entry by resolved path
    updated = False
    for entry in raw:
        if isinstance(entry, dict) and str(entry.get("path") or "").strip():
            try:
                existing_resolved = str(Path(entry["path"]).expanduser().resolve())
            except Exception:
                continue
            if existing_resolved == resolved:
                entry["name"] = name if name else entry.get("name") or Path(resolved).name
                entry["mode"] = mode
                updated = True
                break

    if not updated:
        display_name = name if name else Path(resolved).name
        raw.append({"path": resolved, "name": display_name, "mode": mode})

    settings["shared_workspaces"] = raw
    save_settings(settings)

    # Return the actual persisted rule (name may have been kept from existing entry)
    for entry in raw:
        if isinstance(entry, dict) and str(entry.get("path") or "").strip():
            try:
                if str(Path(entry["path"]).expanduser().resolve()) == resolved:
                    return {"path": resolved, "name": entry.get("name", ""), "mode": entry.get("mode", "read_write")}
            except Exception:
                continue
    return {"path": resolved, "name": name if name else Path(resolved).name, "mode": mode}


def remove_shared_workspace_rule(path: str) -> bool:
    """Remove a shared workspace rule by resolved path. Returns True if removed."""
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        return False

    settings = load_settings()
    raw = settings.get("shared_workspaces", [])
    if not isinstance(raw, list):
        return False

    original_len = len(raw)
    raw = [
        entry
        for entry in raw
        if not (
            isinstance(entry, dict)
            and str(entry.get("path") or "").strip()
            and str(Path(entry["path"]).expanduser().resolve()) == resolved
        )
    ]

    if len(raw) == original_len:
        return False

    settings["shared_workspaces"] = raw
    save_settings(settings)
    return True


def _path_is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def user_workspace_context(user: dict | None) -> dict:
    if not user:
        return {"personal_workspace": None, "shared_rules": get_shared_workspace_rules()}
    username = validate_username(user.get("username") or "")
    personal = Path(ensure_personal_workspace(username))
    return {
        "personal_workspace": personal.resolve(),
        "shared_rules": get_shared_workspace_rules(),
    }


def is_workspace_allowed_for_user(
    candidate: Path,
    user: dict | None,
    *,
    write: bool = False,
) -> bool:
    if user is None:
        return True
    ctx = user_workspace_context(user)
    personal = ctx.get("personal_workspace")
    if isinstance(personal, Path) and _path_is_within(candidate, personal):
        return True
    for rule in ctx.get("shared_rules", []):
        try:
            root = Path(rule["path"]).resolve()
        except Exception:
            continue
        if not _path_is_within(candidate, root):
            continue
        mode = str(rule.get("mode") or "read_write")
        if write and mode == "read_only":
            return False
        return True
    return False
