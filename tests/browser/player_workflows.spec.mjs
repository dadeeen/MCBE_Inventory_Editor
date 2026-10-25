import { expect, test } from "@playwright/test";
import {
  NORMAL_BASE_URL,
  VIEWER_BASE_URL,
  collectBrowserErrors,
  colorComponents,
  compositeColor,
  contrastRatio,
  openAppAndWaitForScan,
  openAppWithSmokeWorldScan,
  openDragFixture,
  openPlayerSwitchFixture,
  copyPlayerFixtureItem,
  captureBrowserEvidence,
  selectSetting,
} from "./fixtures/app.mjs";

test("import preview stays stable when clicking the new-player checkbox after typing", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  let previews = 0;
  let writes = 0;
  await page.route("**/api/server_status", route => route.fulfill({ json: { success: true, status: "offline", write_gate: { allowed: true, read_allowed: true } } }));
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await page.route("**/api/player/import_preview", route => {
    previews += 1;
    return route.fulfill({ json: {
      success: true, importable: true, import_token: { version: 1 },
      player: { player_key: "exported-player", label: "Archivspieler" },
      source_world_name: "Exportwelt", created_at: "2026-10-25",
      preview: { inventory_count: 36, stats: { pos: [128.5, 64, -2048] } },
      cleanup_warning: "Synthetischer Hinweis: Unbekannte Felder bleiben erhalten.",
    } });
  });
  await page.route("**/api/player/import", route => {
    writes += 1;
    return route.fulfill({ json: { success: false, error: "Unexpected test write" } });
  });
  await openDragFixture(page);
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await page.locator('.app-section-nav [data-workflow-view="player"]').click();
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.locator('[data-player-tool="playerImportDialog"]').click();
    await page.locator("#playerImportPath").fill(`/synthetic/player-${width}.mcbe-player.zip`);
    await expect(page.locator("#btnImportPlayer")).toBeEnabled();
    await expect(page.locator("#playerImportPreview")).toContainText("Archivspieler");
    const completedPreviews = previews;
    // Keep focus in the path until this real pointer click. An unconditional
    // change refresh used to move the centered dialog between down and up.
    await page.locator("#playerImportAsExportedKey").check();
    await expect(page.locator("#playerImportAsExportedKey")).toBeChecked();
    expect(previews).toBe(completedPreviews);
    await page.locator("#btnImportPlayer").click();
    await expect(page.locator("#confirmOverlay")).toBeVisible();
    await page.locator("#confirmCancel").click();
    await page.locator("#playerImportAsExportedKey").uncheck();
    await page.keyboard.press("Escape");
    await expect(page.locator("#playerImportDialog")).toBeHidden();
  }
  expect(writes).toBe(0);
  expect(errors).toEqual([]);
});

test("copy keeps target stats and asks to create the target ender chest", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  // Icon rescanning is unrelated to copying and shares a server-wide rate limit.
  await page.route("**/api/icons/scan", route => route.fulfill({ json: { success: true, count: 0 } }));
  const players = [
    { player_key: "target", label: "Zielspieler", editable: true, exportable: true, has_inventory_tag: true, has_ender_chest_tag: false },
    { player_key: "source", label: "Quellspieler", editable: true, exportable: true, has_inventory_tag: true, has_ender_chest_tag: true },
  ];
  await page.route("**/api/players", route => route.fulfill({ json: { success: true, world_name: "Smoke Test World", players } }));
  await page.route("**/api/player/load", route => {
    const source = route.request().postDataJSON().player_key === "source";
    return route.fulfill({ json: {
      success: true, player: players[source ? 1 : 0], player_revision: source ? "source-revision" : "target-revision",
      inventory: {}, ender_chest: source ? { 0: { slot: 0, name: "minecraft:stone", count: 1, damage: 0 } } : {},
      has_ender_chest: source,
      stats: { pos: source ? [0, 70, 0] : [120, 80, -95], dimension_id: source ? 1 : 0,
        health: source ? 20 : 7, xp_level: source ? 9 : 2, xp_progress: 0.5, food_level: 12, food_saturation: 3, gamemode: 0 },
      protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: source,
        ...(source ? { pos_opaque: true, stat_fields_opaque: { health: "Health" } } : {}) },
      hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
      items_db: { "minecraft:stone": ["Stein", "Stone"] }, ench_db: {},
      stack_limits: { __default__: 64 }, max_damage: { __default__: 0 },
    } });
  });
  let savedPayload;
  await page.route("**/api/player/save", route => {
    savedPayload = route.request().postDataJSON();
    return route.fulfill({ json: { success: true, player_revision: "saved-revision", backup_file: "synthetic-backup.zip" } });
  });
  await openAppWithSmokeWorldScan(page);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashPlayerTools"]').click();
  await page.locator("#copySourcePlayerSelect").selectOption("source");
  await page.locator("#copyInventoryArea").uncheck();
  await page.locator("#copyEnderArea").check();
  await page.locator("#copyStatsArea").check();
  await page.locator("#btnCopyFromPlayer").click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await expect(page.locator("#confirmMessage")).toContainText("Quellspieler");
  await expect(page.locator("#confirmMessage")).toContainText("Zielspieler");
  await page.locator("#confirmCancel").click();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  expect(savedPayload).toBeUndefined();
  await expect(page.locator("#statXpLevel")).toHaveValue("2");
  await page.locator("#btnCopyFromPlayer").click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await page.locator("#confirmOk").click();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  for (const [id, value] of [["statHealth", 7], ["statPosX", 120], ["statPosY", 80], ["statPosZ", -95]]) {
    await expect.poll(async () => Number(await page.locator(`#${id}`).inputValue())).toBe(value);
  }
  await page.locator('.app-section-nav button[data-workflow-view="save"]').click();
  await page.locator("#btnSaveWorkflowRun").click();
  await expect(page.locator("#confirmMessage")).toContainText("keinen EnderChestInventory-Tag");
  expect(savedPayload).toBeUndefined();
  await page.locator("#confirmOk").click();
  await expect.poll(() => savedPayload).toBeTruthy();
  expect(savedPayload.player_key).toBe("target");
  expect(savedPayload.allow_create_ender_chest).toBe(true);
  expect(savedPayload.stats).toEqual({ xp_level: 9 });
  expect(savedPayload.ender_chest).toHaveLength(1);
  expect(browserErrors).toEqual([]);
});

test("diagnostic player selection preserves edits until discard is confirmed", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await openPlayerSwitchFixture(page);
  await copyPlayerFixtureItem(page);
  await page.keyboard.press("Control+Shift+v");
  await expect(page.locator("#btnUndo")).toBeEnabled();
  await page.locator(".player-row").filter({ hasText: "Diagnose-Spieler" }).click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await expect(page.locator("#confirmMessage")).toContainText("ungespeicherte Änderungen");
  await captureBrowserEvidence(page, "diagnostic-discard-confirmation");
  await page.locator("#confirmCancel").click();
  expect(await page.evaluate(() => ({ key: currentPlayerKey, dirty: isDirty, item: inventory[1]?.name })))
    .toEqual({ key: "a", dirty: true, item: "minecraft:stone" });
  await expect(page.locator("#btnUndo")).toBeEnabled();
  await page.keyboard.press("Control+z");
  expect(await page.evaluate(() => ({ dirty: isDirty, item: inventory[1]?.name }))).toEqual({ dirty: false, item: undefined });
  await expect(page.locator("#btnRedo")).toBeEnabled();
  await page.locator("#btnRedo").click();
  expect(await page.evaluate(() => isDirty)).toBe(true);
  await page.locator(".player-row").filter({ hasText: "Diagnose-Spieler" }).click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await page.locator("#confirmOk").click();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  await expect(page.locator("#inventoryContainer")).toBeHidden();
  expect(await page.evaluate(() => ({ key: currentPlayerKey, dirty: isDirty, items: Object.keys(inventory).length })))
    .toEqual({ key: "bad", dirty: false, items: 0 });
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(browserErrors).toEqual([]);
});

for (const protectedFields of [true, false]) {
  test(`player load restores the new player's ${protectedFields ? "protected" : "editable"} controls`, async ({ page }) => {
    const browserErrors = collectBrowserErrors(page);
    const fixture = await openPlayerSwitchFixture(page, { fromProtected: !protectedFields, toProtected: protectedFields });
    for (const selector of ["#statHealth", "#abMovementSpeed", "#abFlySpeed", "#btnResetAbilitySpeeds", "#effectsContainer .eff-level"]) {
      await expect(page.locator(selector)).toHaveJSProperty("disabled", !protectedFields);
    }
    const request = page.waitForRequest("**/api/player/load");
    await page.locator(".player-row").filter({ hasText: "Spieler B" }).click();
    await request;
    await fixture.finishLoad(true);
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    for (const selector of ["#statHealth", "#abMovementSpeed", "#abFlySpeed", "#btnResetAbilitySpeeds", "#effectsContainer .eff-level"]) {
      await expect(page.locator(selector)).toHaveJSProperty("disabled", protectedFields);
      await expect(page.locator(selector)).not.toHaveAttribute("title", "Bearbeitung ist während des Ladens gesperrt.");
    }
    await expect(page.locator("#abilityMovementLockNote")).toHaveJSProperty("hidden", !protectedFields);
    if (!protectedFields) {
      // walkSpeed ist in Bedrock nur der Bezug für das Sichtfeld und folgt
      // deshalb der Laufgeschwindigkeit. Der Effekte-Reiter ist in diesem
      // Aufbau nicht geöffnet, deshalb läuft die Eingabe direkt über das DOM.
      await page.locator("#abMovementSpeed").evaluate(element => {
        element.value = "0.3";
        element.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await expect(page.locator("#abWalkSpeed")).toHaveValue("0.3");
    }
    expect(browserErrors).toEqual([]);
  });
}

for (const success of [true, false]) {
  test(`player load blocks editing and releases controls after ${success ? "success" : "failure"}`, async ({ page }) => {
    const browserErrors = collectBrowserErrors(page);
    const fixture = await openPlayerSwitchFixture(page);
    await copyPlayerFixtureItem(page);
    if (!success) {
      await page.keyboard.press("Control+Shift+v");
      await page.locator('[data-slot="2"]').click();
    }
    const before = await page.evaluate(() => JSON.stringify(inventory));
    const request = page.waitForRequest("**/api/player/load");
    await page.locator(".player-row").filter({ hasText: "Spieler B" }).click();
    if (!success) {
      await expect(page.locator("#confirmOverlay")).toBeVisible();
      await page.locator("#confirmOk").click();
    }
    await request;
    await expect(page.locator("#loadingOverlay")).toBeVisible();
    await expect(page.locator(".app-container")).toHaveJSProperty("inert", true);
    await expect(page.locator("#statHealth")).toBeDisabled();
    await expect(page.locator("#btnUndo")).toBeDisabled();
    await page.keyboard.press("Control+Shift+v");
    await page.keyboard.press("Control+z");
    expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
    expect(await page.evaluate(() => isDirty)).toBe(!success);
    if (success) await captureBrowserEvidence(page, "player-load-editing-locked");
    await fixture.finishLoad(success);
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    await expect(page.locator(".app-container")).toHaveJSProperty("inert", false);
    await expect(page.locator("#statHealth")).toBeEnabled();
    expect(await page.evaluate(() => currentPlayerKey)).toBe(success ? "b" : "a");
    if (success) {
      expect(await page.evaluate(() => Object.keys(inventory).length)).toBe(0);
      await expect(page.locator("#btnUndo")).toBeDisabled();
      await page.locator('[data-slot="1"]').click();
      await page.keyboard.press("Control+Shift+v");
      expect(await page.evaluate(() => inventory[1]?.name)).toBe("minecraft:stone");
      await expect(page.locator("#btnUndo")).toBeEnabled();
    } else {
      expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
      await expect(page.locator("#btnUndo")).toBeEnabled();
      await page.keyboard.press("Control+z");
      expect(await page.evaluate(() => isDirty)).toBe(false);
    }
    expect(browserErrors).toEqual([]);
  });
}

test("editing an effect preserves protected durations and unknown effect rows", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const effects = [
    { id: 1, amplifier: 0, duration: -1, ambient: false, show_particles: true, show_icon: true,
      opaque: true, opaque_reason: "Effekt enthält nicht unterstützte NBT-Typen oder Werte und wird geschützt erhalten." },
    { id: 100, amplifier: 400, duration: -20, ambient: false, show_particles: true, show_icon: true },
    { id: 3, amplifier: 0, duration: 601, ambient: false, show_particles: true, show_icon: true },
  ];
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  let savedPayload;
  await page.route("**/api/player/save", route => {
    savedPayload = route.request().postDataJSON();
    return route.fulfill({ json: { success: true, player_revision: "saved-revision", backup_file: "effects-test.zip" } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await openDragFixture(page, {
    effects, effects_db: { 1: ["Tempo", "Speed"], 3: ["Eile", "Haste"] },
    protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true, has_active_effects_tag: true, active_effect_entries_opaque: 1 },
  });
  await expect(page).toHaveURL(NORMAL_BASE_URL + "/");
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashEffects"]').click();
  const rows = page.locator("#effectsContainer .effect-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0).locator(".eff-duration")).toBeDisabled();
  await expect(rows.nth(1).locator(".effect-remove")).toBeDisabled();
  await rows.nth(2).locator(".eff-duration").fill("60");
  await rows.nth(2).locator(".eff-duration").blur();
  if (process.env.MCBE_QA_EFFECTS_SCREENSHOT) {
    await rows.nth(0).evaluate(element => element.scrollIntoView({ block: "start" }));
    await page.screenshot({ path: process.env.MCBE_QA_EFFECTS_SCREENSHOT, fullPage: false });
  }
  await page.locator('.app-section-nav button[data-workflow-view="save"]').click();
  await page.locator("#btnSaveWorkflowRun").click();
  await expect.poll(() => savedPayload).toBeTruthy();
  expect(savedPayload.effects.slice(0, 2)).toEqual(effects.slice(0, 2));
  expect(savedPayload.effects[2].duration).toBe(1200);
  expect(savedPayload.stats).toEqual({});
  expect(browserErrors).toEqual([]);
});

test("unverified stack limits preserve amounts and disable maximum actions", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  // This fixture tests local slot editing, not shared server status, asset
  // setup, or presence. Keep those reads out of the suite-wide rate budget.
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, status: "offline", write_gate: { allowed: true, read_allowed: true },
  } }));
  await page.route("**/api/item-db/status", route => route.fulfill({ json: {
    item_db: { status: "ok", verification: { verified: true }, counts: { items: 2 } },
  } }));
  await page.route("**/api/icons/status", route => route.fulfill({ json: {
    success: true, icons: {}, display_icons: {}, count: 0, sources: [], warnings: [],
  } }));
  await page.route("**/api/world/presence", route => route.fulfill({ json: {
    success: true, other_sessions: [],
  } }));
  await page.setViewportSize({ width: 1280, height: 900 });
  await openDragFixture(page, {
    inventory: {
      0: { slot: 0, name: "minecraft:red_cushion", count: 16, damage: 0 },
      1: { slot: 1, name: "minecraft:oak_sign", count: 1, damage: 0 },
    },
    items_db: { "minecraft:red_cushion": ["Rotes Kissen", "Red Cushion"], "minecraft:oak_sign": ["Eichenschild", "Oak Sign"] },
    addable_items: ["minecraft:red_cushion", "minecraft:oak_sign"],
    stack_limits: { __default__: 64, "minecraft:oak_sign": 16 },
  });
  await expect(page).toHaveTitle("Minecraft Bedrock Inventory Editor");
  expect(new URL(page.url()).hostname).toBe("127.0.0.1");
  await page.locator('[data-slot="0"]').click();
  await expect(page.locator("#slotQuickSubtitle")).toContainText("Stacklimit ungeprüft");
  await expect(page.locator("#btnQuickMaxStack")).toBeDisabled();
  await expect(page.locator("#detailCount")).toHaveValue("16");
  await page.mouse.move(0, 0);
  await page.locator("#slotQuickActions").scrollIntoViewIfNeeded();
  expect(await page.locator("#slotQuickActions").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  if (process.env.MCBE_QA_STACK_SCREENSHOT) {
    await page.locator("#detailEditorPanel").screenshot({ path: process.env.MCBE_QA_STACK_SCREENSHOT });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#panelToggle [data-panel="right"]').click();
  await expect(page.locator("#slotQuickSubtitle")).toBeVisible();
  await page.locator("#slotQuickActions").scrollIntoViewIfNeeded();
  expect(await page.locator("#slotQuickActions").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  if (process.env.MCBE_QA_STACK_MOBILE_SCREENSHOT) {
    await page.locator("#detailEditorPanel").screenshot({ path: process.env.MCBE_QA_STACK_MOBILE_SCREENSHOT });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.locator("#detailCount").fill("8");
  await expect(page.locator("#btnApplySingle")).toHaveCount(0);
  await expect(page.locator("#detailCount")).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#detailFormError")).toBeVisible();
  await expect(page.locator('[data-slot="0"] .item-count')).toHaveText("16");
  await page.locator("#detailCount").fill("16");
  await expect(page.locator("#btnApplySingle")).toHaveCount(0);
  await expect(page.locator("#detailFormError")).toBeHidden();
  await page.locator('[data-slot="1"]').click();
  await expect(page.locator("#btnQuickMaxStack")).toBeEnabled();
  await page.locator("#btnQuickMaxStack").click();
  await expect(page.locator("#detailCount")).toHaveValue("16");
  await expect(page.locator('[data-slot="1"] .item-count')).toHaveText("16");
  await page.locator('[data-slot="0"]').click();
  await expect(page.locator("#detailCount")).toHaveValue("16");
  await expect(page.locator("#btnApplySingle")).toHaveCount(0);
  await expect(page.locator('[data-slot="0"] .item-count')).toHaveText("16");
  await expect(page.locator("#slotQuickSubtitle")).toContainText("Stacklimit ungeprüft");
  await expect(page.locator("#btnQuickMaxStack")).toBeDisabled();
  expect(browserErrors).toEqual([]);
});

test("normal editor can load a world read-only before any write gate decision", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.route("**/api/players", async route => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        world_name: "Smoke Test World",
        players: [],
        capabilities: {},
        compatibility: {},
      }),
    });
  });

  await openAppWithSmokeWorldScan(page);
  await expect(page.locator(".world-card")).toHaveCount(1);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();

  await expect(page.locator("#loadErrorPanel")).toBeHidden();
  await expect(page.locator("#worldName")).toContainText("Smoke Test World");
  await expect(page.locator("#statusStackSummary")).toContainText("Welt geladen");
  await expect(page.locator("#statusStackButton")).toHaveClass(/warning/);
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

test("safe local-to-multiplayer migration is directly accessible and writes after backup", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  if (process.env.MCBE_QA_INVENTORY_SCREENSHOT) {
    await page.setViewportSize({ width: 1280, height: 820 });
  }
  const players = [
    { player_key: "local", label: "Lokaler Spieler", kind: "local", editable: true, exportable: true, has_inventory_tag: true },
    { player_key: "remote", label: "Multiplayer-Spieler", kind: "remote", editable: true, exportable: true, has_inventory_tag: true },
  ];
  await page.route("**/api/players", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      world_name: "Smoke Test World",
      players,
      capabilities: {},
      compatibility: {},
    }),
  }));
  await page.route("**/api/player/load", async route => {
    const playerKey = route.request().postDataJSON().player_key;
    const player = players.find(candidate => candidate.player_key === playerKey) || players[0];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        player,
        player_revision: `revision-${playerKey}`,
        server_guard_epoch: 0,
        inventory: {
          [-106]: { slot: -106, name: "minecraft:shield", count: 1, damage: 8 },
          0: { slot: 0, name: "minecraft:diamond_sword", count: 1, damage: 37 },
          1: { slot: 1, name: "minecraft:diamond_pickaxe", count: 1, damage: 84 },
          2: { slot: 2, name: "minecraft:bow", count: 1, damage: 23 },
          3: { slot: 3, name: "minecraft:torch", count: 64, damage: 0 },
          4: { slot: 4, name: "minecraft:cooked_beef", count: 32, damage: 0 },
          5: { slot: 5, name: "minecraft:water_bucket", count: 1, damage: 0 },
          6: { slot: 6, name: "minecraft:ender_pearl", count: 16, damage: 0 },
          7: { slot: 7, name: "minecraft:golden_apple", count: 5, damage: 0 },
          8: { slot: 8, name: "minecraft:firework_rocket", count: 64, damage: 0 },
          9: { slot: 9, name: "minecraft:cobblestone", count: 64, damage: 0 },
          10: { slot: 10, name: "minecraft:oak_log", count: 64, damage: 0 },
          11: { slot: 11, name: "minecraft:iron_ingot", count: 48, damage: 0 },
          12: { slot: 12, name: "minecraft:diamond", count: 12, damage: 0 },
          13: { slot: 13, name: "minecraft:redstone", count: 64, damage: 0 },
          14: { slot: 14, name: "minecraft:bread", count: 16, damage: 0 },
          15: { slot: 15, name: "minecraft:compass", count: 1, damage: 0 },
          100: { slot: 100, name: "minecraft:diamond_boots", count: 1, damage: 18 },
          101: { slot: 101, name: "minecraft:diamond_leggings", count: 1, damage: 24 },
          102: { slot: 102, name: "minecraft:diamond_chestplate", count: 1, damage: 31 },
          103: { slot: 103, name: "minecraft:diamond_helmet", count: 1, damage: 16 },
        },
        ender_chest: {},
        has_ender_chest: false,
        stats: {
          pos: [0, 64, 0],
          health: 20,
          gamemode: 0,
          xp_level: 0,
          xp_progress: 0,
          food_level: 20,
          food_saturation: 5,
        },
        effects: [],
        abilities: { movement_speed: 0.13, walk_speed: 0.1, fly_speed: 0.05, vertical_fly_speed: 1 },
        protected_nbt: {
          has_inventory_tag: true,
          has_ender_chest_tag: false,
          has_active_effects_tag: false,
          has_abilities_tag: true,
          movement_speed_locked: "modifiers",
        },
        hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
        items_db: {
          "minecraft:bow": ["Bogen", "Bow"],
          "minecraft:bread": ["Brot", "Bread"],
          "minecraft:cobblestone": ["Bruchstein", "Cobblestone"],
          "minecraft:compass": ["Kompass", "Compass"],
          "minecraft:cooked_beef": ["Steak", "Steak"],
          "minecraft:diamond": ["Diamant", "Diamond"],
          "minecraft:diamond_boots": ["Diamantstiefel", "Diamond Boots"],
          "minecraft:diamond_chestplate": ["Diamantharnisch", "Diamond Chestplate"],
          "minecraft:diamond_helmet": ["Diamanthelm", "Diamond Helmet"],
          "minecraft:diamond_leggings": ["Diamantbeinschutz", "Diamond Leggings"],
          "minecraft:diamond_pickaxe": ["Diamantspitzhacke", "Diamond Pickaxe"],
          "minecraft:diamond_sword": ["Diamantschwert", "Diamond Sword"],
          "minecraft:ender_pearl": ["Enderperle", "Ender Pearl"],
          "minecraft:firework_rocket": ["Feuerwerksrakete", "Firework Rocket"],
          "minecraft:golden_apple": ["Goldener Apfel", "Golden Apple"],
          "minecraft:iron_ingot": ["Eisenbarren", "Iron Ingot"],
          "minecraft:oak_log": ["Eichenstamm", "Oak Log"],
          "minecraft:redstone": ["Redstone-Staub", "Redstone Dust"],
          "minecraft:shield": ["Schild", "Shield"],
          "minecraft:torch": ["Fackel", "Torch"],
          "minecraft:water_bucket": ["Wassereimer", "Water Bucket"],
        },
        compat_item_aliases: {},
        addable_items: [],
        block_only_items: [],
        block_items: [],
        ench_db: {},
        enchantment_compatibility: {},
        effects_db: {
          1: ["Geschwindigkeit", "Speed", "Beschreibung für Mauszeiger.", "Description for pointer hover."],
          5: ["Stärke", "Strength", "Beschreibung für Tastaturfokus.", "Description for keyboard focus."],
        },
        stack_limits: {
          __default__: 64,
          "minecraft:bow": 1,
          "minecraft:compass": 1,
          "minecraft:diamond_boots": 1,
          "minecraft:diamond_chestplate": 1,
          "minecraft:diamond_helmet": 1,
          "minecraft:diamond_leggings": 1,
          "minecraft:diamond_pickaxe": 1,
          "minecraft:diamond_sword": 1,
          "minecraft:shield": 1,
          "minecraft:water_bucket": 1,
        },
        max_damage: {
          __default__: 0,
          "minecraft:bow": 384,
          "minecraft:diamond_boots": 429,
          "minecraft:diamond_chestplate": 528,
          "minecraft:diamond_helmet": 363,
          "minecraft:diamond_leggings": 495,
          "minecraft:diamond_pickaxe": 1561,
          "minecraft:diamond_sword": 1561,
          "minecraft:shield": 336,
        },
        compatibility: {},
      }),
    });
  });
  let transferPreviewRequests = 0;
  await page.route("**/api/player/state_transfer_preview", route => {
    transferPreviewRequests += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        direction: "local_to_multiplayer",
        source_player: players[0],
        target_player: players[1],
        server_guard_epoch: 0,
        transfer_token: { version: 2, source_player_key: "local", target_player_key: "remote" },
        plan: {
          groups: [
            { id: "inventory", label: "Inventar und Ausrüstung", copied_fields: ["Inventory"], cleared_fields: [], change_count: 4 },
            { id: "progress", label: "Erfahrung und Fortschritt", copied_fields: ["PlayerLevel"], cleared_fields: [], change_count: 2 },
          ],
          skipped_source_fields: ["UniqueID"],
          preserved_target_fields: ["UniqueID", "ServerId"],
          structured_fields: {
            abilities: {
              copied_fields: ["mayfly"],
              cleared_fields: transferPreviewRequests === 1 ? ["invulnerable"] : [],
              preserved_target_fields: ["TargetAddon"],
              skipped_source_fields: ["<img src=x onerror=alert(1)>"],
            },
            attributes: {
              copied_fields: ["Attributes[minecraft:health]"],
              cleared_fields: [],
              preserved_target_fields: [],
              skipped_source_fields: [],
            },
          },
        },
      }),
    });
  });
  let releaseTransferResponse;
  const transferResponseGate = new Promise(resolve => { releaseTransferResponse = resolve; });
  await page.route("**/api/player/state_transfer", async route => {
    await transferResponseGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        backup_file: "Smoke_Test_World__automatic__20260726T182657Z__f6466a9132f41373.zip",
        validation: { transferred_field_count: 6, target_identity_preserved: true },
      }),
    });
  });

  await openAppAndWaitForScan(page);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  if (process.env.MCBE_QA_INVENTORY_SCREENSHOT) {
    const dismissIconHint = page.locator("#btnIconHintDismiss");
    if (await dismissIconHint.isVisible()) {
      await dismissIconHint.click();
    }
    await page.evaluate(() => {
      document.querySelector(".inventory-section .grid-title")?.scrollIntoView({ block: "start" });
      window.scrollBy(0, -24);
    });
    await page.mouse.move(1200, 40);
    await page.screenshot({ path: process.env.MCBE_QA_INVENTORY_SCREENSHOT, fullPage: false });
  }

  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator(".player-row").filter({ hasText: "Multiplayer-Spieler" }).click();
  await expect(page.locator("body")).toHaveAttribute("data-workflow-view", "player");
  await expect(page.locator("#dashboardPanel")).toBeVisible();
  await expect(page.locator("#inventoryContainer")).toBeHidden();
  await page.locator(".player-row").filter({ hasText: "Lokaler Spieler" }).click();
  await expect(page.locator("body")).toHaveAttribute("data-workflow-view", "player");
  await selectSetting(page, "themeSelect", "light");
  await page.locator('.tab-btn-dash[data-tab-dash="dashEffects"]').click();
  await expect(page.locator("#abilityMovementLockNote")).toBeVisible();
  await expect(page.locator("#abilityMovementLockNote")).toContainText("Modifikatoren");
  await expect(page.locator("#abMovementSpeed")).toBeDisabled();
  await expect(page.locator("#abMovementSpeed")).toHaveValue("0.13");
  const abilityTheme = await page.evaluate(() => {
    const well = getComputedStyle(document.querySelector(".abilities-section"));
    const warning = getComputedStyle(document.querySelector("#abilityMovementLockNote"));
    return {
      wellBackground: well.backgroundColor,
      warningColor: warning.color,
      warningBackground: warning.backgroundColor,
    };
  });
  expect(colorComponents(abilityTheme.wellBackground).a).toBe(1);
  expect(contrastRatio(abilityTheme.warningColor, compositeColor(abilityTheme.warningBackground, abilityTheme.wellBackground))).toBeGreaterThanOrEqual(4.5);
  await expect(page.locator("#abilityScopeNote")).toContainText("Spielmodus und Spielerberechtigung");
  await expect(page.locator("#abWalkSpeedNote")).toContainText("nur auf das Sichtfeld");
  await expect(page.locator("#abVerticalFlySpeed")).toHaveValue("1");
  await expect(page.locator("#abMayfly, #abInstabuild, #abMaybuild")).toHaveCount(0);
  await page.locator('[data-player-tool="playerTransferDialog"]').click();
  await expect(page.locator("#playerTransferDialog")).toBeVisible();
  await expect(page.locator("#stateTransferSourcePlayerSelect")).toHaveValue("local");
  await expect(page.locator("#stateTransferTargetPlayerSelect")).toHaveValue("remote");
  await expect(page.locator("#btnApplyStateTransfer")).toBeDisabled();

  await page.locator("#btnPreviewStateTransfer").click();
  await expect(page.locator("#stateTransferPreview")).toContainText("Lokaler Spieler → Multiplayer-Spieler");
  await expect(page.locator("#stateTransferPreview")).toContainText("Inventar, Ausrüstung und Enderchest werden übernommen");
  await expect(page.locator("#stateTransferPreview")).toContainText("Besitzbeziehungen werden nicht automatisch");
  await expect(page.locator("#stateTransferPreview .state-transfer-warning")).toContainText("1 vorhandener Zielwert wird entfernt");
  await expect(page.locator("#stateTransferDetailsOverlay")).toBeHidden();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  await expect(page.locator("#btnOpenStateTransferDetails")).toBeVisible();
  await page.locator("#btnOpenStateTransferDetails").click();
  await expect(page.locator("#stateTransferDetailsOverlay")).toBeVisible();
  await expect(page.locator("#stateTransferDetailsTitle")).toContainText("Technische Migrationsdetails");
  await expect(page.locator("#stateTransferDetailsBody")).toContainText("Am Ziel entfernt");
  await expect(page.locator("#stateTransferDetailsBody")).toContainText("abilities.invulnerable");
  await expect(page.locator("#stateTransferDetailsBody img")).toHaveCount(0);
  await expect(page.locator("#btnCloseStateTransferDetails")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#stateTransferDetailsOverlay")).toBeHidden();
  await expect(page.locator("#btnOpenStateTransferDetails")).toBeFocused();
  await expect(page.locator("#stateTransferPreview img")).toHaveCount(0);
  await expect(page.locator("#btnApplyStateTransfer")).toBeEnabled();

  await page.locator("#btnPreviewStateTransfer").click();
  await expect(page.locator("#stateTransferPreview .state-transfer-warning")).toHaveCount(0);
  await expect(page.locator("#stateTransferDetailsOverlay")).toBeHidden();
  await expect(page.locator("#btnApplyStateTransfer")).toBeEnabled();
  await page.locator("#btnApplyStateTransfer").click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await page.locator("#confirmOk").click();

  await expect(page.locator("#loadingOverlay")).toBeVisible();
  await expect(page.locator("#loadingText")).toContainText("Spielermigration läuft");
  await expect(page.locator("#stateTransferSourcePlayerSelect")).toBeDisabled();
  await expect(page.locator("#stateTransferTargetPlayerSelect")).toBeDisabled();
  await expect(page.locator("#btnPreviewStateTransfer")).toBeDisabled();
  await expect(page.locator("#btnApplyStateTransfer")).toBeDisabled();
  releaseTransferResponse();
  await expect(page.locator("#stateTransferPreview")).toContainText("Migration validiert");
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect(page.locator("#stateTransferPreview .state-transfer-result-path code")).toContainText("Smoke_Test_World__automatic__20260726T182657Z__f6466a9132f41373.zip");
  await expect(page.locator("#btnApplyStateTransfer")).toHaveText("Migration gespeichert");
  await expect(page.locator("#btnApplyStateTransfer")).toBeDisabled();
  const migrationResultFits = await page.locator("#stateTransferPreview").evaluate(element => (
    element.scrollWidth <= element.clientWidth + 1
  ));
  expect(migrationResultFits).toBe(true);
  await page.locator("#playerTransferDialog [data-close-player-tool]").click();

  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashEffects"]').click();
  await page.locator("#btnOpenEffectPicker").click();
  await expect(page.locator("#effectPickerDialog")).toBeVisible();
  await page.locator("#effectCatalogSearch").fill("speed");
  const speedOption = page.locator('.effect-picker-option[data-effect-id="1"]');
  await speedOption.click();
  await expect(page.locator("#effectPickerDescription")).toContainText("Beschreibung für Mauszeiger");
  await expect(speedOption).toHaveAttribute("aria-pressed", "true");
  const selectedEffectColors = await speedOption.evaluate(element => {
    const style = getComputedStyle(element);
    return { foreground: style.color, background: style.backgroundColor };
  });
  expect(contrastRatio(selectedEffectColors.foreground, selectedEffectColors.background)).toBeGreaterThanOrEqual(4.5);
  await page.locator("#effectCatalogLevel").fill("3");
  await page.locator("#effectCatalogDuration").fill("90");
  await page.locator("#btnAddEffect").click();
  await expect(page.locator("#effectPickerDialog")).toBeHidden();
  await expect(page.locator("#btnOpenEffectPicker")).toBeFocused();
  await expect(page.locator("#effectsContainer .effect-row")).toHaveCount(1);
  await expect(page.locator("#effectsContainer .eff-level")).toHaveValue("3");
  await expect(page.locator("#effectsContainer .eff-duration")).toHaveValue("90");
  await page.locator("#btnOpenEffectPicker").click();
  await expect(speedOption).toBeDisabled();
  await expect(speedOption).toContainText("Bereits aktiv");
  await page.locator("#btnCloseEffectPicker").focus();
  await page.keyboard.press("Control+z");
  await expect(page.locator("#effectsContainer .effect-row")).toHaveCount(1);
  await page.keyboard.press("Control+s");
  await expect(page.locator("#effectPickerDialog")).toBeVisible();
  await expect(page.locator("#saveReviewOverlay")).toBeHidden();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.locator("#effectPickerDialog")).toBeHidden();
  await expect(page.locator("#selectedWorldSafetyNote")).toBeVisible();
  const dirtyBadgeTheme = await page.locator("#selectedWorldSafetyNote").evaluate(element => {
    const style = getComputedStyle(element);
    const backgrounds = [];
    for (let current = element; current; current = current.parentElement) {
      backgrounds.push(getComputedStyle(current).backgroundColor);
    }
    return { color: style.color, backgrounds };
  });
  const dirtyBadgeBackground = dirtyBadgeTheme.backgrounds
    .slice()
    .reverse()
    .reduce((background, foreground) => compositeColor(foreground, background), colorComponents("rgb(255, 255, 255)"));
  expect(contrastRatio(dirtyBadgeTheme.color, dirtyBadgeBackground)).toBeGreaterThanOrEqual(4.5);

  await page.locator("#abFlySpeed").fill("0.2");
  await page.locator("#abWalkSpeed").fill("0.3");
  await page.locator("#abVerticalFlySpeed").fill("5");
  await page.locator("#btnResetAbilitySpeeds").click();
  await expect(page.locator("#abFlySpeed")).toHaveValue("0.05");
  await expect(page.locator("#abWalkSpeed")).toHaveValue("0.1");
  await expect(page.locator("#abVerticalFlySpeed")).toHaveValue("1");

  await page.locator('.app-section-nav button[data-workflow-view="save"]').click();
  await page.evaluate(() => {
    document.querySelector("#saveWorkflowSummary").innerHTML = window.MCBESaveWorkflowView.workflowSummaryHtml({
      summary: { total: 0, shown: [], hidden: 0 },
      validation: {
        errors: 0,
        warnings: 0,
        shown: [{ level: "info", label: "Zusätzliche NBT-Daten bleiben beim Speichern erhalten." }],
      },
      playerLabel: "Lokaler Spieler",
    });
    document.querySelector("#saveDecisionLog").innerHTML = window.MCBESaveWorkflowView.decisionLogHtml([
      { severity: "ok", title: "Backup", text: "Vor jedem tatsächlichen Speichern wird automatisch ein ZIP-Backup erstellt." },
      { severity: "warning", title: "Ersterstellung möglich", text: "Neue Tags werden erst beim Speichern passender Inhalte angelegt." },
    ]);
    document.querySelector("#saveDecisionDetails").open = true;
  });
  await expect(page.locator("#saveDecisionLog .decision-log-row")).toHaveCount(2);
  const diagnosticContrastSamples = await page.evaluate(() => {
    const sample = selector => {
      const element = document.querySelector(selector);
      const backgrounds = [];
      for (let current = element; current; current = current.parentElement) {
        backgrounds.push(getComputedStyle(current).backgroundColor);
      }
      return { color: getComputedStyle(element).color, backgrounds };
    };
    return [
      sample("#saveWorkflowSummary .save-validation-row.info span"),
      sample("#saveWorkflowSummary .save-validation-row.info p"),
      sample("#saveDecisionDetails summary span"),
      sample("#saveDecisionLog .decision-log-row.ok p"),
      sample("#saveDecisionLog .decision-log-row.warning p"),
    ];
  });
  for (const sample of diagnosticContrastSamples) {
    const background = sample.backgrounds
      .slice()
      .reverse()
      .reduce((underlay, overlay) => compositeColor(overlay, underlay), colorComponents("rgb(255, 255, 255)"));
    expect(contrastRatio(sample.color, background)).toBeGreaterThanOrEqual(4.5);
  }
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

test("unexpected server block responses are shown as errors instead of green status", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.route("**/api/players", async route => {
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        success: false,
        error: "Server läuft noch. Bitte Server stoppen, bevor die Welt gelesen oder bearbeitet wird.",
        write_gate: {
          allowed: false,
          read_allowed: false,
          read_only: false,
          reason: "Server läuft noch. Bitte Server stoppen.",
          server_status: { status: "online" },
        },
      }),
    });
  });

  await openAppWithSmokeWorldScan(page);
  await expect(page.locator(".world-card")).toHaveCount(1);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();

  await expect(page.locator("#loadErrorPanel")).toBeVisible();
  await expect(page.locator("#loadErrorPanel")).toContainText("Server läuft noch");
  // The header names the severity; the server message keeps its own wording.
  await expect(page.locator("#statusStackHeadline")).toHaveText("Meldungen");
  await expect(page.locator("#statusStackSummary")).toContainText("Server läuft noch");
  await expect(page.locator("#statusStackSummary")).not.toContainText("Fehler:");
  await expect(page.locator("#statusStackButton")).toHaveClass(/error/);
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

test("read-only viewer is visibly labeled and blocks write endpoints", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);

  const scanResponse = await openAppAndWaitForScan(page, VIEWER_BASE_URL);
  expect(scanResponse.status()).toBe(200);
  await expect(page.locator(".app-subtitle")).toContainText("READONLY / VIEWER");
  await expect(page.locator(".world-card")).toHaveCount(1);

  const result = await page.evaluate(async () => {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
    const response = await fetch("/api/player/save", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({
        world_path: "tests/fixtures/worlds/SmokeWorld",
        player_key: "local_player",
        inventory: [],
        stats: {},
      }),
    });
    return { status: response.status, data: await response.json() };
  });

  expect(result.status).toBe(403);
  expect(result.data.success).toBe(false);
  expect(result.data.read_only).toBe(true);
  expect(result.data.category).toBe("world_write");
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

test("scan auth failures are shown explicitly instead of as an empty world list", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.route("**/api/scan_worlds", async route => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ success: false, error: "Authentifizierung erforderlich." }),
    });
  });

  await openAppAndWaitForScan(page);
  await expect(page.locator("#worldScanEmpty")).toBeVisible();
  await expect(page.locator("#worldScanEmpty")).toContainText("Weltsuche fehlgeschlagen");
  await expect(page.locator("#worldScanEmpty")).toContainText("Authentifizierung erforderlich");
  await expect(page.locator(".world-card")).toHaveCount(0);
  expect(await page.locator("#worldScanEmpty").innerText()).not.toContain("Keine Welten automatisch gefunden");
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});
