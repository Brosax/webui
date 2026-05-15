/* workflow-canvas.js - integrated SVG workflow editor */
let _canvasNodes = [];
let _canvasEdges = [];
let _canvasSelectedNode = null;
let _canvasSelectedEdge = null;
let _canvasDragging = null;
let _canvasConnecting = null;
let _canvasPanning = null;
let _canvasSvg = null;
let _canvasUndo = [];
let _canvasRedo = [];
let _canvasClipboard = null;
let _canvasContextPosition = null;
let _canvasView = { zoom: 1, scroll: { x: 0, y: 0 }, selectedNodeIds: [] };

const WORKFLOW_NODE_WIDTH = 220;
const WORKFLOW_NODE_HEIGHT = 84;

function _registryNode(type) {
  return window.WorkflowNodeRegistry?.get(type) || { type, label: type || "Node", accent: "var(--accent)", inputs: [{ id: "in", label: "Input" }], outputs: [{ id: "out", label: "Output" }], parameters: [] };
}

function _pushCanvasUndo() {
  _canvasUndo.push(JSON.stringify({ nodes: _canvasNodes, edges: _canvasEdges, view: _canvasView }));
  if (_canvasUndo.length > 60) _canvasUndo.shift();
  _canvasRedo = [];
}

function initCanvas(svgEl, preserveState = false) {
  closeWorkflowNodeMenu();
  _canvasSvg = svgEl;
  if (!preserveState) {
    _canvasNodes = [];
    _canvasEdges = [];
    _canvasSelectedNode = null;
    _canvasSelectedEdge = null;
  }
  _canvasDragging = null;
  _canvasConnecting = null;
  _canvasPanning = null;
  if (_canvasSvg) {
    _canvasSvg.onmousedown = onCanvasMouseDown;
    _canvasSvg.onmousemove = onCanvasMouseMove;
    _canvasSvg.onmouseup = onCanvasMouseUp;
    _canvasSvg.onwheel = onCanvasWheel;
    _canvasSvg.oncontextmenu = onCanvasContextMenu;
  }
  document.removeEventListener("keydown", onWorkflowCanvasKeydown);
  document.addEventListener("keydown", onWorkflowCanvasKeydown);
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
}

function renderCanvas() {
  if (!_canvasSvg) return;
  _canvasSvg.innerHTML = "";
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.innerHTML = `
    <pattern id="workflow-canvas-grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <circle cx="1" cy="1" r="1" fill="currentColor" opacity="0.58"></circle>
    </pattern>
    <marker id="workflow-arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
      <path d="M0,0 L0,6 L9,3 z" fill="currentColor"></path>
    </marker>`;
  _canvasSvg.appendChild(defs);

  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", "100%");
  bg.setAttribute("height", "100%");
  bg.setAttribute("class", "workflow-canvas-bg");
  _canvasSvg.appendChild(bg);

  const viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.setAttribute("class", "workflow-canvas-viewport");
  viewport.setAttribute("transform", `translate(${_canvasView.scroll?.x || 0},${_canvasView.scroll?.y || 0}) scale(${_canvasView.zoom || 1})`);
  _canvasSvg.appendChild(viewport);

  _canvasEdges.forEach((edge) => renderEdge(edge, viewport));
  _canvasNodes.forEach((node) => renderNode(node, viewport));
  if (_canvasConnecting) renderConnectingLine(_canvasConnecting, viewport);
  renderMiniMap();
}

function _portPosition(node, handle, direction) {
  const def = _registryNode(node.type);
  const list = direction === "out" ? (def.outputs || []) : (def.inputs || []);
  const index = Math.max(0, list.findIndex((port) => port.id === handle));
  const count = Math.max(1, list.length);
  const y = node.position.y + 30 + ((index + 1) * (WORKFLOW_NODE_HEIGHT - 42)) / (count + 1);
  const x = direction === "out" ? node.position.x + WORKFLOW_NODE_WIDTH : node.position.x;
  return { x, y };
}

function renderNode(node, parent) {
  const def = _registryNode(node.type);
  const selected = _canvasSelectedNode?.id === node.id;
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  g.setAttribute("transform", `translate(${node.position.x}, ${node.position.y})`);
  g.setAttribute("class", `canvas-node workflow-node${selected ? " selected" : ""}${node.disabled ? " disabled" : ""}`);
  g.setAttribute("data-node-id", node.id);

  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("width", WORKFLOW_NODE_WIDTH);
  rect.setAttribute("height", WORKFLOW_NODE_HEIGHT);
  rect.setAttribute("rx", "2");
  rect.setAttribute("class", "workflow-node-box");
  rect.setAttribute("style", `stroke:${def.accent || "var(--accent)"}`);
  g.appendChild(rect);

  const accent = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  accent.setAttribute("width", WORKFLOW_NODE_WIDTH);
  accent.setAttribute("height", "4");
  accent.setAttribute("fill", def.accent || "var(--accent)");
  g.appendChild(accent);

  const iconBox = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  iconBox.setAttribute("x", "14");
  iconBox.setAttribute("y", "17");
  iconBox.setAttribute("width", "22");
  iconBox.setAttribute("height", "22");
  iconBox.setAttribute("rx", "2");
  iconBox.setAttribute("class", "workflow-node-icon-box");
  g.appendChild(iconBox);

  const icon = document.createElementNS("http://www.w3.org/2000/svg", "text");
  icon.setAttribute("x", "25");
  icon.setAttribute("y", "32");
  icon.setAttribute("text-anchor", "middle");
  icon.setAttribute("class", "workflow-node-icon");
  icon.setAttribute("style", `fill:${def.accent || "var(--accent)"}`);
  icon.textContent = _nodeGlyph(node.type);
  g.appendChild(icon);

  const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
  title.setAttribute("x", "45");
  title.setAttribute("y", "31");
  title.setAttribute("class", "workflow-node-title");
  title.textContent = node.name || def.label || node.type;
  g.appendChild(title);

  const type = document.createElementNS("http://www.w3.org/2000/svg", "text");
  type.setAttribute("x", "14");
  type.setAttribute("y", "59");
  type.setAttribute("class", "workflow-node-type");
  type.textContent = _nodeDescription(node, def);
  g.appendChild(type);

  (def.inputs || []).forEach((port, index) => renderPort(g, node, port, "in", index, def.inputs.length));
  (def.outputs || []).forEach((port, index) => renderPort(g, node, port, "out", index, def.outputs.length));

  g.addEventListener("mousedown", (event) => onNodeMouseDown(event, node));
  g.addEventListener("click", (event) => onNodeClick(event, node));
  parent.appendChild(g);
}

function renderPort(group, node, port, direction, index, count) {
  const y = 30 + ((index + 1) * (WORKFLOW_NODE_HEIGHT - 42)) / (Math.max(1, count) + 1);
  const x = direction === "out" ? WORKFLOW_NODE_WIDTH : 0;
  const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  circle.setAttribute("cx", x);
  circle.setAttribute("cy", y);
  circle.setAttribute("r", "6");
  circle.setAttribute("class", `canvas-port canvas-port-${direction}`);
  circle.setAttribute("data-node", node.id);
  circle.setAttribute("data-port", port.id);
  circle.setAttribute("data-direction", direction);
  group.appendChild(circle);

  const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
  label.setAttribute("x", direction === "out" ? WORKFLOW_NODE_WIDTH - 10 : 10);
  label.setAttribute("y", WORKFLOW_NODE_HEIGHT - 8);
  label.setAttribute("text-anchor", direction === "out" ? "end" : "start");
  label.setAttribute("class", "workflow-port-label");
  label.textContent = direction === "out" ? "Out" : "In";
  group.appendChild(label);
}

function _nodeGlyph(type) {
  if (String(type).startsWith("trigger.")) return "T";
  if (String(type).startsWith("agent.")) return "A";
  if (String(type).startsWith("control.")) return "C";
  if (String(type).startsWith("output.")) return "O";
  if (String(type).startsWith("utility.")) return "U";
  if (String(type).startsWith("file.")) return "F";
  if (String(type).startsWith("mcp.")) return "M";
  return "N";
}

function _nodeDescription(node, def) {
  const params = node.parameters || {};
  if (params.instruction) return String(params.instruction).slice(0, 58);
  if (params.notes) return String(params.notes).slice(0, 58);
  if (params.url) return String(params.url).slice(0, 58);
  if (params.key) return `${params.key}: ${params.value || ""}`.slice(0, 58);
  return def.label || node.type;
}

function _edgeKey(edge) {
  if (!edge) return "";
  return edge.id || [
    edge.source || edge.from || "",
    edge.sourceHandle || "out",
    edge.target || edge.to || "",
    edge.targetHandle || "in",
  ].join("::");
}

function renderEdge(edge, parent) {
  const source = _canvasNodes.find((node) => node.id === (edge.source || edge.from));
  const target = _canvasNodes.find((node) => node.id === (edge.target || edge.to));
  if (!source || !target) return;
  const p1 = _portPosition(source, edge.sourceHandle || "out", "out");
  const p2 = _portPosition(target, edge.targetHandle || "in", "in");
  const dx = Math.max(60, Math.abs(p2.x - p1.x) / 2);
  const d = `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;
  const selectEdge = (event) => {
    event.stopPropagation();
    _canvasSelectedEdge = edge;
    _canvasSelectedNode = null;
    renderCanvas();
    renderWorkflowProperties();
  };
  const hitPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  hitPath.setAttribute("d", d);
  hitPath.setAttribute("class", "canvas-edge-hit");
  hitPath.addEventListener("click", selectEdge);
  parent.appendChild(hitPath);

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  path.setAttribute("class", `canvas-edge${_edgeKey(_canvasSelectedEdge) === _edgeKey(edge) ? " selected" : ""}`);
  path.setAttribute("marker-end", "url(#workflow-arrow)");
  path.addEventListener("click", selectEdge);
  parent.appendChild(path);
}

function renderConnectingLine(conn, parent) {
  const source = _canvasNodes.find((node) => node.id === conn.source);
  if (!source) return;
  const p1 = _portPosition(source, conn.sourceHandle || "out", "out");
  const p2 = _clientToCanvas(conn.clientX || 0, conn.clientY || 0);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", `M ${p1.x} ${p1.y} C ${p1.x + 80} ${p1.y}, ${p2.x - 80} ${p2.y}, ${p2.x} ${p2.y}`);
  path.setAttribute("class", "canvas-edge canvas-edge-pending");
  parent.appendChild(path);
}

function _clientToCanvas(clientX, clientY) {
  const rect = _canvasSvg?.getBoundingClientRect?.() || { left: 0, top: 0 };
  const zoom = _canvasView.zoom || 1;
  return {
    x: (clientX - rect.left - (_canvasView.scroll?.x || 0)) / zoom,
    y: (clientY - rect.top - (_canvasView.scroll?.y || 0)) / zoom,
  };
}

function onNodeMouseDown(event, node) {
  event.stopPropagation();
  if (event.button === 1) {
    startCanvasPan(event);
    return;
  }
  if (event.button !== 0) return;
  const direction = event.target.getAttribute("data-direction");
  if (direction === "out") {
    _canvasConnecting = { source: node.id, sourceHandle: event.target.getAttribute("data-port") || "out", clientX: event.clientX, clientY: event.clientY };
    return;
  }
  if (direction === "in" && _canvasConnecting) {
    addWorkflowEdge(_canvasConnecting.source, node.id, _canvasConnecting.sourceHandle, event.target.getAttribute("data-port") || "in");
    _canvasConnecting = null;
    return;
  }
  const point = _clientToCanvas(event.clientX, event.clientY);
  _canvasDragging = { nodeId: node.id, dx: point.x - node.position.x, dy: point.y - node.position.y };
}

function onCanvasMouseDown(event) {
  closeWorkflowNodeMenu();
  if (event.button === 1) {
    startCanvasPan(event);
    return;
  }
  if (event.button !== 0) return;
  if (event.target !== _canvasSvg && !event.target.classList?.contains("workflow-canvas-bg")) return;
  _canvasSelectedNode = null;
  _canvasSelectedEdge = null;
  renderCanvas();
  renderWorkflowProperties();
}

function onCanvasMouseMove(event) {
  if (_canvasPanning) {
    panCanvasTo(event);
    return;
  }
  if (_canvasConnecting) {
    _canvasConnecting.clientX = event.clientX;
    _canvasConnecting.clientY = event.clientY;
    renderCanvas();
    return;
  }
  if (!_canvasDragging) return;
  const node = _canvasNodes.find((item) => item.id === _canvasDragging.nodeId);
  if (!node) return;
  const point = _clientToCanvas(event.clientX, event.clientY);
  node.position.x = Math.round(point.x - _canvasDragging.dx);
  node.position.y = Math.round(point.y - _canvasDragging.dy);
  renderCanvas();
}

function onCanvasMouseUp(event) {
  if (_canvasPanning) {
    endCanvasPan();
    return;
  }
  if (_canvasDragging) {
    _pushCanvasUndo();
    _canvasDragging = null;
  }
  if (_canvasConnecting) {
    const target = event.target;
    if (target?.getAttribute("data-direction") === "in") {
      addWorkflowEdge(_canvasConnecting.source, target.getAttribute("data-node"), _canvasConnecting.sourceHandle, target.getAttribute("data-port") || "in");
    }
    _canvasConnecting = null;
    renderCanvas();
  }
}

function onCanvasWheel(event) {
  event.preventDefault();
  const oldZoom = _canvasView.zoom || 1;
  const point = _clientToCanvas(event.clientX, event.clientY);
  const next = oldZoom * (event.deltaY > 0 ? 0.92 : 1.08);
  const newZoom = Math.max(0.35, Math.min(2, Math.round(next * 100) / 100));
  const rect = _canvasSvg?.getBoundingClientRect?.() || { left: 0, top: 0 };
  _canvasView.zoom = newZoom;
  _canvasView.scroll = {
    x: Math.round(event.clientX - rect.left - point.x * newZoom),
    y: Math.round(event.clientY - rect.top - point.y * newZoom),
  };
  renderCanvas();
}

function startCanvasPan(event) {
  if (!_canvasSvg) return;
  event.preventDefault();
  _canvasPanning = {
    clientX: event.clientX,
    clientY: event.clientY,
    scrollX: _canvasView.scroll?.x || 0,
    scrollY: _canvasView.scroll?.y || 0,
  };
  _canvasSvg.classList.add("is-panning");
  document.addEventListener("mousemove", panCanvasTo);
  document.addEventListener("mouseup", endCanvasPan);
}

function panCanvasTo(event) {
  if (!_canvasPanning) return;
  event.preventDefault();
  _canvasView.scroll = {
    x: Math.round(_canvasPanning.scrollX + event.clientX - _canvasPanning.clientX),
    y: Math.round(_canvasPanning.scrollY + event.clientY - _canvasPanning.clientY),
  };
  renderCanvas();
}

function endCanvasPan(event) {
  if (event?.preventDefault) event.preventDefault();
  _canvasPanning = null;
  if (_canvasSvg) _canvasSvg.classList.remove("is-panning");
  document.removeEventListener("mousemove", panCanvasTo);
  document.removeEventListener("mouseup", endCanvasPan);
}

function onCanvasContextMenu(event) {
  if (!_canvasSvg) return;
  event.preventDefault();
  const point = _clientToCanvas(event.clientX, event.clientY);
  openWorkflowNodeMenu(event.clientX, event.clientY, point);
}

function openWorkflowNodeMenu(clientX, clientY, canvasPoint) {
  closeWorkflowNodeMenu();
  _canvasContextPosition = {
    x: Math.round(canvasPoint.x),
    y: Math.round(canvasPoint.y),
  };
  const menu = document.createElement("div");
  menu.id = "workflow-node-context-menu";
  menu.className = "workflow-node-context-menu";
  menu.style.left = `${clientX}px`;
  menu.style.top = `${clientY}px`;
  menu.innerHTML = renderWorkflowNodeMenu();
  document.body.appendChild(menu);
  clampWorkflowNodeMenu(menu);
  menu.querySelectorAll("[data-workflow-node-type]").forEach((button) => {
    button.addEventListener("click", () => insertWorkflowNodeFromMenu(button.dataset.workflowNodeType));
  });
  setTimeout(() => {
    document.addEventListener("mousedown", closeWorkflowNodeMenuOnOutside);
    document.addEventListener("keydown", closeWorkflowNodeMenuOnEscape);
  }, 0);
}

function renderWorkflowNodeMenu() {
  const registry = window.WorkflowNodeRegistry;
  const categories = registry?.categories || [];
  const nodes = registry?.list?.() || [];
  const groups = categories.map((category) => {
    const items = nodes.filter((node) => node.category === category);
    if (!items.length) return "";
    return `
      <div class="workflow-node-context-category">
        <div class="workflow-node-context-heading">${escapeHtml(category)}</div>
        ${items.map((node) => `
          <button type="button" class="workflow-node-context-item" data-workflow-node-type="${escapeHtml(node.type)}">
            <span class="workflow-node-context-glyph" style="color:${escapeHtml(node.accent || "var(--accent)")}">${escapeHtml(_nodeGlyph(node.type))}</span>
            <span class="workflow-node-context-label">${escapeHtml(node.label || node.type)}</span>
            ${node.implemented === false ? '<span class="workflow-node-context-badge">stub</span>' : ""}
          </button>
        `).join("")}
      </div>
    `;
  }).join("");
  return `
    <div class="workflow-node-context-title">Add node</div>
    <div class="workflow-node-context-body">${groups || '<div class="workflow-node-context-empty">No nodes available</div>'}</div>
  `;
}

function clampWorkflowNodeMenu(menu) {
  const rect = menu.getBoundingClientRect();
  const margin = 8;
  const left = Math.min(rect.left, window.innerWidth - rect.width - margin);
  const top = Math.min(rect.top, window.innerHeight - rect.height - margin);
  menu.style.left = `${Math.max(margin, Math.round(left))}px`;
  menu.style.top = `${Math.max(margin, Math.round(top))}px`;
}

function insertWorkflowNodeFromMenu(type) {
  if (!type || !_canvasContextPosition) return;
  addCanvasNode(type, _canvasContextPosition);
  closeWorkflowNodeMenu();
}

function closeWorkflowNodeMenuOnOutside(event) {
  if (event.target?.closest?.("#workflow-node-context-menu")) return;
  closeWorkflowNodeMenu();
}

function closeWorkflowNodeMenuOnEscape(event) {
  if (event.key === "Escape") closeWorkflowNodeMenu();
}

function closeWorkflowNodeMenu() {
  const menu = document.getElementById("workflow-node-context-menu");
  if (menu) menu.remove();
  _canvasContextPosition = null;
  document.removeEventListener("mousedown", closeWorkflowNodeMenuOnOutside);
  document.removeEventListener("keydown", closeWorkflowNodeMenuOnEscape);
}

function onNodeClick(event, node) {
  event.stopPropagation();
  _canvasSelectedNode = node;
  _canvasSelectedEdge = null;
  _canvasView.selectedNodeIds = [node.id];
  renderCanvas();
  renderWorkflowProperties();
}

function validateWorkflowEdge(sourceId, targetId, sourceHandle = "out", targetHandle = "in") {
  if (!sourceId || !targetId) return "Edge endpoints are required.";
  if (sourceId === targetId) return "A node cannot connect to itself.";
  const source = _canvasNodes.find((node) => node.id === sourceId);
  const target = _canvasNodes.find((node) => node.id === targetId);
  if (!source || !target) return "Edges must connect existing nodes.";
  const sourceDef = _registryNode(source.type);
  const targetDef = _registryNode(target.type);
  if (!(sourceDef.outputs || []).some((port) => port.id === sourceHandle)) return "Invalid sourceHandle.";
  if (!(targetDef.inputs || []).some((port) => port.id === targetHandle)) return "Invalid targetHandle.";
  const testEdges = _canvasEdges.concat([{ source: sourceId, target: targetId, sourceHandle, targetHandle }]);
  const cycle = _validateCanvasDag(_canvasNodes, testEdges).find((msg) => msg.includes("cycle"));
  return cycle || "";
}

function addWorkflowEdge(sourceId, targetId, sourceHandle = "out", targetHandle = "in") {
  const error = validateWorkflowEdge(sourceId, targetId, sourceHandle, targetHandle);
  if (error) {
    if (typeof showToast === "function") showToast(error);
    return false;
  }
  _pushCanvasUndo();
  _canvasEdges.push({ id: `edge_${Date.now()}`, source: sourceId, target: targetId, sourceHandle, targetHandle });
  renderCanvas();
  return true;
}

function addCanvasNode(type, position) {
  _pushCanvasUndo();
  const def = _registryNode(type);
  const id = `${String(type || "node").replace(/[^a-z0-9]+/gi, "_")}_${Date.now()}`;
  _canvasNodes.push({
    id,
    type,
    name: def.label || type,
    typeVersion: 1,
    position: position || { x: 120 + Math.round(Math.random() * 80), y: 120 + Math.round(Math.random() * 80) },
    parameters: window.WorkflowNodeRegistry?.defaultParameters(type) || {},
    disabled: false,
    continueOnFail: false,
  });
  _canvasSelectedNode = _canvasNodes[_canvasNodes.length - 1];
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
}

function renderWorkflowProperties() {
  const panel = document.getElementById("workflow-properties-panel") || document.getElementById("canvasConfigPanel");
  if (!panel) return;
  if (_canvasSelectedEdge) {
    panel.innerHTML = `<div class="workflow-properties-head"><h4>Connection</h4><button type="button" onclick="clearWorkflowSelection()" aria-label="Close">x</button></div><div class="detail-form-row"><label>Source</label><input readonly value="${escapeHtml(_canvasSelectedEdge.source || _canvasSelectedEdge.from || "")}"></div><div class="detail-form-row"><label>Target</label><input readonly value="${escapeHtml(_canvasSelectedEdge.target || _canvasSelectedEdge.to || "")}"></div><button class="workflow-delete-node" type="button" onclick="deleteWorkflowSelection()">Delete Connection</button>`;
    return;
  }
  const node = _canvasSelectedNode;
  if (!node) {
    panel.innerHTML = '<div class="canvas-config-empty">Select a node to configure</div>';
    return;
  }
  const def = _registryNode(node.type);
  const rows = [
    `<div class="workflow-properties-head"><h4>Properties</h4><button type="button" onclick="clearWorkflowSelection()" aria-label="Close">x</button></div>`,
    `<div class="workflow-property-name" style="border-color:${escapeHtml(def.accent || "#333")}"><span>${escapeHtml(def.label || node.type)}</span><strong>${escapeHtml(node.name || "")}</strong></div>`,
    `<div class="detail-form-row"><label>Node ID</label><input readonly value="${escapeHtml(node.id)}"></div>`,
    `<div class="detail-form-row"><label>Name</label><input data-workflow-field="name" value="${escapeHtml(node.name || "")}"></div>`,
  ];
  (def.parameters || []).forEach((param) => rows.push(_renderParameterControl(node, param)));
  rows.push(`<div class="workflow-properties-toggles">
    <label><input type="checkbox" data-workflow-field="disabled" ${node.disabled ? "checked" : ""}> Disabled</label>
    <label><input type="checkbox" data-workflow-field="continueOnFail" ${node.continueOnFail ? "checked" : ""}> Continue on fail</label>
  </div>`);
  rows.push(`<button class="workflow-delete-node" type="button" onclick="deleteWorkflowSelection()">Delete Node</button>`);
  panel.innerHTML = rows.join("");
  panel.querySelectorAll("[data-workflow-field]").forEach((input) => input.addEventListener("input", () => applyNodeConfig(node.id)));
  panel.querySelectorAll("[data-workflow-param]").forEach((input) => input.addEventListener("input", () => applyNodeConfig(node.id)));
}

function clearWorkflowSelection() {
  _canvasSelectedNode = null;
  _canvasSelectedEdge = null;
  _canvasView.selectedNodeIds = [];
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
}

function _renderParameterControl(node, param) {
  const value = node.parameters?.[param.key] ?? "";
  const attr = `data-workflow-param="${escapeHtml(param.key)}"`;
  if (param.type === "boolean") {
    return `<div class="detail-form-row"><label><input type="checkbox" ${attr} ${value ? "checked" : ""}> ${escapeHtml(param.label)}</label></div>`;
  }
  if (param.type === "select" || param.type === "agent" || param.type === "llm" || param.type === "mcp") {
    const options = (param.options || ["default"]).map((option) => `<option value="${escapeHtml(option)}" ${String(value) === String(option) ? "selected" : ""}>${escapeHtml(option)}</option>`).join("");
    return `<div class="detail-form-row"><label>${escapeHtml(param.label)}</label><select ${attr}>${options}</select></div>`;
  }
  if (param.type === "code" || param.type === "json") {
    const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    return `<div class="detail-form-row"><label>${escapeHtml(param.label)}</label><textarea rows="5" ${attr} data-param-type="${escapeHtml(param.type)}">${escapeHtml(text)}</textarea></div>`;
  }
  return `<div class="detail-form-row"><label>${escapeHtml(param.label)}</label><input type="${param.type === "number" ? "number" : "text"}" ${attr} value="${escapeHtml(value)}"></div>`;
}

function applyNodeConfig(nodeId) {
  const node = _canvasNodes.find((item) => item.id === nodeId);
  const panel = document.getElementById("workflow-properties-panel") || document.getElementById("canvasConfigPanel");
  if (!node || !panel) return;
  const name = panel.querySelector('[data-workflow-field="name"]');
  const disabled = panel.querySelector('[data-workflow-field="disabled"]');
  const continueOnFail = panel.querySelector('[data-workflow-field="continueOnFail"]');
  if (name) node.name = name.value;
  if (disabled) node.disabled = disabled.checked;
  if (continueOnFail) node.continueOnFail = continueOnFail.checked;
  node.parameters = node.parameters || {};
  panel.querySelectorAll("[data-workflow-param]").forEach((input) => {
    let value = input.type === "checkbox" ? input.checked : input.value;
    if (input.dataset.paramType === "json") {
      try { value = JSON.parse(input.value || "null"); } catch (_) {}
    }
    node.parameters[input.dataset.workflowParam] = value;
  });
  renderCanvas();
}

function deleteWorkflowSelection() {
  _pushCanvasUndo();
  if (_canvasSelectedNode) {
    const id = _canvasSelectedNode.id;
    _canvasNodes = _canvasNodes.filter((node) => node.id !== id);
    _canvasEdges = _canvasEdges.filter((edge) => edge.source !== id && edge.target !== id && edge.from !== id && edge.to !== id);
    _canvasSelectedNode = null;
  } else if (_canvasSelectedEdge) {
    const selectedKey = _edgeKey(_canvasSelectedEdge);
    _canvasEdges = _canvasEdges.filter((edge) => _edgeKey(edge) !== selectedKey);
    _canvasSelectedEdge = null;
  }
  renderCanvas();
  renderWorkflowProperties();
}

function copyWorkflowSelection() {
  if (!_canvasSelectedNode) return;
  _canvasClipboard = JSON.stringify(_canvasSelectedNode);
}

function pasteWorkflowSelection() {
  if (!_canvasClipboard) return;
  _pushCanvasUndo();
  const node = JSON.parse(_canvasClipboard);
  node.id = `${node.id}_copy_${Date.now()}`;
  node.position = { x: (node.position?.x || 80) + 32, y: (node.position?.y || 80) + 32 };
  _canvasNodes.push(node);
  _canvasSelectedNode = node;
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
}

function undoWorkflowCanvas() {
  if (!_canvasUndo.length) return;
  _canvasRedo.push(JSON.stringify({ nodes: _canvasNodes, edges: _canvasEdges, view: _canvasView }));
  const state = JSON.parse(_canvasUndo.pop());
  _canvasNodes = state.nodes || [];
  _canvasEdges = state.edges || [];
  _canvasView = state.view || _canvasView;
  _canvasSelectedNode = null;
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
}

function redoWorkflowCanvas() {
  if (!_canvasRedo.length) return;
  _canvasUndo.push(JSON.stringify({ nodes: _canvasNodes, edges: _canvasEdges, view: _canvasView }));
  const state = JSON.parse(_canvasRedo.pop());
  _canvasNodes = state.nodes || [];
  _canvasEdges = state.edges || [];
  _canvasView = state.view || _canvasView;
  _canvasSelectedNode = null;
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
}

function onWorkflowCanvasKeydown(event) {
  if (!document.getElementById("workflow-definition-canvas-svg")) return;
  if (event.key === "Delete" || event.key === "Backspace") deleteWorkflowSelection();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") copyWorkflowSelection();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") pasteWorkflowSelection();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") undoWorkflowCanvas();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") redoWorkflowCanvas();
}

function _validateCanvasDag(nodes, edges) {
  const ids = new Set(nodes.map((node) => node.id));
  const incoming = {};
  const outgoing = {};
  nodes.forEach((node) => { incoming[node.id] = 0; outgoing[node.id] = []; });
  for (const edge of edges) {
    const source = edge.source || edge.from;
    const target = edge.target || edge.to;
    if (!ids.has(source) || !ids.has(target)) return ["Edges must connect existing nodes."];
    if (source === target) return ["A node cannot connect to itself."];
    outgoing[source].push(target);
    incoming[target] += 1;
  }
  const ready = Object.keys(incoming).filter((id) => incoming[id] === 0);
  let visited = 0;
  while (ready.length) {
    const id = ready.shift();
    visited += 1;
    outgoing[id].forEach((next) => {
      incoming[next] -= 1;
      if (incoming[next] === 0) ready.push(next);
    });
  }
  return visited === nodes.length ? [] : ["Workflow graph contains a cycle."];
}

function renderMiniMap() {
  const map = document.getElementById("workflow-minimap");
  if (!map) return;
  map.innerHTML = _canvasNodes.map((node) => `<rect x="${Math.max(2, (node.position.x || 0) / 12)}" y="${Math.max(2, (node.position.y || 0) / 12)}" width="18" height="8"></rect>`).join("");
}

function renderWorkflowResultsDrawer() {
  const drawer = document.getElementById("workflow-results-drawer");
  if (!drawer) return;
  const runs = Array.isArray(window._workflowRuns) ? window._workflowRuns : [];
  const latest = runs[0];
  const status = latest?.status || (_canvasNodes.length ? "ready" : "idle");
  const rows = _canvasNodes.slice(0, 6).map((node, index) => {
    const def = _registryNode(node.type);
    const stamp = String(index + 1).padStart(2, "0");
    return `<div class="workflow-console-row"><span>${stamp}</span><strong>${escapeHtml(node.id)}</strong><em>${escapeHtml(def.label || node.type)} ready.</em></div>`;
  }).join("");
  drawer.innerHTML = `
    <div class="workflow-console-head">
      <div><button class="active">Execution Results</button><button>Stats (alpha)</button></div>
      <div><span>${escapeHtml(status)}</span><span>Clear</span><span>Copy</span></div>
    </div>
    <div class="workflow-console-body">${rows || '<div class="workflow-results-empty">No nodes on canvas.</div>'}</div>
    <div class="workflow-console-foot"><span>Execution console</span><span>${escapeHtml(status)}</span></div>
  `;
}

function setWorkflowEditorState(state) {
  _canvasNodes = (state?.nodes || []).map((node, idx) => window.deserializeWorkflowEditor({ draft_steps: [node] }).nodes[0] || node);
  _canvasEdges = state?.edges || [];
  _canvasView = state?.canvas || _canvasView;
  _canvasSelectedNode = null;
  _canvasSelectedEdge = null;
}

function getWorkflowEditorState() {
  return { nodes: _canvasNodes, edges: _canvasEdges, canvas: _canvasView, selectedNodeIds: _canvasSelectedNode ? [_canvasSelectedNode.id] : [] };
}

async function saveCanvasWorkflow() {
  if (typeof saveWorkflowDefinition === "function") return saveWorkflowDefinition();
}

async function runCanvasWorkflow() {
  if (typeof runWorkflowDefinition === "function") return runWorkflowDefinition(true);
}

function openCanvasWorkflow() {}

window.initCanvas = initCanvas;
window.renderCanvas = renderCanvas;
window.addCanvasNode = addCanvasNode;
window.showNodeConfig = renderWorkflowProperties;
window.applyNodeConfig = applyNodeConfig;
window.saveCanvasWorkflow = saveCanvasWorkflow;
window.runCanvasWorkflow = runCanvasWorkflow;
window.openCanvasWorkflow = openCanvasWorkflow;
window.copyWorkflowSelection = copyWorkflowSelection;
window.pasteWorkflowSelection = pasteWorkflowSelection;
window.undoWorkflowCanvas = undoWorkflowCanvas;
window.redoWorkflowCanvas = redoWorkflowCanvas;
window.deleteWorkflowSelection = deleteWorkflowSelection;
window.clearWorkflowSelection = clearWorkflowSelection;
window.validateWorkflowEdge = validateWorkflowEdge;
window.setWorkflowEditorState = setWorkflowEditorState;
window.getWorkflowEditorState = getWorkflowEditorState;
window.closeWorkflowNodeMenu = closeWorkflowNodeMenu;
