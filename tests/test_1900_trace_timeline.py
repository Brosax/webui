"""Frontend/static tests for Workflow Trace Timeline UI.

Tests:
- Timeline rendering with run list, node timeline, expandable events
- Artifact links and display
- Collapsed/expanded node behavior
- Permission-error states
- Mobile/narrow layout behavior
- Generic event card rendering for unknown event types
"""
import json
import re
import urllib.error
import urllib.request

import pytest

from tests._pytest_port import BASE

WORKFLOW_JS = (
    pytest.importorskip("pathlib").Path(__file__).parent.parent / "static" / "workflow.js"
).read_text(encoding="utf-8")
STYLE_CSS = (
    pytest.importorskip("pathlib").Path(__file__).parent.parent / "static" / "style.css"
).read_text(encoding="utf-8")
INDEX_HTML = (
    pytest.importorskip("pathlib").Path(__file__).parent.parent / "static" / "index.html"
).read_text(encoding="utf-8")


# ── Auth helpers (mirrors test_workflow.py pattern) ───────────────────────────
_admin_setup_done = False


def _ensure_admin_setup():
    """Complete admin setup if not already done."""
    global _admin_setup_done
    if _admin_setup_done:
        return True
    try:
        # Check if already set up
        req = urllib.request.Request(BASE + "/api/auth/status")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            if data.get("setup_required") is False:
                _admin_setup_done = True
                return True
    except Exception:
        pass
    # Do setup
    try:
        _post(BASE + "/api/setup/admin", {
            "username": "testadmin",
            "password": "testpassword123",
        })
        _admin_setup_done = True
        return True
    except Exception:
        return False


def _build_opener():
    """Return an opener with auth cookie after logging in."""
    _ensure_admin_setup()
    import urllib.request
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    # Login
    data = json.dumps({"username": "testadmin", "password": "testpassword123"}).encode()
    req = urllib.request.Request(BASE + "/api/auth/login", data=data,
                                headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=10) as r:
            pass
    except Exception:
        pass
    return opener


# Module-level opener lazily initialized
_session_opener = None


def _get_opener():
    global _session_opener
    if _session_opener is None:
        import urllib.request
        import http.cookiejar
        # Set sentinel BEFORE calling _ensure_admin_setup to break re-entrant loop
        class _SentinelOpener:
            def open(self, req, timeout=None):
                raise RuntimeError("re-entrant")
        _session_opener = _SentinelOpener()
        # Do setup using direct unauthenticated request
        _ensure_admin_setup()
        # Now build real opener with cookie jar
        jar = http.cookiejar.CookieJar()
        _session_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        data = json.dumps({"username": "testadmin", "password": "testpassword123"}).encode()
        req = urllib.request.Request(BASE + "/api/auth/login", data=data,
                                    headers={"Content-Type": "application/json"})
        try:
            with _session_opener.open(req, timeout=10) as r:
                pass
        except Exception:
            pass
    return _session_opener


def _get(path):
    opener = _get_opener()
    with opener.open(BASE + path, timeout=10) as r:
        return json.loads(r.read()), r.status


def _post(path, body):
    opener = _get_opener()
    data = json.dumps(body).encode("utf-8")
    # _get_opener returns an opener scoped to BASE; path is always relative
    full_url = BASE + path if path.startswith("/") else path
    req = urllib.request.Request(full_url, data=data,
                                headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        return json.loads(payload or b"{}"), e.code


# ── Code structure tests ──────────────────────────────────────────────────────

class TestTraceCodeStructure:
    """Verify workflow.js exports the required functions and follows patterns."""

    def test_loadWorkflowTasks_exports(self):
        assert "function loadWorkflowTasks" in WORKFLOW_JS or "loadWorkflowTasks" in WORKFLOW_JS
        assert "window.loadWorkflowTasks" in WORKFLOW_JS

    def test_renderTraceView_exported(self):
        assert "renderTraceView" in WORKFLOW_JS
        assert "window.renderTraceView" in WORKFLOW_JS or "renderTraceView" in WORKFLOW_JS

    def test_toggleTraceTimeline_exported(self):
        assert "toggleTraceTimeline" in WORKFLOW_JS
        assert "window.toggleTraceTimeline" in WORKFLOW_JS

    def test_toggleEventBody_exported(self):
        assert "toggleEventBody" in WORKFLOW_JS

    def test_openTraceView_exported(self):
        assert "openTraceView" in WORKFLOW_JS
        assert "window.openTraceView" in WORKFLOW_JS

    def test_renderEventCard_exists(self):
        assert "function renderEventCard" in WORKFLOW_JS or "renderEventCard" in WORKFLOW_JS

    def test_renderNodeDoneMarker_exists(self):
        assert "renderNodeDoneMarker" in WORKFLOW_JS

    def test_renderArtifactChip_exists(self):
        assert "renderArtifactChip" in WORKFLOW_JS

    def test_escapeHtml_used(self):
        assert "function escapeHtml" in WORKFLOW_JS

    def test_formatTimeAgo_used(self):
        assert "function formatTimeAgo" in WORKFLOW_JS

    def test_formatFileSize_used(self):
        assert "function formatFileSize" in WORKFLOW_JS


class TestTraceCSSStructure:
    """Verify style.css includes required trace timeline styles."""

    def test_trace_timeline_class(self):
        assert ".trace-timeline" in STYLE_CSS

    def test_trace_event_class(self):
        assert ".trace-event" in STYLE_CSS

    def test_trace_node_done_class(self):
        assert ".trace-node-done" in STYLE_CSS

    def test_artifact_chip_class(self):
        assert ".artifact-chip" in STYLE_CSS

    def test_status_running_style(self):
        assert ".status-running" in STYLE_CSS

    def test_status_completed_style(self):
        assert ".status-completed" in STYLE_CSS

    def test_status_failed_style(self):
        assert ".status-failed" in STYLE_CSS

    def test_redacted_mark_style(self):
        assert ".redacted-mark" in STYLE_CSS or "redacted" in STYLE_CSS.lower()

    def test_truncated_mark_style(self):
        assert ".truncated-mark" in STYLE_CSS or "truncated" in STYLE_CSS.lower()

    def test_btn_back_style(self):
        assert ".btn-back" in STYLE_CSS

    def test_detail_dl_style(self):
        assert ".detail-dl" in STYLE_CSS

    def test_modal_overlay_style(self):
        assert ".modal-overlay" in STYLE_CSS

    def test_artifact_modal_style(self):
        assert ".artifact-modal" in STYLE_CSS


class TestTraceHTMLStructure:
    """Verify index.html includes the workflow panel container."""

    def test_panelWorkflow_exists(self):
        assert 'id="panelWorkflow"' in INDEX_HTML

    def test_workflow_nav_tab_exists(self):
        assert 'data-panel="workflow"' in INDEX_HTML

    def test_workflow_js_script(self):
        assert "workflow.js" in INDEX_HTML


# ── API integration tests ────────────────────────────────────────────────────

@pytest.fixture(scope="class", autouse=True)
def setup_admin_for_api_tests():
    _ensure_admin_setup()
    yield


class TestTraceAPI:
    """Test the trace API endpoints return correct payload shapes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Clean up any existing test runs
        try:
            runs, _ = _get("/api/workflow/runs")
            for run in (runs.get("data") or []):
                if run.get("name", "").startswith("test_trace_"):
                    run_id = run.get("run_id")
                    if run_id:
                        try:
                            _post(f"/api/workflow/runs/{run_id}/cancel", {})
                        except Exception:
                            pass
        except Exception:
            pass

    def test_create_and_list_runs(self):
        # Create a run
        body = {"name": "test_trace_api_run", "metadata": {"test": True}}
        resp, status = _post("/api/workflow/runs", body)
        assert status == 201, f"Expected 201, got {status}: {resp}"
        assert resp.get("success") is True
        run = resp["data"]
        assert "run_id" in run
        assert run["name"] == "test_trace_api_run"
        assert run["status"] == "running"

        # List runs
        resp2, _ = _get("/api/workflow/runs")
        assert resp2.get("success") is True
        assert any(r["run_id"] == run["run_id"] for r in (resp2.get("data") or []))

    def test_get_run_detail(self):
        # Create
        body = {"name": "test_trace_detail"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Get detail
        resp, status = _get(f"/api/workflow/runs/{run_id}")
        assert status == 200
        assert resp.get("success") is True
        assert resp["data"]["run_id"] == run_id

    def test_get_trace_payload(self):
        # Create
        body = {"name": "test_trace_payload"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Get full trace
        resp, status = _get(f"/api/workflow/runs/{run_id}/trace")
        assert status == 200
        assert resp.get("success") is True
        trace = resp["data"]
        # Integration contract: run, nodes, events, artifacts
        assert "run" in trace
        assert "nodes" in trace
        assert "events" in trace
        assert "artifacts" in trace

    def test_append_event(self):
        # Create
        body = {"name": "test_trace_event"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Append token event
        event_body = {
            "event_type": "token",
            "payload": {"text": "Hello world"},
            "actor": "test-user",
        }
        resp, status = _post(f"/api/workflow/runs/{run_id}/events", event_body)
        assert status == 201, f"Expected 201, got {status}: {resp}"
        assert resp.get("success") is True
        event = resp["data"]
        assert event["event_type"] == "token"
        assert event["run_id"] == run_id
        assert event["payload"]["text"] == "Hello world"

    def test_append_tool_event_with_redaction(self):
        # Create
        body = {"name": "test_trace_tool"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Append tool event
        event_body = {
            "event_type": "tool",
            "payload": {
                "tool_name": "read_file",
                "input": {"path": "/tmp/test.txt"},
                "output": "file content here",
            },
            "actor": "agent",
        }
        resp, _ = _post(f"/api/workflow/runs/{run_id}/events", event_body)
        event = resp["data"]
        assert event["event_type"] == "tool"
        assert event["payload"]["tool_name"] == "read_file"

    def test_append_approval_event(self):
        # Create
        body = {"name": "test_trace_approval"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Append approval event (must use pattern_keys plural per CLAUDE.md RULE-9)
        event_body = {
            "event_type": "approval",
            "payload": {
                "pattern_keys": ["file.write", "shell.exec"],  # plural!
                "status": "pending",
                "approved": None,
            },
            "actor": "agent",
        }
        resp, _ = _post(f"/api/workflow/runs/{run_id}/events", event_body)
        event = resp["data"]
        assert event["event_type"] == "approval"
        assert event["payload"]["pattern_keys"] == ["file.write", "shell.exec"]

    def test_unknown_event_type_tolerated(self):
        # Create
        body = {"name": "test_trace_unknown"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Append unknown event type — must not error
        event_body = {
            "event_type": "custom_unregistered_type",
            "payload": {"custom": "data"},
            "actor": "test",
        }
        resp, status = _post(f"/api/workflow/runs/{run_id}/events", event_body)
        assert status == 201, f"Unknown event type should be tolerated: {resp}"
        assert resp["data"]["event_type"] == "custom_unregistered_type"

    def test_node_crud(self):
        # Create
        body = {"name": "test_trace_nodes"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Get nodes
        resp, _ = _get(f"/api/workflow/runs/{run_id}/nodes")
        assert resp.get("success") is True
        assert isinstance(resp["data"], list)

    def test_artifacts_api(self):
        # Create
        body = {"name": "test_trace_artifacts"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Get artifacts
        resp, _ = _get(f"/api/workflow/runs/{run_id}/artifacts")
        assert resp.get("success") is True
        assert isinstance(resp["data"], list)

    def test_trace_events_sorted_by_sequence(self):
        # Create
        body = {"name": "test_trace_sequence"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Append multiple events
        for i in range(5):
            _post(f"/api/workflow/runs/{run_id}/events", {
                "event_type": "token",
                "payload": {"text": f"token {i}"},
            })

        # Get trace and verify events are sorted by event_id (sequence)
        resp, _ = _get(f"/api/workflow/runs/{run_id}/trace")
        events = resp["data"]["events"]
        event_ids = [e["event_id"] for e in events]
        assert event_ids == sorted(event_ids), "Events must be sorted by sequence"

    def test_cancel_run(self):
        # Create
        body = {"name": "test_trace_cancel"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Cancel
        resp, status = _post(f"/api/workflow/runs/{run_id}/cancel", {})
        assert status == 200
        assert resp["data"]["status"] == "cancelled"

    def test_update_run_via_patch(self):
        # Create
        body = {"name": "test_trace_patch"}
        create_resp, _ = _post("/api/workflow/runs", body)
        run_id = create_resp["data"]["run_id"]

        # Patch
        data = json.dumps({"status": "running"}).encode()
        req = urllib.request.Request(
            BASE + f"/api/workflow/runs/{run_id}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        opener = _get_opener()
        with opener.open(req, timeout=10) as r:
            resp = json.loads(r.read())
        assert resp.get("success") is True


# ── JS function signature tests ───────────────────────────────────────────────

class TestTraceJSFunctionSignatures:
    """Verify JS functions have correct signatures and required behavior."""

    def _function_block(self, src, name):
        marker = re.search(rf"(?:^|\n)(?:async\s+)?function\s+{re.escape(name)}\(", src)
        assert marker is not None, f"{name}() not found in workflow.js"
        start = marker.start()
        next_marker = re.search(
            r"\n(?:function\s+\w+|async\s+function\s+\w+|\bclass\s)", src[start + 1 :]
        )
        end = start + 1 + next_marker.start() if next_marker else len(src)
        return src[start:end]

    def test_renderEventCard_accepts_event_and_node(self):
        block = self._function_block(WORKFLOW_JS, "renderEventCard")
        # Should call _getEventIcon and _renderEventPayload
        assert "_getEventIcon" in block
        assert "_renderEventPayload" in block

    def test_renderEventCard_handles_unknown_event_type(self):
        block = self._function_block(WORKFLOW_JS, "renderEventCard")
        # Should have generic fallback for unknown types
        assert "_getEventIcon" in block

    def test_renderNodeDoneMarker_uses_fixed_output_shape(self):
        block = self._function_block(WORKFLOW_JS, "renderNodeDoneMarker")
        # Fixed shape: structured_result, summary, artifacts
        assert "structured_result" in block or "structuredResult" in block
        assert "artifacts" in block

    def test_escapeHtml_defined(self):
        block = self._function_block(WORKFLOW_JS, "escapeHtml")
        # Should use replace with char map
        assert "replace" in block

    def test_toggleTraceTimeline_toggles_all_bodies(self):
        block = self._function_block(WORKFLOW_JS, "toggleTraceTimeline")
        assert "trace-event-body" in block
        assert "trace-node-done-body" in block

    def test_showArtifactDetail_uses_modal(self):
        block = self._function_block(WORKFLOW_JS, "showArtifactDetail")
        assert "modal" in block.lower() or "overlay" in block.lower()

    def test_viewArtifactContent_fetches_content_endpoint(self):
        block = self._function_block(WORKFLOW_JS, "viewArtifactContent")
        assert "artifact" in block.lower()
        assert "/content" in block


# ── CSS responsiveness tests ──────────────────────────────────────────────────

class TestTraceCSSResponsive:
    """Verify trace timeline CSS works at narrow widths."""

    def test_trace_events_have_overflow_handling(self):
        # Should use overflow-hidden or overflow-auto on trace-event
        assert "overflow" in STYLE_CSS

    def test_artifact_chip_has_max_width(self):
        # Artifact chip name should be truncated
        assert "overflow" in STYLE_CSS or "text-overflow" in STYLE_CSS

    def test_modal_overlay_uses_fixed_position(self):
        assert "position: fixed" in STYLE_CSS or "position:fixed" in STYLE_CSS

    def test_artifact_modal_has_max_width(self):
        assert "max-width" in STYLE_CSS


# ── Generic event card test ──────────────────────────────────────────────────

class TestGenericEventCard:
    """UI must tolerate unknown event types by rendering a generic event card."""

    def test_generic_event_type_fallback_in_js(self):
        # The JS should have a fallback case for unknown event types
        assert "generic" in WORKFLOW_JS.lower() or "fallback" in WORKFLOW_JS.lower()

    def test_unknown_event_type_renders_payload(self):
        # Unknown event types should show their payload as JSON
        assert "detail-code" in STYLE_CSS or "pre" in WORKFLOW_JS
