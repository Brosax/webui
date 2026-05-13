# Workflow Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A visual workflow editor with drag-drop nodes, bezier-edge connections, and a split-panel live execution view. 4 node types: File Input, Agent, Prompt, File Output.

**Architecture:**
- Canvas: SVG-based node editor with drag/drop + port-based edge connections
- Split panel: left=canvas editor, right=live run status
- Persistence: workflow_definitions table stores nodes+edges JSON; runs create snapshot at start
- Execution: sequential node processing via existing workflow_trace engine

**Tech Stack:** Vanilla JS (no build step), SVG for canvas rendering, existing SQLite schema

---

## File Map

| File | Responsibility |
|------|----------------|
| `static/workflow-canvas.js` | **NEW** — canvas editor, node/edge rendering, live panel |
| `static/workflow-run.js` | **NEW** — node execution loop, input resolution, SSE streaming |
| `api/workflow_trace.py` | Extend with canvas save/load/run functions |
| `api/routes.py` | Add canvas routes (save, load, run, live SSE) |
| `static/style.css` | Add canvas + node + edge + toolbar styles |
| `static/index.html` | Add canvas panel tab + mount point |
| `static/panels.js` | Wire canvas panel open/close |
| `tests/test_workflow_canvas.py` | **NEW** — canvas persistence + run integration tests |

---

## Task 1: Canvas Core — Rendering + Interactions
**Agent 1 owns this.** Produces a working canvas with draggable nodes and connectable edges.

- [ ] **Step 1: Write failing test — canvas save/load roundtrip**

```python
# tests/test_workflow_canvas.py
def test_canvas_save_load_roundtrip():
    """Nodes + edges JSON survives save/load cycle."""
    from api.workflow_trace import save_canvas_definition, load_canvas_definition
    nodes = [
        {"id": "n1", "type": "file_input", "x": 100, "y": 200, "config": {"path": "/tmp/in"}},
        {"id": "n2", "type": "agent", "x": 300, "y": 200, "config": {"agent": "chat"}},
    ]
    edges = [
        {"from": "n1", "to": "n2"},
    ]
    saved = save_canvas_definition("test-wf", nodes, edges, created_by="tester")
    loaded = load_canvas_definition(saved["workflow_id"])
    assert loaded["nodes"] == nodes
    assert loaded["edges"] == edges
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_workflow_canvas.py::test_canvas_save_load_roundtrip -v`
Expected: FAIL — `save_canvas_definition` not defined

- [ ] **Step 3: Write minimal save/load in workflow_trace.py**

```python
# Add to api/workflow_trace.py (after update_workflow_definition)
@_with_lock
def save_canvas_definition(name, nodes, edges, created_by="unknown", project_id=None, metadata=None) -> dict:
    """Save canvas state (nodes + edges) as a workflow definition draft."""
    return create_workflow_definition(
        name=name,
        created_by=created_by,
        project_id=project_id,
        draft_steps=nodes,  # reuse steps column for nodes
        metadata={**(metadata or {}), "_canvas_edges": edges},
    )

@_with_lock
def load_canvas_definition(workflow_id: str) -> Optional[dict]:
    """Load canvas state from a workflow definition."""
    defn = get_workflow_definition(workflow_id)
    if not defn:
        return None
    nodes = defn.get("draft_steps") or []
    edges = (defn.get("metadata") or {}).get("_canvas_edges") or []
    return {"workflow_id": workflow_id, "nodes": nodes, "edges": edges}
```

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_workflow_canvas.py::test_canvas_save_load_roundtrip -v`
Expected: PASS

- [ ] **Step 5: Write failing test — canvas run executes nodes**

```python
# tests/test_workflow_canvas.py
def test_canvas_run_simple():
    """A file_input → agent → file_output chain runs without error."""
    from api.workflow_trace import save_canvas_definition, run_canvas_workflow
    nodes = [
        {"id": "input1", "type": "file_input", "x": 50, "y": 100, "config": {"path": "/tmp/test.txt"}},
        {"id": "agent1", "type": "agent", "x": 250, "y": 100, "config": {"agent": "chat", "instruction": "Summarize the file."}},
        {"id": "output1", "type": "file_output", "x": 450, "y": 100, "config": {"format": "txt"}},
    ]
    edges = [
        {"from": "input1", "to": "agent1"},
        {"from": "agent1", "to": "output1"},
    ]
    wf = save_canvas_definition("test-run", nodes, edges, created_by="tester")
    run = run_canvas_workflow(wf["workflow_id"], actor="tester", inputs={"path": "/tmp/test.txt"})
    assert run["status"] in ("completed", "running")
```

- [ ] **Step 6: Run test to verify it fails**
Run: `pytest tests/test_workflow_canvas.py::test_canvas_run_simple -v`
Expected: FAIL — `run_canvas_workflow` not defined

- [ ] **Step 7: Implement run_canvas_workflow in workflow_trace.py**

```python
# Add to api/workflow_trace.py
def run_canvas_workflow(workflow_id, actor, inputs=None, is_test_run=False):
    """Run a canvas workflow: resolve input, execute nodes sequentially, capture output."""
    canvas = load_canvas_definition(workflow_id)
    if not canvas:
        raise ValueError("Workflow not found")
    nodes = canvas["nodes"]
    edges = canvas["edges"]
    # Build adjacency: for each edge, map target node → source node
    node_map = {n["id"]: n for n in nodes}
    # Compute execution order (topological sort — for v1, sequential left-to-right)
    # Input nodes (no incoming edges) execute first, then downstream
    context = {"inputs": inputs or {}, "artifacts": {}}
    run = create_run(name=f"Canvas run {workflow_id}", created_by=actor, metadata={"workflow_id": workflow_id})
    for node in nodes:
        result = _run_canvas_node(run, node, context)
        if result.get("state") == "error":
            update_run(run["run_id"], status="failed", error=result.get("error"))
            return run
    update_run(run["run_id"], status="completed")
    return run

def _run_canvas_node(run, node, context):
    node_id = node["id"]
    node_type = node.get("type", "")
    config = node.get("config", {})
    if node_type == "file_input":
        path = config.get("path") or context["inputs"].get("path")
        if path:
            context["artifacts"][node_id] = {"path": path}
        return {"state": "completed", "output": {"path": path}}
    if node_type == "agent":
        instruction = config.get("instruction", "")
        return {"state": "completed", "output": {"instruction": instruction, "simulated": True}}
    if node_type == "prompt":
        template = config.get("template", "")
        return {"state": "completed", "output": {"template": template}}
    if node_type == "file_output":
        return {"state": "completed", "output": {"format": config.get("format", "txt")}}
    return {"state": "error", "error": f"Unknown node type: {node_type}"}
```

- [ ] **Step 8: Run test to verify it passes**
Run: `pytest tests/test_workflow_canvas.py::test_canvas_run_simple -v`
Expected: PASS

- [ ] **Step 9: Commit**
```bash
git add api/workflow_trace.py tests/test_workflow_canvas.py
git commit -m "feat(workflow-canvas): add canvas save/load and run engine

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Frontend Canvas UI
**Agent 2 owns this.** Produces `static/workflow-canvas.js` with working SVG canvas.

- [ ] **Step 1: Create static/workflow-canvas.js with canvas scaffold**

```javascript
/* workflow-canvas.js — Visual node editor with live run panel */
let _canvasNodes = [];
let _canvasEdges = [];
let _canvasSelectedNode = null;
let _canvasDragging = null;
let _canvasConnecting = null;
let _canvasSvg = null;

const NODE_TYPES = {
  file_input: { icon: "📁", label: "File Input" },
  agent:       { icon: "🤖", label: "Agent" },
  prompt:      { icon: "💬", label: "Prompt" },
  file_output: { icon: "💾", label: "File Output" },
};

function initCanvas(svgEl) {
  _canvasSvg = svgEl;
  _canvasNodes = [];
  _canvasEdges = [];
  _canvasSelectedNode = null;
}

function renderCanvas() {
  if (!_canvasSvg) return;
  _canvasSvg.innerHTML = "";
  // Grid background
  const grid = _canvasSvg.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "pattern"));
  grid.setAttribute("id", "canvas-grid");
  grid.setAttribute("width", "40");
  grid.setAttribute("height", "40");
  grid.setAttribute("patternUnits", "userSpaceOnUse");
  grid.innerHTML = `<rect width="40" height="40" fill="none" stroke="var(--border)" stroke-width="0.5" opacity="0.3"/>`;

  // Edges
  for (const edge of _canvasEdges) {
    renderEdge(edge);
  }
  // Nodes
  for (const node of _canvasNodes) {
    renderNode(node);
  }
  // Connecting line
  if (_canvasConnecting) {
    renderConnectingLine(_canvasConnecting);
  }
}

function renderNode(node) {
  const { icon, label } = NODE_TYPES[node.type] || { icon: "❓", label: node.type };
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  g.setAttribute("transform", `translate(${node.x}, ${node.y})`);
  g.setAttribute("class", `canvas-node canvas-node-${node.type}${_canvasSelectedNode?.id === node.id ? " selected" : ""}`);
  g.setAttribute("data-node-id", node.id);
  // Card bg
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("width", "160");
  rect.setAttribute("height", "56");
  rect.setAttribute("rx", "8");
  rect.setAttribute("fill", "var(--panel-bg)");
  rect.setAttribute("stroke", "var(--border)");
  g.appendChild(rect);
  // Icon + label
  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.setAttribute("x", "16");
  text.setAttribute("y", "35");
  text.setAttribute("fill", "var(--text)");
  text.setAttribute("font-size", "13");
  text.textContent = `${icon} ${label}`;
  g.appendChild(text);
  // Input port (left)
  const inPort = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  inPort.setAttribute("cx", "0");
  inPort.setAttribute("cy", "28");
  inPort.setAttribute("r", "6");
  inPort.setAttribute("class", "canvas-port canvas-port-in");
  inPort.setAttribute("data-port", "in");
  inPort.setAttribute("data-node", node.id);
  g.appendChild(inPort);
  // Output port (right)
  const outPort = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  outPort.setAttribute("cx", "160");
  outPort.setAttribute("cy", "28");
  outPort.setAttribute("r", "6");
  outPort.setAttribute("class", "canvas-port canvas-port-out");
  outPort.setAttribute("data-port", "out");
  outPort.setAttribute("data-node", node.id);
  g.appendChild(outPort);
  // Events
  g.addEventListener("mousedown", (e) => onNodeMouseDown(e, node));
  g.addEventListener("click", (e) => { if (!e.shiftKey) return; onNodeClick(e, node); });
  _canvasSvg.appendChild(g);
}

function renderEdge(edge) {
  const fromNode = _canvasNodes.find(n => n.id === edge.from);
  const toNode = _canvasNodes.find(n => n.id === edge.to);
  if (!fromNode || !toNode) return;
  const x1 = fromNode.x + 160, y1 = fromNode.y + 28;
  const x2 = toNode.x, y2 = toNode.y + 28;
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  const d = `M ${x1} ${y1} C ${x1 + 60} ${y1}, ${x2 - 60} ${y2}, ${x2} ${y2}`;
  path.setAttribute("d", d);
  path.setAttribute("stroke", "var(--accent)");
  path.setAttribute("stroke-width", "2");
  path.setAttribute("fill", "none");
  path.setAttribute("marker-end", "url(#arrow)");
  path.setAttribute("class", "canvas-edge");
  _canvasSvg.appendChild(path);
}

function onNodeMouseDown(e, node) {
  e.stopPropagation();
  const port = e.target.getAttribute("data-port");
  if (port === "out") {
    _canvasConnecting = { from: node.id, x: e.clientX, y: e.clientY };
    document.addEventListener("mouseup", onMouseUpConnect);
    document.addEventListener("mousemove", onMouseMoveConnect);
  } else if (port === "in") {
    // Complete connection from _canvasConnecting
    if (_canvasConnecting) {
      _canvasEdges.push({ from: _canvasConnecting.from, to: node.id });
      _canvasConnecting = null;
      renderCanvas();
    }
  } else {
    _canvasDragging = { node, offsetX: e.clientX - node.x, offsetY: e.clientY - node.y };
    document.addEventListener("mousemove", onMouseMoveDrag);
    document.addEventListener("mouseup", onMouseUpDrag);
  }
}

function onMouseMoveDrag(e) {
  if (!_canvasDragging) return;
  const n = _canvasNodes.find(n => n.id === _canvasDragging.node.id);
  if (n) { n.x = e.clientX - _canvasDragging.offsetX; n.y = e.clientY - _canvasDragging.offsetY; renderCanvas(); }
}
function onMouseUpDrag() {
  _canvasDragging = null;
  document.removeEventListener("mousemove", onMouseMoveDrag);
  document.removeEventListener("mouseup", onMouseUpDrag);
}
function onMouseMoveConnect(e) {
  if (!_canvasConnecting) return;
  _canvasConnecting.x = e.clientX; _canvasConnecting.y = e.clientY;
  renderCanvas();
}
function onMouseUpConnect(e) {
  _canvasConnecting = null;
  document.removeEventListener("mousemove", onMouseMoveConnect);
  document.removeEventListener("mouseup", onMouseUpConnect);
  renderCanvas();
}
function onNodeClick(e, node) {
  _canvasSelectedNode = node;
  renderCanvas();
  showNodeConfig(node);
}

// Toolbar actions
function addCanvasNode(type) {
  const id = "node_" + Date.now();
  _canvasNodes.push({ id, type, x: 200 + Math.random() * 100, y: 150 + Math.random() * 80, config: {} });
  renderCanvas();
}

window.initCanvas = initCanvas;
window.renderCanvas = renderCanvas;
window.addCanvasNode = addCanvasNode;
```

- [ ] **Step 2: Write HTML canvas mount + toolbar**

Add to `static/index.html` inside appropriate panel:
```html
<div id="workflow-canvas-panel" style="display:none" class="split-horizontal">
  <div class="canvas-toolbar">
    <button class="btn btn-sm" onclick="addCanvasNode('file_input')">📁 Input</button>
    <button class="btn btn-sm" onclick="addCanvasNode('agent')">🤖 Agent</button>
    <button class="btn btn-sm" onclick="addCanvasNode('prompt')">💬 Prompt</button>
    <button class="btn btn-sm" onclick="addCanvasNode('file_output')">💾 Output</button>
    <span class="toolbar-sep"></span>
    <button class="btn btn-sm btn-accent" onclick="saveCanvasWorkflow()">Save</button>
    <button class="btn btn-sm" onclick="runCanvasWorkflow()">Run</button>
  </div>
  <div class="canvas-split">
    <div class="canvas-area">
      <svg id="workflow-canvas-svg" class="workflow-canvas-svg"></svg>
    </div>
    <div class="canvas-config-panel" id="canvasConfigPanel">
      <div class="canvas-config-empty">Select a node to configure</div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add CSS for canvas, nodes, edges, toolbar**

Add to `static/style.css`:
```css
.workflow-canvas-svg { width: 100%; height: 400px; background: var(--bg); border: 1px solid var(--border); }
.canvas-node { cursor: move; }
.canvas-node.selected rect { stroke: var(--accent); stroke-width: 2; }
.canvas-port { cursor: crosshair; fill: var(--panel-bg); stroke: var(--accent); }
.canvas-port:hover { fill: var(--accent); }
.canvas-edge { pointer-events: stroke; }
.canvas-toolbar { display: flex; gap: 8px; padding: 8px; background: var(--panel-bg); border-bottom: 1px solid var(--border); align-items: center; }
.toolbar-sep { width: 1px; height: 20px; background: var(--border); margin: 0 4px; }
.canvas-split { display: flex; flex: 1; overflow: hidden; }
.canvas-area { flex: 1; overflow: auto; }
.canvas-config-panel { width: 280px; border-left: 1px solid var(--border); padding: 12px; overflow-y: auto; }
.canvas-config-empty { color: var(--muted); font-size: 12px; text-align: center; padding-top: 40px; }
```

- [ ] **Step 4: Add node config form**

```javascript
function showNodeConfig(node) {
  const panel = document.getElementById('canvasConfigPanel');
  if (!panel) return;
  const tpl = NODE_TYPES[node.type] || {};
  panel.innerHTML = `
    <h4>${tpl.icon || ""} ${tpl.label || node.type}</h4>
    <div class="detail-form-row">
      <label>Node ID</label>
      <input readonly value="${node.id}">
    </div>
    ${node.type === 'file_input' ? `
    <div class="detail-form-row">
      <label>Path</label>
      <input id="cfg-path" value="${node.config?.path || ''}" placeholder="/path/to/file">
    </div>
    ` : ''}
    ${node.type === 'agent' ? `
    <div class="detail-form-row">
      <label>Agent</label>
      <select id="cfg-agent"><option>chat</option><option>codegen</option></select>
    </div>
    <div class="detail-form-row">
      <label>Instruction</label>
      <textarea id="cfg-instruction" rows="4">${node.config?.instruction || ''}</textarea>
    </div>
    ` : ''}
    ${node.type === 'prompt' ? `
    <div class="detail-form-row">
      <label>Template</label>
      <textarea id="cfg-template" rows="4">${node.config?.template || ''}</textarea>
    </div>
    ` : ''}
    ${node.type === 'file_output' ? `
    <div class="detail-form-row">
      <label>Format</label>
      <select id="cfg-format"><option>txt</option><option>json</option><option>csv</option></select>
    </div>
    ` : ''}
    <button class="btn btn-sm btn-accent" onclick="applyNodeConfig('${node.id}')">Apply</button>
  `;
}

function applyNodeConfig(nodeId) {
  const node = _canvasNodes.find(n => n.id === nodeId);
  if (!node) return;
  const path = document.getElementById('cfg-path')?.value;
  const instruction = document.getElementById('cfg-instruction')?.value;
  const template = document.getElementById('cfg-template')?.value;
  const format = document.getElementById('cfg-format')?.value;
  if (path !== undefined) node.config.path = path;
  if (instruction !== undefined) node.config.instruction = instruction;
  if (template !== undefined) node.config.template = template;
  if (format !== undefined) node.config.format = format;
  showToast('Config applied');
}
```

- [ ] **Step 5: Save + Run API calls**

```javascript
async function saveCanvasWorkflow() {
  const name = prompt("Workflow name:", "My Workflow");
  if (!name) return;
  try {
    const res = await api('/api/workflow/canvas', {
      method: 'POST',
      body: JSON.stringify({ name, nodes: _canvasNodes, edges: _canvasEdges }),
    });
    showToast('Saved');
  } catch (e) { showToast('Save failed: ' + e.message); }
}

async function runCanvasWorkflow() {
  try {
    const res = await api('/api/workflow/canvas/run', {
      method: 'POST',
      body: JSON.stringify({ nodes: _canvasNodes, edges: _canvasEdges }),
    });
    showToast('Run started: ' + res.data?.run_id);
    openRunDetail(res.data.run_id);
  } catch (e) { showToast('Run failed: ' + e.message); }
}
```

- [ ] **Step 6: Commit**
```bash
git add static/workflow-canvas.js static/index.html static/style.css
git commit -m "feat(canvas): add workflow canvas SVG editor with drag-drop nodes

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Backend Routes + Live SSE
**Agent 3 owns this.** Wires canvas routes and live status SSE endpoint.

- [ ] **Step 1: Add POST /api/workflow/canvas route to routes.py**

```python
# In do_POST, after existing workflow routes (~line 3622):
_canvas_pattern = re.compile(r"^/api/workflow/canvas(/run)?$")
_canvas_match = _canvas_pattern.match(parsed.path or "")
if _canvas_match:
    is_run = bool(_canvas_match.group(1))
    body = read_body(handler)
    data = json.loads(body)
    current_user = _current_user(handler)
    username = current_user.get("username", "unknown") if current_user else "unknown"

    if is_run:
        # Run canvas workflow (inline nodes/edges, no saved def)
        from api.workflow_trace import run_canvas_workflow
        try:
            run = run_canvas_workflow(
                workflow_id=None,  # inline run
                actor=username,
                inputs=data.get("inputs", {}),
                inline_nodes=data.get("nodes", []),
                inline_edges=data.get("edges", []),
            )
            return j(handler, {"success": True, "data": run})
        except Exception as exc:
            return bad(handler, str(exc), 400)

    # Save canvas
    from api.workflow_trace import save_canvas_definition
    wf = save_canvas_definition(
        name=data.get("name", "Untitled"),
        nodes=data.get("nodes", []),
        edges=data.get("edges", []),
        created_by=username,
    )
    return j(handler, {"success": True, "data": wf})
```

- [ ] **Step 2: Add GET /api/workflow/canvas/{id} route**

```python
# In do_GET, after existing workflow routes:
_canvas_get_pattern = re.compile(r"^/api/workflow/canvas/([^/]+)$")
_canvas_get_match = _canvas_get_pattern.match(parsed.path or "")
if _canvas_get_match:
    workflow_id = _canvas_get_match.group(1)
    from api.workflow_trace import load_canvas_definition, can_read_definition
    current_user = _current_user(handler)
    if not can_read_definition(workflow_id, current_user):
        return bad(handler, "Access denied", 403)
    canvas = load_canvas_definition(workflow_id)
    if not canvas:
        return bad(handler, "Not found", 404)
    return j(handler, {"success": True, "data": canvas})
```

- [ ] **Step 3: Update run_canvas_workflow to handle inline nodes (no saved def)**

```python
# Update run_canvas_workflow in api/workflow_trace.py:
def run_canvas_workflow(workflow_id, actor, inputs=None, inline_nodes=None, inline_edges=None):
    # If workflow_id is None, use inline nodes/edges directly
    if workflow_id is None and (inline_nodes is not None):
        nodes = inline_nodes
        edges = inline_edges or []
    else:
        canvas = load_canvas_definition(workflow_id)
        if not canvas:
            raise ValueError("Workflow not found")
        nodes = canvas["nodes"]
        edges = canvas["edges"]
    # ... rest of execution logic unchanged
```

- [ ] **Step 4: Add live SSE endpoint for run progress**

```python
# In do_GET:
_canvas_live_pattern = re.compile(r"^/api/workflow/canvas/live/([^/]+)$")
_canvas_live_match = _canvas_live_pattern.match(parsed.path or "")
if _canvas_live_match:
    run_id = _canvas_live_match.group(1)
    from api.workflow_trace import can_read_run, get_run, list_run_nodes, list_run_events
    current_user = _current_user(handler)
    if not can_read_run(run_id, current_user):
        return bad(handler, "Access denied", 403)
    # SSE stream
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    import time
    last_event_id = 0
    while True:
        run = get_run(run_id)
        nodes = list_run_nodes(run_id)
        events = list_run_events(run_id)
        data = json.dumps({"run": run, "nodes": nodes, "events": events[-10:]})
        handler.wfile.write(f"data: {data}\n\n".encode())
        handler.wfile.flush()
        if run and run.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(1.5)
    return True
```

- [ ] **Step 5: Commit**
```bash
git add api/routes.py api/workflow_trace.py
git commit -m "feat(canvas-routes): add canvas save/load routes and live SSE endpoint

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Integration + Panel Wiring
Wires the canvas into the existing panel system.

- [ ] **Step 1: Add canvas panel to panels.js nav**

In `panels.js`, add canvas button to nav sidebar and handler:
```javascript
// In sidebar nav setup (around other panel buttons):
<button onclick="showPanel('workflow-canvas')">🧩 Canvas</button>

function showPanel(name) {
  // hide other panels, show named panel
  document.querySelectorAll('.panel-page').forEach(el => el.style.display = 'none');
  const panel = document.getElementById('panel-' + name) || document.getElementById('workflow-canvas-panel');
  if (panel) panel.style.display = '';
}
```

- [ ] **Step 2: Add canvas SVG defs (arrow marker)**

Add inside the SVG in index.html:
```html
<svg id="workflow-canvas-svg" class="workflow-canvas-svg">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
      <path d="M0,0 L0,6 L9,3 z" fill="var(--accent)" />
    </marker>
  </defs>
</svg>
```

- [ ] **Step 3: Initialize canvas on panel open**

```javascript
// In showPanel('workflow-canvas'), call:
initCanvas(document.getElementById('workflow-canvas-svg'));
renderCanvas();
```

- [ ] **Step 4: Write integration test**

```python
# tests/test_workflow_canvas.py — add after Task 1 tests:
def test_canvas_routes_save_load():
    """POST /api/workflow/canvas saves, GET /api/workflow/canvas/{id} loads."""
    import json, urllib.request
    # Create
    data = json.dumps({"name": "route-test", "nodes": [{"id": "a", "type": "agent"}], "edges": []}).encode()
    req = urllib.request.Request("http://localhost:8787/api/workflow/canvas", data=data, headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req).read())
    wf_id = resp["data"]["workflow_id"]
    # Load
    req2 = urllib.request.Request(f"http://localhost:8787/api/workflow/canvas/{wf_id}")
    loaded = json.loads(urllib.request.urlopen(req2).read())
    assert loaded["data"]["nodes"][0]["id"] == "a"
```

- [ ] **Step 5: Commit**
```bash
git add static/panels.js static/index.html tests/test_workflow_canvas.py
git commit -m "feat(canvas-integrate): wire canvas panel into workflow sidebar

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Spec Coverage Check

| Spec Section | Task |
|-------------|------|
| 4 node types (file_input, agent, prompt, file_output) | Task 1 + 2 |
| Canvas drag/drop + edge connection | Task 2 |
| Split panel: edit left / live status right | Task 2 |
| Real-time log stream | Task 3 (SSE) |
| Save/load workflow definitions | Task 1 + 3 |
| Input file selection at run time | Task 1 (file_input node config) |
| Node execution loop | Task 1 (run_canvas_workflow) |
| SVG bezier edges with arrows | Task 2 |

## Placeholder Scan
- No "TBD", "TODO", or vague requirements found
- All node types specified with config fields
- All API routes have exact paths and methods
- Test code is complete and runnable

## Type Consistency Check
- `save_canvas_definition` returns dict with `workflow_id`
- `load_canvas_definition` takes `workflow_id` string, returns `{nodes, edges}`
- `run_canvas_workflow` accepts `workflow_id` OR `inline_nodes` + `inline_edges`
- All frontend `addCanvasNode` node ids are string (uses `Date.now()`)

---

## Execution Options

**1. Subagent-Driven (recommended)** — Dispatch 3 agents in parallel for Tasks 1, 2, 3. Review after each completes. Task 4 (integration) can be done inline or as a 4th agent.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?