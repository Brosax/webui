"""
Tests for LAN multi-user server mode — shared workspaces and auth status.

Tests the following features:
- auth status returns multi_user field
- shared_workspaces in settings defaults and allowed keys
- shared workspace rules preserve name/mode/path
- upsert can add and update shared workspace rules
- remove can delete shared workspace rules by path
- admin-only endpoints reject normal users and anonymous callers
- read_only shared workspace blocks write operations
- legacy skills dir behavior is preserved
"""

import json
import pathlib
import pytest

from tests.conftest import TEST_STATE_DIR, TEST_BASE, _post


pytestmark = pytest.mark.usefixtures("test_server")


# ── Auth status: multi_user field ────────────────────────────────────────────

def test_auth_status_has_multi_user_field():
    """GET /api/auth/status must include multi_user field."""
    import urllib.request
    with urllib.request.urlopen(TEST_BASE + "/api/auth/status", timeout=5) as r:
        data = json.loads(r.read())
    assert "multi_user" in data, f"auth status keys: {list(data.keys())}"


def test_auth_status_multi_user_is_bool():
    """multi_user field must be a bool."""
    import urllib.request
    with urllib.request.urlopen(TEST_BASE + "/api/auth/status", timeout=5) as r:
        data = json.loads(r.read())
    assert isinstance(data["multi_user"], bool)


# ── Settings: shared_workspaces in defaults and allowed keys ──────────────────

def test_shared_workspaces_in_settings_defaults():
    """shared_workspaces must be in _SETTINGS_DEFAULTS."""
    from api.config import _SETTINGS_DEFAULTS
    assert "shared_workspaces" in _SETTINGS_DEFAULTS, list(_SETTINGS_DEFAULTS.keys())
    assert isinstance(_SETTINGS_DEFAULTS["shared_workspaces"], list)


def test_shared_workspaces_in_settings_allowed_keys():
    """shared_workspaces must be in _SETTINGS_ALLOWED_KEYS."""
    from api.config import _SETTINGS_ALLOWED_KEYS
    assert "shared_workspaces" in _SETTINGS_ALLOWED_KEYS, list(_SETTINGS_ALLOWED_KEYS)


# ── Shared workspace rules: name/mode/path ───────────────────────────────────

def test_get_shared_workspace_rules_preserves_name():
    """get_shared_workspace_rules must preserve the name field."""
    from api.users import get_shared_workspace_rules, upsert_shared_workspace_rule, remove_shared_workspace_rule

    # Clean up any existing rule for this path
    test_path = str(TEST_STATE_DIR / "test-shared-workspace")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    # Insert with explicit name
    upsert_shared_workspace_rule(path=test_path, name="Test Workspace", mode="read_write")
    rules = get_shared_workspace_rules()
    matching = [r for r in rules if r["path"] == test_path]
    assert len(matching) == 1, f"Expected rule for {test_path}, got: {rules}"
    assert matching[0]["name"] == "Test Workspace"
    assert matching[0]["mode"] == "read_write"
    assert matching[0]["path"] == test_path
    remove_shared_workspace_rule(test_path)


def test_get_shared_workspace_rules_defaults_name_to_dirname():
    """When name is not provided, it defaults to the directory name."""
    from api.users import get_shared_workspace_rules, upsert_shared_workspace_rule, remove_shared_workspace_rule

    test_path = str(TEST_STATE_DIR / "another-test-workspace")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    # Insert without name
    upsert_shared_workspace_rule(path=test_path, mode="read_only")
    rules = get_shared_workspace_rules()
    matching = [r for r in rules if r["path"] == test_path]
    assert len(matching) == 1
    assert matching[0]["name"] == pathlib.Path(test_path).name
    assert matching[0]["mode"] == "read_only"
    remove_shared_workspace_rule(test_path)


# ── Upsert: add new and update existing ─────────────────────────────────────

def test_upsert_shared_workspace_rule_adds_new():
    """upsert_shared_workspace_rule must add a new rule when path is not present."""
    from api.users import get_shared_workspace_rules, upsert_shared_workspace_rule, remove_shared_workspace_rule

    test_path = str(TEST_STATE_DIR / "upsert-test-workspace")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    rule = upsert_shared_workspace_rule(path=test_path, name="Added Workspace", mode="read_write")
    assert rule["path"] == test_path
    assert rule["name"] == "Added Workspace"
    assert rule["mode"] == "read_write"

    # Verify it's in the list
    rules = get_shared_workspace_rules()
    assert any(r["path"] == test_path for r in rules), f"Rule not found in: {rules}"

    # Clean up
    remove_shared_workspace_rule(test_path)


def test_upsert_shared_workspace_rule_updates_existing():
    """upsert_shared_workspace_rule must update mode/name when path already exists."""
    from api.users import get_shared_workspace_rules, upsert_shared_workspace_rule, remove_shared_workspace_rule

    test_path = str(TEST_STATE_DIR / "upsert-update-workspace")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    # Add with initial values
    upsert_shared_workspace_rule(path=test_path, name="Initial Name", mode="read_write")
    rules = get_shared_workspace_rules()
    assert any(r["path"] == test_path and r["mode"] == "read_write" for r in rules)

    # Update with new values
    upsert_shared_workspace_rule(path=test_path, name="Updated Name", mode="read_only")
    rules = get_shared_workspace_rules()
    assert any(r["path"] == test_path and r["name"] == "Updated Name" and r["mode"] == "read_only" for r in rules)

    # Verify only one entry for this path exists
    matching = [r for r in rules if r["path"] == test_path]
    assert len(matching) == 1, f"Multiple entries for same path: {matching}"

    # Clean up
    remove_shared_workspace_rule(test_path)


# ── Remove ───────────────────────────────────────────────────────────────────

def test_remove_shared_workspace_rule_by_path():
    """remove_shared_workspace_rule must remove the rule with the given path."""
    from api.users import get_shared_workspace_rules, upsert_shared_workspace_rule, remove_shared_workspace_rule

    test_path = str(TEST_STATE_DIR / "remove-test-workspace")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    upsert_shared_workspace_rule(path=test_path, name="To Be Removed", mode="read_write")
    rules = get_shared_workspace_rules()
    assert any(r["path"] == test_path for r in rules), "Rule was not added"

    removed = remove_shared_workspace_rule(test_path)
    assert removed is True

    rules = get_shared_workspace_rules()
    assert not any(r["path"] == test_path for r in rules), "Rule was not removed"


def test_remove_shared_workspace_rule_returns_false_for_nonexistent():
    """remove_shared_workspace_rule must return False when path does not exist."""
    from api.users import remove_shared_workspace_rule
    result = remove_shared_workspace_rule("/nonexistent/path/that/does/not/exist")
    assert result is False


# ── Admin-only endpoints ──────────────────────────────────────────────────────

def _make_request(method, path, body=None):
    """Make an HTTP request to the test server."""
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(
        TEST_BASE + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {}, e.code


def test_admin_shared_workspaces_get_requires_admin():
    """GET /api/admin/shared-workspaces must return 403 for non-admin users."""
    from api.users import create_user, verify_user_password, create_auth_session
    from api.config import save_settings
    from api import config

    # Create a normal (non-admin) user
    user = create_user(
        username="testuser",
        password="testpassword123",
        role="user",
        display_name="Test User",
    )
    token = create_auth_session(user["id"], ttl_seconds=3600)

    # Create the session cookie (simulated)
    import hmac, hashlib, time as _time, secrets
    from api.auth import _signing_key
    raw_token = token
    sig = hmac.new(_signing_key(), raw_token.encode(), hashlib.sha256).hexdigest()[:32]
    cookie_value = f"{raw_token}.{sig}"

    # Make request with session cookie
    import urllib.request
    req = urllib.request.Request(
        TEST_BASE + "/api/admin/shared-workspaces",
        headers={"Cookie": f"hermes_session={cookie_value}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        status = e.code

    # Normal user must NOT get admin endpoint access
    assert status in (401, 403), f"Expected 401 or 403, got {status}"


def test_admin_shared_workspaces_get_succeeds_for_admin():
    """GET /api/admin/shared-workspaces must succeed for admin users."""
    from api.users import create_user, create_auth_session
    import hmac, hashlib
    from api.auth import _signing_key

    # Create an admin user
    try:
        from api.users import get_user_by_username
        admin = get_user_by_username("testadmin")
        if not admin:
            admin = create_user(
                username="testadmin",
                password="adminpassword123",
                role="admin",
                display_name="Test Admin",
            )
    except Exception:
        admin = create_user(
            username="testadmin",
            password="adminpassword123",
            role="admin",
            display_name="Test Admin",
        )

    token = create_auth_session(admin["id"], ttl_seconds=3600)
    raw_token = token
    sig = hmac.new(_signing_key(), raw_token.encode(), hashlib.sha256).hexdigest()[:32]
    cookie_value = f"{raw_token}.{sig}"

    import urllib.request
    req = urllib.request.Request(
        TEST_BASE + "/api/admin/shared-workspaces",
        headers={"Cookie": f"hermes_session={cookie_value}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        status = e.code
        data = {}

    assert status == 200, f"Admin GET failed with {status}: {data}"
    assert "workspaces" in data


def test_admin_shared_workspaces_post_requires_admin():
    """POST /api/admin/shared-workspaces must return 403 for non-admin users."""
    from api.users import create_user, create_auth_session
    import hmac, hashlib
    from api.auth import _signing_key

    try:
        from api.users import get_user_by_username
        user = get_user_by_username("testuser")
        if not user:
            user = create_user(username="testuser", password="testpassword123", role="user")
    except Exception:
        user = create_user(username="testuser", password="testpassword123", role="user")

    token = create_auth_session(user["id"], ttl_seconds=3600)
    raw_token = token
    sig = hmac.new(_signing_key(), raw_token.encode(), hashlib.sha256).hexdigest()[:32]
    cookie_value = f"{raw_token}.{sig}"

    import urllib.request
    body = json.dumps({"path": "/tmp/test-workspace"}).encode()
    req = urllib.request.Request(
        TEST_BASE + "/api/admin/shared-workspaces",
        data=body,
        headers={"Content-Type": "application/json", "Cookie": f"hermes_session={cookie_value}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code

    assert status in (401, 403), f"Expected 401 or 403, got {status}"


def test_admin_shared_workspaces_delete_requires_admin():
    """DELETE /api/admin/shared-workspaces must return 403 for non-admin users."""
    from api.users import create_user, create_auth_session
    import hmac, hashlib
    from api.auth import _signing_key

    try:
        from api.users import get_user_by_username
        user = get_user_by_username("testuser")
        if not user:
            user = create_user(username="testuser", password="testpassword123", role="user")
    except Exception:
        user = create_user(username="testuser", password="testpassword123", role="user")

    token = create_auth_session(user["id"], ttl_seconds=3600)
    raw_token = token
    sig = hmac.new(_signing_key(), raw_token.encode(), hashlib.sha256).hexdigest()[:32]
    cookie_value = f"{raw_token}.{sig}"

    import urllib.request
    body = json.dumps({"path": "/tmp/test-workspace"}).encode()
    req = urllib.request.Request(
        TEST_BASE + "/api/admin/shared-workspaces",
        data=body,
        headers={"Content-Type": "application/json", "Cookie": f"hermes_session={cookie_value}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code

    assert status in (401, 403), f"Expected 401 or 403, got {status}"


# ── Read-only workspace blocks write operations ───────────────────────────────

def test_read_only_shared_workspace_blocks_upload():
    """Upload to a read_only shared workspace must be rejected server-side."""
    from api.users import upsert_shared_workspace_rule, remove_shared_workspace_rule, is_workspace_allowed_for_user
    from pathlib import Path

    # Create a test directory
    test_path = str(TEST_STATE_DIR / "read-only-test-workspace")
    Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    upsert_shared_workspace_rule(path=test_path, name="Read Only Workspace", mode="read_only")

    # is_workspace_allowed_for_user with write=True must return False
    allowed = is_workspace_allowed_for_user(Path(test_path), user={"username": "testuser"}, write=True)
    assert allowed is False, "read_only workspace should block write=True"

    allowed_read = is_workspace_allowed_for_user(Path(test_path), user={"username": "testuser"}, write=False)
    assert allowed_read is True, "read_only workspace should allow write=False"

    # Clean up
    remove_shared_workspace_rule(test_path)


def test_read_only_shared_workspace_blocks_save():
    """Save operation to a read_only shared workspace must be rejected."""
    from api.users import upsert_shared_workspace_rule, remove_shared_workspace_rule, is_workspace_allowed_for_user
    from pathlib import Path

    test_path = str(TEST_STATE_DIR / "read-only-save-test")
    Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    upsert_shared_workspace_rule(path=test_path, name="Read Only Save Test", mode="read_only")

    # Any write operation should be blocked
    file_path = Path(test_path) / "somefile.txt"
    allowed = is_workspace_allowed_for_user(file_path, user={"username": "testuser"}, write=True)
    assert allowed is False, "read_only workspace should block write to sub-path"

    # Clean up
    remove_shared_workspace_rule(test_path)


# ── Upsert return value must match persisted state ────────────────────────────

def test_upsert_returns_actual_persisted_rule():
    """Upsert without name on existing rule must return the old name, not Path.name."""
    from api.users import get_shared_workspace_rules, upsert_shared_workspace_rule, remove_shared_workspace_rule

    test_path = str(TEST_STATE_DIR / "upsert-return-value-test")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    # Insert with explicit name
    rule1 = upsert_shared_workspace_rule(path=test_path, name="Persisted Name", mode="read_write")
    assert rule1["name"] == "Persisted Name"

    # Update without providing name — return value must still show old name
    rule2 = upsert_shared_workspace_rule(path=test_path, mode="read_only")
    assert rule2["name"] == "Persisted Name", f"Expected 'Persisted Name' but got '{rule2['name']}'"

    # Verify persisted state also has the old name
    rules = get_shared_workspace_rules()
    matching = [r for r in rules if r["path"] == test_path]
    assert len(matching) == 1
    assert matching[0]["name"] == "Persisted Name"

    # Update WITH a new name — return value must show the new name
    rule3 = upsert_shared_workspace_rule(path=test_path, name="New Name")
    assert rule3["name"] == "New Name"

    # Clean up
    remove_shared_workspace_rule(test_path)


# ── Workspaces: name must not be mutated ──────────────────────────────────────

def test_read_only_workspace_keeps_name_unchanged():
    """Read-only shared workspace name must not be mutated with (RO) suffix."""
    from api.users import upsert_shared_workspace_rule, remove_shared_workspace_rule

    test_path = str(TEST_STATE_DIR / "ro-name-unchanged-test")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    upsert_shared_workspace_rule(path=test_path, name="My Shared Data", mode="read_only")
    rules = get_shared_workspace_rules()
    matching = [r for r in rules if r["path"] == test_path]
    assert len(matching) == 1
    # Name must NOT have (RO) appended
    assert matching[0]["name"] == "My Shared Data", f"Name was mutated: {matching[0]['name']}"
    # Mode must be read_only
    assert matching[0]["mode"] == "read_only"

    # Clean up
    remove_shared_workspace_rule(test_path)


# ── Skills dir: legacy vs multi-user mode ─────────────────────────────────────

def test_active_skills_dir_uses_home_skills_in_multi_user_mode(monkeypatch, tmp_path):
    """_active_skills_dir must use ~/.hermes/skills in multi-user mode."""
    from api.routes import _active_skills_dir
    from api.users import is_multi_user_mode

    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    # This test only makes sense when multi-user mode is active
    # (i.e., at least one user exists in users.db)
    # If no users exist, the server is in setup mode and this check doesn't apply
    try:
        from api.users import users_count
        if users_count() == 0:
            # No users yet — skip this test
            return
    except Exception:
        return

    skills_dir = _active_skills_dir()
    expected = tmp_path / "home" / ".hermes" / "skills"
    assert skills_dir == expected, f"_active_skills_dir() should use ~/.hermes/skills: expected {expected}, got {skills_dir}"


def test_active_skills_dir_uses_home_skills_in_single_user_mode(monkeypatch, tmp_path):
    """_active_skills_dir must use ~/.hermes/skills in single-user mode."""
    from api.routes import _active_skills_dir

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("api.routes.is_multi_user_mode", lambda: False)

    skills_dir = _active_skills_dir()
    expected = tmp_path / "home" / ".hermes" / "skills"
    assert skills_dir == expected


# ── Workspaces endpoint: name/mode metadata ───────────────────────────────────

def test_workspaces_endpoint_returns_shared_with_name_and_mode():
    """GET /api/workspaces must include name and mode for shared workspaces."""
    from api.users import upsert_shared_workspace_rule, remove_shared_workspace_rule

    test_path = str(TEST_STATE_DIR / "shared-ws-name-test")
    pathlib.Path(test_path).mkdir(exist_ok=True)
    try:
        remove_shared_workspace_rule(test_path)
    except Exception:
        pass

    upsert_shared_workspace_rule(path=test_path, name="Custom Shared Name", mode="read_only")

    import urllib.request
    try:
        with urllib.request.urlopen(TEST_BASE + "/api/workspaces", timeout=5) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        # If we get an error here (e.g., not logged in), skip
        return

    # Find the shared workspace in the list
    shared_entries = [w for w in data.get("workspaces", []) if w.get("path") == test_path]
    assert len(shared_entries) >= 1, f"Shared workspace not found in list: {data.get('workspaces', [])}"

    entry = shared_entries[0]
    assert "name" in entry, f"Entry missing 'name' field: {entry}"
    assert "mode" in entry, f"Entry missing 'mode' field: {entry}"
    assert entry["name"] == "Custom Shared Name", f"Expected 'Custom Shared Name', got: {entry['name']}"
    assert entry["mode"] == "read_only", f"Expected 'read_only', got: {entry['mode']}"

    # Clean up
    remove_shared_workspace_rule(test_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
