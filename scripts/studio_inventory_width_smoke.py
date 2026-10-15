"""Offline Studio inventory-width regression checks, using the real HTML and CSS.

Run: python scripts/studio_inventory_width_smoke.py
Requires Jinja2, Playwright for Python, and Chromium. Uses synthetic inventory
slots: this checks layout/selection states, not Bedrock world persistence.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright
from studio_scroll_smoke import render_template

ROOT = Path(__file__).resolve().parents[1]


def prepare_page(page):
    page.set_content(render_template())
    for asset in ("style.css", "layout_variants.css", "focus_workspace.css"):
        page.add_style_tag(content=(ROOT / "static" / asset).read_text(encoding="utf-8"))
    page.evaluate("""() => {
        document.documentElement.dataset.layout = 'studio';
        document.documentElement.dataset.theme = 'dark';
        document.getElementById('layoutSelect').value = 'studio';
        document.body.classList.add('app-world-loaded', 'app-player-loaded');
        document.body.dataset.workflowView = 'inventory';
        document.getElementById('inventoryContainer').style.display = 'flex';
        document.getElementById('selectedWorldBar').style.display = 'flex';
        document.getElementById('playerInventorySummary').style.display = 'flex';
        document.getElementById('layoutViewTitle').textContent = 'Inventar bearbeiten';
        document.getElementById('layoutViewDescription').textContent =
            'Bearbeite Items, Ausrüstung und Enderchest des gewählten Spielers.';
        document.getElementById('layoutCurrentWorld').textContent = 'Testwelt';
        document.getElementById('layoutCurrentPlayer').textContent = 'Lokaler Spieler';
        document.querySelector('[data-workflow-view="inventory"].app-section-nav button');
        for (const [selector, count, offset] of [
            ['.main-inventory-grid', 27, 9],
            ['.hotbar-grid', 9, 0],
            ['.ender-chest-grid', 27, 0]]) {
            const grid = document.querySelector(selector);
            for (let index = 0; index < count; index++) {
                const cell = document.createElement('div');
                cell.className = 'inventory-slot';
                cell.dataset.slot = String(index + offset);
                cell.innerHTML = '<small style="position:absolute;top:3px;left:5px;font-size:9px">'
                    + String(index + offset) + '</small>' + (index === 2 ? '<span>▣</span>' : '');
                grid.appendChild(cell);
            }
        }
    }""")


def set_mode(page, state):
    page.evaluate(
        """state => {
        document.getElementById('detailEditorPanel').style.display =
            state === 'single' ? 'flex' : 'none';
        document.getElementById('multiSelectPanel').style.display =
            state === 'multi' ? 'flex' : 'none';
        document.querySelector('.main-inventory-grid .inventory-slot').classList.toggle('selected', state !== 'standby');
    }""",
        state,
    )


def sizes(page):
    return page.evaluate("""() => {
        const rect = selector => {
            const box = document.querySelector(selector).getBoundingClientRect();
            return {x: box.x, right: box.right, width: box.width, height: box.height};
        };
        const grid = rect('.main-inventory-grid');
        const inspector = rect('.right-panel');
        return {
            workspace: rect('.workspace'),
            inventory: rect('#inventoryContainer'),
            grid, slot: rect('.main-inventory-grid .inventory-slot'),
            inspector, gap: inspector.x - grid.right,
            horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
            standbyVisible: getComputedStyle(document.getElementById('studioInspectorStandby')).display !== 'none',
        };
    }""")


def main():
    checks = 0
    path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("chromium-browser")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=path, args=["--no-sandbox"] if os.name == "posix" else [])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        prepare_page(page)
        # The user-reported gap was over 400px at 1920px. Keep it close to a
        # single card padding + column gap, without making the slots enormous.
        for width in (1181, 1200, 1280, 1366, 1440, 1600, 1740, 1920, 2200, 2560):
            page.set_viewport_size({"width": width, "height": 900})
            baseline = None
            for state in ("standby", "single", "multi", "standby"):
                set_mode(page, state)
                observed = sizes(page)
                assert observed["horizontalOverflow"] <= 1, (width, state, observed)
                assert 0 < observed["gap"] <= 80, (width, state, observed)
                assert 44 <= observed["slot"]["width"] <= 105, (width, state, observed)
                assert observed["standbyVisible"] == (state == "standby"), (width, state, observed)
                assert observed["inspector"]["x"] >= observed["inventory"]["right"] + 15, (width, state, observed)
                if baseline is None:
                    baseline = observed
                else:
                    for name in ("workspace", "inventory", "grid", "slot", "inspector"):
                        assert abs(observed[name]["width"] - baseline[name]["width"]) <= 0.5, (width, state, name, observed, baseline)
                        assert abs(observed[name]["x"] - baseline[name]["x"]) <= 0.5, (width, state, name, observed, baseline)
                checks += 1
            # Visible header, heading and editor share one right edge. The world
            # context lives in the rail; its former card no longer occupies space.
            alignment = page.evaluate("""() => {
                const right = selector => document.querySelector(selector).getBoundingClientRect().right;
                return [right('.app-header'), right('.layout-intro'), right('.workspace')];
            }""")
            assert max(alignment) - min(alignment) <= 1, (width, alignment)
            assert page.locator("#selectedWorldBar").is_hidden(), width
            if width >= 1920:
                assert 99 <= baseline["slot"]["width"] <= 105, (width, baseline)
                # The wider navigation rail leaves less than 530px for the
                # inspector. Bound the actual inventory track instead of
                # coupling this check to an obsolete sidebar proportion.
                assert baseline["inventory"]["width"] <= 1018, (width, baseline)
                assert baseline["inspector"]["width"] >= 400, (width, baseline)
                assert baseline["gap"] <= 36, (width, baseline)
            print(f"Studio {width}px: slot={baseline['slot']['width']:.1f}px, gap={baseline['gap']:.1f}px, inspector stable")

        # Below the desktop breakpoint, preserve the original stacked responsive
        # layout, including a functional inspector view after inventory slots.
        for width, height in ((1180, 800), (1024, 800), (760, 800), (390, 800)):
            page.set_viewport_size({"width": width, "height": height})
            for state in ("standby", "single", "multi"):
                set_mode(page, state)
                observed = sizes(page)
                assert observed["horizontalOverflow"] <= 1, (width, state, observed)
                assert observed["workspace"]["width"] <= width, (width, state, observed)
                checks += 1

        # Other editor views are intentionally untouched by Studio's inventory-only cap.
        page.set_viewport_size({"width": 1920, "height": 900})
        for view in ("world", "player-edit", "mounts", "tools", "save"):
            page.evaluate("""view => document.body.dataset.workflowView = view""", view)
            assert page.evaluate("""() => getComputedStyle(document.querySelector('.workspace')).maxWidth""") == "none", view
            checks += 1
        browser.close()
    print(f"PASS: {checks} offline Chromium Studio inventory layout checks")


if __name__ == "__main__":
    main()
