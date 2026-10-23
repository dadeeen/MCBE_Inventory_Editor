import { expect, test } from "@playwright/test";
import {
  collectBrowserErrors,
  openAppAndWaitForScan,
  openAppWithEmptyWorldScan,
  openAppWithSmokeWorldScan,
  openDragFixture,
  selectSetting,
} from "./fixtures/app.mjs";

for (const scenario of ["foreign_text", "foreign_internal", "drag_ended", "previous_drag", "world_changed", "player_changed", "source_replaced"]) {
  test(`inventory drag rejects ${scenario}`, async ({ page }) => {
    const browserErrors = collectBrowserErrors(page);
    await openDragFixture(page);
    const state = await page.evaluate(scenario => {
      const before = JSON.stringify(inventory);
      const source = document.querySelector('[data-slot="0"]');
      const target = document.querySelector('[data-slot="1"]');
      const transfer = new DataTransfer();
      if (scenario === "foreign_text") transfer.setData("text/plain", "0 not-an-inventory-drag");
      else if (scenario === "foreign_internal") transfer.setData("application/x-mcbe-slot", JSON.stringify({ slot: 0, container: "inventory", dragId: "foreign" }));
      else {
        source.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: transfer }));
        if (scenario === "drag_ended") source.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: transfer }));
        if (scenario === "previous_drag") {
          source.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: transfer }));
          source.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() }));
        }
        if (scenario === "world_changed") worldPath += "/different-world";
        if (scenario === "player_changed") currentPlayerKey = "different-player";
        if (scenario === "source_replaced") inventory[0] = { ...inventory[0] };
      }
      target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
      return { before, after: JSON.stringify(inventory), dirty: isDirty };
    }, scenario);
    expect(state.after).toBe(state.before);
    expect(state.dirty).toBe(false);
    expect(browserErrors).toEqual([]);
  });
}

for (const viewport of [{width: 1440, theme: 'dark'}, {width: 390, theme: 'light'}]) {
test(`equipment browser filters by slot and resets for ordinary inventory (${viewport.width}/${viewport.theme})`, async ({ page }) => {
  const ids = ['stone', 'iron_helmet', 'elytra', 'iron_leggings', 'iron_boots', 'shield', 'future_offhand'];
  await openDragFixture(page, {
    items_db: Object.fromEntries(ids.map(id => [`minecraft:${id}`, [id, id]])),
    addable_items: ids.map(id => `minecraft:${id}`),
    item_components: { allow_off_hand: { 'minecraft:future_offhand': { value: true } } },
  });
  for (const layout of ['classic', 'studio', 'focus']) {
    await page.setViewportSize({ width: viewport.width, height: 1000 });
    await selectSetting(page, 'layoutSelect', layout);
    await selectSetting(page, 'themeSelect', viewport.theme);
    for (const [slot, title, expected] of [
      [103, 'Helm auswählen', ['iron_helmet']],
      [102, 'Brustausrüstung auswählen', ['elytra']],
      [101, 'Beinausrüstung auswählen', ['iron_leggings']],
      [100, 'Stiefel auswählen', ['iron_boots']],
      [-106, 'Nebenhand auswählen', ['shield', 'future_offhand']],
      [0, '📖 Item-Browser', ids],
    ]) {
      const inventoryToggle = page.locator('.btn-toggle[data-panel="left"]');
      if (await inventoryToggle.isVisible()) await inventoryToggle.click();
      await page.locator(`.inventory-slot[data-slot="${slot}"]`).click();
      const editorToggle = page.locator('.btn-toggle[data-panel="right"]');
      if (await editorToggle.isVisible()) await editorToggle.click();
      const originalItem = await page.locator('#detailItemSearch').inputValue();
      await page.locator('#detailItemSearch').fill('minecraft:');
      const suggestions = await page.locator('#detailItemAutocomplete .autocomplete-item').count();
      expect(suggestions).toBe(expected.length);
      await page.locator('#detailItemSearch').press('Escape');
      await page.locator('#btnBrowserDetail').click();
      await expect(page.locator('#itemBrowserTitle')).toHaveText(title);
      const rendered = await page.locator('#browserGrid .browser-item-id').allTextContents();
      expect(rendered.map(id => id.trim()).sort()).toEqual(expected.map(id => `minecraft:${id}`).sort());
      await page.locator('#browserSearchInput').fill('stone');
      await expect(page.locator('#browserGrid .browser-item')).toHaveCount(slot === 0 ? 1 : 0);
      await page.locator('#btnBrowserClose').click();
      await page.locator('#detailItemSearch').fill(originalItem);
    }
  }
});
}

test("focus reserves desktop facts without stale values or mobile placeholder rows", async ({ page }) => {
  await openDragFixture(page);
  await selectSetting(page, 'layoutSelect', 'focus');
  const facts = page.locator('#focusContextFacts');
  const values = page.locator('#focusContextFacts strong');
  const geometry = () => page.locator('.layout-context-bar').evaluate(el =>
    [el, ...el.children].map(node => { const r = node.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }));
  for (const theme of ['dark', 'light']) {
    await selectSetting(page, 'themeSelect', theme);
    for (const width of [1280, 1440, 1830]) {
      await page.setViewportSize({width, height: 1000});
      await expect(facts).toBeVisible();
      await expect(page.locator('#focusFactPosition')).toHaveText('0.00, 64.00, 0.00');
      const loaded = await geometry();
      // Retain old form values deliberately: the unloaded state must mask them.
      await page.evaluate(() => document.body.classList.remove('app-player-loaded'));
      await expect(values).toHaveText(['—', '—', '—']);
      await expect(page.locator('#focusFactMode')).toHaveAttribute('title', '');
      expect(await geometry()).toEqual(loaded);
      await page.evaluate(() => document.body.classList.add('app-player-loaded'));
      await expect(page.locator('#focusFactPosition')).toHaveText('0.00, 64.00, 0.00');
      expect(await geometry()).toEqual(loaded);
    }
    for (const width of [390, 760, 1279]) {
      await page.setViewportSize({width, height: 1000});
      await page.evaluate(() => document.body.classList.remove('app-player-loaded'));
      await expect(values).toHaveText(['—', '—', '—']);
      await expect(facts).toBeHidden();
      await page.evaluate(() => document.body.classList.add('app-player-loaded'));
    }
  }
});

test("slot quick actions keep a compact two by two grid at every panel width", async ({ page }) => {
  await openDragFixture(page);
  for (const layout of ['classic', 'studio', 'focus']) {
    for (const slot of [0, 1]) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await selectSetting(page, 'layoutSelect', layout);
      await page.locator(`.inventory-slot[data-slot="${slot}"]`).click();
      for (const width of [320, 504, 820, 1180, 1181, 1830]) {
        await page.setViewportSize({ width, height: 1000 });
        const toggle = page.locator('.btn-toggle[data-panel="right"]');
        if (layout === 'classic' && width <= 1024) await expect(toggle).toBeVisible();
        if (await toggle.isVisible()) await toggle.click();
        await expect(page.locator('#slotQuickActions'), `${layout}/${slot}/${width}`).toBeVisible();
        const boxes = await page.locator('.slot-quick-buttons button').evaluateAll(buttons => buttons.map(button => {
          const r = button.getBoundingClientRect();
          return { x: r.x, y: r.y, height: r.height, overflow: button.scrollWidth - button.clientWidth };
        }));
        expect(boxes).toHaveLength(4);
        expect(boxes[0].y).toBeCloseTo(boxes[1].y, 0);
        expect(boxes[2].y).toBeCloseTo(boxes[3].y, 0);
        expect(boxes[2].y).toBeGreaterThan(boxes[0].y);
        expect(boxes[0].x).toBeCloseTo(boxes[2].x, 0);
        for (const box of boxes) {
          expect(box.height).toBeGreaterThanOrEqual(44);
          expect(box.height).toBeLessThan(60);
          expect(box.overflow).toBeLessThanOrEqual(1);
        }
      }
    }
  }
});

test("inventory drag supports moving copying equipment and undo redo", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  // Plain HTTP on a LAN has getRandomValues, but no secure-context randomUUID.
  await page.addInitScript(() => Object.defineProperty(window.crypto, "randomUUID", { value: undefined }));
  await openDragFixture(page);
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  expect(await page.evaluate(() => inventory[1]?.name)).toBe("minecraft:stone");
  await page.keyboard.press("Control+z");
  expect(await page.evaluate(() => inventory[0]?.name)).toBe("minecraft:stone");
  await page.keyboard.press("Control+y");
  expect(await page.evaluate(() => inventory[1]?.name)).toBe("minecraft:stone");
  for (const modifier of ["Control", "Meta"]) {
    await page.keyboard.press(`${modifier}+z`);
    expect(await page.evaluate(() => inventory[0]?.name)).toBe("minecraft:stone");
    await page.keyboard.press(`${modifier}+Shift+KeyZ`);
    expect(await page.evaluate(() => inventory[1]?.name)).toBe("minecraft:stone");
  }
  const state = await page.evaluate(() => {
    function drag(source, target, copyMode = false) {
      const transfer = new DataTransfer();
      source.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: transfer }));
      target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, ctrlKey: copyMode, dataTransfer: transfer }));
      source.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: transfer }));
    }
    drag(document.querySelector('[data-slot="1"]'), document.querySelector('[data-ender-slot="0"]'), true);
    drag(document.querySelector('[data-slot="3"]'), document.querySelector('[data-slot="103"]'));
    return { source: inventory[1]?.name, copied: enderChestInventory[0]?.name, helmet: inventory[103]?.name, oldHelmetSlot: inventory[3], dirty: isDirty };
  });
  expect(state.source).toBe("minecraft:stone");
  expect(state.copied).toBe("minecraft:stone");
  expect(state.helmet).toBe("minecraft:iron_helmet");
  expect(state.oldHelmetSlot).toBeFalsy();
  expect(state.dirty).toBe(true);
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
    // Provenance is shared by the group instead of repeated in every row.
    const sourceGroup = page.getByRole("group", { name: "Configured world root", exact: true });
    await expect(sourceGroup.locator(".world-source-title")).toContainText("Configured world root");
    await expect(sourceGroup).not.toContainText("Konfigurierter Welt-Root");
    await expect(sourceGroup.locator(".world-card").filter({ hasText: "Second Smoke World" })).toBeVisible();
    const secondWorldAction = secondCard.locator(".world-card-action");
    await expect(secondWorldAction).toHaveCount(0);
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
    await expect(page.locator('[data-player-tool="playerExportDialog"]')).toHaveText("Export …");
    await expect(page.locator('#playerExportTitle')).toHaveText("Export player");
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
    expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
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
    await expect(page.locator("#detailDataVariantLabel")).toHaveText("Variant");
    await expect(page.locator("#detailDataVariant")).toHaveValue("14");
    await expect(page.locator("#detailDataVariant option:checked")).toHaveText("Orange Banner");

    if (process.env.MCBE_QA_VARIANT_SCREENSHOT) {
      await page.screenshot({ path: process.env.MCBE_QA_VARIANT_SCREENSHOT, fullPage: false });
    }
    expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
  });
});
