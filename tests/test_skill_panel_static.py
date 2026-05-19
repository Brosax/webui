"""Static checks for the Skills panel detail UI."""

from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PANELS = (REPO / "static" / "panels.js").read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    marker = f"async function {name}("
    start = source.find(marker)
    assert start >= 0, f"{name} not found"
    brace = source.find("{", start)
    assert brace >= 0, f"{name} body not found"
    depth = 0
    for idx in range(brace, len(source)):
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : idx]
    raise AssertionError(f"{name} body did not close")


def test_open_skill_treats_unsuccessful_skill_view_as_load_failure():
    body = _function_body(PANELS, "openSkill")

    assert "data.success === false" in body
    assert "throw new Error" in body
    assert "skill_load_failed" in body


def test_open_skill_preserves_raw_skill_content_for_editing():
    body = _function_body(PANELS, "openSkill")

    assert "const content = data.raw_content || data.content || ''" in body
    assert "_currentSkillDetail = { name: displayName, content, linked_files: data.linked_files || {} }" in body
    assert "_renderSkillDetail(displayName, content, data.linked_files || {})" in body
