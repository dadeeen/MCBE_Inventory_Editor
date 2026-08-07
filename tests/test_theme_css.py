from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "static" / "style.css"
CSS = CSS_PATH.read_text(encoding="utf-8")


_THEME_ALIASES = {
    "accent",
    "border",
    "surface",
    "surface-muted",
    "text-color",
    "text-muted",
    "success-color",
    "warning-color",
    "warning-text",
}
_LIGHT_TOKENS = {
    "control-bg",
    "control-border",
    "code-bg",
    "code-text",
    "logo-title-start",
    "logo-title-end",
    "success-text",
    "warning-text",
    "danger-text",
    "info-text",
    "floating-card-bg",
    "modal-card-bg",
    "modal-card-border",
    "browser-item-bg",
    "browser-item-border",
    "enchantment-text",
    "workspace-well-bg",
    "workspace-row-bg",
    "workspace-well-border",
}


def _defined_vars() -> set[str]:
    return set(re.findall(r"--([a-zA-Z0-9_-]+)\s*:", CSS))


def _used_vars() -> set[str]:
    return set(re.findall(r"var\(--([a-zA-Z0-9_-]+)", CSS))


def _block_vars(selector: str) -> set[str]:
    matches = list(re.finditer(re.escape(selector) + r"\s*\{(?P<body>.*?)\n\}", CSS, flags=re.S))
    assert matches, f"CSS block missing: {selector}"
    names: set[str] = set()
    for match in matches:
        names.update(re.findall(r"--([a-zA-Z0-9_-]+)\s*:", match.group("body")))
    return names


def test_css_custom_properties_are_defined() -> None:
    assert _used_vars() <= _defined_vars()


def test_newer_theme_aliases_are_defined() -> None:
    assert _defined_vars() >= _THEME_ALIASES


def test_light_theme_defines_contrast_tokens() -> None:
    assert _block_vars(':root[data-theme="light"]') >= _LIGHT_TOKENS


def test_system_light_theme_defines_contrast_tokens() -> None:
    assert _block_vars(':root[data-theme="system"]') >= _LIGHT_TOKENS


def test_logo_gradient_is_theme_aware() -> None:
    logo_rules = list(re.finditer(r"\.logo h1\s*\{(?P<body>.*?)\n\}", CSS, flags=re.S))
    assert logo_rules
    combined = "\n".join(match.group("body") for match in logo_rules)
    assert "--logo-title-start" in combined
    assert "--logo-title-end" in combined


def test_elevated_surfaces_are_opaque_and_item_browser_width_is_stable() -> None:
    assert "background: var(--floating-card-bg);" in CSS
    assert "background: var(--modal-card-bg" in CSS
    assert ".browser-box" in CSS and "align-items: stretch;" in CSS
    browser_grid = re.search(r"\.browser-grid\s*\{(?P<body>.*?)\n\}", CSS, flags=re.S)
    assert browser_grid
    assert "width: 100%;" in browser_grid.group("body")
    assert "min-width: 0;" in browser_grid.group("body")


def test_light_theme_tooltips_and_browser_cards_use_theme_surfaces() -> None:
    assert "background: var(--browser-item-bg" in CSS
    assert "background: var(--modal-card-bg" in CSS
    assert "color: var(--enchantment-text" in CSS


def test_workspace_wells_and_ability_warnings_use_theme_tokens() -> None:
    assert "background: var(--workspace-well-bg);" in CSS
    assert "background: var(--workspace-row-bg);" in CSS
    risk_rules = list(re.finditer(r"\.ability-risk-note\s*\{(?P<body>.*?)\n\}", CSS, flags=re.S))
    assert risk_rules
    final_rule = risk_rules[-1].group("body")
    assert "color: var(--warning-text);" in final_rule
    assert "background: var(--warning-bg);" in final_rule
    assert "border-color: var(--warning-border);" in final_rule


def test_save_validation_and_decision_log_use_theme_tokens() -> None:
    assert ".save-validation-status.ok" in CSS
    assert "color: var(--success-text);" in CSS
    assert ".save-validation-row.info span { background: var(--info-bg); color: var(--info-text); }" in CSS
    decision_panel = re.search(r"\.decision-log-panel\s*\{(?P<body>.*?)\n\}", CSS, flags=re.S)
    decision_row = re.search(r"\.decision-log-row\s*\{(?P<body>.*?)\n\}", CSS, flags=re.S)
    assert decision_panel and "background: var(--surface-muted);" in decision_panel.group("body")
    assert decision_row and "background: var(--surface-strong);" in decision_row.group("body")
