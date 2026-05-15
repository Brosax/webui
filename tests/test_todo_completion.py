import json
from pathlib import Path

import api.models as models
from api.models import Session
from api.routes import (
    _apply_todo_overrides,
    _latest_todo_state_from_messages,
    _todo_source_fingerprint,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PANELS_JS = (REPO_ROOT / "static" / "panels.js").read_text(encoding="utf-8")
SESSIONS_JS = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
STYLE_CSS = (REPO_ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_session_persists_todo_overrides(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", session_dir / "_index.json")
    models.SESSIONS.clear()

    session = Session(
        session_id="todo_state",
        messages=[{"role": "user", "content": "hi"}],
        todo_overrides={
            "source_fingerprint": "abc",
            "items": {"t1": {"status": "completed", "updated_at": 123}},
        },
    )
    session.save()

    loaded = Session.load("todo_state")
    assert loaded.todo_overrides["items"]["t1"]["status"] == "completed"
    assert loaded.compact()["todo_overrides"]["source_fingerprint"] == "abc"


def test_latest_todo_state_uses_most_recent_tool_payload():
    old = {"todos": [{"id": "old", "content": "Old task", "status": "pending"}]}
    new = {"todos": [{"id": "new", "content": "New task", "status": "pending"}]}
    result = _latest_todo_state_from_messages(
        [
            {"role": "tool", "content": json.dumps(old)},
            {"role": "assistant", "content": "ok"},
            {"role": "tool", "content": json.dumps(new)},
        ]
    )

    assert result is not None
    _, todos = result
    assert todos[0]["id"] == "new"


def test_todo_overrides_apply_only_to_matching_fingerprint():
    todos = [{"id": "t1", "content": "Ship it", "status": "pending"}]
    fingerprint = _todo_source_fingerprint(todos)
    overrides = {
        "source_fingerprint": fingerprint,
        "items": {"t1": {"status": "completed", "updated_at": 123}},
    }

    assert _apply_todo_overrides(todos, overrides, fingerprint)[0]["status"] == "completed"
    assert _apply_todo_overrides(todos, {**overrides, "source_fingerprint": "stale"}, fingerprint)[0]["status"] == "pending"


def test_todo_panel_has_click_completion_api():
    assert "async function toggleTodoStatus(todoId)" in PANELS_JS
    assert "method: 'PATCH'" in PANELS_JS
    assert "/api/session/todos" in PANELS_JS
    assert "data-todo-id" in PANELS_JS
    assert "todo_overrides" in PANELS_JS
    assert "S.session._todo_message_count = (S.messages || []).length" in PANELS_JS


def test_session_load_preserves_effective_todos_from_api():
    assert "S.session.todos=data.session.todos" in SESSIONS_JS
    assert "S.session.todo_overrides=data.session.todo_overrides" in SESSIONS_JS
    assert "S.session._todo_message_count=msgs.length" in SESSIONS_JS


def test_todo_panel_styles_present():
    for selector in [".todo-item", ".todo-toggle", ".todo-content", ".todo-meta", ".todo-status-completed"]:
        assert selector in STYLE_CSS
