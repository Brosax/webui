import pytest
import json
from api.workflow import (
    create_task, get_task, list_tasks, update_task, delete_task,
    create_agent_call, get_agent_call, get_task_calls, update_agent_call,
    create_artifact, get_artifact, get_artifact_content, get_task_artifacts,
    _ensure_dirs, TASKS_DIR, ARTIFACTS_DIR
)
import shutil
import sys
import os

# Add repo root to path for conftest imports
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Import conftest helpers (test server runs on TEST_PORT)
try:
    from tests.conftest import TEST_BASE
except ImportError:
    # Fallback if conftest not available during standalone test
    TEST_BASE = "http://127.0.0.1:20000"

import http.cookiejar
import urllib.request
import urllib.error


# Create a session for all API tests using urllib
_api_session = None


def _ensure_session():
    """Ensure we have an authenticated session."""
    global _api_session
    if _api_session is not None:
        return _api_session

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    # Check if we need to complete admin setup
    try:
        req = urllib.request.Request(f"{TEST_BASE}/api/auth/status")
        with opener.open(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("setup_required"):
                # Complete admin setup
                data = json.dumps({
                    "username": "testadmin",
                    "password": "testpassword123"
                }).encode()
                req = urllib.request.Request(
                    f"{TEST_BASE}/api/setup/admin",
                    data=data,
                    headers={"Content-Type": "application/json"}
                )
                opener.open(req, timeout=10)
    except Exception:
        pass

    # Login
    try:
        data = json.dumps({
            "username": "testadmin",
            "password": "testpassword123"
        }).encode()
        req = urllib.request.Request(
            f"{TEST_BASE}/api/auth/login",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        opener.open(req, timeout=10)
    except Exception:
        pass

    _api_session = (opener, cookie_jar)
    return _api_session


# Track if we've completed admin setup for the test session
_admin_setup_done = False

def _ensure_admin_setup():
    """Complete admin setup if not already done (for test isolation)."""
    global _admin_setup_done
    if _admin_setup_done:
        return True

    # Check if already setup by querying auth status
    import urllib.request
    try:
        req = urllib.request.Request(TEST_BASE + "/api/auth/status")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            if data.get("setup_required") is False:
                _admin_setup_done = True
                return True
    except Exception:
        pass

    # Complete admin setup
    try:
        _post(TEST_BASE, "/api/setup/admin", {
            "username": "testadmin",
            "password": "testpassword123",
        })
        _admin_setup_done = True
        return True
    except Exception:
        return False


@pytest.fixture(scope="class", autouse=True)
def setup_admin_for_api_tests():
    """Ensure admin is set up and logged in before running API tests."""
    _ensure_session()
    yield


def _get_json(path):
    """Make a GET request using the authenticated session."""
    opener, _ = _ensure_session() or (None, None)
    if not opener:
        return {}, 500
    try:
        req = urllib.request.Request(f"{TEST_BASE}{path}")
        with opener.open(req, timeout=10) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {}, e.code
    except Exception:
        return {}, 500


def _post_json(path, body=None):
    """Make a POST request using the authenticated session."""
    opener, _ = _ensure_session() or (None, None)
    if not opener:
        return {}
    try:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"{TEST_BASE}{path}",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with opener.open(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {}
    except Exception:
        return {}


def _patch_json(path, body):
    """Make a PATCH request using the authenticated session."""
    opener, _ = _ensure_session() or (None, None)
    if not opener:
        return {}, 500
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{TEST_BASE}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="PATCH"
        )
        with opener.open(req, timeout=10) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {}, e.code
    except Exception:
        return {}, 500


def _delete_json(path):
    """Make a DELETE request using the authenticated session."""
    opener, _ = _ensure_session() or (None, None)
    if not opener:
        return {}, 500
    try:
        req = urllib.request.Request(f"{TEST_BASE}{path}", method="DELETE")
        with opener.open(req, timeout=10) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {}, e.code
    except Exception:
        return {}, 500


def _get_content(path):
    """Make a GET request and return raw content."""
    opener, _ = _ensure_session() or (None, None)
    if not opener:
        return "", 500
    try:
        req = urllib.request.Request(f"{TEST_BASE}{path}")
        with opener.open(req, timeout=10) as resp:
            return resp.read().decode("utf-8"), resp.status
    except urllib.error.HTTPError as e:
        return "", e.code
    except Exception:
        return "", 500

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

    # Create an artifact to verify deletion
    call = create_agent_call(task_id, "test_agent")
    artifact = create_artifact(task_id, call["id"], "test.txt", "content")
    artifact_id = artifact["id"]

    # Verify artifact exists
    assert (ARTIFACTS_DIR / artifact_id).exists()

    assert delete_task(task_id) is True
    assert get_task(task_id) is None

    # Verify artifact was deleted
    assert not (ARTIFACTS_DIR / artifact_id).exists()

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


# ── API Route Tests ────────────────────────────────────────────────────────────

class TestWorkflowAPI:
    """Test workflow API endpoints via HTTP."""

    def test_api_list_tasks(self):
        """GET /api/workflow/tasks returns task list."""
        resp, status = _get_json("/api/workflow/tasks")
        assert status == 200
        assert resp.get("success") is True
        assert "data" in resp
        # Should be a list (may be empty)
        assert isinstance(resp["data"], list)

    def test_api_create_task(self):
        """POST /api/workflow/tasks creates a new task."""
        resp = _post_json("/api/workflow/tasks", {
            "name": "API Test Task",
            "input": {"test": True}
        })
        assert resp.get("success") is True
        assert "data" in resp
        task = resp["data"]
        assert task["name"] == "API Test Task"
        assert task["status"] == "pending"
        assert "id" in task

    def test_api_get_task(self):
        """GET /api/workflow/tasks/{task_id} returns task details."""
        # Create a task first
        created = _post_json("/api/workflow/tasks", {"name": "Get Test"})
        task_id = created["data"]["id"]

        # Get the task
        resp, status = _get_json(f"/api/workflow/tasks/{task_id}")
        assert status == 200
        assert resp.get("success") is True
        assert resp["data"]["id"] == task_id
        assert resp["data"]["name"] == "Get Test"

    def test_api_get_task_not_found(self):
        """GET /api/workflow/tasks/{invalid_id} returns 404."""
        resp, status = _get_json("/api/workflow/tasks/nonexistent-id")
        assert status == 404
        assert resp.get("success") is not True

    def test_api_delete_task(self):
        """DELETE /api/workflow/tasks/{task_id} removes the task."""
        # Create a task
        created = _post_json("/api/workflow/tasks", {"name": "To Delete"})
        task_id = created["data"]["id"]

        # Delete it
        resp, status = _delete_json(f"/api/workflow/tasks/{task_id}")
        assert status == 200
        assert resp.get("success") is True

        # Verify it's gone
        _, status = _get_json(f"/api/workflow/tasks/{task_id}")
        assert status == 404

    def test_api_create_and_get_calls(self):
        """POST and GET /api/workflow/tasks/{task_id}/calls works."""
        # Create task
        task = _post_json("/api/workflow/tasks", {"name": "Call Test"})["data"]
        task_id = task["id"]

        # Create a call
        call_resp = _post_json(f"/api/workflow/tasks/{task_id}/calls", {
            "agent_name": "test-agent",
            "input": {"query": "hello"}
        })
        assert call_resp.get("success") is True
        call = call_resp["data"]
        assert call["agent_name"] == "test-agent"
        assert call["status"] == "pending"

        # Get calls
        resp, _ = _get_json(f"/api/workflow/tasks/{task_id}/calls")
        assert resp.get("success") is True
        assert len(resp["data"]) >= 1
        assert any(c["id"] == call["id"] for c in resp["data"])

    def test_api_update_call(self):
        """PATCH /api/workflow/tasks/{task_id}/calls/{call_id} updates call."""
        # Create task and call
        task = _post_json("/api/workflow/tasks", {"name": "Update Test"})["data"]
        task_id = task["id"]
        call = _post_json(f"/api/workflow/tasks/{task_id}/calls", {
            "agent_name": "updater"
        })["data"]
        call_id = call["id"]

        # Update call
        resp, status = _patch_json(
            f"/api/workflow/tasks/{task_id}/calls/{call_id}",
            {"status": "completed", "output": {"result": "done"}}
        )
        assert status == 200
        assert resp.get("success") is True
        assert resp["data"]["status"] == "completed"
        assert resp["data"]["output"]["result"] == "done"

    def test_api_create_and_get_artifacts(self):
        """POST and GET /api/workflow/tasks/{task_id}/artifacts works."""
        # Create task
        task = _post_json("/api/workflow/tasks", {"name": "Artifact Test"})["data"]
        task_id = task["id"]

        # Create artifact
        art_resp = _post_json(f"/api/workflow/tasks/{task_id}/artifacts", {
            "name": "report.md",
            "content": "# Report Content",
            "type": "document"
        })
        assert art_resp.get("success") is True
        artifact = art_resp["data"]
        assert artifact["name"] == "report.md"
        assert artifact["type"] == "document"

        # Get artifacts
        resp, _ = _get_json(f"/api/workflow/tasks/{task_id}/artifacts")
        assert resp.get("success") is True
        assert len(resp["data"]) >= 1
        assert any(a["id"] == artifact["id"] for a in resp["data"])

    def test_api_get_artifact_metadata(self):
        """GET /api/workflow/artifacts/{artifact_id} returns metadata."""
        # Create task and artifact
        task = _post_json("/api/workflow/tasks", {"name": "Meta Test"})["data"]
        task_id = task["id"]
        artifact = _post_json(f"/api/workflow/tasks/{task_id}/artifacts", {
            "name": "data.json",
            "content": '{"key": "value"}',
            "type": "data"
        })["data"]
        artifact_id = artifact["id"]

        # Get artifact metadata
        resp, status = _get_json(f"/api/workflow/artifacts/{artifact_id}")
        assert status == 200
        assert resp.get("success") is True
        assert resp["data"]["id"] == artifact_id
        assert resp["data"]["name"] == "data.json"

    def test_api_get_artifact_content(self):
        """GET /api/workflow/artifacts/{artifact_id}/content returns file content."""
        # Create task and artifact
        task = _post_json("/api/workflow/tasks", {"name": "Content Test"})["data"]
        task_id = task["id"]
        artifact = _post_json(f"/api/workflow/tasks/{task_id}/artifacts", {
            "name": "hello.txt",
            "content": "Hello, World!",
            "type": "document"
        })["data"]
        artifact_id = artifact["id"]

        # Get content
        content, status = _get_content(f"/api/workflow/artifacts/{artifact_id}/content")
        assert status == 200
        assert content == "Hello, World!"

    def test_api_artifact_not_found(self):
        """GET /api/workflow/artifacts/{invalid_id} returns 404."""
        resp, status = _get_json("/api/workflow/artifacts/nonexistent-id")
        assert status == 404

    def test_api_artifact_content_not_found(self):
        """GET /api/workflow/artifacts/{invalid_id}/content returns 404."""
        content, status = _get_content("/api/workflow/artifacts/nonexistent/content")
        assert status == 404