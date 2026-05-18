"""Static regressions for workflow canvas route wiring."""
from pathlib import Path


ROUTES = Path(__file__).resolve().parent.parent / "api" / "routes.py"


def _routes_source():
    return ROUTES.read_text(encoding="utf-8")


def test_canvas_run_route_does_not_read_body_twice():
    src = _routes_source()
    start = src.find('_canvas_pattern = re.compile(r"^/api/workflow/canvas(/run)?$")')
    assert start != -1, "canvas route block not found"
    end = src.find('if parsed.path == "/api/setup/admin":', start)
    assert end != -1, "canvas route block end not found"
    block = src[start:end]

    assert "body = read_body(handler)" not in block
    assert "json.loads(body)" not in block
    assert "data = body if isinstance(body, dict) else {}" in block


def test_canvas_live_route_does_not_shadow_global_time():
    src = _routes_source()
    start = src.find('r"^/api/workflow/canvas/live/([^/]+)$"')
    assert start != -1, "canvas live route block not found"
    end = src.find("# GET /api/workflow/projects/{project_id}/members", start)
    assert end != -1, "canvas live route block end not found"
    block = src[start:end]

    assert "\n        import time\n" not in block
