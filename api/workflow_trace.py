"""Workflow Trace Persistence — SQLite WAL schema for runs, nodes, events, artifacts."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
STATE_DIR = Path(os.getenv("HERMES_WEBUI_STATE_DIR", str(Path.home() / ".hermes" / "webui-mvp")))
TRACE_DIR = STATE_DIR / "workflow_trace"
TRACE_DB = TRACE_DIR / "trace.db"

_LOCKS_DIR = TRACE_DIR / ".locks"

_trace_lock = threading.RLock()
_connections: dict[str, sqlite3.Connection] = {}

# ---------------------------------------------------------------------------
# Schema — v2 with per-user memberships
# ---------------------------------------------------------------------------
_SCHEMA_V2 = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id          TEXT PRIMARY KEY,
    project_id      TEXT,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    created_by      TEXT NOT NULL DEFAULT 'unknown',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    ended_at        TEXT,
    error           TEXT,
    node_count      INTEGER NOT NULL DEFAULT 0,
    event_count     INTEGER NOT NULL DEFAULT 0,
    artifact_count  INTEGER NOT NULL DEFAULT 0,
    parent_run_id   TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workflow_nodes (
    node_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    parent_node_id  TEXT,
    agent_name      TEXT NOT NULL,
    name            TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TEXT,
    ended_at        TEXT,
    structured_result TEXT,
    summary         TEXT,
    artifacts       TEXT NOT NULL DEFAULT '[]',
    skill_snapshot  TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_run_id ON workflow_nodes(run_id);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON workflow_nodes(parent_node_id);

CREATE TABLE IF NOT EXISTS workflow_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    node_id         TEXT,
    event_type      TEXT NOT NULL,
    actor           TEXT,
    payload         TEXT NOT NULL DEFAULT '{}',
    redacted        INTEGER NOT NULL DEFAULT 0,
    truncated       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run_id ON workflow_events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_sequence ON workflow_events(run_id, event_id);

CREATE TABLE IF NOT EXISTS workflow_artifacts (
    artifact_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    node_id         TEXT,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL DEFAULT 'document',
    path            TEXT,
    size            INTEGER NOT NULL DEFAULT 0,
    hash_sha256     TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON workflow_artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_node ON workflow_artifacts(node_id);

-- Per-user project memberships (replaces old per-run scheme)
CREATE TABLE IF NOT EXISTS project_trace_memberships (
    project_id      TEXT NOT NULL,
    username        TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    can_read        INTEGER NOT NULL DEFAULT 1,
    can_write       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (project_id, username)
);

CREATE INDEX IF NOT EXISTS idx_ptm_project ON project_trace_memberships(project_id);
CREATE INDEX IF NOT EXISTS idx_ptm_username ON project_trace_memberships(username);

CREATE TABLE IF NOT EXISTS workflow_definitions (
    workflow_id          TEXT PRIMARY KEY,
    project_id           TEXT,
    name                 TEXT NOT NULL,
    description          TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'draft',
    created_by           TEXT NOT NULL DEFAULT 'unknown',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    published_version_id TEXT,
    draft_revision       INTEGER NOT NULL DEFAULT 1,
    default_profile      TEXT,
    input_schema         TEXT NOT NULL DEFAULT '[]',
    draft_steps          TEXT NOT NULL DEFAULT '[]',
    metadata             TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_wf_defs_project ON workflow_definitions(project_id);
CREATE INDEX IF NOT EXISTS idx_wf_defs_updated ON workflow_definitions(updated_at);

CREATE TABLE IF NOT EXISTS workflow_versions (
    version_id        TEXT PRIMARY KEY,
    workflow_id       TEXT NOT NULL REFERENCES workflow_definitions(workflow_id) ON DELETE CASCADE,
    version_number    INTEGER NOT NULL,
    created_by        TEXT NOT NULL DEFAULT 'unknown',
    created_at        TEXT NOT NULL,
    source_revision   INTEGER NOT NULL DEFAULT 1,
    input_schema      TEXT NOT NULL DEFAULT '[]',
    steps             TEXT NOT NULL DEFAULT '[]',
    metadata          TEXT NOT NULL DEFAULT '{}',
    UNIQUE(workflow_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_wf_versions_workflow ON workflow_versions(workflow_id, version_number DESC);

CREATE TABLE IF NOT EXISTS workflow_edit_locks (
    workflow_id       TEXT PRIMARY KEY REFERENCES workflow_definitions(workflow_id) ON DELETE CASCADE,
    locked_by         TEXT NOT NULL,
    lock_expires_at   TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Helpers from api.helpers (real secret redaction)
# ---------------------------------------------------------------------------
def _apply_redaction(text: str) -> tuple[str, bool]:
    """Apply real secret redaction to text. Returns (redacted, was_changed)."""
    try:
        from api import helpers as h
        redacted = h._redact_text(text)
        return redacted, redacted != text
    except Exception:
        return text, False


def _apply_redaction_to_value(value) -> tuple:
    """Apply secret redaction to a value (dict, list, or string)."""
    try:
        from api import helpers as h
        redacted = h._redact_value(value)
        was_changed = redacted != value
        return redacted, was_changed
    except Exception:
        return value, False


# ---------------------------------------------------------------------------
# Size caps (applied after redaction)
# ---------------------------------------------------------------------------
_MAX_PAYLOAD_CHARS = 200_000
_MAX_TEXT_FIELD_CHARS = 80_000
_MAX_ARTIFACT_META_CHARS = 5_000


def _truncate_text(text: str, limit: int) -> tuple[str, bool]:
    """Truncate text to limit chars. Returns (result, was_truncated)."""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _redact_and_truncate_payload(payload: dict) -> tuple[str, bool, bool]:
    """Redact secrets then truncate. Returns (stored_str, was_redacted, was_truncated)."""
    redacted, was_redacted = _apply_redaction_to_value(payload)
    if isinstance(redacted, dict):
        stored_str = json.dumps(redacted, ensure_ascii=False)
    elif isinstance(redacted, str):
        stored_str = redacted
    else:
        stored_str = json.dumps(redacted, ensure_ascii=False)
    stored_str, was_truncated = _truncate_text(stored_str, _MAX_PAYLOAD_CHARS)
    return stored_str, was_redacted, was_truncated


def _redact_text_field(text: str) -> tuple[str, bool, bool]:
    """Redact and truncate a text field. Returns (stored, was_redacted, was_truncated)."""
    redacted, was_redacted = _apply_redaction(text)
    redacted, was_truncated = _truncate_text(redacted, _MAX_TEXT_FIELD_CHARS)
    return redacted, was_redacted, was_truncated


def _redact_artifact_metadata(meta: dict) -> tuple[dict, bool, bool]:
    """Redact artifact metadata. Returns (redacted, was_redacted, was_truncated)."""
    result = dict(meta) if isinstance(meta, dict) else {}
    any_redacted = False
    for key in ("description", "name", "content_type", "author", "tags"):
        if key in result and isinstance(result[key], str):
            result[key], was_r, _ = _redact_text_field(result[key])
            if was_r:
                any_redacted = True
    return result, any_redacted, False


def hash_artifact_content(content: str) -> str:
    """Return SHA-256 hex digest of artifact content (on stored/redacted bytes)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Connection management + migration
# ---------------------------------------------------------------------------
def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local DB connection with migration support."""
    tid = threading.current_thread().ident
    if tid not in _connections:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        _LOCKS_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(TRACE_DB), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Detect and migrate old per-run memberships schema
        _migrate_if_needed(conn)

        # Initialize v2 schema
        for stmt in _SCHEMA_V2.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        _connections[tid] = conn
        return conn

    conn = _connections[tid]
    # Re-run migration/schema guards on reused thread-local connections so tests
    # that mutate schema out-of-band still converge to the current model.
    _migrate_if_needed(conn)
    for stmt in _SCHEMA_V2.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()
    return conn


def _migrate_if_needed(conn: sqlite3.Connection) -> None:
    """Migrate old (project_id, run_id) memberships to new (project_id, username) scheme."""
    try:
        # Force schema cache refresh (SQLite caches schema per-connection)
        conn.execute("SELECT 1").fetchone()
        # Check if old table exists with run_id column
        rows = conn.execute(
            "PRAGMA table_info(project_trace_memberships)"
        ).fetchall()
        col_names = {r["name"] for r in rows}
        if "run_id" not in col_names:
            return  # Already migrated or fresh install
    except sqlite3.OperationalError:
        return  # Table doesn't exist yet

    logger.info("Migrating project_trace_memberships from per-run to per-user schema")

    try:
        # Read all existing memberships
        old_rows = conn.execute(
            "SELECT project_id, run_id, can_read, can_write FROM project_trace_memberships"
        ).fetchall()

        # Read all runs to get created_by for owner backfill
        runs = {}
        for row in conn.execute("SELECT run_id, project_id, created_by FROM workflow_runs").fetchall():
            runs[row["run_id"]] = dict(row)

        # Build new per-user memberships
        now = datetime.now(timezone.utc).isoformat()
        seen = {}  # (project_id, username) -> membership data

        for old in old_rows:
            pid = old["project_id"]
            rid = old["run_id"]
            can_read = bool(old["can_read"])
            can_write = bool(old["can_write"])

            # Owner: created_by of the run
            run = runs.get(rid, {})
            creator = run.get("created_by", "unknown")
            key = (pid, creator)
            if key not in seen:
                seen[key] = {
                    "project_id": pid,
                    "username": creator,
                    "role": "owner",
                    "can_read": 1,
                    "can_write": 1,
                    "created_at": now,
                }

            # Members: any additional membership
            # The old schema had one entry per (project, run) - we keep can_read/can_write
            # as the maximum permission found
            existing = seen.get(key, {})
            if can_write:
                existing["can_write"] = 1
                existing["role"] = "owner"

        # Create new table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_trace_memberships_new (
                project_id      TEXT NOT NULL,
                username        TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'member',
                can_read        INTEGER NOT NULL DEFAULT 1,
                can_write       INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                PRIMARY KEY (project_id, username)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ptm_project_new ON project_trace_memberships_new(project_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ptm_username_new ON project_trace_memberships_new(username)")

        # Populate new table
        for m in seen.values():
            conn.execute("""
                INSERT OR IGNORE INTO project_trace_memberships_new
                    (project_id, username, role, can_read, can_write, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (m["project_id"], m["username"], m["role"], m["can_read"], m["can_write"], m["created_at"]))

        # Drop old table and rename
        conn.execute("DROP TABLE project_trace_memberships")
        conn.execute("ALTER TABLE project_trace_memberships_new RENAME TO project_trace_memberships")
        conn.commit()
        logger.info("Migration complete: project_trace_memberships migrated to per-user schema")
    except sqlite3.Error as e:
        logger.error("Migration failed: %s", e)
        conn.rollback()


def _with_lock(func):
    """Decorator: hold module-level lock for the duration of func."""
    def wrapper(*args, **kwargs):
        with _trace_lock:
            return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# ACL helpers
# ---------------------------------------------------------------------------

def user_can_trace_audit(user: dict | None) -> bool:
    """Return True if user has trace audit capability.

    For cookie sessions: user['trace_audit'] == 1
    For API tokens: user['trace_audit'] == 1 (scope already validated by verify_api_token)
    """
    if not user:
        return False
    return bool(user.get("trace_audit") == 1)


def can_read_run(run_id: str, user: dict | None) -> bool:
    """Return True if user can read the run.

    Rules:
    - None user: False
    - admin role: True
    - user_can_trace_audit(user): True (cross-project auditor)
    - project_id=NULL: only creator (created_by == username)
    - Otherwise: check project_trace_memberships for (project_id, username) can_read=1
    """
    if not user:
        return False

    username = str(user.get("username") or "").strip()

    # Admin always has access
    if str(user.get("role")) == "admin":
        return True

    # Trace auditors have cross-project read access
    if user_can_trace_audit(user):
        return True

    # Check the run
    run = get_run(run_id)
    if not run:
        return False

    project_id = run.get("project_id")
    if not project_id:
        # No project = private to creator
        return run.get("created_by") == username

    # Check project membership
    return _check_project_membership(project_id, username, require_read=True)


def can_write_run(run_id: str, user: dict | None) -> bool:
    """Return True if user can mutate the run (cancel, append events, approve).

    Rules:
    - None user: False
    - admin role: True
    - user_can_trace_audit(user): True
    - project_id=NULL: only creator
    - Otherwise: check project_trace_memberships can_write=1
    """
    if not user:
        return False

    username = str(user.get("username") or "").strip()

    if str(user.get("role")) == "admin":
        return True

    if user_can_trace_audit(user):
        return True

    run = get_run(run_id)
    if not run:
        return False

    project_id = run.get("project_id")
    if not project_id:
        return run.get("created_by") == username

    return _check_project_membership(project_id, username, require_write=True)


@_with_lock
def _check_project_membership(project_id: str, username: str, require_read: bool = False,
                               require_write: bool = False) -> bool:
    """Check membership in project. Must be called under lock."""
    if not project_id or not username:
        return False
    conn = _get_conn()
    if require_write:
        row = conn.execute(
            "SELECT 1 FROM project_trace_memberships WHERE project_id = ? AND username = ? AND can_write = 1",
            (project_id, username)
        ).fetchone()
    elif require_read:
        row = conn.execute(
            "SELECT 1 FROM project_trace_memberships WHERE project_id = ? AND username = ? AND can_read = 1",
            (project_id, username)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM project_trace_memberships WHERE project_id = ? AND username = ?",
            (project_id, username)
        ).fetchone()
    return row is not None


@_with_lock
def get_user_role_in_project(project_id: str, username: str) -> str | None:
    """Return user's role in project ('owner', 'writer', 'member', 'reader') or None."""
    if not project_id or not username:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT role FROM project_trace_memberships WHERE project_id = ? AND username = ?",
        (project_id, username)
    ).fetchone()
    return str(row["role"]) if row else None


# ---------------------------------------------------------------------------
# Membership CRUD
# ---------------------------------------------------------------------------

def seed_project_owner_membership(project_id: str, username: str) -> None:
    """Seed the first owner membership for a project."""
    if not project_id or not username:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO project_trace_memberships
            (project_id, username, role, can_read, can_write, created_at)
        VALUES (?, ?, 'owner', 1, 1, ?)
    """, (project_id, username, now))
    conn.commit()


def upsert_project_membership(project_id: str, username: str, role: str = "member",
                               can_read: bool = True, can_write: bool = False) -> None:
    """Insert or update a user's membership in a project."""
    if not project_id or not username:
        return
    if role not in ("owner", "writer", "member", "reader"):
        role = "member"
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute("""
        INSERT INTO project_trace_memberships
            (project_id, username, role, can_read, can_write, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, username) DO UPDATE SET
            role = excluded.role,
            can_read = excluded.can_read,
            can_write = excluded.can_write
    """, (project_id, username, role, 1 if can_read else 0, 1 if can_write else 0, now))
    conn.commit()


@_with_lock
def remove_project_membership(project_id: str, username: str) -> bool:
    """Remove a user's membership. Returns True if removed."""
    if not project_id or not username:
        return False
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM project_trace_memberships WHERE project_id = ? AND username = ?",
        (project_id, username)
    )
    conn.commit()
    return cur.rowcount > 0


@_with_lock
def list_project_members(project_id: str) -> list[dict]:
    """Return all members of a project."""
    if not project_id:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM project_trace_memberships WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Run CRUD
# ---------------------------------------------------------------------------
@_with_lock
def create_run(name: str, project_id: str | None = None, created_by: str = "unknown",
               parent_run_id: str = None, metadata: dict = None) -> dict:
    """Create a new workflow run.

    If project_id is set and no trace memberships exist for that project,
    the creator is seeded as owner.
    """
    conn = _get_conn()
    run_id = uuid.uuid4().hex[:24]
    now = datetime.now(timezone.utc).isoformat()

    meta_json = json.dumps(metadata or {}, ensure_ascii=False)

    conn.execute(
        """
        INSERT INTO workflow_runs
            (run_id, project_id, name, status, created_by, created_at, updated_at, parent_run_id, metadata)
        VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
        """,
        (run_id, project_id, name, created_by, now, now, parent_run_id, meta_json)
    )

    # Seed owner if this is the first run for this project
    if project_id:
        existing = conn.execute(
            "SELECT 1 FROM project_trace_memberships WHERE project_id = ? LIMIT 1",
            (project_id,)
        ).fetchone()
        if not existing:
            conn.execute("""
                INSERT OR IGNORE INTO project_trace_memberships
                    (project_id, username, role, can_read, can_write, created_at)
                VALUES (?, ?, 'owner', 1, 1, ?)
            """, (project_id, created_by, now))

    conn.commit()
    return _run_row(conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone())


@_with_lock
def get_run(run_id: str) -> Optional[dict]:
    """Get a run by ID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
    return _run_row(row) if row else None


@_with_lock
def list_runs(project_id: str | None = None, status: str = None,
             limit: int = 100, offset: int = 0, user: dict | None = None) -> list[dict]:
    """List runs, optionally filtered by project_id and status.

    If user is provided, results are filtered to only runs visible to that user.
    """
    conn = _get_conn()
    base_query = "SELECT * FROM workflow_runs"
    params = []
    conditions = []

    if project_id is not None:
        conditions.append("project_id = ?")
        params.append(project_id)
    if status:
        conditions.append("status = ?")
        params.append(status)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    rows = conn.execute(
        base_query + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset)
    ).fetchall()

    all_runs = [_run_row(r) for r in rows]

    if user is None:
        return all_runs

    # Filter to visible runs for this user
    visible = []
    for run in all_runs:
        if can_read_run(run["run_id"], user):
            visible.append(run)
    return visible


@_with_lock
def update_run(run_id: str, **kwargs) -> Optional[dict]:
    """Update run fields (status, ended_at, error, etc.)."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        return None

    allowed = {"status", "ended_at", "error", "metadata", "node_count", "event_count", "artifact_count"}
    setters = []
    values = []
    for key, val in kwargs.items():
        if key in allowed:
            setters.append(f"{key} = ?")
            if key == "metadata":
                values.append(json.dumps(val, ensure_ascii=False) if isinstance(val, dict) else val)
            else:
                values.append(val)
    if not setters:
        return _run_row(row)

    setters.append("updated_at = ?")
    values.append(datetime.now(timezone.utc).isoformat())
    values.append(run_id)

    conn.execute(f"UPDATE workflow_runs SET {', '.join(setters)} WHERE run_id = ?", values)
    conn.commit()

    updated = conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
    return _run_row(updated) if updated else None


@_with_lock
def cancel_run(run_id: str) -> Optional[dict]:
    """Cancel a running workflow."""
    return update_run(run_id, status="cancelled", ended_at=datetime.now(timezone.utc).isoformat())


@_with_lock
def delete_run(run_id: str) -> bool:
    """Delete a run and all its nodes, events, artifacts."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM workflow_runs WHERE run_id = ?", (run_id,))
    conn.commit()
    return cur.rowcount > 0


def _run_row(row: sqlite3.Row | None) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    for field in ("metadata",):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = {}
    return d


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------
@_with_lock
def create_node(run_id: str, agent_name: str, parent_node_id: str = None,
                name: str = None, skill_snapshot: dict = None) -> Optional[dict]:
    """Create a new node within a run."""
    conn = _get_conn()
    run = get_run(run_id)
    if not run:
        return None

    node_id = uuid.uuid4().hex[:24]
    now = datetime.now(timezone.utc).isoformat()

    # Redact skill_snapshot before storing
    skill_json = None
    if skill_snapshot:
        redacted, _ = _apply_redaction_to_value(skill_snapshot)
        skill_json = json.dumps(redacted, ensure_ascii=False)

    conn.execute(
        """
        INSERT INTO workflow_nodes
            (node_id, run_id, parent_node_id, agent_name, name, status, started_at, skill_snapshot, created_at)
        VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)
        """,
        (node_id, run_id, parent_node_id, agent_name, name, now, skill_json, now)
    )
    conn.execute(
        "UPDATE workflow_runs SET node_count = node_count + 1, updated_at = ? WHERE run_id = ?",
        (now, run_id)
    )
    conn.commit()
    return _node_row(conn.execute("SELECT * FROM workflow_nodes WHERE node_id = ?", (node_id,)).fetchone())


@_with_lock
def get_node(node_id: str) -> Optional[dict]:
    row = _get_conn().execute("SELECT * FROM workflow_nodes WHERE node_id = ?", (node_id,)).fetchone()
    return _node_row(row) if row else None


@_with_lock
def list_run_nodes(run_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM workflow_nodes WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,)
    ).fetchall()
    return [_node_row(r) for r in rows]


@_with_lock
def update_node(node_id: str, **kwargs) -> Optional[dict]:
    """Update node fields. Applies redaction + truncation to text fields."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM workflow_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if not row:
        return None

    allowed = {
        "status", "ended_at", "structured_result", "summary", "artifacts", "error"
    }
    setters = []
    values = []
    for key, val in kwargs.items():
        if key in allowed:
            if key == "structured_result" and val is not None:
                stored, _ = _apply_redaction_to_value(val)
                setters.append(f"{key} = ?")
                values.append(json.dumps(stored, ensure_ascii=False) if isinstance(stored, dict) else stored)
            elif key in ("summary", "error") and val is not None:
                stored, _, was_trunc = _redact_text_field(str(val))
                setters.append(f"{key} = ?")
                values.append(stored)
            else:
                setters.append(f"{key} = ?")
                values.append(val)
    if not setters:
        return _node_row(row)

    values.append(node_id)
    conn.execute(f"UPDATE workflow_nodes SET {', '.join(setters)} WHERE node_id = ?", values)
    conn.commit()

    updated = conn.execute("SELECT * FROM workflow_nodes WHERE node_id = ?", (node_id,)).fetchone()
    return _node_row(updated) if updated else None


def _node_row(row: sqlite3.Row | None) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    for field in ("structured_result", "artifacts", "skill_snapshot"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = None if field != "artifacts" else []
    return d


# ---------------------------------------------------------------------------
# Event append (append-only)
# ---------------------------------------------------------------------------
@_with_lock
def append_event(run_id: str, event_type: str, actor: str = None,
                 node_id: str = None, payload: dict = None) -> dict:
    """Append an append-only event to a run.

    Secrets are redacted and content is truncated before storage.
    """
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()

    # Redact + truncate payload
    stored_str, was_redacted, was_truncated = _redact_and_truncate_payload(payload or {})

    cursor = conn.execute(
        """
        INSERT INTO workflow_events (run_id, node_id, event_type, actor, payload, redacted, truncated, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, node_id, event_type, actor, stored_str, 1 if was_redacted else 0, 1 if was_truncated else 0, now)
    )
    conn.execute(
        "UPDATE workflow_runs SET event_count = event_count + 1, updated_at = ? WHERE run_id = ?",
        (now, run_id)
    )
    conn.commit()

    event_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM workflow_events WHERE event_id = ?", (event_id,)).fetchone()
    return _event_row(row) if row else None


@_with_lock
def list_run_events(run_id: str, node_id: str = None) -> list[dict]:
    """List events for a run, optionally filtered by node_id."""
    conn = _get_conn()
    if node_id:
        rows = conn.execute(
            "SELECT * FROM workflow_events WHERE run_id = ? AND node_id = ? ORDER BY event_id ASC",
            (run_id, node_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM workflow_events WHERE run_id = ? ORDER BY event_id ASC",
            (run_id,)
        ).fetchall()
    return [_event_row(r) for r in rows]


def _event_row(row: sqlite3.Row | None) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    if "payload" in d and isinstance(d["payload"], str):
        try:
            d["payload"] = json.loads(d["payload"])
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
    d["redacted"] = bool(d.get("redacted"))
    d["truncated"] = bool(d.get("truncated"))
    return d


# ---------------------------------------------------------------------------
# Artifact CRUD
# ---------------------------------------------------------------------------
@_with_lock
def create_artifact(run_id: str, node_id: str = None, name: str = "",
                    artifact_type: str = "document", content: str = "",
                    path: str = None, metadata: dict = None) -> Optional[dict]:
    """Create an artifact.

    Content is stored on disk, then redacted SHA-256 hash is computed.
    Metadata fields are redacted.
    """
    conn = _get_conn()
    run = get_run(run_id)
    if not run:
        return None

    artifact_id = uuid.uuid4().hex[:24]
    now = datetime.now(timezone.utc).isoformat()

    # Store content to disk
    artifact_dir = TRACE_DIR / "artifacts" / artifact_id
    stored_path = None
    size = 0
    sha256 = None

    if content:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        file_path = artifact_dir / name
        # Redact before storing, then hash stored bytes
        redacted_content, was_redacted = _apply_redaction(content)
        file_path.write_text(redacted_content, encoding="utf-8")
        stored_path = str(file_path)
        size = len(redacted_content)
        sha256 = hash_artifact_content(redacted_content)
    elif path:
        stored_path = path
        try:
            size = Path(path).stat().st_size
        except OSError:
            pass

    # Redact metadata
    redacted_meta, _, _ = _redact_artifact_metadata(metadata or {})
    meta_json = json.dumps(redacted_meta, ensure_ascii=False)

    conn.execute(
        """
        INSERT INTO workflow_artifacts
            (artifact_id, run_id, node_id, name, type, path, size, hash_sha256, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, run_id, node_id, name, artifact_type, stored_path, size, sha256, meta_json, now)
    )
    conn.execute(
        "UPDATE workflow_runs SET artifact_count = artifact_count + 1, updated_at = ? WHERE run_id = ?",
        (now, run_id)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM workflow_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
    return _artifact_row(row) if row else None


@_with_lock
def get_artifact(artifact_id: str) -> Optional[dict]:
    row = _get_conn().execute("SELECT * FROM workflow_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
    return _artifact_row(row) if row else None


@_with_lock
def get_artifact_content(artifact_id: str) -> Optional[str]:
    """Read artifact content from disk. Returns None if not found."""
    artifact = get_artifact(artifact_id)
    if not artifact:
        return None
    if artifact.get("path"):
        p = Path(artifact["path"])
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


@_with_lock
def list_run_artifacts(run_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM workflow_artifacts WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,)
    ).fetchall()
    return [_artifact_row(r) for r in rows]


def _artifact_row(row: sqlite3.Row | None) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    if "metadata" in d and isinstance(d["metadata"], str):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
    return d


# ---------------------------------------------------------------------------
# Full trace payload
# ---------------------------------------------------------------------------
@_with_lock
def get_trace_payload(run_id: str) -> Optional[dict]:
    """Return full trace payload: run + nodes + events + artifacts sorted by sequence."""
    run = get_run(run_id)
    if not run:
        return None

    nodes = list_run_nodes(run_id)
    events = list_run_events(run_id)
    artifacts = list_run_artifacts(run_id)

    events.sort(key=lambda e: e.get("event_id", 0))

    return {
        "run": run,
        "nodes": nodes,
        "events": events,
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# Approval helpers
# ---------------------------------------------------------------------------
@_with_lock
def append_approval_event(run_id: str, node_id: str, actor: str,
                           pattern_keys: list[str], payload: dict = None) -> Optional[dict]:
    """Append an approval event. pattern_keys is plural per RULE-9."""
    event_payload = {
        "type": "approval",
        "pattern_keys": pattern_keys,
        **(payload or {})
    }
    return append_event(run_id, "approval", actor=actor, node_id=node_id, payload=event_payload)


@_with_lock
def append_skill_snapshot_event(run_id: str, node_id: str, actor: str,
                                  skill_name: str, snapshot: dict) -> Optional[dict]:
    """Append a skill invocation snapshot event (immutable)."""
    event_payload = {
        "type": "skill_snapshot",
        "skill_name": skill_name,
        "snapshot": snapshot,
    }
    return append_event(run_id, "skill_invocation", actor=actor, node_id=node_id, payload=event_payload)


# ---------------------------------------------------------------------------
# Workflow Definitions + Versions
# ---------------------------------------------------------------------------
def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _definition_row(row: sqlite3.Row | None) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    d["input_schema"] = _json_list(d.get("input_schema"))
    d["draft_steps"] = _json_list(d.get("draft_steps"))
    d["metadata"] = _json_dict(d.get("metadata"))
    return d


def _version_row(row: sqlite3.Row | None) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    d["input_schema"] = _json_list(d.get("input_schema"))
    d["steps"] = _json_list(d.get("steps"))
    d["metadata"] = _json_dict(d.get("metadata"))
    return d


@_with_lock
def can_read_definition(workflow_id: str, user: dict | None) -> bool:
    if not user:
        return False
    definition = get_workflow_definition(workflow_id)
    if not definition:
        return False
    username = str(user.get("username") or "").strip()
    if str(user.get("role")) == "admin":
        return True
    if user_can_trace_audit(user):
        return True
    project_id = definition.get("project_id")
    if not project_id:
        return definition.get("created_by") == username
    return _check_project_membership(project_id, username, require_read=True)


@_with_lock
def can_write_definition(workflow_id: str, user: dict | None) -> bool:
    if not user:
        return False
    definition = get_workflow_definition(workflow_id)
    if not definition:
        return False
    username = str(user.get("username") or "").strip()
    if str(user.get("role")) == "admin":
        return True
    if user_can_trace_audit(user):
        return True
    project_id = definition.get("project_id")
    if not project_id:
        return definition.get("created_by") == username
    return _check_project_membership(project_id, username, require_write=True)


@_with_lock
def create_workflow_definition(
    name: str,
    created_by: str = "unknown",
    project_id: str | None = None,
    description: str = "",
    input_schema: list | None = None,
    draft_steps: list | None = None,
    default_profile: str | None = None,
    metadata: dict | None = None,
) -> dict:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    workflow_id = uuid.uuid4().hex[:24]
    conn.execute(
        """
        INSERT INTO workflow_definitions
            (workflow_id, project_id, name, description, status, created_by, created_at, updated_at,
             draft_revision, default_profile, input_schema, draft_steps, metadata)
        VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            workflow_id,
            project_id,
            name,
            description or "",
            created_by,
            now,
            now,
            default_profile,
            json.dumps(input_schema or [], ensure_ascii=False),
            json.dumps(draft_steps or [], ensure_ascii=False),
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    if project_id:
        existing = conn.execute(
            "SELECT 1 FROM project_trace_memberships WHERE project_id = ? LIMIT 1",
            (project_id,),
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT OR IGNORE INTO project_trace_memberships
                    (project_id, username, role, can_read, can_write, created_at)
                VALUES (?, ?, 'owner', 1, 1, ?)
                """,
                (project_id, created_by, now),
            )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM workflow_definitions WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchone()
    return _definition_row(row) or {}


@_with_lock
def get_workflow_definition(workflow_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT * FROM workflow_definitions WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchone()
    return _definition_row(row)


@_with_lock
def list_workflow_definitions(
    project_id: str | None = None,
    user: dict | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    conn = _get_conn()
    q = "SELECT * FROM workflow_definitions"
    params: list[Any] = []
    if project_id:
        q += " WHERE project_id = ?"
        params.append(project_id)
    q += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(q, tuple(params)).fetchall()
    all_defs = [_definition_row(r) for r in rows]
    visible: list[dict] = []
    for d in all_defs:
        if not d:
            continue
        if user is None:
            visible.append(d)
            continue
        if can_read_definition(d["workflow_id"], user):
            visible.append(d)
    return visible


@_with_lock
def update_workflow_definition(workflow_id: str, **kwargs) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM workflow_definitions WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchone()
    if not row:
        return None
    allowed = {
        "name",
        "description",
        "default_profile",
        "input_schema",
        "draft_steps",
        "metadata",
        "status",
    }
    setters = []
    values: list[Any] = []
    increment_revision = False
    for key, val in kwargs.items():
        if key not in allowed:
            continue
        if key in {"input_schema", "draft_steps"}:
            setters.append(f"{key} = ?")
            values.append(json.dumps(_json_list(val), ensure_ascii=False))
            increment_revision = True
        elif key == "metadata":
            setters.append("metadata = ?")
            values.append(json.dumps(_json_dict(val), ensure_ascii=False))
        else:
            setters.append(f"{key} = ?")
            values.append(val)
    if not setters:
        return _definition_row(row)
    if increment_revision:
        setters.append("draft_revision = draft_revision + 1")
    setters.append("updated_at = ?")
    values.append(datetime.now(timezone.utc).isoformat())
    values.append(workflow_id)
    conn.execute(
        f"UPDATE workflow_definitions SET {', '.join(setters)} WHERE workflow_id = ?",
        values,
    )
    conn.commit()
    updated = conn.execute(
        "SELECT * FROM workflow_definitions WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchone()
    return _definition_row(updated)


@_with_lock
def publish_workflow_definition(workflow_id: str, actor: str = "unknown") -> Optional[dict]:
    conn = _get_conn()
    definition = get_workflow_definition(workflow_id)
    if not definition:
        return None
    now = datetime.now(timezone.utc).isoformat()
    next_version = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_v FROM workflow_versions WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchone()["next_v"]
    version_id = uuid.uuid4().hex[:24]
    conn.execute(
        """
        INSERT INTO workflow_versions
            (version_id, workflow_id, version_number, created_by, created_at, source_revision, input_schema, steps, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            workflow_id,
            int(next_version),
            actor,
            now,
            int(definition.get("draft_revision") or 1),
            json.dumps(definition.get("input_schema") or [], ensure_ascii=False),
            json.dumps(definition.get("draft_steps") or [], ensure_ascii=False),
            json.dumps(definition.get("metadata") or {}, ensure_ascii=False),
        ),
    )
    conn.execute(
        """
        UPDATE workflow_definitions
        SET status = 'published', published_version_id = ?, updated_at = ?
        WHERE workflow_id = ?
        """,
        (version_id, now, workflow_id),
    )
    conn.commit()
    version = conn.execute(
        "SELECT * FROM workflow_versions WHERE version_id = ?",
        (version_id,),
    ).fetchone()
    return _version_row(version)


@_with_lock
def list_workflow_versions(workflow_id: str, limit: int = 50) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM workflow_versions WHERE workflow_id = ? ORDER BY version_number DESC LIMIT ?",
        (workflow_id, limit),
    ).fetchall()
    return [_version_row(r) for r in rows if r]


@_with_lock
def list_definition_runs(workflow_id: str, user: dict | None = None, limit: int = 100) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT ?",
        (limit * 5,),
    ).fetchall()
    result: list[dict] = []
    for row in rows:
        run = _run_row(row)
        if not run:
            continue
        meta = run.get("metadata") or {}
        if str(meta.get("workflow_id") or "") != workflow_id:
            continue
        if user and not can_read_run(run["run_id"], user):
            continue
        result.append(run)
        if len(result) >= limit:
            break
    return result


@_with_lock
def acquire_workflow_edit_lock(
    workflow_id: str,
    username: str,
    ttl_seconds: int = 300,
) -> dict:
    conn = _get_conn()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    expires = (now_dt + timedelta(seconds=max(30, int(ttl_seconds)))).isoformat()
    row = conn.execute(
        "SELECT * FROM workflow_edit_locks WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchone()
    if row:
        current = dict(row)
        holder = str(current.get("locked_by") or "")
        lock_expires = str(current.get("lock_expires_at") or "")
        if lock_expires > now and holder and holder != username:
            return {"ok": False, "locked_by": holder, "lock_expires_at": lock_expires}
    conn.execute(
        """
        INSERT INTO workflow_edit_locks (workflow_id, locked_by, lock_expires_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(workflow_id) DO UPDATE SET
            locked_by = excluded.locked_by,
            lock_expires_at = excluded.lock_expires_at,
            updated_at = excluded.updated_at
        """,
        (workflow_id, username, expires, now),
    )
    conn.commit()
    return {"ok": True, "locked_by": username, "lock_expires_at": expires}


@_with_lock
def release_workflow_edit_lock(workflow_id: str, username: str) -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM workflow_edit_locks WHERE workflow_id = ? AND locked_by = ?",
        (workflow_id, username),
    )
    conn.commit()
    return cur.rowcount > 0


def _read_path(data: Any, path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
            continue
        if isinstance(cur, list):
            try:
                idx = int(part)
            except (TypeError, ValueError):
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
            continue
        return None
    return cur


def _resolve_bindings(value: Any, context: dict) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_bindings(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_bindings(v, context) for v in value]
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"{{\s*([^{}]+?)\s*}}")
    full = pattern.fullmatch(value)
    if full:
        resolved = _read_path(context, full.group(1))
        return resolved
    def repl(match):
        resolved = _read_path(context, match.group(1))
        if resolved is None:
            return ""
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, ensure_ascii=False)
        return str(resolved)
    return pattern.sub(repl, value)


def _step_name(step: dict, index: int) -> str:
    raw = str(step.get("name") or "").strip()
    if raw:
        return raw
    return f"Step {index + 1}"


def _step_key(step: dict, index: int) -> str:
    raw = str(step.get("step_id") or "").strip()
    if raw:
        return raw
    return f"step_{index + 1}"


def _merge_run_metadata(run: dict, patch: dict) -> dict:
    meta = dict(run.get("metadata") or {})
    meta.update(patch)
    return meta


def _extract_approval_decision(inputs: dict, step_key: str) -> dict | None:
    approvals = inputs.get("_approvals")
    if not isinstance(approvals, dict):
        return None
    decision = approvals.get(step_key)
    if isinstance(decision, bool):
        return {"approved": bool(decision), "message": ""}
    if isinstance(decision, dict):
        approved = bool(decision.get("approved"))
        message = str(decision.get("message") or decision.get("comment") or "")
        return {"approved": approved, "message": message}
    return None


def _run_step(
    run: dict,
    step: dict,
    index: int,
    actor: str,
    context: dict,
    is_test_run: bool,
) -> dict:
    run_id = run["run_id"]
    step_type = str(step.get("type") or "").strip().lower()
    step_key = _step_key(step, index)
    step_label = _step_name(step, index)
    agent_name = f"workflow:{step_type or 'step'}"
    node = create_node(run_id, agent_name=agent_name, name=step_label)
    if not node:
        raise RuntimeError(f"Failed to create node for {step_label}")
    node_id = node["node_id"]

    append_event(
        run_id,
        "node_start",
        actor=actor,
        node_id=node_id,
        payload={
            "step_id": step_key,
            "step_type": step_type,
            "step_name": step_label,
        },
    )

    if step_type == "agent_instruction":
        prompt = _resolve_bindings(step.get("prompt") or step.get("instruction") or "", context)
        payload = {
            "step_id": step_key,
            "prompt": prompt,
            "is_test_run": bool(is_test_run),
        }
        append_event(run_id, "token", actor=actor, node_id=node_id, payload=payload)
        result = {"message": prompt, "simulated": True}
        summary = str(step.get("summary") or "Agent instruction recorded")
        update_node(
            node_id,
            status="completed",
            ended_at=datetime.now(timezone.utc).isoformat(),
            structured_result=result,
            summary=summary,
        )
        append_event(run_id, "done", actor=actor, node_id=node_id, payload={"summary": summary})
        return {"state": "completed", "step_key": step_key, "output": result, "summary": summary, "artifacts": []}

    if step_type == "skill_call":
        skill_name = str(step.get("skill_name") or "").strip()
        args = _resolve_bindings(step.get("args") or {}, context)
        if not skill_name:
            raise ValueError(f"{step_label}: skill_name is required")
        append_skill_snapshot_event(
            run_id,
            node_id=node_id,
            actor=actor,
            skill_name=skill_name,
            snapshot={"args": args},
        )
        result = {
            "skill_name": skill_name,
            "arguments": args,
            "result": step.get("mock_result") if "mock_result" in step else {"ok": True},
            "simulated": True,
        }
        artifacts: list[str] = []
        emit_name = str(step.get("artifact_name") or "").strip()
        if emit_name:
            content = json.dumps(result, ensure_ascii=False, indent=2)
            art = create_artifact(
                run_id,
                node_id=node_id,
                name=emit_name,
                artifact_type="data",
                content=content,
                metadata={"step_id": step_key, "skill_name": skill_name},
            )
            if art:
                artifacts.append(art["artifact_id"])
        update_node(
            node_id,
            status="completed",
            ended_at=datetime.now(timezone.utc).isoformat(),
            structured_result=result,
            summary=f"Skill {skill_name} executed",
            artifacts=json.dumps(artifacts, ensure_ascii=False),
        )
        append_event(
            run_id,
            "done",
            actor=actor,
            node_id=node_id,
            payload={"summary": f"Skill {skill_name} executed"},
        )
        return {"state": "completed", "step_key": step_key, "output": result, "summary": f"Skill {skill_name} executed", "artifacts": artifacts}

    if step_type == "approval":
        decision = _extract_approval_decision(context.get("inputs", {}), step_key)
        pattern_keys = [step_key]
        if not decision:
            append_event(
                run_id,
                "approval_request",
                actor=actor,
                node_id=node_id,
                payload={"pattern_keys": pattern_keys, "status": "pending"},
            )
            update_node(
                node_id,
                status="pending",
                summary=f"Awaiting approval for {step_label}",
            )
            return {"state": "pending_approval", "step_key": step_key, "node_id": node_id}
        approved = bool(decision.get("approved"))
        message = str(decision.get("message") or "")
        append_approval_event(
            run_id=run_id,
            node_id=node_id,
            actor=actor,
            pattern_keys=pattern_keys,
            payload={
                "status": "approved" if approved else "denied",
                "approved": approved,
                "message": message,
            },
        )
        if not approved:
            update_node(
                node_id,
                status="failed",
                ended_at=datetime.now(timezone.utc).isoformat(),
                summary=message or "Approval denied",
                error=message or "Approval denied",
            )
            return {"state": "denied", "step_key": step_key, "error": message or "Approval denied"}
        update_node(
            node_id,
            status="completed",
            ended_at=datetime.now(timezone.utc).isoformat(),
            summary=message or "Approval granted",
            structured_result={"approved": True, "message": message},
        )
        return {"state": "completed", "step_key": step_key, "output": {"approved": True, "message": message}, "summary": "Approval granted", "artifacts": []}

    if step_type == "output":
        rendered = _resolve_bindings(step.get("value"), context)
        if rendered is None:
            rendered = _resolve_bindings(step.get("template") or "", context)
        artifact_ids: list[str] = []
        artifact_name = str(step.get("artifact_name") or "").strip()
        if artifact_name:
            content = rendered if isinstance(rendered, str) else json.dumps(rendered, ensure_ascii=False, indent=2)
            art = create_artifact(
                run_id,
                node_id=node_id,
                name=artifact_name,
                artifact_type=step.get("artifact_type") or "document",
                content=content,
                metadata={"step_id": step_key},
            )
            if art:
                artifact_ids.append(art["artifact_id"])
        summary = str(step.get("summary") or "Output generated")
        update_node(
            node_id,
            status="completed",
            ended_at=datetime.now(timezone.utc).isoformat(),
            structured_result={"value": rendered},
            summary=summary,
            artifacts=json.dumps(artifact_ids, ensure_ascii=False),
        )
        append_event(run_id, "done", actor=actor, node_id=node_id, payload={"summary": summary})
        return {"state": "completed", "step_key": step_key, "output": {"value": rendered}, "summary": summary, "artifacts": artifact_ids}

    raise ValueError(f"Unsupported step type: {step_type}")


@_with_lock
def run_workflow_definition(
    workflow_id: str,
    actor: str,
    user: dict | None,
    inputs: dict | None = None,
    is_test_run: bool = False,
) -> dict:
    definition = get_workflow_definition(workflow_id)
    if not definition:
        raise ValueError("Workflow definition not found")
    if user and not can_read_definition(workflow_id, user):
        raise PermissionError("Access denied")

    if is_test_run:
        selected_steps = definition.get("draft_steps") or []
        selected_schema = definition.get("input_schema") or []
        version_id = None
        version_number = None
    else:
        published_id = definition.get("published_version_id")
        if not published_id:
            raise ValueError("Workflow has no published version")
        version_row = _get_conn().execute(
            "SELECT * FROM workflow_versions WHERE version_id = ?",
            (published_id,),
        ).fetchone()
        version = _version_row(version_row)
        if not version:
            raise ValueError("Published workflow version not found")
        selected_steps = version.get("steps") or []
        selected_schema = version.get("input_schema") or []
        version_id = version.get("version_id")
        version_number = version.get("version_number")

    run_metadata = {
        "workflow_id": workflow_id,
        "workflow_name": definition.get("name"),
        "workflow_version_id": version_id,
        "workflow_version_number": version_number,
        "is_test_run": bool(is_test_run),
        "input_schema": selected_schema,
        "input_values": inputs or {},
    }
    run_name = f"{definition.get('name')} ({'test' if is_test_run else 'run'})"
    run = create_run(
        name=run_name,
        project_id=definition.get("project_id"),
        created_by=actor,
        metadata=run_metadata,
    )

    context = {"inputs": inputs or {}, "steps": {}}
    try:
        for idx, raw_step in enumerate(selected_steps):
            step = raw_step if isinstance(raw_step, dict) else {}
            result = _run_step(run, step, idx, actor, context, is_test_run)
            step_key = result.get("step_key") or _step_key(step, idx)
            if result.get("state") == "completed":
                context["steps"][step_key] = {
                    "output": result.get("output"),
                    "summary": result.get("summary"),
                    "artifacts": result.get("artifacts") or [],
                }
                continue
            if result.get("state") == "pending_approval":
                patch = _merge_run_metadata(
                    get_run(run["run_id"]) or run,
                    {
                        "pending_approval": True,
                        "pending_step_id": step_key,
                        "step_outputs": context["steps"],
                    },
                )
                update_run(
                    run["run_id"],
                    status="pending_approval",
                    metadata=patch,
                )
                return get_run(run["run_id"]) or run
            if result.get("state") == "denied":
                err = str(result.get("error") or f"Approval denied at {step_key}")
                append_event(
                    run["run_id"],
                    "error",
                    actor=actor,
                    payload={"message": err, "step_id": step_key},
                )
                update_run(
                    run["run_id"],
                    status="failed",
                    ended_at=datetime.now(timezone.utc).isoformat(),
                    error=err,
                    metadata=_merge_run_metadata(
                        get_run(run["run_id"]) or run,
                        {"step_outputs": context["steps"]},
                    ),
                )
                return get_run(run["run_id"]) or run
        final_patch = _merge_run_metadata(
            get_run(run["run_id"]) or run,
            {"step_outputs": context["steps"], "pending_approval": False},
        )
        append_event(run["run_id"], "done", actor=actor, payload={"summary": "Workflow completed"})
        update_run(
            run["run_id"],
            status="completed",
            ended_at=datetime.now(timezone.utc).isoformat(),
            metadata=final_patch,
        )
        return get_run(run["run_id"]) or run
    except Exception as exc:
        msg = str(exc) or "Workflow execution failed"
        append_event(
            run["run_id"],
            "error",
            actor=actor,
            payload={"message": msg, "stack": traceback.format_exc()},
        )
        update_run(
            run["run_id"],
            status="failed",
            ended_at=datetime.now(timezone.utc).isoformat(),
            error=msg,
            metadata=_merge_run_metadata(
                get_run(run["run_id"]) or run,
                {"step_outputs": context.get("steps", {})},
            ),
        )
        return get_run(run["run_id"]) or run


# ---------------------------------------------------------------------------
# Canvas Workflow — save/load + run
# ---------------------------------------------------------------------------
@_with_lock
def save_canvas_definition(name, nodes, edges, created_by="unknown", project_id=None, metadata=None) -> dict:
    """Save canvas state (nodes + edges) as a workflow definition draft.

    Nodes are stored in draft_steps; edges in metadata._canvas_edges.
    """
    meta = dict(metadata or {})
    meta["_canvas_edges"] = edges
    return create_workflow_definition(
        name=name,
        created_by=created_by,
        project_id=project_id,
        draft_steps=nodes,
        metadata=meta,
    )


@_with_lock
def load_canvas_definition(workflow_id: str) -> Optional[dict]:
    """Load canvas state from a workflow definition."""
    defn = get_workflow_definition(workflow_id)
    if not defn:
        return None
    nodes = defn.get("draft_steps") or []
    edges = (defn.get("metadata") or {}).get("_canvas_edges") or []
    return {"workflow_id": workflow_id, "nodes": nodes, "edges": edges}


def run_canvas_workflow(workflow_id=None, actor="unknown", inputs=None,
                         inline_nodes=None, inline_edges=None, is_test_run=False) -> dict:
    """Run a canvas workflow.

    Accepts either a saved workflow_id (load from DB) or inline nodes/edges dict.
    Executes nodes sequentially and returns the run record.
    """
    if workflow_id is None and inline_nodes is not None:
        nodes = list(inline_nodes)
        edges = list(inline_edges or [])
    elif workflow_id:
        canvas = load_canvas_definition(workflow_id)
        if not canvas:
            raise ValueError("Workflow not found")
        nodes = canvas["nodes"]
        edges = canvas["edges"]
    else:
        raise ValueError("Either workflow_id or inline_nodes must be provided")

    context = {"inputs": inputs or {}, "artifacts": {}, "steps": {}}
    run_name = f"Canvas run {workflow_id or 'inline'}"
    run = create_run(name=run_name, created_by=actor, metadata={"workflow_id": workflow_id})
    try:
        for idx, node in enumerate(nodes):
            result = _run_canvas_node(run, node, idx, context)
            step_key = str(node.get("id") or f"node_{idx}")
            if result.get("state") == "completed":
                context["steps"][step_key] = {
                    "output": result.get("output", {}),
                    "summary": result.get("summary", ""),
                    "artifacts": result.get("artifacts", []),
                }
            elif result.get("state") == "error":
                update_run(run["run_id"], status="failed", error=result.get("error"))
                return get_run(run["run_id"])
        update_run(run["run_id"], status="completed")
        return get_run(run["run_id"])
    except Exception as exc:
        update_run(run["run_id"], status="failed", error=str(exc))
        return get_run(run["run_id"])


def _run_canvas_node(run, node, index, context) -> dict:
    """Execute a single canvas node. Returns {state, output, summary, artifacts}."""
    node_id = node.get("id") or f"node_{index}"
    node_type = node.get("type", "")
    config = node.get("config", {})

    if node_type == "file_input":
        path = config.get("path") or context["inputs"].get("path")
        if path:
            context["artifacts"][node_id] = {"path": path}
        summary = f"File input: {path}"
        return {"state": "completed", "output": {"path": path}, "summary": summary, "artifacts": []}

    if node_type == "agent":
        instruction = config.get("instruction", "")
        agent_name = f"canvas:agent:{node_id}"
        n = create_node(run["run_id"], agent_name=agent_name, name=node_id)
        if n:
            update_node(n["node_id"], status="completed",
                       ended_at=datetime.now(timezone.utc).isoformat(),
                       summary=instruction or f"Agent: {node_id}")
        return {"state": "completed", "output": {"instruction": instruction}, "summary": instruction or agent_name, "artifacts": []}

    if node_type == "prompt":
        template = config.get("template", "")
        summary = f"Prompt: {template[:40]}{'...' if len(template) > 40 else ''}"
        return {"state": "completed", "output": {"template": template}, "summary": summary, "artifacts": []}

    if node_type == "file_output":
        fmt = config.get("format", "txt")
        summary = f"File output ({fmt})"
        return {"state": "completed", "output": {"format": fmt}, "summary": summary, "artifacts": []}

    return {"state": "error", "error": f"Unknown node type: {node_type}", "output": None, "summary": "", "artifacts": []}
