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


def test_opening_workflow_keeps_definition_sidebar_visible():
    detail_start = WORKFLOW_JS.index("function _showWorkflowDetail()")
    detail_end = WORKFLOW_JS.index("function _setWorkflowHeaderButtons", detail_start)
    detail_block = WORKFLOW_JS[detail_start:detail_end]
    assert "panel.classList.add('active')" in detail_block
    assert "renderDefinitionList()" in detail_block
    assert "panel.classList.remove('active')" not in detail_block


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
    assert "_clientToCanvas(event.clientX, event.clientY)" in wheel_block
    assert "_canvasView.scroll" in wheel_block

    assert "let _canvasPanning = null" in CANVAS_JS
    assert "if (event.button === 1)" in CANVAS_JS
    assert "function startCanvasPan(event)" in CANVAS_JS
    assert 'document.addEventListener("mousemove", panCanvasTo)' in CANVAS_JS
    assert 'document.removeEventListener("mousemove", panCanvasTo)' in CANVAS_JS


def test_canvas_right_click_opens_node_type_menu():
    context_start = CANVAS_JS.index("function onCanvasContextMenu(event)")
    context_end = CANVAS_JS.index("function openWorkflowNodeMenu", context_start)
    context_block = CANVAS_JS[context_start:context_end]
    assert "openWorkflowNodeMenu(event.clientX, event.clientY, point)" in context_block
    assert 'addCanvasNode("core.set", point)' not in context_block

    assert "function renderWorkflowNodeMenu()" in CANVAS_JS
    assert "WorkflowNodeRegistry" in CANVAS_JS
    assert "data-workflow-node-type" in CANVAS_JS
    assert "function insertWorkflowNodeFromMenu(type)" in CANVAS_JS
    assert "addCanvasNode(type, _canvasContextPosition)" in CANVAS_JS
    assert "workflow-node-context-menu" in STYLE_CSS


def test_canvas_edges_can_be_selected_and_deleted():
    assert "function _edgeKey(edge)" in CANVAS_JS
    assert "canvas-edge-hit" in CANVAS_JS
    assert "_edgeKey(_canvasSelectedEdge) === _edgeKey(edge)" in CANVAS_JS
    assert "Delete Connection" in CANVAS_JS
    assert "const selectedKey = _edgeKey(_canvasSelectedEdge)" in CANVAS_JS
    assert "_canvasEdges.filter((edge) => _edgeKey(edge) !== selectedKey)" in CANVAS_JS
    assert ".canvas-edge-hit" in STYLE_CSS


def test_old_standalone_canvas_panel_is_removed():
    assert "workflow-canvas-panel" not in INDEX_HTML
    assert "switchWorkflowView" not in CANVAS_JS
