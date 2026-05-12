# Workflow GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Hermes WebUI 添加可视化工作流面板，支持企业 Skills 的调用链追踪和产物溯源

**Architecture:** 四层架构：UI 面板 → API 路由 → JSON 文件存储 → Agent 调用。通过卡片列表展示任务，点击展开显示完整调用链和产物。

**Tech Stack:** Python (api/workflow.py), Vanilla JS (static/workflow.js), JSON files, CSS

---

## File Structure

| 文件 | 职责 |
|------|------|
| `api/workflow.py` | 工作流数据层：Task/AgentCall/Artifact 读写 |
| `api/routes.py` | 注册 /api/workflow/* 路由 |
| `static/workflow.js` | 工作流面板 JS 逻辑 |
| `static/panels.js` | 添加 workflow 面板 Tab |
| `static/index.html` | 添加 panelWorkflow 容器 |
| `static/style.css` | 工作流面板样式 |
| `server.py` | 路由分发到 workflow.py |

---

## Task 1: 数据模型和存储层

**Files:**
- Create: `api/workflow.py`
- Test: `tests/test_workflow.py`

- [ ] **Step 1: 创建 api/workflow.py**

```python
"""Workflow data layer: Task/AgentCall/Artifact CRUD via JSON files."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATE_DIR = Path.home() / ".hermes" / "webui-mvp"
WORKFLOWS_DIR = STATE_DIR / "workflows"
TASKS_DIR = WORKFLOWS_DIR / "tasks"
ARTIFACTS_DIR = WORKFLOWS_DIR / "artifacts"

def _ensure_dirs():
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None

def _save_json(path: Path, data: dict):
    _ensure_dirs()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ── Task ──────────────────────────────────────────────────────────────────────
def create_task(name: str, input_data: dict, created_by: str = "unknown") -> dict:
    """Create a new task."""
    _ensure_dirs()
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    task = {
        "id": task_id,
        "name": name,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "created_by": created_by,
        "input": input_data,
        "calls": [],
        "artifacts": []
    }
    _save_json(TASKS_DIR / f"{task_id}.json", task)
    return task

def get_task(task_id: str) -> Optional[dict]:
    """Get a task by ID."""
    path = TASKS_DIR / f"{task_id}.json"
    return _load_json(path)

def list_tasks() -> list[dict]:
    """List all tasks sorted by created_at desc."""
    _ensure_dirs()
    tasks = []
    for p in TASKS_DIR.glob("*.json"):
        t = _load_json(p)
        if t:
            tasks.append(t)
    return sorted(tasks, key=lambda x: x.get("created_at", ""), reverse=True)

def update_task(task_id: str, **kwargs) -> Optional[dict]:
    """Update task fields."""
    task = get_task(task_id)
    if not task:
        return None
    task.update(kwargs)
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_json(TASKS_DIR / f"{task_id}.json", task)
    return task

def delete_task(task_id: str) -> bool:
    """Delete a task and its artifacts."""
    task = get_task(task_id)
    if not task:
        return False
    # Delete artifacts
    for art_id in task.get("artifacts", []):
        art_dir = ARTIFACTS_DIR / art_id
        if art_dir.exists():
            shutil.rmtree(art_dir)
    # Delete task file
    (TASKS_DIR / f"{task_id}.json").unlink(missing_ok=True)
    return True

# ── AgentCall ────────────────────────────────────────────────────────────────
def create_agent_call(task_id: str, agent_name: str, parent_call_id: str = None,
                      input_data: dict = None) -> Optional[dict]:
    """Create an agent call record linked to a task."""
    task = get_task(task_id)
    if not task:
        return None
    call_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    call = {
        "id": call_id,
        "task_id": task_id,
        "parent_call_id": parent_call_id,
        "agent_name": agent_name,
        "status": "pending",
        "started_at": now,
        "ended_at": None,
        "input": input_data or {},
        "output": None,
        "error": None,
        "children": []
    }
    _ensure_dirs()
    _save_json(TASKS_DIR / f"{call_id}_call.json", call)
    # Link to parent
    if parent_call_id:
        parent = get_agent_call(parent_call_id)
        if parent:
            parent["children"] = parent.get("children", []) + [call_id]
            _save_json(TASKS_DIR / f"{parent_call_id}_call.json", parent)
    # Link to task
    task["calls"] = task.get("calls", []) + [call_id]
    task["updated_at"] = now
    _save_json(TASKS_DIR / f"{task_id}.json", task)
    return call

def get_agent_call(call_id: str) -> Optional[dict]:
    """Get an agent call by ID."""
    return _load_json(TASKS_DIR / f"{call_id}_call.json")

def get_task_calls(task_id: str) -> list[dict]:
    """Get all calls for a task."""
    task = get_task(task_id)
    if not task:
        return []
    calls = []
    for call_id in task.get("calls", []):
        c = get_agent_call(call_id)
        if c:
            calls.append(c)
    return sorted(calls, key=lambda x: x.get("started_at", ""))

def update_agent_call(call_id: str, **kwargs) -> Optional[dict]:
    """Update agent call fields."""
    call = get_agent_call(call_id)
    if not call:
        return None
    call.update(kwargs)
    _save_json(TASKS_DIR / f"{call_id}_call.json", call)
    return call

# ── Artifact ─────────────────────────────────────────────────────────────────
def create_artifact(task_id: str, call_id: str, name: str, content: str,
                    artifact_type: str = "document", metadata: dict = None) -> Optional[dict]:
    """Create an artifact file."""
    task = get_task(task_id)
    if not task:
        return None
    art_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    artifact_dir = ARTIFACTS_DIR / art_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    # Save content
    file_path = artifact_dir / name
    file_path.write_text(content, encoding="utf-8")
    artifact = {
        "id": art_id,
        "task_id": task_id,
        "call_id": call_id,
        "name": name,
        "type": artifact_type,
        "path": str(file_path),
        "size": len(content),
        "created_at": now,
        "metadata": metadata or {}
    }
    _save_json(artifact_dir / "meta.json", artifact)
    # Link to task
    task["artifacts"] = task.get("artifacts", []) + [art_id]
    task["updated_at"] = now
    _save_json(TASKS_DIR / f"{task_id}.json", task)
    return artifact

def get_artifact(artifact_id: str) -> Optional[dict]:
    """Get artifact metadata."""
    meta_path = ARTIFACTS_DIR / artifact_id / "meta.json"
    return _load_json(meta_path)

def get_artifact_content(artifact_id: str) -> Optional[str]:
    """Get artifact file content."""
    artifact = get_artifact(artifact_id)
    if not artifact:
        return None
    path = Path(artifact["path"])
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None

def get_task_artifacts(task_id: str) -> list[dict]:
    """Get all artifacts for a task."""
    task = get_task(task_id)
    if not task:
        return []
    artifacts = []
    for art_id in task.get("artifacts", []):
        a = get_artifact(art_id)
        if a:
            artifacts.append(a)
    return sorted(artifacts, key=lambda x: x.get("created_at", ""))
```

- [ ] **Step 2: 写测试 tests/test_workflow.py**

```python
import pytest
from api.workflow import (
    create_task, get_task, list_tasks, update_task, delete_task,
    create_agent_call, get_agent_call, get_task_calls, update_agent_call,
    create_artifact, get_artifact, get_artifact_content, get_task_artifacts,
    _ensure_dirs, TASKS_DIR, ARTIFACTS_DIR
)
import shutil

@pytest.fixture(autouse=True)
def clean_workflow_dirs():
    _ensure_dirs()
    yield
    # Cleanup
    for p in TASKS_DIR.glob("*.json"):
        p.unlink(missing_ok=True)
    for p in TASKS_DIR.glob("*_call.json"):
        p.unlink(missing_ok=True)
    if ARTIFACTS_DIR.exists():
        shutil.rmtree(ARTIFACTS_DIR)
    _ensure_dirs()

def test_create_and_get_task():
    task = create_task("Test Task", {"tool": "test"})
    assert task["name"] == "Test Task"
    assert task["status"] == "pending"
    assert "id" in task
    
    fetched = get_task(task["id"])
    assert fetched["id"] == task["id"]
    assert fetched["name"] == "Test Task"

def test_list_tasks():
    create_task("Task 1", {})
    create_task("Task 2", {})
    tasks = list_tasks()
    assert len(tasks) == 2

def test_update_task():
    task = create_task("Original", {})
    updated = update_task(task["id"], status="running", name="Updated")
    assert updated["status"] == "running"
    assert updated["name"] == "Updated"

def test_delete_task():
    task = create_task("To Delete", {})
    task_id = task["id"]
    assert delete_task(task_id) is True
    assert get_task(task_id) is None

def test_agent_call_lifecycle():
    task = create_task("Task with Call", {})
    call = create_agent_call(task["id"], "test_agent", input_data={"query": "hello"})
    assert call["agent_name"] == "test_agent"
    assert call["status"] == "pending"
    
    # Update status
    updated = update_agent_call(call["id"], status="completed", output={"result": "done"})
    assert updated["status"] == "completed"
    assert updated["output"]["result"] == "done"
    
    # Check task links
    task = get_task(task["id"])
    assert call["id"] in task["calls"]

def test_artifact_lifecycle():
    task = create_task("Task with Artifact", {})
    call = create_agent_call(task["id"], "doc_agent")
    artifact = create_artifact(task["id"], call["id"], "report.md", "# Report Content", metadata={"format": "markdown"})
    
    assert artifact["name"] == "report.md"
    assert artifact["type"] == "document"
    
    content = get_artifact_content(artifact["id"])
    assert content == "# Report Content"
    
    # Check task links
    task = get_task(task["id"])
    assert artifact["id"] in task["artifacts"]
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/test_workflow.py -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add api/workflow.py tests/test_workflow.py
git commit -m "feat(workflow): add data layer for Task/AgentCall/Artifact"
```

---

## Task 2: API 路由

**Files:**
- Modify: `api/routes.py` (~line 1200+, 添加 /api/workflow/* 路由)
- Modify: `server.py` (路由分发)

- [ ] **Step 1: 在 api/routes.py 末尾添加工作流 API**

```python
# ── Workflow ─────────────────────────────────────────────────────────────────
from api.workflow import (
    create_task, get_task, list_tasks, update_task, delete_task,
    create_agent_call, get_agent_call, get_task_calls, update_agent_call,
    create_artifact, get_artifact, get_artifact_content, get_task_artifacts,
)

@route("/api/workflow/tasks", methods=["GET"])
def workflow_list_tasks(handler):
    tasks = list_tasks()
    return j({"success": True, "data": tasks})

@route("/api/workflow/tasks", methods=["POST"])
def workflow_create_task(handler):
    body = json.loads(handler.body or "{}")
    name = body.get("name", "Untitled Task")
    input_data = body.get("input", {})
    created_by = handler.get_cookie("user") or "unknown"
    task = create_task(name, input_data, created_by)
    return j({"success": True, "data": task})

@route("/api/workflow/tasks/{task_id}", methods=["GET"])
def workflow_get_task(handler, task_id):
    task = get_task(task_id)
    if not task:
        return bad(404, "Task not found")
    return j({"success": True, "data": task})

@route("/api/workflow/tasks/{task_id}", methods=["DELETE"])
def workflow_delete_task(handler, task_id):
    if delete_task(task_id):
        return j({"success": True})
    return bad(404, "Task not found")

@route("/api/workflow/tasks/{task_id}/calls", methods=["GET"])
def workflow_get_calls(handler, task_id):
    calls = get_task_calls(task_id)
    return j({"success": True, "data": calls})

@route("/api/workflow/tasks/{task_id}/calls", methods=["POST"])
def workflow_create_call(handler, task_id):
    body = json.loads(handler.body or "{}")
    call = create_agent_call(task_id, body.get("agent_name", "unknown"),
                             body.get("parent_call_id"), body.get("input"))
    if not call:
        return bad(404, "Task not found")
    return j({"success": True, "data": call})

@route("/api/workflow/tasks/{task_id}/calls/{call_id}", methods=["PATCH"])
def workflow_update_call(handler, task_id, call_id):
    body = json.loads(handler.body or "{}")
    call = update_agent_call(call_id, **body)
    if not call:
        return bad(404, "Call not found")
    return j({"success": True, "data": call})

@route("/api/workflow/tasks/{task_id}/artifacts", methods=["GET"])
def workflow_get_artifacts(handler, task_id):
    artifacts = get_task_artifacts(task_id)
    return j({"success": True, "data": artifacts})

@route("/api/workflow/tasks/{task_id}/artifacts", methods=["POST"])
def workflow_create_artifact(handler, task_id):
    body = json.loads(handler.body or "{}")
    call_id = body.get("call_id", "")
    artifact = create_artifact(task_id, call_id, body.get("name", "file.txt"),
                               body.get("content", ""), body.get("type", "document"),
                               body.get("metadata"))
    if not artifact:
        return bad(404, "Task not found")
    return j({"success": True, "data": artifact})

@route("/api/workflow/artifacts/{artifact_id}", methods=["GET"])
def workflow_get_artifact(handler, artifact_id):
    artifact = get_artifact(artifact_id)
    if not artifact:
        return bad(404, "Artifact not found")
    return j({"success": True, "data": artifact})

@route("/api/workflow/artifacts/{artifact_id}/content", methods=["GET"])
def workflow_get_artifact_content(handler, artifact_id):
    content = get_artifact_content(artifact_id)
    if content is None:
        return bad(404, "Artifact not found")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(content.encode("utf-8"))
    return
```

- [ ] **Step 2: 测试 API 路由**

Run: `pytest tests/ -k "workflow" -v` 或手动测试端点

- [ ] **Step 3: Commit**

```bash
git add api/routes.py
git commit -m "feat(workflow): add API routes for workflow CRUD"
```

---

## Task 3: 工作流面板 UI

**Files:**
- Create: `static/workflow.js`
- Modify: `static/panels.js` (添加 workflow Tab)
- Modify: `static/index.html` (添加 panelWorkflow 容器)
- Modify: `static/style.css` (添加工作流面板样式)

- [ ] **Step 1: 创建 static/workflow.js**

```javascript
/* Workflow panel JS module */
let _workflowTasks = [];
let _currentTaskDetail = null;
let _workflowDetailMode = 'list'; // 'list' | 'detail'

async function loadWorkflowTasks() {
  try {
    const res = await api('/api/workflow/tasks');
    _workflowTasks = res.data || [];
    renderWorkflowPanel();
  } catch (e) {
    showToast('Failed to load workflows: ' + e.message);
  }
}

function renderWorkflowPanel() {
  const panel = document.getElementById('panelWorkflow');
  if (!panel) return;
  
  if (_workflowDetailMode === 'detail' && _currentTaskDetail) {
    renderWorkflowDetail(panel);
  } else {
    renderWorkflowList(panel);
  }
}

function renderWorkflowList(panel) {
  panel.innerHTML = `
    <div class="panel-header">
      <h3>Workflows</h3>
      <button class="btn btn-primary" onclick="showWorkflowCreateModal()">+ New</button>
    </div>
    <div class="workflow-list">
      ${_workflowTasks.length === 0 ? '<p class="empty-state">No workflows yet</p>' : ''}
      ${_workflowTasks.map(t => renderTaskCard(t)).join('')}
    </div>
  `;
}

function renderTaskCard(task) {
  const statusIcon = {'pending':'⏳','running':'🔄','completed':'✅','failed':'❌'}[task.status] || '📄';
  const timeAgo = formatTimeAgo(task.created_at);
  const callsCount = task.calls?.length || 0;
  const artifactsCount = task.artifacts?.length || 0;
  
  return `
    <div class="workflow-card" onclick="openWorkflowDetail('${task.id}')">
      <div class="workflow-card-header">
        <span class="workflow-card-icon">${statusIcon}</span>
        <span class="workflow-card-name">${escapeHtml(task.name)}</span>
        <span class="workflow-card-status">${task.status}</span>
      </div>
      <div class="workflow-card-meta">
        <span>${callsCount} calls</span> · <span>${artifactsCount} artifacts</span>
        <span class="workflow-card-time">${timeAgo}</span>
      </div>
    </div>
  `;
}

async function openWorkflowDetail(taskId) {
  try {
    const res = await api(`/api/workflow/tasks/${taskId}`);
    _currentTaskDetail = res.data;
    _workflowDetailMode = 'detail';
    renderWorkflowPanel();
  } catch (e) {
    showToast('Failed to load task: ' + e.message);
  }
}

function renderWorkflowDetail(panel) {
  const task = _currentTaskDetail;
  const statusIcon = {'pending':'⏳','running':'🔄','completed':'✅','failed':'❌'}[task.status] || '📄';
  
  panel.innerHTML = `
    <div class="panel-header">
      <button class="btn-back" onclick="closeWorkflowDetail()">← Back</button>
      <h3>${escapeHtml(task.name)}</h3>
      <span class="status-badge status-${task.status}">${statusIcon} ${task.status}</span>
    </div>
    <div class="workflow-detail">
      <section class="detail-section">
        <h4>Input</h4>
        <pre class="detail-code">${escapeHtml(JSON.stringify(task.input, null, 2))}</pre>
      </section>
      <section class="detail-section">
        <h4>Calls (${task.calls?.length || 0})</h4>
        <div class="calls-list">
          ${task.calls?.map((callId, i) => renderCallCard(callId, i)).join('') || '<p>No calls</p>'}
        </div>
      </section>
      <section class="detail-section">
        <h4>Artifacts (${task.artifacts?.length || 0})</h4>
        <div class="artifacts-list">
          ${task.artifacts?.map(artId => renderArtifactCard(artId)).join('') || '<p>No artifacts</p>'}
        </div>
      </section>
    </div>
  `;
  
  // Load call details
  loadCallDetails(task.calls || []);
  loadArtifactDetails(task.artifacts || []);
}

async function loadCallDetails(callIds) {
  for (const callId of callIds) {
    try {
      const res = await api(`/api/workflow/tasks/${_currentTaskDetail.id}/calls`);
      const calls = res.data || [];
      calls.forEach(call => {
        const el = document.querySelector(`[data-call-id="${call.id}"]`);
        if (el) {
          el.innerHTML = renderCallCardContent(call);
        }
      });
    } catch (e) {}
  }
}

function renderCallCard(callId, index) {
  return `
    <div class="call-card" data-call-id="${callId}">
      <div class="call-card-loading">Loading call ${index + 1}...</div>
    </div>
  `;
}

function renderCallCardContent(call) {
  return `
    <div class="call-card-content">
      <div class="call-header">
        <span class="call-index">#${call.agent_name}</span>
        <span class="call-status status-${call.status}">${call.status}</span>
      </div>
      <div class="call-body">
        <details>
          <summary>Input</summary>
          <pre class="detail-code">${escapeHtml(JSON.stringify(call.input, null, 2))}</pre>
        </details>
        ${call.output ? `<details>
          <summary>Output</summary>
          <pre class="detail-code">${escapeHtml(JSON.stringify(call.output, null, 2))}</pre>
        </details>` : ''}
        ${call.error ? `<p class="call-error">Error: ${escapeHtml(call.error)}</p>` : ''}
      </div>
    </div>
  `;
}

async function loadArtifactDetails(artifactIds) {
  for (const artId of artifactIds) {
    try {
      const res = await api(`/api/workflow/artifacts/${artId}`);
      const el = document.querySelector(`[data-artifact-id="${artId}"]`);
      if (el && res.data) {
        el.innerHTML = renderArtifactCardContent(res.data);
      }
    } catch (e) {}
  }
}

function renderArtifactCard(artId) {
  return `<div class="artifact-card" data-artifact-id="${artId}"><div class="loading">Loading...</div></div>`;
}

function renderArtifactCardContent(artifact) {
  return `
    <div class="artifact-card-content">
      <span class="artifact-icon">${getArtifactIcon(artifact.type)}</span>
      <span class="artifact-name">${escapeHtml(artifact.name)}</span>
      <span class="artifact-size">${formatFileSize(artifact.size)}</span>
    </div>
  `;
}

function getArtifactIcon(type) {
  return {'document':'📄','code':'💻','image':'🖼️'}[type] || '📎';
}

function closeWorkflowDetail() {
  _currentTaskDetail = null;
  _workflowDetailMode = 'list';
  renderWorkflowPanel();
}

function showWorkflowCreateModal() {
  const name = prompt('Workflow name:');
  if (!name) return;
  createWorkflowTask(name);
}

async function createWorkflowTask(name) {
  try {
    const res = await api('/api/workflow/tasks', {
      method: 'POST',
      body: JSON.stringify({ name, input: {} })
    });
    if (res.data) {
      _workflowTasks.unshift(res.data);
      renderWorkflowPanel();
      showToast('Workflow created');
    }
  } catch (e) {
    showToast('Failed to create workflow: ' + e.message);
  }
}

// Helpers
function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function formatTimeAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
  return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
}

// Export for panel integration
window.loadWorkflowTasks = loadWorkflowTasks;
window.renderWorkflowPanel = renderWorkflowPanel;
window.openWorkflowDetail = openWorkflowDetail;
window.closeWorkflowDetail = closeWorkflowDetail;
window.showWorkflowCreateModal = showWorkflowCreateModal;
```

- [ ] **Step 2: 修改 static/panels.js 添加 workflow Tab**

在 `APP_TITLEBAR_KEYS` 中添加:
```javascript
const APP_TITLEBAR_KEYS = {
  // ... existing entries ...
  workflow: 'tab_workflow',
};
```

在 `_switchPanel` 函数中添加 workflow 处理:
```javascript
if (nextPanel === 'workflow') await loadWorkflowTasks();
```

- [ ] **Step 3: 修改 static/index.html 添加面板容器**

在面板区域添加:
```html
<div id="panelWorkflow" class="panel-view"></div>
```

- [ ] **Step 4: 修改 static/style.css 添加样式**

```css
/* Workflow Panel */
.panel-view#panelWorkflow {
  padding: 16px;
  overflow-y: auto;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-header h3 {
  flex: 1;
  margin: 0;
}

.workflow-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.workflow-card {
  background: var(--bg-secondary, #1a1a2e);
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.workflow-card:hover {
  border-color: var(--accent-color, #4a9eff);
}

.workflow-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.workflow-card-name {
  flex: 1;
  font-weight: 500;
}

.workflow-card-status {
  font-size: 12px;
  color: var(--text-secondary, #888);
}

.workflow-card-meta {
  font-size: 12px;
  color: var(--text-secondary, #888);
  display: flex;
  justify-content: space-between;
}

.workflow-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-section {
  background: var(--bg-secondary, #1a1a2e);
  border-radius: 8px;
  padding: 12px;
}

.detail-section h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: var(--text-secondary, #888);
}

.detail-code {
  background: var(--bg-primary, #0f0f1a);
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.call-card, .artifact-card {
  border: 1px solid var(--border-color, #333);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 8px;
}

.call-header, .artifact-card-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.call-index {
  font-weight: 500;
}

.call-status, .status-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.status-pending { background: #666; }
.status-running { background: #4a9eff; }
.status-completed { background: #2ecc71; }
.status-failed { background: #e74c3c; }

.btn-back {
  background: none;
  border: none;
  color: var(--accent-color, #4a9eff);
  cursor: pointer;
  font-size: 14px;
}

details {
  margin: 4px 0;
}

summary {
  cursor: pointer;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text-secondary, #888);
}

.call-error {
  color: var(--error-color, #e74c3c);
  font-size: 12px;
  margin: 4px 0;
}

.empty-state {
  text-align: center;
  color: var(--text-secondary, #888);
  padding: 32px;
}
```

- [ ] **Step 5: 测试 UI**

手动测试：
1. 刷新页面
2. 点击左侧导航的 Workflow Tab
3. 创建新任务
4. 查看详情展开

- [ ] **Step 6: Commit**

```bash
git add static/workflow.js static/panels.js static/index.html static/style.css
git commit -m "feat(workflow): add workflow panel UI"
```

---

## Task 4: 与 Skills 面板集成

**Files:**
- Modify: `static/workflow.js` (添加从 Skills 触发工作流)

- [ ] **Step 1: 添加从 Skills 触发工作流的功能**

在 static/workflow.js 末尾添加:

```javascript
/* Integration: trigger workflow from Skills panel */
async function triggerWorkflowFromSkill(skillName, params) {
  // Create task with skill as input
  const task = await api('/api/workflow/tasks', {
    method: 'POST',
    body: JSON.stringify({
      name: `Skill: ${skillName}`,
      input: { skill: skillName, params }
    })
  });
  
  if (task.data) {
    _workflowTasks.unshift(task.data);
    renderWorkflowPanel();
    openWorkflowDetail(task.data.id);
    showToast(`Started workflow: ${skillName}`);
  }
}

// Export for skills integration
window.triggerWorkflowFromSkill = triggerWorkflowFromSkill;
```

在 Skills 面板的触发逻辑中调用 `triggerWorkflowFromSkill`

- [ ] **Step 2: Commit**

```bash
git add static/workflow.js
git commit -m "feat(workflow): integrate with skills panel for workflow triggering"
```

---

## Task 5: 端到端测试

**Files:**
- Test: `tests/test_workflow_e2e.py`

- [ ] **Step 1: 写端到端测试**

```python
import pytest

def test_workflow_e2e(client):
    """Full workflow: create task → add call → add artifact → verify"""
    # Create task
    resp = client.post('/api/workflow/tasks', json={
        'name': 'E2E Test Task',
        'input': {'tool': 'test'}
    })
    assert resp.status == 200
    task = resp.json()['data']
    task_id = task['id']
    
    # Add call
    resp = client.post(f'/api/workflow/tasks/{task_id}/calls', json={
        'agent_name': 'test_agent',
        'input': {'query': 'test'}
    })
    assert resp.status == 200
    call = resp.json()['data']
    call_id = call['id']
    
    # Update call
    resp = client.patch(f'/api/workflow/tasks/{task_id}/calls/{call_id}', json={
        'status': 'completed',
        'output': {'result': 'success'}
    })
    assert resp.status == 200
    
    # Add artifact
    resp = client.post(f'/api/workflow/tasks/{task_id}/artifacts', json={
        'call_id': call_id,
        'name': 'result.md',
        'content': '# Test Result',
        'type': 'document'
    })
    assert resp.status == 200
    artifact_id = resp.json()['data']['id']
    
    # Verify task has call and artifact
    resp = client.get(f'/api/workflow/tasks/{task_id}')
    task = resp.json()['data']
    assert call_id in task['calls']
    assert artifact_id in task['artifacts']
    
    # Get artifact content
    resp = client.get(f'/api/workflow/artifacts/{artifact_id}/content')
    assert resp.status == 200
    assert b'# Test Result' in resp.data
    
    # Cleanup
    resp = client.delete(f'/api/workflow/tasks/{task_id}')
    assert resp.status == 200
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_workflow_e2e.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_workflow_e2e.py
git commit -m "test(workflow): add e2e tests"
```

---

## Self-Review Checklist

- [ ] Spec coverage: 所有 Phase 1-2 功能已覆盖
- [ ] Placeholder scan: 无 TBD/TODO
- [ ] Type consistency: 所有函数签名匹配
- [ ] 任务边界清晰，可独立测试

---

## Execution Options

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
