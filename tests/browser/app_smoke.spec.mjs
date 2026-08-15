import { expect, test } from "@playwright/test";
import fs from "node:fs";

// Die Assertions prüfen deutsche UI-Texte; der Server wählt die Sprache über
// Accept-Language (Standard ohne Header ist Englisch).
test.use({ locale: "de-DE" });

const NORMAL_BASE_URL = "http://127.0.0.1:8765";
const VIEWER_BASE_URL = "http://127.0.0.1:8766";
const ITEM_AVAILABILITY = JSON.parse(
  fs.readFileSync("mcbe_editor/resources/item_availability.json", "utf8"),
);

function isExpectedHttpConsoleNoise(text) {
  return /Failed to load resource: the server responded with a status of (401|403|409)\b/.test(text || "");
}

function collectBrowserErrors(page) {
  const browserErrors = [];
  page.on("pageerror", error => browserErrors.push(error.message));
  page.on("console", message => {
    const text = message.text();
    if (message.type() === "error" && !isExpectedHttpConsoleNoise(text)) browserErrors.push(text);
  });
  return browserErrors;
}

function colorComponents(value) {
  const match = String(value).match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/);
  if (!match) throw new Error(`Unsupported computed color: ${value}`);
  return { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]), a: match[4] === undefined ? 1 : Number(match[4]) };
}

function compositeColor(foreground, background) {
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

function contrastRatio(foreground, background) {
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
async function dismissFirstRunSetup(page) {
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

async function openAppAndWaitForScan(page, baseURL = NORMAL_BASE_URL) {
  await dismissFirstRunSetup(page);
  const scanResponsePromise = page.waitForResponse(response =>
    response.url().endsWith("/api/scan_worlds") && response.request().method() === "GET",
  );
  await page.goto(baseURL + "/");
  const scanResponse = await scanResponsePromise;
  return scanResponse;
}

async function openAppWithEmptyWorldScan(page, baseURL = NORMAL_BASE_URL) {
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));
  return openAppAndWaitForScan(page, baseURL);
}

async function openAppWithSmokeWorldScan(page, baseURL = NORMAL_BASE_URL) {
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

test("app starts without JavaScript bootstrap errors and renders discovered worlds", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);

  const scanResponse = await openAppAndWaitForScan(page);
  expect(scanResponse.status()).toBe(200);
  const scanPayload = await scanResponse.json();
  expect(scanPayload.success).toBe(true);
  expect(scanPayload.worlds).toHaveLength(1);
  expect(scanPayload.worlds[0].path).toContain("SmokeWorld");

  await expect(page.locator("#worldSection")).toBeVisible();
  await expect(page.locator(".world-card")).toHaveCount(1);
  await expect(page.locator(".world-card")).toContainText("Smoke Test World");
  expect(browserErrors).toEqual([]);
});

test("German item search accepts German and English names", async ({ page }) => {
  await openAppWithEmptyWorldScan(page);
  const localizedItems = await page.evaluate(() => {
    const items = { "minecraft:diamond": ["Diamant", "Diamond"] };
    return {
      autocomplete: window.MCBEItemBrowserLogic.autocompleteItemHtml({
        id: "minecraft:diamond",
        de: "Diamant",
        en: "Diamond",
      }),
      germanMatches: window.MCBEItemBrowserLogic.autocompleteMatches(items, "diamant"),
      englishMatches: window.MCBEItemBrowserLogic.autocompleteMatches(items, "diamond"),
      enchantment: window.MCBEEnchantmentsView.enchantmentRowModel({
        id: 0,
        info: { name_de: "Schutz", name_en: "Protection", max_lvl: 4 },
      }),
      axolotlOption: window.MCBEEntityVariantEditor.axolotlColorOptions()[0],
    };
  });

  expect(localizedItems.autocomplete).toContain("<strong>Diamant</strong> (Diamond)");
  expect(localizedItems.germanMatches).toHaveLength(1);
  expect(localizedItems.englishMatches).toHaveLength(1);
  expect(localizedItems.enchantment.primaryName).toBe("Schutz");
  expect(localizedItems.enchantment.secondaryName).toBe("Protection");
  expect(localizedItems.axolotlOption.label).toBe("Leuzistisch (Leucistic)");
});

test.describe("English locale", () => {
  test.use({ locale: "en-US" });

  test("world selection and localized editor labels stay consistently English", async ({ page }) => {
    const browserErrors = collectBrowserErrors(page);
    await page.route("**/api/scan_worlds", async route => {
      const response = await route.fetch();
      const payload = await response.json();
      const firstWorld = payload.worlds[0];
      await route.fulfill({
        response,
        json: {
          ...payload,
          worlds: [
            firstWorld,
            {
              ...firstWorld,
              name: "Second Smoke World",
              folder: "SecondSmokeWorld",
              path: String(firstWorld.path).replace("SmokeWorld", "SecondSmokeWorld"),
            },
          ],
        },
      });
    });
    await openAppAndWaitForScan(page);

    const secondCard = page.locator(".world-card").filter({ hasText: "Second Smoke World" });
    await expect(secondCard).toContainText("Configured world root");
    await expect(secondCard).not.toContainText("Konfigurierter Welt-Root");
    const secondWorldAction = secondCard.locator(".world-card-action");
    await expect(secondWorldAction).toHaveText("Select");
    await secondCard.click();
    await expect(secondWorldAction).toHaveText("Selected");

    await page.locator("#btnToggleManualWorld").click();
    await expect(page.locator("#worldPath")).toHaveAttribute(
      "placeholder",
      "C:\\...\\minecraftWorlds\\<world folder> or /worlds/<world>",
    );

    const localizedModels = await page.evaluate(() => {
      const effect = window.MCBEEffectsLogic.addEffectDecision({
        effects: [],
        effectsDb: { 1: ["Geschwindigkeit", "Speed"] },
        selectedEffectId: 1,
      });
      const enchantment = window.MCBEEnchantmentsView.enchantmentRowModel({
        id: 0,
        info: { name_de: "Schutz", name_en: "Protection", max_lvl: 4 },
      });
      const enchantmentHtml = window.MCBEEnchantmentsView.enchantmentRowHtml(enchantment);
      const itemCard = window.MCBEItemBrowserLogic.browserItemCardHtml({
        id: "minecraft:diamond",
        names: ["Diamant", "Diamond"],
      });
      const itemAutocomplete = window.MCBEItemBrowserLogic.autocompleteItemHtml({
        id: "minecraft:diamond",
        de: "Diamant",
        en: "Diamond",
      });
      const itemSearchByGerman = window.MCBEItemBrowserLogic.autocompleteMatches({
        "minecraft:diamond": ["Diamant", "Diamond"],
      }, "diamant");
      const itemSearchByEnglish = window.MCBEItemBrowserLogic.autocompleteMatches({
        "minecraft:diamond": ["Diamant", "Diamond"],
      }, "diamond");
      const itemCount = window.MCBEItemBrowserLogic.browserCountText({ count: 2 });
      const apiClient = window.MCBEApiClient.createApiClient();
      const structuredError = apiClient.buildErrorMessage({
        code: "invalid_slot",
        params: { slot: 7 },
        message_key: "Ungültiger Slot: {slot}",
        message: "Ungültiger Slot: 7",
        error: "Ungültiger Slot: 7",
      });
      const serverPayload = window.MCBEWriteStatusView.localizeServerStatusPayload({
        server_status: {
          status: "unknown",
          message: "Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden.",
          message_key: "Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden.",
          message_params: {},
          technical_error: "Der angegebene Host ist unbekannt.",
        },
        write_gate: {
          allowed: false,
          reason: "Server läuft noch. Bitte Server stoppen.",
        },
      });
      return {
        effect,
        enchantment,
        enchantmentHtml,
        itemCard,
        itemAutocomplete,
        itemSearchByGerman,
        itemSearchByEnglish,
        itemCount,
        structuredError,
        serverPayload,
      };
    });
    expect(localizedModels.effect.toastMessage).toBe("+ Speed added");
    expect(localizedModels.enchantment.primaryName).toBe("Protection");
    expect(localizedModels.enchantment.secondaryName).toBe("");
    expect(localizedModels.enchantmentHtml).toContain("Protection");
    expect(localizedModels.enchantmentHtml).not.toContain("Schutz");
    expect(localizedModels.itemCard).toContain(">Diamond<");
    expect(localizedModels.itemAutocomplete).toContain("<strong>Diamond</strong>");
    expect(localizedModels.itemAutocomplete).not.toContain("Diamant");
    expect(localizedModels.itemSearchByGerman).toHaveLength(0);
    expect(localizedModels.itemSearchByEnglish).toHaveLength(1);
    expect(localizedModels.itemCount).toBe("2 Items · All categories · Type");
    expect(localizedModels.structuredError).toBe("Invalid slot: 7");
    expect(localizedModels.serverPayload.write_gate.reason).toBe("The server is still running. Please stop the server.");
    expect(localizedModels.serverPayload.server_status.message).toBe(
      "Server status unknown: server address could not be resolved.",
    );
    const transferToggleLabels = await page.evaluate(() => {
      const panel = document.querySelector(".player-transfer-panel.export-panel");
      const summary = panel?.querySelector("summary");
      if (!panel || !summary) return null;
      const label = () => getComputedStyle(summary, "::after").content.replace(/^[\"'](.*)[\"']$/, "$1");
      const collapsed = label();
      panel.open = true;
      const expanded = label();
      panel.open = false;
      return { collapsed, expanded };
    });
    expect(transferToggleLabels).toEqual({ collapsed: "Expand", expanded: "Collapse" });
    const bilingualRegressionModels = await page.evaluate(() => {
      const button = document.querySelector("#btnToggleEnderChest");
      if (!button) return null;
      const initialEnderChestLabel = button.textContent.trim();
      button.click();
      const collapsedEnderChestLabel = button.textContent.trim();
      button.click();
      const expandedEnderChestLabel = button.textContent.trim();
      const mountWarnings = window.MCBEMountView.warningListHtml(["Blockfreiheit geprüft."]);
      return {
        initialEnderChestLabel,
        collapsedEnderChestLabel,
        expandedEnderChestLabel,
        localPlayerLabel: window.t("Lokaler Spieler"),
        mountWarnings,
      };
    });
    expect(bilingualRegressionModels).not.toBeNull();
    expect(bilingualRegressionModels.initialEnderChestLabel).toBe("Collapse");
    expect(bilingualRegressionModels.collapsedEnderChestLabel).toBe("Expand");
    expect(bilingualRegressionModels.expandedEnderChestLabel).toBe("Collapse");
    expect(bilingualRegressionModels.localPlayerLabel).toBe("Local player");
    expect(bilingualRegressionModels.mountWarnings).toContain("Clearance checked.");
    expect(bilingualRegressionModels.mountWarnings).not.toContain("Blockfreiheit geprüft.");
    if (process.env.MCBE_QA_SCREENSHOT) {
      await page.screenshot({ path: process.env.MCBE_QA_SCREENSHOT, fullPage: false });
    }
    expect(browserErrors).toEqual([]);
  });
});

test.describe("item variant editors", () => {
  test.use({ locale: "en-US" });

  test("captured animal buckets are editable while incomplete buckets stay read-only", async ({ page }) => {
    const browserErrors = collectBrowserErrors(page);
    const player = {
      player_key: "local",
      label: "Local player",
      kind: "local",
      editable: true,
      exportable: true,
      has_inventory_tag: true,
    };
    await page.route("**/api/players", route => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        world_name: "Smoke Test World",
        players: [player],
        capabilities: {},
        compatibility: {},
      }),
    }));
    await page.route("**/api/player/load", route => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        player,
        player_revision: "variant-editor-revision",
        server_guard_epoch: 0,
        inventory: {
          0: {
            slot: 0,
            name: "minecraft:axolotl_bucket",
            count: 1,
            damage: 0,
            entity_variant: {
              entity_id: "minecraft:axolotl",
              kind_label_de: "Entity-Variante",
              kind_label_en: "Entity variant",
              variant: 1,
              key: "cyan",
              label_de: "Türkis",
              label_en: "Cyan",
              display_name_de: "Türkiser Axolotl",
              display_name_en: "Cyan Axolotl",
              is_baby: false,
              can_edit: true,
            },
          },
          1: {
            slot: 1,
            name: "minecraft:tropical_fish_bucket",
            count: 1,
            damage: 0,
          },
          2: {
            slot: 2,
            name: "minecraft:banner",
            count: 1,
            damage: 14,
          },
          3: {
            slot: 3,
            name: "minecraft:axolotl_bucket",
            count: 1,
            damage: 0,
            entity_variant: null,
            entity_variant_state: "generic",
          },
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
        abilities: {},
        protected_nbt: {
          has_inventory_tag: true,
          has_ender_chest_tag: false,
          has_active_effects_tag: false,
          has_abilities_tag: false,
        },
        hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
        items_db: {
          "minecraft:axolotl_bucket": ["Axolotleimer", "Axolotl Bucket"],
          "minecraft:banner": ["Banner", "Banner"],
          "minecraft:stone": ["Stein", "Stone"],
          "minecraft:tropical_fish_bucket": ["Tropenfischeimer", "Tropical Fish Bucket"],
        },
        compat_item_aliases: {},
        addable_items: [
          "minecraft:axolotl_bucket",
          "minecraft:banner",
          "minecraft:stone",
          "minecraft:tropical_fish_bucket",
        ],
        block_only_items: [],
        block_items: [],
        ench_db: {},
        enchantment_compatibility: {},
        effects_db: {},
        stack_limits: {
          __default__: 64,
          "minecraft:axolotl_bucket": 1,
          "minecraft:banner": 16,
          "minecraft:tropical_fish_bucket": 1,
        },
        max_damage: { __default__: 32767 },
        compatibility: {},
      }),
    }));

    await openAppWithSmokeWorldScan(page);
    await expect(page.locator(".world-card")).toHaveCount(1);
    await page.locator(".world-card").click();
    await page.locator("#btnLoad").click();
    await expect(page.locator("#inventoryContainer")).toBeVisible();

    const axolotlSlot = page.locator('[data-slot="0"]');
    await expect(axolotlSlot).toHaveCount(1);
    await axolotlSlot.click();
    await expect(page.locator("#detailEditorPanel")).toBeVisible();
    await expect(page.locator("#detailEntityVariantTitle")).toHaveText("Axolotl in a bucket");
    await expect(page.locator("#detailEntityVariantNote")).toContainText("all other data is preserved");
    await expect(page.locator("#detailEntityVariantNote")).not.toContainText("übrigen Daten");
    await expect(page.locator("#detailAxolotlColor")).toBeEnabled();
    await expect(page.locator('#detailAxolotlColor option[value="0"]')).toHaveText("Leucistic");
    await expect(page.locator('#detailAxolotlColor option[value="0"]')).not.toContainText("Leuzistisch");
    await expect(page.locator("#detailAxolotlColor")).toHaveValue("1");
    await expect(page.locator("#detailAxolotlAge")).toHaveValue("adult");
    await page.locator("#detailItemSearch").fill("minecraft:stone");
    await expect(page.locator("#detailPreviewName")).toHaveText("Stone");
    await expect(page.locator("#detailPreviewName")).not.toContainText("Axolotl");
    await page.locator("#detailItemSearch").fill("");
    await expect(page.locator("#detailPreviewName")).not.toContainText("Axolotl");
    await page.locator("#detailItemSearch").fill("minecraft:axolotl_bucket");
    await expect(page.locator("#detailPreviewName")).toHaveText("Cyan Axolotl");
    await page.locator("#detailAxolotlColor").selectOption("4");
    await page.locator("#detailAxolotlAge").selectOption("baby");
    await page.locator("#btnApplySingle").click();
    await expect(page.locator("#detailPreviewName")).toContainText("Blue Axolotl");
    await expect(page.locator("#detailAxolotlColor")).toHaveValue("4");
    await expect(page.locator("#detailAxolotlAge")).toHaveValue("baby");
    if (process.env.MCBE_QA_AXOLOTL_SCREENSHOT) {
      await page.screenshot({ path: process.env.MCBE_QA_AXOLOTL_SCREENSHOT, fullPage: false });
    }

    const genericAxolotlSlot = page.locator('[data-slot="3"]');
    await genericAxolotlSlot.click();
    await expect(page.locator("#detailEntityVariantNote")).toContainText("Valid creative bucket");
    await expect(page.locator("#detailAxolotlColor")).toBeDisabled();
    await expect(page.locator("#detailAxolotlAge")).toBeDisabled();
    await expect(page.locator("#detailAxolotlColor")).toHaveValue("generic");
    await expect(page.locator('#detailAxolotlColor option[value="generic"]')).toHaveText("Random when released");
    await expect(page.locator("#detailAxolotlAge")).toHaveValue("adult");
    await expect(page.locator('#detailAxolotlAge option[value="adult"]')).toHaveText("Adult when released");

    const genericFishSlot = page.locator('[data-slot="1"]');
    await expect(genericFishSlot).toHaveCount(1);
    await genericFishSlot.click();
    await expect(page.locator("#detailEntityVariantTitle")).toHaveText("Tropical fish in a bucket");
    await expect(page.locator("#detailEntityVariantNote")).toContainText("already captured tropical fish");
    await expect(page.locator("#detailTropicalFishPattern")).toBeDisabled();
    await expect(page.locator("#detailTropicalFishColor")).toBeDisabled();
    await expect(page.locator("#detailTropicalFishColor2")).toBeDisabled();
    if (process.env.MCBE_QA_GENERIC_BUCKET_SCREENSHOT) {
      await page.screenshot({ path: process.env.MCBE_QA_GENERIC_BUCKET_SCREENSHOT, fullPage: false });
    }

    const bannerSlot = page.locator('[data-slot="2"]');
    await expect(bannerSlot).toHaveCount(1);
    await bannerSlot.click();
    await expect(page.locator("#detailDataVariantGroup")).toBeVisible();
    await expect(page.locator("#detailDamageGroup")).toBeHidden();
    await expect(page.locator("#detailDataVariantLabel")).toHaveText("Banner color");
    await expect(page.locator("#detailDataVariant")).toHaveValue("14");
    await expect(page.locator("#detailDataVariant option:checked")).toHaveText("Orange Banner");

    if (process.env.MCBE_QA_VARIANT_SCREENSHOT) {
      await page.screenshot({ path: process.env.MCBE_QA_VARIANT_SCREENSHOT, fullPage: false });
    }
    expect(browserErrors).toEqual([]);
  });
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
  expect(browserErrors).toEqual([]);
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
        abilities: { mayfly: true, instabuild: true, invulnerable: true },
        protected_nbt: {
          has_inventory_tag: true,
          has_ender_chest_tag: false,
          has_active_effects_tag: false,
          has_abilities_tag: true,
        },
        hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
        items_db: {
          "minecraft:bow": ["Bogen", "Bow"],
          "minecraft:bread": ["Brot", "Bread"],
          "minecraft:cobblestone": ["Bruchstein", "Cobblestone"],
          "minecraft:compass": ["Kompass", "Compass"],
          "minecraft:cooked_beef": ["Gebratenes Rindfleisch", "Cooked Beef"],
          "minecraft:diamond": ["Diamant", "Diamond"],
          "minecraft:diamond_boots": ["Diamantstiefel", "Diamond Boots"],
          "minecraft:diamond_chestplate": ["Diamantbrustplatte", "Diamond Chestplate"],
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
  await page.route("**/api/player/state_transfer", async route => {
    await new Promise(resolve => setTimeout(resolve, 350));
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
  await page.locator("#themeSelect").selectOption("light");
  await page.locator('.tab-btn-dash[data-tab-dash="dashEffects"]').click();
  await expect(page.locator("#abilityRiskNote")).toBeVisible();
  const abilityTheme = await page.evaluate(() => {
    const well = getComputedStyle(document.querySelector(".abilities-section"));
    const row = getComputedStyle(document.querySelector(".ability-toggle"));
    const warning = getComputedStyle(document.querySelector("#abilityRiskNote"));
    return {
      wellBackground: well.backgroundColor,
      rowBackground: row.backgroundColor,
      warningColor: warning.color,
      warningBackground: warning.backgroundColor,
    };
  });
  expect(colorComponents(abilityTheme.wellBackground).a).toBe(1);
  expect(colorComponents(abilityTheme.rowBackground).a).toBe(1);
  expect(contrastRatio(abilityTheme.warningColor, compositeColor(abilityTheme.warningBackground, abilityTheme.wellBackground))).toBeGreaterThanOrEqual(4.5);
  const instantBreakControl = page.locator("label:has(#abInstabuild)");
  await expect(instantBreakControl).toContainText("Blöcke sofort abbauen");
  await expect(instantBreakControl).toHaveAttribute("title", /ohne normale Abbauzeit.*instabuild/i);
  await expect(page.locator("details.state-transfer-panel")).toBeVisible();
  await page.locator("details.state-transfer-panel summary").click();
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
  await expect(page.locator("#stateTransferPreview")).toContainText("Migration validiert");
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect(page.locator("#stateTransferPreview .state-transfer-result-path code")).toContainText("Smoke_Test_World__automatic__20260726T182657Z__f6466a9132f41373.zip");
  await expect(page.locator("#btnApplyStateTransfer")).toHaveText("Migration gespeichert");
  await expect(page.locator("#btnApplyStateTransfer")).toBeDisabled();
  const migrationResultFits = await page.locator("#stateTransferPreview").evaluate(element => (
    element.scrollWidth <= element.clientWidth + 1
  ));
  expect(migrationResultFits).toBe(true);

  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashEffects"]').click();
  await page.locator("#effectPickerSummary").click();
  const speedOption = page.locator('.effect-picker-option[data-effect-id="1"]');
  await speedOption.hover();
  await expect(page.locator("#effectPickerDescription")).toContainText("Beschreibung für Mauszeiger");
  await page.locator('.effect-picker-option[data-effect-id="5"]').focus();
  await expect(page.locator("#effectPickerDescription")).toContainText("Beschreibung für Tastaturfokus");
  await speedOption.click();
  await expect(page.locator("#effectPickerSummary")).toContainText("Geschwindigkeit");
  await page.locator("#effectPickerSummary").click();
  await expect(speedOption).toHaveAttribute("aria-selected", "true");
  await page.locator("#effectPickerSummary").click();
  await expect(page.locator("#btnAddEffect")).toBeEnabled();
  await page.locator("#btnAddEffect").click();
  await expect(page.locator("#effectsContainer .effect-row")).toHaveCount(1);
  await expect(page.locator("#effectsContainer .eff-level")).toHaveValue("1");
  await expect(page.locator("#effectsContainer .eff-duration")).toHaveValue("30");
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
  await page.locator("#btnResetAbilitySpeeds").click();
  await expect(page.locator("#abFlySpeed")).toHaveValue("0.05");
  await expect(page.locator("#abWalkSpeed")).toHaveValue("0.1");

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
  expect(browserErrors).toEqual([]);
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
  await expect(page.locator("#statusStackSummary")).toContainText("Fehler: Server läuft noch");
  await expect(page.locator("#statusStackButton")).toHaveClass(/error/);
  expect(browserErrors).toEqual([]);
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
  expect(browserErrors).toEqual([]);
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
  expect(browserErrors).toEqual([]);
});

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

test("item browser closes accessibly and restores keyboard focus", async ({ page }) => {
  await openAppWithEmptyWorldScan(page);
  await page.evaluate(() => {
    document.body.classList.add("app-world-loaded", "app-player-loaded");
    document.body.dataset.workflowView = "inventory";
    document.querySelector("#multiSelectPanel").style.display = "block";
  });

  const trigger = page.locator("#btnBrowserBulk");
  const overlay = page.locator("#itemBrowserOverlay");
  await trigger.focus();
  await trigger.click();

  await expect(overlay).toBeVisible();
  await expect(overlay).toHaveAttribute("aria-hidden", "false");
  await expect(page.locator("#browserSearchInput")).toBeFocused();
  await expect(page.locator("body")).toHaveClass(/item-browser-open/);

  await page.keyboard.press("Escape");

  await expect(overlay).toBeHidden();
  await expect(overlay).toHaveAttribute("aria-hidden", "true");
  await expect(trigger).toBeFocused();
  await expect(page.locator("body")).not.toHaveClass(/item-browser-open/);
});

test("item browser shows restrained availability labels including potion variants", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const player = {
    player_key: "local",
    label: "Lokaler Spieler",
    kind: "local",
    editable: true,
    exportable: true,
    has_inventory_tag: true,
  };
  const technicalDoubleSlab = "minecraft:black_wool_double_slab";
  const itemsDb = {
    "minecraft:allow": ["Erlauben", "Allow"],
    "minecraft:apple": ["Apfel", "Apple"],
    "minecraft:barrier": ["Barriere", "Barrier"],
    "minecraft:bedrock": ["Grundgestein", "Bedrock"],
    [technicalDoubleSlab]: ["Black Wool Double Slab", "Black Wool Double Slab"],
    "minecraft:ender_dragon_spawn_egg": ["Enderdrachen-Spawn-Ei", "Ender Dragon Spawn Egg"],
    "minecraft:frosted_ice": ["Brüchiges Eis", "Frosted Ice"],
    "minecraft:petrified_oak_slab": ["Versteinerte Eichenholzstufe", "Petrified Oak Slab"],
    "minecraft:potion": ["Trank", "Potion"],
    "minecraft:white_cushion": ["White Cushion", "White Cushion"],
  };
  const itemAvailability = JSON.parse(JSON.stringify(ITEM_AVAILABILITY));
  itemAvailability.classifications.unreviewed = ["minecraft:white_cushion"];
  const unreviewedDescription = [
    "Von Mojang registriert. Kann Welt-Experimente oder eine neuere Minecraft-Version benötigen.",
    "Der Editor aktiviert Experimente nicht.",
    "Verfügbarkeit und Spielverhalten wurden noch nicht geprüft.",
  ].join(" ");
  await page.route("**/api/players", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      world_name: "Smoke Test World",
      players: [player],
      capabilities: {},
      compatibility: {},
    }),
  }));
  await page.route("**/api/player/load", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      player,
      player_revision: "availability-revision",
      server_guard_epoch: 0,
      inventory: { 0: { slot: 0, name: "minecraft:apple", count: 1, damage: 0 } },
      ender_chest: {},
      has_ender_chest: false,
      stats: { pos: [0, 64, 0], health: 20, gamemode: 0, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5 },
      effects: [],
      abilities: {},
      protected_nbt: {
        has_inventory_tag: true,
        has_ender_chest_tag: false,
        has_active_effects_tag: false,
        has_abilities_tag: false,
      },
      hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
      items_db: itemsDb,
      compat_item_aliases: {},
      addable_items: Object.keys(itemsDb).filter(itemId => itemId !== technicalDoubleSlab),
      block_only_items: [technicalDoubleSlab],
      block_items: [
        "minecraft:allow",
        "minecraft:barrier",
        "minecraft:bedrock",
        "minecraft:frosted_ice",
        "minecraft:petrified_oak_slab",
      ],
      item_availability: itemAvailability,
      ench_db: {},
      enchantment_compatibility: {},
      item_components: {},
      effects_db: {},
      stack_limits: { __default__: 64, "minecraft:potion": 1 },
      max_damage: { __default__: 32767 },
      compatibility: {},
    }),
  }));

  await page.setViewportSize({ width: 1080, height: 820 });
  await openAppWithSmokeWorldScan(page);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();
  await page.locator('[data-slot="0"]').click();
  await page.locator("#btnBrowserDetail").click();
  await expect(page.locator("#itemBrowserOverlay")).toBeVisible();

  const cardFor = text => page.locator(".browser-item").filter({
    has: page.locator(".browser-item-id", { hasText: text }),
  });
  const expectedBadges = [
    [/^minecraft:barrier$/, "Technisch"],
    [/^minecraft:bedrock$/, "Kreativ"],
    [/^minecraft:ender_dragon_spawn_egg$/, "Befehlsitem"],
    [/^minecraft:allow$/, "Education"],
    [/^minecraft:frosted_ice$/, "Zustandsblock"],
    [/^minecraft:petrified_oak_slab$/, "Legacy"],
    [/^minecraft:white_cushion$/, "Neu · noch nicht geprüft"],
  ];
  for (const [itemLabel, badgeLabel] of expectedBadges) {
    const card = cardFor(itemLabel);
    await expect(card).toHaveCount(1);
    await expect(card.locator(".item-availability-badge")).toHaveText(badgeLabel);
  }
  await expect(cardFor(/^minecraft:apple$/).locator(".item-availability-badge")).toHaveCount(0);
  await expect(cardFor(/^minecraft:potion$/).locator(".item-availability-badge")).toHaveCount(0);
  await expect(cardFor(/^minecraft:black_wool_double_slab$/)).toHaveCount(0);
  await expect(cardFor(/^minecraft:bedrock$/).locator(".item-availability-badge")).toHaveAttribute(
    "title",
    "Im Kreativinventar verfügbar, im normalen Überlebensmodus nicht als Gegenstand erhältlich.",
  );
  await expect(cardFor(/^minecraft:white_cushion$/).locator(".item-availability-badge")).toHaveAttribute(
    "title",
    unreviewedDescription,
  );

  await cardFor(/^minecraft:potion$/).click();
  await expect(page.locator("#itemBrowserOverlay")).toBeHidden();
  await expect(page.locator("#detailPreviewAvailability")).toBeHidden();
  await page.locator("#detailDamage").fill("36");
  await expect(page.locator("#detailPreviewAvailability")).toBeVisible();
  await expect(page.locator("#detailPreviewAvailability")).toHaveText("Kreativ");
  await page.locator("#detailDamage").fill("0");
  await expect(page.locator("#detailPreviewAvailability")).toBeHidden();

  await page.locator("#btnBrowserDetail").click();
  await page.setViewportSize({ width: 429, height: 897 });
  await expect(cardFor(/^minecraft:barrier$/).locator(".item-availability-badge")).toBeVisible();
  const mobileLayout = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
    gridColumns: getComputedStyle(document.querySelector("#browserGrid")).gridTemplateColumns.split(" ").length,
  }));
  expect(mobileLayout.documentWidth).toBeLessThanOrEqual(mobileLayout.viewportWidth);
  expect(mobileLayout.gridColumns).toBe(1);

  await page.locator("#btnBrowserClose").click();
  await page.locator('[data-slot="0"]').click();
  await page.locator('[data-panel="right"]').click();
  await expect(page.locator("#detailItemSearch")).toBeVisible();
  await page.locator("#detailItemSearch").fill("ender_dragon");
  const mobileAutocomplete = page.locator("#detailItemAutocomplete");
  await expect(mobileAutocomplete).toBeVisible();
  await expect(mobileAutocomplete.locator(".autocomplete-item")).toHaveCount(1);
  await expect(mobileAutocomplete.locator(".item-availability-badge")).toHaveText("Befehlsitem");
  const mobileAutocompleteLayout = await mobileAutocomplete.evaluate(element => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    rowClientWidth: element.querySelector(".autocomplete-item")?.clientWidth || 0,
    rowScrollWidth: element.querySelector(".autocomplete-item")?.scrollWidth || 0,
  }));
  expect(mobileAutocompleteLayout.scrollWidth).toBeLessThanOrEqual(mobileAutocompleteLayout.clientWidth);
  expect(mobileAutocompleteLayout.rowScrollWidth).toBeLessThanOrEqual(mobileAutocompleteLayout.rowClientWidth);
  expect(browserErrors).toEqual([]);
});

test("light item browser keeps readable colors and a stable width while scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 947, height: 813 });
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));
  await openAppAndWaitForScan(page);
  await page.locator("#themeSelect").selectOption("light");
  await page.evaluate(() => {
    document.body.classList.add("app-world-loaded", "app-player-loaded");
    document.body.dataset.workflowView = "inventory";
    document.querySelector(".left-panel").classList.add("visible");
    document.querySelector(".right-panel").classList.add("visible");
    document.querySelector("#multiSelectPanel").style.display = "block";
  });

  await page.locator("#btnBrowserBulk").click();
  await expect(page.locator("#itemBrowserOverlay")).toBeVisible();
  // getBoundingClientRect includes the modal's opening scale transform. Wait
  // for that animation before taking the baseline used to detect real shifts.
  await expect(page.locator(".browser-box")).toHaveCSS("transform", "none");
  await page.evaluate(() => {
    const grid = document.querySelector("#browserGrid");
    grid.innerHTML = Array.from({ length: 150 }, (_, index) => {
      const name = index < 60 ? `Item ${index}` : `Very long browser item name ${index} that must not resize the grid`;
      return `<div class="browser-item"><div class="browser-item-name">${name}</div><div class="browser-item-id">minecraft:test_${index}</div></div>`;
    }).join("");
    const tooltip = document.createElement("div");
    tooltip.className = "slot-hover-card";
    tooltip.dataset.testid = "light-tooltip";
    tooltip.textContent = "Potion details";
    document.body.appendChild(tooltip);
  });

  const before = await page.evaluate(() => {
    const box = document.querySelector(".browser-box");
    const controls = document.querySelector(".browser-search-advanced");
    const grid = document.querySelector(".browser-grid");
    const modalStyle = getComputedStyle(box);
    const itemStyle = getComputedStyle(grid.querySelector(".browser-item"));
    const navStyle = getComputedStyle(document.querySelector(".app-section-nav"));
    const tooltipStyle = getComputedStyle(document.querySelector('[data-testid="light-tooltip"]'));
    const worldPickerStyle = getComputedStyle(document.querySelector(".world-picker"));
    const inventoryWellStyle = getComputedStyle(document.querySelector(".mc-grid"));
    return {
      controlsWidth: controls.getBoundingClientRect().width,
      gridWidth: grid.getBoundingClientRect().width,
      modalBackground: modalStyle.backgroundColor,
      modalColor: modalStyle.color,
      itemBackground: itemStyle.backgroundColor,
      itemColor: itemStyle.color,
      navBackground: navStyle.backgroundColor,
      navColor: navStyle.color,
      tooltipBackground: tooltipStyle.backgroundColor,
      tooltipColor: tooltipStyle.color,
      worldPickerBackground: worldPickerStyle.backgroundColor,
      inventoryWellBackground: inventoryWellStyle.backgroundColor,
    };
  });

  expect(Math.abs(before.controlsWidth - before.gridWidth)).toBeLessThanOrEqual(1);
  for (const [foreground, background] of [
    [before.modalColor, before.modalBackground],
    [before.itemColor, before.itemBackground],
    [before.navColor, before.navBackground],
    [before.tooltipColor, before.tooltipBackground],
  ]) {
    expect(colorComponents(background).a).toBe(1);
    expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(4.5);
  }
  expect(colorComponents(before.worldPickerBackground).a).toBe(1);
  expect(colorComponents(before.inventoryWellBackground).a).toBe(1);

  const afterWidth = await page.evaluate(() => {
    const grid = document.querySelector(".browser-grid");
    grid.scrollTop = grid.scrollHeight;
    return grid.getBoundingClientRect().width;
  });
  expect(Math.abs(afterWidth - before.gridWidth)).toBeLessThanOrEqual(1);
});

test("fresh browser storage does not turn unavailable data statuses into setup work", async ({ page }) => {
  await page.route("**/api/item-db/status", route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ success: false, error: "Item-DB status unavailable" }),
  }));
  await page.route("**/api/icons/status", route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ success: false, error: "Icon status unavailable" }),
  }));
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));

  await page.goto(NORMAL_BASE_URL + "/");

  await expect(page.locator("#assetDataStatusPanel")).toContainText(/Status nicht verfügbar|status unavailable/);
  await expect(page.locator("#firstRunSetupOverlay")).toBeHidden();
  await expect(page.locator("#setupTodoBanner")).toBeHidden();
  expect(await page.evaluate(() => window.localStorage.getItem("mcbe-inventory-editor:workspace"))).toBeNull();
});

test("regular tools update refreshes the dismissed setup banner and resolves releases automatically", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await dismissFirstRunSetup(page);
  let updateRequest = null;
  await page.route("**/api/item-db/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      item_db: {
        status: "ok",
        verification: { verified: false, reason: "missing" },
        source_version_present: true,
        source_version: {},
        counts: { items: 2048, effects: 37, enchantments: 42 },
      },
    }),
  }));
  await page.route("**/api/icons/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      icons: { "minecraft:apple": "/api/icons/minecraft:apple" },
      display_icons: {},
      count: 1,
      sources: [{ enabled: true, exists: true }],
      warnings: [],
    }),
  }));
  await page.route("**/api/update_db", route => {
    updateRequest = route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        returncode: 0,
        output: "Alles aktuell, keine Änderungen.",
        update_committed: true,
        reloaded: true,
        item_db: {
          status: "ok",
          verification: { verified: true, reason: "verified" },
          source_version_present: true,
          source_version: {},
          counts: { items: 2048, effects: 37, enchantments: 42 },
        },
      }),
    });
  });
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));

  await page.goto(NORMAL_BASE_URL + "/");

  const banner = page.locator("#setupTodoBanner");
  await expect(page.locator("#firstRunSetupOverlay")).toBeHidden();
  await expect(banner).toBeVisible();
  await expect(banner.locator("[data-role='detail']")).toContainText(/Item-Datenbank|Item database/);
  await expect(banner.locator("[data-role='detail']")).not.toContainText(/Item-Icons|Item icons/);

  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashUpdate"]').click();
  await expect(page.locator("#updateDbUseCache")).toHaveCount(0);
  await expect(page.locator("#dashUpdate")).toContainText(/automatisch geprüft|checked automatically/);

  await page.locator("#btnUpdateDbApply").click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  const updateResponse = page.waitForResponse(response => response.url().endsWith("/api/update_db"));
  await page.locator("#confirmOk").click();
  await updateResponse;
  await expect(page.locator("#itemDbStatusPanel")).toContainText(/geprüft|verified/);
  expect(Object.hasOwn(updateRequest || {}, "use_cache")).toBe(false);

  await page.locator('.tab-btn-dash[data-tab-dash="dashIcons"]').click();
  await expect(page.locator("#updateIconsUseCache")).toHaveCount(0);
  await expect(page.locator("#dashIcons")).toContainText(/automatisch geprüft|checked automatically/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashIcons"]').click();
  await expect(page.locator("#dashIcons")).toContainText(/automatisch geprüft|checked automatically/);

  await page.locator('.app-section-nav button[data-workflow-view="world"]').click();
  await expect(banner).toBeHidden();
  expect(browserErrors).toEqual([]);
});

test("first-run setup overlay guides through item DB and icons, then hands over to the banner", async ({ page }) => {
  // Force the fresh-install state: bundled item snapshot, no icons yet.
  let itemDbVerified = false;
  let requestedUpdateScope = undefined;
  await page.route("**/api/item-db/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      item_db: {
        status: "ok",
        matches_bundled_snapshot: true,
        verification: { verified: itemDbVerified, reason: itemDbVerified ? "verified" : "missing" },
        source_version_present: true,
        source_version: {},
        counts: { items: 2048, effects: 37, enchantments: 42 },
      },
    }),
  }));
  await page.route("**/api/icons/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, icons: {}, display_icons: {}, count: 0, sources: [], warnings: [] }),
  }));
  await page.route("**/api/update_db", route => {
    itemDbVerified = true;
    requestedUpdateScope = route.request().postDataJSON().only;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        returncode: 0,
        output: "Alles aktuell, keine Änderungen.",
        update_committed: true,
        reloaded: true,
        item_db: {
          status: "ok",
          matches_bundled_snapshot: true,
          verification: { verified: true, reason: "verified" },
          source_version_present: true,
          source_version: {},
          counts: { items: 2048, effects: 37, enchantments: 42 },
        },
      }),
    });
  });
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));

  await page.goto(NORMAL_BASE_URL + "/");

  const overlay = page.locator("#firstRunSetupOverlay");
  await expect(overlay).toBeVisible();
  await expect(overlay.locator("[data-first-run-todo='item_db'] [data-role='mark']")).toHaveText("○");
  await expect(overlay.locator("[data-first-run-todo='icons'] [data-role='mark']")).toHaveText("○");

  const banner = page.locator("#setupTodoBanner");
  await expect(banner).toBeHidden();

  // The setup action must remain a full verification run even if the tools
  // workspace currently points at a partial update scope.
  await page.locator("#updateOnlySelect").evaluate(select => { select.value = "items"; });
  await overlay.locator("[data-first-run-todo='item_db'] [data-role='run']").click();
  await expect(overlay.locator("[data-first-run-todo='item_db'] [data-role='mark']")).toHaveText("✓");
  await expect(overlay.locator("[data-first-run-todo='item_db'] [data-role='state']")).toHaveText(/^(Erledigt|Done)\.$/);
  expect(requestedUpdateScope).toBeNull();
  expect(await page.evaluate(() => JSON.parse(
    window.localStorage.getItem("mcbe-inventory-editor:workspace") || "{}",
  ).first_run_item_db_verified)).toBeUndefined();

  await page.locator("#btnFirstRunSetupClose").click();
  await expect(overlay).toBeHidden();

  // Dismissing must not lose the todos: the banner is the documented way back.
  await expect(banner).toBeVisible();
  await expect(banner.locator("[data-role='detail']")).toContainText(/Item-Icons|Item icons/);
  await expect(banner.locator("[data-role='detail']")).not.toContainText(/Item-Datenbank|Item database/);
  await page.locator("#btnSetupTodoBanner").click();
  await expect(overlay).toBeVisible();
  await expect(banner).toBeHidden();
  await expect(overlay.locator("[data-first-run-todo='icons'] [data-role='run']")).toBeFocused();

  // Modal keyboard behavior must return to the banner without leaving focus
  // behind the overlay.
  await page.keyboard.press("Escape");
  await expect(overlay).toBeHidden();
  await expect(banner).toBeVisible();
  await expect(page.locator("#btnSetupTodoBanner")).toBeFocused();
});
