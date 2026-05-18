import types
from urllib.parse import urlparse

import api.routes as routes


def _handler():
    return types.SimpleNamespace(current_user=None)


def test_handle_list_dir_without_workspace_path_keeps_session_workspace(monkeypatch):
    monkeypatch.setattr(routes, "_require_scope", lambda handler, scope: None)
    monkeypatch.setattr(routes, "_ensure_session_workspace_allowed", lambda handler, s, write=False: None)
    monkeypatch.setattr(routes, "get_session", lambda sid: types.SimpleNamespace(workspace="/tmp/ws-session"))
    monkeypatch.setattr(routes, "list_dir", lambda workspace, rel: [{"path": rel, "root": str(workspace)}])
    monkeypatch.setattr(routes, "j", lambda handler, payload, status=200: (payload, status))

    payload, status = routes._handle_list_dir(_handler(), urlparse("/api/list?session_id=s1&path=."))
    assert status == 200
    assert payload["entries"][0]["root"] == "/tmp/ws-session"


def test_handle_list_dir_workspace_path_overrides_workspace(monkeypatch):
    monkeypatch.setattr(routes, "_require_scope", lambda handler, scope: None)
    monkeypatch.setattr(routes, "_ensure_session_workspace_allowed", lambda handler, s, write=False: None)
    monkeypatch.setattr(routes, "get_session", lambda sid: types.SimpleNamespace(workspace="/tmp/ws-session"))
    monkeypatch.setattr(routes, "resolve_trusted_workspace", lambda path: "/tmp/ws-selected")
    monkeypatch.setattr(routes, "list_dir", lambda workspace, rel: [{"path": rel, "root": str(workspace)}])
    monkeypatch.setattr(routes, "j", lambda handler, payload, status=200: (payload, status))

    payload, status = routes._handle_list_dir(
        _handler(),
        urlparse("/api/list?session_id=s1&workspace_path=/tmp/ws-selected&path=sub"),
    )
    assert status == 200
    assert payload["entries"][0]["root"] == "/tmp/ws-selected"


def test_handle_list_dir_workspace_path_rejected_when_untrusted(monkeypatch):
    monkeypatch.setattr(routes, "_require_scope", lambda handler, scope: None)
    monkeypatch.setattr(routes, "_ensure_session_workspace_allowed", lambda handler, s, write=False: None)
    monkeypatch.setattr(routes, "get_session", lambda sid: types.SimpleNamespace(workspace="/tmp/ws-session"))
    monkeypatch.setattr(routes, "resolve_trusted_workspace", lambda path: (_ for _ in ()).throw(ValueError("blocked")))
    monkeypatch.setattr(routes, "bad", lambda handler, msg, status=400: (msg, status))

    msg, status = routes._handle_list_dir(
        _handler(),
        urlparse("/api/list?session_id=s1&workspace_path=/etc&path=."),
    )
    assert status == 404
    assert "blocked" in msg
