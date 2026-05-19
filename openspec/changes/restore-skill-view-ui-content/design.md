## Context

Hermes WebUI has two related but distinct skill surfaces:

- Runtime slash invocation, which must use the active profile's `HERMES_HOME/skills` so it matches Hermes CLI behavior.
- Skills panel browsing/detail display, which must use the active WebUI management surface: profile skills in legacy/profile mode, shared skills in multi-user mode, plus configured external skill directories and plugin-qualified fallback.

Recent stabilization work avoided stale `tools.skills_tool.SKILLS_DIR` by reading resolved local `SKILL.md` files directly. That protected profile isolation, but it also moved the detail response away from the original `skill_view` behavior that users expect to see in the UI.

## Goals / Non-Goals

**Goals:**

- Restore `skill_view`-compatible detail data for skills opened in the WebUI.
- Keep profile-safe lookup and avoid stale startup-profile module globals.
- Ensure every skill listed in the panel can be opened from the same resolved source.
- Preserve multi-user shared skill management semantics.
- Keep runtime slash skill invocation separate from browsing semantics.

**Non-Goals:**

- Do not change Hermes Agent's upstream `tools.skills_tool` API.
- Do not make shared multi-user skills the runtime invocation source.
- Do not introduce a frontend framework or build step.
- Do not redesign the Skills panel beyond the minimum needed to render restored detail data and errors correctly.

## Decisions

1. Resolve skill files first, then produce a `skill_view`-compatible payload.

   The backend should continue resolving the skill against explicit search dirs before reading detail data. This avoids calling `tools.skills_tool.skill_view(name)` for ordinary local skills, because that function depends on module-global paths that can point at the wrong profile. After resolving the file, WebUI can either call `skill_view` using an absolute path if that is proven safe, or construct a response that preserves the same public fields and semantics.

   Alternative considered: patch `tools.skills_tool.SKILLS_DIR` per request and delegate all local lookups to `skill_view(name)`. This is closer to upstream but reintroduces global mutation and concurrency risk.

2. Use one shared resolver for list, detail, and linked files.

   The search order should be the active skills directory followed by external skill dirs. Detail and linked-file requests must use the same resolver so the UI cannot list a skill that later cannot be opened.

   Alternative considered: keep list and detail resolution separate. That is the source of the current mismatch and should be avoided.

3. Keep plugin-qualified skill fallback delegated to Hermes Agent.

   Plugin skills may not live on disk under the active skills directory. For `namespace:skill` requests that are not local file skills, WebUI should keep using Hermes plugin discovery and `skill_view` fallback.

   Alternative considered: remove plugin fallback and only support local files. That would regress existing plugin-qualified skill viewing.

4. Treat unsuccessful backend responses as UI errors.

   The Skills panel currently renders `data.content || ''`, which can hide backend lookup failures behind an empty successful-looking pane. The frontend should check `success === false` or missing content and show a visible failure state.

   Alternative considered: rely only on HTTP status failures. Existing helpers may return structured unsuccessful JSON with HTTP 200, so UI-side checking is needed.

## Risks / Trade-offs

- `skill_view` upstream may add fields later -> Mitigation: tests should pin required fields while allowing extra fields.
- Absolute-path delegation to `skill_view` may still depend on module globals in some Hermes Agent versions -> Mitigation: prefer explicit resolved-file parsing unless tests prove safe delegation.
- External directory ordering can create duplicate skill names -> Mitigation: preserve current list dedup/search order so opening a name matches the listed entry.
- UI changes can accidentally affect skill editing -> Mitigation: keep `_currentSkillDetail` and edit flows using the raw content returned by the detail endpoint.

## Migration Plan

1. Add backend tests for response shape and source resolution.
2. Adjust backend detail serialization to be `skill_view` compatible without stale global fallback.
3. Add frontend/static tests for failure handling and content rendering.
4. Run targeted skill tests and then the broader relevant suite.
5. Restart the WebUI service after implementation.
