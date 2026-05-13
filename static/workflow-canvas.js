/* workflow-canvas.js — Visual node editor with drag-drop + bezier edges */
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
  _canvasDragging = null;
  _canvasConnecting = null;
  renderCanvas();
}

function renderCanvas() {
  if (!_canvasSvg) return;
  _canvasSvg.innerHTML = "";

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");

  const grid = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
  grid.setAttribute("id", "canvas-grid");
  grid.setAttribute("width", "40");
  grid.setAttribute("height", "40");
  grid.setAttribute("patternUnits", "userSpaceOnUse");
  grid.innerHTML = `<rect width="40" height="40" fill="none" stroke="#333" stroke-width="0.5" opacity="0.3"/>`;
  defs.appendChild(grid);

  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", "arrow");
  marker.setAttribute("markerWidth", "10");
  marker.setAttribute("markerHeight", "10");
  marker.setAttribute("refX", "9");
  marker.setAttribute("refY", "3");
  marker.setAttribute("orient", "auto");
  marker.innerHTML = `<path d="M0,0 L0,6 L9,3 z" fill="var(--accent)"/>`;
  defs.appendChild(marker);
  _canvasSvg.appendChild(defs);

  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", "100%");
  bg.setAttribute("height", "100%");
  bg.setAttribute("fill", "url(#canvas-grid)");
  bg.style.cursor = "crosshair";
  _canvasSvg.appendChild(bg);

  for (const edge of _canvasEdges) renderEdge(edge);
  for (const node of _canvasNodes) renderNode(node);
  if (_canvasConnecting) renderConnectingLine(_canvasConnecting);
}

function renderNode(node) {
  const { icon, label } = NODE_TYPES[node.type] || { icon: "❓", label: node.type };
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  g.setAttribute("transform", `translate(${node.x}, ${node.y})`);
  const selClass = _canvasSelectedNode?.id === node.id ? " selected" : "";
  g.setAttribute("class", `canvas-node canvas-node-${node.type}${selClass}`);
  g.setAttribute("data-node-id", node.id);

  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("width", "160");
  rect.setAttribute("height", "56");
  rect.setAttribute("rx", "8");
  rect.setAttribute("fill", "var(--panel-bg)");
  rect.setAttribute("stroke", "var(--border)");
  g.appendChild(rect);

  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.setAttribute("x", "16");
  text.setAttribute("y", "35");
  text.setAttribute("fill", "var(--text)");
  text.setAttribute("font-size", "13");
  text.textContent = `${icon} ${label}`;
  g.appendChild(text);

  if (node.type !== "file_input") {
    const inPort = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    inPort.setAttribute("cx", "0");
    inPort.setAttribute("cy", "28");
    inPort.setAttribute("r", "6");
    inPort.setAttribute("class", "canvas-port canvas-port-in");
    inPort.setAttribute("data-port", "in");
    inPort.setAttribute("data-node", node.id);
    g.appendChild(inPort);
  }

  if (node.type !== "file_output") {
    const outPort = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    outPort.setAttribute("cx", "160");
    outPort.setAttribute("cy", "28");
    outPort.setAttribute("r", "6");
    outPort.setAttribute("class", "canvas-port canvas-port-out");
    outPort.setAttribute("data-port", "out");
    outPort.setAttribute("data-node", node.id);
    g.appendChild(outPort);
  }

  g.addEventListener("mousedown", (e) => onNodeMouseDown(e, node));
  g.addEventListener("click", (e) => { if (e.shiftKey) return; onNodeClick(e, node); });
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
    _canvasConnecting = { from: node.id };
    document.addEventListener("mouseup", onMouseUpConnect);
    document.addEventListener("mousemove", onMouseMoveConnect);
  } else if (port === "in") {
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
  _canvasConnecting.x = e.clientX;
  _canvasConnecting.y = e.clientY;
  renderCanvas();
}

function onMouseUpConnect() {
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

function renderConnectingLine(conn) {
  const fromNode = _canvasNodes.find(n => n.id === conn.from);
  if (!fromNode) return;
  const x1 = fromNode.x + 160, y1 = fromNode.y + 28;
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", x1); line.setAttribute("y1", y1);
  line.setAttribute("x2", conn.x || x1); line.setAttribute("y2", conn.y || y1);
  line.setAttribute("stroke", "var(--accent)");
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-dasharray", "4");
  _canvasSvg.appendChild(line);
}

function addCanvasNode(type) {
  const id = "node_" + Date.now();
  _canvasNodes.push({ id, type, x: 200 + Math.random() * 100, y: 150 + Math.random() * 80, config: {} });
  renderCanvas();
}

function showNodeConfig(node) {
  const panel = document.getElementById("canvasConfigPanel");
  if (!panel) return;
  const tpl = NODE_TYPES[node.type] || {};
  let html = `<h4>${tpl.icon || ""} ${tpl.label || node.type}</h4>`;
  html += `<div class="detail-form-row"><label>Node ID</label><input readonly value="${node.id}"></div>`;

  if (node.type === "file_input") {
    html += `<div class="detail-form-row"><label>Path</label><input id="cfg-path" value="${node.config?.path || ""}" placeholder="/path/to/file"></div>`;
  } else if (node.type === "agent") {
    html += `<div class="detail-form-row"><label>Agent</label><select id="cfg-agent"><option value="chat" ${node.config?.agent === "chat" ? "selected" : ""}>chat</option><option value="codegen" ${node.config?.agent === "codegen" ? "selected" : ""}>codegen</option></select></div>`;
    html += `<div class="detail-form-row"><label>Instruction</label><textarea id="cfg-instruction" rows="4">${node.config?.instruction || ""}</textarea></div>`;
  } else if (node.type === "prompt") {
    html += `<div class="detail-form-row"><label>Template</label><textarea id="cfg-template" rows="4">${node.config?.template || ""}</textarea></div>`;
  } else if (node.type === "file_output") {
    html += `<div class="detail-form-row"><label>Format</label><select id="cfg-format"><option value="txt" ${node.config?.format === "txt" ? "selected" : ""}>TXT</option><option value="json" ${node.config?.format === "json" ? "selected" : ""}>JSON</option><option value="csv" ${node.config?.format === "csv" ? "selected" : ""}>CSV</option></select></div>`;
  }

  html += `<button class="btn btn-sm btn-accent" onclick="applyNodeConfig('${node.id}')">Apply</button>`;
  panel.innerHTML = html;
}

function applyNodeConfig(nodeId) {
  const node = _canvasNodes.find(n => n.id === nodeId);
  if (!node) return;
  if (document.getElementById("cfg-path")) node.config.path = document.getElementById("cfg-path").value;
  if (document.getElementById("cfg-instruction")) node.config.instruction = document.getElementById("cfg-instruction").value;
  if (document.getElementById("cfg-template")) node.config.template = document.getElementById("cfg-template").value;
  if (document.getElementById("cfg-format")) node.config.format = document.getElementById("cfg-format").value;
  if (document.getElementById("cfg-agent")) node.config.agent = document.getElementById("cfg-agent").value;
  showToast("Config applied");
}

async function saveCanvasWorkflow() {
  const name = window.prompt("Workflow name:", "My Workflow");
  if (!name) return;
  try {
    const res = await api("/api/workflow/canvas", {
      method: "POST",
      body: JSON.stringify({ name, nodes: _canvasNodes, edges: _canvasEdges }),
    });
    showToast("Saved");
  } catch (e) { showToast("Save failed: " + e.message); }
}

async function runCanvasWorkflow() {
  try {
    const res = await api("/api/workflow/canvas/run", {
      method: "POST",
      body: JSON.stringify({ nodes: _canvasNodes, edges: _canvasEdges }),
    });
    showToast("Run started: " + (res.data?.run_id || ""));
    if (res.data?.run_id) openRunDetail(res.data.run_id);
  } catch (e) { showToast("Run failed: " + e.message); }
}

function openCanvasWorkflow(wfId) {
  api(`/api/workflow/canvas/${wfId}`).then(res => {
    if (res.data) {
      _canvasNodes = res.data.nodes || [];
      _canvasEdges = res.data.edges || [];
      _canvasSelectedNode = null;
      initCanvas(document.getElementById("workflow-canvas-svg"));
    }
  }).catch(e => showToast("Failed to load: " + e.message));
}

function switchWorkflowView(view) {
  if (view === "canvas") {
    document.getElementById("workflowList").style.display = "none";
    const canvasPanel = document.getElementById("workflow-canvas-panel");
    if (canvasPanel) {
      canvasPanel.style.display = "flex";
      initCanvas(document.getElementById("workflow-canvas-svg"));
    }
  } else {
    document.getElementById("workflowList").style.display = "";
    const canvasPanel = document.getElementById("workflow-canvas-panel");
    if (canvasPanel) canvasPanel.style.display = "none";
    _canvasNodes = [];
    _canvasEdges = [];
    _canvasSelectedNode = null;
  }
}

window.initCanvas = initCanvas;
window.renderCanvas = renderCanvas;
window.addCanvasNode = addCanvasNode;
window.showNodeConfig = showNodeConfig;
window.applyNodeConfig = applyNodeConfig;
window.saveCanvasWorkflow = saveCanvasWorkflow;
window.runCanvasWorkflow = runCanvasWorkflow;
window.openCanvasWorkflow = openCanvasWorkflow;