"""Regression checks for the shared button style contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
THEMES = ROOT / "THEMES.md"
STYLE = ROOT / "static" / "style.css"


def test_themes_doc_declares_button_style_contract():
    src = THEMES.read_text(encoding="utf-8")
    assert "Button style contract" in src
    assert "--btn-secondary-bg" in src
    assert "--btn-primary-bg" in src
    assert "--btn-danger-bg" in src
    assert "--btn-icon-bg" in src


def test_style_defines_button_tokens_for_light_and_dark():
    src = STYLE.read_text(encoding="utf-8")
    assert "--btn-secondary-bg:var(--surface)" in src
    assert "--btn-primary-bg:var(--accent)" in src
    assert "--btn-danger-bg:" in src
    assert "--btn-icon-bg:transparent" in src


def test_shared_button_classes_use_button_tokens():
    src = STYLE.read_text(encoding="utf-8")
    assert ".btn,\n.sm-btn{" in src or ".btn,\r\n.sm-btn{" in src
    assert "background:var(--btn-secondary-bg);" in src
    assert "border-color:var(--btn-secondary-hover-border);" in src
    assert ".btn.primary," in src
    assert ".btn.danger," in src
    assert ".panel-head-btn{" in src
    assert "var(--btn-icon-hover-bg)" in src
