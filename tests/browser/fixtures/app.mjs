import { expect } from "@playwright/test";
import fs from "node:fs";

export async function openSpecialProperties(dialog) {
  const properties = dialog.locator(".special-properties");
  await expect(properties).toBeVisible();
  if (!(await properties.evaluate(element => element.open))) await properties.locator("summary").click();
}

export async function openSpecialFixture(page, inventory, overrides = {}) {
  await page.route("**/api/server_status", route => route.fulfill({ json: { success: true, status: "offline", write_gate: { allowed: true, read_allowed: true } } }));
  await page.route("**/api/item-db/status", route => route.fulfill({ json: { item_db: { status: "ok", verification: { verified: true }, counts: { items: 8 } } } }));
  await page.route("**/api/icons/status*", route => route.fulfill({ json: { success: true, icons: {}, banner_patterns: {}, count: 0, sources: [], warnings: [] } }));
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  const ids = ["bundle", "undyed_shulker_box", "diamond", "diamond_sword", "writable_book", "written_book", "firework_rocket", "firework_star", "banner"];
  await openDragFixture(page, {
    inventory,
    items_db: Object.fromEntries(ids.map(id => [`minecraft:${id}`, [id, id]])),
    addable_items: ids.map(id => `minecraft:${id}`),
    stack_limits: { __default__: 64, "minecraft:bundle": 1, "minecraft:undyed_shulker_box": 1, "minecraft:diamond": 64, "minecraft:diamond_sword": 1, "minecraft:writable_book": 1, "minecraft:written_book": 16, "minecraft:firework_rocket": 64, "minecraft:firework_star": 64, "minecraft:banner": 16 },
    max_damage: { __default__: 32767, "minecraft:diamond_sword": 1561 },
    ...overrides,
  });
}

export async function prepareBannerTextures(page, { synthetic = false, publish = true } = {}) {
  const generated = await page.evaluate(() => {
    const codes = ["base", "illager", ...JSON.parse(document.getElementById("specialItemSchema").textContent).patterns];
    return Object.fromEntries(codes.map((code, index) => {
      const canvas = document.createElement("canvas"); canvas.width = 20; canvas.height = 40;
      const ctx = canvas.getContext("2d");
      const image = ctx.createImageData(20, 40);
      for (let y = 0; y < 40; y++) for (let x = 0; x < 20; x++) {
        const offset = (y * 20 + x) * 4;
        image.data.set([255, 255, 255, 0], offset);
        if (code === "base") image.data.set([200, 200, 200, 255], offset);
        else if (code === "illager") image.data.set([25, 155, 170, 255], offset);
        else if (code === "cre") image.data[offset + 3] = x < 10 ? 255 : 0;
        else if (code === "glb") image.data[offset + 3] = y < 20 ? 128 : 0;
        else if (code === "gra") image.data[offset + 3] = Math.round(255 * y / 39);
        else image.data[offset + 3] = (x + y + index) % (index + 2) === 0 ? 255 : 0;
      }
      ctx.putImageData(image, 0, 0);
      return [code, canvas.toDataURL("image/png").split(",")[1]];
    }));
  });
  const assets = Object.fromEntries(Object.keys(generated).map(code => [code, { url: `/api/icons/qa-banner-${code}` }]));
  await page.route("**/api/icons/qa-banner-*", route => {
    const code = new URL(route.request().url()).pathname.split("qa-banner-")[1];
    const path = !synthetic && process.env.MCBE_QA_BANNER_TEXTURES ? `${process.env.MCBE_QA_BANNER_TEXTURES}/banner_${code}.png` : null;
    return route.fulfill({ contentType: "image/png", body: path ? fs.readFileSync(path) : Buffer.from(generated[code], "base64") });
  });
  const response = { success: true, icons: {}, banner_patterns: assets, count: 0, sources: [], warnings: [] };
  if (publish) {
    await page.route("**/api/icons/status*", route => route.fulfill({ json: response }));
    await page.evaluate(() => loadLocalIconIndex());
  }
  return { assets, response, generated };
}

export const NORMAL_BASE_URL = "http://127.0.0.1:8765";

export const VIEWER_BASE_URL = "http://127.0.0.1:8766";

export const ITEM_AVAILABILITY = JSON.parse(
  fs.readFileSync("mcbe_editor/resources/item_availability.json", "utf8"),
);

export function isExpectedHttpConsoleNoise(text) {
  return /Failed to load resource: the server responded with a status of (401|403|409)\b/.test(text || "");
}

export function collectBrowserErrors(page) {
  const browserErrors = [];
  page.on("pageerror", error => browserErrors.push(error.message));
  page.on("console", message => {
    const text = message.text();
    if (message.type() === "error" && !isExpectedHttpConsoleNoise(text)) {
      const source = message.location().url;
      browserErrors.push(source ? `${text} (${source})` : text);
    }
  });
  return browserErrors;
}

export function colorComponents(value) {
  const match = String(value).match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/);
  if (!match) throw new Error(`Unsupported computed color: ${value}`);
  return { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]), a: match[4] === undefined ? 1 : Number(match[4]) };
}

export function compositeColor(foreground, background) {
  const fg = typeof foreground === "string" ? colorComponents(foreground) : foreground;
  const bg = typeof background === "string" ? colorComponents(background) : background;
  const alpha = fg.a + bg.a * (1 - fg.a);
  return {
    r: (fg.r * fg.a + bg.r * bg.a * (1 - fg.a)) / alpha,
    g: (fg.g * fg.a + bg.g * bg.a * (1 - fg.a)) / alpha,
    b: (fg.b * fg.a + bg.b * bg.a * (1 - fg.a)) / alpha,
    a: alpha,
  };
}

export function contrastRatio(foreground, background) {
  const channel = value => {
    const normalized = value / 255;
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  const fg = typeof foreground === "string" ? colorComponents(foreground) : foreground;
  const bg = typeof background === "string" ? colorComponents(background) : background;
  const luminance = color => 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
  const lighter = Math.max(luminance(fg), luminance(bg));
  const darker = Math.min(luminance(fg), luminance(bg));
  return (lighter + 0.05) / (darker + 0.05);
}

// The first-run setup overlay is modal and would intercept every click below.
// These tests cover the already-configured editor, so they start from a
// workspace that has dismissed it. See firstRunSetup tests for the overlay.
export async function dismissFirstRunSetup(page) {
  await page.addInitScript(() => {
    // The storage migration drops the workspace whenever the schema key does not
    // match, so it has to be seeded together with the flag.
    window.localStorage.setItem("mcbe-inventory-editor:storageSchema", "v3-dark-session-history");
    window.localStorage.setItem(
      "mcbe-inventory-editor:workspace",
      JSON.stringify({ first_run_setup_dismissed: true }),
    );
  });
}

export async function openAppAndWaitForScan(page, baseURL = NORMAL_BASE_URL) {
  await dismissFirstRunSetup(page);
  const scanResponsePromise = page.waitForResponse(response =>
    response.url().endsWith("/api/scan_worlds") && response.request().method() === "GET",
  );
  await page.goto(baseURL + "/");
  const scanResponse = await scanResponsePromise;
  return scanResponse;
}

export async function openAppWithEmptyWorldScan(page, baseURL = NORMAL_BASE_URL) {
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));
  return openAppAndWaitForScan(page, baseURL);
}

export async function openAppWithSmokeWorldScan(page, baseURL = NORMAL_BASE_URL) {
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      worlds: [{
        path: "tests/fixtures/worlds/SmokeWorld",
        name: "Smoke Test World",
        folder: "SmokeWorld",
        source_kind: "configured-root",
        source_label: "Konfigurierter Welt-Root",
        modified_ts: null,
        modified_iso: "",
      }],
    }),
  }));
  return openAppAndWaitForScan(page, baseURL);
}

export async function openDragFixture(page, overrides = {}, players = null) {
  const player = { player_key: "drag-player", label: "Drag Test", editable: true, exportable: true, has_inventory_tag: true, has_ender_chest_tag: true };
  // Synthetic editor flows must not register sessions on the shared server.
  // Page routes take precedence, preserving explicit presence scenarios.
  await page.context().route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await page.route("**/api/icons/scan", route => route.fulfill({ json: { success: true, icons: {}, count: 0 } }));
  await page.route("**/api/heartbeat", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await page.route("**/api/players", route => route.fulfill({ json: { success: true, world_name: "Drag Test World", players: players || [player] } }));
  await page.route("**/api/player/load", route => route.fulfill({ json: {
    success: true, player, player_revision: "drag-revision",
    inventory: {
      0: { slot: 0, name: "minecraft:stone", count: 1, damage: 0 },
      2: { slot: 2, name: "minecraft:carrot", count: 1, damage: 0 },
      3: { slot: 3, name: "minecraft:iron_helmet", count: 1, damage: 0 },
    }, ender_chest: {}, has_ender_chest: true,
    stats: { pos: [0, 64, 0], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 },
    protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true },
    hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
    items_db: { "minecraft:stone": ["Stein", "Stone"], "minecraft:carrot": ["Karotte", "Carrot"], "minecraft:iron_helmet": ["Eisenhelm", "Iron Helmet"] },
    ench_db: {}, stack_limits: { __default__: 64 }, max_damage: { __default__: 0 },
    // A function answers each load with the values current at that moment.
    ...(typeof overrides === "function" ? overrides(route.request().postDataJSON()) : overrides),
  } }));
  await openAppWithSmokeWorldScan(page);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
}

export async function openChangeHistory(page) {
  await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
  await page.locator('[data-tab-dash="dashSession"]').click();
  await expect(page.locator('#dashSession')).toBeVisible();
}

export async function openPlayerSwitchFixture(page, { fromProtected = false, toProtected = false } = {}) {
  const players = [
    { player_key: "a", label: "Spieler A", editable: true, exportable: true, has_inventory_tag: true },
    { player_key: "b", label: "Spieler B", editable: true, exportable: true, has_inventory_tag: true },
    { player_key: "bad", label: "Diagnose-Spieler", editable: false, exportable: false, reason: "Player NBT could not be read" },
  ];
  const payload = key => ({
    success: true, player: players.find(player => player.player_key === key), player_revision: `revision-${key}`,
    inventory: key === "a" ? { 0: { slot: 0, name: "minecraft:stone", count: 16, damage: 0 } } : {},
    ender_chest: {}, has_ender_chest: true,
    effects: [{ id: 1, amplifier: 0, duration: 600, show_particles: true, opaque: key === "a" ? fromProtected : toProtected }],
    effects_db: { 1: ["Tempo", "Speed"], 2: ["Langsamkeit", "Slowness"] },
    stats: { pos: [0, 64, 0], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 },
    protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true,
      ...((key === "a" ? fromProtected : toProtected)
        ? {
          stat_fields_opaque: { health: "Health" },
          ability_fields_opaque: { walk_speed: "walkSpeed", fly_speed: "flySpeed", vertical_fly_speed: "verticalFlySpeed" },
          movement_speed_locked: "value",
        } : {}) },
    hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
    items_db: { "minecraft:stone": ["Stein", "Stone"] }, ench_db: {},
    stack_limits: { __default__: 64 }, max_damage: { __default__: 0 },
  });
  let pendingLoad;
  for (const url of ["**/api/icons/scan", "**/api/world/presence", "**/api/heartbeat"]) {
    await page.route(url, route => route.fulfill({ json: { success: true, icons: {}, count: 0, other_sessions: [] } }));
  }
  // These synthetic player flows do not exercise background status services;
  // keep their repeated page starts out of the shared server rate limit.
  for (const [url, response] of Object.entries({
    "**/api/server_status": { success: true, server_status: { status: "offline" }, write_gate: { allowed: true } },
    "**/api/icons/status": { success: true, icons: {}, count: 0 },
    "**/api/item-db/status": { success: true, item_db: { status: "ready", counts: {} } },
    "**/api/backup/settings": { success: true, settings: { max_uncompressed_mib: 2048, source: "default" } },
    "**/api/backups": { success: true, backups: [] },
  })) {
    await page.route(url, route => route.fulfill({ json: response }));
  }
  await page.route("**/api/players", route => route.fulfill({ json: { success: true, world_name: "Smoke Test World", players } }));
  await page.route("**/api/player/load", route => {
    const key = route.request().postDataJSON().player_key;
    if (key === "b") { pendingLoad = route; return; }
    return route.fulfill({ json: payload(key) });
  });
  await openAppWithSmokeWorldScan(page);
  await expect(page).toHaveTitle("Minecraft Bedrock Inventory Editor");
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  return {
    finishLoad: async success => {
      expect(pendingLoad).toBeTruthy();
      await pendingLoad.fulfill({ json: success ? payload("b") : { success: false, error: "Synthetischer Ladefehler" } });
    },
  };
}

export async function copyPlayerFixtureItem(page) {
  await page.locator('[data-slot="0"]').click();
  await page.keyboard.press("Control+c");
  await page.locator('[data-slot="1"]').click();
}

export async function captureBrowserEvidence(page, name, selector = null) {
  const directory = process.env.MCBE_BROWSER_EVIDENCE_DIR;
  if (!directory) return;
  fs.mkdirSync(directory, { recursive: true });
  const target = selector ? page.locator(selector) : page;
  await target.screenshot({ path: `${directory}/${name}.png`, animations: "disabled",
    style: selector ? ".toast-container { visibility: hidden; }" : undefined });
}

export async function openBackupSettings(page) {
  await page.locator('.app-section-nav [data-workflow-view="tools"]').click();
  await page.locator('[data-tab-dash="dashBackups"]').click();
  await expect(page.locator("#backupSettingsPanel")).toBeVisible();
}

export async function openBackupSettingsApp(page) {
  // These settings tests do not exercise server probing. Keep those background
  // polls out of the shared rate-limit bucket used by the world workflow tests.
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, status: "offline", write_gate: { allowed: true, read_allowed: true },
  } }));
  await openAppWithEmptyWorldScan(page);
}

export async function selectSetting(page, id, value) {
  const select = page.locator(`#${id}`);
  if (!(await select.isVisible())) await page.locator("#focusSettingsToggle").click();
  await select.selectOption(value);
  if (await page.locator("#focusSettingsPanel").isVisible()) await page.locator("#focusSettingsToggle").click();
}

export async function selectLayout(page, layout) {
  const select = page.locator("#layoutSelect");
  if (!(await select.isVisible())) await page.locator("#focusSettingsToggle").click();
  await select.selectOption(layout);
  await expect(page.locator("html")).toHaveAttribute("data-layout", layout);
  if (await page.locator("#focusSettingsPanel").isVisible()) {
    await page.locator("#focusSettingsToggle").click();
  }
}

export async function openSlotSyncFixture(page) {
  await page.setViewportSize({ width: 1440, height: 1280 });
  await page.route('**/api/world/presence', route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page, {
    inventory: {
      9: { slot: 9, name: 'minecraft:stone', count: 12, damage: 0, display_name: 'Stone', lore: ['Keep me'], enchantments: [] },
      11: { slot: 11, name: 'minecraft:carrot', count: 5, damage: 0, display_name: '', lore: [], enchantments: [] },
      13: { slot: 13, name: 'minecraft:diamond', count: 4, damage: 0, display_name: '', lore: [], enchantments: [] },
    },
    ender_chest: { 0: { slot: 0, name: 'minecraft:carrot', count: 3, damage: 0 } },
    stack_limits: { 'minecraft:stone': 64, 'minecraft:carrot': 64, 'minecraft:diamond': 64 },
    addable_items: ['minecraft:stone', 'minecraft:carrot', 'minecraft:diamond'],
  });
  await expect(page.locator('#loadingOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => getPlayerLoadApp().isLoading())).toBe(false);
}

export async function dragSlot(page, from, to) {
  await from.scrollIntoViewIfNeeded();
  const a = await from.boundingBox(), b = await to.boundingBox();
  await page.mouse.move(a.x + 8, a.y + 8);
  await page.mouse.down();
  await page.mouse.move(b.x + 8, b.y + 8, { steps: 20 });
  await page.mouse.up();
}
