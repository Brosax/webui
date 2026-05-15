# Agent 2 Remediation Plan

## Summary

- Keep the overall three-view UI structure in `static/workflow.js`: run list, run detail, trace view.
- Fix the runtime defects first: broken timeline ordering, artifact content rendering, modal close wiring, and the invalid dynamic import.
- Align the frontend with the backend remediation plan so Agent 2 does not cement the current broken artifact and cancel-route behavior.

## Required Fixes

### 1. Fix timeline ordering

- Replace the current mixed sort in `_buildTimeline()`.
- Do not assign synthetic sequence `0` to `node_done` markers.
- Build a real ordering key:
  - events sort by `event_id` first
  - node completion markers sort by `ended_at` when present
  - when both exist for the same node, the completion marker must render after that node’s terminal event
- If backend later exposes a node completion event, prefer rendering from events instead of injecting a synthetic marker.

### 2. Fix artifact content loading

- `api()` returns plain text for `text/plain` responses, not `{ data }`.
- Update `viewArtifactContent()` to treat the response as a string payload.
- Preserve truncation only in the UI layer for preview rendering; do not assume backend JSON wrapping.
- Handle empty-string content correctly instead of treating it as missing data.

### 3. Fix modal close wiring

- Export `closeArtifactModal` on `window`, or remove the inline `onclick` and bind the handler programmatically.
- Prefer programmatic binding to reduce global leakage and prevent future rename drift.
- Keep overlay click-to-close behavior.

### 4. Remove invalid dynamic import in create flow

- Delete the `import('/api/workflow/runs')` logic from `createTraceRun()`.
- Use one direct `POST /api/workflow/runs` request.
- Keep one payload shape only; do not rely on exception-driven fallback control flow.
- After successful create, either:
  - prepend the returned run to `_traceRuns`, or
  - refresh via `loadWorkflowTasks()` if the backend returns derived counts later.

### 5. Align artifact routes with backend remediation

- Stop binding trace artifacts to `/api/workflow/artifacts/{artifact_id}`.
- Move UI calls to the remediated dedicated prefix:
  - `GET /api/workflow/trace-artifacts/{artifact_id}`
  - `GET /api/workflow/trace-artifacts/{artifact_id}/content`
- Keep artifact rendering code isolated so this route change touches only a few call sites.

### 6. Align cancel behavior with backend contract

- Do not invent trace mutation semantics in the UI.
- If backend keeps `POST /api/workflow/runs/{run_id}/cancel`, call that explicitly.
- If backend keeps `PATCH /api/workflow/runs/{run_id}`, restrict the UI to the exact supported mutation contract and do not assume generic patchability.
- Agent 2 should follow the final Agent 1 route decision, not force the contract from the frontend side.

### 7. Improve expand/collapse behavior

- The current CSS sets `.trace-event-body` and `.trace-node-done-body` to `display: none` by default.
- Decide the intended default:
  - if cards should start collapsed, the header chevron and toggle button text must reflect that
  - if cards should start expanded, the initial DOM/CSS state must render them visible
- Make `toggleTraceTimeline()` and `toggleEventBody()` update both visibility and affordance state consistently.
- Add support for expanding/collapsing node output bodies, not just event bodies.

### 8. Harden payload rendering

- Keep generic fallback rendering for unknown event types.
- Make payload rendering tolerant of:
  - missing `payload`
  - non-object payloads
  - missing `node`
  - missing `artifact.name`, `artifact.size`, `artifact.type`
- Avoid assuming `node.agent_name` always exists; fall back to `node.node_id` or a generic label.

## Test Changes

### Replace structure-only tests with behavioral tests

- Keep a small number of structure tests for smoke coverage.
- Add focused JS-behavior tests that inspect function bodies or execute minimal browser-like logic where feasible.

### Add tests for the known regressions

- Timeline ordering test:
  - given events with increasing `event_id` and a completed node
  - assert synthetic node marker is not sorted before earlier events
- Artifact content test:
  - simulate `api()` returning plain text
  - assert `viewArtifactContent()` renders that text
- Modal close test:
  - assert the close control resolves to a defined callable path
- Create run test:
  - assert `createTraceRun()` does not contain `import('/api/workflow/runs')`
- Route binding test:
  - assert artifact fetches target `/api/workflow/trace-artifacts/`
- Collapse state test:
  - assert initial state and toggle label are consistent

### Re-scope API tests

- Current API tests in `tests/test_1900_trace_timeline.py` are really backend contract tests.
- Keep only thin integration checks in the UI-focused file.
- Move authoritative route and payload tests to backend trace test files if they are not already covered there.
- Do not let frontend tests bless insecure or provisional backend routes.

## Suggested Edit Scope

- [static/workflow.js](/home/ubuntu/workspace/hermes-webui/static/workflow.js)
  - `_buildTimeline`
  - `viewArtifactContent`
  - `_showArtifactModal` / `closeArtifactModal`
  - `createTraceRun`
  - `cancelRun`
  - artifact endpoint call sites
  - expand/collapse handlers
- [static/style.css](/home/ubuntu/workspace/hermes-webui/static/style.css)
  - body visibility defaults
  - chevron/expanded-state styling if needed
  - node body expand/collapse affordance
- [tests/test_1900_trace_timeline.py](/home/ubuntu/workspace/hermes-webui/tests/test_1900_trace_timeline.py)
  - remove brittle string-presence assertions that do not prove behavior
  - add regression tests for the specific runtime issues above

## Assumptions

- Agent 1 will change trace artifact routes as part of the ACL remediation.
- Agent 2 should not optimize for compatibility with the currently broken artifact route shadowing.
- The UI remains vanilla JS with no build step and should continue using the shared `api()` helper.
