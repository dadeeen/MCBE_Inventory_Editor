from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_versions_button_stays_inside_editor() -> None:
    app_js = _read("static/app.js")
    data_source_js = _read("static/data_source_view.js")
    html = _read("templates/index.html")

    assert "data_source_view.js" in html
    assert html.index("data_source_view.js") < html.index("app.js")
    assert "window.MCBEDataSourceView.createInventoryDataSourceController" in app_js
    assert "data-toggle-db-versions" in data_source_js
    assert 'href="/versions"' not in app_js
    assert 'href="/versions"' not in data_source_js
    assert 'fetch("/api/item-db/versions")' in data_source_js


def test_versions_page_back_link_prefers_browser_history() -> None:
    template = _read("templates/versions.html")

    assert "data-history-back" in template
    assert "window.history.back()" in template
    assert "referrer.origin !== window.location.origin" in template
