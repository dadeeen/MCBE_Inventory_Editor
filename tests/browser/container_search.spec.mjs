import { expect, test } from "@playwright/test";
import {
  openSpecialFixture,
  collectBrowserErrors,
} from "./fixtures/app.mjs";

test("container search opens nested current drafts and retains cancel undo and focus", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const shulker = { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 2, source_index: 0, name: "minecraft:bundle", count: 1, damage: 0,
        special_item: { kind: "bundle", editable: true, data: { items: [
          { slot: 3, source_index: 0, name: "minecraft:diamond", count: 7, damage: 0, display_name: "Mein Fund" },
        ] } } },
    ] } } };
  await openSpecialFixture(page, { 1: { slot: 1, name: "minecraft:diamond", count: 1, damage: 0 } }, {
    ender_chest: { 0: shulker },
    items_db: { "minecraft:diamond": ["Diamant", "Diamond"], "minecraft:bundle": ["Bundle", "Bundle"],
      "minecraft:undyed_shulker_box": ["Shulkerkiste", "Shulker Box"] },
  });
  const before = await page.evaluate(() => JSON.stringify(enderChestInventory[0]));
  const search = page.locator("#gridSearch");
  const results = page.locator("#gridSearchResults");
  const hit = results.locator("button");
  const dialog = page.locator("#specialItemDialog");
  await expect(results).toBeHidden();
  for (const query of ["Diamant", "diamond", "mein fund"]) {
    await search.fill(query);
    await expect(hit).toHaveCount(1);
    await expect(hit).toContainText("Mein Fund");
    await expect(hit).toContainText("Enderchest 1 → Shulkerkiste → Slot 3: Bundle → Mein Fund");
    await expect(page.locator('[data-ender-slot="0"]')).toHaveCSS("opacity", "1");
  }
  if (process.env.MCBE_QA_SPECIAL_DIR) await results.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/container-search-desktop.png` });
  await hit.click();
  await expect(dialog.getByLabel("Menge", { exact: true })).toHaveValue("7");
  await dialog.getByLabel("Menge", { exact: true }).fill("12");
  for (let depth = 0; depth < 4; depth++) await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(search).toBeFocused();
  expect(await page.evaluate(() => JSON.stringify(enderChestInventory[0]))).toBe(before);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await hit.click();
  for (let depth = 0; depth < 3; depth++) await dialog.getByRole("button", { name: "Übernehmen und zurück", exact: true }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => JSON.stringify(enderChestInventory[0]))).toBe(before);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await hit.click();
  await dialog.getByLabel("Menge", { exact: true }).fill("23");
  for (let depth = 0; depth < 3; depth++) await dialog.getByRole("button", { name: "Übernehmen und zurück", exact: true }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  await expect(hit).toContainText("× 23");
  await expect(search).toBeFocused();
  await hit.click();
  await expect(dialog.getByLabel("Menge", { exact: true })).toHaveValue("23");
  for (let depth = 0; depth < 4; depth++) await page.keyboard.press("Escape");
  await page.locator("#btnUndo").click();
  await expect(hit).toContainText("× 7");
  await page.locator("#btnRedo").click();
  await expect(hit).toContainText("× 23");
  await search.fill("");
  await expect(results).toBeHidden();
  expect(errors).toEqual([]);
});

test("container search reports display limits protected branches and read only results", async ({ page }) => {
  const inventory = Object.fromEntries(Array.from({ length: 4 }, (_, rootSlot) => [rootSlot, {
    slot: rootSlot, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: Array.from({ length: 26 }, (_, slot) => ({
      slot, source_index: slot, name: "minecraft:diamond", count: 1, damage: 0,
      display_name: slot === 0 ? "<img src=x onerror=alert(1)>" : "",
    })) } },
  }]));
  inventory[4] = { slot: 4, name: "minecraft:bundle", count: 1, damage: 0,
    special_item: { kind: "bundle", editable: false, reason: "Geschützte Spezialdaten" } };
  await openSpecialFixture(page, inventory);
  await page.setViewportSize({ width: 390, height: 844 });
  const search = page.locator("#gridSearch");
  const results = page.locator("#gridSearchResults");
  await search.fill("diamond");
  await expect(results.locator("button")).toHaveCount(100);
  await expect(results.getByRole("status")).toContainText("Treffer in Behältern: 104");
  await expect(results.getByRole("status")).toContainText("Die ersten 100 Treffer");
  await expect(results.getByRole("status")).toContainText("nicht vollständig durchsucht");
  await expect(results.locator("img")).toHaveCount(0);
  expect(await results.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  if (process.env.MCBE_QA_SPECIAL_DIR) await results.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/container-search-mobile.png` });
  await page.evaluate(() => { appConfig.read_only = true; updateGridVisuals(); });
  await expect(results.locator("button").first()).toBeDisabled();
  await expect(results.locator("button").first()).toHaveAttribute("title", "Bearbeitung ist aktuell gesperrt.");
  await search.fill("no such item");
  await expect(results.locator("button")).toHaveCount(0);
  await expect(results.getByRole("status")).toContainText("nicht vollständig durchsucht");
  await search.fill("");
  await expect(results).toBeHidden();
  expect(await page.evaluate(() => isDirty)).toBe(false);
});

test("container search refuses a stale child path without creating a replacement draft", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [] } } } });
  await page.evaluate(() => openSpecialEditor(0, "inventory", null, [5]));
  const dialog = page.locator("#specialItemDialog");
  await expect(dialog.getByRole("alert")).toContainText("Suche erneut");
  await expect(dialog.locator(".special-slot")).toHaveCount(27);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.locator("#gridSearch")).toBeFocused();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  await expect(page.locator("#btnUndo")).toBeDisabled();
});
