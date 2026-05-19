## Why

The current WebUI skill detail path no longer matches the original WebUI/Hermes Agent `skill_view` behavior closely enough, so skills can be listed but their detail view may omit or reshape the content users expect to see in the UI. This matters now because recent skill-runtime hardening intentionally avoided stale `tools.skills_tool` globals, but the replacement direct-file response needs to preserve the `skill_view` contract.

## What Changes

- Restore skill detail responses so `/api/skills/content` returns a `skill_view`-compatible payload for local, profile-scoped, shared, external, and plugin-qualified skills.
- Keep the recent profile/runtime safety guarantees: no stale startup-profile `SKILLS_DIR`, no cross-profile path leakage, and no accidental first-time skill-tool imports while holding streaming env locks.
- Ensure the Skills panel displays the full resolved skill content and metadata consistently with the original WebUI behavior.
- Add regressions covering profile skills, external skill dirs, linked files, and UI expectations around `skill_view`-style data.

## Capabilities

### New Capabilities
- `skill-detail-viewing`: Skill browsing and detail rendering for WebUI skill sources, including `skill_view`-compatible content and linked files.

### Modified Capabilities

## Impact

- Backend API: `api/routes.py` skill listing/detail helpers and `/api/skills/content`.
- Frontend UI: `static/panels.js` skill detail rendering, if needed to consume restored metadata fields.
- Tests: focused pytest coverage for skill detail response shape, external directories, profile/shared modes, and linked file navigation.
- No new runtime dependencies are expected.
