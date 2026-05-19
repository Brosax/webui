"""Regression coverage for WebUI Hermes skill slash runtime context."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("yaml")


def test_runtime_skills_dir_uses_global_home_skills_in_multi_user_mode(tmp_path, monkeypatch):
    from api.streaming import _resolve_skills_dir

    profile_home = tmp_path / "hermes-home"
    shared = tmp_path / "shared_skills"
    shared.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    monkeypatch.setattr("api.users.is_multi_user_mode", lambda: True)
    monkeypatch.setattr("api.users.get_shared_skills_dir", lambda: shared)

    assert _resolve_skills_dir(str(profile_home)) == tmp_path / "home" / ".hermes" / "skills"


def test_agent_thread_env_marks_webui_session_and_profile_home(tmp_path):
    from api.streaming import _build_agent_thread_env

    profile_home = tmp_path / "hermes-home"
    workspace = tmp_path / "workspace"
    env = _build_agent_thread_env(
        {"TERMINAL_CWD": "/from/profile", "CUSTOM_PROFILE_VALUE": "1"},
        str(workspace),
        "session-123",
        str(profile_home),
    )

    assert env["TERMINAL_CWD"] == str(workspace)
    assert env["HERMES_EXEC_ASK"] == "1"
    assert env["HERMES_SESSION_KEY"] == "session-123"
    assert env["HERMES_SESSION_ID"] == "session-123"
    assert env["HERMES_SESSION_PLATFORM"] == "webui"
    assert env["HERMES_HOME"] == str(profile_home)
    assert env["CUSTOM_PROFILE_VALUE"] == "1"


def test_skill_module_patch_uses_global_home_skills_dir(tmp_path, monkeypatch):
    from api.streaming import _patch_skill_tool_modules_for_agent

    profile_home = tmp_path / "hermes-home"
    skills_dir = tmp_path / "home" / ".hermes" / "skills"
    skills_tool = SimpleNamespace()
    skill_manager_tool = SimpleNamespace()

    def fail_profiles_patch(*_args, **_kwargs):
        raise RuntimeError("force fallback path")

    monkeypatch.setattr("api.profiles.patch_skill_home_modules", fail_profiles_patch)

    _patch_skill_tool_modules_for_agent(
        str(profile_home),
        skills_dir,
        modules=(skills_tool, skill_manager_tool),
    )

    assert skills_tool.HERMES_HOME == Path(profile_home)
    assert skills_tool.SKILLS_DIR == skills_dir
    assert skill_manager_tool.HERMES_HOME == Path(profile_home)
    assert skill_manager_tool.SKILLS_DIR == skills_dir


def test_webui_no_longer_expands_skill_slash_commands_before_agent_run():
    import api.streaming as streaming

    assert not hasattr(streaming, "_expand_skill_slash_command_for_agent")
