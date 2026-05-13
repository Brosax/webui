"""Tests for workflow canvas save/load and run engine."""
import json
import pathlib

import pytest
from api.workflow_trace import (
    save_canvas_definition,
    load_canvas_definition,
    run_canvas_workflow,
)


def test_canvas_save_load_roundtrip():
    """Nodes + edges JSON survives save/load cycle."""
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


def test_canvas_run_simple(tmp_path):
    """A file_input → agent → file_output chain runs without error."""
    # Create a temp input file
    input_file = tmp_path / "test.txt"
    input_file.write_text("hello world")

    nodes = [
        {"id": "input1", "type": "file_input", "x": 50, "y": 100, "config": {"path": str(input_file)}},
        {"id": "agent1", "type": "agent", "x": 250, "y": 100, "config": {"agent": "chat", "instruction": "Summarize the file."}},
        {"id": "output1", "type": "file_output", "x": 450, "y": 100, "config": {"format": "txt"}},
    ]
    edges = [
        {"from": "input1", "to": "agent1"},
        {"from": "agent1", "to": "output1"},
    ]
    wf = save_canvas_definition("test-run", nodes, edges, created_by="tester")
    run = run_canvas_workflow(wf["workflow_id"], actor="tester", inputs={"path": str(input_file)})
    assert run["status"] in ("completed", "running")


def test_canvas_run_inline_nodes(tmp_path):
    """Inline nodes/edges (no saved def) runs without error."""
    input_file = tmp_path / "test.txt"
    input_file.write_text("inline test")

    nodes = [
        {"id": "input1", "type": "file_input", "x": 50, "y": 100, "config": {"path": str(input_file)}},
        {"id": "agent1", "type": "agent", "x": 250, "y": 100, "config": {"agent": "chat", "instruction": "Echo the file."}},
    ]
    edges = [{"from": "input1", "to": "agent1"}]
    run = run_canvas_workflow(
        workflow_id=None,
        actor="tester",
        inputs={"path": str(input_file)},
        inline_nodes=nodes,
        inline_edges=edges,
    )
    assert run["status"] in ("completed", "running")


# ---------------------------------------------------------------------------
# Route-level integration tests (require live test server on port 8788)
# ---------------------------------------------------------------------------

def test_canvas_routes_save_load(clean_trace_env):
    """POST /api/workflow/canvas saves canvas; GET /api/workflow/canvas/{id} loads it."""
    import urllib.request, urllib.error

    base = "http://127.0.0.1:8787"
    payload = json.dumps({
        "name": "route-test-canvas",
        "nodes": [{"id": "a", "type": "agent", "name": "Node A", "config": {"instruction": "hello"}}],
        "edges": [{"source": "a", "target": "b", "label": "then"}]
    }).encode()
    req = urllib.request.Request(
        base + "/api/workflow/canvas",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    assert resp["success"] is True
    wf_id = resp["data"]["workflow_id"]
    assert wf_id is not None

    # Load it back
    req2 = urllib.request.Request(base + "/api/workflow/canvas/" + wf_id)
    loaded = json.loads(urllib.request.urlopen(req2, timeout=10).read())
    assert loaded["success"] is True
    assert loaded["data"]["workflow_id"] == wf_id
    assert loaded["data"]["nodes"][0]["id"] == "a"
    assert loaded["data"]["edges"][0]["source"] == "a"


def test_run_canvas_inline_route(clean_trace_env):
    """POST /api/workflow/canvas/run executes inline nodes and returns run record."""
    import urllib.request, urllib.error

    base = "http://127.0.0.1:8787"
    payload = json.dumps({
        "inputs": {"msg": "test input"},
        "nodes": [
            {"id": "n1", "type": "agent", "name": "First Agent", "config": {"instruction": "say hello"}},
            {"id": "n2", "type": "output", "name": "Output Node", "config": {"value": "Result: {{inputs.msg}}"}}
        ],
        "edges": [{"source": "n1", "target": "n2"}]
    }).encode()
    req = urllib.request.Request(
        base + "/api/workflow/canvas/run",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    assert resp["success"] is True
    run = resp["data"]
    assert run["status"] == "completed"
    assert run["run_id"] is not None
    # Verify nodes were created for this run
    from api.workflow_trace import list_run_nodes
    nodes = list_run_nodes(run["run_id"])
    assert len(nodes) >= 1


def test_canvas_live_sse_route(clean_trace_env):
    """GET /api/workflow/canvas/live/{run_id} returns SSE stream."""
    import urllib.request, urllib.error

    base = "http://127.0.0.1:8787"

    # First create a run via canvas/run
    payload = json.dumps({
        "nodes": [{"id": "x", "type": "agent", "name": "X", "config": {}}],
        "edges": []
    }).encode()
    req = urllib.request.Request(
        base + "/api/workflow/canvas/run",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    run_resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    run_id = run_resp["data"]["run_id"]

    # Now poll the live SSE endpoint
    sse_req = urllib.request.Request(base + "/api/workflow/canvas/live/" + run_id)
    try:
        resp = urllib.request.urlopen(sse_req, timeout=10)
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "text/event-stream"
        body = resp.read().decode("utf-8")
        # SSE data: should be JSON wrapped in "data: "
        assert "data: " in body
        data = json.loads(body.split("data: ")[1].split("\n\n")[0])
        assert "run" in data
        assert data["run"]["run_id"] == run_id
    except urllib.error.HTTPError as e:
        pytest.fail(f"SSE endpoint returned {e.code}: {e.read()}")


def test_canvas_route_404_for_unknown_id(clean_trace_env):
    """GET /api/workflow/canvas/{unknown_id} returns 404."""
    import urllib.request, urllib.error

    base = "http://127.0.0.1:8787"
    req = urllib.request.Request(base + "/api/workflow/canvas/nonexistent12345678")
    try:
        urllib.request.urlopen(req, timeout=5)
        pytest.fail("Expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404