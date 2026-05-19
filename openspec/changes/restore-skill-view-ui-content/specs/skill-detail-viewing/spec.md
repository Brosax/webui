## ADDED Requirements

### Requirement: Skill detail responses are skill_view compatible
The system SHALL return skill detail data from `/api/skills/content` in a shape compatible with Hermes Agent `skill_view`, including success state, resolved name, description, content, path metadata, tags, related skills, and linked files.

#### Scenario: Profile skill detail opens
- **WHEN** a user opens a skill listed from the active profile skills directory
- **THEN** `/api/skills/content` returns the full `SKILL.md` content and `skill_view`-compatible metadata for that same skill

#### Scenario: Missing optional metadata remains stable
- **WHEN** a skill has no tags, related skills, or linked files
- **THEN** `/api/skills/content` returns empty collections for those fields instead of omitting them or returning null

### Requirement: Skill detail resolution covers every listed source
The system SHALL allow every skill returned by the WebUI skills list to be opened through `/api/skills/content`, including skills from profile directories, shared multi-user directories, configured external skill directories, and plugin-qualified names.

#### Scenario: External skill opens from list
- **WHEN** a skill is discovered from an external skill directory and appears in the Skills panel
- **THEN** selecting the skill opens its detail view from that external directory

#### Scenario: Shared multi-user skill opens
- **WHEN** multi-user mode lists skills from the shared skills directory
- **THEN** selecting a shared skill opens its detail view from the shared skills directory

#### Scenario: Plugin-qualified skill fallback works
- **WHEN** the requested skill name is plugin-qualified and cannot be resolved as a local file skill
- **THEN** the system uses Hermes Agent plugin skill resolution and returns the plugin skill detail when available

### Requirement: Skill detail lookup is profile-safe
The system SHALL resolve local skill detail content using the active WebUI profile or active shared skills surface without falling back to stale module-global paths from the startup profile.

#### Scenario: Browser profile isolation
- **WHEN** two browser profiles have different skills with distinct names
- **THEN** each profile can open only its active skill detail through the Skills panel

#### Scenario: No stale startup path fallback
- **WHEN** a skill is absent from the active profile but present in the startup/root profile
- **THEN** `/api/skills/content` does not return the startup/root skill for the active profile request

### Requirement: Linked skill files are safely browsable
The system SHALL allow linked files under the resolved skill directory to be opened while rejecting path traversal and wildcard-shaped skill requests.

#### Scenario: Linked reference file opens
- **WHEN** a skill detail response includes a linked reference file
- **THEN** requesting that linked file returns the file content from the resolved skill directory

#### Scenario: Traversal is rejected
- **WHEN** a linked file request attempts to escape the resolved skill directory
- **THEN** the request is rejected without reading files outside the skill directory

### Requirement: Skills panel renders restored skill detail content
The Skills panel SHALL display the restored `skill_view`-compatible content and linked file sections without showing an empty detail pane for successfully resolved skills.

#### Scenario: Skill detail content appears in UI
- **WHEN** a user selects a resolved skill in the Skills panel
- **THEN** the panel displays the skill body content and any linked files returned by `/api/skills/content`

#### Scenario: Skill load failure is visible
- **WHEN** `/api/skills/content` returns an unsuccessful skill detail response
- **THEN** the Skills panel shows a load failure state instead of rendering a blank successful detail view
