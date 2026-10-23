import { expect, test } from "@playwright/test";
import {
  collectBrowserErrors,
  openAppAndWaitForScan,
  openAppWithEmptyWorldScan,
  openDragFixture,
  selectSetting,
  selectLayout,
} from "./fixtures/app.mjs";

test("loaded desktop workflows keep world above focus and player context", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openAppWithEmptyWorldScan(page);

  await page.evaluate(() => {
    document.body.classList.add("app-world-loaded", "app-player-loaded");
    document.querySelector("#selectedWorldSafetyNote").textContent = "Ungespeicherte Änderungen";
  });

  for (const { view, focus } of [
    { view: "inventory", focus: "#inventoryContainer" },
    { view: "player", focus: "#dashboardPanel" },
    { view: "mounts", focus: "#mountsPanel" },
    { view: "save", focus: "#saveWorkflowPanel" },
  ]) {
    await page.evaluate(activeView => { document.body.dataset.workflowView = activeView; }, view);

    const worldBox = await page.locator("#worldSection").boundingBox();
    const focusBox = await page.locator(focus).boundingBox();
    const playerBox = await page.locator("#playerManager").boundingBox();
    expect(worldBox, `${view}: world context`).not.toBeNull();
    expect(focusBox, `${view}: focus`).not.toBeNull();
    expect(playerBox, `${view}: player context`).not.toBeNull();
    expect(worldBox.y + worldBox.height).toBeLessThanOrEqual(focusBox.y);
    expect(worldBox.y + worldBox.height).toBeLessThanOrEqual(playerBox.y);
    expect(focusBox.x + focusBox.width).toBeLessThan(playerBox.x);
    expect(worldBox.x + worldBox.width).toBeGreaterThanOrEqual(playerBox.x + playerBox.width);

    const playerSurface = await page.locator("#playerManager").evaluate(element => {
      const style = getComputedStyle(element);
      const rgbaMatch = style.backgroundColor.match(/^rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)$/);
      return {
        position: style.position,
        alpha: rgbaMatch ? Number(rgbaMatch[1]) : 1,
      };
    });
    if (view === "inventory") {
      expect(playerSurface.position).toBe("static");
    } else {
      expect(playerSurface.position).toBe("sticky");
      expect(playerSurface.alpha).toBe(1);
    }
  }

  await page.evaluate(() => {
    document.querySelector("#selectedWorldName").textContent = "Smoke Test World";
    const safetyNote = document.querySelector("#selectedWorldSafetyNote");
    safetyNote.textContent = "Ungespeicherte Änderungen";
    safetyNote.style.display = "inline-flex";
  });
  const worldCopy = await page.locator("#selectedWorldName").boundingBox();
  const dirtyNote = await page.locator("#selectedWorldSafetyNote").boundingBox();
  const worldActions = await page.locator("#selectedWorldBar .selected-world-actions").boundingBox();
  expect(worldCopy).not.toBeNull();
  expect(dirtyNote).not.toBeNull();
  expect(worldActions).not.toBeNull();
  expect(Math.abs(worldCopy.y - dirtyNote.y)).toBeLessThan(24);
  expect(Math.abs(worldCopy.y - worldActions.y)).toBeLessThan(24);
});

test("inventory player context does not overlap the visible slot editor while scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 720 });
  await openAppWithEmptyWorldScan(page);

  await page.evaluate(() => {
    document.body.classList.add("app-world-loaded", "app-player-loaded");
    document.body.dataset.workflowView = "inventory";
    const inventory = document.querySelector("#inventoryContainer");
    const player = document.querySelector("#playerManager");
    const detail = document.querySelector("#detailEditorPanel");
    inventory.style.minHeight = "1500px";
    player.style.display = "flex";
    detail.style.display = "flex";
    detail.style.minHeight = "1200px";
  });

  await expect(page.locator("#playerManager")).toBeVisible();
  await expect(page.locator("#detailEditorPanel")).toBeVisible();
  await expect(page.locator("#playerManager")).toHaveCSS("position", "static");

  await page.evaluate(() => {
    const detail = document.querySelector("#detailEditorPanel");
    const absoluteTop = detail.getBoundingClientRect().top + window.scrollY;
    window.scrollTo(0, Math.max(0, absoluteTop - 80));
  });
  await page.waitForFunction(() => window.scrollY > 0);

  const playerBox = await page.locator("#playerManager").boundingBox();
  const detailBox = await page.locator("#detailEditorPanel").boundingBox();
  expect(playerBox).not.toBeNull();
  expect(detailBox).not.toBeNull();
  expect(playerBox.y + playerBox.height).toBeLessThanOrEqual(detailBox.y + 1);
});

test("narrowing to mobile keeps the active workspace panel visible", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openAppWithEmptyWorldScan(page);

  await page.setViewportSize({ width: 429, height: 897 });

  await expect(page.locator(".left-panel")).toBeVisible();
  await expect(page.locator(".right-panel")).toBeHidden();
  const workspaceBox = await page.locator(".workspace").boundingBox();
  expect(workspaceBox).not.toBeNull();
  expect(workspaceBox.height).toBeGreaterThan(0);
  const mobileOverflow = await page.evaluate(() => {
    const nav = document.querySelector(".app-section-nav");
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      navOverflowX: nav ? getComputedStyle(nav).overflowX : "missing",
    };
  });
  expect(mobileOverflow.documentWidth).toBeLessThanOrEqual(mobileOverflow.viewportWidth);
  expect(mobileOverflow.navOverflowX).toBe("auto");
});

test("studio and focus provide distinct layouts without changing items, theme or workflow", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/icons/scan", route => route.fulfill({ json: { success: true, icons: {}, count: 0 } }));
  await openDragFixture(page);

  await selectSetting(page, "themeSelect", "light");
  const originalItem = await page.evaluate(() => JSON.stringify(inventory[0]));
  await expect(page.locator("#layoutSelect")).toHaveValue("classic");

  await selectSetting(page, "layoutSelect", "studio");
  await expect(page.locator("html")).toHaveAttribute("data-layout", "studio");
  await expect(page.locator("#layoutViewTitle")).toHaveText("Inventar bearbeiten");
  const studio = await page.evaluate(() => ({
    rail: getComputedStyle(document.querySelector(".layout-controls")).position,
    panel: getComputedStyle(document.querySelector("#detailEditorPanel")).position,
    navLeft: document.querySelector(".app-workflow-nav").getBoundingClientRect().left,
    workLeft: document.querySelector(".workspace").getBoundingClientRect().left,
  }));
  expect(studio.rail).toBe("sticky");
  expect(studio.workLeft).toBeGreaterThan(studio.navLeft + 170);
  // Context is actually above the editor destinations in the same sidebar.
  // Save/review is a separate global action below navigation.
  const studioHierarchy = await page.evaluate(() => ({
    world: document.querySelector('.layout-context-chip[data-workflow-view="world"]').getBoundingClientRect().top,
    player: document.querySelector('.layout-context-chip[data-workflow-view="player"]').getBoundingClientRect().top,
    nav: document.querySelector('.app-workflow-nav').getBoundingClientRect().top,
    save: document.querySelector('.layout-context-action').getBoundingClientRect().top,
    contextDisplay: getComputedStyle(document.querySelector('.layout-context-bar')).display,
  }));
  expect(studioHierarchy.world).toBeLessThan(studioHierarchy.player);
  expect(studioHierarchy.player).toBeLessThan(studioHierarchy.nav);
  expect(studioHierarchy.nav).toBeLessThan(studioHierarchy.save);
  expect(studioHierarchy.contextDisplay).toBe('contents');
  await expect(page.locator('.layout-nav-heading, .layout-context-caption, .layout-nav-admin, .layout-nav-optional')).toHaveCount(0);

  await page.locator('[data-slot="0"]').click();
  await expect(page.locator("#detailEditorPanel")).toBeVisible();
  await expect(page.locator("#detailItemSearch")).toHaveValue("minecraft:stone");
  expect(await page.locator("#detailEditorPanel").evaluate(el => getComputedStyle(el).position)).not.toBe("fixed");

  await selectSetting(page, "layoutSelect", "focus");
  await expect(page.locator("html")).toHaveAttribute("data-layout", "focus");
  const focus = await page.evaluate(() => {
    const drawer = document.querySelector("#detailEditorPanel").getBoundingClientRect();
    const inventory = document.querySelector("#inventoryContainer").getBoundingClientRect();
    const workspace = document.querySelector(".workspace").getBoundingClientRect();
    const players = document.querySelector("#focusPlayerRail").getBoundingClientRect();
    return {
      drawerX: drawer.left,
      drawerRight: drawer.right,
      inventoryX: inventory.left,
      inventoryRight: inventory.right,
      playersRight: players.right,
      workspaceRight: workspace.right,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
    };
  });
  await expect(page.locator("#focusPlayerListMount #playersList")).toBeVisible();
  // Focus keeps the selectors above the editor tabs, not a wizard heading.
  const focusHierarchy = await page.evaluate(() => ({
    context: document.querySelector('.layout-context-bar').getBoundingClientRect().top,
    nav: document.querySelector('.app-workflow-nav').getBoundingClientRect().top,
  }));
  expect(focusHierarchy.context).toBeLessThan(focusHierarchy.nav);
  await expect(page.locator(".layout-intro")).toBeHidden();
  expect(focus.inventoryX).toBeGreaterThan(focus.playersRight);
  expect(focus.drawerX).toBeGreaterThan(focus.inventoryRight);
  expect(focus.drawerRight).toBeLessThanOrEqual(focus.workspaceRight);
  expect(focus.overflow).toBeLessThanOrEqual(0);
  await expect(page.locator("#detailItemSearch")).toHaveValue("minecraft:stone");

  // The header uses the saved mode's short label, while player data retains
  // the technical value. A form refresh must update both without an edit.
  await page.evaluate(() => MCBEAbilityView.applyStatsFormModel(
    {gamemode:document.getElementById('statGamemode')},
    {gamemode:MCBEAbilityView.gamemodeDisplayModel(5)},
  ));
  await expect(page.locator('#focusFactMode')).toHaveText('Weltvorgabe');
  await expect(page.locator('#focusFactMode')).toHaveAttribute('title', 'Verwendet die Spielmodus-Vorgabe der Welt oder des Servers.');
  await expect(page.locator('#statGamemode')).toHaveValue('Standard/Weltmodus (Default) · NBT-Wert 5');
  await page.setViewportSize({width:1280,height:900});
  const clippedFacts = await page.locator('.focus-context-facts strong').evaluateAll(nodes =>
    nodes.filter(node => node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1).map(node => node.id));
  expect(clippedFacts).toEqual([]);
  await page.setViewportSize({width:1440,height:900});

  // World and player selection are CONTEXT switches, not numbered steps.
  // Editing player data and inventory are independent workspaces.
  await expect(page.locator("#layoutCurrentPlayer")).not.toBeEmpty();
  await page.locator('.layout-context-chip[data-workflow-view="player"]').click();
  await expect(page.locator("#layoutViewTitle")).toHaveText("Spieler auswählen");
  await expect(page.locator("#dashboardPanel")).toBeHidden();
  await page.locator('.app-workflow-nav button[data-workflow-view="player-edit"]').click();
  await expect(page.locator("#layoutViewTitle")).toHaveText("Spielerdaten bearbeiten");
  await expect(page.locator("#dashboardPanel")).toBeVisible();
  // Changing layout from the standalone player-data editor must not leave
  // Classic on a route that Classic does not present in its navigation.
  await selectLayout(page, "classic");
  await expect(page.locator("body")).toHaveAttribute("data-workflow-view", "player");
  await selectLayout(page, "focus");
  await page.locator('.app-workflow-nav button[data-workflow-view="inventory"]').click();
  await expect(page.locator("#layoutViewTitle")).toHaveText("Inventar bearbeiten");
  await expect(page.locator("#inventoryContainer")).toBeVisible();

  await selectLayout(page, "classic");
  await expect(page.locator("html")).toHaveAttribute("data-layout", "classic");
  await expect(page.locator(".layout-intro")).toBeHidden();
  await expect(page.locator("#themeSelect")).toHaveValue("light");
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(originalItem);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  expect(browserErrors).toEqual([]);
});

test("alternative layouts preserve live warnings without duplicate world cards in player selection and save review", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.route("**/api/world/presence", route => route.fulfill({ json: {
    success: true, other_sessions: 1, same_player_sessions: 1,
    other_dirty_sessions: 1, same_player_dirty_sessions: 1,
  } }));
  await openDragFixture(page);
  await page.evaluate(() => updateWorldPresence());
  await page.evaluate(() => MCBEWorldStatusView.applyLoadErrorPanel(
    document.getElementById("loadErrorPanel"),
    MCBEWorldStatusView.loadErrorHtml({ message: "Spieler konnte nicht erneut geladen werden." }),
  ));
  await page.locator("#worldName").evaluate(node => {
    node.textContent = "Unsere gemeinsame Abenteuerwelt mit einem besonders langen Namen";
  });

  for (const layout of ["focus", "studio"]) {
    await selectLayout(page, layout);
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      for (const view of ["inventory", "player-edit", "player", "save", "inventory"]) {
        const selector = view === "player" ? '.layout-context-chip[data-workflow-view="player"]'
          : view === "save" ? "#layoutSaveAction" : `.app-workflow-nav [data-workflow-view="${view}"]`;
        await page.locator(selector).click();
        const host = layout === "focus" && view === "inventory" ? "#inventoryContainer"
          : layout === "focus" && view === "player-edit" ? "#dashboardPanel" : "#worldSection";
        const warning = page.locator(`${host} #worldPresenceBanner`);
        await expect(warning).toBeVisible();
        await expect(warning).toContainText("Eine andere Sitzung bearbeitet vermutlich denselben Spieler");
        await expect(page.locator(`${host} #loadErrorPanel`)).toBeVisible();
        await expect(page.locator("#worldPresenceBanner")).toHaveCount(1);
        await expect(page.locator("#loadErrorPanel")).toHaveCount(1);
        if (view === "player" || view === "save") {
          await expect(page.locator("#selectedWorldBar")).toBeHidden();
          await expect(page.locator("#layoutCurrentWorld")).toBeVisible();
          expect(await page.locator("#layoutCurrentWorld").evaluate(node => {
            const style = getComputedStyle(node);
            return node.getBoundingClientRect().height <= parseFloat(style.lineHeight) * 2 + 1
              && style.webkitLineClamp === "2";
          })).toBe(true);
          await expect(page.locator(view === "player" ? "#playerManager" : "#saveWorkflowPanel")).toBeVisible();
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
      }
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  for (const layout of ["studio", "classic"]) {
    await selectLayout(page, layout);
    await expect(page.locator("#worldSection #worldPresenceBanner")).toBeVisible();
  }
  expect(browserErrors).toEqual([]);
});

test("Studio keeps warning details readable and its status log inside narrow windows", async ({ page }) => {
  await openDragFixture(page);
  await selectLayout(page, "studio");
  const message = "Die Welt wurde außerhalb des Editors verändert. Spieler neu laden, bevor Änderungen gespeichert werden.";
  await page.evaluate(message => logStatus(message, "warning", { key: "visual-warning", active: true }), message);
  const status = page.locator("#statusStackButton");
  const panel = page.locator("#statusStackPanel");

  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1600, height: 900 }, { width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 568 }]) {
    await page.setViewportSize(viewport);
    await expect(status).toBeVisible();
    await expect(page.locator("#statusStackSummary")).toHaveText(message);
    await expect(status).toHaveAttribute("data-focus-label", "Meldungen (1)");
    await expect(page.locator("#statusStackSummary")).toBeHidden();
    if (viewport.width >= 1600) {
      const centers = await page.evaluate(() =>
        [".logo", ".header-status-area", ".focus-command-bar"].map(selector => {
          const rect = document.querySelector(`.app-header ${selector}`).getBoundingClientRect();
          return rect.y + rect.height / 2;
        }));
      expect(Math.max(...centers) - Math.min(...centers)).toBeLessThanOrEqual(1);
    }
    const server = page.locator("#serverStatusBadge");
    await expect(server).toHaveCSS("font-size", "0px");
    await server.press("Enter");
    await expect(page.locator("#focusServerStatusPanel")).toBeVisible();
    await expect(page.locator("#focusServerStatusText")).toHaveText(await server.textContent());
    await page.keyboard.press("Escape");
    await expect(page.locator("#focusServerStatusPanel")).toBeHidden();
    await expect(server).toBeFocused();
    await status.focus();
    await page.keyboard.press("Enter");
    await expect(status).toHaveAttribute("aria-expanded", "true");
    await expect(panel).toBeVisible();
    await expect(panel).toContainText(message);
    const box = await panel.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    await page.keyboard.press("Enter");
    await expect(panel).toBeHidden();
  }
});

for (const [layout, stickyTop] of [["focus", 12], ["studio", 18]]) {
  test(`${layout} keeps the inspector in view while scrolling and locks the page for the item browser`, async ({ page }) => {
    const browserErrors = collectBrowserErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    // A presence update from another test session can change the page geometry
    // between measuring the scroll position and opening the item browser.
    await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
    await openDragFixture(page);
    await selectLayout(page, layout);
    await page.locator('[data-slot="0"]').click();
    await page.evaluate(() => window.scrollTo(0, 0));
    const inspector = page.locator(".workspace > .right-panel");
    const initialTop = (await inspector.boundingBox()).y;
    await page.evaluate(top => window.scrollTo(0, top + 60), initialTop);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(initialTop + 20);
    await expect.poll(async () => Math.abs((await inspector.boundingBox()).y - stickyTop)).toBeLessThan(2);
    await expect(page.locator("#detailItemSearch")).toBeInViewport();

    const trigger = page.locator("#btnBrowserDetail");
    await trigger.scrollIntoViewIfNeeded();
    const scrollBefore = await page.evaluate(() => window.scrollY);
    await trigger.click();
    await expect(page.locator("#itemBrowserOverlay")).toBeVisible();
    await expect(page.locator("#browserSearchInput")).toBeFocused();
    await expect(page.locator("body")).toHaveCSS("overflow-y", "hidden");
    await expect(page.locator("body")).toHaveCSS("position", "fixed");
    await page.keyboard.press("Escape");
    await expect(page.locator("#itemBrowserOverlay")).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(scrollBefore);
    await expect.poll(async () => Math.abs((await inspector.boundingBox()).y - stickyTop)).toBeLessThan(2);
    expect(browserErrors).toEqual([]);
  });
}

test("adaptive item icons keep equipment numbers separate in every layout", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  // A non-square flipbook catches accidental stretching when equipment tiles
  // grow vertically to make room for their optional number row.
  const iconUrl = "/api/icons/equipment-size-fixture";
  await page.route("**/api/icons/equipment-size-fixture", route => route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="48"><path fill="#ddd" d="M0 0h16v16H0z"/></svg>',
  }));
  await page.route("**/api/icons/status*", route => route.fulfill({ json: {
    success: true, count: 1, icons: { "minecraft:iron_helmet": { url: iconUrl } }, sources: [], warnings: [],
  } }));
  await openDragFixture(page, {
    inventory: Object.fromEntries([9, 100, 101, 102, 103, -106].map(slot => [slot, {
      slot, name: "minecraft:iron_helmet", count: 1, damage: 0,
      enchantments: slot === 102 ? [{ id: 0, lvl: 1 }] : [],
    }])),
  });
  await page.evaluate(() => loadLocalIconIndex({ rescan: false }));
  await expect(page.locator('.armor-slot[data-slot="103"] .item-visual img')).toBeVisible();

  for (const layout of ["classic", "studio", "focus"]) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await selectLayout(page, layout);
    for (const width of [1440, 1024, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      if (layout === "classic" && width <= 1024 && await page.locator("#toggleSlotNumbers").isHidden()) {
        await page.locator('.btn-toggle[data-panel="left"]').click();
      }
      for (const numbers of [true, false]) {
        await page.locator("#toggleSlotNumbers").setChecked(numbers);
        const geometry = await page.locator(".armor-slot, .offhand-slot").evaluateAll(slots => slots.map(slot => {
          const image = slot.querySelector(".item-visual img");
          const badge = slot.querySelector(".slot-number-badge");
          const s = slot.getBoundingClientRect(), i = image.getBoundingClientRect(), b = badge?.getBoundingClientRect();
          const caption = slot.querySelector(".studio-equipment-label").getBoundingClientRect();
          const frame = slot.closest(".armor-offhand-layout").getBoundingClientRect();
          const offhand = document.querySelector(".offhand-slot-container").getBoundingClientRect();
          return { slot: slot.dataset.slot, w: i.width, h: i.height, badge: !!badge,
            gap: b ? i.top - b.bottom : null,
            captionFrameGap: frame.bottom - caption.bottom,
            captionSeparatorGap: slot.classList.contains("armor-slot") ? offhand.top - caption.bottom : null,
            centered: (i.top + i.bottom - s.top - s.bottom) / 2,
            inside: i.top >= s.top && i.bottom <= s.bottom && i.left >= s.left && i.right <= s.right };
        }));
        expect(geometry).toHaveLength(5);
        for (const item of geometry) {
          const context = JSON.stringify({ layout, width, numbers, ...item });
          expect(item.badge, context).toBe(numbers);
          expect(item.w, context).toBeGreaterThanOrEqual(27);
          expect(item.w, context).toBeLessThanOrEqual(32);
          expect(Math.abs(item.w - item.h), context).toBeLessThan(0.5);
          expect(item.inside, context).toBe(true);
          expect(item.captionFrameGap, context).toBeGreaterThanOrEqual(8);
          if (layout === "classic" && width <= 560 && item.captionSeparatorGap !== null) {
            expect(item.captionSeparatorGap, context).toBeGreaterThanOrEqual(10);
          }
          if (numbers) expect(item.gap, context).toBeGreaterThanOrEqual(2);
          else expect(Math.abs(item.centered), context).toBeLessThan(1);
        }
        const inventoryIcon = await page.locator('.main-inventory-grid [data-slot="9"] img').boundingBox();
        expect(inventoryIcon.width).toBeLessThanOrEqual(40);
        if (width === 1440) expect(inventoryIcon.width).toBeGreaterThan(28);
        const enderHeading = await page.locator(".ender-title").boundingBox();
        const enderGrid = await page.locator(".ender-chest-grid").boundingBox();
        expect(enderGrid.y - enderHeading.y - enderHeading.height).toBeGreaterThanOrEqual(8);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      }
    }
  }
  expect(errors).toEqual([]);
});

test("layout preferences persist after reload and mobile controls remain accessible", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openAppWithEmptyWorldScan(page);
  await expect(page.locator("#layoutSelect")).toHaveValue("classic");
  await selectSetting(page, "themeSelect", "minecraft");
  // An existing installation has a color preference but no layout key yet.
  await page.evaluate(() => localStorage.removeItem("mcbe-inventory-editor:layout"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-layout", "classic");
  await expect(page.locator("#layoutSelect")).toHaveValue("classic");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "minecraft");
  await selectSetting(page, "layoutSelect", "focus");
  await page.reload();
  await expect(page.locator("#layoutSelect")).toHaveValue("focus");
  await expect(page.locator("html")).toHaveAttribute("data-layout", "focus");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "minecraft");
  await expect(page.locator("#layoutViewTitle")).toHaveText("Welt auswählen");
  for (const layout of ["studio", "focus", "classic"]) {
    await selectLayout(page, layout);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(overflow, `horizontal overflow in ${layout}`).toBeLessThanOrEqual(0);
    await expect(page.locator("#focusSettingsToggle")).toBeVisible();
    for (const viewport of [{ width: 320, height: 568 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport);
      const toggle = page.locator("#focusSettingsToggle");
      await toggle.press("Enter");
      const panel = page.locator("#focusSettingsPanel");
      await expect(panel).toBeVisible();
      const box = await panel.boundingBox();
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
      await page.locator("#languageSelect").focus();
      await expect(page.locator("#languageSelect")).toBeInViewport();
      await page.keyboard.press("Escape");
      await expect(panel).toBeHidden();
      await expect(toggle).toBeFocused();
    }
    if (layout !== 'classic') {
      await expect(page.locator('.layout-context-chip[data-workflow-view="world"]')).toBeVisible();
      await expect(page.locator('.layout-context-chip[data-workflow-view="player"]')).toBeVisible();
    } else {
      await expect(page.locator('.layout-context-bar')).toBeHidden();
    }
  }
  expect(browserErrors).toEqual([]);
});

test("Studio world selection keeps the card and world list stationary", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const worlds = Array.from({ length: 10 }, (_, i) => ({
    path: `tests/fixtures/worlds/StableWorld${i}`,
    name: `Welt ${i + 1}`,
    folder: `StableWorld${i}`,
    source_kind: "configured-root",
    source_label: "Konfigurierter Welt-Root",
    modified_ts: null,
    modified_iso: "",
  }));
  await page.route("**/api/scan_worlds", route => route.fulfill({ json: { success: true, worlds } }));
  await openAppAndWaitForScan(page);
  // Receiving headers does not mean the response body has been rendered yet.
  await expect(page.locator(".world-card")).toHaveCount(worlds.length);
  await expect(page.locator("#worldScanLoading")).toBeHidden();
  await selectSetting(page, "layoutSelect", "studio");
  const selection = page.locator("#selectedWorldBar");
  await expect(selection).toBeVisible();
  await expect(selection).toContainText("Keine Welt ausgewählt");
  await expect(page.locator("#btnLoad")).toBeDisabled();
  const geometry = async () => page.evaluate(() => ({
    card: document.getElementById("selectedWorldBar").getBoundingClientRect().toJSON(),
    picker: document.getElementById("worldPicker").getBoundingClientRect().toJSON(),
    list: document.getElementById("worldList").getBoundingClientRect().toJSON(),
  }));
  const before = await geometry();
  await page.locator(".world-card").first().click();
  await expect(selection).toContainText("Welt 1");
  await expect(page.locator("#btnLoad")).toBeEnabled();
  expect(await page.locator("body").evaluate(el => el.classList.contains("app-world-loaded"))).toBe(false);
  const after = await geometry();
  for (const part of ["card", "picker", "list"]) {
    expect(Math.abs(after[part].y - before[part].y), `${part} moved after selecting a world`).toBeLessThanOrEqual(1);
  }
  expect(Math.abs(after.card.height - before.card.height)).toBeLessThanOrEqual(1);
  await page.reload();
  await expect(selection).toContainText("Keine Welt ausgewählt");
  await selectSetting(page, "layoutSelect", "classic");
  await expect(selection).toBeHidden();
  await selectSetting(page, "layoutSelect", "focus");
  await expect(selection).toBeVisible();
  await expect(page.locator("#btnLoad")).toBeDisabled();
  await selectLayout(page, "studio");
  await expect(selection).toBeVisible();
});

test("Studio routine status messages keep the workspace stable across font metrics and window sizes", async ({ page }) => {
  await openAppWithEmptyWorldScan(page);
  await expect(page.locator("#worldScanLoading")).toBeHidden();
  await expect(page.locator("#serverStatusBadge")).not.toHaveText("Status wird geprüft");
  await selectLayout(page, "studio");
  const worldSection = page.locator("#worldSection");
  const top = () => worldSection.evaluate(node => node.getBoundingClientRect().top + window.scrollY);
  const messages = ["Keine Hinweise", "Welt ausgewählt. Klicke auf Laden, wenn du sie öffnen möchtest.", "Erfolgreich"];
  // Arial reproduces the header wrap seen with Linux's narrower font metrics.
  for (const font of ["Segoe UI", "Arial"]) {
    const style = await page.addStyleTag({ content: `body, button { font-family: "${font}", sans-serif !important; }` });
    for (const width of [320, 390, 1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      // Resize/font changes animate button sizes. Compare messages only after
      // those finite transitions finish; keep infinite loading animations out.
      await page.evaluate(async () => {
        const frames = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        await frames();
        await Promise.all(document.getAnimations()
          .filter(animation => Number.isFinite(animation.effect?.getComputedTiming().iterations))
          .map(animation => animation.finished.catch(() => {})));
        await frames();
      });
      let before;
      for (const message of messages) {
        await page.evaluate(message => logStatus(message, "success", { key: "stable-status" }), message);
        await expect(page.locator("#statusStackSummary")).toHaveText(message);
        const after = await top();
        if (before !== undefined) expect(Math.abs(after - before), `${font}, ${width}px, ${message}`).toBeLessThanOrEqual(1);
        before = after;
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
    }
    await style.evaluate(node => node.remove());
  }
});

test("world rescans retain keyboard focus and scroll when the results are unchanged", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const worlds = Array.from({ length: 28 }, (_, i) => ({
    path: `tests/fixtures/worlds/RescanWorld${i}`,
    name: `Rescan Welt ${String(i + 1).padStart(2, "0")}`,
    folder: `RescanWorld${i}`,
    source_kind: "configured-root",
  }));
  let releaseScan;
  let holdScan = false;
  await page.route("**/api/scan_worlds", async route => {
    if (holdScan) await new Promise(resolve => { releaseScan = resolve; });
    await route.fulfill({ json: { success: true, worlds } });
  });
  await openAppAndWaitForScan(page);
  for (const layout of ["studio", "focus"]) {
    await selectLayout(page, layout);
    holdScan = true;
    releaseScan = undefined;
    await page.locator("#btnRefreshWorlds").click();
    await expect.poll(() => Boolean(releaseScan)).toBe(true);
    const card = page.locator(".world-card").nth(20);
    await card.focus();
    const focusedPath = await card.getAttribute("data-world-path");
    const previousScroll = await page.locator("#worldList").evaluate(el => el.scrollTop);
    expect(previousScroll).toBeGreaterThan(0);
    releaseScan();
    await expect(page.locator("#worldScanLoading")).toBeHidden();
    await expect(page.locator(".world-card").nth(20)).toBeFocused();
    expect(await page.locator("#worldList").evaluate(el => el.scrollTop)).toBe(previousScroll);
    expect(await page.locator(":focus").getAttribute("data-world-path")).toBe(focusedPath);
  }
});

for (const failure of ["response", "connection"]) {
  test(`failed world rescans clear obsolete selectable results (${failure})`, async ({ page }) => {
    let failScan = false;
    await page.route("**/api/scan_worlds", route => {
      if (failScan) return failure === "connection" ? route.abort("failed")
        : route.fulfill({ status: 500, json: { success: false, error: "Synthetic scan failure" } });
      return route.fulfill({ json: { success: true, worlds: [
        { name: "Test A", folder: "A", path: "tests/fixtures/worlds/A" },
        { name: "Test B", folder: "B", path: "tests/fixtures/worlds/B" },
      ] } });
    });
    await openAppAndWaitForScan(page);
    await expect(page.locator(".world-card")).toHaveCount(2);
    failScan = true;
    await page.locator("#btnRefreshWorlds").click();
    await expect(page.locator("#worldScanEmpty")).toContainText(failure === "connection" ? "Weltsuche nicht erreichbar" : "Weltsuche fehlgeschlagen");
    await expect(page.locator(".world-card")).toHaveCount(0);
    await page.locator("#worldSearchInput").press("Enter");
    await expect(page.locator("#btnLoad")).toBeDisabled();
  });
}

test("Studio keeps the world load action in view while long search results scroll independently", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const worlds = Array.from({ length: 28 }, (_, i) => ({
    path: `tests/fixtures/worlds/StudioWorld${i}`,
    name: `Studio Welt ${i + 1}`,
    folder: `StudioWorld${i}`,
    source_kind: "configured-root",
    source_label: "Konfigurierter Welt-Root",
    modified_ts: null,
    modified_iso: "",
  }));
  await page.route("**/api/scan_worlds", route => route.fulfill({ json: { success: true, worlds } }));
  await openAppAndWaitForScan(page);
  await selectSetting(page, "layoutSelect", "studio");
  await page.locator(".world-card").first().click();
  await expect(page.locator("#btnLoad")).toBeVisible();

  const initial = await page.evaluate(() => {
    const list = document.getElementById("worldList");
    const button = document.getElementById("btnLoad");
    return {
      scrollHeight: list.scrollHeight,
      clientHeight: list.clientHeight,
      listTop: list.getBoundingClientRect().top,
      buttonBottom: button.getBoundingClientRect().bottom,
      overflowY: getComputedStyle(list).overflowY,
      sidePosition: getComputedStyle(document.querySelector(".layout-controls")).position,
    };
  });
  expect(initial.scrollHeight).toBeGreaterThan(initial.clientHeight);
  expect(initial.overflowY).toBe("auto");
  expect(initial.buttonBottom).toBeLessThan(initial.listTop);
  expect(initial.buttonBottom).toBeLessThan(900);
  expect(initial.sidePosition).toBe("sticky");

  // Scrolling worlds does not scroll the page or move the load button.
  const afterListScroll = await page.evaluate(() => {
    const list = document.getElementById("worldList");
    const button = document.getElementById("btnLoad");
    const before = button.getBoundingClientRect().top;
    list.scrollTop = list.scrollHeight;
    return { listScrollTop: list.scrollTop, before, after: button.getBoundingClientRect().top };
  });
  expect(afterListScroll.listScrollTop).toBeGreaterThan(0);
  expect(afterListScroll.after).toBe(afterListScroll.before);

  // Expanded controls can naturally exceed the viewport. The sidebar follows
  // the page while the world list retains its own bounded scroll region.
  await page.setViewportSize({ width: 1440, height: 650 });
  await page.locator("#btnToggleManualWorld").click();
  await page.locator("#btnScanPaths").click();
  await page.evaluate(() => {
    window.scrollTo(0, document.documentElement.scrollHeight);
  });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
  const sidebarTop = await page.locator(".layout-controls").evaluate(el => el.getBoundingClientRect().top);
  expect(Math.abs(sidebarTop - 18)).toBeLessThanOrEqual(2);
});

test("Focus fits world selection to the window and keeps search and loading outside the results scroll", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1984, height: 1100 });
  const worlds = Array.from({ length: 28 }, (_, i) => ({
    path: `tests/fixtures/worlds/FocusWorld${i}`,
    name: `Welt ${String(i + 1).padStart(2, "0")} – Eine Welt mit einem längeren Namen`,
    folder: `FocusWorld${i}`,
    source_kind: i < 14 ? "minecraft-default" : "configured-root",
    source_label: i < 14 ? "Minecraft-Standardordner" : "Konfigurierter Welt-Root",
    modified_ts: null,
    modified_iso: "",
  }));
  await page.route("**/api/scan_worlds", route => route.fulfill({ json: { success: true, worlds } }));
  await openAppAndWaitForScan(page);
  await selectLayout(page, "focus");
  const worldWidth = await page.locator(".app-container").evaluate(el => el.getBoundingClientRect().width);
  const navigationGeometry = () => page.locator(".app-workflow-nav").evaluate(el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    const workspace = document.querySelector(".workspace").getBoundingClientRect();
    return {height: rect.height, radius: style.borderRadius, border: style.borderBottomWidth,
      gap: workspace.top - rect.bottom};
  });
  const worldNavigation = await navigationGeometry();
  await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
  expect(await navigationGeometry()).toEqual(worldNavigation);
  expect(worldNavigation.gap).toBeGreaterThanOrEqual(9);
  expect(worldNavigation.border).toBe("1px");
  expect(await page.locator(".app-container").evaluate(el => el.getBoundingClientRect().width)).toBe(worldWidth);
  await page.locator('.layout-context-chip[data-workflow-view="world"]').click();

  const geometry = () => page.evaluate(() => {
    const list = document.getElementById("worldList");
    return {
      pageRange: document.documentElement.scrollHeight - innerHeight,
      pageScroll: window.scrollY,
      overflow: document.documentElement.scrollWidth - innerWidth,
      listTop: list.getBoundingClientRect().top,
      listHeight: list.clientHeight,
      listScroll: list.scrollTop,
      listRange: list.scrollHeight - list.clientHeight,
      loadTop: document.getElementById("btnLoad").getBoundingClientRect().top,
      loadBottom: document.getElementById("btnLoad").getBoundingClientRect().bottom,
      searchBottom: document.getElementById("worldSearchInput").getBoundingClientRect().bottom,
    };
  });
  await expect(page.locator("#btnLoad")).toBeDisabled();
  const before = await geometry();
  // The separate navigation frame reserves its own padding and content gap.
  expect(before.listHeight).toBeGreaterThan(360);
  await page.locator(".world-card").first().click();
  await expect(page.locator("#btnLoad")).toBeEnabled();
  const selected = await geometry();
  expect(Math.abs(selected.listTop - before.listTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(selected.loadTop - before.loadTop)).toBeLessThanOrEqual(1);
  await page.locator(".world-card").first().press("End");
  await page.locator(".world-card").last().press("Enter");
  await expect(page.locator("#selectedWorldName")).toContainText("Welt 28");
  const scrolled = await geometry();
  expect(scrolled.listScroll).toBeGreaterThan(0);
  expect(scrolled.pageScroll).toBe(0);
  expect(Math.abs(scrolled.loadTop - selected.loadTop)).toBeLessThanOrEqual(1);

  for (const viewport of [{ width: 1440, height: 900 }, { width: 1181, height: 900 }]) {
    await page.setViewportSize(viewport);
    const current = await geometry();
    expect(current.pageRange).toBeLessThanOrEqual(1);
    expect(current.overflow).toBeLessThanOrEqual(0);
    expect(current.listRange).toBeGreaterThan(0);
    expect(current.loadBottom).toBeLessThan(current.listTop);
    expect(current.searchBottom).toBeLessThan(current.listTop);
  }
  await page.locator("#worldSearchInput").fill("Welt 28");
  await expect(page.locator(".world-card")).toHaveCount(1);
  await page.locator("#worldSearchInput").fill("Kein Treffer");
  await expect(page.locator("#worldScanEmpty")).toBeVisible();
  await expect(page.locator("#worldList")).toBeHidden();
  await expect(page.locator("#btnLoad")).toBeEnabled();
  await page.locator("#worldSearchInput").fill("");
  await expect(page.locator(".world-card")).toHaveCount(28);

  // Extra controls remain in the normal page flow, even on short screens.
  await page.setViewportSize({ width: 1366, height: 650 });
  await page.locator("#btnToggleManualWorld").click();
  await page.locator("#btnScanPaths").click();
  await expect(page.locator("#worldPath")).toBeVisible();
  await expect(page.locator("#scanPathsPanel")).toBeVisible();
  await page.locator("#btnLoad").scrollIntoViewIfNeeded();
  await expect(page.locator("#btnLoad")).toBeInViewport();
  expect((await geometry()).overflow).toBeLessThanOrEqual(0);
  expect(browserErrors).toEqual([]);
});

test("Studio omits duplicate world summaries in player data and inventory", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openDragFixture(page);
  await selectSetting(page, "layoutSelect", "studio");
  for (const view of ["player-edit", "inventory"]) {
    await page.locator(`.app-workflow-nav button[data-workflow-view="${view}"]`).click();
    await expect(page.locator("#selectedWorldBar")).toBeHidden();
    const borders = await page.evaluate(() => ({
      outer: getComputedStyle(document.getElementById("worldSection")).borderTopWidth,
      inner: getComputedStyle(document.getElementById("selectedWorldBar")).borderTopWidth,
    }));
    expect(borders.outer, `outer world-card border in ${view}`).toBe("0px");
    expect(borders.inner, `missing selected-world card border in ${view}`).toBe("1px");
  }
  await selectSetting(page, "layoutSelect", "classic");
  await expect(page.locator("html")).toHaveAttribute("data-layout", "classic");
});
