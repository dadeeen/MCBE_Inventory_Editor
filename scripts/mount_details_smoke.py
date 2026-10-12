"""Focused offline browser checks for Mount inspection details.

Run with the same Python Playwright and Chromium setup as
mount_workspace_smoke.py. Actual UI code runs with synthetic preview data;
no Minecraft world is opened and the fixture rejects every write.

Checks opaque, readable dialogs in all themes/layouts, keyboard dismissal,
small-screen scrolling, and the visual mapping of four footprint shapes.
Optional --screenshots DIR saves review images and observed metrics.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from pathlib import Path

from mount_workspace_smoke import ROOT, assert_contained_controls, create_mount_page
from playwright.sync_api import sync_playwright

THEMES = (
    ("dark", "dark"),
    ("light", "light"),
    ("minecraft", "dark"),
    ("system", "dark"),
    ("system", "light"),
)

FOOTPRINTS = (
    {"x": 168.0, "z": -316.0, "halfWidth": 0.7, "width": 2, "depth": 2},
    {"x": 168.0, "z": -315.5, "halfWidth": 0.7, "width": 2, "depth": 3},
    {"x": 168.5, "z": -316.0, "halfWidth": 0.7, "width": 3, "depth": 2},
    {"x": 168.5, "z": -315.5, "halfWidth": 0.7, "width": 3, "depth": 3},
)


def dialog_observations(page):
    return page.locator("#mountTechOverlay").evaluate("""dialog => {
      const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
      const context=canvas.getContext('2d',{willReadFrequently:true});
      const rgba=value=>{
        context.clearRect(0,0,1,1);context.fillStyle=value;context.fillRect(0,0,1,1);
        return [...context.getImageData(0,0,1,1).data];
      };
      const composite=(front,back)=>{
        const alpha=front[3]/255;
        return [0,1,2].map(index=>front[index]*alpha+back[index]*(1-alpha)).concat(255);
      };
      const luminance=color=>color.slice(0,3).map(value=>{
        value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;
      }).reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
      const style=getComputedStyle(dialog),rect=dialog.getBoundingClientRect();
      const background=rgba(style.backgroundColor);
      const selectors='#mountTechTitle,.mount-tech-label,.mount-tech-note,'+
        '.mount-footprint-head strong,.mount-footprint-head small,.mount-fp-caption,.mount-fp-size,'+
        '.mount-fp-legend,.mount-scan-chip,.mount-tech-blocks th,.mount-tech-blocks td,.status-pill,'+
        '.mount-probe-details>summary,.mount-placement-reason';
      const contrast=[...dialog.querySelectorAll(selectors)].filter(node=>
        node.getClientRects().length&&node.textContent.trim()).map(node=>{
          let effective=background;
          const chain=[];for(let item=node;item&&item!==dialog;item=item.parentElement)chain.push(item);
          for(const item of chain.reverse())effective=composite(rgba(getComputedStyle(item).backgroundColor),effective);
          const color=composite(rgba(getComputedStyle(node).color),effective);
          const light=luminance(color),dark=luminance(effective);
          return {text:node.textContent.trim().slice(0,90),
            ratio:(Math.max(light,dark)+.05)/(Math.min(light,dark)+.05),
            color:getComputedStyle(node).color};
        });
      const clipped=[];
      const walker=document.createTreeWalker(dialog,NodeFilter.SHOW_TEXT);
      for(let node=walker.nextNode();node;node=walker.nextNode()){
        if(!node.textContent.trim()||!node.parentElement?.getClientRects().length)continue;
        const range=document.createRange();range.selectNodeContents(node);
        if([...range.getClientRects()].some(part=>part.left<rect.left+1||part.right>rect.right-1))
          clipped.push(node.textContent.trim().slice(0,90));
      }
      return {background:style.backgroundColor,backgroundAlpha:background[3]/255,
        opacity:Number(style.opacity),color:style.color,
        bounds:{left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom,
          width:rect.width,height:rect.height},
        scrollWidth:dialog.scrollWidth,clientWidth:dialog.clientWidth,
        scrollHeight:dialog.scrollHeight,clientHeight:dialog.clientHeight,
        pageOverflow:document.documentElement.scrollWidth-innerWidth,
        contrast,clipped};
    }""")


def assert_dialog_frame(page, context):
    observed = dialog_observations(page)
    assert observed["backgroundAlpha"] == 1 and observed["opacity"] == 1, (context, "transparent dialog", observed)
    rect = observed["bounds"]
    viewport = page.viewport_size
    assert viewport is not None
    assert rect["left"] >= 15 and rect["right"] <= viewport["width"] - 15, (context, rect)
    assert rect["top"] >= 15 and rect["bottom"] <= viewport["height"] - 15, (context, rect)
    assert observed["scrollWidth"] <= observed["clientWidth"] + 1, (context, "horizontal dialog overflow", observed)
    assert observed["pageOverflow"] <= 1, (context, "horizontal page overflow", observed)
    assert not observed["clipped"], (context, "clipped dialog copy", observed["clipped"])
    weak = [item for item in observed["contrast"] if item["ratio"] < 4.49]
    assert not weak, (context, "dialog text contrast below 4.5:1", weak)
    return observed


def open_all_details(page):
    for details in page.locator("#mountTechOverlay details").all():
        if not details.evaluate("node=>node.open"):
            details.locator(":scope > summary").click()


def assert_keyboard_dismissal(page, context):
    dialog = page.locator("#mountTechOverlay")
    trigger = page.locator("#btnMountTechDetails")
    visible_summaries = dialog.locator("summary:visible").count()
    visited = set()
    for _ in range(visible_summaries + 3):
        page.keyboard.press("Tab")
        assert dialog.evaluate("node=>node.contains(document.activeElement)"), (context, "Tab left dialog")
        active = page.evaluate("document.activeElement.id||document.activeElement.parentElement.className")
        visited.add(active)
    assert "btnMountTechClose" in visited, (context, "close button unreachable", visited)
    page.keyboard.press("Shift+Tab")
    assert dialog.evaluate("node=>node.contains(document.activeElement)"), (context, "reverse Tab left dialog")
    page.keyboard.press("Escape")
    assert not dialog.evaluate("node=>node.open"), (context, "Escape did not close")
    assert trigger.evaluate("node=>node===document.activeElement"), (context, "Escape lost trigger focus")
    trigger.click()
    page.locator("#btnMountTechClose").click()
    assert not dialog.evaluate("node=>node.open"), (context, "close button did not close")
    assert trigger.evaluate("node=>node===document.activeElement"), (context, "close button lost trigger focus")
    trigger.click()
    page.mouse.click(3, 3)
    assert not dialog.evaluate("node=>node.open"), (context, "backdrop click did not close")
    assert trigger.evaluate("node=>node===document.activeElement"), (context, "backdrop dismissal lost trigger focus")


def run_dialog_checks(browser, root, screenshots=None):
    observations = []
    for layout in ("classic", "studio", "focus"):
        for width, height in ((320, 568), (390, 740), (1440, 960)):
            for theme, scheme in THEMES:
                context = (layout, width, theme, scheme)
                page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme, reduced_motion="reduce")
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                create_mount_page(page, root=root, locale="en" if width == 320 else "de", layout=layout, loaded=True)
                page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
                page.locator("#btnMountTechDetails").click()
                observed = assert_dialog_frame(page, context)
                open_all_details(page)
                assert page.locator('[data-disclosure="preview-notes"]').count() == 0, (context, "redundant preview notes")
                assert page.locator(".mount-fp-caption").count() == 0, (context, "safe verdict repeated below the diagram")
                expected_rows = ["Head space", "Feet space", "Floor"] if width == 320 else ["Kopfraum", "Fußraum", "Boden"]
                assert page.locator(".mount-tech-blocks th").all_text_contents() == expected_rows, (context, "block order")
                expanded = assert_dialog_frame(page, (context, "expanded details"))
                dialog = page.locator("#mountTechOverlay")
                if width < 400 and expanded["scrollHeight"] > expanded["clientHeight"]:
                    dialog.evaluate("node=>node.scrollTop=0")
                    previous_scroll = page.evaluate("scrollY")
                    rect = dialog.bounding_box()
                    assert rect is not None
                    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
                    page.mouse.wheel(0, 600)
                    page.wait_for_function("document.getElementById('mountTechOverlay').scrollTop>0")
                    assert page.evaluate("scrollY") == previous_scroll, (context, "underlying page scrolled")
                    assert_dialog_frame(page, (context, "scrolled details"))
                dialog.evaluate("node=>node.scrollTop=0")
                if screenshots and layout == "studio" and (width == 1440 or (width == 320 and theme in ("dark", "light"))):
                    page.screenshot(path=str(screenshots / f"details-{layout}-{width}-{theme}-{scheme}.png"))
                assert_keyboard_dismissal(page, context)
                assert not errors, (context, errors)
                assert page.evaluate("window.mountTestState.writes") == 0, (context, "unexpected write")
                observations.append(
                    {
                        "layout": layout,
                        "width": width,
                        "theme": theme,
                        "scheme": scheme,
                        "background": observed["background"],
                        "minContrast": min(item["ratio"] for item in expanded["contrast"]),
                        "height": observed["bounds"]["height"],
                        "expandedHeight": expanded["bounds"]["height"],
                    }
                )
                page.close()
    print(f"Opaque, readable Mount dialogs, keyboard and scrolling: {len(observations)} scenarios passed", flush=True)
    return observations


def run_footprint_checks(browser, root, screenshots=None):
    observations = []
    for locale in ("de", "en"):
        for width in (320, 1440):
            page = browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
            create_mount_page(page, root=root, locale=locale)
            for sample in FOOTPRINTS:
                context = (locale, width, sample)
                page.evaluate("sample=>window.mountTestState.footprintSample=sample", sample)
                page.evaluate("window.mountTestController.loadPreview()")
                page.locator("#btnMountTechDetails").click()
                board = page.locator(".mount-fp-board.has-bounds")
                assert board.count() == 1, (context, "collision board missing")
                assert board.get_attribute("role") == "img", (context, "footprint has no accessible image role")
                assert board.get_attribute("data-grid-width") == str(sample["width"]), context
                assert board.get_attribute("data-grid-depth") == str(sample["depth"]), context
                assert board.locator(".mount-fp-cell").count() == sample["width"] * sample["depth"], context
                assert f"{sample['width']}×{sample['depth']}" in page.locator(".mount-footprint-head").inner_text(), context
                box = board.locator(".mount-fp-bounds")
                assert box.is_visible() and board.locator(".mount-fp-position").is_visible(), context
                grid_rect = board.locator(".mount-fp-grid").bounding_box()
                bounds_rect = box.bounding_box()
                assert grid_rect and bounds_rect, context
                expected_x = (sample["x"] - sample["halfWidth"] - math.floor(sample["x"] - sample["halfWidth"])) / sample["width"]
                expected_z = (sample["z"] - sample["halfWidth"] - math.floor(sample["z"] - sample["halfWidth"])) / sample["depth"]
                expected_width = sample["halfWidth"] * 2 / sample["width"]
                expected_depth = sample["halfWidth"] * 2 / sample["depth"]
                for actual, expected in (
                    (bounds_rect["x"] - grid_rect["x"], expected_x * grid_rect["width"]),
                    (bounds_rect["y"] - grid_rect["y"], expected_z * grid_rect["height"]),
                    (bounds_rect["width"], expected_width * grid_rect["width"]),
                    (bounds_rect["height"], expected_depth * grid_rect["height"]),
                ):
                    assert abs(actual - expected) < 1.1, (context, "collision overlay misaligned", actual, expected)
                assert abs(float(box.get_attribute("data-width-blocks")) - 2 * sample["halfWidth"]) < 0.0001, context
                assert_dialog_frame(page, context)
                if screenshots and locale == "de" and width == 1440:
                    page.locator(".mount-footprint").screenshot(path=str(screenshots / f"footprint-{sample['width']}x{sample['depth']}.png"))
                observations.append({"locale": locale, "viewport": width, **sample, "bounds": bounds_rect})
                page.keyboard.press("Escape")
            if locale == "de" and width == 1440:
                # "stairs" contains "air" but is still a solid material in the
                # diagram. Actual placement safety is determined by the backend.
                for floor_name in ("minecraft:stone_stairs", "minecraft:air"):
                    sample = {**FOOTPRINTS[0], "floorName": floor_name}
                    page.evaluate("sample=>window.mountTestState.footprintSample=sample", sample)
                    page.evaluate("window.mountTestController.loadPreview()")
                    page.locator("#btnMountTechDetails").click()
                    cells = page.locator(".mount-fp-cell")
                    air_count = page.locator(".mount-fp-cell.air").count()
                    assert air_count == (cells.count() if floor_name == "minecraft:air" else 0), (floor_name, "incorrect air material")
                    block_details = page.locator('details[data-disclosure="block-probe"]')
                    if not block_details.evaluate("node=>node.open"):
                        block_details.locator(":scope > summary").click()
                    floor_tile = block_details.locator("tr").filter(has=page.get_by_role("rowheader", name="Boden", exact=True)).locator(".mount-block-tile")
                    assert floor_tile.evaluate("node=>node.classList.contains('air')") == (floor_name == "minecraft:air"), (floor_name, "incorrect floor tile")
                    observations.append({"locale": locale, "viewport": width, "material": floor_name, "airCells": air_count})
                    page.keyboard.press("Escape")
                sample = {**FOOTPRINTS[0], "edgeOverhang": True}
                page.evaluate("sample=>window.mountTestState.footprintSample=sample", sample)
                page.evaluate("window.mountTestController.loadPreview()")
                page.locator("#btnMountTechDetails").click()
                assert page.locator(".mount-fp-cell.air").count() == 1, "Missing edge overhang material"
                assert page.locator(".mount-fp-cell.blocked").count() == 0, "Tolerated edge overhang shown as a failed placement"
                assert page.locator(".mount-tech-position .status-pill.success").count() == 1, "Overall safe placement status lost"
                assert page.locator(".mount-fp-caption").inner_text() == page.evaluate(
                    "window.mountTestPreview().candidate_positions[0].chunk_probe.footprint_check.message"
                ), "Tolerated edge overhang explanation lost"
                assert page.locator("#btnMountCreate").is_enabled(), "Supported edge overhang blocks the queue"
                observations.append({"locale": locale, "viewport": width, "case": "tolerated edge overhang"})
                page.keyboard.press("Escape")
                page.evaluate("() => {window.mountTestState.footprintSample=null;window.mountTestState.allUnsafe=true;}")
                page.evaluate("window.mountTestController.loadPreview()")
                assert page.locator(".mount-tech-position .status-pill.error").count() == 1, "Overall unsafe placement status lost"
                action = page.locator("#btnMountCreate")
                assert not action.count() or action.is_disabled(), "Unsafe placement can be queued"
                assert page.locator(".mount-fp-cell.blocked").count() == 0, "Floor material grid overrides overall placement result"
                observations.append({"locale": locale, "viewport": width, "case": "unsafe overall placement"})
            assert page.evaluate("window.mountTestState.writes") == 0
            page.close()
    print(f"Footprint cells, X/Z dimensions and collision overlays: {len(observations)} scenarios passed", flush=True)
    return observations


def run_diagnostic_checks(browser, root, screenshots=None):
    # Use the backend's real explanation text, including both languages.
    sys.path.insert(0, str(root))
    from mcbe_editor.i18n import translate
    from mcbe_editor.mount_diagnostics import placement_issue

    cases = [
        ["chunk_data_missing"],
        ["generation_incomplete"],
        ["generation_unconfirmed"],
        ["additional_block_layers", "unsupported_block_format"],
        ["probe_failed"],
    ]
    observations = []
    for locale in ("de", "en"):
        for width in (320, 1440):
            for theme in ("dark", "light", "minecraft"):
                page = browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                create_mount_page(page, root=root, locale=locale)
                page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
                for codes in cases:
                    context = (locale, width, theme, codes)
                    issues = [placement_issue(code) for code in codes]
                    for issue in issues:
                        if issue["code"] != "probe_failed":
                            issue.update(chunks=[{"x": 10, "z": -20}], block_count=9, sample_block={"x": 168, "y": 75, "z": -308})
                    page.evaluate("issues=>window.mountTestState.diagnosticIssues=issues", issues)
                    page.evaluate("window.mountTestController.loadPreview()")
                    page.locator('[data-candidate-id="hinter_dir_4"]').click()
                    reason = translate(issues[0]["message"], locale)
                    assert page.locator("#mountUncheckedReason").inner_text() == reason, context
                    assert translate(issues[0]["hint"], locale) in page.locator(".mount-placement-explanation").inner_text(), context
                    assert_contained_controls(page, context)
                    if screenshots and locale == "de" and codes == ["chunk_data_missing"] and theme != "minecraft":
                        page.locator(".mount-placement-target").screenshot(path=str(screenshots / f"reason-{width}-{theme}.png"))
                    page.locator("#btnMountTechDetails").click()
                    assert page.locator(".mount-placement-issues li").count() == len(issues), context
                    for issue in issues:
                        assert translate(issue["message"], locale) in page.locator(".mount-placement-issues").inner_text(), context
                    observed = assert_dialog_frame(page, context)
                    if screenshots and locale == "de" and codes == ["generation_unconfirmed"] and theme != "minecraft":
                        page.screenshot(path=str(screenshots / f"reason-details-{width}-{theme}.png"))
                    page.keyboard.press("Escape")
                    # The confirmation repeats the reason; cancelling changes nothing.
                    page.locator("#btnMountCreate").click()
                    assert reason in page.evaluate("window.mountTestState.confirms.at(-1)"), context
                    assert page.evaluate("window.mountTestController.getPendingMounts().length") == 0, context
                    page.locator('[data-candidate-id="rechts_4"]').click()
                    assert page.locator("#mountUncheckedReason").count() == 0, (context, "stale reason after safe selection")
                    observations.append(
                        {"locale": locale, "width": width, "theme": theme, "codes": codes, "minContrast": min(item["ratio"] for item in observed["contrast"])}
                    )
                assert not errors, errors
                assert page.evaluate("window.mountTestState.writes") == 0
                page.close()
    print(f"Unchecked reasons, affected chunks, translations and confirmations: {len(observations)} scenarios passed", flush=True)
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--checks", choices=("all", "dialog", "footprint", "diagnostics"), default="all")
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    chromium_path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("chromium-browser")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chromium_path, args=["--no-sandbox"] if os.name == "posix" else [])
        try:
            observations = {}
            if args.checks in ("all", "dialog"):
                observations["dialogs"] = run_dialog_checks(browser, args.root, args.screenshots)
            if args.checks in ("all", "footprint"):
                observations["footprints"] = run_footprint_checks(browser, args.root, args.screenshots)
            if args.checks in ("all", "diagnostics"):
                observations["diagnostics"] = run_diagnostic_checks(browser, args.root, args.screenshots)
            if args.screenshots:
                (args.screenshots / "details-metrics.json").write_text(json.dumps(observations, indent=2), "utf-8")
            print(f"PASS: {sum(len(rows) for rows in observations.values())} focused Mount detail scenarios (synthetic data; no writes)", flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
