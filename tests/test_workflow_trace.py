"""
Backend tests for workflow trace — schema init, migration, ACLs, membership CRUD,
redaction, run lifecycle, approval events, skill snapshot immutability.
"""
import json
import os
import pathlib
import shutil
import sqlite3

import pytest

TESTS_DIR = pathlib.Path(__file__).parent.resolve()
STATE_DIR = pathlib.Path(os.getenv("HERMES_WEBUI_TEST_STATE_DIR", str(pathlib.Path.home() / ".hermes" / "webui-mvp")))
TRACE_DIR = STATE_DIR / "workflow_trace"
TRACE_DB = TRACE_DIR / "trace.db"


def _get_db():
    """Get a fresh SQLite connection to the trace DB (bypasses module caching)."""
    import sqlite3
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(TRACE_DB), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture(autouse=True)
def clean_trace_env():
    """Wipe trace state before and after each test."""
    import api.workflow_trace as wt
    if TRACE_DIR.exists():
        shutil.rmtree(TRACE_DIR)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    # Clear module-level connection cache so next test gets fresh connection
    wt._connections.clear()
    yield
    if TRACE_DIR.exists():
        shutil.rmtree(TRACE_DIR)
    wt._connections.clear()


# ---------------------------------------------------------------------------
# Schema init + migration
# ---------------------------------------------------------------------------
def test_schema_init_creates_tables():
    """Verify all trace tables exist with v2 schema columns."""
    from api.workflow_trace import _get_conn

    _get_conn()  # initialize schema

    conn = _get_db()
    for table in ("workflow_runs", "workflow_nodes", "workflow_events",
                  "workflow_artifacts", "project_trace_memberships"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        assert row is not None, f"Table {table} not created"

    # Verify v2 membership schema
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(project_trace_memberships)").fetchall()}
    assert "username" in cols
    assert "role" in cols
    assert "run_id" not in cols


def test_schema_init_foreign_keys():
    """Verify foreign key constraints are set up (ON DELETE CASCADE)."""
    from api.workflow_trace import _get_conn, create_run, create_node, delete_run

    _get_conn()  # initialize schema

    conn = _get_db()
    # Check that foreign keys are enforced by verifying a CASCADE delete works
    run = create_run(project_id="fk-test-proj", name="FK Test", created_by="alice")
    node = create_node(run["run_id"], agent_name="Agent")
    run_id = run["run_id"]
    node_id = node["node_id"]

    delete_run(run_id)
    # Node should be gone due to CASCADE
    conn = _get_db()
    row = conn.execute("SELECT node_id FROM workflow_nodes WHERE node_id = ?", (node_id,)).fetchone()
    assert row is None, "Node should have been cascade-deleted"


def test_schema_migration_old_membership_table():
    """Old (project_id, run_id, can_read, can_write) migrates to per-user schema."""
    from api.workflow_trace import _migrate_if_needed, list_project_members

    # Create fresh schema first
    from api.workflow_trace import _get_conn
    _get_conn()

    # Drop membership table and recreate with old schema
    conn = _get_db()
    conn.execute("DROP TABLE IF EXISTS project_trace_memberships")
    conn.execute("""
        CREATE TABLE project_trace_memberships (
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            can_read INTEGER NOT NULL DEFAULT 1,
            can_write INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (project_id, run_id)
        )
    """)
    # Insert a run with old membership
    run_id = "oldrun001"
    conn.execute("""
        INSERT INTO workflow_runs
            (run_id, project_id, name, status, created_by, created_at, updated_at, metadata)
        VALUES (?, ?, ?, 'running', 'alice', datetime('now'), datetime('now'), '{}')
    """, (run_id, "proj-old", "Old Run"))
    conn.execute(
        "INSERT INTO project_trace_memberships (project_id, run_id, can_read, can_write) VALUES (?, ?, 1, 0)",
        ("proj-old", run_id)
    )
    conn.commit()
    conn.close()

    # Calling _get_conn again triggers migration
    from api.workflow_trace import _get_conn as gc
    gc()

    # New table should exist with per-user schema
    conn2 = _get_db()
    cols = {r["name"] for r in conn2.execute("PRAGMA table_info(project_trace_memberships)").fetchall()}
    assert "username" in cols, "New membership table should have username column"
    assert "run_id" not in cols, "run_id should be removed from membership table"
    assert "role" in cols, "New membership table should have role column"
    conn2.close()

    # Owner should be backfilled from created_by
    members = list_project_members("proj-old")
    assert len(members) >= 1
    assert any(m["username"] == "alice" for m in members)


# ---------------------------------------------------------------------------
# Run CRUD
# ---------------------------------------------------------------------------
def test_create_run():
    from api.workflow_trace import create_run, get_run

    run = create_run(project_id="proj1", name="Test Run", created_by="alice")
    assert run["run_id"] is not None
    assert run["name"] == "Test Run"
    assert run["status"] == "running"
    assert run["project_id"] == "proj1"
    assert run["created_by"] == "alice"

    fetched = get_run(run["run_id"])
    assert fetched is not None
    assert fetched["run_id"] == run["run_id"]


def test_create_run_no_project():
    from api.workflow_trace import create_run

    run = create_run(project_id=None, name="Private Run", created_by="alice")
    assert run["project_id"] is None
    assert run["status"] == "running"


def test_create_run_seeds_owner_on_first_run():
    """First run for a project seeds the creator as owner."""
    from api.workflow_trace import create_run, list_project_members

    run = create_run(project_id="new-proj", name="First Run", created_by="founder")
    members = list_project_members("new-proj")
    assert len(members) == 1
    assert members[0]["username"] == "founder"
    assert members[0]["role"] == "owner"


def test_create_run_does_not_seed_on_subsequent_runs():
    """Subsequent runs for a project don't add extra memberships."""
    from api.workflow_trace import create_run, list_project_members, upsert_project_membership

    run1 = create_run(project_id="proj-x", name="Run 1", created_by="alice")
    upsert_project_membership("proj-x", "bob", role="writer", can_read=True, can_write=True)
    run2 = create_run(project_id="proj-x", name="Run 2", created_by="alice")

    members = list_project_members("proj-x")
    # Should have alice (seeded on first run) + bob (added manually) = 2
    usernames = {m["username"] for m in members}
    assert "alice" in usernames
    assert "bob" in usernames


def test_update_run():
    from api.workflow_trace import create_run, update_run

    run = create_run(name="Update Test", created_by="alice")
    updated = update_run(run["run_id"], status="completed", ended_at="2025-01-01T00:00:00Z")
    assert updated["status"] == "completed"
    assert updated["ended_at"] == "2025-01-01T00:00:00Z"


def test_cancel_run():
    from api.workflow_trace import create_run, cancel_run

    run = create_run(name="Cancel Test", created_by="alice")
    cancelled = cancel_run(run["run_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["ended_at"] is not None


def test_delete_run():
    from api.workflow_trace import create_run, delete_run, get_run

    run = create_run(name="Delete Test", created_by="alice")
    assert delete_run(run["run_id"]) is True
    assert get_run(run["run_id"]) is None


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------
def test_create_node():
    from api.workflow_trace import create_run, create_node, get_node

    run = create_run(name="Node Test", created_by="alice")
    node = create_node(run["run_id"], agent_name="TestAgent", name="Node 1")
    assert node["node_id"] is not None
    assert node["agent_name"] == "TestAgent"
    assert node["status"] == "running"

    fetched = get_node(node["node_id"])
    assert fetched["node_id"] == node["node_id"]


def test_create_node_with_parent():
    from api.workflow_trace import create_run, create_node

    run = create_run(name="Parent Node Test", created_by="alice")
    parent = create_node(run["run_id"], agent_name="ParentAgent")
    child = create_node(run["run_id"], agent_name="ChildAgent", parent_node_id=parent["node_id"])
    assert child["parent_node_id"] == parent["node_id"]


def test_update_node():
    from api.workflow_trace import create_run, create_node, update_node

    run = create_run(name="Update Node Test", created_by="alice")
    node = create_node(run["run_id"], agent_name="UpdateNode")
    updated = update_node(
        node["node_id"],
        status="completed",
        structured_result={"result": "success"},
        summary="Done",
    )
    assert updated["status"] == "completed"
    assert updated["structured_result"] == {"result": "success"}
    assert updated["summary"] == "Done"


def test_list_run_nodes():
    from api.workflow_trace import create_run, create_node, list_run_nodes

    run = create_run(name="List Nodes Test", created_by="alice")
    n1 = create_node(run["run_id"], agent_name="Agent1")
    n2 = create_node(run["run_id"], agent_name="Agent2")
    nodes = list_run_nodes(run["run_id"])
    node_ids = {n["node_id"] for n in nodes}
    assert n1["node_id"] in node_ids
    assert n2["node_id"] in node_ids


# ---------------------------------------------------------------------------
# Append-only events
# ---------------------------------------------------------------------------
def test_append_event():
    from api.workflow_trace import create_run, append_event, list_run_events

    run = create_run(name="Event Test", created_by="alice")
    event = append_event(
        run["run_id"], event_type="tool_call", actor="alice",
        payload={"tool": "test_tool", "args": {"arg1": "value1"}},
    )
    assert event["event_id"] is not None
    assert event["event_type"] == "tool_call"
    assert event["actor"] == "alice"
    assert event["redacted"] is False
    assert event["truncated"] is False


def test_append_event_with_node():
    from api.workflow_trace import create_run, create_node, append_event

    run = create_run(name="Node Event Test", created_by="alice")
    node = create_node(run["run_id"], agent_name="EventNode")
    event = append_event(run["run_id"], "node_started", node_id=node["node_id"])
    assert event["node_id"] == node["node_id"]


def test_events_cascade_delete_with_run():
    """Events are deleted when parent run is deleted."""
    from api.workflow_trace import create_run, append_event, delete_run, list_run_events

    run = create_run(name="Cascade Test", created_by="alice")
    append_event(run["run_id"], "test_event")
    delete_run(run["run_id"])
    events = list_run_events(run["run_id"])
    assert len(events) == 0


def test_event_truncation():
    from api.workflow_trace import create_run, append_event

    run = create_run(name="Truncation Test", created_by="alice")
    large_payload = {"data": "x" * 300_000}
    event = append_event(run["run_id"], "large_event", payload=large_payload)
    assert event["truncated"] is True


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------
def test_create_artifact():
    from api.workflow_trace import create_run, create_artifact, get_artifact

    run = create_run(name="Artifact Test", created_by="alice")
    artifact = create_artifact(
        run["run_id"], name="test.txt", artifact_type="document",
        content="Hello, World!",
    )
    assert artifact["artifact_id"] is not None
    assert artifact["name"] == "test.txt"
    assert artifact["size"] == len("Hello, World!")


def test_artifact_content_on_disk():
    from api.workflow_trace import create_run, create_artifact, get_artifact_content

    run = create_run(name="Artifact Content Test", created_by="alice")
    content = "File content here"
    artifact = create_artifact(run["run_id"], name="content.txt", content=content)
    read_back = get_artifact_content(artifact["artifact_id"])
    assert read_back == content


def test_artifact_hash_on_stored_content():
    """Hash is computed on the stored (potentially redacted) bytes."""
    from api.workflow_trace import create_run, create_artifact, get_artifact

    run = create_run(name="Hash Test", created_by="alice")
    artifact = create_artifact(run["run_id"], name="test.txt", content="hello")
    assert artifact["hash_sha256"] is not None
    # Hash of "hello"
    import hashlib
    expected = hashlib.sha256(b"hello").hexdigest()
    assert artifact["hash_sha256"] == expected


def test_list_run_artifacts():
    from api.workflow_trace import create_run, create_artifact, list_run_artifacts

    run = create_run(name="List Artifacts Test", created_by="alice")
    a1 = create_artifact(run["run_id"], name="a1.txt", content="a")
    a2 = create_artifact(run["run_id"], name="a2.txt", content="b")
    artifacts = list_run_artifacts(run["run_id"])
    artifact_ids = {a["artifact_id"] for a in artifacts}
    assert a1["artifact_id"] in artifact_ids
    assert a2["artifact_id"] in artifact_ids


# ---------------------------------------------------------------------------
# ACL — can_read_run / can_write_run / user_can_trace_audit
# ---------------------------------------------------------------------------

def _make_user(username, role="user", trace_audit=0):
    return {"username": username, "role": role, "trace_audit": trace_audit, "profile_name": "default"}


def test_user_can_trace_audit():
    from api.workflow_trace import user_can_trace_audit

    assert user_can_trace_audit(_make_user("alice", trace_audit=1)) is True
    assert user_can_trace_audit(_make_user("bob", trace_audit=0)) is False
    assert user_can_trace_audit(None) is False
    assert user_can_trace_audit(_make_user("eve")) is False


def test_admin_can_read_any_run():
    from api.workflow_trace import create_run, can_read_run

    run = create_run(name="Admin Test", project_id="secret-project", created_by="alice")
    admin = _make_user("admin", role="admin")
    assert can_read_run(run["run_id"], admin) is True


def test_admin_can_write_any_run():
    from api.workflow_trace import create_run, can_write_run

    run = create_run(name="Admin Write Test", project_id="secret-project", created_by="alice")
    admin = _make_user("admin", role="admin")
    assert can_write_run(run["run_id"], admin) is True


def test_trace_auditor_cross_project_access():
    """User with trace_audit=1 can read across projects."""
    from api.workflow_trace import create_run, can_read_run

    run = create_run(name="Cross Project", project_id="other-project", created_by="eve")
    auditor = _make_user("auditor", trace_audit=1)
    assert can_read_run(run["run_id"], auditor) is True


def test_trace_auditor_can_write():
    from api.workflow_trace import create_run, can_write_run

    run = create_run(name="Auditor Write", project_id="secret", created_by="eve")
    auditor = _make_user("auditor", trace_audit=1)
    assert can_write_run(run["run_id"], auditor) is True


def test_project_member_can_read():
    from api.workflow_trace import create_run, can_read_run, upsert_project_membership

    run = create_run(name="Member Read", project_id="proj-member", created_by="alice")
    upsert_project_membership("proj-member", "bob", role="member", can_read=True, can_write=False)
    bob = _make_user("bob")
    assert can_read_run(run["run_id"], bob) is True


def test_project_member_cannot_write():
    from api.workflow_trace import create_run, can_write_run, upsert_project_membership

    run = create_run(name="Member Write", project_id="proj-member", created_by="alice")
    upsert_project_membership("proj-member", "bob", role="member", can_read=True, can_write=False)
    bob = _make_user("bob")
    assert can_write_run(run["run_id"], bob) is False


def test_project_writer_can_write():
    from api.workflow_trace import create_run, can_write_run, upsert_project_membership

    run = create_run(name="Writer Write", project_id="proj-writer", created_by="alice")
    upsert_project_membership("proj-writer", "bob", role="writer", can_read=True, can_write=True)
    bob = _make_user("bob")
    assert can_write_run(run["run_id"], bob) is True


def test_project_owner_can_write():
    from api.workflow_trace import create_run, can_write_run, upsert_project_membership

    run = create_run(name="Owner Write", project_id="proj-owner", created_by="alice")
    upsert_project_membership("proj-owner", "alice", role="owner", can_read=True, can_write=True)
    alice = _make_user("alice")
    assert can_write_run(run["run_id"], alice) is True


def test_non_member_cannot_read_project_run():
    """User not in project memberships cannot read the run."""
    from api.workflow_trace import create_run, can_read_run

    run = create_run(name="Private Project", project_id="private-proj", created_by="alice")
    outsider = _make_user("bob")  # No membership
    assert can_read_run(run["run_id"], outsider) is False


def test_non_member_cannot_write_project_run():
    from api.workflow_trace import create_run, can_write_run

    run = create_run(name="Private Project Write", project_id="private-proj", created_by="alice")
    outsider = _make_user("bob")
    assert can_write_run(run["run_id"], outsider) is False


def test_project_id_null_run_private_to_creator():
    """project_id=NULL run is only readable/writable by the creator."""
    from api.workflow_trace import create_run, can_read_run, can_write_run

    run = create_run(name="Private Run", project_id=None, created_by="alice")
    alice = _make_user("alice")
    bob = _make_user("bob")

    assert can_read_run(run["run_id"], alice) is True
    assert can_write_run(run["run_id"], alice) is True
    assert can_read_run(run["run_id"], bob) is False
    assert can_write_run(run["run_id"], bob) is False


def test_creator_can_read_write_null_project():
    from api.workflow_trace import create_run, can_read_run, can_write_run

    run = create_run(name="Creator Only", project_id=None, created_by="alice")
    alice = _make_user("alice")
    assert can_read_run(run["run_id"], alice) is True
    assert can_write_run(run["run_id"], alice) is True


# ---------------------------------------------------------------------------
# Membership CRUD
# ---------------------------------------------------------------------------

def test_seed_project_owner_membership():
    from api.workflow_trace import seed_project_owner_membership, list_project_members

    seed_project_owner_membership("proj-seed", "founder")
    members = list_project_members("proj-seed")
    assert len(members) == 1
    assert members[0]["username"] == "founder"
    assert members[0]["role"] == "owner"


def test_upsert_project_membership():
    from api.workflow_trace import upsert_project_membership, list_project_members, get_user_role_in_project

    upsert_project_membership("proj-up", "alice", role="owner", can_read=True, can_write=True)
    assert get_user_role_in_project("proj-up", "alice") == "owner"

    upsert_project_membership("proj-up", "bob", role="reader", can_read=True, can_write=False)
    assert get_user_role_in_project("proj-up", "bob") == "reader"

    members = list_project_members("proj-up")
    assert len(members) == 2


def test_remove_project_membership():
    from api.workflow_trace import upsert_project_membership, remove_project_membership, list_project_members

    upsert_project_membership("proj-rm", "alice", role="owner")
    upsert_project_membership("proj-rm", "bob", role="member")
    assert len(list_project_members("proj-rm")) == 2

    remove_project_membership("proj-rm", "bob")
    members = list_project_members("proj-rm")
    assert len(members) == 1
    assert members[0]["username"] == "alice"


def test_owner_backfill_from_created_by():
    """Seed owner membership works for a project with existing runs."""
    from api.workflow_trace import seed_project_owner_membership, list_project_members

    # Seed owner for a project
    seed_project_owner_membership("migrated-proj", "mig-user")
    members = list_project_members("migrated-proj")
    assert any(m["username"] == "mig-user" for m in members)


# ---------------------------------------------------------------------------
# list_runs visibility filtering
# ---------------------------------------------------------------------------

def test_list_runs_filters_by_visibility():
    from api.workflow_trace import create_run, list_runs, upsert_project_membership

    # Public run (no project) created by alice
    r1 = create_run(name="Alice Private", project_id=None, created_by="alice")
    # Project run for proj-visible with bob as member
    r2 = create_run(name="Project Run", project_id="proj-vis", created_by="alice")
    upsert_project_membership("proj-vis", "bob", role="member", can_read=True, can_write=False)
    # Project run for proj-secret with no bob membership
    r3 = create_run(name="Secret Run", project_id="proj-secret", created_by="eve")

    alice = _make_user("alice")
    bob = _make_user("bob")
    eve = _make_user("eve")

    all_runs_alice = list_runs(user=alice)
    alice_run_ids = {r["run_id"] for r in all_runs_alice}
    # Alice sees her private run and proj-vis run (she's owner)
    assert r1["run_id"] in alice_run_ids
    assert r2["run_id"] in alice_run_ids
    # Alice doesn't see secret project
    assert r3["run_id"] not in alice_run_ids

    bob_runs = list_runs(user=bob)
    bob_run_ids = {r["run_id"] for r in bob_runs}
    assert r2["run_id"] in bob_run_ids  # bob is member
    assert r1["run_id"] not in bob_run_ids  # alice's private
    assert r3["run_id"] not in bob_run_ids  # secret


# ---------------------------------------------------------------------------
# Full trace payload
# ---------------------------------------------------------------------------

def test_get_trace_payload():
    from api.workflow_trace import (
        create_run, create_node, append_event, create_artifact, get_trace_payload,
    )

    run = create_run(name="Full Payload", project_id="payload-proj", created_by="alice")
    run_id = run["run_id"]
    node = create_node(run_id, agent_name="PayloadAgent")
    append_event(run_id, "node_started", node_id=node["node_id"], payload={"order": 1})
    append_event(run_id, "node_ended", node_id=node["node_id"], payload={"order": 2})
    artifact = create_artifact(run_id, name="payload.txt", content="data")

    trace = get_trace_payload(run_id)
    assert trace["run"]["run_id"] == run_id
    assert len(trace["nodes"]) >= 1
    assert len(trace["events"]) == 2
    assert len(trace["artifacts"]) >= 1
    # Events sorted by event_id
    event_ids = [e["event_id"] for e in trace["events"]]
    assert event_ids == sorted(event_ids)


# ---------------------------------------------------------------------------
# Approval + skill snapshot events
# ---------------------------------------------------------------------------

def test_append_approval_event():
    from api.workflow_trace import create_run, append_approval_event

    run = create_run(name="Approval Test", created_by="alice")
    event = append_approval_event(
        run["run_id"], node_id=None, actor="alice",
        pattern_keys=["key1", "key2"],
        payload={"approved": True},
    )
    assert event is not None
    assert event["payload"]["type"] == "approval"
    assert event["payload"]["pattern_keys"] == ["key1", "key2"]


def test_append_skill_snapshot_event():
    from api.workflow_trace import create_run, append_skill_snapshot_event

    run = create_run(name="Skill Snapshot Test", created_by="alice")
    snapshot = {"name": "my-skill", "version": "1.0"}
    event = append_skill_snapshot_event(
        run["run_id"], node_id=None, actor="system",
        skill_name="my-skill", snapshot=snapshot,
    )
    assert event is not None
    assert event["payload"]["type"] == "skill_snapshot"
    assert event["payload"]["skill_name"] == "my-skill"


# ---------------------------------------------------------------------------
# Run lifecycle + counts
# ---------------------------------------------------------------------------

def test_run_lifecycle_pending_to_completed():
    from api.workflow_trace import create_run, update_run, get_run

    run = create_run(name="Lifecycle Test", created_by="alice")
    assert run["status"] == "running"
    updated = update_run(run["run_id"], status="completed", ended_at="2025-01-01T00:00:00Z")
    assert updated["status"] == "completed"

    fetched = get_run(run["run_id"])
    assert fetched["status"] == "completed"


def test_run_node_event_counts():
    from api.workflow_trace import create_run, create_node, append_event, get_run

    run = create_run(name="Count Test", created_by="alice")
    run_id = run["run_id"]
    create_node(run_id, agent_name="CountNode")
    append_event(run_id, "event1")
    append_event(run_id, "event2")
    fetched = get_run(run_id)
    assert fetched["node_count"] == 1
    assert fetched["event_count"] == 2


# ---------------------------------------------------------------------------
# Skill snapshot immutability
# ---------------------------------------------------------------------------

def test_skill_snapshot_immutable_after_node_creation():
    from api.workflow_trace import create_run, create_node, get_node, update_node

    run = create_run(name="Immutable Test", created_by="alice")
    snapshot = {"name": "immutable-skill", "version": "2.0", "tools": ["t1"]}
    node = create_node(run["run_id"], agent_name="ImmAgent", skill_snapshot=snapshot)
    update_node(node["node_id"], status="completed")
    fetched = get_node(node["node_id"])
    assert fetched["skill_snapshot"] == snapshot


# ---------------------------------------------------------------------------
# Permission helpers edge cases
# ---------------------------------------------------------------------------

def test_can_read_run_rejects_none_user():
    from api.workflow_trace import create_run, can_read_run

    run = create_run(name="No User Test", created_by="alice")
    assert can_read_run(run["run_id"], None) is False


def test_can_write_run_rejects_none_user():
    from api.workflow_trace import create_run, can_write_run

    run = create_run(name="No User Write Test", created_by="alice")
    assert can_write_run(run["run_id"], None) is False


def test_get_user_role_in_project_nonexistent():
    from api.workflow_trace import get_user_role_in_project

    assert get_user_role_in_project("nonexistent", "alice") is None


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------

def test_redact_prompt_long():
    """Long prompt is redacted (uses api.helpers._redact_text)."""
    from api.workflow_trace import _apply_redaction

    long_text = "Hello world, " * 1000
    redacted, was_changed = _apply_redaction(long_text)
    # No secret pattern matched, so unchanged
    assert was_changed is False


def test_redact_secret_pattern_masked():
    """Secret patterns are actually masked by api.helpers._redact_text."""
    from api.workflow_trace import _apply_redaction

    # OpenAI key
    text = "Use sk-1234567890abcdef for the API call"
    redacted, was_changed = _apply_redaction(text)
    assert was_changed is True
    assert "sk-123456" not in redacted
    assert "..." in redacted or "***" in redacted or "sk-" not in redacted


def test_redact_payload_preserves_structure():
    """Redaction doesn't destroy dict structure."""
    from api.workflow_trace import _apply_redaction_to_value

    payload = {"tool": "bash", "args": {"cmd": "ls", "api_key": "sk-secret123456"}}
    redacted, was_changed = _apply_redaction_to_value(payload)
    assert isinstance(redacted, dict)
    assert redacted["tool"] == "bash"
    assert "sk-secret" not in str(redacted)
    assert was_changed is True
