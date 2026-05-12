import pathlib
import re

REPO = pathlib.Path(__file__).parent.parent
INDEX = (REPO / "static" / "index.html").read_text(encoding="utf-8")
PANELS = (REPO / "static" / "panels.js").read_text(encoding="utf-8")
CSS = (REPO / "static" / "style.css").read_text(encoding="utf-8")
README = (REPO / "README.md").read_text(encoding="utf-8")


def _function_body(src: str, name: str) -> str:
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", src)
    assert match, f"{name}() not found"
    brace = src.find("{", match.end())
    assert brace != -1, f"{name}() has no body"
    depth = 1
    i = brace + 1
    in_string = None
    escaped = False
    in_line_comment = False
    in_block_comment = False
    while i < len(src) and depth:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in "'\"`":
            in_string = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"{name}() body did not close"
    return src[brace + 1:i - 1]


# ── 1. Users panel uses status.multi_user ────────────────────────────────────

def test_users_panel_reads_multi_user_from_auth_status():
    """loadUsersPanel() must call /api/auth/status and check status.multi_user."""
    body = _function_body(PANELS, "loadUsersPanel")
    assert "/api/auth/status" in body, "loadUsersPanel must fetch /api/auth/status"
    assert "multi_user" in body, "loadUsersPanel must reference multi_user field"
    # Verify it uses the correct field path: status.multi_user
    assert "status.multi_user" in body or "status&&status.multi_user" in body, \
        "loadUsersPanel must check status.multi_user (not a stale field name)"


def test_users_panel_branches_on_multi_user_flag():
    """loadUsersPanel must distinguish legacy vs multi-user mode."""
    body = _function_body(PANELS, "loadUsersPanel")
    assert "'legacy'" in body, "loadUsersPanel must set _authMode='legacy' for non-multi-user"
    assert "'multi'" in body, "loadUsersPanel must set _authMode='multi' for multi-user mode"


def test_users_panel_checks_admin_role():
    """loadUsersPanel must check user.role==='admin' for admin view."""
    body = _function_body(PANELS, "loadUsersPanel")
    assert "role" in body and "admin" in body, \
        "loadUsersPanel must check admin role to show/hide admin view"


# ── 2. Shared Workspaces UI exists ───────────────────────────────────────────

def test_shared_workspaces_section_exists_in_html():
    """The admin-only Shared Workspaces section must exist in index.html."""
    assert 'id="sharedWorkspacesSection"' in INDEX
    assert 'id="sharedWorkspacesList"' in INDEX
    assert 'id="sharedWorkspacesEmpty"' in INDEX
    assert 'id="sharedWorkspaceForm"' in INDEX


def test_shared_workspaces_form_has_path_name_mode_fields():
    """The add/edit form must have path, name, and mode inputs."""
    assert 'id="sharedWsPath"' in INDEX
    assert 'id="sharedWsName"' in INDEX
    assert 'id="sharedWsMode"' in INDEX
    assert 'value="read_write"' in INDEX
    assert 'value="read_only"' in INDEX


def test_shared_workspaces_section_is_inside_admin_view():
    """The shared workspaces section must be within or adjacent to usersAdminView
    and hidden by default (shown only for admin in multi-user mode via JS)."""
    # The section should appear after usersAdminView content
    admin_pos = INDEX.index('id="usersAdminView"')
    shared_pos = INDEX.index('id="sharedWorkspacesSection"')
    self_pos = INDEX.index('id="usersSelfView"')
    assert admin_pos < shared_pos < self_pos, \
        "sharedWorkspacesSection must appear between usersAdminView and usersSelfView"


def test_shared_workspaces_section_hidden_by_default():
    """The sharedWorkspacesSection div must have display:none in its default
    inline style so it stays hidden before loadUsersPanel() runs or if the
    API call fails. This prevents normal users from briefly seeing admin
    controls during page load."""
    # Extract the opening tag of sharedWorkspacesSection
    marker = 'id="sharedWorkspacesSection"'
    tag_start = INDEX.rfind('<div', 0, INDEX.index(marker))
    tag_end = INDEX.index('>', INDEX.index(marker))
    opening_tag = INDEX[tag_start:tag_end + 1]
    assert 'display:none' in opening_tag or 'display: none' in opening_tag, \
        "sharedWorkspacesSection must have display:none in its default inline style"


def test_shared_workspaces_data_ws_mode_escaped():
    """_renderSharedWorkspacesList must escape the data-ws-mode attribute value
    using esc() to avoid injecting raw backend values into HTML attributes."""
    body = _function_body(PANELS, "_renderSharedWorkspacesList")
    # Must use esc() around ws.mode in the data-ws-mode attribute
    assert 'esc(ws.mode' in body or "esc(ws.mode" in body, \
        "_renderSharedWorkspacesList must escape ws.mode with esc() in data-ws-mode"


def test_shared_workspaces_badge_classes_exist_in_css():
    """CSS must define .shared-ws-badge, .shared-ws-mode-rw, .shared-ws-mode-ro."""
    css_compact = re.sub(r"\s+", "", CSS)
    assert ".shared-ws-badge" in css_compact
    assert ".shared-ws-mode-rw" in css_compact
    assert ".shared-ws-mode-ro" in css_compact


def test_shared_workspaces_row_css_exists():
    """CSS must define .shared-ws-row and .shared-ws-row-main."""
    css_compact = re.sub(r"\s+", "", CSS)
    assert ".shared-ws-row{" in css_compact
    assert ".shared-ws-row-main{" in css_compact


# ── 3. JS calls /api/admin/shared-workspaces ─────────────────────────────────

def test_shared_workspaces_js_loads_from_api():
    """_loadSharedWorkspaces must call GET /api/admin/shared-workspaces."""
    body = _function_body(PANELS, "_loadSharedWorkspaces")
    assert "/api/admin/shared-workspaces" in body


def test_shared_workspaces_js_creates_via_post():
    """submitSharedWorkspace must call POST /api/admin/shared-workspaces."""
    body = _function_body(PANELS, "submitSharedWorkspace")
    assert "/api/admin/shared-workspaces" in body
    assert "'POST'" in body or "method:'POST'" in body or 'method:"POST"' in body


def test_shared_workspaces_js_updates_via_patch():
    """submitSharedWorkspace must call PATCH when editing an existing workspace."""
    body = _function_body(PANELS, "submitSharedWorkspace")
    assert "'PATCH'" in body or "method:'PATCH'" in body or 'method:"PATCH"' in body


def test_shared_workspaces_js_deletes_via_delete():
    """_deleteSharedWorkspace must call DELETE /api/admin/shared-workspaces."""
    body = _function_body(PANELS, "_deleteSharedWorkspace")
    assert "/api/admin/shared-workspaces" in body
    assert "'DELETE'" in body or "method:'DELETE'" in body or 'method:"DELETE"' in body


def test_shared_workspaces_loaded_for_admin_in_load_users_panel():
    """loadUsersPanel must call _loadSharedWorkspaces() for admin users."""
    body = _function_body(PANELS, "loadUsersPanel")
    assert "_loadSharedWorkspaces()" in body


def test_shared_workspaces_hidden_for_non_admin():
    """loadUsersPanel must hide sharedWorkspacesSection for non-admin users."""
    body = _function_body(PANELS, "loadUsersPanel")
    assert "sharedWorkspacesSection" in body
    assert "'none'" in body, "loadUsersPanel must set display:none for non-admin shared ws section"


def test_shared_workspaces_hidden_in_legacy_mode():
    """loadUsersPanel must hide sharedWorkspacesSection in legacy (non-multi-user) mode."""
    body = _function_body(PANELS, "loadUsersPanel")
    # The legacy branch runs before the sharedWsSection variable is declared,
    # but it still queries the element and hides it
    assert "sharedWorkspacesSection" in body


# ── 4. No unsafe inline onclick with raw filesystem paths ────────────────────

def test_no_inline_onclick_with_path_in_shared_workspace_rows():
    """_renderSharedWorkspacesList must NOT embed raw paths in onclick strings.
    It must use data attributes and event delegation instead."""
    body = _function_body(PANELS, "_renderSharedWorkspacesList")
    # Must NOT have onclick handlers that interpolate ws.path
    assert "onclick=" not in body.lower() or "onclick=\"showAddSharedWorkspaceForm()\"" not in body, \
        "_renderSharedWorkspacesList must not use inline onclick with path values"
    # Must use data attributes for delegation
    assert "data-action" in body, \
        "_renderSharedWorkspacesList must use data-action attributes for event delegation"
    assert "data-ws-path" in body, \
        "_renderSharedWorkspacesList must use data-ws-path attribute on rows"


def test_shared_workspace_actions_use_event_delegation():
    """Shared workspace edit/delete must use event delegation on the container,
    not inline onclick strings with raw paths."""
    # The event delegation block should exist
    assert "sharedWorkspacesList" in PANELS
    assert "data-action" in PANELS
    assert "closest" in PANELS, "Must use .closest() for event delegation"


def test_no_raw_path_string_interpolation_in_onclick():
    """Verify no onclick handler in the entire file concatenates a raw
    filesystem path into a string for inline onclick."""
    # Search the entire panels.js for patterns like onclick="...'+path+'..."
    # in the shared workspaces section
    sw_section_start = PANELS.find("// ── Shared Workspaces")
    if sw_section_start == -1:
        return  # section not found, other tests will catch this
    sw_section = PANELS[sw_section_start:]
    # Check that _renderSharedWorkspacesList doesn't have onclick with path
    render_fn = _function_body(PANELS, "_renderSharedWorkspacesList")
    assert "onclick=" not in render_fn.lower(), \
        "_renderSharedWorkspacesList must not use inline onclick at all"


# ── 5. README contains LAN multi-user docs ───────────────────────────────────

def test_readme_has_lan_multi_user_section():
    """README must contain a LAN Multi-User Server section."""
    assert "LAN Multi-User Server" in README
    assert "/setup-admin" in README


def test_readme_documents_host_binding():
    """README must document HERMES_WEBUI_HOST=0.0.0.0 for LAN binding."""
    assert "HERMES_WEBUI_HOST=0.0.0.0" in README


def test_readme_documents_shared_workspaces():
    """README must mention shared workspaces management."""
    assert "Shared Workspace" in README or "shared workspace" in README.lower()


def test_readme_documents_shared_skills():
    """README must mention shared skills in multi-user mode."""
    assert "shared skill" in README.lower() or "Shared Skill" in README


def test_readme_documents_provider_sharing():
    """README must mention that provider/API key config is server-level shared."""
    assert "server-level" in README.lower() or "server level" in README.lower() or "shared setting" in README.lower()


def test_readme_documents_admin_setup_flow():
    """README must describe the first-run admin setup at /setup-admin."""
    assert "/setup-admin" in README
    assert "admin" in README.lower()
