# Repository Guidelines

## Project Structure & Module Organization

Hermes WebUI is a lightweight Python and vanilla JavaScript app with no frontend build step. Server entry points live at `server.py`, `mcp_server.py`, `bootstrap.py`, and `start.sh`. Backend route and helper modules are in `api/`; keep `server.py` thin and place new server behavior there. Browser code, styles, service worker, icons, and HTML are in `static/`. Tests are in `tests/`, mostly issue- or sprint-focused regression files such as `test_issue1910_login_attempt_persistence.py`. Documentation and manual testing assets are in `docs/`, with broader project docs at the repository root.

## Build, Test, and Development Commands

- `python3 bootstrap.py`: installs or locates dependencies, checks Hermes Agent integration, starts the local web server, and opens the UI unless disabled.
- `./start.sh`: shell launcher for local development.
- `./ctl.sh start|status|logs|restart|stop`: daemon lifecycle wrapper; logs default to `~/.hermes/webui.log`.
- After completing any code, style, or documentation update, automatically run `CODEX_NETWORK_ALLOW_LOCAL_BINDING=1 HERMES_WEBUI_DEFAULT_WORKSPACE=/home/ubuntu/workspace/hermes-webui HERMES_WEBUI_HOST=0.0.0.0 ./ctl.sh restart` so the local service reflects the latest workspace changes.
- `pytest tests/ -v --timeout=60`: primary automated test command used for local verification and CI.
- `docker compose up -d`: runs the single-container Docker setup after copying and editing `.env.docker.example` to `.env`.

## Coding Style & Naming Conventions

Preserve the project’s simple architecture: Python stdlib plus minimal dependencies, vanilla JS, no bundler, and no frontend framework. Use 4-space indentation in Python and clear snake_case names for modules, functions, and tests. JavaScript files in `static/` use direct DOM APIs and module-level helpers; match nearby naming and event-handling patterns. Keep comments short and only where they clarify non-obvious behavior.

## Testing Guidelines

Use pytest for automated coverage. Add or update focused regression tests in `tests/` when changing backend behavior, session state, config handling, uploads, streaming, or static UI logic. Follow existing naming patterns: `test_issueNNNN_*.py`, `test_sprintNN.py`, or a concise feature name. For UI changes, also run relevant manual checks from `TESTING.md`, including reload behavior and narrow/mobile layouts when affected.

## Commit & Pull Request Guidelines

Git history uses short conventional-style subjects such as `docs(contributors): ...` and `test(infra): ...`; follow that pattern when practical. Keep PRs to one logical change, avoid drive-by refactors, and update docs when behavior or setup changes. PR descriptions should include what changed, why it matters, verification, risks or follow-ups, and AI usage disclosure. User-visible UI changes should include before/after screenshots or a short video.

For moderately large updates, create a local git backup commit after verification and service restart. Use a concise conventional-style subject that makes the checkpoint easy to find later.

## Security & Configuration Tips

Treat auth, environment files, path handling, uploads, streaming, and workspace access as high-risk areas. Use `.env.example` or `.env.docker.example` as templates, never commit secrets, and document any new environment variable in the relevant setup docs.
