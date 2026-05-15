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


def _workflow_doc(name="Demo", edges=None):
    from api.workflow_markdown import render_workflow_markdown

    return render_workflow_markdown(
        {
            "schema_version": 1,
            "id": "demo",
            "name": name,
            "description": "Example",
            "default_profile": "coding",
            "inputs": [{"key": "topic", "type": "text"}],
            "nodes": [
                {"id": "input", "type": "input", "name": "Topic", "config": {"key": "topic", "type": "text"}},
                {"id": "prompt", "type": "prompt", "name": "Draft prompt", "config": {"template": "Write about {{ inputs.topic }}"}},
                {"id": "agent", "type": "agent", "name": "Writer", "config": {"instruction": "{{ steps.prompt.output.template }}"}},
                {"id": "output", "type": "output", "name": "Result", "config": {"value": "{{ steps.agent.output.message }}", "type": "text"}},
            ],
            "edges": edges if edges is not None else [
                {"from": "input", "to": "prompt"},
                {"from": "prompt", "to": "agent"},
                {"from": "agent", "to": "output"},
            ],
            "outputs": [{"key": "result", "type": "text", "source": "output"}],
            "canvas": {"nodes": {"input": {"x": 40, "y": 120}}},
        },
        existing_markdown="# Human notes\n\nKeep this note.\n",
    )


def test_markdown_round_trip_preserves_human_notes():
    from api.workflow_markdown import parse_workflow_markdown, render_workflow_markdown

    source = _workflow_doc()
    parsed = parse_workflow_markdown(source)
    assert parsed["name"] == "Demo"
    assert parsed["inputs"][0]["type"] == "text"

    rendered = render_workflow_markdown({**parsed, "name": "Renamed"}, existing_markdown=source)
    assert "Keep this note." in rendered
    assert '"name": "Renamed"' in rendered
    assert parse_workflow_markdown(rendered)["name"] == "Renamed"


def test_invalid_json_and_cycles_are_rejected():
    from api.workflow_markdown import parse_workflow_markdown, validate_workflow_document

    with pytest.raises(ValueError, match="Invalid workflow JSON"):
        parse_workflow_markdown("<!-- hermes-workflow:start -->\n```json\n{bad\n```\n<!-- hermes-workflow:end -->")

    with pytest.raises(ValueError, match="cycle"):
        validate_workflow_document({
            "schema_version": 1,
            "name": "Cyclic",
            "nodes": [
                {"id": "input", "type": "input"},
                {"id": "prompt", "type": "prompt"},
            ],
            "edges": [
                {"from": "input", "to": "prompt"},
                {"from": "prompt", "to": "input"},
            ],
        })


def test_source_path_must_stay_inside_workspace(tmp_path):
    from api.workflow_markdown import resolve_workflow_source_path

    with pytest.raises(ValueError, match="relative"):
        resolve_workflow_source_path(tmp_path, "/tmp/out.workflow.md")
    with pytest.raises(ValueError, match="outside"):
        resolve_workflow_source_path(tmp_path, "../out.workflow.md")
    assert resolve_workflow_source_path(tmp_path, "workflows/demo.workflow.md") == tmp_path / "workflows" / "demo.workflow.md"


def test_create_import_save_source_and_checksum_conflict(tmp_path):
    from api.workflow_markdown import create_markdown_workflow, import_markdown_workflow, read_workflow_source, save_workflow_source
    from api.workflow_trace import get_workflow_definition

    created = create_markdown_workflow(tmp_path, "workflows/blank.workflow.md", "Blank", actor="alice")
    assert (tmp_path / "workflows" / "blank.workflow.md").exists()
    assert created["metadata"]["source_path"] == "workflows/blank.workflow.md"
    assert created["input_schema"] == []

    imported_path = tmp_path / "workflows" / "imported.workflow.md"
    imported_path.write_text(_workflow_doc(name="Imported"), encoding="utf-8")
    imported = import_markdown_workflow(tmp_path, "workflows/imported.workflow.md", actor="alice")
    assert imported["name"] == "Imported"
    assert imported["metadata"]["source_path"] == "workflows/imported.workflow.md"
    assert imported["metadata"]["_canvas_edges"] == [
        {"from": "input", "to": "prompt"},
        {"from": "prompt", "to": "agent"},
        {"from": "agent", "to": "output"},
    ]

    source = read_workflow_source(tmp_path, imported["workflow_id"])
    changed = source["source"].replace('"description": "Example"', '"description": "Changed"')
    saved = save_workflow_source(tmp_path, imported["workflow_id"], changed, expected_checksum=source["checksum"])
    assert saved["definition"]["description"] == "Changed"
    assert get_workflow_definition(imported["workflow_id"])["description"] == "Changed"

    with pytest.raises(ValueError, match="conflict"):
        save_workflow_source(tmp_path, imported["workflow_id"], changed, expected_checksum=source["checksum"])


def test_markdown_preview_run_uses_topological_order(tmp_path):
    from api.workflow_markdown import import_markdown_workflow
    from api.workflow_trace import list_run_nodes, run_workflow_definition

    path = tmp_path / "workflows" / "ordered.workflow.md"
    path.parent.mkdir()
    path.write_text(_workflow_doc(name="Ordered"), encoding="utf-8")
    definition = import_markdown_workflow(tmp_path, "workflows/ordered.workflow.md", actor="alice")

    run = run_workflow_definition(
        definition["workflow_id"],
        actor="alice",
        user={"username": "alice", "role": "member"},
        inputs={"topic": "tests"},
        is_test_run=True,
    )
    assert run["status"] == "completed"
    names = [node["name"] for node in list_run_nodes(run["run_id"])]
    assert names == ["Topic", "Draft prompt", "Writer", "Result"]


def test_extended_editor_schema_round_trip_and_port_validation():
    from api.workflow_markdown import parse_workflow_markdown, render_workflow_markdown, validate_workflow_document

    doc = {
        "schema_version": 1,
        "name": "Editor schema",
        "nodes": [
            {
                "id": "manual",
                "type": "trigger.manual",
                "name": "Manual",
                "position": {"x": 40, "y": 80},
                "parameters": {"payload": {"topic": "tests"}},
            },
            {
                "id": "set",
                "type": "core.set",
                "name": "Set value",
                "position": {"x": 320, "y": 80},
                "parameters": {"key": "topic", "value": "{{ inputs.topic }}"},
                "continueOnFail": True,
            },
            {
                "id": "out",
                "type": "output.results_display",
                "name": "Results",
                "position": {"x": 600, "y": 80},
                "parameters": {"value": "{{ steps.set.output.value }}"},
                "disabled": False,
            },
        ],
        "edges": [
            {"id": "e1", "source": "manual", "target": "set", "sourceHandle": "out", "targetHandle": "in"},
            {"id": "e2", "source": "set", "target": "out", "sourceHandle": "out", "targetHandle": "in"},
        ],
        "canvas": {"zoom": 1.2, "scroll": {"x": 10, "y": 20}, "selectedNodeIds": ["set"]},
    }
    source = render_workflow_markdown(doc, existing_markdown="# Notes\n")
    parsed = parse_workflow_markdown(source)
    assert parsed["nodes"][0]["position"] == {"x": 40, "y": 80}
    assert parsed["nodes"][1]["parameters"]["key"] == "topic"
    assert parsed["edges"][0]["sourceHandle"] == "out"

    bad = {**doc, "edges": [{"source": "manual", "target": "set", "sourceHandle": "in", "targetHandle": "in"}]}
    with pytest.raises(ValueError, match="sourceHandle"):
        validate_workflow_document(bad)

    bad_type = {**doc, "edges": [{"source": "manual", "target": "set", "sourceHandle": "out", "targetHandle": "error"}]}
    with pytest.raises(ValueError, match="targetHandle"):
        validate_workflow_document(bad_type)


def test_dag_run_skips_disabled_nodes_and_records_not_implemented(tmp_path):
    from api.workflow_markdown import import_markdown_workflow, render_workflow_markdown
    from api.workflow_trace import list_run_nodes, run_workflow_definition

    path = tmp_path / "workflows" / "dag.workflow.md"
    path.parent.mkdir()
    path.write_text(
        render_workflow_markdown({
            "schema_version": 1,
            "name": "DAG",
            "nodes": [
                {"id": "manual", "type": "trigger.manual", "name": "Manual", "parameters": {"payload": {"topic": "from trigger"}}},
                {"id": "skip", "type": "utility.sleep", "name": "Disabled", "disabled": True},
                {"id": "unknown", "type": "utility.transform", "name": "Later", "continueOnFail": True},
                {"id": "out", "type": "output.results_display", "name": "Results", "parameters": {"value": "{{ steps.manual.output.payload.topic }}"}},
            ],
            "edges": [
                {"source": "manual", "target": "skip", "sourceHandle": "out", "targetHandle": "in"},
                {"source": "skip", "target": "unknown", "sourceHandle": "out", "targetHandle": "in"},
                {"source": "unknown", "target": "out", "sourceHandle": "out", "targetHandle": "in"},
            ],
        })
    )
    definition = import_markdown_workflow(tmp_path, "workflows/dag.workflow.md", actor="alice")
    run = run_workflow_definition(
        definition["workflow_id"],
        actor="alice",
        user={"username": "alice", "role": "member"},
        inputs={"topic": "tests"},
        is_test_run=True,
    )
    assert run["status"] == "completed"
    nodes = list_run_nodes(run["run_id"])
    statuses = {node["name"]: node["status"] for node in nodes}
    assert statuses["Disabled"] == "skipped"
    assert statuses["Later"] == "failed"
    assert statuses["Results"] == "completed"
    assert "not implemented" in (run["metadata"]["step_outputs"]["unknown"]["error"].lower())
