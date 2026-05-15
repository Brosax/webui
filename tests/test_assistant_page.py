"""Regression coverage for the My Assistant aggregate page."""

from __future__ import annotations

import io
import json
import time
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class _JSONHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.response_headers = []
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.response_headers.append((key, value))

    def end_headers(self):
        pass


def _payload(handler):
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_assistant_profile_config_roundtrip(tmp_path, monkeypatch):
    import api.profiles as profiles
    import api.routes as routes

    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: tmp_path)

    handler = _JSONHandler()
    routes._handle_profile_config_write(
        handler,
        {"assistant": {"memory_injection": False, "default_deliver": "teams"}},
    )
    assert handler.status == 200
    body = _payload(handler)
    assert body["ok"] is True
    assert body["assistant"]["memory_injection"] is False
    assert body["assistant"]["default_deliver"] == "teams"

    config_text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "assistant:" in config_text
    assert "memory_injection: false" in config_text

    read_handler = _JSONHandler()
    routes._handle_profile_config_read(read_handler)
    read_body = _payload(read_handler)
    assert read_body["assistant"]["memory_injection"] is False
    assert read_body["assistant"]["default_deliver"] == "teams"


def test_assistant_cron_subprocess_injects_memory_into_prompt(tmp_path, monkeypatch):
    import api.profiles as profiles
    import api.routes as routes

    home = tmp_path / "home"
    memories = home / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("Remember the launch plan.", encoding="utf-8")
    (memories / "USER.md").write_text("Prefers short updates.", encoding="utf-8")

    captured = {}

    cron_pkg = types.ModuleType("cron")
    cron_pkg.__path__ = []
    cron_scheduler = types.ModuleType("cron.scheduler")
    cron_scheduler.run_job = lambda job: captured.setdefault("job", dict(job)) or {"ok": True}

    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: home)
    monkeypatch.setitem(sys.modules, "cron", cron_pkg)
    monkeypatch.setitem(sys.modules, "cron.scheduler", cron_scheduler)

    queue = types.SimpleNamespace(put=lambda item: captured.setdefault("result", item))
    routes._cron_job_subprocess_main(
        {
            "id": "assistant-job-1",
            "assistant_managed": True,
            "prompt": "Draft a Teams update.",
        },
        None,
        queue,
    )

    assert captured["result"][0] == "ok"
    prompt = captured["job"]["prompt"]
    assert "profile-bound assistant routine" in prompt
    assert "MEMORY.md" in prompt
    assert "USER.md" in prompt
    assert "Draft a Teams update." in prompt


def test_cron_create_and_update_pass_assistant_fields(monkeypatch):
    import api.routes as routes

    created = {}
    updated = []

    cron_pkg = types.ModuleType("cron")
    cron_pkg.__path__ = []
    cron_jobs = types.ModuleType("cron.jobs")

    def create_job(**kwargs):
        created["kwargs"] = kwargs
        return {"id": "job-a", "name": kwargs.get("name", ""), **kwargs}

    def update_job(job_id, updates):
        updated.append((job_id, updates))
        return {"id": job_id, "name": "Job A", **updates}

    cron_jobs.create_job = create_job
    cron_jobs.update_job = update_job
    monkeypatch.setitem(sys.modules, "cron", cron_pkg)
    monkeypatch.setitem(sys.modules, "cron.jobs", cron_jobs)

    create_handler = _JSONHandler()
    routes._handle_cron_create(
        create_handler,
        {
            "name": "Assistant draft",
            "prompt": "Do the thing",
            "schedule": "0 9 * * *",
            "deliver": "teams",
            "assistant_managed": True,
            "assistant_memory_injection": False,
        },
    )
    create_body = _payload(create_handler)
    assert create_handler.status == 200
    assert create_body["job"]["assistant_managed"] is True
    assert created["kwargs"]["assistant_managed"] is True
    assert created["kwargs"]["assistant_memory_injection"] is False

    update_handler = _JSONHandler()
    routes._handle_cron_update(
        update_handler,
        {
            "job_id": "job-a",
            "assistant_managed": False,
            "assistant_memory_injection": True,
        },
    )
    update_body = _payload(update_handler)
    assert update_handler.status == 200
    assert update_body["job"]["assistant_managed"] is False
    assert updated[0][1]["assistant_managed"] is False
    assert updated[0][1]["assistant_memory_injection"] is True


def test_assistant_cockpit_builds_today_and_stale_drafts(tmp_path, monkeypatch):
    import api.profiles as profiles
    import api.routes as routes

    home = tmp_path / "home"
    memories = home / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("Focus on launch hygiene.", encoding="utf-8")
    (memories / "USER.md").write_text("Write concise updates.", encoding="utf-8")
    now = time.time()

    cron_pkg = types.ModuleType("cron")
    cron_pkg.__path__ = []
    cron_jobs = types.ModuleType("cron.jobs")
    cron_jobs.list_jobs = lambda include_disabled=True: [
        {
            "id": "job-1",
            "name": "Morning check",
            "assistant_managed": True,
            "enabled": True,
            "schedule": "0 9 * * *",
            "last_status": "success",
            "last_run_at": now - 1800,
        },
        {
            "id": "job-2",
            "name": "Weekly audit",
            "assistant_managed": True,
            "enabled": True,
            "schedule": "0 12 * * 1",
            "last_status": "failed",
            "last_run_at": now - (4 * 24 * 3600),
        },
    ]

    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: home)
    monkeypatch.setitem(sys.modules, "cron", cron_pkg)
    monkeypatch.setitem(sys.modules, "cron.jobs", cron_jobs)

    today_handler = _JSONHandler()
    routes._handle_assistant_cockpit(today_handler, types.SimpleNamespace(query="kind=today"))
    assert today_handler.status == 200
    today = _payload(today_handler)
    assert today["kind"] == "today"
    assert "Today Plan (Draft)" in today["text"]
    assert "Morning check" in today["text"]
    assert "Focus: Write concise updates." in today["text"]

    stale_handler = _JSONHandler()
    routes._handle_assistant_cockpit(stale_handler, types.SimpleNamespace(query="kind=stale"))
    assert stale_handler.status == 200
    stale = _payload(stale_handler)
    assert stale["kind"] == "stale"
    assert "Stale Routine Reminders" in stale["text"]
    assert "Weekly audit" in stale["text"]


def test_my_assistant_static_hooks_exist():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panels = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert 'data-panel="assistant"' in index
    assert 'id="mainAssistant"' in index
    assert "function loadAssistant(" in panels
    assert "function saveAssistantRoutine(" in panels
    assert "function saveAssistantConfig(" in panels
    assert "function generateAssistantCockpit(" in panels
    assert "function applyAssistantDraftToTeams(" in panels
    assert "assistantCockpitDraft" in index
    assert "assistantManaged" not in panels  # spelling should stay snake_case
    assert "showing-assistant" in css
