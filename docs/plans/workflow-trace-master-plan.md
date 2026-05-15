# Workflow Trace Master Plan

## Summary

- Goal: deliver an enterprise-grade workflow trace layer for Hermes WebUI that makes each workflow run inspectable, reviewable, and auditable at the node/event/artifact level.
- Scope: backend trace persistence, ACLs, APIs, frontend trace timeline UI, artifact access, approval events, and focused regression tests.
- Constraint: preserve the existing lightweight architecture: Python stdlib backend, vanilla JS frontend, no build step, and minimal changes to unrelated workflow/chat/session code.

## Desired End State

Each workflow run should support:

- a stable `run` record with creator, project, timestamps, status, workspace, model, and skill snapshot metadata
- a `nodes` list describing node execution state and fixed output shape
- an append-only `events` stream describing what happened over time
- an `artifacts` list with metadata and separately fetched content
- project-scoped access control with explicit audit access
- redaction before persistence, not only before display
- a dedicated UI that shows timeline, node outputs, approvals, artifacts, and error states

## Non-Goals For This Iteration

- legal-grade tamper-proofing
- cryptographic signing or hash chains across events
- full workflow replay from stored traces
- a major rework of the existing workflow/task subsystem
- introducing a frontend framework or build pipeline

## Architecture Overview

### Trace Data Model

Core backend entities:

- `workflow_runs`
  - one row per workflow execution
  - stores run identity, project, creator, lifecycle status, timestamps, parent run, metadata
- `workflow_nodes`
  - one row per node
  - stores node lifecycle, agent name, timing, summary, structured result, artifact references
- `workflow_events`
  - append-only stream of run/node events
  - stores ordered sequence, event type, actor, payload, timestamps, redaction/truncation flags
- `workflow_artifacts`
  - metadata index for stored artifacts
  - stores artifact id, run id, file metadata, content hash, storage path, timestamps
- `project_trace_memberships`
  - trace-specific project ACL table
  - stores project id, username, role, can_read, can_write, created_at

### Storage Model

- SQLite remains the primary persistence layer.
- Trace DB should run in WAL mode.
- Large artifact content stays on disk under a trace-specific state directory.
- DB stores only artifact metadata and the file path, not large blobs.

### Security Model

- Project members read/write only within allowed projects.
- `trace_audit` is an explicit user capability, not implied by admin UI access.
- Browser sessions must not inherit audit privileges from token-scope helpers.
- API tokens need both:
  - user capability `trace_audit = 1`
  - token scope `trace.audit`
- Runs with no `project_id` are creator-private by default, except for trace auditors.

## Workstreams

## Workstream 1: Backend Trace Core

Owner: Agent 1

### Objectives

- make trace persistence correct and append-only where required
- fix the current broken membership model
- enforce read/write ACLs correctly
- expose stable APIs for the UI

### Tasks

1. Stabilize schema in `api/workflow_trace.py`
   - keep `workflow_runs`, `workflow_nodes`, `workflow_events`, `workflow_artifacts`
   - replace incorrect membership shape with per-user membership rows
   - add schema migration detection for existing broken table shape

2. Implement explicit permission helpers
   - `user_can_trace_audit(user)`
   - `can_read_run(run_id, user)`
   - `can_write_run(run_id, user)`
   - creator-private logic for unprojected runs

3. Add trace membership helpers
   - list project members
   - upsert project member
   - delete project member
   - seed first writer as owner when a project trace ACL is first created

4. Fix event persistence
   - preserve append-only semantics
   - reject mutable updates to existing events
   - keep stable ordering by sequence/event id

5. Fix redaction
   - replace length-only truncation with real secret redaction via shared helpers
   - set `redacted` and `truncated` flags independently
   - apply to event payloads, node outputs, summaries, artifact metadata, text content, errors, skill snapshots

6. Fix artifact handling
   - use dedicated trace artifact routes and storage helpers
   - hash stored bytes with SHA-256
   - ensure artifact read uses parent run ACL

7. Expose stable trace APIs
   - `GET /api/workflow/runs`
   - `POST /api/workflow/runs`
   - `GET /api/workflow/runs/{run_id}`
   - `GET /api/workflow/runs/{run_id}/nodes`
   - `GET /api/workflow/runs/{run_id}/events`
   - `GET /api/workflow/runs/{run_id}/artifacts`
   - `GET /api/workflow/runs/{run_id}/trace`
   - `POST /api/workflow/runs/{run_id}/cancel`
   - `POST /api/workflow/runs/{run_id}/approval`
   - `POST /api/workflow/runs/{run_id}/events`
   - `GET /api/workflow/trace-artifacts/{artifact_id}`
   - `GET /api/workflow/trace-artifacts/{artifact_id}/content`
   - `GET /api/workflow/projects/{project_id}/members`
   - `POST /api/workflow/projects/{project_id}/members`
   - `DELETE /api/workflow/projects/{project_id}/members/{username}`

8. Tighten validation and error handling
   - invalid membership changes should return 4xx
   - invalid run writes should return 4xx
   - permission failures should consistently return 403
   - not found conditions should consistently return 404

### Acceptance Criteria

- outsiders cannot read or mutate another project’s runs
- read-only members can inspect but not mutate
- artifact metadata and content both enforce ACL
- runs list only returns visible runs
- secret-like values are masked before storage
- all legacy route shadowing is removed for trace artifacts

## Workstream 2: Frontend Trace Timeline UI

Owner: Agent 2

### Objectives

- present trace data clearly without breaking existing workflow panel usage
- tolerate incomplete or evolving event types
- align with the corrected backend contract

### Tasks

1. Preserve the three-view workflow panel
   - run list
   - run detail
   - trace timeline

2. Fix timeline construction in `static/workflow.js`
   - correct ordering between events and synthetic node markers
   - do not place node completion markers before earlier events
   - prefer event-driven ordering where possible

3. Fix artifact detail flow
   - switch to `/api/workflow/trace-artifacts/*`
   - treat plain-text content responses as strings
   - render previews correctly for empty and non-empty text
   - keep download and detail modal working

4. Fix modal and interaction wiring
   - make close action callable
   - avoid fragile inline/global coupling when possible
   - keep overlay click-to-close

5. Fix create/cancel flow
   - remove invalid dynamic import from create path
   - use one direct API path for create
   - align cancel action with final backend route contract

6. Harden payload rendering
   - unknown event types must fall back safely
   - missing node, artifact, or payload fields must not break rendering
   - render fixed node output shape when present

7. Improve expand/collapse UX
   - make default state explicit and consistent
   - keep toggle labels and chevrons synchronized with state
   - support node output expansion as well as event expansion

8. Keep styling localized
   - add trace-specific classes in `static/style.css`
   - preserve existing layout and panel assumptions
   - support narrow/mobile layouts

### Acceptance Criteria

- trace view opens and renders from `{ run, nodes, events, artifacts }`
- unknown event types render generic cards
- artifact preview displays actual content
- close button works
- timeline order matches execution order
- create/cancel actions use the intended API contract

## Workstream 3: Integration And Review

Owner: final reviewer

### Objectives

- ensure Agent 1 and Agent 2 converge on one contract
- block merge if ACL or trace correctness is still weak

### Tasks

1. Contract review
   - check route paths match on both sides
   - check payload field names match on both sides
   - verify node output shape assumptions

2. Security review
   - verify browser sessions do not get implicit audit access
   - verify token scope rules are conjunctive, not alternative
   - verify artifact access follows run ACL

3. Trace correctness review
   - verify event ordering
   - verify append-only event semantics
   - verify redaction happens before persistence
   - verify cancellation, failure, and partial runs remain explainable

4. Regression review
   - confirm existing workflow task endpoints still work
   - confirm existing artifact endpoints for legacy workflow tasks still work
   - confirm workflow panel still loads without trace data

## Execution Order

### Phase 1: Backend Remediation First

1. fix ACLs and membership schema
2. fix artifact route shadowing
3. stabilize trace payload and route contract
4. update backend tests to remove insecure assumptions

Reason:

- the frontend should not bind itself to broken artifact routes or broken permission semantics

### Phase 2: Frontend Remediation

1. update route bindings to final backend contract
2. fix timeline ordering
3. fix artifact preview behavior
4. fix modal close and expand/collapse details
5. update frontend regression tests

Reason:

- once the backend contract is stable, the UI can be finished without rework

### Phase 3: Integration Verification

1. run backend trace tests
2. run workflow UI/static tests
3. manually verify run list, detail, trace view, artifact modal, cancel flow, and permission errors
4. review diff for accidental changes in unrelated workflow/chat paths

## Test Plan

### Backend Tests

- schema initialization
- migration from old bad membership schema
- owner backfill from `workflow_runs.created_by`
- append-only event insertion and ordering
- read ACL for creator, member, outsider, auditor
- write ACL for writer vs read-only member
- private run visibility when `project_id` is null
- token audit scope and user capability combinations
- artifact metadata and content ACL
- real secret redaction and truncation flags

### Frontend Tests

- trace view rendering from full payload
- generic fallback rendering for unknown event types
- artifact preview content rendering from text response
- modal close behavior
- timeline ordering behavior
- expand/collapse behavior
- route binding to trace-artifact endpoints
- create flow without dynamic import

### Manual Verification

- create a run and inspect it in run list
- open run detail
- open full trace
- verify events appear in chronological/sequence order
- verify node completion marker appears after relevant execution activity
- open artifact modal and preview content
- cancel a running run
- verify outsider user cannot read another project trace
- verify auditor can read across projects only when explicitly configured

## Risks

### Risk 1: Existing dirty worktree overlap

- `api/routes.py`, `static/workflow.js`, and `static/style.css` already contain in-progress changes.
- Mitigation:
  - patch narrowly
  - review surrounding code before each edit
  - avoid broad rewrites

### Risk 2: Contract churn between agents

- frontend may code against temporary backend behavior
- Mitigation:
  - backend contract must be finalized first
  - frontend route usage must follow that contract exactly

### Risk 3: False confidence from brittle tests

- string-presence tests can pass while the UI is broken
- Mitigation:
  - convert key tests to behavior-focused regression tests

### Risk 4: Legacy workflow artifact route conflicts

- trace and legacy workflow artifacts currently overlap
- Mitigation:
  - move trace artifacts to a dedicated prefix
  - keep legacy workflow artifact tests intact

## Deliverables

### Backend Deliverables

- corrected `api/workflow_trace.py`
- corrected trace route handling in `api/routes.py`
- any required user capability storage changes
- updated backend trace regression tests

### Frontend Deliverables

- corrected `static/workflow.js`
- corrected trace-related CSS in `static/style.css`
- updated frontend trace regression tests

### Documentation Deliverables

- this master plan
- Agent 1 remediation plan
- Agent 2 remediation plan
- any follow-up ADR or RFC if route/ACL semantics become part of the stable platform contract

## File Map

- [api/workflow_trace.py](/home/ubuntu/workspace/hermes-webui/api/workflow_trace.py)
- [api/routes.py](/home/ubuntu/workspace/hermes-webui/api/routes.py)
- [api/auth.py](/home/ubuntu/workspace/hermes-webui/api/auth.py)
- [api/users.py](/home/ubuntu/workspace/hermes-webui/api/users.py)
- [api/helpers.py](/home/ubuntu/workspace/hermes-webui/api/helpers.py)
- [static/workflow.js](/home/ubuntu/workspace/hermes-webui/static/workflow.js)
- [static/style.css](/home/ubuntu/workspace/hermes-webui/static/style.css)
- [tests/test_workflow_trace.py](/home/ubuntu/workspace/hermes-webui/tests/test_workflow_trace.py)
- [tests/test_1900_trace_timeline.py](/home/ubuntu/workspace/hermes-webui/tests/test_1900_trace_timeline.py)
- [workflow-traceability-two-agent-plan.md](/home/ubuntu/workspace/hermes-webui/docs/plans/workflow-traceability-two-agent-plan.md)
- [agent1-remediation-plan.md](/home/ubuntu/workspace/hermes-webui/docs/plans/agent1-remediation-plan.md)
- [agent2-remediation-plan.md](/home/ubuntu/workspace/hermes-webui/docs/plans/agent2-remediation-plan.md)

## Definition Of Done

This work is done when:

- trace ACLs are correct
- trace artifact routes are isolated from legacy workflow artifact routes
- redaction occurs before persistence
- event ordering is trustworthy
- frontend trace timeline renders the corrected contract without runtime errors
- regression tests cover the known failure modes
- manual checks confirm the main run/trace/artifact flows work
