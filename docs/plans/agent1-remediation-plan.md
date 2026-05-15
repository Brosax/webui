# Agent 1 Remediation Plan

## Summary

- Keep the current `workflow_runs` / `workflow_nodes` / `workflow_events` / `workflow_artifacts` skeleton.
- Rework ACLs, route wiring, and redaction so the trace backend matches the original intent: project-member read/write, explicit audit permission, private unprojected runs, and protected artifact access.
- Treat the current implementation as a non-mergeable draft: preserve the data model where it is sound, replace the parts that currently encode insecure behavior into tests.

## Key Changes

- Replace the current ACL model.
  - Remove `require_trace_audit` from `can_read_run()` and split permission checks into `can_read_run(run_id, user)`, `can_write_run(run_id, user)`, and `user_can_trace_audit(user)`.
  - Add explicit `trace_audit` user capability in `users.db` via a new `users.trace_audit` boolean column; include it in authenticated user payloads.
  - For API tokens, require both: the bound user has `trace_audit=1`, and the token scope includes `trace.audit`.
  - For cookie/browser sessions, do not use `user_has_scope()` as an authorization source for trace audit.

- Replace `project_trace_memberships` with actual per-user membership.
  - Migrate the table to `(project_id, username, role, can_read, can_write, created_at)`; remove `run_id` from the membership key.
  - Seed the run creator as `owner` when the first trace run is created for a project with no existing trace membership.
  - `project_id = null` runs are creator-private by default; only the creator and explicit trace auditors may read them.
  - Add helpers to list/upsert/remove project trace members; do not infer membership from “a run exists”.

- Fix route-level authorization and path collisions.
  - Change trace artifact endpoints to a distinct prefix: `/api/workflow/trace-artifacts/{artifact_id}` and `/api/workflow/trace-artifacts/{artifact_id}/content`.
  - Do not reuse `/api/workflow/artifacts/*`, because that namespace is already claimed by the legacy workflow/task API.
  - `GET /api/workflow/runs*` and trace subresources use `can_read_run`.
  - `POST /api/workflow/runs/{run_id}/cancel|approval|events` and `PATCH /api/workflow/runs/{run_id}` use `can_write_run`.
  - `GET /api/workflow/runs` must filter to only runs visible to the current user; do not return the raw global list.

- Use real secret redaction, then truncate.
  - Replace the local “redaction” helpers with `api.helpers._redact_value` / `_redact_text`, then apply size caps.
  - Persist separate `redacted` and `truncated` flags based on actual content changes.
  - Apply this to event payloads, node outputs, summaries, errors, skill snapshots, artifact metadata, and text artifact content before writing to disk.
  - Keep hashing on the stored artifact bytes so `hash_sha256` reflects what was actually persisted.

- Add migration and hardening.
  - On startup/schema init, detect the current incorrect `project_trace_memberships(project_id, run_id, ...)` shape and rebuild it to the per-user schema.
  - Backfill owner memberships from existing `workflow_runs(project_id, created_by)` rows where possible.
  - Add validation so membership mutation, run creation, and event append return clean 4xx responses instead of bubbling SQLite/foreign-key failures as 500s.

## Public/API Changes

- `GET /api/workflow/runs`
  - Returns only runs visible to the current user.
- `POST /api/workflow/runs`
  - Creates a run only if the caller can write to the target project; for a project with no trace membership rows yet, seeds the creator as owner.
- `GET /api/workflow/runs/{run_id}`
  - Read-protected by `can_read_run`.
- `POST /api/workflow/runs/{run_id}/cancel|approval|events`
  - Write-protected by `can_write_run`.
- `PATCH /api/workflow/runs/{run_id}`
  - Write-protected by `can_write_run`.
- `GET /api/workflow/trace-artifacts/{artifact_id}` and `/content`
  - Read-protected by the parent run ACL.
- Add minimal backend membership endpoints for Agent 2 to consume later.
  - `GET /api/workflow/projects/{project_id}/members`
  - `POST /api/workflow/projects/{project_id}/members`
  - `DELETE /api/workflow/projects/{project_id}/members/{username}`

## Test Plan

- Remove tests that currently bless insecure behavior.
  - outsider access due to auto-created “membership”
  - public access to `project_id != null` runs
- Add backend permission tests for:
  - cookie user without membership cannot read another project’s run
  - read-only member can read but cannot cancel/patch/append/approve
  - writer/owner can mutate
  - `project_id = null` run is visible only to creator and trace auditor
  - token with `trace.audit` scope but user `trace_audit = 0` is denied
  - token for a trace auditor without `trace.audit` scope is denied
- Add route tests for:
  - `GET /api/workflow/runs` visibility filtering
  - trace artifact endpoints are not shadowed by legacy workflow artifact routes
  - artifact metadata and artifact content both enforce ACLs
  - invalid run/node membership writes return 400/403/404, not 500
- Add redaction tests using real credential fixtures from `tests/test_security_redaction.py`.
  - event payload secret masking
  - artifact content secret masking
  - `redacted` vs `truncated` flag correctness
- Add migration tests.
  - old `project_trace_memberships(project_id, run_id, ...)` schema upgrades cleanly
  - owner backfill from `created_by` works for existing runs

## Assumptions

- Existing project records do not have native owners or members, so trace membership is introduced as a trace-specific project ACL layer.
- The first trace writer to a project with no trace ACL rows becomes its initial trace owner.
- UI management of trace members can land after this backend remediation, but the backend membership endpoints and ACL semantics must land now so Agent 2 has a stable contract.
