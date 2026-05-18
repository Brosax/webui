import json
import pathlib
import shutil
import subprocess

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANVAS_JS = ROOT / "static" / "workflow-canvas.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_canvas_driver(actions):
    script = f"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {{
  return {{
    children: [],
    attributes: {{}},
    style: {{}},
    classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }} }},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || null; }},
    appendChild(child) {{ this.children.push(child); return child; }},
    addEventListener() {{}},
    removeEventListener() {{}},
    closest() {{ return null; }},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    focus() {{}},
    innerHTML: '',
    textContent: '',
  }};
}}

const svg = makeElement();
svg.getBoundingClientRect = () => ({{ left: 10, top: 20, width: 800, height: 600 }});

const documentStub = {{
  createElementNS() {{ return makeElement(); }},
  createElement() {{ return makeElement(); }},
  createTextNode(text) {{ const node = makeElement(); node.textContent = text; return node; }},
  getElementById() {{ return null; }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  addEventListener() {{}},
  removeEventListener() {{}},
}};

const context = {{
  console,
  document: documentStub,
  window: {{}},
  Date,
  setTimeout,
  clearTimeout,
  escapeHtml(value) {{ return String(value ?? ''); }},
}};
context.window.WorkflowNodeRegistry = {{
  get(type) {{ return {{ type, label: type, accent: '#888', inputs: [{{ id: 'in' }}], outputs: [{{ id: 'out' }}], parameters: [] }}; }},
}};
context.window.deserializeWorkflowEditor = (definition) => ({{ nodes: definition.draft_steps }});
context.window.serializeWorkflowEditor = (state) => state;
context.window._workflowRuns = [];
context.globalThis = context;
context.window.window = context.window;

vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(CANVAS_JS))}, 'utf8'), context);
context.window.initCanvas(svg);

const actions = {json.dumps(actions)};
const states = [];
for (const action of actions) {{
  if (action.kind === 'state') {{
    context.window.setWorkflowEditorState(action.value);
  }} else if (action.kind === 'fit') {{
    context.window.fitWorkflowCanvasView();
  }} else if (action.kind === 'reset') {{
    context.window.resetWorkflowCanvasZoom();
  }} else if (action.kind === 'zoomIn') {{
    context.window.zoomWorkflowCanvasIn();
  }} else if (action.kind === 'zoomOut') {{
    context.window.zoomWorkflowCanvasOut();
  }} else if (action.kind === 'toggleLock') {{
    context.window.toggleWorkflowCanvasLock();
  }} else if (action.kind === 'dragNode') {{
    const node = context.window.getWorkflowEditorState().nodes.find((item) => item.id === action.id);
    const target = {{ getAttribute() {{ return null; }} }};
    context.onNodeMouseDown({{
      button: 0,
      clientX: action.from[0],
      clientY: action.from[1],
      target,
      stopPropagation() {{}},
    }}, node);
    context.onCanvasMouseMove({{
      clientX: action.to[0],
      clientY: action.to[1],
      preventDefault() {{}},
    }});
    context.onCanvasMouseUp({{
      target,
      preventDefault() {{}},
    }});
  }}
  states.push(JSON.parse(JSON.stringify(context.window.getWorkflowEditorState())));
}}
process.stdout.write(JSON.stringify(states));
"""
    result = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_fit_view_frames_existing_nodes_and_empty_canvas_falls_back_to_center():
    states = _run_canvas_driver([
        {
            "kind": "state",
            "value": {
                "nodes": [
                    {"id": "a", "type": "trigger.manual", "position": {"x": -200, "y": 100}},
                    {"id": "b", "type": "agent.run", "position": {"x": 1200, "y": 700}},
                ],
                "edges": [],
                "canvas": {"zoom": 1, "scroll": {"x": 0, "y": 0}, "selectedNodeIds": []},
            },
        },
        {"kind": "fit"},
        {"kind": "state", "value": {"nodes": [], "edges": [], "canvas": {"zoom": 1.5, "scroll": {"x": 12, "y": 34}, "selectedNodeIds": []}}},
        {"kind": "fit"},
    ])

    fitted = states[1]["canvas"]
    assert 0.35 <= fitted["zoom"] <= 2
    assert fitted["zoom"] != 1
    assert fitted["scroll"] != {"x": 0, "y": 0}
    assert states[3]["canvas"]["zoom"] == 1
    assert states[3]["canvas"]["scroll"] == {"x": 400, "y": 300}


def test_zoom_buttons_clamp_and_reset_preserves_viewport_center():
    states = _run_canvas_driver([
        {"kind": "state", "value": {"nodes": [], "edges": [], "canvas": {"zoom": 1.9, "scroll": {"x": 50, "y": -40}, "selectedNodeIds": []}}},
        {"kind": "zoomIn"},
        {"kind": "state", "value": {"nodes": [], "edges": [], "canvas": {"zoom": 0.36, "scroll": {"x": 50, "y": -40}, "selectedNodeIds": []}}},
        {"kind": "zoomOut"},
        {"kind": "state", "value": {"nodes": [], "edges": [], "canvas": {"zoom": 1.5, "scroll": {"x": 100, "y": -20}, "selectedNodeIds": []}}},
        {"kind": "reset"},
    ])

    assert states[1]["canvas"]["zoom"] == 2
    assert states[3]["canvas"]["zoom"] == 0.35
    assert states[5]["canvas"]["zoom"] == 1
    # At zoom 1.5 and scroll (100, -20), viewport center (400, 300) maps to
    # canvas point (200, 213.333...). Resetting to 100% keeps that point centered.
    assert states[5]["canvas"]["scroll"] == {"x": 200, "y": 87}


def test_lock_button_only_disables_node_dragging():
    states = _run_canvas_driver([
        {
            "kind": "state",
            "value": {
                "nodes": [{"id": "a", "type": "trigger.manual", "position": {"x": 100, "y": 100}}],
                "edges": [],
                "canvas": {"zoom": 1, "scroll": {"x": 0, "y": 0}, "selectedNodeIds": []},
            },
        },
        {"kind": "toggleLock"},
        {"kind": "dragNode", "id": "a", "from": [120, 140], "to": [220, 240]},
        {"kind": "zoomIn"},
        {"kind": "zoomOut"},
        {"kind": "fit"},
        {"kind": "reset"},
        {"kind": "toggleLock"},
        {"kind": "dragNode", "id": "a", "from": [120, 140], "to": [220, 240]},
    ])

    assert states[2]["nodes"][0]["position"] == {"x": 100, "y": 100}
    assert states[3]["canvas"]["zoom"] > states[2]["canvas"]["zoom"]
    assert states[4]["canvas"]["zoom"] < states[3]["canvas"]["zoom"]
    assert states[5]["canvas"] != states[4]["canvas"]
    assert states[6]["canvas"]["zoom"] == 1
    assert states[8]["nodes"][0]["position"] == {"x": 200, "y": 200}
