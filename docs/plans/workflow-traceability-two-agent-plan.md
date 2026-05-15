# Workflow Traceability Two-Agent Implementation Plan

## Summary

- Agent 1 owns backend trace infrastructure, permissions, APIs, and tests.
- Agent 2 owns workflow/trace UI, frontend wiring, and UI tests.
- Final integration review focuses on schema/API correctness, security boundaries, trace completeness, and regression risk.

## Agent 1: Backend + Data Model

- Create trace persistence in `api/workflow_trace.py`: SQLite WAL schema for runs, nodes, append-only events, artifacts, and project memberships.
- Add route handlers in `api/routes.py`: create/list/read/cancel workflow runs, submit approvals, read artifacts.
- Add permission checks: project members can read project traces; `trace.audit` can read across projects; regular admin does not bypass trace-content permissions by default.
- Add redaction/truncation before persistence for prompts, tool args, tool outputs, node outputs, and artifact metadata.
- Add backend tests for schema init, append-only events, redaction, artifact hashing, permissions, run lifecycle, approval events, and skill snapshot immutability.

## Agent 2: UI + Trace Viewer

- Build the dedicated trace timeline UI in `static/workflow.js`: run list, node timeline, expandable events, artifacts, approvals, structured outputs, truncation/redaction markers.
- Add required styles in `static/style.css`, preserving the existing vanilla JS/no build-step architecture.
- Wire navigation from workflow runs or sessions into the trace view without replacing the existing chat transcript/tool-call display.
- Add frontend/static tests for timeline rendering, permission-error states, artifact links, collapsed/expanded nodes, approval event display, and mobile/narrow layout behavior.

## Integration Contract

- Backend returns trace payload as `run`, `nodes`, `events`, `artifacts`, sorted by event sequence.
- Events are append-only and include `event_type`, `run_id`, optional `node_id`, `actor`, `created_at`, `payload`, `redacted`, and `truncated`.
- Node output shape is fixed: `structured_result`, `summary`, `artifacts`.
- Artifacts are referenced by id and metadata only; large content is fetched through the artifact endpoint.
- UI must tolerate unknown event types by rendering a generic event card.

## Final Review Scope

- Verify Agent 1 and Agent 2 write scopes do not conflict except intentional route/UI integration.
- Review trace permissions carefully, especially cross-project access and admin behavior.
- Review redaction before write, not just before display.
- Review event ordering, append-only behavior, and crash-safe partial run states.
- Run focused pytest coverage plus relevant static UI tests.
- Check that existing session, project, multi-user, skill, and workflow behavior remains compatible.

## Assumptions

- Agents should work on separate branches or isolated worktrees and avoid reverting each other's changes.
- Agent 1 should land backend tests first so Agent 2 can develop against stable API fixtures.
- Agent 2 may mock backend responses initially, but final integration must use real API responses.
