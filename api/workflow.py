"""Workflow data layer: Task/AgentCall/Artifact CRUD via JSON files."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import shutil

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