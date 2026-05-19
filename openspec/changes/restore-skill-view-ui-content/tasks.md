## 1. Backend Skill Detail Contract

- [ ] 1.1 Add tests that compare `/api/skills/content` local skill responses against the required `skill_view`-compatible fields.
- [ ] 1.2 Update the resolved-file detail serializer to return stable `success`, `name`, `description`, `content`, `path`, `skill_dir`, `tags`, `related_skills`, and `linked_files` fields.
- [ ] 1.3 Preserve profile-safe lookup by resolving local skills from explicit active/search directories before reading or serializing detail content.
- [ ] 1.4 Preserve plugin-qualified fallback through Hermes Agent `skill_view` for unresolved `namespace:skill` requests.

## 2. Source Resolution Coverage

- [ ] 2.1 Add tests proving every skill listed from an external skills directory can be opened from `/api/skills/content`.
- [ ] 2.2 Add or update tests for shared multi-user skills so listed shared skills open from the shared directory.
- [ ] 2.3 Add or update profile isolation tests so active-profile detail lookup does not fall back to root/startup-profile skills.
- [ ] 2.4 Verify linked file requests reuse the same resolved skill directory and reject traversal.

## 3. Skills Panel UI

- [ ] 3.1 Add static/frontend tests that `openSkill` treats `success: false` skill detail responses as load failures.
- [ ] 3.2 Update `static/panels.js` only if needed so successful skill detail responses render body content, metadata, and linked files instead of a blank pane.
- [ ] 3.3 Preserve edit/create/delete flows by keeping raw `SKILL.md` content available in `_currentSkillDetail`.

## 4. Verification

- [ ] 4.1 Run targeted skill tests including `tests/test_skill_invocation_stability.py`, `tests/test_webui_skill_slash_runtime.py`, `tests/test_issue1880_profile_scoped_skills.py`, and relevant Skills panel/static tests.
- [ ] 4.2 Run the broader relevant pytest suite, documenting unrelated pre-existing failures separately.
- [ ] 4.3 Restart the WebUI service with the repository-required `ctl.sh restart` command.
