"""Regression coverage for WebUI Hermes skill slash expansion."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("yaml")


def _write_skill(root: Path, dirname: str, name: str, body: str = "Follow this test skill.") -> None:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill {name}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_runtime_skill_expansion_uses_first_slash_token_and_passes_args(tmp_path, monkeypatch):
    from api.streaming import _expand_skill_slash_command_for_agent

    profile_home = tmp_path / "hermes-home"
    skills_dir = profile_home / "skills"
    _write_skill(skills_dir, "codex", "codex", "Inspect carefully.")

    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    expanded = _expand_skill_slash_command_for_agent(
        "/codex inspect this",
        session_id="session-123",
        hermes_home=str(profile_home),
        skills_dir=skills_dir,
    )

    assert "[IMPORTANT: The user has invoked" in expanded
    assert '"codex" skill' in expanded
    assert "Inspect carefully." in expanded
    assert "inspect this" in expanded


def test_runtime_skill_expansion_uses_profile_skills_not_shared_skills(tmp_path, monkeypatch):
    from api.streaming import _expand_skill_slash_command_for_agent

    profile_home = tmp_path / "hermes-home"
    profile_skills = profile_home / "skills"
    shared_skills = tmp_path / "shared_skills"
    _write_skill(profile_skills, "dogfood", "dogfood", "Profile skill content.")
    shared_skills.mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    expanded = _expand_skill_slash_command_for_agent(
        "/dogfood test",
        session_id="session-456",
        hermes_home=str(profile_home),
        skills_dir=profile_skills,
    )

    assert "[IMPORTANT: The user has invoked" in expanded
    assert "Profile skill content." in expanded
    assert "test" in expanded


def test_runtime_skill_expansion_supports_command_without_args(tmp_path, monkeypatch):
    from api.streaming import _expand_skill_slash_command_for_agent

    profile_home = tmp_path / "hermes-home"
    skills_dir = profile_home / "skills"
    _write_skill(skills_dir, "solo-skill", "solo skill", "No args skill body.")

    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    expanded = _expand_skill_slash_command_for_agent(
        "/solo-skill",
        session_id="session-789",
        hermes_home=str(profile_home),
        skills_dir=skills_dir,
    )

    assert "[IMPORTANT: The user has invoked" in expanded
    assert "No args skill body." in expanded


def test_unknown_runtime_skill_is_preserved_and_logged(tmp_path, monkeypatch, caplog):
    from api.streaming import _expand_skill_slash_command_for_agent

    profile_home = tmp_path / "hermes-home"
    skills_dir = profile_home / "skills"
    skills_dir.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    original = "/unknown-skill args"
    expanded = _expand_skill_slash_command_for_agent(
        original,
        session_id="session-missing",
        hermes_home=str(profile_home),
        skills_dir=skills_dir,
    )

    assert expanded == original
    assert "Skill slash command not found" in caplog.text
    assert "unknown-skill" in caplog.text


def test_runtime_skills_dir_matches_cli_profile_home_in_multi_user_mode(tmp_path, monkeypatch):
    from api.streaming import _resolve_skills_dir

    profile_home = tmp_path / "hermes-home"
    shared = tmp_path / "shared_skills"
    shared.mkdir()

    monkeypatch.setattr("api.users.is_multi_user_mode", lambda: True)
    monkeypatch.setattr("api.users.get_shared_skills_dir", lambda: shared)

    assert _resolve_skills_dir(str(profile_home)) == profile_home / "skills"
