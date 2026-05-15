"""Evergreen skin: deep green palette, opt-in via Settings -> Skin."""

from pathlib import Path


REPO = Path(__file__).parent.parent
CSS = (REPO / "static" / "style.css").read_text(encoding="utf-8")
BOOT_JS = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
INDEX_HTML = (REPO / "static" / "index.html").read_text(encoding="utf-8")


def test_evergreen_skin_present_in_skins_list():
    assert "{name:'Evergreen'" in BOOT_JS, "Evergreen skin missing from _SKINS list"
    assert "'#3FAE6C','#2D8852','#1F6A3D'" in BOOT_JS, "Evergreen swatches missing"


def test_evergreen_skin_in_early_init_allowlist():
    assert "evergreen:1" in INDEX_HTML, (
        "Evergreen missing from early-init skin allowlist; saved skin would reset on boot"
    )


def test_evergreen_legacy_theme_alias_maps_to_dark_skin():
    assert "evergreen:{theme:'dark',skin:'evergreen'}" in BOOT_JS, (
        "Legacy /theme evergreen alias must map to dark + evergreen skin"
    )
    assert "evergreen:['dark','evergreen']" in INDEX_HTML, (
        "Head init legacy map must normalize /theme evergreen consistently"
    )


def test_evergreen_skin_palette_has_light_and_dark_blocks():
    assert ':root[data-skin="evergreen"]{' in CSS, "Evergreen light palette block missing"
    assert ':root.dark[data-skin="evergreen"]{' in CSS, "Evergreen dark palette block missing"
    for token in ("--bg:#F3FAF5", "--sidebar:#E8F2EA", "--accent:#1E7A46"):
        assert token in CSS, f"Evergreen light token missing: {token}"
    for token in ("--bg:#0F1712", "--sidebar:#16211A", "--accent:#3FAE6C"):
        assert token in CSS, f"Evergreen dark token missing: {token}"
