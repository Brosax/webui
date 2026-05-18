import types
from pathlib import Path

import api.routes as routes

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static" / "index.html"
PANELS_JS = ROOT / "static" / "panels.js"
STYLE_CSS = ROOT / "static" / "style.css"
I18N_JS = ROOT / "static" / "i18n.js"


def _handler():
    return types.SimpleNamespace(current_user=None)


def test_workspace_active_endpoint_persists_existing_workspace_without_session(monkeypatch):
    calls = []
    monkeypatch.setattr(routes, "_require_scope", lambda handler, scope: None)
    monkeypatch.setattr(routes, "resolve_trusted_workspace", lambda path: str(Path(path)))
    monkeypatch.setattr(routes, "set_last_workspace", lambda path: calls.append(path))
    monkeypatch.setattr(routes, "load_workspaces", lambda: [{"path": "/tmp/a", "name": "A"}])
    monkeypatch.setattr(routes, "j", lambda handler, payload, status=200: (payload, status))

    payload, status = routes._handle_workspace_active(_handler(), {"path": "/tmp/a"})

    assert status == 200
    assert payload == {"ok": True, "last": "/tmp/a", "workspace": {"path": "/tmp/a", "name": "A"}}
    assert calls == ["/tmp/a"]


def test_workspace_active_endpoint_rejects_unknown_workspace(monkeypatch):
    monkeypatch.setattr(routes, "_require_scope", lambda handler, scope: None)
    monkeypatch.setattr(routes, "resolve_trusted_workspace", lambda path: str(Path(path)))
    monkeypatch.setattr(routes, "load_workspaces", lambda: [{"path": "/tmp/a", "name": "A"}])
    monkeypatch.setattr(routes, "bad", lambda handler, msg, status=400: (msg, status))

    msg, status = routes._handle_workspace_active(_handler(), {"path": "/tmp/missing"})

    assert status == 404
    assert "Workspace not found" in msg


def test_titlebar_contains_user_and_global_workspace_controls():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="titlebarWorkspaceChip"' in html
    assert 'id="titlebarWorkspaceDropdown"' in html
    assert 'id="titlebarUserChip"' in html
    assert 'id="titlebarUserMenu"' in html


def test_titlebar_js_uses_active_workspace_endpoint_and_empty_session_rule():
    js = PANELS_JS.read_text(encoding="utf-8")

    assert "/api/workspaces/active" in js
    assert "function isCurrentSessionBlankForGlobalWorkspace" in js
    assert "applyGlobalWorkspaceSelection" in js
    assert "S._profileDefaultWorkspace" in js
    assert "hasPersistedSessionContent" in js


def test_titlebar_i18n_keys_exist_for_required_locales():
    body = I18N_JS.read_text(encoding="utf-8")
    for key in (
        "titlebar_global_workspace",
        "titlebar_local_user",
        "titlebar_user_settings",
        "titlebar_logout",
        "titlebar_running_chats_keep_workspace",
    ):
        assert body.count(f"{key}:") >= 3, f"missing i18n key in en/zh/es: {key}"


def test_titlebar_css_classes_exist():
    css = STYLE_CSS.read_text(encoding="utf-8")
    for cls in (
        ".titlebar-workspace-chip",
        ".titlebar-user-chip",
        ".titlebar-menu",
        ".titlebar-avatar",
    ):
        assert cls in css
    assert "-webkit-app-region:no-drag" in css
