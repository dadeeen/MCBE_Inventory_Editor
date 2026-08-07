from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_loading_overlay_shows_spinner_progress_and_status_text() -> None:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="loadingOverlay"' in html
    assert 'class="loading-spinner"' in html
    assert 'class="loading-progress"' in html
    assert 'id="loadingText"' in html
    assert ".loading-progress" in css
    assert "@keyframes loadingProgress" in css
