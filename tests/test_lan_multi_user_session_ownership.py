"""Regression tests for LAN multi-user session/profile ownership."""

import pathlib
import uuid

import pytest


REPO = pathlib.Path(__file__).parent.parent
ROUTES = (REPO / "api" / "routes.py").read_text(encoding="utf-8")
SESSIONS_JS = (REPO / "static" / "sessions.js").read_text(encoding="utf-8")
BOOT_JS = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
COMMANDS_JS = (REPO / "static" / "commands.js").read_text(encoding="utf-8")
MESSAGES_JS = (REPO / "static" / "messages.js").read_text(encoding="utf-8")


def _session_new_route_block() -> str:
    marker = 'if parsed.path == "/api/session/new":'
    start = ROUTES.find(marker)
    assert start != -1, "/api/session/new route not found"
    end = ROUTES.find('if parsed.path == "/api/session/duplicate":', start)
    assert end > start, "/api/session/new route block end not found"
    return ROUTES[start:end]


def _load_session_error_block() -> str:
    start = SESSIONS_JS.find("data = await api(`/api/session?")
    assert start != -1, "loadSession metadata request not found"
    catch_idx = SESSIONS_JS.find("} catch(e) {", start)
    assert catch_idx > start, "loadSession metadata catch block not found"
    end = SESSIONS_JS.find("return;", catch_idx)
    assert end > catch_idx, "loadSession metadata catch return not found"
    return SESSIONS_JS[catch_idx:end]


@pytest.fixture(autouse=True)
def _clear_request_user():
    from api import auth

    auth.clear_current_user()
    yield
    auth.clear_current_user()


@pytest.fixture
def clean_sessions():
    from api import models

    with models.LOCK:
        models.SESSIONS.clear()
    yield
    with models.LOCK:
        models.SESSIONS.clear()


def _request_as(profile_name: str, username: str | None = None) -> None:
    from api import auth

    user = {
        "id": 100,
        "username": username or profile_name,
        "display_name": username or profile_name,
        "role": "user",
        "status": "active",
        "profile_name": profile_name,
    }
    auth._set_current_user(type("DummyHandler", (), {})(), user)


def _sid() -> str:
    return f"t_{uuid.uuid4().hex[:10]}"


def test_get_session_reloads_disk_when_cached_owner_is_stale(clean_sessions):
    from api import models

    sid = _sid()
    disk_session = models.Session(session_id=sid, title="Disk", profile="alice")
    disk_session.messages = [{"role": "user", "content": "owned by alice"}]
    disk_session.save()

    stale_cached = models.Session(session_id=sid, title="Stale", profile="bob")
    with models.LOCK:
        models.SESSIONS[sid] = stale_cached

    try:
        _request_as("alice")

        loaded = models.get_session(sid)

        assert loaded.profile == "alice"
        assert loaded.title == "Disk"
        with models.LOCK:
            assert models.SESSIONS[sid] is loaded
    finally:
        disk_session.path.unlink(missing_ok=True)


def test_get_session_keeps_cross_user_access_hidden_after_disk_reload(clean_sessions):
    from api import models

    sid = _sid()
    disk_session = models.Session(session_id=sid, title="Alice only", profile="alice")
    disk_session.save()

    stale_cached = models.Session(session_id=sid, title="Wrong cache", profile="bob")
    with models.LOCK:
        models.SESSIONS[sid] = stale_cached

    try:
        _request_as("charlie")

        with pytest.raises(KeyError):
            models.get_session(sid)
    finally:
        disk_session.path.unlink(missing_ok=True)


def test_multi_user_session_new_uses_authenticated_profile_not_threadlocal_fallback():
    block = _session_new_route_block()

    assert "current_user = _current_user(handler)" in block
    assert "current_profile" in block
    assert 'current_user.get("profile_name")' in block
    assert "profile=(current_profile if is_multi_user_mode()" in block
    assert "profile=None if is_multi_user_mode()" not in block


def test_active_session_storage_is_account_scoped():
    assert "const ACTIVE_SESSION_STORAGE_PREFIX='hermes-webui-session:'" in SESSIONS_JS
    assert "function activeSessionStorageKey" in SESSIONS_JS
    assert "function getSavedActiveSessionId" in SESSIONS_JS
    assert "function setSavedActiveSessionId" in SESSIONS_JS
    assert "function removeSavedActiveSessionId" in SESSIONS_JS


def test_frontend_does_not_use_legacy_global_session_storage_key_directly():
    legacy_calls = (
        "localStorage.getItem('hermes-webui-session')",
        'localStorage.getItem("hermes-webui-session")',
        "localStorage.setItem('hermes-webui-session'",
        'localStorage.setItem("hermes-webui-session"',
        "localStorage.removeItem('hermes-webui-session')",
        'localStorage.removeItem("hermes-webui-session")',
    )
    for name, src in {
        "boot.js": BOOT_JS,
        "commands.js": COMMANDS_JS,
        "messages.js": MESSAGES_JS,
        "sessions.js": SESSIONS_JS,
    }.items():
        for call in legacy_calls:
            assert call not in src, f"{name} must use account-scoped session storage helpers"


def test_boot_reads_auth_status_before_restoring_scoped_saved_session():
    auth_idx = BOOT_JS.find("const _bootAuthStatus=await api('/api/auth/status')")
    saved_idx = BOOT_JS.find("const savedLocal=getSavedActiveSessionId")

    assert auth_idx != -1, "boot must read /api/auth/status before session restore"
    assert saved_idx != -1, "boot must restore from the account-scoped session key"
    assert auth_idx < saved_idx
    assert "const savedProfile=" in BOOT_JS
    assert "getSavedActiveSessionId(savedProfile)" in BOOT_JS


def test_load_session_404_clears_only_current_account_key():
    block = _load_session_error_block()

    assert "getSavedActiveSessionId()===sid" in block
    assert "removeSavedActiveSessionId()" in block
    assert "localStorage.removeItem('hermes-webui-session')" not in block
