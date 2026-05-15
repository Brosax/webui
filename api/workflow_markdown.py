"""Markdown-backed workflow source helpers.

Workflow Markdown is the canonical editable source. The SQLite definition row
is an index/cache used by listing, publishing, runs, and trace.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


START_MARKER = "<!-- hermes-workflow:start -->"
END_MARKER = "<!-- hermes-workflow:end -->"
_BLOCK_RE = re.compile(
    re.escape(START_MARKER)
    + r"\s*```(?:json)?\s*(.*?)\s*```\s*"
    + re.escape(END_MARKER),
    re.DOTALL,
)
_SUPPORTED_TYPES = {
    "input",
    "prompt",
    "agent",
    "output",
    "trigger.manual",
    "core.set",
    "control.if_else",
    "control.merge",
    "agent.run",
    "output.results_display",
    "file.operations",
    "utility.http_request",
}
_SUPPORTED_IO_TYPES = {"text", "json", "file"}
_SOURCE_HANDLES = {"out", "true", "false", "_branch", "_route", "route0", "route1", "route2"}
_TARGET_HANDLES = {"in"}


def source_checksum(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def parse_workflow_markdown(source: str) -> dict:
    match = _BLOCK_RE.search(source or "")
    if not match:
        raise ValueError("Workflow Markdown is missing hermes-workflow block")
    raw_json = match.group(1).strip()
    try:
        doc = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid workflow JSON: {exc.msg}") from exc
    if not isinstance(doc, dict):
        raise ValueError("Workflow JSON must be an object")
    validate_workflow_document(doc)
    return doc


def render_workflow_markdown(doc: dict, existing_markdown: str = "") -> str:
    validate_workflow_document(doc)
    block = (
        f"{START_MARKER}\n"
        "```json\n"
        f"{json.dumps(doc, ensure_ascii=False, indent=2)}\n"
        "```\n"
        f"{END_MARKER}"
    )
    if _BLOCK_RE.search(existing_markdown or ""):
        return _BLOCK_RE.sub(block, existing_markdown, count=1)
    prefix = (existing_markdown or "").rstrip()
    if prefix:
        return f"{prefix}\n\n{block}\n"
    return f"{block}\n"


def validate_workflow_document(doc: dict) -> None:
    if int(doc.get("schema_version") or 1) != 1:
        raise ValueError("Unsupported workflow schema_version")
    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    inputs = doc.get("inputs") or []
    outputs = doc.get("outputs") or []
    if not isinstance(nodes, list):
        raise ValueError("nodes must be an array")
    if not isinstance(edges, list):
        raise ValueError("edges must be an array")
    seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("Each node must be an object")
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise ValueError("Each node requires an id")
        if node_id in seen:
            raise ValueError(f"Duplicate node id: {node_id}")
        seen.add(node_id)
        node_type = str(node.get("type") or "").strip()
        if not _is_supported_node_type(node_type):
            raise ValueError(f"Unsupported node type: {node_type}")
    for item in list(inputs) + list(outputs):
        if not isinstance(item, dict):
            raise ValueError("inputs and outputs must contain objects")
        io_type = str(item.get("type") or "text")
        if io_type not in _SUPPORTED_IO_TYPES:
            raise ValueError(f"Unsupported input/output type: {io_type}")
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("Each edge must be an object")
        from_id = _edge_endpoint(edge, "from", "source")
        to_id = _edge_endpoint(edge, "to", "target")
        if from_id not in seen or to_id not in seen:
            raise ValueError("Each edge must reference existing nodes")
        if from_id == to_id:
            raise ValueError("Workflow graph contains a cycle")
        source_handle = str(edge.get("sourceHandle") or edge.get("source_handle") or "out").strip()
        target_handle = str(edge.get("targetHandle") or edge.get("target_handle") or "in").strip()
        if source_handle not in _SOURCE_HANDLES:
            raise ValueError(f"Invalid sourceHandle: {source_handle}")
        if target_handle not in _TARGET_HANDLES:
            raise ValueError(f"Invalid targetHandle: {target_handle}")
    _topological_node_ids(nodes, edges)


def resolve_workflow_source_path(workspace_root: str | Path, source_path: str) -> Path:
    raw = Path(str(source_path or ""))
    if raw.is_absolute():
        raise ValueError("Workflow source path must be workspace-relative")
    root = Path(workspace_root).expanduser().resolve()
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Workflow source path escapes outside workspace") from exc
    if ".." in raw.parts:
        raise ValueError("Workflow source path escapes outside workspace")
    if resolved.suffix != ".md" or not resolved.name.endswith(".workflow.md"):
        raise ValueError("Workflow source path must end with .workflow.md")
    return resolved


def create_markdown_workflow(
    workspace_root: str | Path,
    source_path: str,
    name: str,
    actor: str = "unknown",
    project_id: str | None = None,
    template: str = "blank",
) -> dict:
    from api.workflow_trace import create_workflow_definition, update_workflow_definition

    target = resolve_workflow_source_path(workspace_root, source_path)
    if target.exists():
        raise ValueError("Workflow source file already exists")
    slug = target.name.removesuffix(".workflow.md")
    doc = _blank_document(slug, name, template=template)
    source = render_workflow_markdown(doc, existing_markdown=f"# {name}\n\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    fields = _definition_fields_from_doc(doc, source_path, source_checksum(source))
    created = create_workflow_definition(
        name=fields["name"],
        created_by=actor,
        project_id=project_id,
        description=fields["description"],
        input_schema=fields["input_schema"],
        draft_steps=fields["draft_steps"],
        default_profile=fields["default_profile"],
        metadata=fields["metadata"],
    )
    if doc.get("id") != created.get("workflow_id"):
        doc["id"] = created["workflow_id"]
        source = render_workflow_markdown(doc, existing_markdown=source)
        target.write_text(source, encoding="utf-8")
        fields = _definition_fields_from_doc(doc, source_path, source_checksum(source))
        created = update_workflow_definition(created["workflow_id"], **fields) or created
    return created


def import_markdown_workflow(
    workspace_root: str | Path,
    source_path: str,
    actor: str = "unknown",
    project_id: str | None = None,
) -> dict:
    from api.workflow_trace import create_workflow_definition

    target = resolve_workflow_source_path(workspace_root, source_path)
    if not target.exists():
        raise ValueError("Workflow source file not found")
    source = target.read_text(encoding="utf-8")
    doc = parse_workflow_markdown(source)
    fields = _definition_fields_from_doc(doc, source_path, source_checksum(source))
    return create_workflow_definition(
        name=fields["name"],
        created_by=actor,
        project_id=project_id,
        description=fields["description"],
        input_schema=fields["input_schema"],
        draft_steps=fields["draft_steps"],
        default_profile=fields["default_profile"],
        metadata=fields["metadata"],
    )


def read_workflow_source(workspace_root: str | Path, workflow_id: str) -> dict:
    from api.workflow_trace import get_workflow_definition

    definition = get_workflow_definition(workflow_id)
    if not definition:
        raise ValueError("Workflow definition not found")
    metadata = definition.get("metadata") or {}
    source_path = metadata.get("source_path")
    if not source_path:
        source = render_workflow_markdown(_document_from_legacy_definition(definition))
        return {
            "source": source,
            "checksum": source_checksum(source),
            "source_path": None,
            "compatibility_mode": True,
        }
    target = resolve_workflow_source_path(workspace_root, source_path)
    if not target.exists():
        raise ValueError("Workflow source file not found")
    source = target.read_text(encoding="utf-8")
    return {
        "source": source,
        "checksum": source_checksum(source),
        "source_path": source_path,
        "compatibility_mode": False,
    }


def save_workflow_source(
    workspace_root: str | Path,
    workflow_id: str,
    source: str,
    expected_checksum: str | None = None,
    source_path: str | None = None,
) -> dict:
    from api.workflow_trace import get_workflow_definition, update_workflow_definition

    definition = get_workflow_definition(workflow_id)
    if not definition:
        raise ValueError("Workflow definition not found")
    metadata = definition.get("metadata") or {}
    rel_path = source_path or metadata.get("source_path")
    if not rel_path:
        slug = _slugify(definition.get("name") or workflow_id)
        rel_path = f"workflows/{slug}.workflow.md"
    target = resolve_workflow_source_path(workspace_root, rel_path)
    current_source = target.read_text(encoding="utf-8") if target.exists() else ""
    current_checksum = source_checksum(current_source) if current_source else None
    if expected_checksum and current_checksum and expected_checksum != current_checksum:
        raise ValueError("Workflow source conflict: checksum mismatch")
    doc = parse_workflow_markdown(source)
    rendered = render_workflow_markdown(doc, existing_markdown=source)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    fields = _definition_fields_from_doc(doc, rel_path, source_checksum(rendered))
    updated = update_workflow_definition(workflow_id, **fields)
    return {
        "definition": updated,
        "source": rendered,
        "checksum": source_checksum(rendered),
        "source_path": rel_path,
    }


def _definition_fields_from_doc(doc: dict, source_path: str, checksum: str) -> dict:
    metadata = dict(doc.get("metadata") or {})
    metadata["_canvas_edges"] = _normalise_edges(doc.get("edges") or [])
    metadata["source_path"] = source_path
    metadata["source_checksum"] = checksum
    metadata["outputs"] = doc.get("outputs") or []
    metadata["canvas"] = doc.get("canvas") or {}
    return {
        "name": str(doc.get("name") or "Untitled Workflow"),
        "description": str(doc.get("description") or ""),
        "default_profile": doc.get("default_profile"),
        "input_schema": doc.get("inputs") or [],
        "draft_steps": _steps_from_doc(doc),
        "metadata": metadata,
    }


def _steps_from_doc(doc: dict) -> list[dict]:
    nodes = {str(node.get("id")): dict(node) for node in doc.get("nodes") or []}
    ordered_ids = _topological_node_ids(list(nodes.values()), doc.get("edges") or [])
    steps: list[dict] = []
    for node_id in ordered_ids:
        node = nodes[node_id]
        config = dict(node.get("parameters") or node.get("config") or {})
        step = {
            "step_id": node_id,
            "type": str(node.get("type") or ""),
            "name": node.get("name") or node_id,
            "config": config,
            "parameters": config,
            "position": node.get("position") or {},
            "disabled": bool(node.get("disabled")),
            "continueOnFail": bool(node.get("continueOnFail") or node.get("continue_on_fail")),
        }
        if step["type"] == "agent":
            step["prompt"] = config.get("instruction") or config.get("prompt") or ""
        if step["type"] == "prompt":
            step["template"] = config.get("template") or ""
        if step["type"] == "output":
            step["value"] = config.get("value")
            step["artifact_name"] = config.get("artifact_name")
            step["artifact_type"] = config.get("artifact_type") or config.get("type") or "document"
        steps.append(step)
    return steps


def _document_from_legacy_definition(definition: dict) -> dict:
    metadata = definition.get("metadata") or {}
    return {
        "schema_version": 1,
        "id": definition.get("workflow_id"),
        "name": definition.get("name") or "Untitled Workflow",
        "description": definition.get("description") or "",
        "default_profile": definition.get("default_profile"),
        "inputs": definition.get("input_schema") or [],
        "nodes": _legacy_nodes(definition.get("draft_steps") or []),
        "edges": metadata.get("_canvas_edges") or [],
        "outputs": metadata.get("outputs") or [],
        "canvas": metadata.get("canvas") or {},
    }


def _legacy_nodes(steps: list[dict]) -> list[dict]:
    nodes = []
    for idx, step in enumerate(steps):
        step_id = str(step.get("step_id") or step.get("id") or f"step_{idx + 1}")
        step_type = str(step.get("type") or "agent").replace("agent_instruction", "agent")
        if step_type == "file_input":
            step_type = "input"
        if step_type == "file_output":
            step_type = "output"
        if not _is_supported_node_type(step_type):
            step_type = "agent"
        config = dict(step.get("parameters") or step.get("config") or {})
        position = step.get("position") or {}
        if not position and ("x" in step or "y" in step):
            position = {"x": step.get("x", 80 + idx * 260), "y": step.get("y", 120)}
        nodes.append({
            "id": step_id,
            "type": step_type,
            "name": step.get("name") or step_id,
            "position": position,
            "parameters": config,
            "disabled": bool(step.get("disabled")),
            "continueOnFail": bool(step.get("continueOnFail") or step.get("continue_on_fail")),
            "config": config,
        })
    return nodes


def _topological_node_ids(nodes: list[dict], edges: list[dict]) -> list[str]:
    ids = [str(node.get("id")) for node in nodes]
    incoming = {node_id: 0 for node_id in ids}
    outgoing = {node_id: [] for node_id in ids}
    for edge in edges:
        from_id = _edge_endpoint(edge, "from", "source")
        to_id = _edge_endpoint(edge, "to", "target")
        outgoing[from_id].append(to_id)
        incoming[to_id] += 1
    ready = [node_id for node_id in ids if incoming[node_id] == 0]
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for next_id in outgoing[node_id]:
            incoming[next_id] -= 1
            if incoming[next_id] == 0:
                ready.append(next_id)
    if len(ordered) != len(ids):
        raise ValueError("Workflow graph contains a cycle")
    return ordered


def _normalise_edges(edges: list[dict]) -> list[dict]:
    normalised = []
    for edge in edges:
        item = {"from": _edge_endpoint(edge, "from", "source"), "to": _edge_endpoint(edge, "to", "target")}
        if edge.get("id"):
            item["id"] = str(edge.get("id"))
        source_handle = edge.get("sourceHandle") or edge.get("source_handle")
        target_handle = edge.get("targetHandle") or edge.get("target_handle")
        if source_handle:
            item["sourceHandle"] = str(source_handle)
        if target_handle:
            item["targetHandle"] = str(target_handle)
        normalised.append(item)
    return normalised


def _edge_endpoint(edge: dict, primary: str, legacy: str) -> str:
    return str(edge.get(primary) or edge.get(legacy) or "").strip()


def _is_supported_node_type(node_type: str) -> bool:
    if node_type in _SUPPORTED_TYPES:
        return True
    prefix = node_type.split(".", 1)[0]
    return prefix in {"trigger", "core", "control", "agent", "output", "file", "utility", "llm", "mcp", "safety", "data"}


def _blank_document(slug: str, name: str, template: str = "blank") -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    if template == "basic":
        nodes = [
            {"id": "input", "type": "input", "name": "Input", "position": {"x": 60, "y": 120}, "parameters": {"key": "topic", "type": "text"}},
            {"id": "agent", "type": "agent.run", "name": "Agent", "position": {"x": 340, "y": 120}, "parameters": {"instruction": "Process {{ inputs.topic }}"}},
            {"id": "output", "type": "output.results_display", "name": "Output", "position": {"x": 620, "y": 120}, "parameters": {"value": "{{ steps.agent.output.message }}", "type": "text"}},
        ]
        edges = [{"source": "input", "target": "agent", "sourceHandle": "out", "targetHandle": "in"}, {"source": "agent", "target": "output", "sourceHandle": "out", "targetHandle": "in"}]
    return {
        "schema_version": 1,
        "id": slug,
        "name": name,
        "description": "",
        "default_profile": None,
        "inputs": [],
        "nodes": nodes,
        "edges": edges,
        "outputs": [],
        "canvas": {},
    }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "workflow"
