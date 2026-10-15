"""Offline browser regression for equipment editing, Lore and long world lists.

Runs the real template, styles, inventory/slot-detail, write-control, world-card
and layout controllers with synthetic data. Folder calls are intercepted: no
real file manager, Bedrock world or write endpoint is used.

Requires Jinja2, Python Playwright and Chromium (CHROMIUM_PATH).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from design_polish_smoke import ROOT, STYLES, render_template, settle
from playwright.sync_api import sync_playwright

MODULES = (
    "i18n.js",
    "html_utils.js",
    "selection_state.js",
    "slot_display.js",
    "equipment_rules.js",
    "slot_interaction_logic.js",
    "inventory_state.js",
    "item_catalog.js",
    "enchantment_editor_logic.js",
    "enchantments_view.js",
    "entity_variant_editor.js",
    "slot_detail_logic.js",
    "inventory_rendering.js",
    "workflow_state.js",
    "write_status_view.js",
    "ui_feedback.js",
    "world_cards_view.js",
    "world_status_view.js",
    "world_browser.js",
    "player_view_models.js",
)

FIXTURE = r"""({layout,view}) => {
  const el=id=>document.getElementById(id);
  localStorage.setItem('mcbe-inventory-editor:layout',layout);
  document.documentElement.dataset.layout=layout;
  document.documentElement.dataset.theme='dark';
  document.body.dataset.workflowView=view;
  document.body.classList.toggle('app-world-loaded',view!=='world');
  document.body.classList.toggle('app-player-loaded',view==='inventory');
  el('inventoryContainer').style.display=view==='inventory'?'flex':'none';
  el('worldPicker').style.display=view==='world'?'block':'none';
  el('playerInventorySummary').style.display=view==='inventory'?'flex':'none';
  el('worldName').textContent='Survival – Bergdorf';
  el('playerSummaryName').textContent='Dennis';
  el('toggleSlotNumbers').checked=true;
  el('serverStatusBadge').className='server-status-badge offline';
  el('serverStatusBadge').textContent=t('Server offline');
  el('statusStackSummary').textContent=t('Bereit');
  for(const button of document.querySelectorAll('[data-workflow-view]')) {
    button.disabled=view==='world'&&!['world','tools'].includes(button.dataset.workflowView);
    button.classList.toggle('active',button.dataset.workflowView===view);
  }
  for(const [id,value] of Object.entries({statPosX:'90.5',statPosY:'71.6',statPosZ:'89.9',
      statHealth:'20',statFoodLevel:'20',statXpLevel:'37',statGamemode:'Survival'})) {
    if(el(id))el(id).value=value;
  }
  el('playersList').replaceChildren(...['Dennis','Alex'].map((label,index)=>
    MCBEPlayerViewModels.playerRowElement(MCBEPlayerViewModels.playerRowModel({
      label,player_key:'synthetic-'+index,kind:index===0?'local':'remote',editable:true,
    },'synthetic-0'))));
  const names={103:'diamond_helmet',102:'diamond_chestplate',101:'diamond_leggings',
    100:'diamond_boots','-106':'shield',9:'diamond_sword',17:'diamond'};
  const inventory=Object.fromEntries(Object.entries(names).map(([slot,name])=>[slot,{
    slot:Number(slot),name:'minecraft:'+name,count:1,damage:0,display_name:'',
    lore:['Vorhandene Beschreibung','Zweite Zeile'],enchantments:[],
  }]));
  const state={slots:[],ender:-1,filter:'',blocked:false,dirty:false,undo:0,loads:0,
    editorLoads:0,toasts:[],logs:[],api:[],folderMode:'success',worlds:[],rendered:[],selected:null};
  window.revisionState=state;window.revisionInventory=inventory;
  const itemDb=Object.fromEntries(Object.values(names).map(name=>['minecraft:'+name,[name,name]]));
  const catalog=MCBEItemCatalog.createItemCatalog({getItemsDb:()=>itemDb,
    getCompatItemAliases:()=>({}),getItemIconIndex:()=>({}),
    getStackLimits:()=>Object.fromEntries(Object.keys(itemDb).map(name=>[name,1])),
    getMaxDamageMap:()=>({__default__:500}),getEnchantmentCompatibility:()=>({}),
    itemIdRe:/^[a-z0-9_.-]+:[a-z0-9_./-]+$/,defaultMaxDamage:0,maxBedrockStackCount:127});
  const selection=()=>({selectedSlots:state.slots,selectedEnderSlot:state.ender});
  const toast=(message,type,ms)=>{
    state.toasts.push({message,type,ms});return MCBEUiFeedback.showToast(message,type,ms);
  };
  const log=(message,type)=>state.logs.push({message,type});
  const syncControls=()=>{
    const controls=MCBEWriteStatusView.collectWriteGateElements(document);
    MCBEWriteStatusView.applyWriteControlModel({...controls,editControls:controls.editControls()},
      MCBEWriteStatusView.writeControlModel({blocked:state.blocked,hasEditablePlayer:true,
        blockedReason:'Nur lesen',isDirty:state.dirty}));
  };
  window.revisionSetBlocked=blocked=>{state.blocked=blocked;syncControls();};
  const tabs=MCBEWorkflowState.createConfiguredSlotTabController({doc:document});tabs.wire();
  let grid;
  const detail=MCBESlotDetailLogic.createInventorySlotDetailController({doc:document,itemCatalog:catalog,
    state:{getInventory:()=>inventory,getEnderChestInventory:()=>({}),
      getCurrentSelectionState:selection,getCurrentPlayerKey:()=> 'synthetic-0',
      getWorldPath:()=>'/synthetic/survival',getEnchantmentsDb:()=>({})},
    helpers:{isProtectedKnownSlot:()=>false,itemRequiresOriginalNbt:()=>false,
      itemHasInspectableNbt:()=>false,itemHasRepairableDamage:item=>item?.damage>0,
      switchTab:id=>tabs.switchTo(id),slotDisplayName:MCBESlotDisplay.slotDisplayName,
      detailItemLabel:(name,custom)=>custom||name,pushUndo:()=>state.undo++,
      updateGridVisuals:()=>grid.updateGridVisuals(),setDirty:dirty=>{state.dirty=dirty;},
      editingBlocked:()=>state.blocked,getEditingBlockedReason:()=> 'Nur lesen',
      syncEditControls:syncControls,logStatus:log,recordAction:()=>{},showToast:toast}});
  grid=MCBEInventoryRendering.createConfiguredInventoryGridController({doc:document,itemCatalog:catalog,
    state:{getInventory:()=>inventory,getEnderChestInventory:()=>({}),
      getSelectedSlots:()=>state.slots,getSelectedEnderSlot:()=>state.ender,
      setSelectedSlots:value=>{state.slots=value;},setSelectedEnderSlot:value=>{state.ender=value;},
      getGridFilter:()=>state.filter,setGridFilter:value=>{state.filter=value;},
      getWorldPath:()=>view==='world'?'':'/synthetic/survival',getCurrentPlayerKey:()=> 'synthetic-0'},
    renderer:{buildSlotTooltipLines:(slot,container)=>[MCBESlotDisplay.slotAreaLabel(slot,container)],
      slotAreaLabel:MCBESlotDisplay.slotAreaLabel,slotDisplayName:MCBESlotDisplay.slotDisplayName},
    helpers:{getInventoryViewPreferences:()=>({getShowSlotNumbers:()=>true}),
      itemRequiresOriginalNbt:()=>false,isProtectedKnownSlot:()=>false,itemIsVisiblePresent:item=>Boolean(item),
      ensureItemOrigin:item=>item,pushUndo:()=>state.undo++,setDirty:dirty=>{state.dirty=dirty;},
      guardEditingAction:()=>state.blocked,
      loadSingleSlotEditor:(slot,ender)=>{state.editorLoads++;detail.loadSingleSlotEditor(slot,ender);}}});
  window.revisionGrid=grid;window.revisionDetail=detail;
  grid.buildGrids();grid.wireControls();detail.wire();grid.updateGridVisuals();grid.updateSelectionUI();
  const responsive=MCBEWorkflowState.createResponsivePanelController({doc:document,win:window,
    leftPanel:document.querySelector('.left-panel'),rightPanel:document.querySelector('.right-panel'),
    panelToggles:document.querySelectorAll('.btn-toggle')});
  responsive.wire();responsive.activateForWorkflow(view);
  const selectedElements={bar:el('selectedWorldBar'),kicker:el('selectedWorldKicker'),
    name:el('selectedWorldName'),path:el('selectedWorldPath'),safetyNote:el('selectedWorldSafetyNote'),
    loadButton:el('btnLoad'),copyButton:el('btnCopySelectedWorldPath'),openButton:el('btnOpenSelectedWorld')};
  const selectWorld=selected=>{
    state.selected=selected;
    MCBEWorldStatusView.applySelectedWorldBarModel(selectedElements,
      MCBEWorldStatusView.selectedWorldBarModel({selectedWorld:selected}));
  };
  window.revisionSelectWorld=selectWorld;
  window.fetch=async(url,options)=>{
    if(url!=='/api/open_folder')throw Error('Unexpected API: '+url);
    state.api.push({url,payload:JSON.parse(options.body)});
    if(state.folderHold)await new Promise(resolve=>{window.revisionReleaseFolder=resolve;});
    if(state.folderMode==='network')throw Error('Offline');
    return {ok:state.folderMode!=='httpFailure',json:async()=>state.folderMode==='failure'
      ?{success:false,error:'Ordner fehlt'}:{success:true,foreground_requested:false}};
  };
  const worlds=MCBEWorldBrowser.createInventoryWorldBrowserController({doc:document,
    getLastWorldScan:()=>({worlds:state.worlds}),getLastRenderedWorlds:()=>state.rendered,
    setLastRenderedWorlds:worlds=>{state.rendered=worlds;},getSelectedWorld:()=>state.selected,
    updateSelectedWorld:selectWorld,logStatus:log,showToast:toast,withCsrf:()=>({'X-CSRFToken':'fixture'}),
    loadWorldFromInput:()=>{state.loads++;state.loadedPath=state.selected?.path;}});
  worlds.wire();window.revisionWorlds=worlds;
  window.revisionShowWorlds=count=>{
    state.worlds=Array.from({length:count},(_,index)=>({name:'Welt '+String(index+1).padStart(3,'0'),
      path:'/worlds/'+index,folder:'Welt-'+index,source_kind:'minecraft-default',
      source_label:t('Minecraft-Standardordner'),modified_ts:1700000000-index}));
    worlds.renderFilteredWorlds();
  };
  window.revisionShowWorlds(100);
  selectWorld(view==='world'?null:{name:'Survival – Bergdorf',path:'/synthetic/survival',
    source_label:t('Minecraft-Standardordner')});
}"""


def create_page(page, root=ROOT, *, layout="focus", view="inventory", locale="de"):
    html = render_template(root, locale)
    page.route(
        "**/*",
        lambda route: route.fulfill(status=200, content_type="text/html", body=html) if route.request.url == "http://mcbe-preview.test/" else route.abort(),
    )
    page.goto("http://mcbe-preview.test/")
    for name in STYLES:
        page.add_style_tag(content=(root / "static" / name).read_text("utf-8"))
    for name in MODULES:
        page.add_script_tag(content=(root / "static" / name).read_text("utf-8"))
    page.evaluate(FIXTURE, {"layout": layout, "view": view})
    for name in ("layout_controller.js", "focus_workspace.js"):
        page.add_script_tag(content=(root / "static" / name).read_text("utf-8"))
    settle(page)


def equipment_state(page):
    return page.evaluate("""()=>{
      const box=element=>{const r=element.getBoundingClientRect();return {x:r.x,y:r.y,
        width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
      const slots=[...document.querySelectorAll('.armor-slot,.offhand-slot')];
      const editor=document.getElementById('detailEditorPanel'),lore=document.getElementById('detailLore');
      const loreStyle=getComputedStyle(lore),loreBox=box(lore),equipment=box(slots[0].closest('.armor-offhand-layout'));
      const quickGap=box(document.querySelector('.slot-quick-buttons')).y-box(document.getElementById('slotQuickSubtitle')).bottom;
      const ids=[...document.querySelectorAll('[id]')].map(node=>node.id);
      return {slots:slots.map(node=>({slot:Number(node.dataset.slot),visible:node.checkVisibility(),
          selected:node.classList.contains('selected'),width:box(node).width,height:box(node).height})),
        editorVisible:editor.checkVisibility(),equipment,inventory:box(document.querySelector('.main-inventory-grid')),
        lore:loreBox,loreResize:loreStyle.resize,loreOverflow:loreStyle.overflowY,
        editor:box(editor),selection:revisionState.slots,editorLoads:revisionState.editorLoads,
        duplicates:ids.filter((id,index)=>ids.indexOf(id)!==index),
        quickGap,viewportWidth:innerWidth,pageOverflow:document.documentElement.scrollWidth-innerWidth};
    }""")


def assert_equipment(page, context, *, selected=None, above=False):
    current = equipment_state(page)
    assert len(current["slots"]) == 5 and all(slot["visible"] for slot in current["slots"]), (context, current)
    assert current["pageOverflow"] <= 1 and not current["duplicates"], (context, current)
    assert all(slot["width"] >= 40 and slot["height"] >= 40 for slot in current["slots"]), (context, current)
    if above:
        assert current["equipment"]["bottom"] < current["inventory"]["y"], (context, current)
    if selected is not None:
        assert current["editorVisible"] and current["selection"] == [selected], (context, current)
        assert current["lore"]["height"] >= 90, (context, current)
        assert 0 < current["lore"]["width"] <= current["editor"]["width"], (context, current)
        assert current["loreResize"] == "vertical" and current["loreOverflow"] == "auto", (context, current)
        if current["viewportWidth"] <= 820:
            assert current["quickGap"] <= 24, (context, current)
    return current


def check_equipment(browser, root, screenshots=None):
    checks = 0
    scenarios = [
        (1780, 1100, "dark", "de"),
        (1440, 900, "light", "en"),
        (920, 700, "system", "de"),
        (390, 844, "dark", "de"),
        (320, 568, "light", "en"),
        (1440, 600, "minecraft", "de"),
    ]
    for width, height, theme, locale in scenarios:
        print(f"  Checking equipment: {width}×{height}, {theme}, {locale}", flush=True)
        errors = []
        page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce", color_scheme="light")
        page.on("pageerror", lambda error, target=errors: target.append(str(error)))
        create_page(page, root, locale=locale)
        page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
        context = (width, height, theme, locale)
        assert_equipment(page, context, above=True)
        initial_loads = page.evaluate("revisionState.editorLoads")
        # All equipped items and offhand use the genuine slot click -> selection
        # -> editor -> form -> apply path; no manual editor display toggles.
        for offset, slot in enumerate((103, 102, 101, 100, -106)):
            page.locator(f'.inventory-slot[data-slot="{slot}"]').click()
            settle(page)
            current = assert_equipment(page, context + (slot,), selected=slot, above=True)
            assert current["editorLoads"] == initial_loads + offset + 1, (context, current)
            assert page.locator("#detailItemSearch").input_value() == page.evaluate("slot=>revisionInventory[slot].name", slot)
            page.locator("#detailLore").fill(f"Feld {slot}\nZweite Zeile\nDritte Zeile")
            page.locator("#btnApplySingle").click()
            assert page.evaluate("slot=>revisionInventory[slot].lore", slot) == [f"Feld {slot}", "Zweite Zeile", "Dritte Zeile"]
            assert page.evaluate("revisionState.undo") == offset + 1
        checks += 1
        page.locator('.main-inventory-grid [data-slot="9"]').click()
        page.locator("#detailCustomName").fill("Inventar bleibt editierbar")
        page.locator("#btnApplySingle").click()
        assert page.evaluate("revisionInventory[9].display_name") == "Inventar bleibt editierbar"
        page.locator('.inventory-slot[data-slot="103"]').click()
        assert page.locator("#detailLore").input_value() == "Feld 103\nZweite Zeile\nDritte Zeile"
        page.locator("#detailLore").fill("\n".join(f"Lange Beschreibung {index}" for index in range(60)))
        page.evaluate("()=>{const el=document.getElementById('detailLore');el.style.height='240px';el.scrollTop=el.scrollHeight;}")
        assert page.locator("#detailLore").evaluate("el=>el.scrollTop>0&&el.scrollHeight>el.clientHeight")
        assert_equipment(page, context, selected=103, above=True)
        checks += 1
        # Moving the original nodes between layouts must preserve identity,
        # selection and the exact number of click handlers.
        page.evaluate("window.revisionOriginalEquipment=[...document.querySelectorAll('.armor-slot,.offhand-slot')]")
        for layout in ("classic", "studio", "focus"):
            page.locator("#layoutSelect").evaluate("(el,layout)=>{el.value=layout;el.dispatchEvent(new Event('change',{bubbles:true}));}", layout)
            settle(page)
            if layout == "classic" and width <= 1024:
                page.locator('.btn-toggle[data-panel="left"]').click()
            before = page.evaluate("revisionState.editorLoads")
            page.locator('.inventory-slot[data-slot="102"]').click()
            settle(page)
            assert page.evaluate("revisionState.editorLoads") == before + 1
            assert page.evaluate("revisionOriginalEquipment.every(node=>node.isConnected)")
            assert page.locator('.inventory-slot[data-slot="102"]').count() == 1
        assert_equipment(page, context, selected=102, above=True)
        checks += 1
        # The genuine edit-control layer disables fields, while the actual
        # slot-detail guard also rejects a direct apply callback in read-only.
        page.evaluate("revisionSetBlocked(true)")
        before = page.evaluate("JSON.stringify(revisionInventory)")
        page.locator('.inventory-slot[data-slot="100"]').click()
        settle(page)
        assert page.locator("#detailLore").is_disabled() and page.locator("#btnApplySingle").is_disabled()
        page.evaluate("()=>{document.getElementById('detailLore').value='Muss blockiert bleiben';revisionDetail.applyCurrentSingleSlot();}")
        assert page.evaluate("JSON.stringify(revisionInventory)") == before
        assert_equipment(page, context, selected=100, above=True)
        page.evaluate("revisionSetBlocked(false)")
        assert page.locator("#detailLore").is_enabled() and page.locator("#btnApplySingle").is_enabled()
        assert not errors, (context, errors)
        checks += 1
        if screenshots and width in (1780, 390):
            screenshots.mkdir(parents=True, exist_ok=True)
            page.evaluate(
                "()=>{revisionGrid.clearSelection();revisionGrid.hideSlotHover();document.querySelectorAll('.toast').forEach(el=>el.remove());document.getElementById('detailLore').style.height='';scrollTo(0,0);}"
            )
            page.mouse.move(0, 0)
            settle(page)
            page.screenshot(path=str(screenshots / f"focus_equipment_{width}.png"), full_page=width == 390)
            page.locator('.inventory-slot[data-slot="103"]').click()
            page.locator("#detailLore").fill("Schutz für die nächste Reise\nFür Ausflüge ins Bergdorf\nUnverwechselbar")
            page.mouse.move(0, 0)
            page.evaluate("revisionGrid.hideSlotHover()")
            if width > 1279:
                page.evaluate("scrollTo(0,0)")
            settle(page)
            page.screenshot(path=str(screenshots / f"focus_editor_{width}.png"), full_page=width == 390)
        print(f"  Equipment: {width}×{height}, {theme}, {locale} passed", flush=True)
        page.close()
    return checks


def world_metrics(page):
    return page.evaluate("""()=>{
      const list=document.getElementById('worldList'),load=document.getElementById('btnLoad'),
        r=list.getBoundingClientRect(),button=load.getBoundingClientRect();
      return {height:r.height,clientHeight:list.clientHeight,scrollHeight:list.scrollHeight,scrollTop:list.scrollTop,
        top:r.top,bottom:r.bottom,loadTop:button.top,loadBottom:button.bottom,viewport:innerHeight,
        overflowY:getComputedStyle(list).overflowY,tabIndex:list.tabIndex,
        cardCount:list.querySelectorAll('[data-world-path]').length,pageY:scrollY,
        pageRange:document.documentElement.scrollHeight-innerHeight,
        pageOverflow:document.documentElement.scrollWidth-innerWidth};
    }""")


def check_worlds(browser, root, screenshots=None):
    checks = 0
    for layout, width, height in (
        ("classic", 1440, 900),
        ("studio", 1440, 900),
        ("focus", 1780, 1100),
        ("focus", 390, 844),
        ("focus", 320, 568),
        ("studio", 920, 700),
    ):
        page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error, target=errors: target.append(str(error)))
        create_page(page, root, layout=layout, view="world")
        context = (layout, width, height)
        before = world_metrics(page)
        assert before["cardCount"] == 100 and before["scrollHeight"] > before["clientHeight"], (context, before)
        assert before["overflowY"] in ("auto", "scroll") and before["pageOverflow"] <= 1, (context, before)
        assert before["height"] <= max(240, height * 0.6), (context, before)
        assert page.locator("#worldList").get_attribute("role") == "listbox"
        assert page.locator('#worldList [role="option"]').count() == 100
        page.evaluate("revisionShowWorlds(13)")
        thirteen = world_metrics(page)
        assert abs(thirteen["pageRange"] - before["pageRange"]) <= 2, (context, before, thirteen)
        page.evaluate("revisionShowWorlds(100)")
        page.locator('#worldList [data-world-path="/worlds/0"]').click()
        settle(page)
        assert page.locator("#btnLoad").is_enabled()
        page.locator("#btnLoad").click()
        assert page.evaluate("revisionState.loadedPath") == "/worlds/0"
        first = world_metrics(page)
        assert first["scrollTop"] < 2, (context, first)
        # The selected-world action must be outside the scrolling collection.
        assert page.locator("#btnLoad").evaluate("el=>!document.getElementById('worldList').contains(el)")
        page.locator('#worldList [tabindex="0"]').focus()
        page.keyboard.press("PageDown")
        page.wait_for_function("document.getElementById('worldList').scrollTop>0")
        scrolled = world_metrics(page)
        assert scrolled["scrollTop"] > 0, (context, scrolled)
        page.keyboard.press("End")
        settle(page)
        assert page.evaluate("document.activeElement.dataset.worldPath") == "/worlds/99"
        last_scroll = world_metrics(page)["scrollTop"]
        before_loads = page.evaluate("revisionState.loads")
        page.keyboard.press("Enter")
        settle(page)
        assert page.evaluate("revisionState.selected.path") == "/worlds/99"
        assert page.locator('#worldList [aria-selected="true"]').get_attribute("data-world-path") == "/worlds/99"
        assert page.evaluate("document.activeElement.dataset.worldPath") == "/worlds/99"
        assert abs(world_metrics(page)["scrollTop"] - last_scroll) < 2
        assert page.evaluate("revisionState.loads") == before_loads
        assert page.locator('#worldList [tabindex="0"]').count() == 1
        page.keyboard.press("ArrowUp")
        assert page.evaluate("document.activeElement.dataset.worldPath") == "/worlds/98"
        page.keyboard.press("Home")
        assert page.evaluate("document.activeElement.dataset.worldPath") == "/worlds/0"
        page.keyboard.press("ArrowDown")
        assert page.evaluate("document.activeElement.dataset.worldPath") == "/worlds/1"
        page.keyboard.press("Space")
        settle(page)
        assert page.evaluate("revisionState.selected.path") == "/worlds/1"
        page.keyboard.press("Tab")
        assert page.evaluate("!document.getElementById('worldList').contains(document.activeElement)")
        if width == 1780:
            page.evaluate(
                "()=>{revisionState.worlds[40].name='Bergdorf';revisionState.worlds[60].name='Wüste';revisionWorlds.renderWorldCards(revisionState.worlds);}"
            )
            page.locator('#worldList [data-world-path="/worlds/0"]').focus()
            page.keyboard.type("Berg", delay=25)
            assert page.evaluate("document.activeElement.dataset.worldPath") == "/worlds/40"
            page.keyboard.press("Enter")
            assert page.evaluate("revisionState.selected.path") == "/worlds/40"
        checks += 1
        # Filtering away an old scroll offset should reveal the remaining card,
        # and Enter selects its exact identity before focusing the load action.
        page.locator("#worldSearchInput").fill("Welt 100")
        settle(page)
        filtered = world_metrics(page)
        assert filtered["cardCount"] == 1 and filtered["scrollTop"] < 2, (context, filtered)
        page.locator("#worldSearchInput").press("Enter")
        assert page.locator("#btnLoad").evaluate("el=>document.activeElement===el")
        page.locator("#btnLoad").press("Enter")
        assert page.evaluate("revisionState.loadedPath") == "/worlds/99"
        page.locator("#worldSearchInput").fill("keine_treffer")
        assert page.locator("#worldScanEmpty").is_visible()
        page.locator("#worldSearchInput").fill("")
        page.evaluate("revisionShowWorlds(1)")
        one = world_metrics(page)
        assert one["cardCount"] == 1 and one["height"] < before["height"], (context, one, before)
        page.evaluate("revisionShowWorlds(0)")
        assert page.locator("#worldScanEmpty").is_visible()
        assert not errors, (context, errors)
        checks += 1
        if screenshots and layout == "focus" and width in (1780, 390):
            page.evaluate("revisionShowWorlds(100)")
            page.locator('#worldList [data-world-path="/worlds/0"]').click()
            page.evaluate("scrollTo(0,0)")
            settle(page)
            page.screenshot(path=str(screenshots / f"focus_worlds_{width}.png"), full_page=width == 390)
        print(f"  Worlds: {layout}, {width}×{height} passed", flush=True)
        page.close()
    return checks


def check_folder(browser, root):
    page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    create_page(page, root, view="world")
    page.locator('#worldList [data-world-path="/worlds/0"]').click()
    for mode in ("success", "failure", "network", "httpFailure"):
        page.evaluate("mode=>{revisionState.folderMode=mode;revisionState.toasts=[];document.querySelectorAll('.toast').forEach(el=>el.remove());}", mode)
        page.locator("#btnOpenSelectedWorld").click()
        page.wait_for_function("revisionState.toasts.length>0")
        observed = page.evaluate("revisionState.toasts.at(-1)")
        assert observed["type"] == ("info" if mode == "success" else "error"), (mode, observed)
        assert observed["message"], (mode, observed)
        assert page.locator(".toast").last.is_visible()
        assert page.locator(".toast").last.get_attribute("role") == ("status" if mode == "success" else "alert")
        if mode == "success":
            assert observed["ms"] >= 6000 and "Taskleiste" in observed["message"]
        assert page.evaluate("revisionState.api.at(-1).payload.path") == "/worlds/0"
        assert page.locator("#btnOpenSelectedWorld").is_enabled()
    assert page.evaluate("revisionState.api.length") == 4
    page.evaluate("()=>{revisionState.folderMode='success';revisionState.folderHold=true;revisionState.toasts=[];}")
    button = page.locator("#btnOpenSelectedWorld")
    button.click()
    assert button.get_attribute("aria-busy") == "true" and button.get_attribute("aria-disabled") == "true"
    assert "Öffne" in button.inner_text()
    button.dispatch_event("click")
    assert page.evaluate("revisionState.api.length") == 5
    # The selected-world renderer owns native disabled: a late folder response
    # must not re-enable an action whose world selection was cleared meanwhile.
    page.evaluate("document.getElementById('btnOpenSelectedWorld').disabled=true")
    page.evaluate("revisionReleaseFolder()")
    page.wait_for_function("revisionState.toasts.length>0")
    assert button.is_disabled() and button.get_attribute("aria-busy") != "true"
    assert button.get_attribute("aria-disabled") != "true"
    assert button.inner_text() == "Ordner öffnen"
    page.close()
    return 5


def check_followup(browser, root, screenshots=None):
    """Specific regressions found in visual QA, without repeating the matrix."""
    checks = 0
    for layout in ("classic", "studio", "focus"):
        page = browser.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        create_page(page, root, layout=layout)
        if layout == "classic":
            page.locator('.btn-toggle[data-panel="left"]').click()
        page.locator('.inventory-slot[data-slot="103"]').click()
        if layout == "classic":
            page.locator('.btn-toggle[data-panel="right"]').click()
        settle(page)
        current = equipment_state(page)
        assert current["editorVisible"] and 0 <= current["quickGap"] <= 24, (layout, current)
        page.locator("#detailLore").fill("Kompakte Schnellaktionen\nBeschreibung bleibt editierbar")
        page.locator("#btnApplySingle").click()
        assert page.evaluate("revisionInventory[103].lore") == ["Kompakte Schnellaktionen", "Beschreibung bleibt editierbar"]
        if layout == "focus":
            assert_equipment(page, ("followup", layout), selected=103, above=True)
            if screenshots:
                page.mouse.move(0, 0)
                settle(page)
                page.evaluate("revisionGrid.hideSlotHover()")
                page.screenshot(path=str(screenshots / "focus_editor_390.png"), full_page=True)
        print(f"  Compact mobile quick actions: {layout}, gap {current['quickGap']:.1f}px passed", flush=True)
        checks += 1
        page.close()
    for width, height in ((1025, 900), (1440, 900), (1780, 1100)):
        page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
        create_page(page, root, layout="focus", view="world")
        page.evaluate("()=>{revisionSelectWorld(null);revisionShowWorlds(0);}")
        assert not page.locator("#selectedWorldBar").is_visible()
        assert page.locator("#worldScanEmpty").is_visible()
        for count in (1, 100):
            page.evaluate("count=>{revisionSelectWorld(null);revisionShowWorlds(count);scrollTo(0,0);}", count)
            settle(page)
            before = world_metrics(page)
            assert page.locator("#selectedWorldBar").is_visible() and page.locator("#btnLoad").is_disabled()
            page.wait_for_function("getComputedStyle(document.getElementById('btnOpenSelectedWorld')).visibility==='hidden'")
            assert not page.locator("#btnOpenSelectedWorld").is_visible()
            page.locator('#worldList [data-world-path="/worlds/0"]').click()
            settle(page)
            after = world_metrics(page)
            assert abs(after["top"] - before["top"]) <= 2, (width, count, before, after)
            assert 0 < after["loadTop"] < after["loadBottom"] <= after["top"], (width, count, after)
            assert after["loadBottom"] <= height and after["pageY"] == 0, (width, count, after)
            assert after["pageOverflow"] <= 1 and after["scrollTop"] == 0, (width, count, after)
            page.locator("#btnLoad").click()
            assert page.evaluate("revisionState.loadedPath") == "/worlds/0"
        assert page.evaluate("revisionState.loads") == 2
        print(f"  Focus first-world load: {width}×{height}, empty/1/100 results, stable action above list passed", flush=True)
        if screenshots and width == 1780:
            page.mouse.move(0, 0)
            page.screenshot(path=str(screenshots / "focus_worlds_1780.png"))
        checks += 1
        page.close()
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--checks", choices=("all", "equipment", "worlds", "folder", "followup"), default="all")
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("CHROMIUM_PATH") or shutil.which("chromium"), args=["--no-sandbox"])
        results = {}
        if args.checks in ("all", "equipment"):
            results["equipment"] = check_equipment(browser, args.root, args.screenshots)
            print(f"Equipment, editor, Lore, layout round trips, read-only: {results['equipment']} passed", flush=True)
        if args.checks in ("all", "worlds"):
            results["worlds"] = check_worlds(browser, args.root, args.screenshots)
            print(f"World collection, selection, load, keyboard, filtering: {results['worlds']} passed", flush=True)
        if args.checks in ("all", "folder"):
            results["folder"] = check_folder(browser, args.root)
            print(f"Folder API feedback: {results['folder']} passed", flush=True)
        if args.checks in ("all", "followup"):
            results["followup"] = check_followup(browser, args.root, args.screenshots)
            print(f"Final visual polish regressions: {results['followup']} passed", flush=True)
        browser.close()
    print(json.dumps({"passed": sum(results.values()), "groups": results}))


if __name__ == "__main__":
    main()
