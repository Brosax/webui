import pathlib
import re


REPO = pathlib.Path(__file__).parent.parent
STYLE_CSS = (REPO / "static" / "style.css").read_text(encoding="utf-8")


def test_kanban_and_profiles_primary_nav_entries_are_hidden():
    """Kanban and Profiles remain available internally but not as main-page entries."""
    for panel in ("kanban", "profiles"):
        assert re.search(
            rf'\.rail\s+\.nav-tab\[data-panel="{panel}"\]\s*,\s*'
            rf'\.sidebar-nav\s+\.nav-tab\[data-panel="{panel}"\]\s*'
            r"\{\s*display\s*:\s*none\s*;\s*\}",
            STYLE_CSS,
        ), f"{panel} primary nav entry must be hidden in both rail and sidebar nav"
