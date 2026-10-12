"""Offline browser regression checks for the three editor designs.

Run: python scripts/design_polish_smoke.py
Dependencies: Jinja2 and Python Playwright, plus Chromium (playwright install
chromium or CHROMIUM_PATH). Real templates, CSS, i18n, layout, world-selection
and inventory controllers run with synthetic data. No Bedrock files are opened.
Optional --screenshots DIR captures review images; --capture-only skips asserts.
--root DIR can render an unchanged source archive for before/after comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STYLES = ("style.css", "layout_variants.css", "focus_workspace.css")
SCRIPTS = (
    "i18n.js",
    "html_utils.js",
    "selection_state.js",
    "slot_display.js",
    "slot_interaction_logic.js",
    "inventory_rendering.js",
    "world_cards_view.js",
    "world_status_view.js",
    "world_browser.js",
    "player_view_models.js",
)


def render_template(root=ROOT, locale="de"):
    catalog = json.loads((root / "static/i18n/en.json").read_text("utf-8")) if locale == "en" else {}
    template = Environment(loader=FileSystemLoader(root / "templates"), autoescape=True).get_template("index.html")
    text = template.render(
        app_locale=locale,
        t=lambda value, **params: catalog.get(value, value).format(**params),
        url_for=lambda name, **params: "/static/" + params["filename"] if name == "static" else "/" + name,
        csrf_token="offline-preview",
        i18n_catalog=catalog,
        app_config={
            "mode": "local",
            "auth_enabled": False,
            "distribution": {"kind": "SOURCE", "project_version": "dev", "app_root": "/example"},
            "data_root_status": {"path": "/example"},
        },
    )
    # Keep the genuine translation catalog; app startup/API calls are replaced
    # only by the fixture below. Actual UI controllers are loaded explicitly.
    return re.sub(r"<script\b[^>]*>[\s\S]*?</script>|<link\b[^>]*>", lambda match: match[0] if 'type="application/json"' in match[0] else "", text)


def settle(page):
    """Measure after layout transitions finish, without waiting on spinners."""
    page.evaluate("""async () => {
      const frames = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      await frames();
      await Promise.all(document.getAnimations()
        .filter(animation => Number.isFinite(animation.effect?.getComputedTiming().iterations))
        .map(animation => animation.finished.catch(() => {})));
      await frames();
    }""")


def create_page(page, root=ROOT, locale="de", layout="studio", view="inventory"):
    html = render_template(root, locale)
    page.route(
        "**/*",
        lambda route: route.fulfill(status=200, content_type="text/html", body=html) if route.request.url == "http://mcbe-preview.test/" else route.abort(),
    )
    page.goto("http://mcbe-preview.test/")
    for name in STYLES:
        page.add_style_tag(content=(root / "static" / name).read_text("utf-8"))
    for name in SCRIPTS:
        page.add_script_tag(content=(root / "static" / name).read_text("utf-8"))
    page.evaluate(
        """({layout,view}) => {
      const byId=id=>document.getElementById(id);
      localStorage.setItem('mcbe-inventory-editor:layout',layout);
      document.documentElement.dataset.layout=layout;
      document.documentElement.dataset.theme='dark';
      document.body.dataset.workflowView=view;
      document.body.classList.toggle('app-world-loaded',view!=='world');
      document.body.classList.toggle('app-player-loaded',view==='inventory');
      byId('inventoryContainer').style.display=view==='inventory'?'flex':'none';
      byId('worldPicker').style.display=view==='world'?'block':'none';
      byId('playerInventorySummary').style.display=view==='inventory'?'flex':'none';
      byId('worldName').textContent='Survival – Bergdorf';
      byId('playerSummaryName').textContent='Dennis';
      byId('summaryBadgeInventory').textContent=window.t('Inventar')+' 2/36';
      byId('serverStatusBadge').className='server-status-badge offline';
      byId('serverStatusBadge').textContent=window.t('Server offline');
      byId('statusStackSummary').textContent=window.t('Bereit');
      for(const button of document.querySelectorAll('[data-workflow-view]')){
        button.disabled=view==='world' && !['world','tools'].includes(button.dataset.workflowView);
        button.classList.toggle('active',button.dataset.workflowView===view);
      }
      for(const [id,value] of Object.entries({statPosX:'168',statPosY:'76',statPosZ:'-312',
          statHealth:'20',statFoodLevel:'20',statXpLevel:'37',statGamemode:'Survival'})) {
        if(byId(id))byId(id).value=value;
      }
      byId('playersList').replaceChildren(...['Dennis','Alex','Steve'].map((label,index)=>
        window.MCBEPlayerViewModels.playerRowElement(window.MCBEPlayerViewModels.playerRowModel({
          label,player_key:'synthetic-'+index,kind:index===0?'local':'remote',editable:true,
        },'synthetic-0'))));
      const state={slots:[],ender:-1,selected:null,rendered:[],worlds:[]};
      const inventory={15:{name:'minecraft:diamond_sword',count:1,damage:0,enchantments:[]},
        17:{name:'minecraft:diamond',count:32,damage:0,enchantments:[]}};
      window.polishTestState=state;
      window.polishInventory=inventory;
      window.polishGrid=window.MCBEInventoryRendering.createInventoryGridController({
        doc:document,elements:window.MCBEInventoryRendering.collectInventoryGridElements(document),
        getInventory:()=>inventory,getSelectedSlots:()=>state.slots,getSelectedEnderSlot:()=>state.ender,
        setSelectedSlots:slots=>{state.slots=slots;},setSelectedEnderSlot:slot=>{state.ender=slot;},
        getWorldPath:()=>view==='world'?'':'/synthetic/survival',
        slotDisplayName:window.MCBESlotDisplay.slotDisplayName,
        buildSlotTooltipLines:(slot,container)=>[window.MCBESlotDisplay.slotAreaLabel(slot,container)],
        loadSingleSlotEditor:slot=>{
          byId('detailSlotNum').textContent=String(slot);
          byId('detailItemId').value=inventory[slot]?.name||'';
          byId('detailCount').value=inventory[slot]?.count||1;
          byId('detailDamage').value=0;
        },
        rendererDeps:{
          buildSlotTooltipLines:(slot,container)=>[window.MCBESlotDisplay.slotAreaLabel(slot,container)],
          getItemEmoji:name=>name.includes('sword')?'⚔️':name.includes('helmet')?'🪖':'💎',
          getItemIconMeta:()=>null,getMaxDamage:()=>0,isKnownItemId:()=>true,
          itemNamesForId:name=>[name,name],itemRequiresOriginalNbt:()=>false,
          isProtectedKnownSlot:()=>false,isSlotSelected:window.MCBESelectionState.isSlotSelected,
          showSlotNumbers:()=>true,slotAreaLabel:window.MCBESlotDisplay.slotAreaLabel,
        },
      });
      window.polishGrid.buildGrids();window.polishGrid.wireControls();
      window.polishGrid.updateGridVisuals();window.polishGrid.updateSelectionUI();
      const selectedElements={bar:byId('selectedWorldBar'),kicker:byId('selectedWorldKicker'),
        name:byId('selectedWorldName'),path:byId('selectedWorldPath'),safetyNote:byId('selectedWorldSafetyNote'),
        loadButton:byId('btnLoad'),copyButton:byId('btnCopySelectedWorldPath'),openButton:byId('btnOpenSelectedWorld')};
      const selectWorld=selected=>{
        state.selected=selected;
        window.MCBEWorldStatusView.applySelectedWorldBarModel(selectedElements,
          window.MCBEWorldStatusView.selectedWorldBarModel({selectedWorld:selected}));
      };
      window.polishSelectWorld=selectWorld;
      window.polishWorlds=window.MCBEWorldBrowser.createWorldBrowserController({
        elements:{worldList:byId('worldList'),worldPicker:byId('worldPicker'),countHint:byId('worldCountHint'),
          scanEmpty:byId('worldScanEmpty'),searchInput:byId('worldSearchInput'),sortSelect:byId('worldSortSelect')},
        getLastWorldScan:()=>({worlds:state.worlds}),getLastRenderedWorlds:()=>state.rendered,
        setLastRenderedWorlds:worlds=>{state.rendered=worlds;},getSelectedWorld:()=>state.selected,
        updateSelectedWorld:selectWorld,
      });
      window.polishShowWorlds=count=>{
        state.worlds=Array.from({length:count},(_,index)=>({name:['Survival – Bergdorf','Kreativwelt','Nether-Projekt'][index%3],
          path:'/worlds/'+index,folder:'Welt-'+index,source_kind:'minecraft-default',source_label:window.t('Minecraft-Standardordner')}));
        window.polishWorlds.renderWorldCards(state.worlds);
      };
      window.polishShowWorlds(12);
      selectWorld(view==='world'?null:{name:'Survival – Bergdorf',path:'/synthetic/survival',
        folder:'Survival',source_label:window.t('Minecraft-Standardordner')});
    }""",
        {"layout": layout, "view": view},
    )
    for name in ("layout_controller.js", "focus_workspace.js"):
        page.add_script_tag(content=(root / "static" / name).read_text("utf-8"))
    settle(page)


def metrics(page):
    return page.evaluate("""() => {
      const box=selector=>{
        const el=document.querySelector(selector);if(!el)return null;
        const r=el.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};
      };
      return {pageOverflow:document.documentElement.scrollWidth-innerWidth,
        pageRange:document.documentElement.scrollHeight-innerHeight,
        firstSlot:box('.main-inventory-grid .inventory-slot'),editor:box('#detailEditorPanel'),
        multi:box('#multiSelectPanel'),title:box('.logo'),commands:box('.focus-command-bar'),
        worldList:box('#worldList'),workspace:box('.workspace')};
    }""")


def overlap(a, b):
    return min(a["right"], b["right"]) - max(a["x"], b["x"]) > 1 and min(a["bottom"], b["bottom"]) - max(a["y"], b["y"]) > 1


def capture(browser, root, output):
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for layout in ("studio", "focus"):
        for width, height in ((1600, 960), (1200, 800), (390, 900)):
            page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
            create_page(page, root, layout=layout)
            summary.append({"layout": layout, "width": width, **metrics(page)})
            page.screenshot(path=str(output / f"{layout}_inventory_{width}.png"), full_page=width == 390)
            if width == 1600:
                page.locator('.main-inventory-grid [data-slot="15"]').click()
                page.screenshot(path=str(output / f"{layout}_selected_{width}.png"))
            page.close()
        page = browser.new_page(viewport={"width": 1600, "height": 960}, reduced_motion="reduce")
        create_page(page, root, layout=layout, view="world")
        page.screenshot(path=str(output / f"{layout}_worlds_1600.png"))
        summary.append({"layout": layout, "view": "world", "width": 1600, **metrics(page)})
        page.close()
    (output / "metrics.json").write_text(json.dumps(summary, indent=2), "utf-8")
    print(f"Screenshots: {output}")


def run_checks(browser, root):
    checks = 0
    # Empty, normal and enchanted equipment must have one readable label and
    # a separate glint. Real rendering removes title attributes as it does in app.
    for locale in ("de", "en"):
        for layout in ("classic", "studio", "focus"):
            page = browser.new_page(viewport={"width": 1600, "height": 960}, reduced_motion="reduce")
            create_page(page, root, locale, layout)
            for theme in ("dark", "light", "minecraft"):
                page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
                for state in ("empty", "normal", "enchanted"):
                    page.evaluate(
                        """state=>{
                      for(const slot of [100,101,102,103,-106]){
                        if(state==='empty')delete window.polishInventory[slot];
                        else window.polishInventory[slot]={name:'minecraft:diamond_helmet',count:1,damage:0,
                          enchantments:state==='enchanted'?[{id:0,lvl:1}]:[]};
                      }
                      window.polishGrid.updateGridVisuals();
                    }""",
                        state,
                    )
                    observed = page.evaluate("""()=>[...document.querySelectorAll('.armor-slot,.offhand-slot')].map(slot=>{
                      const label=slot.querySelector('.studio-equipment-label,.equipment-label');
                      const css=label&&getComputedStyle(label),r=label?.getBoundingClientRect();
                      const before=getComputedStyle(slot,'::before');
                      return {label:label?.textContent.trim(),visible:!!r?.width&&!!r?.height&&css?.display!=='none'&&css?.visibility!=='hidden',
                        duplicate:!['none','normal','""',''].includes(before.content)&&before.display!=='none',
                        enchanted:slot.classList.contains('enchanted'),
                        glint:before.display!=='none'&&before.backgroundImage!=='none'&&before.pointerEvents==='none'};
                    })""")
                    assert len(observed) == 5 and all(item["visible"] and item["label"] and not item["duplicate"] for item in observed), (
                        locale,
                        layout,
                        theme,
                        state,
                        observed,
                    )
                    assert all(item["enchanted"] == (state == "enchanted") for item in observed), (locale, layout, state, observed)
                    if state == "enchanted":
                        assert all(item["glint"] for item in observed), (locale, layout, theme, observed)
                    assert observed[0]["label"] == ("Helmet" if locale == "en" else "Helm"), (locale, observed)
                    checks += 1
            page.close()
    print(f"Equipment: {checks} translated empty/normal/enchanted scenarios passed", flush=True)

    # The exact breakpoint interval previously placed the inspector below the
    # grid but disabled the scroll assistance. Use real pointer and Ctrl clicks.
    for locale in ("de", "en"):
        for layout in ("studio", "focus"):
            widths = (390, 760, 1180, 1181, 1200, 1279, 1280, 1320, 1321, 1600)
            for width in widths:
                page = browser.new_page(viewport={"width": width, "height": 900 if width == 390 else 800}, reduced_motion="reduce")
                create_page(page, root, locale, layout)
                before = metrics(page)
                assert before["pageOverflow"] <= 1, (locale, layout, width, before)
                if layout == "focus":
                    assert not overlap(before["title"], before["commands"]), (locale, layout, width, before)
                if width == 390:
                    assert before["firstSlot"]["width"] >= 43.5, ("click target", locale, layout, before)
                    assert before["firstSlot"]["y"] < 950, ("inventory access", locale, layout, before)
                page.locator('.main-inventory-grid [data-slot="15"]').click()
                page.wait_for_function("getComputedStyle(document.getElementById('detailEditorPanel')).display!=='none'")
                if width < (1280 if layout == "focus" else 1181):
                    page.wait_for_function(
                        """() => {const r=document.getElementById('detailEditorPanel').getBoundingClientRect();return r.top>=-1 && r.top<innerHeight-80;}""",
                        timeout=2000,
                    )
                assert page.locator("#detailSlotNum").inner_text() == "15"
                assert page.locator("#studioInspectorStandby").is_hidden(), (locale, layout, width)
                assert page.locator("#multiSelectPanel").is_hidden(), (locale, layout, width)
                if width == 1600:
                    desired = "Description (lore – one line per entry)" if locale == "en" else "Beschreibung (Lore – eine Zeile pro Eintrag)"
                    assert page.locator('label[for="detailLore"]').inner_text() == desired
                    page.locator("#detailLore").fill("\n".join(f"Lore {number}" for number in range(60)))
                    lore = page.evaluate("""()=>{
                      const el=document.getElementById('detailLore');el.style.height='220px';el.scrollTop=10000;
                      const box=el.getBoundingClientRect(),panel=document.getElementById('detailEditorPanel').getBoundingClientRect();
                      return {scroll:el.scrollTop,range:el.scrollHeight-el.clientHeight,width:box.width,panelWidth:panel.width};
                    }""")
                    assert lore["scroll"] > 0 and lore["range"] > 0 and lore["width"] <= lore["panelWidth"], (locale, layout, lore)
                page.locator('.main-inventory-grid [data-slot="17"]').click(modifiers=["Control"])
                if width < (1280 if layout == "focus" else 1181):
                    page.wait_for_function(
                        """() => {const r=document.getElementById('multiSelectPanel').getBoundingClientRect();return r.top>=-1 && r.top<innerHeight-80;}""",
                        timeout=2000,
                    )
                assert page.locator("#detailEditorPanel").is_hidden()
                assert page.locator("#multiSelectPanel").is_visible()
                checks += 1
                page.close()
    print(f"Selection: {checks} cumulative scenarios passed", flush=True)

    for locale in ("de", "en"):
        for width, height in ((1366, 900), (1440, 900), (1600, 960), (1920, 1080)):
            page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
            create_page(page, root, locale, "studio", "world")
            before = metrics(page)
            assert before["pageRange"] <= 1 and before["pageOverflow"] <= 1, (locale, width, height, before)
            assert page.locator("#btnLoad").is_disabled()
            page.locator("#worldList .world-card").first.click()
            after = metrics(page)
            assert abs(before["worldList"]["y"] - after["worldList"]["y"]) <= 1, ("selection shifts list", locale, width, before, after)
            assert page.locator("#btnLoad").is_enabled()
            page.evaluate("window.polishShowWorlds(80)")
            observed = page.evaluate("""()=>{
              const l=document.getElementById('worldList');l.scrollTop=600;
              const group=l.querySelector('.world-source-group'),card=group.querySelector('.world-card');
              return {range:l.scrollHeight-l.clientHeight,top:l.scrollTop,
                width:card.getBoundingClientRect().width,groupWidth:group.getBoundingClientRect().width,
                page:document.documentElement.scrollHeight-innerHeight};
            }""")
            assert observed["range"] > 0 and observed["top"] > 0 and observed["page"] <= 1, (locale, width, observed)
            assert abs(observed["width"] - observed["groupWidth"]) <= 2, (locale, width, observed)
            checks += 1
            page.close()

    # Focus reserves the load action and sizes results from the remaining
    # desktop height. Long names, source groups and narrow screens still reflow.
    for locale in ("de", "en"):
        page = browser.new_page(viewport={"width": 1984, "height": 1100}, reduced_motion="reduce")
        create_page(page, root, locale, "focus", "world")
        page.evaluate("""() => {
          window.polishShowWorlds(28);
          window.polishTestState.worlds.forEach((world,index)=>{
            world.name += ' – Eine große Landschaft mit einem langen Namen und mehreren Gebäuden';
            world.folder = 'world-folder-'.repeat(12) + index;
            if(index>=14){world.source_kind='configured-root';world.source_label=window.t('Konfigurierter Welt-Root');}
          });
          window.polishWorlds.renderWorldCards(window.polishTestState.worlds);
        }""")
        for width, height in ((1984, 1100), (1440, 900), (1181, 900), (1180, 800), (1030, 768), (1024, 768), (760, 900), (390, 844), (320, 740)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("dark", "light", "minecraft"):
                page.evaluate("theme=>{document.documentElement.dataset.theme=theme;window.polishSelectWorld(null);window.scrollTo(0,0);}", theme)
                settle(page)
                before = metrics(page)
                page.evaluate("window.polishSelectWorld(window.polishTestState.worlds[0])")
                settle(page)
                after = metrics(page)
                assert after["pageOverflow"] <= 1, ("Focus world width", locale, theme, width, after)
                assert after["workspace"]["width"] <= 1540, (locale, theme, width, after)
                if width >= 1181 and height >= 900:
                    assert after["pageRange"] <= 1, ("Focus world height", locale, theme, width, after)
                if width >= 1025:
                    assert abs(before["worldList"]["y"] - after["worldList"]["y"]) <= 1, ("Focus selection shifts list", locale, theme, width, before, after)
                    assert page.locator("#btnLoad").evaluate("el=>el.getBoundingClientRect().bottom") < after["worldList"]["y"]
                checks += 1
        page.close()

    # Classic's narrow desktop track previously widened the page through the
    # player header and transfer summaries. Exercise both collapsed and expanded.
    for locale in ("de", "en"):
        for width in (390, 1181, 1200, 1320):
            page = browser.new_page(viewport={"width": width, "height": 800}, reduced_motion="reduce")
            create_page(page, root, locale, "classic", "player")
            for expanded in (False, True):
                page.evaluate("expanded=>document.querySelectorAll('#playerManager details').forEach(el=>el.open=expanded)", expanded)
                assert metrics(page)["pageOverflow"] <= 1, (locale, "classic", width, expanded, metrics(page))
                page.evaluate("window.scrollTo(999,0)")
                assert page.evaluate("scrollX") == 0, (locale, "classic", width, expanded)
                checks += 1
            page.close()

    for locale in ("de", "en"):
        for layout in ("studio", "focus"):
            page = browser.new_page(viewport={"width": 1600, "height": 960}, reduced_motion="reduce")
            create_page(page, root, locale, layout)
            if layout == "focus":
                page.locator("#focusPlayerSearch").fill("no-such-player-123")
                assert page.locator("#focusPlayerSearchEmpty").is_visible()
                assert page.locator("#focusPlayerListMount .player-row:visible").count() == 0
                page.locator("#focusPlayerSearch").fill("Dennis")
                assert page.locator("#focusPlayerSearchEmpty").is_hidden()
                assert page.locator("#focusPlayerListMount .player-row:visible").count() == 1
            page.evaluate("""()=>{
              const presence=document.getElementById('worldPresenceBanner');presence.style.display='flex';presence.textContent='World presence warning';
              const error=document.getElementById('loadErrorPanel');error.style.display='block';error.textContent='World load warning';
            }""")
            assert page.locator("#worldPresenceBanner").is_visible() and page.locator("#loadErrorPanel").is_visible(), (locale, layout)
            checks += 1
            page.close()
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--capture-only", action="store_true")
    args = parser.parse_args()
    chromium_path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("chromium-browser")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chromium_path, args=["--no-sandbox"] if os.name == "posix" else [])
        try:
            if args.screenshots:
                capture(browser, args.root, args.screenshots)
            if not args.capture_only:
                checks = run_checks(browser, args.root)
                print(f"PASS: {checks} design regression scenarios (real UI controllers; synthetic data)")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
