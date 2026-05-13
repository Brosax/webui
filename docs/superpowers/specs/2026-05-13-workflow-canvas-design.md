# Workflow Canvas Design

**Date:** 2026-05-13
**Status:** Draft

---

## 1. Concept & Vision

A visual workflow editor where users drag nodes onto a canvas, connect them with lines to define data flow, and see real-time execution status in a split-panel layout. Each node represents either an Agent, a Prompt template, a file input, or a file output. The system feels like a lightweight visual pipeline builder — intuitive enough for non-technical users, powerful enough for automated data processing workflows.

---

## 2. Design Language

### Aesthetic
- Dark-themed (matches existing Hermes WebUI)
- Canvas: subtle grid background, nodes as rounded cards with icon + title
- Connections: bezier curves with directional arrows
- Status colors: idle (gray), running (blue pulse), success (green), error (red)

### Layout
```
┌──────────────────────────────────────────────────────────────┐
│  Toolbar: [+ Agent] [+ Prompt] [+ Input] [+ Output] [Save]   │
├─────────────────────────────┬────────────────────────────────┤
│                             │                                │
│      Canvas (drag/connect)  │     Live Preview Panel         │
│                             │     - Run status per node      │
│    [Input] ──→ [Agent]      │     - Real-time logs           │
│              ↓              │     - Output artifact list     │
│         [Prompt] ──→ [Output]                                │
│                             │                                │
├─────────────────────────────┴────────────────────────────────┤
│  Status bar: Run #42 | 3/5 nodes complete | 2m 34s elapsed   │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Node Types

### 3.1 File Input Node
- **Icon:** folder icon
- **Config:** path selector (file or folder), file type filter (e.g., `.pdf`, `.json`, `*`)
- **Output:** file reference passed to connected nodes

### 3.2 Agent Node
- **Icon:** robot icon
- **Config:**
  - Agent selection (dropdown from available agents)
  - Instruction/prompt textarea
  - Input binding: which upstream output to use
- **Output:** execution result (text or structured data)

### 3.3 Prompt Node
- **Icon:** text bubble icon
- **Config:**
  - Template text with `{{variable}}` placeholders
  - Variable binding: connect upstream nodes to fill placeholders
- **Output:** rendered text string

### 3.4 File Output Node
- **Icon:** download icon
- **Config:**
  - Output path
  - Format selector (JSON, TXT, CSV, etc.)
  - Input binding: which node's output to capture

---

## 4. Data Flow

### Connection Model
- Nodes connect via output → input ports
- Data flows along connected edges at runtime
- Each input port accepts specific data types (file reference or text)

### Edge Rules
- File Input → Agent: passes file path to agent
- Agent → Prompt: passes agent output as `{{context}}` variable
- Prompt → Agent: passes rendered text as agent input
- Agent → File Output: captures final output
- Any text output can connect to any text input (duck typing)

---

## 5. Canvas Interactions

| Action | Behavior |
|--------|----------|
| Drag node from toolbar | Creates new node at cursor position |
| Drag node on canvas | Repositions node |
| Click node | Selects node, shows config in right panel |
| Click + drag from output port | Starts drawing edge |
| Drop on input port | Creates connection |
| Double-click edge | Deletes edge |
| Delete key | Removes selected node + its edges |
| Scroll | Pan canvas |
| Pinch | Zoom canvas (if supported) |

---

## 6. Live Preview Panel (Right Side)

### Modes
1. **Edit mode:** Selected node config form
2. **Run mode:** Live execution status

### Run Mode Content
- **Per-node status cards:** Node name, status (queued/running/done/error), elapsed time
- **Log stream:** Real-time log lines from running node, auto-scroll
- **Artifact list:** Files produced by completed nodes, click to preview/download

### Controls
- **[Run]** button: starts workflow
- **[Stop]** button: cancels running workflow
- **[Clear]** button: resets run view

---

## 7. Persistence Model

### Workflow Definition
- Saved as JSON: nodes list + edges list + metadata
- Stored in SQLite via `workflow_trace.py` (existing `workflow_definitions` table)

### Workflow Run
- On **[Run]**: create snapshot of current definition → create `workflow_run` record
- Each node execution: `create_node()` → `update_node()` on completion
- Events stream: `append_event()` for logs/errors

### Input Resolution at Runtime
- **Manual selection:** File picker dialog at run time (binding not connected to upstream)
- **Fixed path:** Resolved from node config at run time
- **Upstream output:** Follow edges back to resolve source node output

---

## 8. Component Inventory

### 8.1 Canvas Component
- SVG-based or HTML5 Canvas for rendering nodes + edges
- States: idle, panning, connecting, node-dragging
- Grid background pattern (CSS)

### 8.2 Node Component
- States: default, selected, running, success, error
- Ports: 1 input (left), 1 output (right) — except File Input (no input) and File Output (no output)

### 8.3 Edge Component
- States: default, selected, hover
- SVG bezier path with arrowhead marker

### 8.4 Config Panel
- Dynamic form based on selected node type
- Validation on field blur
- Auto-save on change (debounced 500ms)

### 8.5 Run Status Card
- Node name + status badge + timer
- Expandable to show node-specific output preview

### 8.6 Log Stream
- Virtualized list for performance (only render visible lines)
- ANSI color code support

---

## 9. Technical Approach

### Frontend
- Vanilla JS (matching project pattern)
- New file: `static/workflow-canvas.js`
- Existing `workflow.js` kept for trace panel — canvas is separate feature

### Backend
- Extend `api/workflow_trace.py` with:
  - `save_workflow_definition(nodes, edges, metadata)`
  - `create_workflow_run(definition_id, inputs)` — resolves inputs at run time
  - `get_node_output(node_id)` — for downstream binding resolution
- New routes:
  - `POST /api/workflow/definitions/canvas` — save canvas state
  - `POST /api/workflow/runs/from-definition/{def_id}` — run with resolved inputs
  - `GET /api/workflow/runs/{run_id}/live` — SSE stream for live status

### Multi-Agent Implementation Tasks

**Agent 1 — Canvas Core (backend + frontend scaffold)**
- Canvas rendering (nodes + edges as SVG)
- Node drag/drop positioning
- Edge connection via port drag
- Node config panel wiring

**Agent 2 — Run Execution Engine**
- Input resolution (manual file picker, fixed path, upstream binding)
- Node execution loop (follow edge order)
- SSE live status streaming
- Log aggregation per node

**Agent 3 — Persistence & Integration**
- Save/load workflow definitions (nodes + edges JSON)
- Run snapshot creation
- Integration with existing `workflow_trace.py` schema

---

## 10. Scope for v1

### In Scope
- 4 node types (File Input, Agent, Prompt, File Output)
- Canvas drag/drop + edge connection
- Split panel: edit left / live status right
- Manual file selection at run time
- Real-time log stream during execution
- Save/load workflow definitions

### Out of Scope (v1)
- Undo/redo
- Canvas zoom/pan gestures
- Multi-user / permissions
- Node concurrency (nodes run sequentially for v1)
- Workflow versioning / publishing

---

## 11. File Changes

| File | Change |
|------|--------|
| `static/workflow-canvas.js` | New — canvas editor + live panel |
| `api/workflow_trace.py` | Extend with canvas save/load/run |
| `api/routes.py` | New routes for canvas operations |
| `static/panels.js` | Wire in new canvas panel |
| `static/style.css` | Canvas + node + edge styles |
| `static/index.html` | Add canvas panel tab |