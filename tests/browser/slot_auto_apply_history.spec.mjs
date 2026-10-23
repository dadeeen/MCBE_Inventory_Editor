import { expect, test } from "@playwright/test";
import { openSpecialFixture, collectBrowserErrors } from "./fixtures/app.mjs";

test("reverting direct edits restores the exact saved slot without a write", async ({ page }) => {
  let writes = 0;
  page.on("request", request => { if (request.url().endsWith("/api/player/save")) writes++; });
  await openSpecialFixture(page, {
    0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0, nbt_view: { tag: "original" }, stack_key: "original-stack" },
    103: { slot: 103, name: "minecraft:diamond_helmet", count: 1, damage: 16,
      root_equipment_source_tag: "Armor", root_equipment_source_index: 0, source_item_digest: "a".repeat(64) },
  }, {
    ender_chest: { 0: { slot: 0, name: "minecraft:diamond", count: 3, damage: 0 } },
    items_db: { "minecraft:diamond_helmet": ["Diamanthelm", "Diamond Helmet"], "minecraft:diamond": ["Diamant", "Diamond"] },
    max_damage: { "minecraft:diamond_helmet": 363 },
  });
  const original = await page.evaluate(() => JSON.stringify(takeSnapshot()));
  for (const [selector, field, changed, restored] of [
    ['.inventory-slot[data-slot="0"]', "#detailCount", "7", "2"],
    ['.inventory-slot[data-ender-slot="0"]', "#detailCount", "8", "3"],
    ['.armor-slot[data-slot="103"]', "#detailDamage", "21", "16"],
  ]) {
    await page.locator(selector).click();
    await page.locator(field).fill(changed);
    expect(await page.evaluate(() => isDirty)).toBe(true);
    await page.locator(field).fill(restored);
    expect(await page.evaluate(() => JSON.stringify(takeSnapshot()))).toBe(original);
    expect(await page.evaluate(() => isDirty)).toBe(false);
    await page.locator("#detailCustomName").fill("Name");
    await page.locator("#detailLore").fill("Lore");
    await page.locator("#detailCustomName").fill("");
    expect(await page.evaluate(() => isDirty)).toBe(true);
    await page.locator("#detailLore").fill("");
    expect(await page.evaluate(() => JSON.stringify(takeSnapshot()))).toBe(original);
    await page.keyboard.press("Control+s");
    await expect(page.locator("#saveReviewOverlay")).toBeHidden();
  }
  expect(writes).toBe(0);
});

test("reverted typing does not leave an empty undo step ahead of earlier changes", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0 } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailCount").fill("7");
  await page.locator("#detailCustomName").fill("Temporary");
  await page.locator("#detailCustomName").fill("");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].count)).toBe(2);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await page.locator("#btnRedo").click();
  expect(await page.evaluate(() => inventory[0].count)).toBe(7);
  await page.locator("#detailCount").fill("9");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].count)).toBe(7);
});

test("entity variants can return to their saved state without losing other direct changes", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:axolotl_bucket", count: 1, damage: 0,
    entity_variant: { entity_id: "minecraft:axolotl", variant: 1, is_baby: false, can_edit: true } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  const original = await page.evaluate(() => JSON.stringify(inventory[0]));
  await page.locator("#detailAxolotlColor").selectOption("4");
  await page.locator("#detailAxolotlAge").selectOption("baby");
  await page.locator("#detailCustomName").fill("Keep me");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].entity_variant_edit)).toMatchObject({ variant: 4, is_baby: true });
  await page.locator("#btnRedo").click();
  await page.locator("#detailAxolotlColor").selectOption("1");
  await page.locator("#detailAxolotlAge").selectOption("adult");
  expect(await page.evaluate(() => inventory[0].display_name)).toBe("Keep me");
  await page.locator("#detailCustomName").fill("");
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(original);
  expect(await page.evaluate(() => isDirty)).toBe(false);
});

test("replacing an item and returning to its old ID retains replacement intent through undo and follow-up edits", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 1, damage: 0,
    has_protected_nbt: true, source_item_digest: "a".repeat(64) } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  for (const id of ["minecraft:diamond_sword", "minecraft:diamond"]) {
    await page.locator("#detailItemSearch").fill(id);
    await page.locator("#detailSlotNum").click();
  }
  await page.locator("#detailCount").fill("2");
  await page.locator("#detailCount").fill("1");
  expect(await page.evaluate(() => inventory[0])).toMatchObject({ replace_original_nbt: true,
    protected_nbt_dropped: true, previous_name: "minecraft:diamond" });
  expect(await page.evaluate(() => isDirty)).toBe(true);
  await page.locator("#btnUndo").click();
  await page.locator("#btnRedo").click();
  await page.locator("#detailCustomName").fill("Replacement");
  expect(await page.evaluate(() => inventory[0])).toMatchObject({ replace_original_nbt: true,
    protected_nbt_dropped: true, previous_name: "minecraft:diamond" });
});

test("save success, failed retry and undo use the latest authoritative item and revision", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const requests = [];
  let rejectNext = false;
  await page.route("**/api/player/save", async route => {
    const payload = route.request().postDataJSON();
    requests.push(payload);
    if (rejectNext) {
      rejectNext = false;
      await route.fulfill({ json: { success: false, error: "Synthetic validation failure" } });
      return;
    }
    const savedItem = { ...payload.inventory[0], source_item_digest: "b".repeat(64),
      nbt_view: { tag: "saved" }, has_preserved_nbt: true };
    delete savedItem.replace_original_nbt;
    await route.fulfill({ json: { success: true, write_committed: true, player_revision: "saved-revision",
      saved_items: { inventory: { 0: savedItem }, ender_chest: {} } } });
  });
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0 } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailCount").fill("7");
  await page.keyboard.press("Control+s");
  await expect(page.locator("#saveReviewOverlay")).toBeVisible();
  await page.keyboard.press("Control+z");
  expect(await page.evaluate(() => inventory[0].count)).toBe(7);
  await page.locator("#btnSaveReviewConfirm").click();
  await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
  expect(requests).toHaveLength(1);
  const saved = await page.evaluate(() => JSON.stringify(inventory[0]));
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator("#detailCount").fill("8");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(saved);
  await page.locator("#btnRedo").click();
  rejectNext = true;
  await page.keyboard.press("Control+s");
  await page.locator("#btnSaveReviewConfirm").click();
  await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
  expect(await page.evaluate(() => isDirty)).toBe(true);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(saved);
  await page.locator("#btnRedo").click();
  await page.locator("#detailCount").fill("9");
  await page.keyboard.press("Control+s");
  await page.locator("#btnSaveReviewConfirm").click();
  await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
  expect(requests).toHaveLength(3);
  expect(requests.slice(1).map(request => request.base_revision)).toEqual(["saved-revision", "saved-revision"]);
  expect(requests[2].inventory[0]).toMatchObject({ count: 9, source_item_digest: "b".repeat(64) });
  expect(await page.evaluate(() => isDirty)).toBe(false);
  expect(errors).toEqual([]);
});

test("composition and invalid drafts block save and history without losing accepted changes", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0 } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailCount").fill("7");
  const name = page.locator("#detailCustomName");
  await name.dispatchEvent("compositionstart");
  await name.fill("入力");
  await page.keyboard.press("Control+s");
  await expect(page.locator("#saveReviewOverlay")).toBeHidden();
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].count)).toBe(7);
  await name.dispatchEvent("compositionend");
  expect(await page.evaluate(() => inventory[0].display_name)).toBe("入力");
  await page.locator("#detailCount").fill("");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].count)).toBe(7);
  await page.locator("#detailCount").fill("7");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].display_name || "")).toBe("");
});
