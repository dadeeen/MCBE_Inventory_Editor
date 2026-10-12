"""Offline browser checks for mount configuration, placement and the pending queue.

Run: python scripts/mount_workspace_smoke.py
Dependencies and Chromium setup are shared with design_polish_smoke.py.
The real template, view and controller run against a synthetic preview API.
No Bedrock files are read or written. --screenshots DIR saves review images;
--capture-only captures without assertions, and --root DIR selects source files.
--checks layout, state, queue or values can repeat only one targeted group.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from design_polish_smoke import ROOT, create_page
from playwright.sync_api import sync_playwright

FIXTURE = r"""() => {
  const state = {
    world: '/synthetic/survival', playerKey: 'synthetic-0', player: {label:'Dennis'},
    pending: [], previews: [], writes: 0, undo: [], confirms: [], allowUnchecked: false,
    review: 0, messages: [], logs: [], failNext: false, holdNext: false, blocked: false,
    allUnsafe: false, noCandidates: false, footprintSample: null, diagnosticIssues: [],
  };
  const types = [
    ['minecraft:horse','Pferd'], ['minecraft:donkey','Esel'], ['minecraft:mule','Maultier'],
    ['minecraft:camel','Kamel'], ['minecraft:skeleton_horse','Skelettpferd'],
  ];
  function candidate(id, x, z, safe, mountType) {
    if(state.allUnsafe) safe=false;
    // The fixture covers precisely the grid columns touched by its synthetic
    // collision box. It does not stand in for backend collision validation.
    const sample = id === 'blickrichtung_4' ? state.footprintSample : null;
    if (sample) ({x, z} = sample);
    const halfWidth = sample?.halfWidth ?? (mountType === 'minecraft:camel' ? 0.85 : 0.7);
    const clearanceBlocks = sample?.clearanceBlocks ?? (mountType === 'minecraft:camel' ? 3 : 2);
    const columns = [];
    for (let blockZ=Math.floor(z-halfWidth); blockZ<Math.ceil(z+halfWidth); blockZ++)
      for (let blockX=Math.floor(x-halfWidth); blockX<Math.ceil(x+halfWidth); blockX++) columns.push({
      block_x:blockX, block_z:blockZ,
      center:blockX===Math.floor(x) && blockZ===Math.floor(z), safe_to_place:safe,
      block_names: {floor:sample?.floorName || 'minecraft:grass_block', feet:safe===false?'minecraft:stone':'minecraft:air',
        head:'minecraft:air', ...Object.fromEntries(Array.from({length:Math.max(0,clearanceBlocks-2)},(_,index)=>['body_'+(index+2),'minecraft:air']))},
    });
    const center = columns.find(column=>column.center);
    const edge = sample?.edgeOverhang ? columns.find(column=>!column.center) : null;
    if (edge) {edge.block_names.floor='minecraft:air';edge.safe_to_place=false;}
    const issues = safe==null ? state.diagnosticIssues.map(issue=>({...issue,
      message:window.t(issue.message),hint:window.t(issue.hint)})) : [];
    const message = safe===true
      ? edge ? window.t('Footprint geprüft: zentraler Boden {floor}, Körperraum frei; {count} Randspalten ohne tragenden Boden toleriert.',
          {floor:center.block_names.floor,count:1})
        : window.t('Footprint geprüft: zentraler Boden {floor}, Körperraum frei.', {floor:center.block_names.floor})
      : safe===false
        ? window.t('Footprint-{label} ist bei {x}/{z} durch {block} blockiert.', {
            label:window.t('Fußraum'),x:Math.floor(x),z:Math.floor(z),block:'minecraft:stone'})
        : issues.length ? issues.map(issue=>issue.message).join(' ')
          : window.t('Footprint konnte nicht geprüft werden; Position ist nicht sicher bestätigt.');
    const attempts = [2,3,4,5,6].map((distance,index)=>({distance,
      safe_to_place:safe===true && index<2 ? (index===0?false:null) : safe}));
    return {id, x, y:76, z, offset:{x:x-168,y:0,z:z+312}, distance:4,
      safe_to_place:safe, warning:message, placement_issues:issues, radius_scan_checked_count:5,
      radius_scan_safe_count:attempts.filter(item=>item.safe_to_place===true).length,
      radius_scan_unchecked_count:attempts.filter(item=>item.safe_to_place==null).length,
      radius_scan_unsafe_count:attempts.filter(item=>item.safe_to_place===false).length,
      radius_scan_attempts:attempts,
      chunk_probe:{footprint_check:{columns,column_count:columns.length,edge_overhang_count:edge?1:0,
          safe_to_place:safe,half_width:halfWidth,clearance_blocks:clearanceBlocks,message},
        placement_check:{message,block_names:center.block_names}},
    };
  }
  const preview = (request={}) => ({
    can_create:!state.blocked, mount_type:request.mountType || 'minecraft:horse',
    mount_label:types.find(([id])=>id===request.mountType)?.[1] || 'Pferd',
    mount_options:types.map(([id,label])=>({id,label,create_available:true})),
    player_reference:{player_key:state.playerKey,player_label:state.player.label},
    player_position:{x:168,y:76,z:-312}, dimension_id:0, server_guard_epoch:42,
    selected_candidate_id:'blickrichtung_4', selected_position:{x:168,y:76,z:-316},
    warnings:state.blocked ? [window.t('Mounts können nur in der Oberwelt erzeugt werden. Wechsle mit dem Spieler in die Oberwelt und lade ihn erneut.')] : [],
    placement_search:{radius:request.placementRadius||6,prefers_view_direction:true,
      full_area_scan:false,block_check:'chunk_probe',placement_safe_count:state.noCandidates||state.allUnsafe?0:2,
      placement_unsafe_count:state.noCandidates?0:state.allUnsafe?4:1,
      placement_unchecked_count:state.noCandidates||state.allUnsafe?0:1},
    candidate_positions:state.noCandidates?[]:[candidate('blickrichtung_4',168,-316,true,request.mountType),candidate('rechts_4',172,-312,true,request.mountType),
      candidate('links_4',164,-312,false,request.mountType),candidate('hinter_dir_4',168,-308,null,request.mountType)],
  });
  window.mountTestState=state;
  window.mountTestPreview=preview;
  window.mountTestController=window.MCBEMountController.createMountController({
    doc:document,
    apiClient:{
      previewMountOrThrow: async request => {
        state.previews.push(request);
        const result=preview(request);
        if(state.failNext){state.failNext=false;throw Error('Synthetic preview failed');}
        if(state.holdNext){state.holdNext=false;return await new Promise(resolve=>{state.release=()=>resolve(result);});}
        return result;
      },
      createMountOrThrow:async()=>{state.writes++;throw Error('A browser preview must never write');},
    },
    getWorldPath:()=>state.world, getCurrentPlayerKey:()=>state.playerKey,
    getCurrentPlayer:()=>state.player, showToast:(message,status)=>state.messages.push({message,status}),
    logStatus:(message,status)=>state.logs.push({message,status}), guardEditingAction:()=>false, pushUndo:label=>state.undo.push(label),
    onPendingChanged:pending=>{state.pending=pending;document.body.classList.toggle('app-dirty',pending.length>0);},
    onReviewRequested:()=>{state.review++;},
    confirmUncheckedCreate:message=>{state.confirms.push(message);return state.allowUnchecked;},
  });
  document.body.classList.add('app-world-loaded','app-player-loaded');
  document.getElementById('mountsPanel').style.display='flex';
  document.getElementById('emptyState').style.display='none';
  document.getElementById('playerManager').style.display='none';
  const responsive=window.MCBEWorkflowState.createResponsivePanelController({
    leftPanel:document.querySelector('.left-panel'),rightPanel:document.querySelector('.right-panel'),
    panelToggles:document.querySelectorAll('.btn-toggle[data-panel]'),
  });
  responsive.wire();responsive.activateForWorkflow('mounts');
  window.mountTestController.refresh();
}"""


def create_mount_page(page, root=ROOT, locale="de", layout="studio", loaded=False):
    page.set_default_timeout(10000)
    create_page(page, root=root, locale=locale, layout=layout, view="mounts")
    # Additional code-native preview assets are optional for v15 before captures.
    for name in ("mount_workspace.css", "mount_model_preview.css"):
        source = root / "static" / name
        if source.is_file():
            page.add_style_tag(content=source.read_text("utf-8"))
    for name in ("workflow_state.js", "mount_model_preview.js", "mount_view.js", "mount_controller.js"):
        source = root / "static" / name
        if source.is_file():
            page.add_script_tag(content=source.read_text("utf-8"))
    page.evaluate(FIXTURE)
    if loaded:
        page.evaluate("window.mountTestController.loadPreview()")
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def mount_metrics(page):
    return page.evaluate("""() => {
      const box=selector=>{
        const node=document.querySelector(selector);if(!node)return null;
        const rect=node.getBoundingClientRect();
        return {x:rect.x,y:rect.y,right:rect.right,bottom:rect.bottom,width:rect.width,height:rect.height};
      };
      return {pageOverflow:document.documentElement.scrollWidth-innerWidth,scrollX,
        pageHeight:document.documentElement.scrollHeight,panel:box('#mountsPanel'),
        config:box('#mountOptionsPanel'),preview:box('#mountPreviewPanel'),
        stage:box('#btnMountCreate'),type:box('#mountTypeSelect'),
        points:[...document.querySelectorAll('.mount-map-point')].map(node=>({
          id:node.dataset.candidateId,disabled:node.disabled,selected:node.classList.contains('active'),
          width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height,
        })),
        focus:document.activeElement?.id||document.activeElement?.dataset.candidateId||document.activeElement?.tagName,
        pendingCount:window.mountTestController.getPendingMounts().length,
        pendingCards:document.querySelectorAll('[data-remove-pending-mount]').length,
      };
    }""")


def assert_contained_controls(page, context):
    # scrollWidth alone misses content clipped by a flex/grid ancestor.
    # Native dialog controls are checked separately in the modal focus test.
    observed = page.evaluate("""() => {
      const panel=document.getElementById('mountsPanel').getBoundingClientRect();
      return [...document.querySelectorAll('#mountsPanel input,#mountsPanel select,#mountsPanel button')]
        .filter(node=>node.offsetWidth && node.offsetHeight && !node.closest('dialog'))
        .map(node=>{const r=node.getBoundingClientRect();return {
          id:node.id||node.dataset.candidateId||node.dataset.modelAction||node.className,
          left:r.left-panel.left,right:r.right-panel.right,width:r.width,
        };}).filter(rect=>rect.left < -1 || rect.right > 1 || rect.width < 24);
    }""")
    assert not observed, (context, "clipped controls", observed)
    assert mount_metrics(page)["pageOverflow"] <= 1, (context, mount_metrics(page))
    assert page.evaluate("scrollX") == 0, (context, "horizontal viewport shifted")


def assert_queue_unavailable(page, context):
    action = page.locator("#btnMountCreate")
    assert not action.count() or action.is_disabled(), (context, "queue action available")


def assert_model_interactions(page, context):
    stage = page.locator("#mountModelPreview .mount-model-stage")
    assert stage.is_visible(), (context, "model missing")
    assert stage.get_attribute("data-random") == "false", (context, "custom mode mislabeled")
    assert stage.get_attribute("data-color") == "4" and stage.get_attribute("data-mark") == "3", context
    before = page.locator("#mountModelPreview .mount-model-svg").inner_html()
    yaw = stage.get_attribute("data-yaw")
    stage.focus()
    page.keyboard.press("ArrowRight")
    assert stage.get_attribute("data-yaw") != yaw, (context, "keyboard rotation")
    assert page.locator("#mountModelPreview .mount-model-svg").inner_html() != before
    page.keyboard.press("Home")
    assert stage.get_attribute("data-yaw") == yaw, (context, "keyboard reset")
    page.locator('#mountModelPreview [data-model-action="left"]').click()
    rotated = stage.get_attribute("data-yaw")
    assert rotated != yaw, (context, "button rotation")
    return rotated


def assert_technical_dialog(page, context):
    trigger = page.locator("#btnMountTechDetails")
    trigger.click()
    dialog = page.locator("#mountTechOverlay")
    assert dialog.evaluate("node=>node.tagName==='DIALOG' && node.open"), (context, "native modal")
    assert dialog.locator('[data-disclosure="preview-notes"]').count() == 0, (context, "redundant preview notes")
    block_details = dialog.locator('details[data-disclosure="block-probe"]')
    for _ in range(12):
        page.keyboard.press("Tab")
        assert dialog.evaluate("node=>node.contains(document.activeElement)"), (context, "modal focus escaped")
        if block_details.locator("summary").evaluate("node=>node===document.activeElement"):
            break
    else:
        raise AssertionError((context, "block data summary unreachable"))
    page.keyboard.press("Enter")
    assert block_details.evaluate("node=>node.open"), (context, "block data disclosure did not open")
    page.keyboard.press("Shift+Tab")
    assert dialog.evaluate("node=>node.contains(document.activeElement)"), (context, "reverse modal focus escaped")
    page.keyboard.press("Escape")
    assert not dialog.evaluate("node=>node.open"), (context, "escape did not close")
    assert trigger.evaluate("node=>node===document.activeElement"), (context, "modal focus not restored")


def capture(browser, root, output):
    output.mkdir(parents=True, exist_ok=True)
    observations = []
    for layout in ("studio", "focus"):
        for width, height in ((1440, 960), (390, 900)):
            page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
            create_mount_page(page, root=root, layout=layout)
            page.screenshot(path=str(output / f"{layout}_mount_idle_{width}.png"), full_page=True)
            observations.append({"layout": layout, "width": width, "state": "idle", **mount_metrics(page)})
            page.locator("#btnMountPreview").click()
            page.wait_for_selector(".mount-map-point")
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=str(output / f"{layout}_mount_ready_{width}.png"), full_page=True)
            observations.append({"layout": layout, "width": width, "state": "ready", **mount_metrics(page)})
            page.locator("#mountHorseProfileMode").select_option("custom")
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=str(output / f"{layout}_mount_custom_{width}.png"), full_page=True)
            page.locator("#btnMountCreate").click()
            observations.append({"layout": layout, "width": width, "state": "queued", **mount_metrics(page)})
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=str(output / f"{layout}_mount_queued_{width}.png"), full_page=True)
            page.close()
    (output / "metrics.json").write_text(json.dumps(observations, indent=2), "utf-8")
    print(f"Screenshots: {output}", flush=True)


def run_layout_checks(browser, root):
    checks = 0
    for locale in ("de", "en"):
        for layout in ("classic", "studio", "focus"):
            for width in (1440, 390):
                page = browser.new_page(viewport={"width": width, "height": 960}, reduced_motion="reduce")
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                create_mount_page(page, root=root, locale=locale, layout=layout)
                context = (locale, layout, width)
                assert_queue_unavailable(page, (context, "idle stage"))
                assert_contained_controls(page, context)
                page.locator("#mountHorseProfileMode").focus()
                page.locator("#mountHorseProfileMode").select_option("custom")
                assert page.evaluate("document.activeElement.id") == "mountHorseProfileMode", (context, "profile focus lost")
                default_model = page.locator("#mountModelPreview .mount-model-svg").inner_html()
                page.locator("#mountHorseColorSelect").select_option("4")
                colored_model = page.locator("#mountModelPreview .mount-model-svg").inner_html()
                assert colored_model != default_model, (context, "color not reflected")
                page.locator("#mountHorseMarkSelect").select_option("3")
                assert page.locator("#mountModelPreview .mount-model-svg").inner_html() != colored_model, (context, "marking not reflected")
                assert page.locator("#mountHorseColorSelect").input_value() == "4"
                assert page.evaluate("window.mountTestState.previews.length") == 0
                rotated = assert_model_interactions(page, context)
                assert_contained_controls(page, context)
                page.locator("#btnMountPreview").click()
                page.wait_for_selector(".mount-map-point")
                assert page.locator("#btnMountCreate").is_enabled(), context
                assert page.evaluate("document.activeElement.id") == "btnMountPreview", (context, "scan button focus lost")
                assert page.locator("#mountModelPreview .mount-model-stage").get_attribute("data-yaw") == rotated
                assert page.locator('[data-candidate-id="links_4"]').is_disabled()
                page.locator('[data-candidate-id="rechts_4"]').focus()
                page.keyboard.press("Enter")
                assert page.locator('[data-candidate-id="rechts_4"]').evaluate("node=>node.classList.contains('active')")
                assert page.evaluate("document.activeElement.dataset.candidateId") == "rechts_4", (context, "candidate focus lost")
                assert page.locator("#mountModelPreview .mount-model-stage").get_attribute("data-yaw") == rotated
                assert page.locator("#mountHorseColorSelect").input_value() == "4"
                assert_technical_dialog(page, context)
                assert_contained_controls(page, context)
                page.locator("#btnMountCreate").click()
                pending = page.evaluate("window.mountTestController.getPendingMounts()")
                assert len(pending) == 1 and pending[0]["horseProfile"]["color"] == 4 and pending[0]["horseProfile"]["mark_variant"] == 3
                assert page.evaluate("window.mountTestState.logs.at(-1).status") == "success", (context, "safe staging reported as a warning")
                assert not page.locator("#mountCreateStatus").inner_text(), (context, "staging repeats the queue and toast")
                assert page.locator(".pending-mount-safety.warning").count() == 0, (context, "safe queue has an unnecessary warning")
                assert pending[0]["preferredOffset"] == {"x": 4, "y": 0, "z": 0}
                assert page.locator("[data-remove-pending-mount]").count() == 1, (context, "invisible queue")
                card = page.locator(".pending-mount-card").bounding_box()
                copy = page.locator(".pending-mount-copy").bounding_box()
                assert card and copy and copy["width"] >= min(160, card["width"] * 0.55), (context, "pending copy squeezed", card, copy)
                page.locator("#btnMountReviewPending").click()
                assert page.evaluate("window.mountTestState.review") == 1
                page.locator("[data-remove-pending-mount]").focus()
                page.keyboard.press("Enter")
                assert page.evaluate("window.mountTestController.getPendingMounts().length") == 0
                assert page.locator("[data-remove-pending-mount]").count() == 0
                assert page.evaluate("document.activeElement.id") == "btnMountCreate", (context, "last removal focus lost")
                for theme in ("dark", "light", "minecraft"):
                    page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
                    assert_contained_controls(page, (context, theme))
                if layout in ("studio", "focus"):
                    page.evaluate("""() => {
                      const presence=document.getElementById('worldPresenceBanner');
                      presence.style.display='flex';presence.textContent='World presence warning';
                      const error=document.getElementById('loadErrorPanel');
                      error.style.display='block';error.textContent='World load warning';
                    }""")
                    assert page.locator("#worldPresenceBanner").is_visible() and page.locator("#loadErrorPanel").is_visible(), context
                assert page.evaluate("window.mountTestState.writes") == 0
                assert not errors, (context, errors)
                checks += 1
                page.close()
    print(f"Mount form, live model, keyboard, modal and queue: {checks} layout/locale/viewport scenarios passed", flush=True)
    return checks


def run_state_checks(browser, root):
    # These asynchronous cases use one layout because the state machine is shared.
    checks = 0
    page = browser.new_page(viewport={"width": 1440, "height": 960}, reduced_motion="reduce")
    create_mount_page(page, root=root, loaded=True)
    page.locator("#mountHorseProfileMode").select_option("custom")
    page.locator('details[data-disclosure="horse-stats"] > summary').click()
    page.locator("#mountHorseHealthInput").fill("27")
    page.locator("#mountHorseColorSelect").select_option("5")
    page.locator("#mountTypeSelect").focus()
    page.locator("#mountTypeSelect").select_option("minecraft:donkey")
    assert_queue_unavailable(page, "type invalidation")
    assert page.locator(".mount-map-point").count() == 0
    assert page.evaluate("document.activeElement.id") == "mountTypeSelect"
    page.locator("#mountStatHealthInput").fill("28")
    page.locator("#mountStatTemperInput").fill("72")
    page.locator("#mountStatTamedCheckbox").check()
    assert page.locator("#mountStatTemperInput").count() == 0
    page.locator("#mountStatTamedCheckbox").uncheck()
    assert page.locator("#mountStatTemperInput").input_value() == "72", "Tame toggle lost earlier wild temper"
    assert page.locator("#mountStatHealthInput").input_value() == "28"
    page.locator("#mountTypeSelect").select_option("minecraft:horse")
    assert page.locator("#mountHorseProfileMode").input_value() == "custom", "Type roundtrip lost profile mode"
    assert page.locator("#mountHorseHealthInput").input_value() == "27"
    assert page.locator("#mountHorseColorSelect").input_value() == "5"
    stats = page.locator('details[data-disclosure="horse-stats"]')
    if not stats.evaluate("node=>node.open"):
        stats.locator("summary").click()
    checks += 1

    page.evaluate("() => {window.mountTestState.holdNext=true;window.mountHeldRequest=window.mountTestController.loadPreview();}")
    assert_queue_unavailable(page, "pending scan")
    page.locator("#mountHorseHealthInput").fill("29")
    page.evaluate("() => {window.mountTestState.release();}")
    page.evaluate("window.mountHeldRequest")
    assert page.locator("#mountHorseHealthInput").input_value() == "29", "Async response lost unblurred edit"
    assert page.evaluate("document.activeElement.id") == "mountHorseHealthInput"
    assert page.locator("#btnMountCreate").is_enabled()
    checks += 1

    page.evaluate("() => {window.mountTestState.holdNext=true;window.mountHeldRequest=window.mountTestController.loadPreview();}")
    page.locator("#mountTypeSelect").select_option("minecraft:camel")
    page.evaluate("() => {window.mountTestState.release();}")
    page.evaluate("window.mountHeldRequest")
    assert page.locator("#mountTypeSelect").input_value() == "minecraft:camel", "Old scan replaced changed mount type"
    assert_queue_unavailable(page, "late scan after type change")
    assert page.locator("#mountModelPreview .mount-model-stage").get_attribute("data-mount-type") == "minecraft:camel"
    checks += 1

    page.locator("#mountTypeSelect").select_option("minecraft:skeleton_horse")
    assert page.locator("#mountStatJumpInput").count() == 1 and page.locator("#mountStatTamedCheckbox").count() == 0
    page.locator("#mountTypeSelect").select_option("minecraft:mule")
    assert page.locator("#mountStatHealthInput").count() == 1 and page.locator("#mountStatTamedCheckbox").count() == 1
    page.locator("#btnMountPreview").click()
    page.wait_for_selector(".mount-map-point")
    page.locator("#mountPlacementRadiusInput").fill("10")
    page.locator("#mountPlacementRadiusInput").press("Tab")
    assert_queue_unavailable(page, "radius invalidation")
    assert page.locator(".mount-map-point").count() == 0
    page.locator("#btnMountPreview").click()
    page.wait_for_selector(".mount-map-point")
    assert page.evaluate("window.mountTestState.previews.at(-1).placementRadius") == 10
    checks += 1

    page.locator('[data-candidate-id="hinter_dir_4"]').click()
    page.locator("#btnMountCreate").click()
    assert page.evaluate("window.mountTestState.confirms.length") == 1
    assert page.evaluate("window.mountTestController.getPendingMounts().length") == 0
    page.evaluate("window.mountTestState.allowUnchecked=true")
    page.locator("#btnMountCreate").click()
    pending = page.evaluate("window.mountTestController.getPendingMounts()")
    assert len(pending) == 1 and pending[0]["allowUncheckedPlacement"] is True and pending[0]["safetyStatus"] == "unchecked"
    assert page.evaluate("window.mountTestState.logs.at(-1).status") == "warning", "Unchecked staging lost its warning"
    assert page.locator(".pending-mount-safety.warning").count() == 1, "Unchecked queue lost its visible warning"
    page.locator("#btnMountDiscardPending").click()
    assert page.evaluate("window.mountTestController.getPendingMounts().length") == 0
    assert page.evaluate("document.activeElement.id") == "btnMountCreate", "Discard queue focus lost"
    checks += 1

    for state in ("allUnsafe", "blocked", "noCandidates"):
        page.evaluate(
            """key=>{
          window.mountTestState.allUnsafe=false;window.mountTestState.blocked=false;
          window.mountTestState.noCandidates=false;window.mountTestState[key]=true;
        }""",
            state,
        )
        page.evaluate("window.mountTestController.loadPreview()")
        assert_queue_unavailable(page, state)
        assert page.locator("#mountPreviewPanel").inner_text().strip(), (state, "missing state explanation")
        if state == "blocked":
            reason = page.locator(".mount-warning-list").inner_text().strip()
            assert reason and page.locator("#btnMountCreate").get_attribute("title") == reason, "Disabled action gives the wrong next step"
        page.evaluate("window.mountTestController.queueMount()")
        assert page.evaluate("window.mountTestController.getPendingMounts().length") == 0
        checks += 1
    page.evaluate("() => {window.mountTestState.noCandidates=false;window.mountTestState.blocked=false;window.mountTestState.allUnsafe=false;}")
    page.evaluate("window.mountTestController.loadPreview()")
    page.evaluate("() => {window.mountTestState.failNext=true;}")
    page.evaluate("window.mountTestController.loadPreview()")
    assert_queue_unavailable(page, "failed scan")
    assert "Synthetic preview failed" in page.locator("#mountCreateStatus").inner_text()
    page.locator("#btnMountPreview").click()
    page.wait_for_selector(".mount-map-point")
    assert page.locator("#btnMountCreate").is_enabled(), "Cannot retry failed scan"
    checks += 1

    page.evaluate("() => {window.mountTestState.holdNext=true;window.mountHeldRequest=window.mountTestController.loadPreview();}")
    page.evaluate("""() => {
      window.mountTestState.playerKey='synthetic-1';window.mountTestState.player={label:'Alex'};
      window.mountTestController.refresh();window.mountTestState.release();
    }""")
    page.evaluate("window.mountHeldRequest")
    assert_queue_unavailable(page, "old player scan")
    assert page.locator(".mount-map-point").count() == 0, "Old player scan accepted"
    page.evaluate("""() => {
      window.mountTestState.world='';window.mountTestState.playerKey='';
      window.mountTestState.player=null;window.mountTestController.refresh();
    }""")
    assert_queue_unavailable(page, "no reference player")
    assert page.evaluate("window.mountTestState.writes") == 0
    checks += 1
    page.close()

    # Narrow reflow and the medium breakpoint previously hid oversized form
    # controls even while document.scrollWidth incorrectly looked healthy.
    for layout in ("classic", "studio", "focus"):
        for width in (320, 920):
            page = browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
            create_mount_page(page, root=root, locale="en", layout=layout, loaded=True)
            page.locator("#mountHorseProfileMode").select_option("custom")
            assert_contained_controls(page, ("narrow/medium", layout, width))
            if layout == "studio" and width == 920:
                stage = page.locator("#mountModelPreview .mount-model-stage")
                stage.scroll_into_view_if_needed()
                rect = stage.bounding_box()
                assert rect is not None
                before = stage.get_attribute("data-yaw")
                edge, middle = rect["x"] + rect["width"] - 2, rect["y"] + rect["height"] / 2
                page.mouse.move(edge, middle)
                page.mouse.down()
                page.mouse.move(edge + 4, middle)
                page.mouse.up()
                page.mouse.move(rect["x"] + rect["width"] / 2, middle)
                assert stage.get_attribute("data-yaw") == before, "Model rotates after releasing outside its boundary"
            page.close()
            checks += 1

    # Genuine Chromium touch input reaches the model's pointer handlers. The
    # stage keeps vertical page scrolling available through touch-action: pan-y.
    page = browser.new_page(viewport={"width": 390, "height": 900}, has_touch=True, is_mobile=True, reduced_motion="reduce")
    create_mount_page(page, root=root)
    stage = page.locator("#mountModelPreview .mount-model-stage")
    stage.scroll_into_view_if_needed()
    assert "pan-y" in stage.evaluate("node=>getComputedStyle(node).touchAction").split()
    before = stage.get_attribute("data-yaw")
    rect = stage.bounding_box()
    assert rect is not None
    x, y = rect["x"] + rect["width"] * 0.5, rect["y"] + rect["height"] * 0.5
    session = page.context.new_cdp_session(page)
    session.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for distance in (12, 25, 40, 60):
        session.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x + distance, "y": y}]})
    session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    assert stage.get_attribute("data-yaw") != before, "Touch drag did not rotate model"
    assert page.evaluate("window.mountTestState.previews.length") == 0, "Model rotation requested a placement scan"
    page.close()
    checks += 1
    return checks


def run_queue_checks(browser, root):
    # Final queue polish: readable narrow cards, keyboard disclosures, and focus
    # following the next removable card or the main action after the last one.
    checks = 0
    for layout in ("classic", "studio", "focus"):
        for width in (320, 390, 1440):
            locale = "en" if width == 320 else "de"
            context = (layout, width, locale)
            page = browser.new_page(viewport={"width": width, "height": 960}, reduced_motion="reduce")
            create_mount_page(page, root=root, layout=layout, locale=locale, loaded=True)
            page.locator("#mountHorseProfileMode").select_option("custom")
            page.locator("#btnMountCreate").click()
            page.locator("#btnMountCreate").click()
            cards = page.locator(".pending-mount-card")
            assert cards.count() == 2, context
            card = cards.first.bounding_box()
            copy = cards.first.locator(".pending-mount-copy").bounding_box()
            assert card and copy and copy["width"] >= min(160, card["width"] * 0.55), (context, card, copy)
            details = cards.first.locator("details")
            assert details.count() == 1, context
            assert not details.evaluate("node=>node.open"), context
            details.locator("summary").focus()
            page.keyboard.press("Enter")
            assert details.evaluate("node=>node.open"), context
            assert_contained_controls(page, context)
            page.locator("[data-remove-pending-mount]").first.focus()
            page.keyboard.press("Enter")
            assert page.locator("[data-remove-pending-mount]").count() == 1, context
            assert page.locator("[data-remove-pending-mount]").evaluate("node=>node===document.activeElement"), context
            page.keyboard.press("Enter")
            assert page.locator("[data-remove-pending-mount]").count() == 0, context
            assert page.evaluate("document.activeElement.id") == "btnMountCreate", context
            page.locator("#btnMountCreate").click()
            page.locator("#btnMountDiscardPending").focus()
            page.keyboard.press("Enter")
            assert page.evaluate("document.activeElement.id") == "btnMountCreate", context
            assert not page.evaluate("window.mountTestController.getPendingMounts().length"), context
            assert not page.evaluate("window.mountTestState.writes"), context
            page.close()
            checks += 1
    print(f"Queue layout, disclosures and removal/discard focus: {checks} scenarios passed", flush=True)
    return checks


def run_value_checks(browser, root):
    checks = 0
    fields = {"Health": 30, "Movement": 0.3375, "Jump": 1, "Temper": 99}
    for layout in ("classic", "studio", "focus"):
        for width, locale in ((1440, "de"), (390, "en")):
            for theme in ("dark", "light"):
                context = (layout, width, locale, theme)
                page = browser.new_page(viewport={"width": width, "height": 960}, reduced_motion="reduce")
                create_mount_page(page, root=root, layout=layout, locale=locale, loaded=True)
                page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
                page.locator("#mountHorseProfileMode").select_option("custom")
                details = page.locator('details[data-disclosure="horse-stats"]')
                details.locator("summary").click()
                for field in fields:
                    page.locator(f"#mountHorse{field}Input").fill("100")
                assert page.locator('[aria-invalid="true"]').count() == 4, context
                assert page.locator(".mount-field-error").count() == 4, context
                movement_hint = page.locator("#mountHorseMovementHint").inner_text()
                assert ("0,1125" if locale == "de" else "0.1125") in movement_hint, (context, movement_hint)
                assert "≈" not in page.locator("#mountHorseJumpHint").inner_text(), context
                assert_contained_controls(page, context)
                # Selecting a new location recreates the controls. Invalid
                # drafts must remain visible and must never be silently clamped.
                page.locator('[data-candidate-id="rechts_4"]').click()
                for field in fields:
                    assert page.locator(f"#mountHorse{field}Input").input_value() == "100", context
                page.evaluate("window.mountTestController.loadPreview()")
                details = page.locator('details[data-disclosure="horse-stats"]')
                details.evaluate("node=>node.open=false")
                page.locator("#btnMountCreate").click()
                assert details.evaluate("node=>node.open"), context
                assert page.evaluate("document.activeElement.id") == "mountHorseHealthInput", context
                assert not page.evaluate("window.mountTestState.pending.length || window.mountTestState.undo.length"), context
                for field, value in fields.items():
                    page.locator(f"#mountHorse{field}Input").fill(str(value))
                page.locator("#mountHorseTemperInput").fill("5.5")
                assert page.locator("#mountHorseTemperInput").get_attribute("aria-invalid") == "true", context
                page.locator("#btnMountCreate").click()
                assert not page.evaluate("window.mountTestState.pending.length"), context
                page.locator("#mountHorseTemperInput").fill("99")
                page.locator("#mountHorseHealthInput").fill("")
                page.evaluate("window.mountTestController.loadPreview()")
                assert page.locator("#mountHorseHealthInput").input_value() == "", context
                page.locator("#btnMountCreate").click()
                assert not page.evaluate("window.mountTestState.pending.length"), context
                page.locator("#mountHorseHealthInput").fill("30")
                assert page.locator('[aria-invalid="true"]').count() == 0, context
                assert "≈" in page.locator("#mountHorseMovementHint").inner_text(), context
                # The same button must still work after rejected clicks.
                page.locator("#btnMountCreate").click()
                pending = page.evaluate("window.mountTestController.getPendingMounts()")
                assert len(pending) == 1, context
                assert {key: pending[0]["horseProfile"][key] for key in ("health", "movement", "jump_strength", "temper")} == {
                    "health": 30,
                    "movement": 0.3375,
                    "jump_strength": 1,
                    "temper": 99,
                }, context
                assert not page.evaluate("window.mountTestState.writes"), context
                page.close()
                checks += 1

    page = browser.new_page(viewport={"width": 1440, "height": 960}, reduced_motion="reduce")
    create_mount_page(page, root=root, loaded=True)
    for species, field in (("donkey", "Health"), ("mule", "Temper"), ("skeleton_horse", "Jump")):
        page.locator("#mountTypeSelect").select_option(f"minecraft:{species}")
        page.evaluate("window.mountTestController.loadPreview()")
        control = page.locator(f"#mountStat{field}Input")
        control.fill("100")
        page.locator("#btnMountCreate").click()
        assert not page.evaluate("window.mountTestState.pending.length"), species
        assert control.get_attribute("aria-invalid") == "true", species
        control.fill("")
        control.press_sequentially("1e")
        assert control.evaluate("node=>node.validity.badInput"), species
        page.evaluate("window.mountTestController.loadPreview()")
        page.locator("#btnMountCreate").click()
        assert not page.evaluate("window.mountTestState.pending.length"), (species, "incomplete value became random")
        # Explicitly clearing an optional value does mean a random attribute.
        control.press("Backspace")
        page.locator("#btnMountCreate").click()
        pending = page.evaluate("window.mountTestController.getPendingMounts()")
        assert len(pending) == 1 and not pending[0]["mountStats"], species
        page.locator("#btnMountDiscardPending").click()
        checks += 1
    assert not page.evaluate("window.mountTestState.writes")
    page.close()
    print(f"Mount numeric bounds, localization, draft persistence and staging: {checks} scenarios passed", flush=True)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--checks", choices=("all", "layout", "state", "queue", "values"), default="all")
    args = parser.parse_args()
    chromium_path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("chromium-browser")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chromium_path, args=["--no-sandbox"] if os.name == "posix" else [])
        try:
            if args.screenshots:
                capture(browser, args.root, args.screenshots)
            if not args.capture_only:
                checks = 0
                if args.checks in ("all", "layout"):
                    checks += run_layout_checks(browser, args.root)
                if args.checks in ("all", "state"):
                    checks += run_state_checks(browser, args.root)
                if args.checks in ("all", "queue"):
                    checks += run_queue_checks(browser, args.root)
                if args.checks in ("all", "values"):
                    checks += run_value_checks(browser, args.root)
                print(f"PASS: {checks} mount browser scenarios (real UI; synthetic preview API; no writes)")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
