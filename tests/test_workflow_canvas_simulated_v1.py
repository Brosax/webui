"""Regression tests for simulated workflow canvas V1 execution."""
import os
import pathlib
import shutil
import time

import pytest


STATE_DIR = pathlib.Path(
    os.getenv("HERMES_WEBUI_TEST_STATE_DIR", str(pathlib.Path.home() / ".hermes" / "webui-mvp"))
)
TRACE_DIR = STATE_DIR / "workflow_trace"
WORKSPACE = pathlib.Path(os.getenv("HERMES_WEBUI_DEFAULT_WORKSPACE", str(STATE_DIR / "test-workspace")))


@pytest.fixture(autouse=True)
def clean_trace_env():
    import api.workflow_trace as wt

    if TRACE_DIR.exists():
        shutil.rmtree(TRACE_DIR)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    wt._connections.clear()
    yield
    if TRACE_DIR.exists():
        shutil.rmtree(TRACE_DIR)
    wt._connections.clear()


def _wait_for_terminal(run_id, timeout=5):
    from api.workflow_trace import get_run

    deadline = time.time() + timeout
    while time.time() < deadline:
        run = get_run(run_id)
        if run and run.get("status") in ("completed", "failed", "cancelled"):
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def _wait_for_status(run_id, predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach expected status")


def test_simulated_canvas_runs_linear_edge_path_and_artifact_output():
    from api.workflow_trace import get_artifact_content, list_run_artifacts, list_run_nodes, run_canvas_workflow

    (WORKSPACE / "input.md").write_text("# Demo\n\nImportant workflow text.", encoding="utf-8")
    nodes = [
        {"id": "trigger_1", "type": "trigger.manual", "name": "Trigger", "parameters": {}},
        {"id": "file_1", "type": "file.input", "name": "File", "parameters": {"path": "{{inputs.file_path}}"}},
        {"id": "agent_1", "type": "agent.run", "name": "Agent", "parameters": {"instruction": "{{inputs.topic}}"}},
        {
            "id": "output_1",
            "type": "file.output",
            "name": "Output",
            "parameters": {"filename": "result.txt", "template": "{{steps.agent_1.output.message}}"},
        },
    ]
    edges = [
        {"source": "trigger_1", "target": "file_1"},
        {"source": "file_1", "target": "agent_1"},
        {"source": "agent_1", "target": "output_1"},
    ]

    run = run_canvas_workflow(
        actor="alice",
        inputs={"file_path": "input.md", "file_type": "markdown", "topic": "summarize", "_simulate_delay_ms": 0},
        inline_nodes=nodes,
        inline_edges=edges,
        is_test_run=True,
    )
    finished = _wait_for_terminal(run["run_id"])

    assert finished["status"] == "completed"
    trace_nodes = list_run_nodes(run["run_id"])
    assert [node["status"] for node in trace_nodes] == ["completed", "completed", "completed", "completed"]
    file_output = trace_nodes[-1]["structured_result"]
    assert file_output["destination"] == "artifact"
    artifacts = list_run_artifacts(run["run_id"])
    assert len(artifacts) == 1
    assert "Simulated agent response" in get_artifact_content(artifacts[0]["artifact_id"])


def test_simulated_canvas_accepts_legacy_input_node_type():
    from api.workflow_trace import list_run_nodes, run_canvas_workflow

    (WORKSPACE / "legacy.md").write_text("Legacy input content.", encoding="utf-8")
    nodes = [
        {"id": "input", "type": "input", "name": "Input", "parameters": {"path": "{{inputs.file_path}}"}},
        {"id": "agent", "type": "agent.run", "name": "Agent", "parameters": {"instruction": "{{inputs.topic}}"}},
        {"id": "output", "type": "output.results_display", "name": "Output", "parameters": {"template": "{{steps.agent.output.message}}"}},
    ]
    edges = [
        {"source": "input", "target": "agent"},
        {"source": "agent", "target": "output"},
    ]

    run = run_canvas_workflow(
        actor="alice",
        inputs={"file_path": "legacy.md", "topic": "summarize", "_simulate_delay_ms": 0},
        inline_nodes=nodes,
        inline_edges=edges,
        is_test_run=True,
    )
    finished = _wait_for_terminal(run["run_id"])

    assert finished["status"] == "completed"
    trace_nodes = list_run_nodes(run["run_id"])
    assert trace_nodes[0]["agent_name"] == "workflow:file.input"
    assert [node["status"] for node in trace_nodes] == ["completed", "completed", "completed"]


def test_simulated_canvas_failure_marks_remaining_nodes_skipped():
    from api.workflow_trace import list_run_nodes, run_canvas_workflow

    nodes = [
        {"id": "trigger_1", "type": "trigger.manual", "name": "Trigger", "parameters": {}},
        {"id": "bad_1", "type": "utility.sleep", "name": "Unsupported", "parameters": {}},
        {"id": "output_1", "type": "output.results_display", "name": "Output", "parameters": {}},
    ]
    edges = [
        {"source": "trigger_1", "target": "bad_1"},
        {"source": "bad_1", "target": "output_1"},
    ]

    run = run_canvas_workflow(
        actor="alice",
        inputs={"_simulate_delay_ms": 0},
        inline_nodes=nodes,
        inline_edges=edges,
        is_test_run=True,
    )
    finished = _wait_for_terminal(run["run_id"])

    assert finished["status"] == "failed"
    statuses = [node["status"] for node in list_run_nodes(run["run_id"])]
    assert statuses == ["completed", "failed", "skipped"]


def test_simulated_canvas_cancel_skips_unstarted_nodes():
    from api.workflow_trace import cancel_run, list_run_nodes, run_canvas_workflow

    nodes = [
        {"id": "trigger_1", "type": "trigger.manual", "name": "Trigger", "parameters": {}},
        {"id": "agent_1", "type": "agent.run", "name": "Agent", "parameters": {}},
        {"id": "output_1", "type": "output.results_display", "name": "Output", "parameters": {}},
    ]
    edges = [
        {"source": "trigger_1", "target": "agent_1"},
        {"source": "agent_1", "target": "output_1"},
    ]

    run = run_canvas_workflow(
        actor="alice",
        inputs={"_simulate_delay_ms": 500},
        inline_nodes=nodes,
        inline_edges=edges,
        is_test_run=True,
    )
    cancel_run(run["run_id"])
    finished = _wait_for_terminal(run["run_id"])

    assert finished["status"] == "cancelled"
    _wait_for_status(
        run["run_id"],
        lambda: "skipped" in [node["status"] for node in list_run_nodes(run["run_id"])],
    )
    statuses = [node["status"] for node in list_run_nodes(run["run_id"])]
    assert "skipped" in statuses


def test_simulated_canvas_human_review_pauses_without_decision():
    from api.workflow_trace import get_run, list_run_nodes, run_canvas_workflow

    nodes = [
        {"id": "trigger_1", "type": "trigger.manual", "name": "Trigger", "parameters": {}},
        {"id": "agent_1", "type": "agent.run", "name": "Agent", "parameters": {"instruction": "draft"}},
        {"id": "review_1", "type": "human.review", "name": "Review", "parameters": {"title": "Manager review"}},
        {"id": "output_1", "type": "output.results_display", "name": "Output", "parameters": {}},
    ]
    edges = [
        {"source": "trigger_1", "target": "agent_1"},
        {"source": "agent_1", "target": "review_1"},
        {"source": "review_1", "target": "output_1"},
    ]

    run = run_canvas_workflow(
        actor="alice",
        inputs={"_simulate_delay_ms": 0},
        inline_nodes=nodes,
        inline_edges=edges,
        is_test_run=True,
    )

    _wait_for_status(run["run_id"], lambda: (get_run(run["run_id"]) or {}).get("status") == "pending_approval")
    latest = get_run(run["run_id"])
    assert latest is not None
    assert latest["status"] == "pending_approval"
    assert latest.get("metadata", {}).get("pending_step_id") == "review_1"
    statuses = [node["status"] for node in list_run_nodes(run["run_id"])]
    assert statuses == ["completed", "completed", "pending", "pending"]


def test_simulated_canvas_human_review_completes_when_approved():
    from api.workflow_trace import list_run_nodes, run_canvas_workflow

    nodes = [
        {"id": "trigger_1", "type": "trigger.manual", "name": "Trigger", "parameters": {}},
        {"id": "agent_1", "type": "agent.run", "name": "Agent", "parameters": {"instruction": "draft"}},
        {"id": "review_1", "type": "human.review", "name": "Review", "parameters": {"title": "Manager review"}},
        {"id": "output_1", "type": "output.results_display", "name": "Output", "parameters": {"template": "{{steps.agent_1.output.message}}"}},
    ]
    edges = [
        {"source": "trigger_1", "target": "agent_1"},
        {"source": "agent_1", "target": "review_1"},
        {"source": "review_1", "target": "output_1"},
    ]

    run = run_canvas_workflow(
        actor="alice",
        inputs={"_simulate_delay_ms": 0, "_approvals": {"review_1": {"approved": True, "message": "looks good"}}},
        inline_nodes=nodes,
        inline_edges=edges,
        is_test_run=True,
    )
    finished = _wait_for_terminal(run["run_id"])

    assert finished["status"] == "completed"
    statuses = [node["status"] for node in list_run_nodes(run["run_id"])]
    assert statuses == ["completed", "completed", "completed", "completed"]
