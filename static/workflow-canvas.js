/* workflow-canvas.js - integrated SVG workflow editor */
let _canvasNodes = [];
let _canvasEdges = [];
let _canvasSelectedNode = null;
let _canvasSelectedEdge = null;
let _canvasDragging = null;
let _canvasConnecting = null;
let _canvasPanning = null;
let _canvasMarquee = null;
let _canvasNodesLocked = false;
let _canvasSvg = null;
let _canvasUndo = [];
let _canvasRedo = [];
let _canvasClipboard = null;
let _canvasContextPosition = null;
let _canvasSuppressNodeClickUntil = 0;
let _canvasView = { zoom: 1, scroll: { x: 0, y: 0 }, selectedNodeIds: [] };
let _workflowPathPicker = null;
let _workflowConsoleExpanded = new Set();
let _workflowDrawerHeight = 196;
let _workflowDrawerResizing = null;

const WORKFLOW_NODE_WIDTH = 220;
const WORKFLOW_NODE_HEIGHT = 84;
const WORKFLOW_NODE_TITLE_MAX_WIDTH = WORKFLOW_NODE_WIDTH - 62;
const WORKFLOW_CANVAS_MIN_ZOOM = 0.35;
const WORKFLOW_CANVAS_MAX_ZOOM = 2;
const WORKFLOW_CANVAS_ZOOM_IN_STEP = 1.08;
const WORKFLOW_CANVAS_ZOOM_OUT_STEP = 0.92;
const WORKFLOW_CANVAS_FIT_PADDING = 56;
let _workflowNodeTextMeasureCanvas = null;

function _registryNode(type) {
  return window.WorkflowNodeRegistry?.get(type) || { type, label: type || "Node", accent: "var(--accent)", inputs: [{ id: "in", label: "Input" }], outputs: [{ id: "out", label: "Output" }], parameters: [] };
}

function _pushCanvasUndo() {
  _canvasUndo.push(JSON.stringify({ nodes: _canvasNodes, edges: _canvasEdges, view: _canvasView }));
  if (_canvasUndo.length > 60) _canvasUndo.shift();
  _canvasRedo = [];
}

function _selectedNodeIds() {
  const ids = Array.isArray(_canvasView.selectedNodeIds) ? _canvasView.selectedNodeIds : [];
  const existing = new Set(_canvasNodes.map((node) => node.id));
  return ids.filter((id, index) => existing.has(id) && ids.indexOf(id) === index);
}

function _selectedNodeIdSet() {
  return new Set(_selectedNodeIds());
}

function _isNodeSelected(nodeId) {
  return _selectedNodeIdSet().has(nodeId);
}

function _setNodeSelection(ids, primaryId = null) {
  const list = Array.isArray(ids) ? ids : [];
  const existing = new Set(_canvasNodes.map((node) => node.id));
  const normalized = list.filter((id, index) => existing.has(id) && list.indexOf(id) === index);
  _canvasView.selectedNodeIds = normalized;
  _canvasSelectedEdge = null;
  const fallback = normalized[0] || null;
  const selectedId = primaryId && normalized.includes(primaryId) ? primaryId : fallback;
  _canvasSelectedNode = selectedId ? (_canvasNodes.find((node) => node.id === selectedId) || null) : null;
}

function _clearNodeSelection() {
  _setNodeSelection([], null);
}

function _nodeBounds(node) {
  return {
    x: node.position?.x || 0,
    y: node.position?.y || 0,
    width: WORKFLOW_NODE_WIDTH,
    height: WORKFLOW_NODE_HEIGHT,
  };
}

function _canvasNodeBounds() {
  if (!_canvasNodes.length) return null;
  return _canvasNodes.reduce((bounds, node) => {
    const rect = _nodeBounds(node);
    if (!bounds) {
      return {
        x: rect.x,
        y: rect.y,
        right: rect.x + rect.width,
        bottom: rect.y + rect.height,
      };
    }
    bounds.x = Math.min(bounds.x, rect.x);
    bounds.y = Math.min(bounds.y, rect.y);
    bounds.right = Math.max(bounds.right, rect.x + rect.width);
    bounds.bottom = Math.max(bounds.bottom, rect.y + rect.height);
    return bounds;
  }, null);
}

function _rectFromPoints(a, b) {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(b.x - a.x),
    height: Math.abs(b.y - a.y),
  };
}

function _rectsIntersect(a, b) {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}

function _selectedNodes() {
  const selected = _selectedNodeIdSet();
  return _canvasNodes.filter((node) => selected.has(node.id));
}

function _marqueeSelectedIds() {
  if (!_canvasMarquee) return [];
  const rect = _rectFromPoints(_canvasMarquee.start, _canvasMarquee.current);
  if (rect.width < 2 && rect.height < 2) return [];
  return _canvasNodes
    .filter((node) => _rectsIntersect(_nodeBounds(node), rect))
    .map((node) => node.id);
}

function initCanvas(svgEl, preserveState = false) {
  closeWorkflowNodeMenu();
  _canvasSvg = svgEl;
  if (!preserveState) {
    _canvasNodes = [];
    _canvasEdges = [];
    _canvasSelectedNode = null;
    _canvasSelectedEdge = null;
    _canvasView.selectedNodeIds = [];
  }
  _canvasDragging = null;
  _canvasConnecting = null;
  _canvasPanning = null;
  _canvasMarquee = null;
  if (_canvasSvg) {
    _canvasSvg.onmousedown = onCanvasMouseDown;
    _canvasSvg.onmousemove = onCanvasMouseMove;
    _canvasSvg.onmouseup = onCanvasMouseUp;
    _canvasSvg.onwheel = onCanvasWheel;
    _canvasSvg.oncontextmenu = onCanvasContextMenu;
  }
  document.removeEventListener("keydown", onWorkflowCanvasKeydown);
  document.addEventListener("keydown", onWorkflowCanvasKeydown);
  _syncWorkflowCanvasLockButton();
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
  if (_canvasMarquee) renderSelectionMarquee(viewport);
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
  const selected = _isNodeSelected(node.id);
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
  _setSvgNodeText(title, node.name || def.label || node.type, WORKFLOW_NODE_TITLE_MAX_WIDTH, "11px", "800");
  g.appendChild(title);

  (def.inputs || []).forEach((port, index) => renderPort(g, node, port, "in", index, def.inputs.length));
  (def.outputs || []).forEach((port, index) => renderPort(g, node, port, "out", index, def.outputs.length));

  g.addEventListener("mousedown", (event) => onNodeMouseDown(event, node));
  g.addEventListener("click", (event) => onNodeClick(event, node));
  parent.appendChild(g);
}

function renderSelectionMarquee(parent) {
  if (!_canvasMarquee) return;
  const rect = _rectFromPoints(_canvasMarquee.start, _canvasMarquee.current);
  if (rect.width < 2 && rect.height < 2) return;
  const box = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  box.setAttribute("x", rect.x);
  box.setAttribute("y", rect.y);
  box.setAttribute("width", rect.width);
  box.setAttribute("height", rect.height);
  box.setAttribute("class", "workflow-canvas-marquee");
  parent.appendChild(box);
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

function _normalizeWorkflowNodeText(text) {
  return String(text == null ? "" : text).replace(/\s+/g, " ").trim();
}

function _workflowNodeTextWidth(text, fontSize = "10px", fontWeight = "400") {
  const content = _normalizeWorkflowNodeText(text);
  if (!content) return 0;
  if (!_workflowNodeTextMeasureCanvas && typeof document !== "undefined") {
    _workflowNodeTextMeasureCanvas = document.createElement("canvas");
  }
  const ctx = _workflowNodeTextMeasureCanvas?.getContext?.("2d");
  if (!ctx) return content.length * 7;
  ctx.font = `${fontWeight} ${fontSize} ui-sans-serif, system-ui, sans-serif`;
  return ctx.measureText(content).width;
}

function _workflowNodeSummary(text, maxWidth, fontSize = "10px", fontWeight = "400") {
  const content = _normalizeWorkflowNodeText(text);
  if (!content) return "";
  if (_workflowNodeTextWidth(content, fontSize, fontWeight) <= maxWidth) return content;
  const ellipsis = "…";
  let low = 0;
  let high = content.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    const candidate = `${content.slice(0, mid).trimEnd()}${ellipsis}`;
    if (_workflowNodeTextWidth(candidate, fontSize, fontWeight) <= maxWidth) low = mid;
    else high = mid - 1;
  }
  const trimmed = content.slice(0, Math.max(0, low)).trimEnd();
  return trimmed ? `${trimmed}${ellipsis}` : ellipsis;
}

function _setSvgNodeText(textEl, fullText, maxWidth, fontSize = "10px", fontWeight = "400") {
  const summary = _workflowNodeSummary(fullText, maxWidth, fontSize, fontWeight);
  textEl.textContent = summary;
  const normalized = _normalizeWorkflowNodeText(fullText);
  if (normalized && normalized !== summary) {
    textEl.setAttribute("title", normalized);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = normalized;
    textEl.appendChild(title);
  } else {
    textEl.removeAttribute("title");
  }
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
  const edgeKey = _edgeKey(edge);
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
  hitPath.setAttribute("data-edge-key", edgeKey);
  hitPath.addEventListener("click", selectEdge);
  parent.appendChild(hitPath);

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  path.setAttribute("class", `canvas-edge${_edgeKey(_canvasSelectedEdge) === edgeKey ? " selected" : ""}`);
  path.setAttribute("data-edge-key", edgeKey);
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

function _clampCanvasZoom(zoom) {
  return Math.max(WORKFLOW_CANVAS_MIN_ZOOM, Math.min(WORKFLOW_CANVAS_MAX_ZOOM, Math.round(zoom * 100) / 100));
}

function setCanvasZoomAtPoint(zoom, clientX, clientY) {
  if (!_canvasSvg) return;
  const newZoom = _clampCanvasZoom(zoom);
  const point = _clientToCanvas(clientX, clientY);
  const rect = _canvasSvg.getBoundingClientRect?.() || { left: 0, top: 0 };
  _canvasView.zoom = newZoom;
  _canvasView.scroll = {
    x: Math.round(clientX - rect.left - point.x * newZoom),
    y: Math.round(clientY - rect.top - point.y * newZoom),
  };
  renderCanvas();
}

function _canvasViewportCenterClientPoint() {
  const rect = _canvasSvg?.getBoundingClientRect?.() || { left: 0, top: 0, width: 0, height: 0 };
  return {
    clientX: rect.left + (rect.width || 0) / 2,
    clientY: rect.top + (rect.height || 0) / 2,
    width: rect.width || 0,
    height: rect.height || 0,
  };
}

function resetCanvasZoom() {
  if (!_canvasSvg) return;
  const center = _canvasViewportCenterClientPoint();
  setCanvasZoomAtPoint(1, center.clientX, center.clientY);
}

function _centerEmptyCanvasView() {
  const rect = _canvasSvg?.getBoundingClientRect?.() || { width: 0, height: 0 };
  _canvasView.zoom = 1;
  _canvasView.scroll = {
    x: Math.round((rect.width || 0) / 2),
    y: Math.round((rect.height || 0) / 2),
  };
  renderCanvas();
}

function fitCanvasView() {
  if (!_canvasSvg) return;
  if (!_canvasNodes.length) {
    _centerEmptyCanvasView();
    return;
  }
  const bounds = _canvasNodeBounds();
  if (!bounds) {
    _centerEmptyCanvasView();
    return;
  }
  const rect = _canvasSvg.getBoundingClientRect?.() || { width: 0, height: 0 };
  const viewportWidth = Math.max(1, rect.width || 0);
  const viewportHeight = Math.max(1, rect.height || 0);
  const contentWidth = Math.max(1, bounds.right - bounds.x);
  const contentHeight = Math.max(1, bounds.bottom - bounds.y);
  const availableWidth = Math.max(1, viewportWidth - WORKFLOW_CANVAS_FIT_PADDING * 2);
  const availableHeight = Math.max(1, viewportHeight - WORKFLOW_CANVAS_FIT_PADDING * 2);
  const zoom = _clampCanvasZoom(Math.min(availableWidth / contentWidth, availableHeight / contentHeight));
  _canvasView.zoom = zoom;
  _canvasView.scroll = {
    x: Math.round((viewportWidth - contentWidth * zoom) / 2 - bounds.x * zoom),
    y: Math.round((viewportHeight - contentHeight * zoom) / 2 - bounds.y * zoom),
  };
  renderCanvas();
}

function zoomWorkflowCanvasIn() {
  const center = _canvasViewportCenterClientPoint();
  setCanvasZoomAtPoint((_canvasView.zoom || 1) * WORKFLOW_CANVAS_ZOOM_IN_STEP, center.clientX, center.clientY);
}

function zoomWorkflowCanvasOut() {
  const center = _canvasViewportCenterClientPoint();
  setCanvasZoomAtPoint((_canvasView.zoom || 1) * WORKFLOW_CANVAS_ZOOM_OUT_STEP, center.clientX, center.clientY);
}

function fitWorkflowCanvasView() {
  fitCanvasView();
}

function resetWorkflowCanvasZoom() {
  resetCanvasZoom();
}

function _syncWorkflowCanvasLockButton() {
  const button = document.getElementById("workflowCanvasLockButton");
  if (!button) return;
  button.classList.toggle("is-active", _canvasNodesLocked);
  button.setAttribute("aria-pressed", _canvasNodesLocked ? "true" : "false");
  const label = _canvasNodesLocked ? "Unlock Nodes" : "Lock Nodes";
  button.setAttribute("aria-label", label);
  button.setAttribute("title", label);
}

function toggleWorkflowCanvasLock() {
  _canvasNodesLocked = !_canvasNodesLocked;
  _canvasDragging = null;
  _syncWorkflowCanvasLockButton();
  if (_canvasSvg) renderCanvas();
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
  if (!_isNodeSelected(node.id)) {
    _setNodeSelection([node.id], node.id);
    renderCanvas();
    renderWorkflowProperties();
  } else {
    _canvasSelectedNode = node;
    _canvasSelectedEdge = null;
  }
  _canvasMarquee = null;
  if (_canvasNodesLocked) return;
  const point = _clientToCanvas(event.clientX, event.clientY);
  const ids = _selectedNodeIds();
  const origPositions = {};
  ids.forEach((id) => {
    const item = _canvasNodes.find((candidate) => candidate.id === id);
    if (item) origPositions[id] = { x: item.position.x, y: item.position.y };
  });
  _canvasDragging = { anchor: point, nodeIds: ids, origPositions, moved: false };
}

function onCanvasMouseDown(event) {
  closeWorkflowNodeMenu();
  if (event.button === 1) {
    startCanvasPan(event);
    return;
  }
  if (event.button !== 0) return;
  if (event.target !== _canvasSvg && !event.target.classList?.contains("workflow-canvas-bg")) return;
  const point = _clientToCanvas(event.clientX, event.clientY);
  _canvasMarquee = { start: point, current: point };
  _canvasSelectedEdge = null;
  renderCanvas();
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
  if (_canvasMarquee) {
    _canvasMarquee.current = _clientToCanvas(event.clientX, event.clientY);
    const ids = _marqueeSelectedIds();
    _setNodeSelection(ids, ids[0] || null);
    renderCanvas();
    return;
  }
  if (!_canvasDragging) return;
  const point = _clientToCanvas(event.clientX, event.clientY);
  const dx = point.x - _canvasDragging.anchor.x;
  const dy = point.y - _canvasDragging.anchor.y;
  _canvasDragging.nodeIds.forEach((id) => {
    const node = _canvasNodes.find((item) => item.id === id);
    const origin = _canvasDragging.origPositions[id];
    if (!node || !origin) return;
    node.position.x = Math.round(origin.x + dx);
    node.position.y = Math.round(origin.y + dy);
  });
  if (Math.abs(dx) > 0 || Math.abs(dy) > 0) _canvasDragging.moved = true;
  renderCanvas();
}

function onCanvasMouseUp(event) {
  if (_canvasPanning) {
    endCanvasPan();
    return;
  }
  if (_canvasDragging) {
    if (_canvasDragging.moved) {
      _pushCanvasUndo();
      _canvasSuppressNodeClickUntil = Date.now() + 120;
    }
    _canvasDragging = null;
  }
  if (_canvasMarquee) {
    const ids = _marqueeSelectedIds();
    _setNodeSelection(ids, ids[0] || null);
    _canvasMarquee = null;
    renderCanvas();
    renderWorkflowProperties();
    return;
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
  const next = oldZoom * (event.deltaY > 0 ? 0.92 : 1.08);
  setCanvasZoomAtPoint(next, event.clientX, event.clientY);
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
  const nodeEl = event.target?.closest?.(".canvas-node[data-node-id]");
  if (nodeEl) {
    const nodeId = nodeEl.getAttribute("data-node-id");
    const node = _canvasNodes.find((item) => item.id === nodeId);
    if (node) {
      const selectedIds = _selectedNodeIds();
      if (!_isNodeSelected(node.id) || selectedIds.length <= 1) {
        _setNodeSelection([node.id], node.id);
      } else {
        _canvasSelectedNode = node;
        _canvasSelectedEdge = null;
      }
      renderCanvas();
      renderWorkflowProperties();
      openWorkflowNodeMenu(event.clientX, event.clientY, { kind: "node" });
      return;
    }
  }
  const edge = _edgeFromContextTarget(event.target);
  if (edge) {
    _canvasSelectedEdge = edge;
    _canvasSelectedNode = null;
    _canvasView.selectedNodeIds = [];
    renderCanvas();
    renderWorkflowProperties();
    openWorkflowNodeMenu(event.clientX, event.clientY, { kind: "edge" });
    return;
  }
  const point = _clientToCanvas(event.clientX, event.clientY);
  openWorkflowNodeMenu(event.clientX, event.clientY, { kind: "canvas", point });
}

function _edgeFromContextTarget(target) {
  const edgeEl = target?.closest?.(".canvas-edge, .canvas-edge-hit");
  if (!edgeEl) return null;
  const edgeKey = edgeEl.getAttribute("data-edge-key");
  if (!edgeKey) return null;
  return _canvasEdges.find((edge) => _edgeKey(edge) === edgeKey) || null;
}

function openWorkflowNodeMenu(clientX, clientY, context = {}) {
  closeWorkflowNodeMenu();
  const kind = context.kind || "canvas";
  if (kind === "canvas" && context.point) {
    _canvasContextPosition = {
      x: Math.round(context.point.x),
      y: Math.round(context.point.y),
    };
  } else {
    _canvasContextPosition = null;
  }
  const menu = document.createElement("div");
  menu.id = "workflow-node-context-menu";
  menu.className = "workflow-node-context-menu";
  menu.style.left = `${clientX}px`;
  menu.style.top = `${clientY}px`;
  menu.innerHTML = renderWorkflowNodeMenu(kind);
  document.body.appendChild(menu);
  clampWorkflowNodeMenu(menu);
  menu.querySelectorAll("[data-workflow-node-type]").forEach((button) => {
    button.addEventListener("click", () => insertWorkflowNodeFromMenu(button.dataset.workflowNodeType));
  });
  menu.querySelectorAll("[data-workflow-replace-node-type]").forEach((button) => {
    button.addEventListener("click", () => handleWorkflowContextAction("replace-node-type", button.dataset.workflowReplaceNodeType));
  });
  menu.querySelectorAll("[data-workflow-action]").forEach((button) => {
    button.addEventListener("click", () => handleWorkflowContextAction(button.dataset.workflowAction));
  });
  setTimeout(() => {
    document.addEventListener("mousedown", closeWorkflowNodeMenuOnOutside);
    document.addEventListener("keydown", closeWorkflowNodeMenuOnEscape);
  }, 0);
}

function renderWorkflowNodeMenu(kind = "canvas") {
  if (kind === "node") return renderWorkflowNodeActions();
  if (kind === "edge") return renderWorkflowEdgeActions();
  if (kind === "replace-node") return renderWorkflowReplaceNodeMenu();
  return renderWorkflowAddNodeMenu();
}

function renderWorkflowAddNodeMenu() {
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

function renderWorkflowNodeActions() {
  const selectedNodes = _selectedNodes();
  const node = _canvasSelectedNode;
  const multi = selectedNodes.length > 1;
  const nodeLabel = multi ? `${selectedNodes.length} nodes selected` : (node ? (node.name || _registryNode(node.type).label || node.type) : "Node");
  const anyEnabled = selectedNodes.some((item) => !item.disabled);
  const toggleLabel = anyEnabled ? "Disable" : "Enable";
  return `
    <div class="workflow-node-context-title">${escapeHtml(nodeLabel)}</div>
    <div class="workflow-node-context-body">
      ${_workflowActionRow("configure-node", "P", "Configure")}
      ${!multi ? _workflowActionRow("open-replace-node", "R", "Replace Node...") : ""}
      ${_workflowActionRow("copy-node", "C", "Copy")}
      ${_workflowActionRow("paste-node", "V", "Paste", { disabled: !_canvasClipboard })}
      ${_workflowActionRow("toggle-node-disabled", "!", toggleLabel)}
      ${_workflowActionRow("delete-node", "X", "Delete Node")}
    </div>
  `;
}

function renderWorkflowReplaceNodeMenu() {
  const registry = window.WorkflowNodeRegistry;
  const categories = registry?.categories || [];
  const nodes = registry?.list?.() || [];
  const currentType = _canvasSelectedNode?.type || "";
  const groups = categories.map((category) => {
    const items = nodes.filter((node) => node.category === category && node.type !== currentType);
    if (!items.length) return "";
    return `
      <div class="workflow-node-context-category">
        <div class="workflow-node-context-heading">${escapeHtml(category)}</div>
        ${items.map((node) => `
          <button type="button" class="workflow-node-context-item" data-workflow-replace-node-type="${escapeHtml(node.type)}">
            <span class="workflow-node-context-glyph" style="color:${escapeHtml(node.accent || "var(--accent)")}">${escapeHtml(_nodeGlyph(node.type))}</span>
            <span class="workflow-node-context-label">${escapeHtml(node.label || node.type)}</span>
            ${node.implemented === false ? '<span class="workflow-node-context-badge">stub</span>' : ""}
          </button>
        `).join("")}
      </div>
    `;
  }).join("");
  return `
    <div class="workflow-node-context-title">Replace node</div>
    <div class="workflow-node-context-body">${groups || '<div class="workflow-node-context-empty">No replacement nodes available</div>'}</div>
  `;
}

function renderWorkflowEdgeActions() {
  return `
    <div class="workflow-node-context-title">Connection</div>
    <div class="workflow-node-context-body">
      ${_workflowActionRow("configure-edge", "P", "Connection Properties")}
      ${_workflowActionRow("delete-edge", "X", "Delete Connection")}
    </div>
  `;
}

function _workflowActionRow(action, glyph, label, opts = {}) {
  return `
    <button type="button" class="workflow-node-context-item" data-workflow-action="${escapeHtml(action)}" ${opts.disabled ? "disabled" : ""}>
      <span class="workflow-node-context-glyph">${escapeHtml(glyph)}</span>
      <span class="workflow-node-context-label">${escapeHtml(label)}</span>
      <span class="workflow-node-context-badge"></span>
    </button>
  `;
}

function handleWorkflowContextAction(action, value = "") {
  if (!action) return;
  if (action === "configure-node" || action === "configure-edge") {
    closeWorkflowNodeMenu();
    renderWorkflowProperties();
    return;
  }
  if (action === "copy-node") {
    copyWorkflowSelection();
    closeWorkflowNodeMenu();
    return;
  }
  if (action === "paste-node") {
    pasteWorkflowSelection();
    closeWorkflowNodeMenu();
    return;
  }
  if (action === "open-replace-node") {
    const menu = document.getElementById("workflow-node-context-menu");
    const rect = menu?.getBoundingClientRect?.();
    openWorkflowNodeMenu(rect?.left || window.innerWidth / 2, rect?.top || window.innerHeight / 2, { kind: "replace-node" });
    return;
  }
  if (action === "replace-node-type") {
    replaceSelectedNodeWithType(value);
    closeWorkflowNodeMenu();
    return;
  }
  if (action === "toggle-node-disabled" && _selectedNodeIds().length) {
    _pushCanvasUndo();
    const selected = _selectedNodes();
    const targetDisabled = selected.some((item) => !item.disabled);
    selected.forEach((item) => { item.disabled = targetDisabled; });
    renderCanvas();
    renderWorkflowProperties();
    renderWorkflowResultsDrawer();
    closeWorkflowNodeMenu();
    return;
  }
  if (action === "delete-node" && _selectedNodeIds().length) {
    deleteWorkflowSelection();
    closeWorkflowNodeMenu();
    return;
  }
  if (action === "delete-edge" && _canvasSelectedEdge) {
    deleteWorkflowSelection();
    closeWorkflowNodeMenu();
    return;
  }
  closeWorkflowNodeMenu();
}

function replaceSelectedNodeWithType(type) {
  const selectedNodes = _selectedNodes();
  const node = selectedNodes.length === 1 ? selectedNodes[0] : null;
  const registry = window.WorkflowNodeRegistry;
  const newDef = registry?.get?.(type);
  if (!node || !newDef || node.type === type) return false;

  const oldDef = _registryNode(node.type);
  const oldParameters = node.parameters || {};
  const newParameters = registry?.defaultParameters(type) || {};
  Object.keys(newParameters).forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(oldParameters, key)) newParameters[key] = oldParameters[key];
  });

  const oldDefaultLabel = oldDef.label || node.type;
  const newDefaultLabel = newDef.label || type;
  const nextName = node.name === oldDefaultLabel ? newDefaultLabel : node.name;
  const firstInput = (newDef.inputs || [])[0]?.id;
  const firstOutput = (newDef.outputs || [])[0]?.id;

  _pushCanvasUndo();
  node.type = type;
  node.typeVersion = newDef.typeVersion || 1;
  node.parameters = newParameters;
  if (nextName) node.name = nextName;
  _canvasEdges = _canvasEdges.filter((edge) => {
    if ((edge.target || edge.to) === node.id) {
      if (!firstInput) return false;
      edge.target = node.id;
      delete edge.to;
      edge.targetHandle = firstInput;
    }
    if ((edge.source || edge.from) === node.id) {
      if (!firstOutput) return false;
      edge.source = node.id;
      delete edge.from;
      edge.sourceHandle = firstOutput;
    }
    return true;
  });
  _setNodeSelection([node.id], node.id);
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
  return true;
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
  if (Date.now() < _canvasSuppressNodeClickUntil) return;
  event.stopPropagation();
  _setNodeSelection([node.id], node.id);
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
  _setNodeSelection([id], id);
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
  const selectedNodes = _selectedNodes();
  if (selectedNodes.length > 1) {
    const anyEnabled = selectedNodes.some((node) => !node.disabled);
    panel.innerHTML = `<div class="workflow-properties-head"><h4>Selection</h4><button type="button" onclick="clearWorkflowSelection()" aria-label="Close">x</button></div><div class="canvas-config-empty" style="padding-top:24px;padding-bottom:24px;">${selectedNodes.length} nodes selected</div><button class="workflow-delete-node" type="button" onclick="toggleWorkflowSelectedDisabled()">${anyEnabled ? "Disable Selected" : "Enable Selected"}</button><button class="workflow-delete-node" type="button" onclick="deleteWorkflowSelection()">Delete Selected Nodes</button>`;
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
  panel.querySelectorAll("[data-workflow-path-browse]").forEach((button) => {
    button.addEventListener("click", () => openWorkflowPathPicker(node.id, button.dataset.workflowPathBrowse || ""));
  });
}

function clearWorkflowSelection() {
  _clearNodeSelection();
  _canvasSelectedEdge = null;
  _canvasMarquee = null;
  renderCanvas();
  renderWorkflowProperties();
  renderWorkflowResultsDrawer();
}

function toggleWorkflowSelectedDisabled() {
  const selected = _selectedNodes();
  if (!selected.length) return;
  _pushCanvasUndo();
  const targetDisabled = selected.some((node) => !node.disabled);
  selected.forEach((node) => { node.disabled = targetDisabled; });
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
  if (param.type === "file") {
    return `<div class="detail-form-row"><label>${escapeHtml(param.label)}</label><div class="workflow-path-control"><input type="text" ${attr} value="${escapeHtml(value)}"><button class="workflow-path-browse" type="button" data-workflow-path-browse="${escapeHtml(param.key)}" title="Browse workspace" aria-label="Browse workspace path">...</button></div></div>`;
  }
  return `<div class="detail-form-row"><label>${escapeHtml(param.label)}</label><input type="${param.type === "number" ? "number" : "text"}" ${attr} value="${escapeHtml(value)}"></div>`;
}

function _workflowPathPickerSessionId() {
  return window.S?.session?.session_id || null;
}

function _workflowPathPickerHasWorkspace() {
  return !!(_workflowPathPickerSessionId() && window.S?.session?.workspace);
}

function _workflowPathParent(path) {
  const normalized = path && path !== "." ? String(path) : ".";
  if (normalized === "." || !normalized.includes("/")) return ".";
  return normalized.slice(0, normalized.lastIndexOf("/")) || ".";
}

function openWorkflowPathPicker(nodeId, paramKey) {
  closeWorkflowPathPicker();
  const sessionWorkspace = String(window.S?.session?.workspace || "").trim();
  _workflowPathPicker = {
    nodeId,
    paramKey,
    sessionWorkspace,
    workspaces: [],
    selectedWorkspace: "",
    currentPath: ".",
    selectedPath: "",
    entries: [],
    loading: false,
    error: "",
    workspaceLoading: false,
    workspaceError: "",
  };
  const overlay = document.createElement("div");
  overlay.className = "workflow-path-picker-overlay";
  overlay.id = "workflow-path-picker-overlay";
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeWorkflowPathPicker();
  });
  document.body.appendChild(overlay);
  renderWorkflowPathPicker();
  loadWorkflowPathPickerWorkspaces();
}

function closeWorkflowPathPicker() {
  const existing = document.getElementById("workflow-path-picker-overlay");
  if (existing) existing.remove();
  _workflowPathPicker = null;
}

async function loadWorkflowPathPickerDir(path = ".") {
  if (!_workflowPathPicker) return;
  const sid = _workflowPathPickerSessionId();
  const selectedWorkspace = String(_workflowPathPicker.selectedWorkspace || "").trim();
  if (!sid || !selectedWorkspace) {
    _workflowPathPicker.entries = [];
    _workflowPathPicker.error = "No workspace selected.";
    renderWorkflowPathPicker();
    return;
  }
  _workflowPathPicker.loading = true;
  _workflowPathPicker.error = "";
  _workflowPathPicker.currentPath = path || ".";
  _workflowPathPicker.selectedPath = "";
  renderWorkflowPathPicker();
  try {
    const data = await api(`/api/list?session_id=${encodeURIComponent(S.session.session_id)}&workspace_path=${encodeURIComponent(selectedWorkspace)}&path=${encodeURIComponent(_workflowPathPicker.currentPath)}`);
    _workflowPathPicker.entries = data.entries || [];
  } catch (err) {
    _workflowPathPicker.entries = [];
    _workflowPathPicker.error = err?.message || "Unable to list workspace files.";
  } finally {
    _workflowPathPicker.loading = false;
    renderWorkflowPathPicker();
  }
}

async function loadWorkflowPathPickerWorkspaces() {
  if (!_workflowPathPicker) return;
  const sid = _workflowPathPickerSessionId();
  if (!sid) {
    _workflowPathPicker.workspaceError = "No active session is available.";
    renderWorkflowPathPicker();
    return;
  }
  _workflowPathPicker.workspaceLoading = true;
  _workflowPathPicker.workspaceError = "";
  renderWorkflowPathPicker();
  try {
    const data = await api("/api/workspaces");
    const workspaces = Array.isArray(data?.workspaces) ? data.workspaces : [];
    _workflowPathPicker.workspaces = workspaces.filter((item) => item && item.path);
    const exact = _workflowPathPicker.workspaces.find((item) => String(item.path) === _workflowPathPicker.sessionWorkspace);
    _workflowPathPicker.selectedWorkspace = String((exact || _workflowPathPicker.workspaces[0] || {}).path || "");
    _workflowPathPicker.entries = [];
    _workflowPathPicker.currentPath = ".";
    _workflowPathPicker.selectedPath = "";
    _workflowPathPicker.error = "";
    if (_workflowPathPicker.selectedWorkspace) {
      await loadWorkflowPathPickerDir(".");
    }
  } catch (err) {
    _workflowPathPicker.workspaces = [];
    _workflowPathPicker.selectedWorkspace = "";
    _workflowPathPicker.entries = [];
    _workflowPathPicker.workspaceError = err?.message || "Unable to load workspaces.";
  } finally {
    _workflowPathPicker.workspaceLoading = false;
    renderWorkflowPathPicker();
  }
}

function selectWorkflowPathPickerWorkspace(path) {
  if (!_workflowPathPicker) return;
  const selectedWorkspace = String(path || "");
  if (!selectedWorkspace || selectedWorkspace === _workflowPathPicker.selectedWorkspace) return;
  _workflowPathPicker.selectedWorkspace = selectedWorkspace;
  _workflowPathPicker.currentPath = ".";
  _workflowPathPicker.selectedPath = "";
  _workflowPathPicker.entries = [];
  _workflowPathPicker.error = "";
  renderWorkflowPathPicker();
  loadWorkflowPathPickerDir(".");
}

function selectWorkflowPathPickerFile(path) {
  if (!_workflowPathPicker) return;
  _workflowPathPicker.selectedPath = path || "";
  renderWorkflowPathPicker();
}

function confirmWorkflowPathPickerSelection() {
  if (!_workflowPathPicker || !_workflowPathPicker.selectedPath) return;
  const { nodeId, paramKey, selectedPath, selectedWorkspace } = _workflowPathPicker;
  const workspaceRoot = String(selectedWorkspace || "").replace(/\/+$/, "");
  const relPath = String(selectedPath || "").replace(/^\.?\//, "");
  const absolutePath = `${workspaceRoot}/${relPath}`.replace(/\/{2,}/g, "/");
  const panel = document.getElementById("workflow-properties-panel") || document.getElementById("canvasConfigPanel");
  const input = Array.from(panel?.querySelectorAll("[data-workflow-param]") || []).find((item) => item.dataset.workflowParam === paramKey);
  if (input) {
    input.value = absolutePath;
    applyNodeConfig(nodeId);
  }
  closeWorkflowPathPicker();
}

function renderWorkflowPathPicker() {
  const overlay = document.getElementById("workflow-path-picker-overlay");
  if (!overlay || !_workflowPathPicker) return;
  const canConfirm = !!_workflowPathPicker.selectedPath;
  const entries = (_workflowPathPicker.entries || []).slice().sort((a, b) => {
    if (a.type === b.type) return String(a.name || "").localeCompare(String(b.name || ""));
    return a.type === "dir" ? -1 : 1;
  });
  const rows = entries.map((item) => {
    const isDir = item.type === "dir";
    const selected = !isDir && _workflowPathPicker.selectedPath === item.path;
    return `<button class="workflow-path-picker-row${selected ? " selected" : ""}" type="button" data-picker-${isDir ? "dir" : "file"}="${escapeHtml(item.path || "")}"><span class="workflow-path-picker-icon">${isDir ? "dir" : "file"}</span><span class="workflow-path-picker-name">${escapeHtml(item.name || item.path || "")}</span></button>`;
  }).join("");
  const body = _workflowPathPicker.workspaceLoading
    ? '<div class="workflow-path-picker-empty">Loading workspaces...</div>'
    : _workflowPathPicker.workspaceError
      ? `<div class="workflow-path-picker-empty">${escapeHtml(_workflowPathPicker.workspaceError)}</div>`
      : !_workflowPathPicker.workspaces.length
        ? '<div class="workflow-path-picker-empty">No saved workspaces found. Add one from Workspaces.</div>'
    : !_workflowPathPicker.selectedWorkspace
      ? '<div class="workflow-path-picker-empty">Select a workspace to browse files.</div>'
    : _workflowPathPicker.loading
      ? '<div class="workflow-path-picker-empty">Loading workspace files...</div>'
      : _workflowPathPicker.error
        ? `<div class="workflow-path-picker-empty">${escapeHtml(_workflowPathPicker.error)}</div>`
        : rows || '<div class="workflow-path-picker-empty">This folder is empty.</div>';
  const workspaceOptions = (_workflowPathPicker.workspaces || []).map((item) => {
    const path = String(item.path || "");
    const name = String(item.name || path);
    const selected = path === _workflowPathPicker.selectedWorkspace;
    return `<option value="${escapeHtml(path)}" ${selected ? "selected" : ""}>${escapeHtml(name)}</option>`;
  }).join("");
  overlay.innerHTML = `<div class="workflow-path-picker-modal" role="dialog" aria-modal="true" aria-label="Browse workspace path">
    <div class="workflow-path-picker-head">
      <div><strong>Browse workspace</strong><span>${escapeHtml(_workflowPathPicker.currentPath || ".")}</span></div>
      <button type="button" data-picker-close aria-label="Close">x</button>
    </div>
    <div class="workflow-path-picker-toolbar">
      <label>Workspace</label>
      <select data-picker-workspace ${_workflowPathPicker.workspaces.length ? "" : "disabled"}>${workspaceOptions}</select>
    </div>
    <div class="workflow-path-picker-toolbar">
      <button type="button" data-picker-up ${_workflowPathPicker.currentPath === "." ? "disabled" : ""}>Up</button>
      <code>${escapeHtml(_workflowPathPicker.selectedPath || "Select a file")}</code>
    </div>
    <div class="workflow-path-picker-list">${body}</div>
    <div class="workflow-path-picker-actions">
      <button type="button" data-picker-cancel>Cancel</button>
      <button type="button" class="primary" data-picker-confirm ${canConfirm ? "" : "disabled"}>Use Path</button>
    </div>
  </div>`;
  overlay.querySelector("[data-picker-close]")?.addEventListener("click", closeWorkflowPathPicker);
  overlay.querySelector("[data-picker-cancel]")?.addEventListener("click", closeWorkflowPathPicker);
  overlay.querySelector("[data-picker-confirm]")?.addEventListener("click", confirmWorkflowPathPickerSelection);
  overlay.querySelector("[data-picker-workspace]")?.addEventListener("change", (event) => selectWorkflowPathPickerWorkspace(event.target.value));
  overlay.querySelector("[data-picker-up]")?.addEventListener("click", () => loadWorkflowPathPickerDir(_workflowPathParent(_workflowPathPicker.currentPath)));
  overlay.querySelectorAll("[data-picker-dir]").forEach((button) => {
    button.addEventListener("click", () => loadWorkflowPathPickerDir(button.dataset.pickerDir || "."));
  });
  overlay.querySelectorAll("[data-picker-file]").forEach((button) => {
    button.addEventListener("click", () => selectWorkflowPathPickerFile(button.dataset.pickerFile || ""));
  });
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
  const selectedIds = _selectedNodeIds();
  if (!selectedIds.length && !_canvasSelectedEdge) return;
  _pushCanvasUndo();
  if (selectedIds.length) {
    const selected = new Set(selectedIds);
    _canvasNodes = _canvasNodes.filter((node) => !selected.has(node.id));
    _canvasEdges = _canvasEdges.filter((edge) => !selected.has(edge.source || edge.from) && !selected.has(edge.target || edge.to));
    _clearNodeSelection();
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
  _setNodeSelection([node.id], node.id);
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
  const selected = state?.selectedNodeIds || _canvasView.selectedNodeIds || [];
  _setNodeSelection(selected, selected[0] || null);
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
  const selected = state?.selectedNodeIds || _canvasView.selectedNodeIds || [];
  _setNodeSelection(selected, selected[0] || null);
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
  map.innerHTML = _canvasNodes.map((node) => {
    const def = _registryNode(node.type);
    const color = def.accent || "var(--accent)";
    return `<rect x="${Math.max(2, (node.position.x || 0) / 12)}" y="${Math.max(2, (node.position.y || 0) / 12)}" width="18" height="8" fill="${escapeHtml(color)}"></rect>`;
  }).join("");
}

function renderWorkflowResultsDrawer() {
  const drawer = document.getElementById("workflow-results-drawer");
  if (!drawer) return;
  drawer.style.height = `${Math.max(140, Math.min(460, _workflowDrawerHeight))}px`;
  const execution = window._workflowExecutionState || null;
  const runs = Array.isArray(window._workflowRuns) ? window._workflowRuns : [];
  const latest = execution?.run || runs[0];
  const status = execution?.status || latest?.status || (_canvasNodes.length ? "ready" : "idle");
  const nodeRows = Array.isArray(execution?.nodes) && execution.nodes.length
    ? execution.nodes
    : _canvasNodes.slice(0, 6).map((node) => ({ name: node.id, status: "ready", summary: _registryNode(node.type).label || node.type }));
  const rows = nodeRows.slice(0, 16).map((node, index) => {
    const stamp = String(index + 1).padStart(2, "0");
    const name = node?.name || node?.node_id || node?.id || `node_${index + 1}`;
    const rowKey = String(node?.node_id || node?.id || name);
    const nodeStatus = node?.status || "ready";
    const summary = node?.summary || (nodeStatus === "ready" ? "Ready." : "Running.");
    const detailPayload = _workflowNodeDetailPayload(node);
    const hasDetail = detailPayload !== "";
    const expanded = hasDetail && _workflowConsoleExpanded.has(rowKey);
    return `
      <div class="workflow-console-row-wrap${expanded ? " expanded" : ""}" data-row-key="${escapeHtml(rowKey)}">
        <div class="workflow-console-row">
          <span>${stamp}</span>
          <strong>${escapeHtml(name)}</strong>
          <em>${escapeHtml(nodeStatus)}: ${escapeHtml(summary)}</em>
          ${hasDetail ? `<button type="button" class="workflow-console-expand" data-workflow-console-expand="${escapeHtml(rowKey)}">${expanded ? "Hide details" : "Show details"}</button>` : ""}
        </div>
        ${hasDetail && expanded ? `<pre class="workflow-console-detail">${escapeHtml(detailPayload)}</pre>` : ""}
      </div>
    `;
  }).join("");
  const summaryText = execution?.summary
    || (latest?.error ? String(latest.error) : "")
    || (execution?.runId ? `Run ${execution.runId}` : "Execution console");
  drawer.innerHTML = `
    <div class="workflow-results-resizer" title="Resize execution results" aria-label="Resize execution results"></div>
    <div class="workflow-console-head">
      <div><button class="active">Execution Results</button><button>Stats (alpha)</button></div>
      <div>
        <span>${escapeHtml(status)}</span>
        <span>${escapeHtml(execution?.runId || "")}</span>
        ${execution?.runId ? `<button type="button" class="btn btn-sm btn-accent" data-workflow-open-trace="${escapeHtml(execution.runId)}">TRACE</button>` : ""}
      </div>
    </div>
    <div class="workflow-console-body">${rows || '<div class="workflow-results-empty">No nodes on canvas.</div>'}</div>
    <div class="workflow-console-foot"><span>${escapeHtml(summaryText)}</span><span>${escapeHtml(status)}</span></div>
  `;
  _bindWorkflowResultsDrawerInteractions(drawer);
}

function _workflowNodeDetailPayload(node) {
  const payload = {};
  if (node?.structured_result !== undefined && node?.structured_result !== null) payload.output = node.structured_result;
  if (node?.error) payload.error = node.error;
  if (node?.artifacts && Array.isArray(node.artifacts) && node.artifacts.length) payload.artifacts = node.artifacts;
  const keys = Object.keys(payload);
  if (!keys.length) return "";
  try {
    return JSON.stringify(payload, null, 2);
  } catch (_) {
    return String(payload);
  }
}

function _bindWorkflowResultsDrawerInteractions(drawer) {
  drawer.querySelectorAll("[data-workflow-open-trace]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const runId = String(btn.getAttribute("data-workflow-open-trace") || "");
      if (!runId) return;
      if (typeof window.openTraceView === "function") window.openTraceView(runId);
    });
  });
  drawer.querySelectorAll("[data-workflow-console-expand]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = String(btn.getAttribute("data-workflow-console-expand") || "");
      if (!key) return;
      if (_workflowConsoleExpanded.has(key)) _workflowConsoleExpanded.delete(key);
      else _workflowConsoleExpanded.add(key);
      renderWorkflowResultsDrawer();
    });
  });
  const handle = drawer.querySelector(".workflow-results-resizer");
  if (!handle) return;
  handle.addEventListener("mousedown", _startWorkflowDrawerResize);
}

function _startWorkflowDrawerResize(event) {
  event.preventDefault();
  const drawer = document.getElementById("workflow-results-drawer");
  if (!drawer) return;
  const rect = drawer.getBoundingClientRect();
  _workflowDrawerResizing = {
    startY: event.clientY,
    startHeight: rect.height,
  };
  document.addEventListener("mousemove", _onWorkflowDrawerResizeMove);
  document.addEventListener("mouseup", _stopWorkflowDrawerResize);
}

function _onWorkflowDrawerResizeMove(event) {
  if (!_workflowDrawerResizing) return;
  const delta = _workflowDrawerResizing.startY - event.clientY;
  _workflowDrawerHeight = Math.max(140, Math.min(460, Math.round(_workflowDrawerResizing.startHeight + delta)));
  const drawer = document.getElementById("workflow-results-drawer");
  if (drawer) drawer.style.height = `${_workflowDrawerHeight}px`;
}

function _stopWorkflowDrawerResize() {
  _workflowDrawerResizing = null;
  document.removeEventListener("mousemove", _onWorkflowDrawerResizeMove);
  document.removeEventListener("mouseup", _stopWorkflowDrawerResize);
}

function setWorkflowEditorState(state) {
  _canvasNodes = (state?.nodes || []).map((node, idx) => window.deserializeWorkflowEditor({ draft_steps: [node] }).nodes[0] || node);
  _canvasEdges = state?.edges || [];
  _canvasView = state?.canvas || _canvasView;
  _setNodeSelection(state?.selectedNodeIds || _canvasView.selectedNodeIds || [], (state?.selectedNodeIds || _canvasView.selectedNodeIds || [])[0] || null);
  _canvasSelectedEdge = null;
}

function getWorkflowEditorState() {
  return { nodes: _canvasNodes, edges: _canvasEdges, canvas: Object.assign({}, _canvasView, { selectedNodeIds: _selectedNodeIds() }), selectedNodeIds: _selectedNodeIds() };
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
window.zoomWorkflowCanvasIn = zoomWorkflowCanvasIn;
window.zoomWorkflowCanvasOut = zoomWorkflowCanvasOut;
window.fitWorkflowCanvasView = fitWorkflowCanvasView;
window.resetWorkflowCanvasZoom = resetWorkflowCanvasZoom;
window.toggleWorkflowCanvasLock = toggleWorkflowCanvasLock;
window.closeWorkflowNodeMenu = closeWorkflowNodeMenu;
window.toggleWorkflowSelectedDisabled = toggleWorkflowSelectedDisabled;
window.replaceSelectedNodeWithType = replaceSelectedNodeWithType;
window.openWorkflowPathPicker = openWorkflowPathPicker;
window.closeWorkflowPathPicker = closeWorkflowPathPicker;
window.loadWorkflowPathPickerDir = loadWorkflowPathPickerDir;
window.selectWorkflowPathPickerFile = selectWorkflowPathPickerFile;
window.confirmWorkflowPathPickerSelection = confirmWorkflowPathPickerSelection;
