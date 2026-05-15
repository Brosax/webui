import os
import pathlib
import shutil

import pytest


STATE_DIR = pathlib.Path(
    os.getenv("HERMES_WEBUI_TEST_STATE_DIR", str(pathlib.Path.home() / ".hermes" / "webui-mvp"))
)
TRACE_DIR = STATE_DIR / "workflow_trace"


@pytest.fixture(autouse=True)
def clean_trace_env():
    import api.workflow_trace as wt
    if TRACE_DIR.exists():
        shutil.rmtree(TRACE_DIR)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    wt._connections.clear()
    yield
    if TRACE_DIR.exists():
        shutil.rmtree(TRACE_DIR)
    wt._connections.clear()


def test_create_and_list_workflow_definitions():
    from api.workflow_trace import create_workflow_definition, list_workflow_definitions

    user = {"username": "alice", "role": "member"}
    created = create_workflow_definition(
        name="invoice-flow",
        created_by="alice",
        project_id="proj-a",
        input_schema=[{"key": "invoice_id", "type": "text"}],
        draft_steps=[{"step_id": "s1", "type": "agent_instruction", "prompt": "hello"}],
    )
    assert created["workflow_id"]
    defs = list_workflow_definitions(project_id="proj-a", user=user)
    assert any(d["workflow_id"] == created["workflow_id"] for d in defs)


def test_publish_creates_version():
    from api.workflow_trace import (
        create_workflow_definition,
        publish_workflow_definition,
        list_workflow_versions,
        get_workflow_definition,
    )

    created = create_workflow_definition(
        name="report-flow",
        created_by="alice",
        project_id="proj-a",
        draft_steps=[{"step_id": "s1", "type": "agent_instruction", "prompt": "draft"}],
    )
    version = publish_workflow_definition(created["workflow_id"], actor="alice")
    assert version is not None
    assert version["version_number"] == 1

    versions = list_workflow_versions(created["workflow_id"])
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1

    definition = get_workflow_definition(created["workflow_id"])
    assert definition["status"] == "published"
    assert definition["published_version_id"] == version["version_id"]


def test_run_published_workflow_completes():
    from api.workflow_trace import (
        create_workflow_definition,
        publish_workflow_definition,
        run_workflow_definition,
        get_trace_payload,
    )

    definition = create_workflow_definition(
        name="delivery-flow",
        created_by="alice",
        project_id="proj-a",
        input_schema=[{"key": "customer", "type": "text"}],
        draft_steps=[
            {"step_id": "s1", "type": "agent_instruction", "prompt": "hello {{ inputs.customer }}"},
            {"step_id": "s2", "type": "approval"},
            {"step_id": "s3", "type": "output", "value": "{{ steps.s1.output.message }}", "artifact_name": "result.txt"},
        ],
    )
    publish_workflow_definition(definition["workflow_id"], actor="alice")

    user = {"username": "alice", "role": "member"}
    run = run_workflow_definition(
        workflow_id=definition["workflow_id"],
        actor="alice",
        user=user,
        inputs={"customer": "Acme", "_approvals": {"s2": {"approved": True, "message": "ok"}}},
        is_test_run=False,
    )
    assert run["status"] == "completed"
    payload = get_trace_payload(run["run_id"])
    assert payload is not None
    assert len(payload["nodes"]) >= 3
    assert len(payload["events"]) >= 3


def test_run_without_approval_decision_pauses():
    from api.workflow_trace import (
        create_workflow_definition,
        publish_workflow_definition,
        run_workflow_definition,
    )

    definition = create_workflow_definition(
        name="approval-flow",
        created_by="alice",
        project_id="proj-a",
        draft_steps=[
            {"step_id": "s1", "type": "approval"},
        ],
    )
    publish_workflow_definition(definition["workflow_id"], actor="alice")
    user = {"username": "alice", "role": "member"}
    run = run_workflow_definition(
        workflow_id=definition["workflow_id"],
        actor="alice",
        user=user,
        inputs={},
        is_test_run=False,
    )
    assert run["status"] == "pending_approval"


def test_test_run_uses_draft_without_publish():
    from api.workflow_trace import create_workflow_definition, run_workflow_definition

    definition = create_workflow_definition(
        name="draft-only-flow",
        created_by="alice",
        project_id="proj-a",
        draft_steps=[{"step_id": "s1", "type": "agent_instruction", "prompt": "draft-only"}],
    )
    user = {"username": "alice", "role": "member"}
    run = run_workflow_definition(
        workflow_id=definition["workflow_id"],
        actor="alice",
        user=user,
        inputs={},
        is_test_run=True,
    )
    assert run["status"] == "completed"
    meta = run.get("metadata") or {}
    assert meta.get("is_test_run") is True
    assert meta.get("workflow_version_id") is None
