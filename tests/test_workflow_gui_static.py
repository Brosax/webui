import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
WORKFLOW_JS = (ROOT / "static" / "workflow.js").read_text(encoding="utf-8")
CANVAS_JS = (ROOT / "static" / "workflow-canvas.js").read_text(encoding="utf-8")
EDITOR_JS = (ROOT / "static" / "workflow-editor.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_workflow_gui_modules_are_loaded_before_workflow_entrypoint():
    registry_idx = INDEX_HTML.index("workflow-registry.js")
    editor_idx = INDEX_HTML.index("workflow-editor.js")
    canvas_idx = INDEX_HTML.index("workflow-canvas.js")
    workflow_idx = INDEX_HTML.index("workflow.js")
    assert registry_idx < editor_idx < canvas_idx < workflow_idx


def test_canvas_tab_exposes_full_editor_shell():
    assert "workflow-node-palette" in WORKFLOW_JS
    assert "workflow-canvas-stage" in WORKFLOW_JS
    assert "workflow-properties-panel" in WORKFLOW_JS
    assert "workflow-results-drawer" in WORKFLOW_JS
    assert "workflow-definition-canvas-svg" in WORKFLOW_JS


def test_canvas_stage_exposes_view_controls():
    editor_start = WORKFLOW_JS.index("function _renderWorkflowCanvasEditor(def)")
    editor_end = WORKFLOW_JS.index("function _workflowNodeGlyph", editor_start)
    editor_block = WORKFLOW_JS[editor_start:editor_end]
    assert "workflow-canvas-controls" in editor_block
    assert "workflow-canvas-controls-group" in editor_block
    assert "zoomWorkflowCanvasIn()" in editor_block
    assert "zoomWorkflowCanvasOut()" in editor_block
    assert "fitWorkflowCanvasView()" in editor_block
    assert "resetWorkflowCanvasZoom()" in editor_block
    assert "toggleWorkflowCanvasLock()" in editor_block
    for label in ["Zoom In", "Zoom Out", "Fit View", "Reset 100%", "Lock Nodes"]:
        assert f'aria-label="{label}"' in editor_block
        assert f'title="{label}"' in editor_block
    assert 'aria-pressed="false"' in editor_block
    assert "<svg viewBox=" in editor_block
    for label in ["Zoom In", "Zoom Out", "Fit View", "Reset 100%"]:
        assert f">{label}</button>" not in editor_block


def test_canvas_view_controls_handlers_and_helpers_are_exported():
    for symbol in [
        "zoomWorkflowCanvasIn",
        "zoomWorkflowCanvasOut",
        "fitWorkflowCanvasView",
        "resetWorkflowCanvasZoom",
        "toggleWorkflowCanvasLock",
    ]:
        assert f"function {symbol}()" in CANVAS_JS
        assert f"window.{symbol} = {symbol}" in CANVAS_JS
    for helper in [
        "function setCanvasZoomAtPoint",
        "function fitCanvasView",
        "function resetCanvasZoom",
        "function _canvasNodeBounds",
    ]:
        assert helper in CANVAS_JS
    assert "WORKFLOW_CANVAS_MIN_ZOOM = 0.35" in CANVAS_JS
    assert "WORKFLOW_CANVAS_MAX_ZOOM = 2" in CANVAS_JS
    assert "if (!_canvasNodes.length)" in CANVAS_JS


def test_canvas_view_controls_have_responsive_styles():
    for selector in [
        ".workflow-canvas-controls",
        ".workflow-canvas-controls-group",
        ".workflow-canvas-control-btn",
        ".workflow-canvas-control-btn.is-active",
        ".workflow-canvas-lock-icon--locked",
    ]:
        assert selector in STYLE_CSS
    assert "background: #141414" in STYLE_CSS
    assert '[aria-pressed="true"]' in STYLE_CSS
    mobile_start = STYLE_CSS.index("@media (max-width: 900px)")
    mobile_css = STYLE_CSS[mobile_start:]
    assert ".workflow-canvas-controls" in mobile_css
    assert ".workflow-canvas-controls-group" in mobile_css


def test_opening_workflow_keeps_definition_sidebar_visible():
    detail_start = WORKFLOW_JS.index("function _showWorkflowDetail()")
    detail_end = WORKFLOW_JS.index("function _setWorkflowHeaderButtons", detail_start)
    detail_block = WORKFLOW_JS[detail_start:detail_end]
    assert "panel.classList.add('active')" in detail_block
    assert "renderDefinitionList()" in detail_block
    assert "panel.classList.remove('active')" not in detail_block


def test_workflow_sidebar_includes_search_input():
    assert 'id="workflowSearch"' in INDEX_HTML
    assert 'class="workflow-search sidebar-search"' in INDEX_HTML
    assert 'oninput="filterWorkflowDefinitions()"' in INDEX_HTML


def test_workflow_sidebar_uses_filter_state_and_function():
    assert "let _workflowFilterQuery = '';" in WORKFLOW_JS
    assert "function filterWorkflowDefinitions()" in WORKFLOW_JS
    assert "function _getFilteredWorkflowDefinitions()" in WORKFLOW_JS
    assert "definition?.name || ''" in WORKFLOW_JS
    assert "definition?.project_id || ''" in WORKFLOW_JS
    assert "definition?.workflow_id || ''" in WORKFLOW_JS


def test_workflow_definitions_render_as_sidebar_rows_with_actions():
    assert "function renderDefinitionRow(definition)" in WORKFLOW_JS
    assert 'class="session-item workflow-session-item' in WORKFLOW_JS
    assert 'class="session-actions-trigger workflow-actions-trigger"' in WORKFLOW_JS
    assert 'data-workflow-actions="${workflowId}"' in WORKFLOW_JS
    row_start = WORKFLOW_JS.index("function renderDefinitionRow(definition)")
    row_end = WORKFLOW_JS.index("function filterWorkflowDefinitions()", row_start)
    row_block = WORKFLOW_JS[row_start:row_end]
    assert "Delete</button>" not in row_block


def test_workflow_action_menu_and_inline_rename_are_wired():
    assert "function _openWorkflowActionMenu(definition, anchorEl)" in WORKFLOW_JS
    assert "function closeWorkflowActionMenu()" in WORKFLOW_JS
    assert "function _positionWorkflowActionMenu(anchorEl)" in WORKFLOW_JS
    assert "function _startWorkflowInlineRename(definition, row)" in WORKFLOW_JS
    assert "event.key === 'Escape' && _workflowActionMenu" in WORKFLOW_JS
    assert "window.addEventListener('resize', () => {" in WORKFLOW_JS
    assert "workflow-title-input" in STYLE_CSS


def test_workflow_inline_rename_patches_definition_name():
    assert "await api(`/api/workflow/definitions/${definition.workflow_id}`," in WORKFLOW_JS
    assert "method: 'PATCH'" in WORKFLOW_JS
    assert "body: JSON.stringify({ name: newName })" in WORKFLOW_JS
    assert "_workflowCurrentDef.name = nextName;" in WORKFLOW_JS
    assert "detailTitle.textContent = nextName;" in WORKFLOW_JS


def test_workflow_toolbar_uses_templates_menu_without_quick_node_buttons():
    editor_start = WORKFLOW_JS.index("function _renderWorkflowCanvasEditor(def)")
    editor_end = WORKFLOW_JS.index("function _workflowNodeGlyph", editor_start)
    editor_block = WORKFLOW_JS[editor_start:editor_end]
    assert "workflow-template-menu" in editor_block
    assert "workflow-template-menu-list" in editor_block
    assert "WorkflowNodeRegistry?.templates || []).map" in editor_block
    assert "workflow-template-strip" not in editor_block
    assert "addCanvasNode('trigger.manual')" not in editor_block
    assert "addCanvasNode('core.set')" not in editor_block
    assert "addCanvasNode('agent.run')" not in editor_block
    assert "addCanvasNode('output.results_display')" not in editor_block


def test_workflow_editor_palette_follows_theme_tokens():
    editor_start = STYLE_CSS.index(".workflow-gui-editor {")
    editor_end = STYLE_CSS.index(".workflow-editor-toolbar", editor_start)
    editor_css = STYLE_CSS[editor_start:editor_end]
    assert "--nodeflow-bg: var(--bg)" in editor_css
    assert "--nodeflow-canvas: var(--surface)" in editor_css
    assert "--nodeflow-card: var(--surface)" in editor_css
    assert "--nodeflow-border: var(--border)" in editor_css
    assert "--nodeflow-text: var(--text)" in editor_css
    assert "--nodeflow-muted: var(--muted)" in editor_css
    assert ":root.dark .workflow-gui-editor" not in STYLE_CSS


def test_registry_driven_canvas_interactions_are_exported():
    for symbol in [
        "copyWorkflowSelection",
        "pasteWorkflowSelection",
        "undoWorkflowCanvas",
        "redoWorkflowCanvas",
        "deleteWorkflowSelection",
        "validateWorkflowEdge",
    ]:
        assert f"window.{symbol}" in CANVAS_JS
    assert "window.serializeWorkflowEditor" in EDITOR_JS
    assert "window.deserializeWorkflowEditor" in EDITOR_JS


def test_canvas_supports_direct_wheel_zoom_and_middle_mouse_pan():
    wheel_start = CANVAS_JS.index("function onCanvasWheel(event)")
    wheel_end = CANVAS_JS.index("function startCanvasPan", wheel_start)
    wheel_block = CANVAS_JS[wheel_start:wheel_end]
    assert "event.preventDefault()" in wheel_block
    assert "if (!event.ctrlKey && !event.metaKey) return" not in wheel_block
    assert "setCanvasZoomAtPoint(next, event.clientX, event.clientY)" in wheel_block

    assert "let _canvasPanning = null" in CANVAS_JS
    assert "if (event.button === 1)" in CANVAS_JS
    assert "function startCanvasPan(event)" in CANVAS_JS
    assert 'document.addEventListener("mousemove", panCanvasTo)' in CANVAS_JS
    assert 'document.removeEventListener("mousemove", panCanvasTo)' in CANVAS_JS


def test_canvas_right_click_routes_context_menu_by_target():
    context_start = CANVAS_JS.index("function onCanvasContextMenu(event)")
    context_end = CANVAS_JS.index("function openWorkflowNodeMenu", context_start)
    context_block = CANVAS_JS[context_start:context_end]
    assert 'event.target?.closest?.(".canvas-node[data-node-id]")' in context_block
    assert "const edge = _edgeFromContextTarget(event.target);" in context_block
    assert 'openWorkflowNodeMenu(event.clientX, event.clientY, { kind: "node" })' in context_block
    assert 'openWorkflowNodeMenu(event.clientX, event.clientY, { kind: "edge" })' in context_block
    assert 'openWorkflowNodeMenu(event.clientX, event.clientY, { kind: "canvas", point })' in context_block
    assert 'addCanvasNode("core.set", point)' not in context_block

    assert 'function renderWorkflowNodeMenu(kind = "canvas")' in CANVAS_JS
    assert "function renderWorkflowNodeActions()" in CANVAS_JS
    assert "function renderWorkflowEdgeActions()" in CANVAS_JS
    assert "function handleWorkflowContextAction(action, value = \"\")" in CANVAS_JS
    assert "Configure" in CANVAS_JS
    assert "Delete Node" in CANVAS_JS
    assert "Connection Properties" in CANVAS_JS
    assert "Delete Connection" in CANVAS_JS
    assert "WorkflowNodeRegistry" in CANVAS_JS
    assert "data-workflow-node-type" in CANVAS_JS
    assert "function insertWorkflowNodeFromMenu(type)" in CANVAS_JS
    assert "addCanvasNode(type, _canvasContextPosition)" in CANVAS_JS
    assert "workflow-node-context-menu" in STYLE_CSS


def test_canvas_node_context_menu_can_replace_single_node_type():
    assert 'Replace Node...' in CANVAS_JS
    assert '_workflowActionRow("open-replace-node", "R", "Replace Node...")' in CANVAS_JS
    assert '${!multi ? _workflowActionRow("open-replace-node", "R", "Replace Node...") : ""}' in CANVAS_JS
    assert 'if (kind === "replace-node") return renderWorkflowReplaceNodeMenu();' in CANVAS_JS
    assert "function renderWorkflowReplaceNodeMenu()" in CANVAS_JS
    assert "function replaceSelectedNodeWithType(type)" in CANVAS_JS
    assert 'action === "open-replace-node"' in CANVAS_JS
    assert 'action === "replace-node-type"' in CANVAS_JS
    assert "data-workflow-replace-node-type" in CANVAS_JS

    replace_start = CANVAS_JS.index("function renderWorkflowReplaceNodeMenu()")
    replace_end = CANVAS_JS.index("function renderWorkflowEdgeActions()", replace_start)
    replace_menu_block = CANVAS_JS[replace_start:replace_end]
    assert "registry?.list?.() || []" in replace_menu_block
    assert "node.category === category && node.type !== currentType" in replace_menu_block

    logic_start = CANVAS_JS.index("function replaceSelectedNodeWithType(type)")
    logic_end = CANVAS_JS.index("function clampWorkflowNodeMenu", logic_start)
    logic_block = CANVAS_JS[logic_start:logic_end]
    assert "selectedNodes.length === 1" in logic_block
    assert "node.type === type" in logic_block
    assert "_pushCanvasUndo();" in logic_block
    assert "registry?.defaultParameters(type) || {}" in logic_block
    assert "Object.keys(newParameters).forEach((key) => {" in logic_block
    assert "Object.prototype.hasOwnProperty.call(oldParameters, key)" in logic_block
    assert "newParameters[key] = oldParameters[key]" in logic_block
    assert "node.name === oldDefaultLabel ? newDefaultLabel : node.name" in logic_block
    assert "const firstInput = (newDef.inputs || [])[0]?.id;" in logic_block
    assert "const firstOutput = (newDef.outputs || [])[0]?.id;" in logic_block
    assert "if (!firstInput) return false;" in logic_block
    assert "edge.targetHandle = firstInput;" in logic_block
    assert "if (!firstOutput) return false;" in logic_block
    assert "edge.sourceHandle = firstOutput;" in logic_block
    assert "renderWorkflowResultsDrawer();" in logic_block


def test_file_parameters_render_manual_input_with_browse_button():
    param_start = CANVAS_JS.index("function _renderParameterControl(node, param)")
    param_end = CANVAS_JS.index("function applyNodeConfig(nodeId)", param_start)
    param_block = CANVAS_JS[param_start:param_end]
    assert 'param.type === "file"' in param_block
    assert "workflow-path-control" in param_block
    assert 'data-workflow-param="${escapeHtml(param.key)}"' in param_block
    assert "openWorkflowPathPicker" in param_block
    assert 'value="${escapeHtml(value)}"' in param_block
    assert "{{inputs.file_path}}" in (ROOT / "static" / "workflow-registry.js").read_text(encoding="utf-8")


def test_workflow_path_picker_helpers_use_workspace_list_api():
    assert "function openWorkflowPathPicker(nodeId, paramKey)" in CANVAS_JS
    assert "function closeWorkflowPathPicker()" in CANVAS_JS
    assert "async function loadWorkflowPathPickerDir(path = \".\")" in CANVAS_JS
    assert "function selectWorkflowPathPickerFile(path)" in CANVAS_JS
    assert "function confirmWorkflowPathPickerSelection()" in CANVAS_JS
    assert "/api/list?session_id=" in CANVAS_JS
    assert "/api/workspaces" in CANVAS_JS
    assert "workspace_path=" in CANVAS_JS
    assert "S.session.session_id" in CANVAS_JS
    assert "workflow-path-picker-modal" in CANVAS_JS
    assert "workflow-path-picker-empty" in CANVAS_JS
    assert "No saved workspaces found. Add one from Workspaces." in CANVAS_JS


def test_workflow_path_picker_styles_are_present():
    for selector in [
        ".workflow-path-control",
        ".workflow-path-browse",
        ".workflow-path-picker-overlay",
        ".workflow-path-picker-modal",
        ".workflow-path-picker-row",
        ".workflow-path-picker-empty",
    ]:
        assert selector in STYLE_CSS


def test_canvas_edges_can_be_selected_and_deleted():
    assert "function _edgeKey(edge)" in CANVAS_JS
    assert "canvas-edge-hit" in CANVAS_JS
    assert 'setAttribute("data-edge-key", edgeKey)' in CANVAS_JS
    assert "_edgeKey(_canvasSelectedEdge) === edgeKey" in CANVAS_JS
    assert "Delete Connection" in CANVAS_JS
    assert "const selectedKey = _edgeKey(_canvasSelectedEdge)" in CANVAS_JS
    assert "_canvasEdges.filter((edge) => _edgeKey(edge) !== selectedKey)" in CANVAS_JS
    assert ".canvas-edge-hit" in STYLE_CSS


def test_canvas_supports_marquee_multi_select_and_group_actions():
    assert "let _canvasMarquee = null" in CANVAS_JS
    assert "function renderSelectionMarquee(parent)" in CANVAS_JS
    assert "workflow-canvas-marquee" in CANVAS_JS
    assert ".workflow-canvas-marquee" in STYLE_CSS
    assert "_canvasMarquee = { start: point, current: point };" in CANVAS_JS
    assert "_canvasMarquee.current = _clientToCanvas(event.clientX, event.clientY);" in CANVAS_JS
    assert "const ids = _marqueeSelectedIds();" in CANVAS_JS
    assert "_setNodeSelection(ids, ids[0] || null);" in CANVAS_JS
    assert "_canvasDragging = { anchor: point, nodeIds: ids, origPositions, moved: false };" in CANVAS_JS
    assert "_canvasDragging.nodeIds.forEach((id) => {" in CANVAS_JS
    assert "selectedNodes.length > 1" in CANVAS_JS
    assert "Delete Selected Nodes" in CANVAS_JS
    assert "toggleWorkflowSelectedDisabled" in CANVAS_JS
    assert "window.toggleWorkflowSelectedDisabled = toggleWorkflowSelectedDisabled;" in CANVAS_JS
    assert "const selectedIds = _selectedNodeIds();" in CANVAS_JS


def test_old_standalone_canvas_panel_is_removed():
    assert "workflow-canvas-panel" not in INDEX_HTML
    assert "switchWorkflowView" not in CANVAS_JS


def test_workflow_sidebar_uses_single_plus_menu_for_creation():
    assert 'onclick="openWorkflowCreateMenu(event)"' in INDEX_HTML
    assert 'function openWorkflowCreateMenu(event)' in WORKFLOW_JS
    assert "workflow-create-menu-item" in WORKFLOW_JS
    assert "workflow-source-actions" not in WORKFLOW_JS
