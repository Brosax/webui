"""Focused regressions for WebUI skill runtime path patching."""

from __future__ import annotations

import sys
import types
from pathlib import Path


def _install_fake_module(monkeypatch, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    parent_name, _, child_name = name.rpartition(".")
    if parent_name:
        parent = sys.modules.get(parent_name) or types.ModuleType(parent_name)
        monkeypatch.setitem(sys.modules, parent_name, parent)
        setattr(parent, child_name, module)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_set_hermes_home_patches_both_skill_tool_modules(tmp_path, monkeypatch):
    from api import profiles

    skills_tool = _install_fake_module(monkeypatch, "tools.skills_tool")
    manager_tool = _install_fake_module(monkeypatch, "tools.skill_manager_tool")

    profiles._set_hermes_home(tmp_path)

    assert skills_tool.HERMES_HOME == tmp_path
    assert skills_tool.SKILLS_DIR == tmp_path / "skills"
    assert manager_tool.HERMES_HOME == tmp_path
    assert manager_tool.SKILLS_DIR == tmp_path / "skills"


def test_skill_home_snapshot_restore_prevents_temporary_patch_leak(tmp_path, monkeypatch):
    from api.profiles import (
        patch_skill_home_modules,
        restore_skill_home_modules,
        snapshot_skill_home_modules,
    )

    skills_tool = _install_fake_module(monkeypatch, "tools.skills_tool")
    manager_tool = _install_fake_module(monkeypatch, "tools.skill_manager_tool")
    original_home = tmp_path / "original"
    original_manager_skills = tmp_path / "manager-skills"
    skills_tool.HERMES_HOME = original_home
    manager_tool.SKILLS_DIR = original_manager_skills

    snapshot = snapshot_skill_home_modules()
    patch_skill_home_modules(tmp_path / "active")
    restore_skill_home_modules(snapshot)

    assert skills_tool.HERMES_HOME == original_home
    assert not hasattr(skills_tool, "SKILLS_DIR")
    assert not hasattr(manager_tool, "HERMES_HOME")
    assert manager_tool.SKILLS_DIR == original_manager_skills


def test_skill_content_opens_external_skill_dir(tmp_path, monkeypatch):
    from api import routes

    tools_mod = _install_fake_module(monkeypatch, "tools.skills_tool")
    tools_mod.MAX_DESCRIPTION_LENGTH = 120
    tools_mod._EXCLUDED_SKILL_DIRS = set()
    tools_mod._get_disabled_skill_names = lambda: set()
    tools_mod._parse_frontmatter = lambda content: (
        {"name": "external-skill", "description": "External skill"},
        content.split("---", 2)[-1],
    )
    tools_mod._parse_tags = lambda raw: []
    tools_mod._sort_skills = lambda skills: sorted(skills, key=lambda s: s["name"])
    tools_mod.skill_matches_platform = lambda frontmatter: True

    skill_utils = _install_fake_module(monkeypatch, "agent.skill_utils")
    skill_utils.iter_skill_index_files = lambda root, filename: Path(root).rglob(filename)
    external_root = tmp_path / "external"
    skill_utils.get_external_skills_dirs = lambda: [external_root]

    active_root = tmp_path / "profile" / "skills"
    active_root.mkdir(parents=True)
    skill_dir = external_root / "external-skill"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: external-skill\ndescription: External skill\n---\n\nExternal body.\n",
        encoding="utf-8",
    )
    (skill_dir / "references" / "note.md").write_text("linked external\n", encoding="utf-8")

    monkeypatch.setattr(routes, "_active_skills_dir", lambda: active_root)

    data = routes._skill_view_from_active_dir("external-skill")

    assert data["success"] is True
    assert data["name"] == "external-skill"
    assert "External body." in data["content"]
    assert data["linked_files"] == {"references": ["references/note.md"]}
