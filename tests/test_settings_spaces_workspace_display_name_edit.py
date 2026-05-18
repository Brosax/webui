"""Regression coverage for Settings > Spaces workspace display-name editing."""

import pathlib


def test_settings_spaces_workspace_row_has_display_name_edit_action():
    src = pathlib.Path("static/panels.js").read_text(encoding="utf-8")
    assert 'class="users-action-btn settings-ws-edit-btn"' in src
    assert "data-action=\"edit\"" in src
    assert "M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" in src
    assert "toggleWorkspaceDisplayNameEdit" in src
    assert "saveWorkspaceDisplayNameFromSettings" in src
    assert "/api/workspaces/rename" in src


def test_settings_spaces_workspace_row_layout_is_split_into_info_and_actions():
    src = pathlib.Path("static/panels.js").read_text(encoding="utf-8")
    assert "settings-ws-row-info" in src
    assert "settings-ws-row-actions" in src
    assert "settings-ws-active-badge" in src
    assert "settings-ws-row-name" in src
    assert "settings-ws-row-path" in src


def test_settings_spaces_workspace_row_css_exists():
    css = pathlib.Path("static/style.css").read_text(encoding="utf-8")
    for token in (
        ".settings-ws-row{",
        ".settings-ws-row-main{",
        ".settings-ws-row-info{",
        ".settings-ws-row-actions{",
        ".settings-ws-active-badge{",
        ".settings-ws-row-edit{",
    ):
        assert token in css
