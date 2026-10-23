import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { openSpecialFixture, NORMAL_BASE_URL, collectBrowserErrors, selectLayout } from "./fixtures/app.mjs";

for (const [locale, width, layout] of [["de", 1440, "classic"], ["en", 1024, "studio"], ["de", 390, "focus"]]) {
  test(`valid slot input applies directly with grouped undo (${locale}/${width}/${layout})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    const errors = collectBrowserErrors(page);
    let writes = 0;
    page.on("request", request => { if (request.url().endsWith("/api/player/save")) writes++; });
    await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0, display_name: "Original" } });
    await selectLayout(page, layout);
    await page.locator('.inventory-slot[data-slot="0"]').click();
    if (!(await page.locator("#detailCustomName").isVisible())) await page.locator('.btn-toggle[data-panel="right"]').click();
    const name = page.locator("#detailCustomName");
    await name.fill("");
    await name.pressSequentially("Neuer Name");
    expect(await page.evaluate(() => inventory[0].display_name)).toBe("Neuer Name");
    expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
    await expect(page.locator("#btnApplySingle, #btnApplySingleEnch")).toHaveCount(0);
    await expect(page.locator("#detailFormError")).toBeHidden();
    await page.locator("#btnUndo").click();
    await expect(page.locator("#sessionLogContainer .edit")).toHaveCount(1);
    await expect(page.locator("#sessionLogContainer .edit")).toContainText("Neuer Name");
    await expect(name).toHaveValue("Original");
    await expect(page.locator("#btnUndo")).toBeDisabled();
    await page.locator("#btnRedo").click();
    await expect(name).toHaveValue("Neuer Name");
    await page.locator("#detailCount").fill("12");
    expect(await page.evaluate(() => inventory[0].count)).toBe(12);
    await page.locator("#detailCount").fill("");
    expect(await page.evaluate(() => inventory[0].count)).toBe(12);
    await expect(page.locator("#detailFormError")).toBeVisible();
    await page.keyboard.press("Control+s");
    await expect(page.locator("#saveReviewOverlay")).toBeHidden();
    await page.locator("#detailCount").fill("4");
    expect(await page.evaluate(() => inventory[0].count)).toBe(4);
    await page.locator("#detailLore").fill("Zeile 1\nZeile 2");
    expect(await page.evaluate(() => inventory[0].lore)).toEqual(["Zeile 1", "Zeile 2"]);
    expect(await page.evaluate(() => window.MCBEDesktop.closeState().dirty)).toBe(true);
    if (process.env.MCBE_QA_SLOT_DIR) {
      mkdirSync(process.env.MCBE_QA_SLOT_DIR, { recursive: true });
      await expect(page.locator(".toast-container .toast")).toHaveCount(0, { timeout: 6000 });
      await page.locator("#detailEditorPanel .hint-text").last().scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${process.env.MCBE_QA_SLOT_DIR}/${locale}-${width}-${layout}.png`, animations: "disabled" });
    }
    expect(writes).toBe(0);
    await page.keyboard.press("Control+s");
    await expect(page.locator("#saveReviewOverlay")).toBeVisible();
    expect(writes).toBe(0);
    expect(errors).toEqual([]);
  });
}

test("search prefixes and empty IDs retain the slot until a valid selection or explicit clear", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond_sword", count: 1, damage: 37,
    display_name: "Original", lore: ["Keep"], enchantments: [{ id: 9, lvl: 2 }] } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  const before = await page.evaluate(() => JSON.stringify(inventory[0]));
  const search = page.locator("#detailItemSearch");
  await search.fill("minecraft:diamond");
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(before);
  await page.locator("#detailItemAutocomplete .autocomplete-item").filter({
    has: page.locator(".item-id", { hasText: /^minecraft:diamond_sword$/ }),
  }).click();
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(before);
  await search.fill("minecraft:diamond");
  await page.locator("#detailSlotNum").click();
  expect(await page.evaluate(() => inventory[0])).toMatchObject({ name: "minecraft:diamond", count: 1, damage: 0, display_name: "", lore: [] });
  await search.fill("");
  await page.locator("#detailSlotNum").click();
  expect(await page.evaluate(() => inventory[0].name)).toBe("minecraft:diamond");
  await page.locator("#btnQuickClearSlot").click();
  expect(await page.evaluate(() => inventory[0])).toBeUndefined();
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].name)).toBe("minecraft:diamond");
});

test("IME composition stays local until complete and invalid input never overwrites an item", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 1, damage: 0, display_name: "Original" } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  const name = page.locator("#detailCustomName");
  await name.dispatchEvent("compositionstart");
  await name.fill("入力");
  expect(await page.evaluate(() => inventory[0].display_name)).toBe("Original");
  await name.dispatchEvent("compositionend");
  expect(await page.evaluate(() => inventory[0].display_name)).toBe("入力");
  const invalidName = "x".repeat(await page.evaluate(() => MAX_DISPLAY_NAME + 1));
  await name.fill(invalidName);
  expect(await page.evaluate(() => inventory[0].display_name)).toBe("入力");
  await expect(page.locator("#detailFormError")).toBeVisible();
  await page.locator('.inventory-slot[data-slot="1"]').click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await page.locator("#confirmCancel").click();
  await expect(name).toHaveValue(invalidName);
});

test("entity edits survive subsequent slot changes and ender chest edits apply directly", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:axolotl_bucket", count: 1, damage: 0,
    entity_variant: { entity_id: "minecraft:axolotl", variant: 1, is_baby: false, can_edit: true } } }, {
    ender_chest: { 0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0 } },
  });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailAxolotlColor").selectOption("4");
  await page.locator("#detailAxolotlAge").selectOption("baby");
  await page.locator("#detailCustomName").fill("Axolotl");
  expect(await page.evaluate(() => inventory[0].entity_variant_edit)).toMatchObject({ variant: 4, is_baby: true });
  await page.locator('.inventory-slot[data-ender-slot="0"]').click();
  await page.locator("#detailCount").fill("5");
  expect(await page.evaluate(() => enderChestInventory[0].count)).toBe(5);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => enderChestInventory[0].count)).toBe(2);
  expect(await page.evaluate(() => inventory[0].entity_variant_edit)).toMatchObject({ variant: 4, is_baby: true });
});

test("equipment wear and enchantments apply directly and undo separately", async ({ page }) => {
  await openSpecialFixture(page, { 103: { slot: 103, name: "minecraft:diamond_helmet", count: 1, damage: 16 } }, {
    items_db: { "minecraft:diamond_helmet": ["Diamanthelm", "Diamond Helmet"] },
    max_damage: { "minecraft:diamond_helmet": 363 },
    stack_limits: { "minecraft:diamond_helmet": 1 },
    ench_db: { 0: { name_de: "Schutz", name_en: "Protection", max_lvl: 4 } },
    enchantment_compatibility: { item_slots: { "minecraft:diamond_helmet": ["head"] }, compatible_slots: { 0: ["head"] } },
  });
  await page.locator('.armor-slot[data-slot="103"]').click();
  await page.locator("#detailDamage").fill("21");
  expect(await page.evaluate(() => inventory[103].damage)).toBe(21);
  await page.locator('[data-tab="tabEnchants"]').click();
  await page.locator("#enchantsContainer .ench-add select").selectOption("0");
  expect(await page.evaluate(() => inventory[103].enchantments)).toEqual([{ id: 0, lvl: 1 }]);
  await page.locator("#enchantsContainer .ench-level").selectOption("3");
  expect(await page.evaluate(() => inventory[103].enchantments)).toEqual([{ id: 0, lvl: 3 }]);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[103])).toMatchObject({ damage: 21, enchantments: [{ id: 0, lvl: 1 }] });
  await page.locator('[data-tab="tabEnchants"]').click();
  await page.locator("#btnMaxAllEnch").click();
  expect(await page.evaluate(() => inventory[103].enchantments)).toEqual([{ id: 0, lvl: 4 }]);
  await page.locator("#btnClearAllEnch").click();
  expect(await page.evaluate(() => inventory[103].enchantments)).toEqual([]);
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
});
