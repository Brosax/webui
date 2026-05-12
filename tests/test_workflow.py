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