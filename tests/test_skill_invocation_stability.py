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


def test_skill_content_response_is_skill_view_compatible(tmp_path, monkeypatch):
    from api import routes

    tools_mod = _install_fake_module(monkeypatch, "tools.skills_tool")
    tools_mod._parse_frontmatter = lambda content: (
        {
            "name": "compat-skill",
            "description": "Compatibility skill",
            "metadata": {"hermes": {"tags": ["webui", "skills"], "related_skills": ["helper"]}},
            "required_environment_variables": [{"name": "COMPAT_TOKEN", "optional": True}],
            "required_credential_files": [],
        },
        content.split("---", 2)[-1],
    )
    tools_mod._parse_tags = lambda raw: list(raw) if isinstance(raw, list) else [raw] if raw else []
    tools_mod.skill_matches_platform = lambda frontmatter: True

    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "compat-skill"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: compat-skill\ndescription: Compatibility skill\n---\n\nSkill body.\n",
        encoding="utf-8",
    )
    (skill_dir / "references" / "guide.md").write_text("guide\n", encoding="utf-8")

    data = routes._skill_view_from_file(skill_dir, skill_dir / "SKILL.md", search_root=skills_root)

    assert data["success"] is True
    assert data["name"] == "compat-skill"
    assert data["description"] == "Compatibility skill"
    assert data["tags"] == ["webui", "skills"]
    assert data["related_skills"] == ["helper"]
    assert data["content"].endswith("Skill body.\n")
    assert data["path"] == "compat-skill/SKILL.md"
    assert data["skill_dir"] == str(skill_dir)
    assert data["linked_files"] == {"references": ["references/guide.md"]}
    assert data["usage_hint"]
    assert data["required_environment_variables"] == [{"name": "COMPAT_TOKEN", "optional": True}]
    assert data["required_commands"] == []
    assert data["missing_required_environment_variables"] == []
    assert data["missing_credential_files"] == []
    assert data["missing_required_commands"] == []
    assert data["setup_needed"] is False
    assert data["setup_skipped"] is False
    assert data["readiness_status"] == "available"


def test_skill_content_response_empty_optional_collections_are_stable(tmp_path, monkeypatch):
    from api import routes

    tools_mod = _install_fake_module(monkeypatch, "tools.skills_tool")
    tools_mod._parse_frontmatter = lambda content: (
        {"name": "plain-skill", "description": ""},
        content,
    )
    tools_mod._parse_tags = lambda raw: []
    tools_mod.skill_matches_platform = lambda frontmatter: True

    skill_dir = tmp_path / "skills" / "plain-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Plain body.\n", encoding="utf-8")

    data = routes._skill_view_from_file(skill_dir, skill_dir / "SKILL.md", search_root=tmp_path / "skills")

    assert data["success"] is True
    assert data["tags"] == []
    assert data["related_skills"] == []
    assert data["linked_files"] == {}
    assert data["usage_hint"] is None


def test_skill_content_uses_active_dir_before_startup_root(tmp_path, monkeypatch):
    from api import routes

    tools_mod = _install_fake_module(monkeypatch, "tools.skills_tool")
    tools_mod._EXCLUDED_SKILL_DIRS = set()
    tools_mod._parse_frontmatter = lambda content: (
        {"name": "same-name", "description": ""},
        content,
    )
    tools_mod._parse_tags = lambda raw: []
    tools_mod.skill_matches_platform = lambda frontmatter: True

    skill_utils = _install_fake_module(monkeypatch, "agent.skill_utils")
    skill_utils.iter_skill_index_files = lambda root, filename: Path(root).rglob(filename)
    skill_utils.get_external_skills_dirs = lambda: []

    active_root = tmp_path / "active" / "skills"
    startup_root = tmp_path / "startup" / "skills"
    active_skill = active_root / "same-name"
    startup_skill = startup_root / "same-name"
    active_skill.mkdir(parents=True)
    startup_skill.mkdir(parents=True)
    (active_skill / "SKILL.md").write_text("Active profile body.\n", encoding="utf-8")
    (startup_skill / "SKILL.md").write_text("Startup profile body.\n", encoding="utf-8")

    monkeypatch.setattr(routes, "_active_skills_dir", lambda: active_root)

    data = routes._skill_view_from_active_dir("same-name")

    assert data["success"] is True
    assert "Active profile body." in data["content"]
    assert "Startup profile body." not in data["content"]


def test_shared_skill_detail_opens_from_active_shared_dir(tmp_path, monkeypatch):
    from api import routes

    tools_mod = _install_fake_module(monkeypatch, "tools.skills_tool")
    tools_mod.MAX_DESCRIPTION_LENGTH = 120
    tools_mod._EXCLUDED_SKILL_DIRS = set()
    tools_mod._get_disabled_skill_names = lambda: set()
    tools_mod._parse_frontmatter = lambda content: (
        {"name": "shared-skill", "description": "Shared skill"},
        content,
    )
    tools_mod._parse_tags = lambda raw: []
    tools_mod._sort_skills = lambda skills: sorted(skills, key=lambda s: s["name"])
    tools_mod.skill_matches_platform = lambda frontmatter: True

    skill_utils = _install_fake_module(monkeypatch, "agent.skill_utils")
    skill_utils.iter_skill_index_files = lambda root, filename: Path(root).rglob(filename)
    skill_utils.get_external_skills_dirs = lambda: []

    shared_root = tmp_path / "shared_skills"
    skill_dir = shared_root / "shared-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Shared skill body.\n", encoding="utf-8")

    monkeypatch.setattr(routes, "_active_skills_dir", lambda: shared_root)

    listed = routes._skills_list_from_dir(shared_root)
    detail = routes._skill_view_from_active_dir("shared-skill")

    assert [s["name"] for s in listed["skills"]] == ["shared-skill"]
    assert detail["success"] is True
    assert "Shared skill body." in detail["content"]


def test_linked_skill_file_response_is_skill_view_compatible(tmp_path, monkeypatch):
    from api import routes

    skill_dir = tmp_path / "skills" / "linked-skill"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "references" / "guide.md").write_text("linked guide\n", encoding="utf-8")

    data, status = routes._skill_linked_file_payload("linked-skill", skill_dir, "references/guide.md")

    assert status == 200
    assert data == {
        "success": True,
        "name": "linked-skill",
        "file": "references/guide.md",
        "content": "linked guide\n",
        "file_type": ".md",
        "path": "references/guide.md",
    }


def test_linked_skill_file_rejects_traversal(tmp_path):
    from api import routes

    skill_dir = tmp_path / "skills" / "linked-skill"
    skill_dir.mkdir(parents=True)

    data, status = routes._skill_linked_file_payload("linked-skill", skill_dir, "../secret.txt")

    assert status == 400
    assert data["success"] is False
    assert "Invalid file path" in data["error"]
