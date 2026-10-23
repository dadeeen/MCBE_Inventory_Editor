import { expect, test } from "@playwright/test";
import {
  openSpecialProperties,
  openSpecialFixture,
  NORMAL_BASE_URL,
  collectBrowserErrors,
  openDragFixture,
  selectLayout,
} from "./fixtures/app.mjs";

test("special unaccepted drafts warn before closing the browser or desktop", async ({ page }) => {
  const book = { slot: 0, source_index: 0, name: "minecraft:written_book", count: 1, damage: 0,
    special_item: { kind: "book", editable: true, data: { pages: [], title: "Original", author: "Autor" } } };
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [book] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const pending = async expected => {
    expect(await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return { desktop: window.MCBEDesktop.closeState().dirty, browser: event.defaultPrevented, inventory: isDirty };
    })).toEqual({ desktop: expected, browser: expected, inventory: false });
  };
  await pending(false);
  await dialog.locator('[data-special-slot="0"]').click();
  await pending(false);
  const count = dialog.getByLabel("Menge", { exact: true });
  await count.fill("2");
  await pending(true);
  await count.fill("1");
  await pending(false);
  await count.fill("2");
  await dialog.getByRole("button", { name: "Buch bearbeiten", exact: true }).click();
  await pending(true); // The suspended parent item form still owns its draft.
  await dialog.getByLabel("Titel", { exact: true }).fill("Verwerfen");
  await page.keyboard.press("Escape");
  await pending(true);
  await page.keyboard.press("Escape");
  await pending(false); // Cancelling that parent discards only its draft.
  await dialog.locator('[data-special-slot="0"]').click();
  await dialog.getByRole("button", { name: "Buch bearbeiten", exact: true }).click();
  await pending(false);
  const title = dialog.getByLabel("Titel", { exact: true });
  await title.fill("Entwurf");
  await pending(true);
  await title.fill("Original");
  await pending(false);
  await title.fill("Entwurf");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await pending(true); // An accepted child remains pending until the root is accepted.
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await pending(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("item dialogs and menus suppress the browser save shortcut without changing inventory", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:writable_book", count: 1, damage: 0 } });
  const slot = page.locator('.inventory-slot[data-slot="0"]');
  await slot.click();
  for (const [opener, id] of [["#btnSpecialItem", "#specialItemDialog"], ["#btnInspectSlotNbt", "#slotInspectorPanel"], ["#btnBrowserDetail", "#itemBrowserOverlay"], [null, "#slotContextMenu"]]) {
    if (opener) await page.locator(opener).click();
    else { await slot.focus(); await page.keyboard.press("Shift+F10"); }
    const surface = page.locator(id);
    await expect(surface).toBeVisible();
    expect(await surface.evaluate(node => ["ctrlKey", "metaKey"].map(modifier => {
      const event = new KeyboardEvent("keydown", { key: "s", [modifier]: true, bubbles: true, cancelable: true });
      node.querySelector("button").dispatchEvent(event);
      return event.defaultPrevented;
    }))).toEqual([true, true]);
    await expect(page.locator("#saveReviewOverlay")).toBeHidden();
    expect(await page.evaluate(() => isDirty)).toBe(false);
    await surface.locator("button:visible").first().focus();
    await page.keyboard.press("Escape");
    await expect(surface).toBeHidden();
    if (opener) {
      await slot.focus();
      // Native close events are queued. A late delivery must not override
      // the user's next focus choice or break the next keyboard action.
      await surface.dispatchEvent("close");
      await expect(slot).toBeFocused();
    }
  }
});

test("ordinary unaccepted slot drafts warn before closing without changing save or undo state", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openSpecialFixture(page, {
    0: { slot: 0, name: "minecraft:diamond_sword", count: 1, damage: 3,
      display_name: "Erste\nZweite", lore: ["Erste\r\nZweite"], enchantments: [{ id: 9, lvl: 2 }, { id: 17, lvl: 1 }] },
    1: { slot: 1, name: "minecraft:axolotl_bucket", count: 1, damage: 0,
      entity_variant: { entity_id: "minecraft:axolotl", variant: 1, is_baby: false, can_edit: true } },
    2: { slot: 2, name: "minecraft:diamond", count: 1, damage: 0 },
  }, {
    ender_chest: { 0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0 } },
    items_db: { "minecraft:diamond_sword": ["Diamantschwert", "Diamond Sword"], "minecraft:diamond": ["Diamant", "Diamond"], "minecraft:axolotl_bucket": ["Axolotleimer", "Axolotl Bucket"] },
    max_damage: { "minecraft:diamond_sword": 1561, __default__: 0 },
    ench_db: { 9: { name_de: "Schärfe", name_en: "Sharpness", max_lvl: 5 }, 17: { name_de: "Haltbarkeit", name_en: "Unbreaking", max_lvl: 3 } },
    enchantment_compatibility: { item_slots: { "minecraft:diamond_sword": ["sword"] }, compatible_slots: { 9: ["sword"], 17: ["sword"] } },
  });
  await selectLayout(page, "focus");
  const apply = page.locator("#btnApplySingle");
  const status = page.locator("#layoutSaveStatus");
  const pending = async (expected, committed = false) => {
    expect(await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return { desktop: window.MCBEDesktop.closeState().dirty, browser: event.defaultPrevented, inventory: isDirty };
    })).toEqual({ desktop: expected || committed, browser: expected || committed, inventory: committed });
  };
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await pending(false);
  await expect(status).toBeVisible();
  await expect(status).toHaveText("Keine Änderungen");
  await expect(apply).toBeDisabled();
  await expect(page.locator("#detailCount")).toHaveAttribute("readonly");
  for (const [id, value] of [["detailDamage", "8"], ["detailCustomName", "Entwurf"], ["detailLore", "Neue Beschreibung"]]) {
    const field = page.locator(`#${id}`);
    const original = await field.inputValue();
    await field.fill(value); await pending(true);
    await expect(status).toHaveText("Eingaben offen");
    await expect(apply).toBeEnabled();
    await field.fill(original); await pending(false);
    await expect(status).toHaveText("Keine Änderungen");
    await expect(apply).toBeDisabled();
  }
  await page.locator('[data-tab="tabEnchants"]').click();
  const sharpness = page.locator(".ench-row").filter({ hasText: "Schärfe" });
  await sharpness.getByRole("button", { name: "Schärfe entfernen" }).click(); await pending(true);
  await page.locator("#enchantsContainer").getByLabel("Verzauberung hinzufügen", { exact: true }).selectOption("9"); await pending(true);
  await sharpness.getByLabel("Stufe", { exact: true }).selectOption("2"); await pending(false);
  await sharpness.getByLabel("Stufe", { exact: true }).selectOption("3"); await pending(true);
  await sharpness.getByLabel("Stufe", { exact: true }).selectOption("2"); await pending(false);
  await page.locator('[data-tab="tabGeneral"]').click();
  await page.locator("#detailItemSearch").fill("minecraft:");
  await expect(apply).toBeDisabled();
  await expect(status).toHaveText("Eingaben offen");
  await pending(true);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#confirmOk").click(); await pending(false);

  await page.locator('.inventory-slot[data-slot="2"]').click(); await pending(false);
  await page.locator("#detailCount").fill(""); await pending(true);
  await page.locator("#detailCount").fill("1"); await pending(false);
  await page.locator("#detailItemSearch").fill("minecraft:axolotl_bucket"); await pending(true);
  await page.locator("#detailItemSearch").fill("minecraft:diamond"); await pending(false);

  await page.locator('.inventory-slot[data-slot="1"]').click(); await pending(false);
  await page.locator("#detailAxolotlColor").selectOption("4"); await pending(true);
  await page.locator("#detailAxolotlColor").selectOption("1"); await pending(false);
  await page.locator("#detailAxolotlAge").selectOption("baby"); await pending(true);
  await page.locator("#btnCloseDetail").click();
  await page.locator("#confirmOk").click(); await pending(false);
  await page.locator('.inventory-slot[data-slot="1"]').click(); await pending(false);

  await page.locator('.inventory-slot[data-ender-slot="0"]').click(); await pending(false);
  await page.locator("#detailCustomName").fill("Ender-Entwurf"); await pending(true);
  await expect(status).toHaveText("Eingaben offen");
  await apply.click(); await pending(false, true);
  await expect(status).toHaveText("1 Änderung");
  await expect(apply).toBeDisabled();
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
  await page.locator("#detailCount").fill("2.0");
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
  await expect(apply).toBeDisabled();
  await expect(status).toHaveText("1 Änderung");
  await page.locator("#btnUndo").click();
  await expect(page.locator("#detailCustomName")).toHaveValue("");
  await expect(status).toHaveText("Keine Änderungen");
  await expect(page.locator("#detailFormError")).toBeHidden();
  await page.locator("#btnRedo").click();
  await expect(page.locator("#detailCustomName")).toHaveValue("Ender-Entwurf");
  await expect(status).toHaveText("1 Änderung");

  // Partial inputs on a still-empty slot remain guarded until chosen or discarded.
  await page.locator('.inventory-slot[data-slot="3"]').click();
  await page.locator("#detailCustomName").fill("Name vor Itemwahl");
  await page.locator("#detailLore").fill("Beschreibung vor Itemwahl");
  await pending(true, true);
  await expect(status).toHaveText("Eingaben offen");
  await expect(apply).toBeDisabled();
  await page.locator('.inventory-slot[data-slot="2"]').click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await page.locator("#confirmCancel").click();
  await expect(page.locator("#detailCustomName")).toHaveValue("Name vor Itemwahl");
  await expect(page.locator("#detailLore")).toHaveValue("Beschreibung vor Itemwahl");
  await page.locator("#detailCustomName").fill("");
  await page.locator("#detailLore").fill("");
  await pending(false, true);
  await expect(status).toHaveText("1 Änderung");

  // A second, still unaccepted form must retain the first applied change.
  await page.locator('.inventory-slot[data-slot="2"]').click();
  await page.setViewportSize({ width: 390, height: 844 });
  if (!(await page.locator("#detailCustomName").isVisible())) {
    await page.locator('.btn-toggle[data-panel="right"]').click();
  }
  await expect(apply).toBeVisible();
  await expect(apply).toBeDisabled();
  const applyAppearance = () => apply.evaluate(button => {
    const style = getComputedStyle(button);
    return { opacity: style.opacity, color: style.color, backgroundColor: style.backgroundColor };
  });
  const disabledAppearance = await applyAppearance();
  await page.locator("#detailCustomName").fill("Zweiter Entwurf");
  await pending(true, true);
  await expect(status).toHaveText("Eingaben offen");
  await expect(apply).toBeEnabled();
  await expect.poll(applyAppearance).not.toEqual(disabledAppearance);
  expect(await page.evaluate(() => enderChestInventory[0].display_name)).toBe("Ender-Entwurf");
  expect(await page.evaluate(() => inventory[2].display_name)).toBeUndefined();
  await expect(page.locator("#layoutSaveAction")).toBeDisabled();
  await page.evaluate(() => setWorkflowView("save", { user: true }));
  await expect(page.locator("body")).toHaveAttribute("data-workflow-view", "inventory");
  await expect(page.locator(".toast").filter({ hasText: "Bitte übernimm zuerst" }).last()).toBeVisible();
  await expect(page.locator("#detailCustomName")).toHaveValue("Zweiter Entwurf");
  await page.keyboard.press("Control+s");
  await expect(page.locator("#saveReviewOverlay")).toBeHidden();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  expect(await page.evaluate(() => inventory[2].display_name)).toBeUndefined();
  await page.locator("#detailCustomName").fill("");
  await pending(false, true);
  await expect(status).toHaveText("1 Änderung");
  await expect(apply).toBeDisabled();
  await page.locator("#detailCustomName").fill("Zweiter Entwurf");
  await apply.click();
  await pending(false, true);
  await expect(apply).toBeDisabled();
  await expect(status).toHaveText("2 Änderungen");
  expect(await page.evaluate(() => inventory[2].display_name)).toBe("Zweiter Entwurf");
  expect(await page.evaluate(() => enderChestInventory[0].display_name)).toBe("Ender-Entwurf");
  await page.locator("#layoutSaveAction").click();
  await expect(page.locator("body")).toHaveAttribute("data-workflow-view", "save");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
  await page.locator('.inventory-slot[data-ender-slot="0"]').click();
  await page.locator("#btnQuickClearSlot").click();
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
  expect(await page.evaluate(() => enderChestInventory[0].display_name)).toBe("Ender-Entwurf");
});

test("special contained enchantment replacements count as unaccepted drafts", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 0, source_index: 0, name: "minecraft:diamond_sword", count: 1, damage: 0, enchantments: [{ id: 9, lvl: 1 }] },
    ] } } } }, {
    ench_db: { 9: { name_de: "Schärfe", name_en: "Sharpness", max_lvl: 5 }, 17: { name_de: "Haltbarkeit", name_en: "Unbreaking", max_lvl: 3 } },
    enchantment_compatibility: { item_slots: { "minecraft:diamond_sword": ["sword"] }, compatible_slots: { 9: ["sword"], 17: ["sword"] } },
  });
  const pending = async expected => {
    expect(await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return { desktop: window.MCBEDesktop.closeState().dirty, browser: event.defaultPrevented, inventory: isDirty };
    })).toEqual({ desktop: expected, browser: expected, inventory: false });
  };
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.locator('[data-special-slot="0"]').click(); await pending(false);
  await openSpecialProperties(dialog);
  await dialog.getByRole("button", { name: "Schärfe entfernen", exact: true }).click();
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Verzauberung hinzufügen", { exact: true }).selectOption("17"); await pending(true);
  await dialog.getByRole("button", { name: "Haltbarkeit entfernen", exact: true }).click();
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Verzauberung hinzufügen", { exact: true }).selectOption("9"); await pending(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("unaccepted player stats and dimension conversions warn before closing", async ({ page }) => {
  const players = [
    { player_key: "drag-player", label: "Stats A", editable: true, exportable: true, has_inventory_tag: true, has_ender_chest_tag: true },
    { player_key: "stats-other", label: "Stats B", editable: true, exportable: true, has_inventory_tag: true, has_ender_chest_tag: true },
  ];
  const originalStats = { pos: [94.41, 71.625, 93.52], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 };
  await page.route("**/api/server_status", route => route.fulfill({ json: { success: true, status: "offline", write_gate: { allowed: true, read_allowed: true } } }));
  await openDragFixture(page, ({ player_key }) => ({
    player: players.find(player => player.player_key === player_key),
    stats: { ...originalStats, health: player_key === "stats-other" ? 10 : 20 },
  }), players);
  await selectLayout(page, "studio");
  await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
  const pending = async (expected, committed = false) => {
    expect(await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return { desktop: window.MCBEDesktop.closeState().dirty, browser: event.defaultPrevented, inventory: isDirty };
    })).toEqual({ desktop: expected || committed, browser: expected || committed, inventory: committed });
  };
  await pending(false);
  for (const [id, value] of [["statHealth", "12"], ["statXpLevel", "3"], ["statXpProgress", "25"], ["statFoodLevel", "15"], ["statFoodSaturation", "8"], ["statPosX", "99"], ["statPosY", "75"], ["statPosZ", "101"]]) {
    const field = page.locator(`#${id}`);
    const original = await field.inputValue();
    await field.fill(value); await pending(true);
    await field.fill(original); await pending(false);
  }
  await page.locator("#statDimensionId").selectOption("2"); await pending(true);
  await page.locator("#statDimensionId").selectOption("0"); await pending(false);
  const originalX = await page.locator("#statPosX").inputValue();
  await page.locator("#statPosX").fill("");
  await page.locator("#btnApplyStats").click(); await pending(true);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator("#statPosX").fill(originalX); await pending(false);
  const convert = page.locator("#btnConvertOverworldNether");
  await convert.click(); await pending(true);
  await expect(page.locator("#statDimensionId")).toHaveValue("1");
  await convert.click(); await pending(false);
  await expect(page.locator("#statDimensionId")).toHaveValue("0");
  expect(await page.evaluate(() => playerStats)).toEqual(originalStats);
  await page.locator("#btnApplyStats").click(); await pending(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();

  await page.locator("#statXpLevel").fill("1e4");
  await page.locator("#statFoodLevel").fill("1e1"); await pending(true);
  await page.locator("#btnApplyStats").click(); await pending(false, true);
  expect(await page.evaluate(() => [playerStats.xp_level, playerStats.food_level])).toEqual([10000, 10]);
  await page.locator("#btnUndo").click(); await pending(false);
  expect(await page.evaluate(() => playerStats)).toEqual(originalStats);

  await page.locator("#statHealth").fill("13"); await pending(true);
  await page.locator("#btnApplyStats").click(); await pending(false, true);
  expect(await page.evaluate(() => statsFormController.hasPendingChanges())).toBe(false);
  await page.locator("#btnApplyStats").click();
  expect(await page.evaluate(() => statsFormController.hasPendingChanges())).toBe(false);
  await page.locator("#btnUndo").click(); await pending(false);
  await expect(page.locator("#statHealth")).toHaveValue("20.0");
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await convert.click(); await pending(true);
  await page.locator("#btnApplyStats").click(); await pending(false, true);
  expect(await page.evaluate(() => statsFormController.hasPendingChanges())).toBe(false);
  await page.locator("#btnUndo").click(); await pending(false);
  expect(await page.evaluate(() => playerStats)).toEqual(originalStats);

  await page.locator("#statHealth").fill("12"); await pending(true);
  await page.locator('.layout-context-chip[data-workflow-view="player"]').click();
  await page.locator('.player-row[data-player-key="stats-other"]').click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await page.locator("#confirmCancel").click();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  await expect(page.locator("#statHealth")).toHaveValue("12"); await pending(true);
  expect(await page.evaluate(() => currentPlayerKey)).toBe("drag-player");
  await page.locator('.player-row[data-player-key="stats-other"]').click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await page.locator("#confirmOk").click();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  await expect(page.locator("#statHealth")).toHaveValue("10.0"); await pending(false);
  expect(await page.evaluate(() => currentPlayerKey)).toBe("stats-other");
  await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
  await page.locator("#statHealth").fill("9"); await pending(true);
  await page.locator("#statHealth").fill("10"); await pending(false);
});

for (const [locale, width, height] of [["de", 1440, 1000], ["en", 1024, 768], ["de", 320, 740], ["en", 390, 844]]) {
  test.describe(`shared item picker ${locale} ${width}px`, () => {
    test.use({ viewport: { width, height }, isMobile: width < 600, hasTouch: width < 600 });
    test("selects variants and respects container rules without changing the parent draft", async ({ page }) => {
      const activate = locator => width < 600 ? locator.tap() : locator.click();
      await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
      const items = { "minecraft:undyed_shulker_box": ["Shulkerkiste", "Shulker Box"],
        "minecraft:light_blue_shulker_box": ["Hellblaue Shulkerkiste", "Light Blue Shulker Box"],
        "minecraft:bundle": ["Bündel", "Bundle"], "minecraft:stone": ["Stein", "Stone"],
        "minecraft:diamond": ["Diamant", "Diamond"], "minecraft:diamond_sword": ["Diamantschwert", "Diamond Sword"],
        "minecraft:goat_horn": ["Ziegenhorn", "Goat Horn"] };
      const errors = collectBrowserErrors(page);
      await openSpecialFixture(page, {
        0: {slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0},
        1: {slot: 1, name: "minecraft:bundle", count: 1, damage: 0, special_item: {kind: "bundle", editable: true,
          data: {items: [{slot: 0, name: "minecraft:diamond", count: 60, damage: 0}]}}},
        2: {slot: 2, name: "minecraft:diamond_sword", count: 1, damage: 0},
      }, { items_db: items, addable_items: Object.keys(items),
        ench_db: { 9: {name_de: "Schärfe", name_en: "Sharpness", max_lvl: 5}, 15: {name_de: "Effizienz", name_en: "Efficiency", max_lvl: 5} },
        enchantment_compatibility: { item_slots: {"minecraft:diamond_sword": ["sword"]}, compatible_slots: {9: ["sword"], 15: ["pickaxe"]} },
        stack_limits: {__default__: 64, "minecraft:diamond": 64, "minecraft:stone": 64, "minecraft:goat_horn": 1, "minecraft:diamond_sword": 1, "minecraft:bundle": 1},
        max_damage: {__default__: 32767, "minecraft:diamond_sword": 1561},
      });
      const dialog = page.locator("#specialItemDialog");
      const picker = page.locator("#itemBrowserOverlay");
      const search = picker.locator("#browserSearchInput");
      const accept = dialog.locator('[data-special="accept"]');
      const choose = dialog.getByRole("button", {name: /Item.Browser|Item browser/});
      const card = text => picker.locator(".browser-item").filter({has: page.locator(".browser-item-id", {hasText: text})});
      async function open(slot) {
        if (!(await page.locator(`.inventory-slot[data-slot="${slot}"]`).isVisible())) await activate(page.locator('.btn-toggle[data-panel="left"]'));
        await activate(page.locator(`.inventory-slot[data-slot="${slot}"]`));
        if (!(await page.locator("#btnSpecialItem").isVisible())) await activate(page.locator('.btn-toggle[data-panel="right"]'));
        await activate(page.locator("#btnSpecialItem"));
      }
      const before = await page.evaluate(() => JSON.stringify(inventory));
      await open(0); await activate(dialog.locator(".special-slot").first());
      await activate(choose);
      expect(await picker.evaluate(el => el.matches(":modal"))).toBe(true);
      await search.fill("shulker");
      await expect(picker.locator('.browser-item[aria-disabled="true"]')).toHaveCount(2);
      await expect(picker.locator(".browser-unavailable").first()).toContainText(locale === "de" ? "dürfen nicht" : "cannot");
      // Aria-disabled cards remain keyboard-readable and cannot be chosen.
      await picker.locator(".browser-item").first().focus(); await page.keyboard.press("Enter");
      await expect(picker).toBeVisible();
      if (process.env.MCBE_QA_SPECIAL_DIR) await page.screenshot({path: `${process.env.MCBE_QA_SPECIAL_DIR}/picker-${locale}-${width}.png`, animations: "disabled"});
      await page.keyboard.press("Escape");
      await expect(picker).toBeHidden(); await expect(dialog).toBeVisible(); await expect(choose).toBeFocused();
      expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
      await activate(choose); await search.fill("goat_horn");
      await activate(card(/minecraft:goat_horn .* 5$/));
      await expect(dialog.locator(".special-item-name")).toHaveValue("minecraft:goat_horn");
      await expect(dialog.getByLabel(locale === "de" ? "Menge" : "Count", {exact: true})).toHaveAttribute("readonly");
      await activate(dialog.locator("summary"));
      await expect(dialog.getByLabel(locale === "de" ? "Variante" : "Variant", {exact: true})).toHaveValue("5");
      await expect(dialog.locator(".special-enchantments")).toBeHidden();
      // Selection alone leaves the original inventory untouched.
      expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
      await activate(choose); await search.fill("diamond_sword"); await activate(card(/^minecraft:diamond_sword$/));
      const ench = dialog.getByLabel(locale === "de" ? "Verzauberung hinzufügen" : "Add enchantment", {exact: true});
      await expect(ench.locator('option[value="9"]')).toHaveCount(1);
      await expect(ench.locator('option[value="15"]')).toHaveCount(0);
      await ench.selectOption("9");
      await expect(dialog.getByLabel(locale === "de" ? "Stufe" : "Level", {exact: true}).locator("option")).toHaveText(["1", "2", "3", "4", "5"]);
      await activate(accept); await activate(accept);
      expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({name: "minecraft:diamond_sword", count: 1, enchantments: [{id: 9, lvl: 1}]});
      await open(1); await activate(dialog.locator(".special-slot").last());
      await activate(choose); await search.fill("diamond_sword");
      await expect(card(/^minecraft:diamond_sword$/)).toHaveAttribute("aria-disabled", "true");
      await search.fill("diamond"); await activate(card(/^minecraft:diamond$/));
      await expect(dialog.getByLabel(locale === "de" ? "Menge" : "Count", {exact: true})).toHaveAttribute("max", "4");
      await dialog.locator(".special-item-name").fill(locale === "de" ? "Stein" : "Stone");
      await activate(dialog.locator(".autocomplete-item").first());
      await expect(dialog.locator(".special-item-name")).toHaveValue("minecraft:stone");
      if (process.env.MCBE_QA_SPECIAL_DIR) await page.screenshot({path: `${process.env.MCBE_QA_SPECIAL_DIR}/shared-form-${locale}-${width}.png`, animations: "disabled"});
      await activate(dialog.locator('footer [data-special="cancel"]')); await activate(dialog.locator('footer [data-special="cancel"]'));
      expect(await page.evaluate(() => inventory[1].special_edit)).toBeUndefined();
      if (!(await page.locator('.inventory-slot[data-slot="2"]').isVisible())) await activate(page.locator('.btn-toggle[data-panel="left"]'));
      await activate(page.locator('.inventory-slot[data-slot="2"]'));
      if (!(await page.locator("#detailCount").isVisible())) await activate(page.locator('.btn-toggle[data-panel="right"]'));
      await expect(page.locator("#detailCount")).toHaveAttribute("max", "1");
      await expect(page.locator("#detailCount")).toHaveAttribute("readonly");
      expect(errors).toEqual([]);
    });
  });
}

for (const [locale, width] of [["de", 1440], ["en", 390]]) {
  test.describe(`entity draft reselection ${locale} ${width}px`, () => {
    test.use({viewport: {width, height: 900}, isMobile: width < 600, hasTouch: width < 600});
    test("keeps unaccepted entity variants through search and browser reselection", async ({page}) => {
      const activate = locator => width < 600 ? locator.tap() : locator.click();
      await page.context().addCookies([{name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL}]);
      const ids = ["minecraft:axolotl_bucket", "minecraft:tropical_fish_bucket", "minecraft:diamond"];
      await openSpecialFixture(page, {
        0: {slot: 0, name: ids[0], count: 1, damage: 0,
          entity_variant: {entity_id: "minecraft:axolotl", variant: 1, is_baby: false, can_edit: true}},
        1: {slot: 1, name: ids[1], count: 1, damage: 0,
          entity_variant: {entity_id: "minecraft:tropicalfish", variant: 0, mark_variant: 1, color: 2, color2: 3, can_edit: true}},
      }, {items_db: Object.fromEntries(ids.map(id => [id, [id, id]])), addable_items: ids,
        stack_limits: Object.fromEntries(ids.map(id => [id, 1]))});
      const errors = collectBrowserErrors(page);
      for (const [slot, controls, edit] of [
        [0, [["detailAxolotlColor", "4"], ["detailAxolotlAge", "baby"]], {kind: "axolotl", variant: 4, is_baby: true}],
        [1, [["detailTropicalFishPattern", "1:5"], ["detailTropicalFishColor", "14"], ["detailTropicalFishColor2", "15"]],
          {kind: "tropical_fish", variant: 1, mark_variant: 5, color: 14, color2: 15}],
      ]) {
        const gridSlot = page.locator(`.inventory-slot[data-slot="${slot}"]`);
        if (!(await gridSlot.isVisible())) await activate(page.locator('.btn-toggle[data-panel="left"]'));
        await activate(gridSlot);
        if (!(await page.locator("#detailItemSearch").isVisible())) await activate(page.locator('.btn-toggle[data-panel="right"]'));
        for (const [id, value] of controls) await page.locator(`#${id}`).selectOption(value);
        // A temporary search query does not replace the item represented by the form.
        await page.locator("#detailItemSearch").fill(ids[slot].slice(10));
        await activate(page.locator("#detailItemAutocomplete .autocomplete-item").filter({has: page.locator(".item-id", {hasText: ids[slot]})}));
        expect(await page.evaluate(slot => inventory[slot].entity_variant_edit, slot)).toBeUndefined();
        await activate(page.locator("#btnApplySingle"));
        expect(await page.evaluate(slot => inventory[slot].entity_variant_edit, slot)).toEqual(edit);
        for (const [id, value] of controls) await expect(page.locator(`#${id}`)).toHaveValue(value);
        // The catalogue also preserves a subsequent unaccepted change.
        const [control] = controls[0];
        const nextValue = slot === 0 ? "2" : "1:4";
        await page.locator(`#${control}`).selectOption(nextValue);
        await activate(page.locator("#btnBrowserDetail"));
        await page.locator("#browserSearchInput").fill(ids[slot]);
        await activate(page.locator("#browserGrid .browser-item").filter({has: page.locator(".browser-item-id", {hasText: ids[slot]})}));
        await expect(page.locator(`#${control}`)).toHaveValue(nextValue);
        expect(await page.evaluate(slot => inventory[slot].entity_variant_edit, slot)).toEqual(edit);
        await activate(page.locator("#btnApplySingle"));
        expect(await page.evaluate(slot => inventory[slot].entity_variant_edit, slot)).toEqual({...edit, ...(slot === 0 ? {variant: 2} : {mark_variant: 4})});
      }
      expect(errors).toEqual([]);
    });
  });

  test.describe(`item reselection ${locale} ${width}px`, () => {
    test.use({viewport: {width, height: 900}, isMobile: width < 600, hasTouch: width < 600});
    for (const contained of [false, true]) {
      test(`typing an item ID preserves the draft across valid prefixes (${contained ? "contained" : "slot"})`, async ({page}) => {
        const activate = locator => width < 600 ? locator.tap() : locator.click();
        await page.context().addCookies([{name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL}]);
        const original = {slot: 0, name: "minecraft:diamond_sword", count: 1, damage: 37,
          display_name: "Keep name", lore: ["Keep lore"], enchantments: [{id: 9, lvl: 2}]};
        await openSpecialFixture(page, {0: contained
          ? {slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
              special_item: {kind: "shulker", editable: true, data: {items: [{...original, source_index: 0}]}}}
          : original});
        const errors = collectBrowserErrors(page);
        await activate(page.locator('.inventory-slot[data-slot="0"]'));
        if (!(await page.locator("#detailItemSearch").isVisible())) await activate(page.locator('.btn-toggle[data-panel="right"]'));
        const dialog = page.locator("#specialItemDialog");
        if (contained) {
          await activate(page.locator("#btnSpecialItem"));
          await activate(dialog.locator(".special-slot").first());
          await expect(dialog.locator(".special-item-name")).toBeFocused();
          await activate(dialog.locator(".special-properties summary"));
        }
        const name = contained ? dialog.locator(".special-item-name") : page.locator("#detailItemSearch");
        const custom = contained ? dialog.getByLabel(locale === "de" ? "Anzeigename" : "Custom name", {exact: true}) : page.locator("#detailCustomName");
        const damage = contained ? dialog.getByLabel(locale === "de" ? "Abnutzung" : "Wear", {exact: true}) : page.locator("#detailDamage");
        const lore = contained ? dialog.locator("textarea") : page.locator("#detailLore");
        await custom.fill("Pending name");
        await name.fill("");
        await name.pressSequentially("minecraft:diamond_sword");
        await activate(custom);
        await expect(custom).toHaveValue("Pending name");
        await expect(damage).toHaveValue("37");
        await expect(lore).toHaveValue("Keep lore");
        // A complete prefix can also be a search query for a longer ID.
        // Choosing a suggestion must not commit the prefix on pointer focus.
        await name.fill("minecraft:diamond");
        const suggestions = contained ? dialog.locator(".special-item-suggestions") : page.locator("#detailItemAutocomplete");
        await activate(suggestions.locator(".autocomplete-item").filter({has: page.locator(".item-id", {hasText: /^minecraft:diamond_sword$/})}));
        await expect(custom).toHaveValue("Pending name");
        await expect(damage).toHaveValue("37");
        await custom.fill("Browser draft");
        const browserButton = contained ? dialog.getByRole("button", {name: /Item.Browser|Item browser/}) : page.locator("#btnBrowserDetail");
        await name.fill("minecraft:diamond");
        if (process.env.MCBE_QA_SPECIAL_DIR) await page.screenshot({path: `${process.env.MCBE_QA_SPECIAL_DIR}/item-picker-${contained ? "contained" : "slot"}-${locale}-${width}.png`, animations: "disabled"});
        await activate(browserButton);
        await page.keyboard.press("Escape");
        // Cancelling the picker also leaves the form's draft intact.
        await expect(custom).toHaveValue("Browser draft");
        await expect(damage).toHaveValue("37");
        await activate(browserButton);
        await page.locator("#browserSearchInput").fill("diamond_sword");
        await activate(page.locator("#browserGrid .browser-item").filter({has: page.locator(".browser-item-id", {hasText: /^minecraft:diamond_sword$/})}));
        await expect(custom).toHaveValue("Browser draft");
        await expect(damage).toHaveValue("37");
        if (contained) {
          await activate(dialog.locator('[data-special="accept"]'));
          await activate(dialog.locator('[data-special="accept"]'));
        } else {
          expect(await page.evaluate(() => inventory[0])).toMatchObject(original);
          await activate(page.locator("#btnApplySingle"));
        }
        expect(await page.evaluate(contained => contained ? inventory[0].special_edit.data.items[0] : inventory[0], contained))
          .toMatchObject({...original, display_name: "Browser draft"});
        expect(errors).toEqual([]);
      });
    }
    test("preserves the same item and resets only a real replacement in both forms", async ({page}) => {
      const activate = locator => width < 600 ? locator.tap() : locator.click();
      await page.context().addCookies([{name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL}]);
      const original = {slot: 0, name: "minecraft:diamond", count: 12, damage: 0, display_name: "Keep name", lore: ["Keep lore"]};
      await openSpecialFixture(page, {
        0: original,
        1: {slot: 1, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
          special_item: {kind: "shulker", editable: true, data: {items: [{...original, source_index: 0}]}}},
      });
      const errors = collectBrowserErrors(page);
      async function selectSlot(slot) {
        const gridSlot = page.locator(`.inventory-slot[data-slot="${slot}"]`);
        if (!(await gridSlot.isVisible())) await activate(page.locator('.btn-toggle[data-panel="left"]'));
        await activate(gridSlot);
        if (!(await page.locator("#detailItemSearch").isVisible())) await activate(page.locator('.btn-toggle[data-panel="right"]'));
      }
      await selectSlot(0);
      await page.locator("#detailItemSearch").fill("diam");
      await activate(page.locator("#detailItemAutocomplete .autocomplete-item").filter({has: page.locator(".item-id", {hasText: /^minecraft:diamond$/})}));
      expect(await page.evaluate(() => inventory[0])).toMatchObject(original);
      await expect(page.locator("#btnApplySingle")).toBeDisabled();
      await expect(page.locator("#btnUndo")).toBeDisabled();
      await expect(page.locator("#detailCustomName")).toHaveValue("Keep name");
      await page.locator("#detailItemSearch").fill("minecraft:diamond_sword");
      await page.locator("#detailItemSearch").press("Enter");
      await expect(page.locator("#detailCount")).toHaveValue("1");
      await expect(page.locator("#detailCustomName")).toHaveValue("");
      expect(await page.evaluate(() => inventory[0])).toMatchObject(original);
      await activate(page.locator("#btnApplySingle"));
      await selectSlot(1);
      await activate(page.locator("#btnSpecialItem"));
      const dialog = page.locator("#specialItemDialog");
      await activate(dialog.locator(".special-slot").first());
      const name = dialog.locator(".special-item-name");
      const count = dialog.getByLabel(locale === "de" ? "Menge" : "Count", {exact: true});
      const custom = dialog.getByLabel(locale === "de" ? "Anzeigename" : "Custom name", {exact: true});
      await name.fill("diam");
      await activate(dialog.locator(".autocomplete-item").filter({has: page.locator(".item-id", {hasText: /^minecraft:diamond$/})}));
      await expect(count).toHaveValue("12");
      await activate(dialog.locator(".special-properties summary"));
      await expect(custom).toHaveValue("Keep name");
      await name.fill("minecraft:diamond_sword");
      await name.press("Enter");
      await expect(count).toHaveValue("1");
      await expect(count).toHaveAttribute("readonly");
      await expect(custom).toHaveValue("");
      await expect(dialog.locator("textarea")).toHaveValue("");
      await activate(dialog.locator('[data-special="accept"]'));
      expect(await page.evaluate(() => inventory[1].special_edit)).toBeUndefined();
      await activate(dialog.locator('footer [data-special="cancel"]'));
      expect(await page.evaluate(() => inventory[1].special_item.data.items[0])).toMatchObject(original);
      expect(errors).toEqual([]);
    });
  });
}

for (const [locale, width, height] of [["de", 1440, 800], ["en", 390, 844]]) {
  test(`special editor contains background scrolling and restores it after dialog changes (${locale}/${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await openSpecialFixture(page, { 0: {
      slot: 0, name: "minecraft:writable_book", count: 1, damage: 0,
      special_item: { kind: "book", editable: true, data: { pages: [
        { source_index: 0, text: "A long unchanged page.\n".repeat(70) },
        { source_index: 1, text: "Another unchanged page.\n".repeat(70) },
      ] } },
    } });
    await page.locator('.inventory-slot[data-slot="0"]').click();
    if (!(await page.locator("#btnSpecialItem").isVisible())) await page.locator('.btn-toggle[data-panel="right"]').click();
    // A tall underlying workspace makes scroll chaining observable at both sizes.
    await page.evaluate(() => { document.body.style.minHeight = "2400px"; window.scrollTo(0, 0); });
    const before = await page.evaluate(() => JSON.stringify(inventory));
    await page.locator("#btnSpecialItem").click();
    const dialog = page.locator("#specialItemDialog");
    const body = dialog.locator(".special-body");
    await expect(dialog).toBeVisible();
    const top = await page.evaluate(() => window.scrollY);
    await body.evaluate(el => { el.scrollTop = el.scrollHeight; });
    await dialog.locator(".special-header").hover();
    await page.mouse.wheel(0, 650);
    await page.waitForTimeout(250); // Browser wheel delivery is asynchronous.
    expect(await page.evaluate(() => window.scrollY)).toBe(top);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.locator("#btnSpecialItem")).toBeFocused();
    await page.locator("#btnInspectSlotNbt").click();
    await expect(page.locator("#slotInspectorPanel")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator("#slotInspectorPanel")).toBeHidden();
    await page.locator("#btnSpecialItem").click();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.mouse.move(width / 2, height - 20);
    await page.mouse.wheel(0, 400);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  });

  test(`unaccepted slot drafts survive cancelled player reloads (${locale}/${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 1, damage: 0 } });
    let loads = 0;
    page.on("request", request => { if (request.url().endsWith("/api/player/load")) loads++; });
    await page.locator('.inventory-slot[data-slot="0"]').click();
    if (!(await page.locator("#detailCount").isVisible())) await page.locator('.btn-toggle[data-panel="right"]').click();
    await page.locator("#detailCount").fill("7");
    expect(await page.evaluate(() => isDirty)).toBe(false);
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    const player = page.locator('.player-row[data-player-key="drag-player"]');
    await player.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#confirmOverlay")).toBeVisible();
    await expect(page.locator("#confirmOverlay")).toContainText(locale === "en" ? "unsaved changes" : "ungespeicherte Änderungen");
    await page.keyboard.press("Escape");
    await expect(page.locator("#confirmOverlay")).toBeHidden();
    expect(loads).toBe(0);
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    if (!(await page.locator("#detailCount").isVisible())) await page.locator('.btn-toggle[data-panel="right"]').click();
    await expect(page.locator("#detailCount")).toHaveValue("7");
    expect(await page.evaluate(() => inventory[0].count)).toBe(1);
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    await player.click();
    await page.locator("#confirmOk").click();
    await expect.poll(() => loads).toBe(1);
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    expect(await page.evaluate(() => ({ pending: window.MCBEDesktop.closeState().dirty, count: inventory[0].count }))).toEqual({ pending: false, count: 1 });
  });
}
