"""Browser regression for Studio inspector visibility, Lore textarea and locale.

Requires Jinja2, Python Playwright and Chromium. No Flask/world file needed:
the real index.html, layout CSS and selection controller run with test data.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from studio_inventory_width_smoke import prepare_page

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(os.environ["STUDIO_PREVIEW_DIR"]) if os.environ.get("STUDIO_PREVIEW_DIR") else None


def setup_controller(page):
    page.add_script_tag(content=(ROOT / "static/selection_state.js").read_text("utf-8"))
    page.add_script_tag(content=(ROOT / "static/inventory_rendering.js").read_text("utf-8"))
    page.evaluate("""() => {
        const state = { slots: [], ender: -1 };
        window.studioTestController = window.MCBEInventoryRendering.createInventoryGridController({
          doc: document,
          elements: window.MCBEInventoryRendering.collectInventoryGridElements(document),
          getSelectedSlots: () => state.slots,
          getSelectedEnderSlot: () => state.ender,
          setSelectedSlots: slots => { state.slots = slots; },
          setSelectedEnderSlot: index => { state.ender = index; },
          getWorldPath: () => '/synthetic/world',
          loadSingleSlotEditor: (slot, ender) => {
            document.getElementById('detailSlotNum').textContent = String(slot);
          },
        });
        window.studioTestController.updateSelectionUI();
        // Show coherent synthetic loaded-world content in visual fixtures.
        document.getElementById('selectedWorldKicker').textContent = 'AUSGEWÄHLT';
        document.getElementById('selectedWorldName').textContent = 'Testwelt';
        document.getElementById('selectedWorldPath').textContent = 'Minecraft-Standardordner · Testwelt';
        document.getElementById('selectedWorldBar').classList.remove('is-empty');
    }""")


def snapshot(page):
    return page.evaluate("""() => {
      const box = s => document.querySelector(s).getBoundingClientRect();
      const visible = s => getComputedStyle(document.querySelector(s)).display !== 'none';
      const lore = document.getElementById('detailLore');
      const css = getComputedStyle(lore);
      const header = box('.app-header'), intro = box('.layout-intro'), world = box('#worldSection');
      const workspace = box('.workspace'), grid = box('.main-inventory-grid');
      const editor = box('#detailEditorPanel'), sidebar = box('.right-panel');
      const input = box('#detailLore');
      return {
        standby: visible('#studioInspectorStandby'),
        single: visible('#detailEditorPanel'),
        multi: visible('#multiSelectPanel'),
        activeSlot: document.querySelectorAll('.main-inventory-grid .inventory-slot.selected').length,
        slotWidth: box('.main-inventory-grid .inventory-slot').width,
        inspectorX: sidebar.x,
        workRight: workspace.right, worldSummaryVisible: visible('#selectedWorldBar'),
        headRight: header.right, introRight: intro.right,
        gap: sidebar.x-grid.right,
        textareaResize: css.resize,
        textareaOverflowY: css.overflowY,
        textareaWidth: input.width,
        editorWidth: editor.width,
        pageOverflow: document.documentElement.scrollWidth - innerWidth,
      };
    }""")


def check_language(locale, catalog):
    def translator(text, **params):
        return (text if locale == "de" else catalog.get(text, text)).format(**params)

    rendered = (
        Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
        .get_template("index.html")
        .render(
            app_locale=locale,
            t=translator,
            url_for=lambda name, **params: "/static/" + params["filename"] if name == "static" else "/" + name,
            csrf_token="preview",
            app_config={
                "mode": "local",
                "distribution": {"kind": "SOURCE", "project_version": "dev", "app_root": "/example"},
                "data_root_status": {"path": "/example"},
                "auth_enabled": False,
            },
            i18n_catalog=catalog if locale == "en" else {},
        )
    )
    match = re.search(r'<label for="detailLore">([^<]+)</label>', rendered)
    assert match, f"Missing Lore label in {locale}"
    value = html.unescape(match.group(1).strip())
    desired = "Beschreibung (Lore – eine Zeile pro Eintrag)" if locale == "de" else "Description (lore – one line per entry)"
    assert value == desired, (locale, value)
    return 1


def run():
    checks = 0
    catalog = json.loads((ROOT / "static/i18n/en.json").read_text("utf-8"))
    with sync_playwright() as pw:
        chromium = pw.chromium.launch(headless=True, executable_path=os.environ.get("CHROMIUM_PATH") or shutil.which("chromium"), args=["--no-sandbox"])
        for language in ("de", "en"):
            checks += check_language(language, catalog)
        for width, height in ((1181, 900), (1366, 900), (1440, 900), (1600, 960), (1740, 960), (1920, 1080), (2200, 900)):
            page = chromium.new_page(viewport={"width": width, "height": height}, locale="de-DE")
            prepare_page(page)
            setup_controller(page)
            for theme in ("dark", "light", "minecraft", "system"):
                page.evaluate("(theme)=>{document.documentElement.dataset.theme=theme}", theme)
                before = snapshot(page)
                assert (before["standby"], before["single"], before["multi"]) == (True, False, False), (width, theme, before)
                assert before["pageOverflow"] <= 1 and before["gap"] <= 80, (width, theme, before)
                assert (
                    max(before[k] for k in ("workRight", "headRight", "introRight")) - min(before[k] for k in ("workRight", "headRight", "introRight")) < 1
                ), (width, theme, before)
                assert not before["worldSummaryVisible"], (width, theme, before)
                checks += 1
                page.evaluate("""() => window.studioTestController.handleSlotClick({ctrlKey:false,metaKey:false},15)""")
                one = snapshot(page)
                assert (one["standby"], one["single"], one["multi"]) == (False, True, False), (width, theme, one)
                assert one["activeSlot"] == 1, (width, theme, one)
                assert abs(one["slotWidth"] - before["slotWidth"]) < 0.5, (width, theme, one, before)
                assert one["textareaResize"] == "vertical" and one["textareaOverflowY"] == "auto", (width, theme, one)
                assert 0 < one["textareaWidth"] <= one["editorWidth"], (width, theme, one)
                checks += 1
                # Textarea must scroll within its own boundaries for long Lore.
                page.evaluate("""() => {
                    const el=document.getElementById('detailLore');
                    el.value=Array.from({length:60}, (_,i)=>'Lore-Eintrag '+i).join('\\n');
                    el.style.height='220px';
                    el.scrollTop=10000;
                }""")
                lore = page.evaluate("""() => {
                    const el=document.getElementById('detailLore');
                    return {scrollTop:el.scrollTop, scrollHeight:el.scrollHeight, clientHeight:el.clientHeight,
                        width:el.getBoundingClientRect().width, maxHeight:parseFloat(getComputedStyle(el).maxHeight)};
                }""")
                assert lore["scrollTop"] > 0 and lore["scrollHeight"] > lore["clientHeight"], (width, theme, lore)
                assert lore["width"] <= one["editorWidth"] and lore["clientHeight"] <= lore["maxHeight"], (width, theme, lore)
                checks += 1
                page.evaluate("""() => window.studioTestController.handleSlotClick({ctrlKey:true,metaKey:false},17)""")
                multi = snapshot(page)
                assert (multi["standby"], multi["single"], multi["multi"]) == (False, False, True), (width, theme, multi)
                checks += 1
                page.evaluate("""() => window.studioTestController.clearSelection()""")
                end = snapshot(page)
                assert (end["standby"], end["single"], end["multi"]) == (True, False, False), (width, theme, end)
                assert abs(end["slotWidth"] - before["slotWidth"]) < 0.5, (width, theme, end, before)
                checks += 1
            if OUTPUT_DIR is not None and width == 1600:
                page.evaluate("""()=>{document.documentElement.dataset.theme='dark';window.studioTestController.clearSelection();}""")
                OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
                page.screenshot(path=str(OUTPUT_DIR / "Studio_v13_Standby_1600.png"), full_page=False)
                page.evaluate("""() => window.studioTestController.handleSlotClick({ctrlKey:false},15)""")
                page.screenshot(path=str(OUTPUT_DIR / "Studio_v13_Slot_1600.png"), full_page=False)
            if OUTPUT_DIR is not None and width == 1920:
                page.evaluate("""()=>{document.documentElement.dataset.theme='dark';window.studioTestController.clearSelection();}""")
                page.screenshot(path=str(OUTPUT_DIR / "Studio_v13_Standby_1920.png"), full_page=False)
                page.evaluate("""() => window.studioTestController.handleSlotClick({ctrlKey:false},15)""")
                page.screenshot(path=str(OUTPUT_DIR / "Studio_v13_Slot_1920.png"), full_page=False)
            page.close()
        chromium.close()
    print(f"PASS: {checks} real-selection, grid, Lore, localization and theme checks")


if __name__ == "__main__":
    run()
