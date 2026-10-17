import { expect, test } from "@playwright/test";
import fs from "node:fs";

async function openSpecialFixture(page, inventory, overrides = {}) {
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
    ...overrides,
  });
}

test("special contained data values validate registered variants and preserve unknown originals", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 0, source_index: 0, name: "minecraft:banner", count: 1, damage: 16 },
      { slot: 1, source_index: 1, name: "minecraft:banner", count: 1, damage: 0 },
      { slot: 2, source_index: 2, name: "minecraft:empty_map", count: 1, damage: 0 },
    ] } } } }, { max_damage: { __default__: 32767 } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Menge", { exact: true }).fill("2");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  for (const [slot, invalid, valid] of [[2, "16", "15"], [3, "1", "2"]]) {
    await dialog.getByRole("button", { name: new RegExp(`Slot ${slot}:`) }).click();
    await dialog.getByLabel("Abnutzung / Datenwert", { exact: true }).fill(invalid);
    await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Datenwert");
    await dialog.getByLabel("Abnutzung / Datenwert", { exact: true }).fill(valid);
    await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  }
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items.map(({ count, damage }) => ({ count, damage })))).toEqual([
    { count: 2, damage: 16 }, { count: 1, damage: 15 }, { count: 1, damage: 2 },
  ]);
});

test("special contained text preserves untouched raw strings and rejects silent truncation", async ({ page }) => {
  const original = { slot: 0, source_index: 0, name: "minecraft:diamond", count: 1, damage: 0,
    display_name: "Erste\nZweite", lore: ["Erste\r\nZweite", "Dritte\rVierte", "x".repeat(513)] };
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [original,
      { slot: 1, source_index: 1, name: "minecraft:diamond", count: 1, damage: 0, display_name: "x".repeat(513) },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Menge", { exact: true }).fill("2");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({ ...original, count: 2 });
  await page.locator("#btnSpecialItem").click();
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  const lore = dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true });
  for (const text of [Array(51).fill("Zeile").join("\n"), "x".repeat(511) + "🦜"]) {
    await lore.fill(text);
    await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Beschreibung");
    await expect(lore).toHaveValue(text);
  }
  await page.keyboard.press("Escape");
  await dialog.getByRole("button", { name: /Slot 2:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:writable_book");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Anzeigename");
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await dialog.getByLabel("Menge", { exact: true }).fill("2");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[1])).toMatchObject({ count: 2, display_name: "x".repeat(513) });
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0].lore)).toEqual(original.lore);
});

test("special bundles inside a shulker enforce their absolute nesting depth", async ({ page }) => {
  let nested = { slot: 0, source_index: 0, name: "minecraft:bundle", count: 1, damage: 0,
    special_item: { kind: "bundle", editable: true, data: { items: [] } } };
  for (let depth = 1; depth < 7; depth++) nested = { ...nested,
    special_item: { kind: "bundle", editable: true, data: { items: [nested] } } };
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [nested] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  for (let depth = 0; depth < 7; depth++) {
    await dialog.getByRole("button", { name: /Slot 1:/ }).click();
    await dialog.getByRole("button", { name: "Inhalte bearbeiten", exact: true }).click();
  }
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Verschachtelungstiefe");
  await expect(dialog.getByLabel("Item-ID", { exact: true })).toHaveValue("minecraft:diamond");
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("special editor text remains readable in the light theme", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 0, source_index: 0, name: "minecraft:diamond", count: 9, damage: 0 },
    ] } } } });
  await selectSetting(page, "themeSelect", "light");
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const samples = await dialog.evaluate(element => [element, ...element.querySelectorAll(".special-slot, .special-slot-count")].map(node => ({
    color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor,
  })));
  for (const sample of samples) expect(contrastRatio(sample.color, sample.background)).toBeGreaterThanOrEqual(4.5);
  const slot = dialog.getByRole("button", { name: /Slot 1:/ });
  await slot.hover();
  const hover = await slot.evaluate(node => ({ color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor }));
  expect(contrastRatio(hover.color, hover.background)).toBeGreaterThanOrEqual(4.5);
  await slot.click();
  const fields = await dialog.locator(".special-fields input, .special-fields textarea, .special-fields select").evaluateAll(nodes => nodes.map(node => ({
    color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor,
  })));
  for (const field of fields) expect(contrastRatio(field.color, field.background)).toBeGreaterThanOrEqual(4.5);
  if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/special-light.png`, animations: "disabled" });
});

test("keyboard item menu restores grid focus after copy clear paste and cut", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 9, damage: 0 } });
  const slot = page.locator('.inventory-slot[data-slot="0"]');
  const next = page.locator('.inventory-slot[data-slot="1"]');
  await slot.focus();
  for (const [action, keys, present] of [["copy", ["Home"], true], ["clear", ["End"], false], ["paste", ["Home", "ArrowDown"], true], ["cut", ["End", "ArrowUp"], false]]) {
    await page.keyboard.press("Shift+F10");
    for (const key of keys) await page.keyboard.press(key);
    await expect(page.locator(`#slotContextMenu [data-action="${action}"]`)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(slot).toBeFocused();
    expect(await page.evaluate(() => inventory[0]?.count)).toBe(present ? 9 : undefined);
    await page.keyboard.press("ArrowRight");
    await expect(next).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(slot).toBeFocused();
  }
});

test("special nested editor cancellation preserves the parent item draft", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0, display_name: "Meine sehr ausführlich beschriftete Shulkerkiste ".repeat(10) } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await page.setViewportSize({ width: 320, height: 568 });
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:written_book");
  await dialog.getByLabel("Menge", { exact: true }).fill("3");
  await dialog.getByLabel("Zielslot", { exact: true }).selectOption({ value: "5" });
  await dialog.getByLabel("Anzeigename", { exact: true }).fill("Mein Entwurf");
  await dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true }).fill("Unveröffentlicht");
  await dialog.getByRole("button", { name: "Buch bearbeiten", exact: true }).click();
  await dialog.getByLabel("Titel", { exact: true }).fill("Verwerfen");
  await page.keyboard.press("Escape");
  await expect(dialog.getByLabel("Item-ID", { exact: true })).toHaveValue("minecraft:written_book");
  await expect(dialog.getByLabel("Menge", { exact: true })).toHaveValue("3");
  await expect(dialog.getByLabel("Zielslot", { exact: true })).toHaveValue("5");
  await expect(dialog.getByLabel("Anzeigename", { exact: true })).toHaveValue("Mein Entwurf");
  await expect(dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true })).toHaveValue("Unveröffentlicht");
  await dialog.getByRole("button", { name: "Buch bearbeiten", exact: true }).click();
  await expect(dialog.getByLabel("Titel", { exact: true })).toHaveValue("");
  await page.keyboard.press("Escape");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({ slot: 5, name: "minecraft:written_book", count: 3, display_name: "Mein Entwurf", lore: ["Unveröffentlicht"] });
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  expect(errors).toEqual([]);
});

test("special contained enchantments retain levels and enforce the catalog bounds", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [{ slot: 0, source_index: 0, name: "minecraft:diamond_sword", count: 1, damage: 0, enchantments: [{ id: 9, lvl: 2 }] }] } } } }, {
    ench_db: { 9: { name_de: "Schärfe", name_en: "Sharpness", max_lvl: 5 }, 17: { name_de: "Haltbarkeit", name_en: "Unbreaking", max_lvl: 3 } },
    enchantment_compatibility: { item_slots: { "minecraft:diamond_sword": ["sword"] }, compatible_slots: { 9: ["sword"], 17: ["sword"] } },
  });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  const levels = dialog.getByLabel("Stufe", { exact: true });
  await expect(levels.first()).toHaveValue("2");
  await levels.first().fill("6");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Verzauberungsstufe");
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844], ["narrow", 320, 568]]) {
    await page.setViewportSize({ width, height });
    await levels.first().scrollIntoViewIfNeeded();
    expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    const header = await dialog.locator("header").evaluate(el => ({ top: el.getBoundingClientRect().top, closeTop: el.querySelector("button").getBoundingClientRect().top }));
    expect(header.closeTop - header.top).toBeLessThan(30);
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/enchantments-${name}.png`, animations: "disabled" });
  }
  await levels.first().fill("5");
  await dialog.getByLabel("Verzauberung hinzufügen", { exact: true }).selectOption("17");
  await expect(levels.nth(1)).toHaveValue("1");
  await levels.nth(1).fill("3");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0].enchantments)).toEqual([{ id: 9, lvl: 5 }, { id: 17, lvl: 3 }]);
  expect(errors).toEqual([]);
});

test("special unchanged child editing preserves unsorted original container contents", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 20, source_index: 0, name: "minecraft:diamond", count: 1, damage: 0 },
      { slot: 1, source_index: 1, name: "minecraft:diamond", count: 2, damage: 0 },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: /Slot 21:/ }).click();
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("special contained type changes detach the original before returning to the old type", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 0, source_index: 0, name: "minecraft:writable_book", count: 1, damage: 0,
        special_item: { kind: "book", editable: true, data: { pages: [{ source_index: 0, text: "Original" }] } } },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:writable_book");
  await dialog.getByRole("button", { name: "Buch bearbeiten", exact: true }).click();
  await expect(dialog).toContainText("0 / 50 Seiten");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  const child = await page.evaluate(() => inventory[0].special_edit.data.items[0]);
  expect(child.name).toBe("minecraft:writable_book");
  expect(child).not.toHaveProperty("source_index");
  expect(child).not.toHaveProperty("special_item");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_item.data.items[0].special_item.data.pages[0].text)).toBe("Original");
});

for (const clearFirst of [false, true]) {
  test(`special root replacement starts a fresh item after ${clearFirst ? "clearing" : "type changes"}`, async ({ page }) => {
    await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:writable_book", count: 1, damage: 0,
      source_item_digest: "a".repeat(64), special_item: { kind: "book", editable: true, data: { pages: [{ source_index: 0, text: "Original" }] } } } });
    await page.locator('.inventory-slot[data-slot="0"]').click();
    if (clearFirst) await page.locator("#btnQuickClearSlot").click();
    else {
      await page.locator("#detailItemSearch").fill("minecraft:diamond");
      await page.locator("#btnApplySingle").click();
    }
    await page.locator("#detailItemSearch").fill("minecraft:writable_book");
    await page.locator("#btnSpecialItem").click();
    const dialog = page.locator("#specialItemDialog");
    await expect(dialog).toContainText("0 / 50 Seiten");
    await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
    const replacement = await page.evaluate(() => inventory[0]);
    expect(replacement.replace_original_nbt).toBe(true);
    expect(replacement).not.toHaveProperty("source_item_digest");
    expect(replacement).not.toHaveProperty("special_item");
  });
}

for (const width of [1440, 390]) {
  test(`special successive saves use authoritative page origins and fresh metadata (${width}px)`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await page.setViewportSize({ width, height: 900 });
    const original = { slot: 0, name: "minecraft:writable_book", count: 1, damage: 0,
      special_item: { kind: "book", editable: true, data: { pages: [{ source_index: 0, text: "Erste" }, { source_index: 1, text: "Zweite" }] } } };
    await openSpecialFixture(page, { 0: original });
    await page.route("**/api/backups", route => route.fulfill({ json: { success: true, backups: [] } }));
    const requests = [];
    let saved = original;
    await page.route("**/api/player/save", route => {
      const payload = route.request().postDataJSON();
      requests.push(payload);
      const draft = payload.inventory[0];
      saved = { ...saved, ...draft, source_item_digest: "b".repeat(64), has_preserved_nbt: true,
        special_item: { kind: "book", editable: true, data: { pages: draft.special_edit.data.pages.map((entry, source_index) => ({ ...entry, source_index })) } } };
      delete saved.special_edit;
      return route.fulfill({ json: { success: true, player_revision: `saved-${requests.length}`, backup_file: "synthetic-backup.zip",
        item_source_digests: { inventory: { 0: saved.source_item_digest }, ender_chest: {} },
        saved_items: { inventory: { 0: saved }, ender_chest: {} } } });
    });
    await page.locator('.inventory-slot[data-slot="0"]').click();
    if (width < 600) await page.locator('.btn-toggle[data-panel="right"]').click();
    await page.locator("#btnSpecialItem").click();
    const dialog = page.locator("#specialItemDialog");
    await dialog.getByRole("button", { name: "Nach unten", exact: true }).first().click();
    await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
    await page.evaluate(() => saveCurrentPlayer({ skipReview: true }));
    expect(requests).toHaveLength(1);
    expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
    expect(await page.evaluate(() => isDirty)).toBe(false);
    await page.locator("#btnSpecialItem").click();
    await expect(dialog.getByLabel("Seite 1", { exact: true })).toHaveValue("Zweite");
    await dialog.getByLabel("Seite 1", { exact: true }).fill("Zweite, bearbeitet");
    expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/repeated-book-${width}.png`, animations: "disabled" });
    await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
    await page.evaluate(() => saveCurrentPlayer({ skipReview: true }));
    expect(requests).toHaveLength(2);
    expect(requests[1].inventory[0].special_edit.data.pages).toEqual([
      { source_index: 0, text: "Zweite, bearbeitet" }, { source_index: 1, text: "Erste" },
    ]);
    expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
    expect(await page.evaluate(() => currentPlayerStaleReason)).toBe("");
    expect(errors).toEqual([]);
  });
}

test("special saved draft without authoritative state requires reload before another write", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:writable_book", count: 1, damage: 0 } });
  let writes = 0;
  await page.route("**/api/player/save", route => {
    writes++;
    return route.fulfill({ json: { success: true, player_revision: "saved-revision", backup_file: "synthetic-backup.zip" } });
  });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: "Seite hinzufügen" }).click();
  await dialog.getByLabel("Seite 1", { exact: true }).fill("Entwurf");
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  await page.evaluate(() => saveCurrentPlayer({ skipReview: true }));
  expect(writes).toBe(1);
  await expect(page.locator("#btnSave")).toBeDisabled();
  expect(await page.evaluate(() => currentPlayerStaleReason)).toContain("Nachbearbeitung");
  await page.evaluate(() => saveCurrentPlayer({ skipReview: true }));
  expect(writes).toBe(1);
});

test("special contained numeric edits reject invalid input without silently clamping", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [{ slot: 0, source_index: 0, name: "minecraft:diamond", count: 10, damage: 0 }] } } } },
    { max_damage: { __default__: 0, "minecraft:diamond_sword": 100 } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond_sword");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Stacklimits");
  await dialog.getByLabel("Menge", { exact: true }).fill("1");
  for (const value of ["", "0.5", "101"]) {
    await dialog.getByLabel("Abnutzung / Datenwert", { exact: true }).fill(value);
    await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Datenwert");
  }
  await dialog.getByLabel("Abnutzung / Datenwert", { exact: true }).fill("1e1");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({ name: "minecraft:diamond_sword", count: 1, damage: 10 });
});

test("special editor cannot bypass equipment slot validation", async ({ page }) => {
  await openSpecialFixture(page, { [-106]: { slot: -106, name: "minecraft:firework_rocket", count: 1, damage: 0 } });
  await page.locator('.inventory-slot[data-slot="-106"]').click();
  await page.locator("#detailItemSearch").fill("minecraft:written_book");
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: "Seite hinzufügen" }).click();
  await dialog.getByLabel("Seite 1", { exact: true }).fill("Falscher Ausrüstungsslot");
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Schildhand");
  expect(await page.evaluate(() => inventory[-106].name)).toBe("minecraft:firework_rocket");
  await page.keyboard.press("Escape");
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("special editors isolate nested drafts, cancel, undo and preserve origins", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const original = { slot: 0, name: "minecraft:bundle", count: 1, damage: 0, special_item: { kind: "bundle", editable: true, data: { items: [{ slot: 2, source_index: 2, name: "minecraft:diamond", count: 7, damage: 0 }] } } };
  await openSpecialFixture(page, { 0: original });
  const slot = page.locator('.inventory-slot[data-slot="0"]');
  await slot.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Inhalte bearbeiten" }).click();
  const dialog = page.locator("#specialItemDialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("7 / 64 Gewichtseinheiten");
  await dialog.getByRole("button", { name: /Slot 3:/ }).click();
  await dialog.getByLabel("Menge", { exact: true }).fill("23");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog).toContainText("23 / 64 Gewichtseinheiten");
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await dialog.locator('footer [data-special="cancel"]').click();
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator("#btnSpecialItem").click();
  await expect(dialog).toContainText("7 / 64 Gewichtseinheiten");
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator("#btnSpecialItem").click();
  await dialog.getByRole("button", { name: /Slot 3:/ }).click();
  await dialog.getByLabel("Menge", { exact: true }).fill("23");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const edited = await page.evaluate(() => inventory[0]);
  expect(edited.special_edit.data.items[0]).toMatchObject({ count: 23, source_index: 2 });
  expect(edited.special_edit.data.items[0]).not.toHaveProperty("source_slot");
  expect(await page.evaluate(() => buildChangeSummary().shown[0].label)).toContain("Container-Inhalte geändert");
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator("#btnRedo").click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0].count)).toBe(23);
  expect(errors).toEqual([]);
});

test("special editors validate bundle capacity and keyboard focus at mobile width", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:bundle", count: 1, damage: 0, special_item: { kind: "bundle", editable: true, data: { items: [{ slot: 0, source_index: 0, name: "minecraft:diamond", count: 64, damage: 0 }] } } } });
  const slot = page.locator('.inventory-slot[data-slot="0"]');
  await slot.focus(); await page.keyboard.press("Shift+F10");
  await expect(page.locator('#slotContextMenu [data-action="special"]')).toBeFocused();
  await page.keyboard.press("Enter");
  const dialog = page.locator("#specialItemDialog");
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: process.env.MCBE_QA_SPECIAL_DIR + "/bundle-mobile.png" });
  await dialog.getByRole("button", { name: /Slot 2:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog.getByRole("alert")).toContainText("zu voll");
  await page.keyboard.press("Escape");
  await expect(dialog).toContainText("64 / 64 Gewichtseinheiten");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(slot).toBeFocused();
  expect(errors).toEqual([]);
});

test("special book firework banner and shulker forms produce independent edits", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const names = ["written_book", "firework_rocket", "banner", "undyed_shulker_box", "firework_star"];
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openSpecialFixture(page, Object.fromEntries(names.map((name, slot) => [slot, { slot, name: `minecraft:${name}`, count: 1, damage: 0 }])));
  const dialog = page.locator("#specialItemDialog");
  async function open(slot) { await page.locator(`.inventory-slot[data-slot="${slot}"]`).click(); await page.locator("#btnSpecialItem").click(); }
  async function apply() { await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click(); }
  async function checkMobile(name) {
    await page.setViewportSize({width:390,height:844});
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    const bounds = await dialog.evaluate(el => ({
      bottom:el.getBoundingClientRect().bottom, footerTop:el.querySelector('footer').getBoundingClientRect().top,
      footerBottom:el.querySelector('footer').getBoundingClientRect().bottom, bodyBottom:el.querySelector('.special-body').getBoundingClientRect().bottom,
    }));
    expect(bounds.bodyBottom).toBeLessThanOrEqual(bounds.footerTop + 1);
    expect(bounds.footerBottom).toBeLessThanOrEqual(bounds.bottom + 1);
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: process.env.MCBE_QA_SPECIAL_DIR + `/${name}-mobile.png`, animations:"disabled" });
    await page.setViewportSize({width:1440,height:1000});
  }
  await open(0);
  await dialog.getByLabel("Titel", { exact: true }).fill("Reisetagebuch");
  await dialog.getByLabel("Autor", { exact: true }).fill("Alex");
  await dialog.getByRole("button", { name: "Seite hinzufügen" }).click();
  await dialog.getByLabel("Seite 1", { exact: true }).fill("Grüße aus der Oberwelt!\nZweite Zeile.");
  if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: process.env.MCBE_QA_SPECIAL_DIR + "/book-desktop.png" });
  await checkMobile("book");
  await apply();
  await open(1); await dialog.getByLabel("Flugdauer", { exact: true }).selectOption("3");
  await dialog.getByRole("button", { name: "Effekt hinzufügen" }).click();
  await dialog.getByLabel("Form", { exact: true }).selectOption("2");
  await dialog.getByRole("group", { name: "Farben", exact: true }).getByLabel("Rot", { exact: true }).check();
  await dialog.getByLabel("Schweif", { exact: true }).check();
  if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: process.env.MCBE_QA_SPECIAL_DIR + "/firework-desktop.png" });
  await checkMobile("firework");
  await apply();
  await open(2); await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Muster", { exact: true }).selectOption("bo");
  await dialog.getByLabel("Farbe", { exact: true }).selectOption("1"); await checkMobile("banner"); await apply();
  await open(3); await expect(dialog.locator(".special-slot")).toHaveCount(27);
  if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: process.env.MCBE_QA_SPECIAL_DIR + "/shulker-desktop.png" });
  await checkMobile("shulker");
  await dialog.getByRole("button", { name: /Slot 27:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:bundle");
  await dialog.getByRole("button", { name: "Inhalte bearbeiten" }).click();
  await dialog.getByRole("button", { name: /Slot 1:/ }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await dialog.getByLabel("Menge", { exact: true }).fill("12");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await apply();
  await open(4); await dialog.getByRole("button", { name: "Effekt hinzufügen" }).click(); await apply();
  const result = await page.evaluate(() => Object.values(inventory).map(item => item.special_edit));
  expect(result[0].data.pages[0].text).toContain("Grüße");
  expect(result[1].data).toMatchObject({ flight: 3, explosions: [{ shape: 2, colors: [1, 15], trail: true }] });
  expect(result[2].data.patterns).toEqual([{ pattern: "bo", color: 1 }]);
  expect(result[3].data.items[0].special_edit.data.items[0].count).toBe(12);
  expect(result[4].data.explosions).toHaveLength(1);
  expect(errors).toEqual([]);
});

async function prepareBannerTextures(page, { synthetic = false, publish = true } = {}) {
  const generated = await page.evaluate(() => {
    const codes = ["base", ...JSON.parse(document.getElementById("specialItemSchema").textContent).patterns];
    return Object.fromEntries(codes.map((code, index) => {
      const canvas = document.createElement("canvas"); canvas.width = 20; canvas.height = 40;
      const ctx = canvas.getContext("2d");
      const image = ctx.createImageData(20, 40);
      for (let y = 0; y < 40; y++) for (let x = 0; x < 20; x++) {
        const offset = (y * 20 + x) * 4;
        image.data.set([255, 255, 255, 0], offset);
        if (code === "base") image.data.set([200, 200, 200, 255], offset);
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

test("banner preview renders all motifs and keeps desktop and mobile layouts usable", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15 } });
  const { assets } = await prepareBannerTextures(page);
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const preview = dialog.locator(".special-banner-preview");
  const canvas = preview.locator("canvas");
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Farbe", { exact: true }).selectOption("4");
  const images = [];
  for (const pattern of Object.keys(assets).filter(code => code !== "base")) {
    await dialog.getByLabel("Muster", { exact: true }).selectOption(pattern);
    await expect(preview).toHaveAttribute("data-state", "ready");
    images.push({ pattern, url: await canvas.evaluate(el => el.toDataURL()) });
  }
  expect(new Set(images.map(image => image.url)).size).toBe(42);
  await dialog.getByLabel("Muster", { exact: true }).selectOption("glb");
  await expect(canvas).toHaveAccessibleName(/Globus, Blau/);
  await expect(preview).toHaveAttribute("data-state", "ready");
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844], ["narrow", 320, 568], ["landscape", 844, 390]]) {
    await page.setViewportSize({ width, height });
    await canvas.scrollIntoViewIfNeeded();
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    const bounds = await dialog.evaluate(el => ({
      bottom: el.getBoundingClientRect().bottom, footerTop: el.querySelector("footer").getBoundingClientRect().top,
      footerBottom: el.querySelector("footer").getBoundingClientRect().bottom, bodyBottom: el.querySelector(".special-body").getBoundingClientRect().bottom,
    }));
    expect(bounds.bodyBottom).toBeLessThanOrEqual(bounds.footerTop + 1);
    expect(bounds.footerBottom).toBeLessThanOrEqual(bounds.bottom + 1);
    const size = await canvas.boundingBox(); expect(size.height / size.width).toBe(2);
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/banner-${name}.png`, animations: "disabled" });
    // The inputs and apply action remain reachable at every viewport size.
    await dialog.getByLabel("Farbe", { exact: true }).selectOption("1");
    await expect(preview).toHaveAttribute("data-state", "ready");
    await dialog.getByLabel("Farbe", { exact: true }).selectOption("4");
  }
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.patterns)).toEqual([{ pattern: "glb", color: 4 }]);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  if (process.env.MCBE_QA_SPECIAL_DIR) {
    await page.setViewportSize({ width: 1200, height: 1200 });
    await page.evaluate(images => {
      const gallery = document.createElement("div"); gallery.id = "qa-banner-gallery";
      gallery.style.cssText = "position:absolute;inset:0;z-index:99999;display:grid;grid-template-columns:repeat(7,1fr);gap:16px;padding:24px;background:#17232c;color:white;";
      images.forEach(({ pattern, url }) => {
        const cell = document.createElement("div"); cell.style.cssText = "display:grid;justify-items:center;gap:6px;";
        const image = document.createElement("img"); image.src = url; image.style.cssText = "width:60px;height:120px;image-rendering:pixelated";
        cell.append(image, document.createTextNode(pattern)); gallery.append(cell);
      }); document.body.append(gallery);
    }, images);
    await page.locator("#qa-banner-gallery").screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/banner-all-patterns.png` });
  }
  expect(errors).toEqual([]);
});

test("banner preview preserves alpha, dye color and layer order through edits and cancel", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15, special_item: { kind: "banner", editable: true,
    data: { patterns: [{ pattern: "cre", color: 1 }, { pattern: "glb", color: 4 }] } } } });
  await prepareBannerTextures(page, { synthetic: true });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const preview = dialog.locator(".special-banner-preview");
  async function pixel(x, y) {
    await expect(preview).toHaveAttribute("data-state", "ready");
    return preview.locator("canvas").evaluate((el, [x, y]) => Array.from(el.getContext("2d").getImageData(x, y, 1, 1).data), [x, y]);
  }
  // Bottom-right is tinted base cloth; lower-left is opaque red; upper-left
  // is half-transparent blue over red (rounded source-over blend).
  expect(await pixel(15, 30)).toEqual([188, 188, 188, 255]);
  expect(await pixel(5, 30)).toEqual([176, 46, 38, 255]);
  const blend = await pixel(5, 5);
  for (const [index, value] of [118, 57, 104, 255].entries()) expect(Math.abs(blend[index] - value)).toBeLessThanOrEqual(1);
  await dialog.getByRole("button", { name: "Nach oben", exact: true }).nth(1).click();
  expect(await pixel(5, 5)).toEqual([176, 46, 38, 255]);
  await dialog.getByRole("button", { name: "Entfernen", exact: true }).nth(1).click();
  await dialog.getByLabel("Muster", { exact: true }).selectOption("gra");
  expect(await pixel(5, 0)).toEqual([188, 188, 188, 255]);
  expect(await pixel(5, 39)).toEqual([60, 68, 170, 255]);
  await page.keyboard.press("Escape");
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("banner preview recovers missing assets without losing a draft", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15 } });
  const { response } = await prepareBannerTextures(page, { synthetic: true, publish: false });
  let attempts = 0;
  await page.route("**/api/icons/vanilla/update", route => {
    attempts++;
    return route.fulfill({ json: attempts === 1 ? { success: false, error: "Test: Download unterbrochen" } : response });
  });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Muster", { exact: true }).selectOption("sku");
  await expect(dialog.locator(".special-banner-preview")).toHaveAttribute("data-state", "missing");
  await expect(dialog.locator("canvas")).toBeHidden();
  await dialog.getByRole("button", { name: "Bannermuster laden" }).click();
  await expect(dialog.getByRole("status")).toContainText("Download unterbrochen");
  await dialog.getByRole("button", { name: "Bannermuster laden" }).click();
  await expect(dialog.locator(".special-banner-preview")).toHaveAttribute("data-state", "ready");
  await expect(dialog.getByLabel("Muster", { exact: true })).toHaveValue("sku");
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(attempts).toBe(2);
  await page.keyboard.press("Escape");
});

test("banner preview rejects broken textures, retries, and discards late renders", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15 } });
  const { generated } = await prepareBannerTextures(page, { synthetic: true });
  await page.route("**/api/icons/qa-banner-base", route => route.fulfill({ contentType: "image/png", body: Buffer.from("invalid") }));
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const preview = dialog.locator(".special-banner-preview");
  await expect(preview).toHaveAttribute("data-state", "error");
  await page.unroute("**/api/icons/qa-banner-base");
  await dialog.getByRole("button", { name: "Erneut versuchen" }).click();
  await expect(preview).toHaveAttribute("data-state", "ready");
  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  await page.route("**/api/icons/qa-banner-cre", async route => {
    await delayed; await route.fulfill({ contentType: "image/png", body: Buffer.from(generated.cre, "base64") });
  });
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Muster", { exact: true }).selectOption("cre");
  await expect(preview).toHaveAttribute("data-state", "loading");
  await dialog.getByLabel("Muster", { exact: true }).selectOption("glb");
  await expect(preview).toHaveAttribute("data-state", "ready");
  const before = await preview.locator("canvas").evaluate(el => el.toDataURL());
  const lateResponse = page.waitForResponse("**/api/icons/qa-banner-cre");
  release();
  await (await lateResponse).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  expect(await preview.locator("canvas").evaluate(el => el.toDataURL())).toBe(before);
  await expect(preview.locator("canvas")).toHaveAccessibleName(/Globus/);
  await page.keyboard.press("Escape");
});

test.describe("banner preview touch interaction", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
  test("six layers remain editable with a sharp preview on a mobile device", async ({ page }) => {
    await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15, special_item: { kind: "banner", editable: true,
      data: { patterns: ["gra", "cre", "bri", "flw", "bo", "sku"].map((pattern, index) => ({ pattern, color: index })) } } } });
    await prepareBannerTextures(page);
    await page.locator('.inventory-slot[data-slot="0"]').tap();
    await page.locator('.btn-toggle[data-panel="right"]').tap();
    await page.locator("#btnSpecialItem").tap();
    const dialog = page.locator("#specialItemDialog");
    const preview = dialog.locator(".special-banner-preview");
    await expect(preview).toHaveAttribute("data-state", "ready");
    await expect(dialog.getByRole("button", { name: "Muster hinzufügen" })).toBeDisabled();
    await dialog.getByLabel("Muster", { exact: true }).nth(5).selectOption("gus");
    await dialog.getByLabel("Farbe", { exact: true }).nth(5).selectOption("1");
    await dialog.getByRole("button", { name: "Nach oben", exact: true }).nth(5).tap();
    await expect(preview).toHaveAttribute("data-state", "ready");
    await expect(preview.locator("canvas")).toHaveAccessibleName(/Ebene 5: Windstoßer, Rot/);
    await preview.scrollIntoViewIfNeeded();
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/banner-touch.png`, animations: "disabled" });
    await dialog.getByRole("button", { name: "Übernehmen", exact: true }).tap();
    expect(await page.evaluate(() => inventory[0].special_edit.data.patterns[4])).toEqual({ pattern: "gus", color: 1 });
    await page.locator("#btnUndo").tap();
    expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  });
});

test("special editors keep unknown formats read only and ordinary edits retain drafts", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:bundle", count: 1, damage: 0, special_item: { kind: "bundle", editable: false, reason: "Geschützte Spezialdaten" } }, 1: { slot: 1, name: "minecraft:writable_book", count: 1, damage: 0 } });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await expect(dialog).toContainText("Geschützte Spezialdaten");
  await expect(dialog.getByRole("button", { name: "Übernehmen", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.locator('.inventory-slot[data-slot="1"]').click();
  await page.locator("#detailCustomName").fill("Lokaler Entwurf");
  await page.locator("#btnSpecialItem").click();
  await dialog.getByRole("button", { name: "Seite hinzufügen" }).click();
  await dialog.getByLabel("Seite 1", { exact: true }).fill("Text");
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  await page.locator("#detailCustomName").fill("Neuer Name"); await page.locator("#btnApplySingle").click();
  expect(await page.evaluate(() => inventory[1])).toMatchObject({ display_name: "Neuer Name", special_edit: { kind: "book", data: { pages: [{ text: "Text" }] } } });
});

test("special editor refuses a stale parent and restores focus on cancel", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:writable_book", count: 1, damage: 0 } });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: "Seite hinzufügen" }).click();
  await dialog.getByLabel("Seite 1", { exact: true }).fill("Stale edit");
  await page.evaluate(() => { inventory[0] = { slot:0, name:"minecraft:diamond", count:2, damage:0 }; });
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("inzwischen geändert");
  expect(await page.evaluate(() => inventory[0])).toEqual({ slot:0, name:"minecraft:diamond", count:2, damage:0 });
  await page.keyboard.press("Escape");
  await expect(page.locator("#btnSpecialItem")).toBeFocused();
});

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
    if (message.type() === "error" && !isExpectedHttpConsoleNoise(text)) {
      const source = message.location().url;
      browserErrors.push(source ? `${text} (${source})` : text);
    }
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
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
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

async function openDragFixture(page, overrides = {}, players = null) {
  const player = { player_key: "drag-player", label: "Drag Test", editable: true, exportable: true, has_inventory_tag: true, has_ender_chest_tag: true };
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
}

async function openChangeHistory(page) {
  await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
  await page.locator('[data-tab-dash="dashSession"]').click();
  await expect(page.locator('#dashSession')).toBeVisible();
}

test("change history records each drag once and retains opposite same-second actions", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page);
  await page.clock.setFixedTime(new Date('2026-01-01T12:00:00Z'));
  await page.evaluate(() => document.addEventListener('drop', event => {
    window.historyTestDragPayload = event.dataTransfer?.getData('application/x-mcbe-slot');
  }, true));
  const initial = await page.evaluate(() => JSON.stringify(inventory));
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  await expect(page.locator('#sessionLogContainer .edit')).toHaveCount(1);
  const label = await page.locator('#sessionLogContainer .edit strong').textContent();
  expect(label).toContain('1× Stein');
  expect(label).toContain('verschoben');
  await expect(page.locator('#btnUndo')).toHaveAttribute('title', new RegExp('verschoben'));
  // Replay the consumed payload as a second drop: no active drag remains.
  const transfer = await page.evaluateHandle(() => {
    const data = new DataTransfer();
    data.setData('application/x-mcbe-slot', window.historyTestDragPayload);
    return data;
  });
  await page.locator('[data-slot="0"]').dispatchEvent('drop', { dataTransfer: transfer });
  await transfer.dispose();
  await expect(page.locator('#sessionLogContainer .edit')).toHaveCount(1);
  await page.locator('[data-slot="1"]').dragTo(page.locator('[data-slot="0"]'));
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(initial);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await expect(page.locator('#sessionLogContainer .edit')).toHaveCount(2);
  const times = await page.locator('#sessionLogContainer .edit .session-log-time').allTextContents();
  expect(times[0]).toBe(times[1]);
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="2"]'));
  await expect(page.locator('#sessionLogContainer .edit').first()).toContainText('getauscht');
  await expect(page.locator('#sessionLogContainer .edit').first()).toContainText('Karotte');
  await page.keyboard.down('Control');
  await page.locator('[data-slot="2"]').dragTo(page.locator('[data-slot="1"]'));
  await page.keyboard.up('Control');
  await expect(page.locator('#sessionLogContainer .edit').first()).toContainText('kopiert');
  await expect(page.locator('#sessionLogContainer .edit')).toHaveCount(4);
  await openChangeHistory(page);
  await page.locator('#btnHistoryUndo').focus();
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => inventory[1])).toBeUndefined();
  await page.locator('#btnHistoryRedo').click();
  expect(await page.evaluate(() => inventory[1].name)).toBe('minecraft:stone');
  expect(errors).toEqual([]);
});

for (const width of [1440, 390, 320]) {
  test.describe(`change history at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width < 500, isMobile: width < 500 });
    test('shows status and supports undo, redo, copy and log clearing', async ({ page, context }) => {
      test.setTimeout(45_000);
      const errors = collectBrowserErrors(page);
      const activate = locator => width < 500 ? locator.tap() : locator.click();
      await context.grantPermissions(['clipboard-read', 'clipboard-write']);
      await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
      await page.route("**/api/server_status", route => route.fulfill({ json: { success: true, server_status: { status: "offline" }, write_gate: { allowed: true, read_allowed: true } } }));
      await openDragFixture(page, { stack_limits: { 'minecraft:stone': 64 } });
      await openChangeHistory(page);
      await expect(page.locator('#historySaveState')).toHaveAttribute('data-state', 'clean');
      await expect(page.locator('#btnHistoryUndo')).toBeDisabled();
      await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
      await activate(page.locator('[data-slot="0"]'));
      if (width < 500) await activate(page.locator('.btn-toggle[data-panel="right"]'));
      await page.locator('#detailCount').fill('5');
      await activate(page.locator('#btnApplySingle'));
      await openChangeHistory(page);
      await expect(page.locator('#historySaveState')).toHaveAttribute('data-state', 'dirty');
      await expect(page.locator('#undoRedoPanel')).toContainText('aktualisiert');
      await activate(page.locator('#btnHistoryUndo'));
      expect(await page.evaluate(() => inventory[0].count)).toBe(1);
      await expect(page.locator('#historySaveState')).toHaveAttribute('data-state', 'clean');
      await activate(page.locator('#btnHistoryRedo'));
      expect(await page.evaluate(() => inventory[0].count)).toBe(5);
      await expect(page.locator('#historySaveState')).toHaveAttribute('data-state', 'dirty');
      await activate(page.locator('#btnCopySessionLog'));
      expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('aktualisiert');
      await expect(page.locator('.toast-container .toast')).toHaveCount(0);
      for (const layout of ['classic', 'studio', 'focus']) {
        await selectLayout(page, layout);
        await openChangeHistory(page);
        for (const theme of ['dark', 'light']) {
          await selectSetting(page, 'themeSelect', theme);
          await page.locator('#dashSession').scrollIntoViewIfNeeded();
          const bounds = await page.locator('#dashSession').evaluate(panel => ({
            width: panel.clientWidth, scroll: panel.scrollWidth,
            controls: [...panel.querySelectorAll('.history-actions button')].map(el => {
              const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, height: r.height };
            }), viewport: innerWidth,
          }));
          expect(bounds.scroll).toBeLessThanOrEqual(bounds.width + 1);
          for (const button of bounds.controls) {
            expect(button.left).toBeGreaterThanOrEqual(0);
            expect(button.right).toBeLessThanOrEqual(bounds.viewport);
            expect(button.height).toBeGreaterThanOrEqual(44);
          }
          await captureBrowserEvidence(page, `history-${width}-${layout}-${theme}`);
        }
      }
      await activate(page.locator('#btnClearSessionLog'));
      await expect(page.locator('#sessionLogContainer .session-log-row')).toHaveCount(0);
      await expect(page.locator('#btnClearSessionLog')).toBeDisabled();
      await expect(page.locator('#btnHistoryUndo')).toBeEnabled();
      expect(await page.evaluate(() => inventory[0].count)).toBe(5);
      await activate(page.locator('#btnHistoryUndo'));
      expect(await page.evaluate(() => inventory[0].count)).toBe(1);
      await expect(page.locator('#historySaveState')).toHaveAttribute('data-state', 'clean');
      if (width === 1440) {
        await selectLayout(page, 'classic');
        await page.locator('#btnHistoryRedo').click();
        let saved;
        await page.route('**/api/player/save', route => {
          saved = route.request().postDataJSON();
          return route.fulfill({ json: { success: true, player_revision: 'history-saved', backup_file: 'synthetic-backup.zip' } });
        });
        await page.locator('.app-workflow-nav [data-workflow-view="save"]').click();
        await page.locator('#btnSaveWorkflowRun').click();
        await expect.poll(() => saved).toBeTruthy();
        await openChangeHistory(page);
        await expect(page.locator('#historySaveState')).toHaveAttribute('data-state', 'clean');
        await expect(page.locator('#btnHistoryUndo')).toBeDisabled();
        await expect(page.locator('#btnHistoryRedo')).toBeDisabled();
        await expect(page.locator('#sessionLogContainer .save')).toHaveCount(1);
      }
      expect(errors).toEqual([]);
    });
  });
}

test('change history groups live input and change events without losing separate edits', async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.route('**/api/world/presence', route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page, {
    abilities: { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.05, vertical_fly_speed: 1 },
    effects: [{ id: 1, amplifier: 0, duration: 600, show_particles: true }],
    effects_db: { 1: ['Tempo', 'Speed'] },
    protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true, has_abilities_tag: true, has_active_effects_tag: true },
  });
  await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
  await page.locator('[data-tab-dash="dashEffects"]').click();
  const speed = page.locator('#abFlySpeed');
  await speed.fill('0.2');
  await speed.press('Tab');
  await expect(page.locator('#sessionLogContainer .edit')).toHaveCount(1);
  await expect(page.locator('#btnUndo')).toHaveAttribute('data-history-count', '1');
  await speed.fill('0.3');
  await speed.press('Tab');
  await expect(page.locator('#sessionLogContainer .edit')).toHaveCount(2);
  await page.locator('#btnUndo').click();
  expect(await page.evaluate(() => playerAbilities.fly_speed)).toBe(0.2);
  const particles = page.locator('.eff-particles');
  await particles.uncheck();
  await particles.check();
  await expect(page.locator('#sessionLogContainer .edit')).toHaveCount(4);
  await page.locator('#btnUndo').click();
  expect(await page.evaluate(() => playerEffects[0].show_particles)).toBe(false);
  expect(errors).toEqual([]);
});

test('change history translates its controls and wraps long names on a narrow screen', async ({ page }) => {
  await page.context().addCookies([{ name: 'mcbe_locale', value: 'en', url: NORMAL_BASE_URL }]);
  await page.route('**/api/world/presence', route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page, { inventory: { 0: { slot: 0, name: 'minecraft:stone', count: 32, damage: 0, display_name: 'LongItemName'.repeat(15) } } });
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  await page.setViewportSize({ width: 320, height: 900 });
  await openChangeHistory(page);
  await expect(page.locator('#dashSession h3')).toHaveText('Change history');
  await expect(page.locator('#btnHistoryUndo')).toContainText('Undo');
  await expect(page.locator('#btnClearSessionLog')).toHaveText('Clear log');
  await expect(page.locator('#historySaveState')).toHaveText('Unsaved changes');
  await expect(page.locator('#sessionLogContainer .edit strong')).toContainText('Moved 32×');
  const overflow = await page.locator('#dashSession').evaluate(el => el.scrollWidth > el.clientWidth + 1);
  expect(overflow).toBe(false);
  await page.locator('#dashSession').scrollIntoViewIfNeeded();
  await captureBrowserEvidence(page, 'history-320-english-long-name');
});

test("main item edits preserve untouched raw names and lore in both containers", async ({ page }) => {
  const original = { slot: 0, name: "minecraft:stone", count: 1, damage: 0,
    display_name: "Erste\nZweite", lore: ["Erste\r\nZweite", "Dritte\rVierte", "x".repeat(513)] };
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page, { inventory: { 0: original }, ender_chest: { 0: original }, stack_limits: { "minecraft:stone": 64 } });
  for (const container of ["inventory", "ender_chest"]) {
    await page.locator(container === "inventory" ? '[data-slot="0"]' : '[data-ender-slot="0"]').click();
    await page.locator("#detailCount").fill("2");
    await page.locator("#btnApplySingle").click();
    expect(await page.evaluate(name => (name === "inventory" ? inventory : enderChestInventory)[0], container)).toMatchObject({ ...original, count: 2 });
  }
});

test("main item editor rejects oversized text without changing the item or losing input", async ({ page }) => {
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page, { stack_limits: { "minecraft:stone": 64 } });
  await page.locator('[data-slot="0"]').click();
  const original = await page.evaluate(() => inventory[0]);
  for (const [id, value, message] of [
    ["detailCustomName", "x".repeat(511) + "🦜", "Anzeigename"],
    ["detailLore", Array(51).fill("Zeile").join("\n"), "Beschreibung"],
    ["detailLore", "x".repeat(511) + "🦜", "Beschreibung"],
  ]) {
    await page.locator(`#${id}`).fill(value);
    await page.locator("#btnApplySingle").click();
    await expect(page.locator(".toast-warning").last()).toContainText(message);
    await expect(page.locator(`#${id}`)).toHaveValue(value);
    expect(await page.evaluate(() => inventory[0])).toEqual(original);
    await expect(page.locator("#btnUndo")).toBeDisabled();
    await page.locator(`#${id}`).fill("");
  }
});

for (const withMounts of [false, true]) {
  test(`uncertain ${withMounts ? "mount" : "player"} save blocks all retries until reload`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/server_status", route => route.fulfill({ json: {
      success: true, server_status: { status: "offline" }, write_gate: { allowed: true },
    } }));
    await page.route("**/api/backups", route => route.fulfill({ json: { success: true, backups: [] } }));
    let attempts = 0;
    await page.route(withMounts ? "**/api/workspace/save" : "**/api/player/save", route => {
      attempts++;
      return route.fulfill({ status: 500, json: {
        success: false, write_outcome_unknown: true, reload_required: true,
        backup_file: "synthetic-backup.zip",
        error: "Ob die Änderungen bereits geschrieben wurden, ist unbekannt. Nicht erneut speichern; Welt neu laden und Backup prüfen.",
      } });
    });
    await openDragFixture(page);
    if (withMounts) {
      await page.evaluate(() => getMountController().setPendingMounts([{
        id: "synthetic-mount", mountType: "minecraft:donkey", mountLabel: "Esel",
        worldPath, playerKey: currentPlayerKey, createMode: "synthetic_full",
        allowUncheckedPlacement: true, preferredOffset: { x: 2, z: 2 },
        selectedPosition: { x: 2, y: 64, z: 2 }, safetyStatus: "unchecked",
      }], { renderPanel: false }));
    } else {
      await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
    }
    expect(await page.evaluate(() => isDirty)).toBe(true);
    await page.evaluate(() => saveCurrentPlayer({ skipReview: true }));
    expect(attempts).toBe(1);
    await expect(page.locator("#btnSave")).toBeDisabled();
    await expect(page.locator("#btnSaveWorkflowRun")).toBeDisabled();
    expect(await page.evaluate(() => currentPlayerStaleReason)).toContain("unbekannt");
    expect(await page.evaluate(() => currentPlayerRevision)).toBe("drag-revision");
    expect(await page.evaluate(() => isDirty)).toBe(true);
    expect(await page.evaluate(() => getMountController().getPendingMounts().length)).toBe(withMounts ? 1 : 0);
    await page.evaluate(() => saveCurrentPlayer({ skipReview: true }));
    expect(attempts).toBe(1);
    expect(errors).toEqual([]);
  });
}

async function openPlayerSwitchFixture(page, { fromProtected = false, toProtected = false } = {}) {
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

async function copyPlayerFixtureItem(page) {
  await page.locator('[data-slot="0"]').click();
  await page.keyboard.press("Control+c");
  await page.locator('[data-slot="1"]').click();
}

async function captureBrowserEvidence(page, name, selector = null) {
  const directory = process.env.MCBE_BROWSER_EVIDENCE_DIR;
  if (!directory) return;
  fs.mkdirSync(directory, { recursive: true });
  const target = selector ? page.locator(selector) : page;
  await target.screenshot({ path: `${directory}/${name}.png`, animations: "disabled",
    style: selector ? ".toast-container { visibility: hidden; }" : undefined });
}

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
  await page.locator("#btnApplySingle").click();
  await expect(page.locator('[data-slot="0"] .item-count')).toHaveText("16");
  await page.locator('[data-slot="1"]').click();
  await expect(page.locator("#btnQuickMaxStack")).toBeEnabled();
  await page.locator("#btnQuickMaxStack").click();
  await expect(page.locator("#detailCount")).toHaveValue("16");
  await expect(page.locator('[data-slot="1"] .item-count')).toHaveText("16");
  await page.locator('[data-slot="0"]').click();
  await expect(page.locator("#detailCount")).toHaveValue("16");
  await page.locator("#btnApplySingle").click();
  await expect(page.locator('[data-slot="0"] .item-count')).toHaveText("16");
  await expect(page.locator("#slotQuickSubtitle")).toContainText("Stacklimit ungeprüft");
  await expect(page.locator("#btnQuickMaxStack")).toBeDisabled();
  expect(browserErrors).toEqual([]);
});

async function openBackupSettings(page) {
  await page.locator('.app-section-nav [data-workflow-view="tools"]').click();
  await page.locator('[data-tab-dash="dashBackups"]').click();
  await expect(page.locator("#backupSettingsPanel")).toBeVisible();
}

async function openBackupSettingsApp(page) {
  // These settings tests do not exercise server probing. Keep those background
  // polls out of the shared rate-limit bucket used by the world workflow tests.
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, status: "offline", write_gate: { allowed: true, read_allowed: true },
  } }));
  await openAppWithEmptyWorldScan(page);
}

test("backup size setting persists through reload without selecting a world", async ({ page }, testInfo) => {
  const errors = collectBrowserErrors(page);
  await openBackupSettingsApp(page);
  await openBackupSettings(page);
  const input = page.locator("#backupMaxSizeGib");
  await expect(input).toBeEnabled();
  const original = await input.inputValue();
  await input.fill("2.5");
  const savedResponse = page.waitForResponse(response => response.url().endsWith("/api/backup/settings") && response.request().method() === "POST");
  await page.locator("#btnSaveBackupSettings").click();
  expect((await (await savedResponse).json()).settings.max_uncompressed_mib).toBe(2560);
  await page.reload();
  await openBackupSettings(page);
  await expect(input).toHaveValue("2.5");
  await page.locator("#backupSettingsPanel").screenshot({ path: testInfo.outputPath("backup-settings.png") });
  await input.fill(original);
  const resetResponse = page.waitForResponse(response => response.url().endsWith("/api/backup/settings") && response.request().method() === "POST");
  await page.locator("#btnSaveBackupSettings").click();
  expect((await resetResponse).ok()).toBe(true);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({width, height: 900});
    await captureBrowserEvidence(page, `backup-size-setting-${width}`, '#backupSettingsPanel');
  }
  expect(errors).toEqual([]);
});

test("operator backup limit is visible but cannot be edited", async ({ page }) => {
  await page.route("**/api/backup/settings", route => route.fulfill({ json: {
    success: true, settings: { max_uncompressed_mib: 4096, source: "environment", editable: false },
  } }));
  await openBackupSettingsApp(page);
  await openBackupSettings(page);
  await expect(page.locator("#backupMaxSizeGib")).toHaveValue("4");
  await expect(page.locator("#backupMaxSizeGib")).toBeDisabled();
  await expect(page.locator("#btnSaveBackupSettings")).toBeDisabled();
  await expect(page.locator("#backupSettingsStatus")).toContainText("MCBE_BACKUP_MAX_UNCOMPRESSED_MIB");
});

test("backup limit error offers a direct link to its settings", async ({ page }) => {
  await openBackupSettingsApp(page);
  await page.evaluate(async () => {
    const response = new Response(JSON.stringify({ success: false, code: "backup_limit_exceeded", error: "limit" }), {
      status: 400, headers: { "Content-Type": "application/json" },
    });
    await window.MCBEApiClient.createApiClient().parseJsonResponse(response);
  });
  await page.locator(".toast-container .toast button").click();
  await expect(page.locator("#backupSettingsPanel")).toBeVisible();
  await expect(page.locator("#backupSettingsPanel")).toBeFocused();
});

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
    await expect(page.locator("#detailDataVariantLabel")).toHaveText("Banner color");
    await expect(page.locator("#detailDataVariant")).toHaveValue("14");
    await expect(page.locator("#detailDataVariant option:checked")).toHaveText("Orange Banner");

    if (process.env.MCBE_QA_VARIANT_SCREENSHOT) {
      await page.screenshot({ path: process.env.MCBE_QA_VARIANT_SCREENSHOT, fullPage: false });
    }
    expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
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
  await openDragFixture(page, { addable_items: ["minecraft:stone"] });
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

  // Filter down to one real catalog hit, then select it without a pointer.
  for (const key of ["Enter", "Space"]) {
    await trigger.focus();
    await page.keyboard.press("Enter");
    await page.locator("#browserSearchInput").fill("minecraft:stone");
    const card = page.locator("#browserGrid .browser-item");
    await expect(card).toHaveCount(1);
    await page.locator("#browserSortSelect").focus();
    await page.keyboard.press("Tab");
    await expect(card).toBeFocused();
    await page.keyboard.press(key);
    await expect(overlay).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(page.locator("#bulkItemSearch")).toHaveValue("minecraft:stone");
  }
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
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

test("slot editor suggestions rank exact names first and close after Enter", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const player = {
    player_key: "local",
    label: "Lokaler Spieler",
    kind: "local",
    editable: true,
    exportable: true,
    has_inventory_tag: true,
  };
  const catalog = JSON.parse(fs.readFileSync("mcbe_editor/resources/item_db.json", "utf8"));
  const fences = Object.fromEntries(Object.entries(catalog.items).filter(([id]) => (
    catalog.addable_items.includes(id) && id.includes("fence")
  )));
  const fenceCount = Object.keys(fences).length;
  expect(fenceCount).toBeGreaterThan(20);
  // Registry order deliberately keeps the exact match behind its substring hits.
  const itemsDb = {
    ...fences,
    "minecraft:bedrock": ["Grundgestein", "Bedrock"],
    "minecraft:blackstone": ["Schwarzstein", "Blackstone"],
    "minecraft:cobblestone": ["Bruchstein", "Cobblestone"],
    "minecraft:stone": ["Stein", "Stone"],
    "minecraft:stone_stairs": ["Steintreppe", "Stone Stairs"],
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
      player_revision: "autocomplete-revision",
      server_guard_epoch: 0,
      inventory: { 0: { slot: 0, name: "minecraft:cobblestone", count: 1, damage: 0 } },
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
      addable_items: Object.keys(itemsDb),
      block_only_items: [],
      block_items: [],
      ench_db: {},
      enchantment_compatibility: {},
      item_components: {},
      effects_db: {},
      stack_limits: { __default__: 64 },
      max_damage: { __default__: 32767 },
      compatibility: {},
    }),
  }));

  await openAppWithSmokeWorldScan(page);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();
  await page.locator('[data-slot="0"]').click();
  await expect(page.locator("#detailItemSearch")).toBeVisible();

  const autocomplete = page.locator("#detailItemAutocomplete");
  await page.locator("#detailItemSearch").fill("Stein");
  await expect(autocomplete).toBeVisible();
  await expect(autocomplete.locator(".autocomplete-item")).toHaveCount(5);
  await expect(autocomplete.locator(".autocomplete-item").first().locator(".item-id")).toHaveText("minecraft:stone");

  // Enter applies the exact match and leaves the suggestion list closed.
  await page.locator("#detailItemSearch").press("Enter");
  await expect(page.locator("#detailItemSearch")).toHaveValue("minecraft:stone");
  await expect(autocomplete).toBeHidden();
  await expect(page.locator("#detailPreviewName")).toHaveText("Stein");

  // Ambiguous input keeps the choice with the user.
  await page.locator("#detailItemSearch").fill("stei");
  await expect(autocomplete).toBeVisible();
  await page.locator("#detailItemSearch").press("Enter");
  await expect(page.locator("#detailItemSearch")).toHaveValue("stei");
  await expect(autocomplete).toBeVisible();

  // A unique substring resolves without an exact name.
  await page.locator("#detailItemSearch").fill("stone_st");
  await page.locator("#detailItemSearch").press("Enter");
  await expect(page.locator("#detailItemSearch")).toHaveValue("minecraft:stone_stairs");
  await expect(autocomplete).toBeHidden();

  // Broad searches must make every match reachable, including fences after
  // the initial ten suggestions. Loading the last page must not close the list.
  await page.locator("#detailItemSearch").fill("Zaun");
  const more = autocomplete.locator(".autocomplete-load-more");
  await expect(autocomplete.locator(".autocomplete-item")).toHaveCount(10);
  await expect(more).toHaveText(`Weitere 10 von ${fenceCount - 10} anzeigen`);
  await more.focus();
  await more.press("Enter");
  await expect(autocomplete.locator(".autocomplete-item")).toHaveCount(20);
  await expect(autocomplete.locator(".autocomplete-item").nth(10)).toBeFocused();
  while (await more.count()) await more.click();
  await expect(autocomplete.locator(".autocomplete-item")).toHaveCount(fenceCount);
  await expect(more).toHaveCount(0);
  await expect(autocomplete).toBeVisible();
  const fenceRow = autocomplete.locator(".autocomplete-item").filter({
    has: page.locator(".item-id", { hasText: /^minecraft:dark_oak_fence$/ }),
  });
  await fenceRow.focus();
  await fenceRow.press("Enter");
  await expect(page.locator("#detailItemSearch")).toHaveValue("minecraft:dark_oak_fence");
  await expect(page.locator("#detailPreviewName")).toHaveText("Schwarzeichenholzzaun");
  await expect(autocomplete).toBeHidden();
  await expect(page.locator("#detailItemSearch")).toBeFocused();

  // A new query starts a fresh page and scroll position; exact IDs still win.
  await page.locator("#detailItemSearch").fill("Zaun");
  await expect(autocomplete.locator(".autocomplete-item")).toHaveCount(10);
  await expect.poll(() => autocomplete.evaluate(element => element.scrollTop)).toBe(0);
  await page.locator("#detailItemSearch").fill("minecraft:dark_oak_fence");
  await expect(more).toHaveCount(0);
  await expect(autocomplete.locator(".autocomplete-item").first().locator(".item-id")).toHaveText("minecraft:dark_oak_fence");
  await page.locator("#detailItemSearch").press("Enter");
  await expect(autocomplete).toBeHidden();

  await page.locator("#detailItemSearch").fill("Zaun");
  await page.locator("#detailItemSearch").press("Escape");
  await expect(autocomplete).toBeHidden();
  await expect(page.locator("#detailItemSearch")).toHaveValue("Zaun");
  await expect(page.locator("#detailItemSearch")).toBeVisible();

  // Moving focus to another field must not leave a stale popup in the editor.
  await page.locator("#detailItemSearch").fill("Zaun");
  await page.locator("#detailCount").focus();
  await expect(autocomplete).toBeHidden();

  // Bulk autocomplete exposes the same later matches, but choosing one only
  // fills the bulk form; it must not immediately overwrite selected slots.
  await page.locator('[data-slot="0"]').click();
  await page.locator('[data-slot="1"]').click({ modifiers: ["Control"] });
  const bulkSearch = page.locator("#bulkItemSearch");
  const bulkList = page.locator("#bulkItemAutocomplete");
  await bulkSearch.fill("Zaun");
  while (await bulkList.locator(".autocomplete-load-more").count()) {
    await bulkList.locator(".autocomplete-load-more").click();
  }
  await expect(bulkList.locator(".autocomplete-item")).toHaveCount(fenceCount);
  const spruceRow = bulkList.locator(".autocomplete-item").filter({
    has: page.locator(".item-id", { hasText: /^minecraft:spruce_fence$/ }),
  });
  await spruceRow.focus();
  await spruceRow.press("Enter");
  await expect(bulkSearch).toHaveValue("minecraft:spruce_fence");
  await expect(bulkList).toBeHidden();
  await expect(bulkSearch).toBeFocused();
  await page.locator('[data-slot="0"]').click();
  await expect(page.locator("#detailItemSearch")).toHaveValue("minecraft:dark_oak_fence");

  // The popup must remain readable and fit its input in every theme, including
  // narrow layouts. The old fixed dark background obscured light-theme text.
  for (const theme of ["dark", "light", "minecraft"]) {
    await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      if (width < 700) await page.locator('[data-panel="right"]').click();
      await page.locator("#detailItemSearch").fill("Zaun");
      const popup = await autocomplete.evaluate(element => ({
        background: getComputedStyle(element).backgroundColor,
        name: getComputedStyle(element.querySelector("strong")).color,
        id: getComputedStyle(element.querySelector(".item-id")).color,
        more: getComputedStyle(element.querySelector(".autocomplete-load-more")).color,
        moreBackground: getComputedStyle(element.querySelector(".autocomplete-load-more")).backgroundColor,
        client: element.clientWidth,
        scroll: element.scrollWidth,
      }));
      for (const foreground of [popup.name, popup.id]) {
        expect(contrastRatio(foreground, popup.background), `${theme} text at ${width}px`).toBeGreaterThanOrEqual(4.5);
      }
      expect(contrastRatio(popup.more, compositeColor(popup.moreBackground, popup.background))).toBeGreaterThanOrEqual(4.5);
      expect(popup.scroll).toBeLessThanOrEqual(popup.client);
    }
  }

  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

test("light item browser keeps readable colors and a stable width while scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 947, height: 813 });
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));
  await openAppAndWaitForScan(page);
  await selectSetting(page, "themeSelect", "light");
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
  // This flow exercises asset updates; server polling is covered separately
  // and must not consume the shared read budget of the smoke-test process.
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, status: "offline", write_gate: { allowed: true, read_allowed: true },
  } }));
  // Opening Tools also refreshes the diagnostic panel, which is outside this
  // asset-update flow and must not depend on earlier tests' shared read budget.
  await page.route("**/api/diagnostics/status", route => route.fulfill({ json: {
    success: true, mode: "local", data_root: { writable: true },
    write_gate: { allowed: true, read_allowed: true },
  } }));
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
  await expect(page.locator("#btnUpdateDbApply")).toBeEnabled();

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
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
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

test("a player changed outside the editor shows an error until it is reloaded", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const stored = { revision: "drag-revision", fingerprint: "at-load" };
  const presenceBodies = [];
  await page.route("**/api/world/presence", route => {
    const body = route.request().postDataJSON();
    presenceBodies.push(body);
    const json = { success: true, other_sessions: 0 };
    if (body.fingerprint_baseline) {
      json.world_fingerprint = stored.fingerprint;
      // The server reads the player once the world stayed the same for a poll.
      if (body.fingerprint_seen === stored.fingerprint) json.player_revision = stored.revision;
    }
    return route.fulfill({ json });
  });
  let loads = 0;
  await openDragFixture(page, () => {
    loads++;
    return { player_revision: stored.revision, world_fingerprint: stored.fingerprint };
  });
  expect(loads).toBe(1);
  const status = page.locator("#statusStackButton");
  const toast = page.locator(".toast-error", { hasText: "seit dem Laden verändert" });
  await page.evaluate(() => updateWorldPresence());
  await expect(status).not.toHaveClass(/\berror\b/);

  // Minecraft saves the world after changing this player.
  stored.revision = "minecraft-revision";
  stored.fingerprint = "after-minecraft";
  await page.evaluate(() => updateWorldPresence());
  await expect(status).not.toHaveClass(/\berror\b/);
  await page.evaluate(() => updateWorldPresence());
  await expect(status).toHaveClass(/\berror\b/);
  await expect(page.locator("#statusStackSummary")).toContainText("seit dem Laden verändert");
  await expect(toast).toBeVisible();
  const checked = presenceBodies.filter(body => body.fingerprint_seen === "after-minecraft");
  expect(checked.length).toBeGreaterThan(0);
  expect(checked[0].fingerprint_baseline).toBe("at-load");

  // Reloading keeps the world and the current view; only the player is read
  // again, and loading it clears the error.
  await page.locator('.app-section-nav button[data-workflow-view="inventory"]').click();
  const worldBefore = await page.evaluate(() => worldPath);
  await toast.getByRole("button", { name: "Spieler neu laden" }).click();
  await expect.poll(() => loads).toBe(2);
  await expect(status).not.toHaveClass(/\berror\b/);
  await expect(page.locator("#statusStackSummary")).not.toContainText("seit dem Laden verändert");
  expect(await page.evaluate(() => currentPlayerRevision)).toBe("minecraft-revision");
  expect(await page.evaluate(() => worldPath)).toBe(worldBefore);
  expect(await page.evaluate(() => activeWorkflowView)).toBe("inventory");
  await expect(page.locator("#inventoryContainer")).toBeVisible();

  // After the toast, the error in the status area still offers the reload.
  stored.revision = "second-minecraft-revision";
  stored.fingerprint = "after-second-change";
  await page.evaluate(() => updateWorldPresence());
  await page.evaluate(() => updateWorldPresence());
  await expect(status).toHaveClass(/\berror\b/);
  await expect(toast).toBeVisible();
  await status.click();
  await page.locator("#statusStackPanel").getByRole("button", { name: "Spieler neu laden" }).click();
  await expect.poll(() => loads).toBe(3);
  await expect(status).not.toHaveClass(/\berror\b/);
  // The reload locks the app; afterwards the status button has the focus again.
  await expect(status).toBeFocused();
  // The toast goes with the error instead of offering a reload for 7 seconds.
  await expect(toast).toHaveCount(0, { timeout: 1500 });
  expect(await page.evaluate(() => currentPlayerRevision)).toBe("second-minecraft-revision");
  expect(await page.evaluate(() => activeWorkflowView)).toBe("inventory");
  expect(browserErrors).toEqual([]);
});

test("keyboard focus returns to its element after loading and saving", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, server_status: { status: "offline" }, write_gate: { allowed: true },
  } }));
  await page.route("**/api/backups", route => route.fulfill({ json: { success: true, backups: [] } }));
  let saves = 0;
  await page.route("**/api/player/save", route => {
    saves++;
    return route.fulfill({ json: { success: true, player_revision: `saved-${saves}`, backup_file: "focus-test.zip" } });
  });
  let loads = 0;
  await openDragFixture(page, () => {
    loads++;
    return {};
  });
  const appArea = page.locator(".app-container");

  // Loading a player locks the app and renders the list anew; the new row
  // of the same player gets the focus.
  const row = page.locator('.player-row[data-player-key="drag-player"]');
  await row.focus();
  const oldRow = await row.elementHandle();
  await page.keyboard.press("Enter");
  await expect.poll(() => loads).toBe(2);
  await expect(appArea).not.toHaveAttribute("inert", "");
  await expect(row).toBeFocused();
  expect(await oldRow.evaluate(element => element.isConnected)).toBe(false);

  // Saving with the keyboard from a slot passes through the review dialog;
  // afterwards the slot has the focus again.
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  expect(await page.evaluate(() => isDirty)).toBe(true);
  const slot = page.locator('[data-slot="1"]');
  await slot.focus();
  await page.keyboard.press("Control+s");
  await expect(page.locator("#btnSaveReviewConfirm")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => saves).toBe(1);
  await expect(page.locator("#saveReviewOverlay")).toBeHidden();
  await expect(slot).toBeFocused();
  expect(await page.evaluate(() => isDirty)).toBe(false);

  // Loading the world from the world view switches to the inventory, where
  // the load button is hidden; the focus lands at the start of that view.
  await page.locator('.app-section-nav button[data-workflow-view="world"]').click();
  await page.locator("#btnLoad").focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => loads).toBe(3);
  await expect(page.locator("#btnLoad")).toBeHidden();
  await expect(page.locator('[data-view-landing="inventory"]')).toBeFocused();

  // A narrow layout also opens the inventory after loading a world and
  // restores focus to the visible inventory landing point.
  await page.setViewportSize({ width: 1000, height: 800 });
  await page.locator('.app-section-nav button[data-workflow-view="world"]').click();
  await page.locator("#btnLoad").focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => loads).toBe(4);
  await expect(page.locator('[data-view-landing="inventory"]')).toBeVisible();
  await expect(page.locator('[data-view-landing="inventory"]')).toBeFocused();
  expect(browserErrors).toEqual([]);
});

test("dialogs return the keyboard focus to the element that opened them", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async () => { document.activeElement?.blur(); throw new Error("Synthetic clipboard denial"); },
    } });
  });
  let loads = 0;
  await openDragFixture(page, () => {
    loads++;
    return {};
  });

  // Cancelling the question about discarding changes returns to its button.
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  await page.locator('.app-section-nav button[data-workflow-view="save"]').click();
  const discard = page.locator("#btnReviewDiscardChanges");
  await discard.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  await expect(page.locator("#confirmOk")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#confirmCancel")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator("#confirmOk")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  await expect(discard).toBeFocused();
  await page.keyboard.press("Enter");
  await page.locator("#confirmCancel").click();
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  await expect(discard).toBeFocused();
  expect(await page.evaluate(() => isDirty)).toBe(true);
  expect(loads).toBe(1);

  // A confirmation without a cancel button keeps both Tab directions on OK.
  await page.evaluate(() => {
    window.confirmResult = null;
    void showConfirmDialog("Prüfhinweis", { cancelLabel: "" }).then(value => { window.confirmResult = value; });
  });
  await expect(page.locator("#confirmOk")).toBeFocused();
  for (const key of ["Tab", "Shift+Tab"]) {
    await page.keyboard.press(key);
    await expect(page.locator("#confirmOk")).toBeFocused();
  }
  await page.keyboard.press("Enter");
  await expect(page.locator("#confirmOverlay")).toBeHidden();
  expect(await page.evaluate(() => window.confirmResult)).toBe(true);
  await expect(discard).toBeFocused();

  // Help keeps focus on its only action, then returns to the help button.
  const helpButton = page.locator("#btnHelp");
  await helpButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#helpOverlay")).toBeVisible();
  await expect(page.locator("#btnHelpClose")).toBeFocused();
  for (const key of ["Tab", "Shift+Tab"]) {
    await page.keyboard.press(key);
    await expect(page.locator("#btnHelpClose")).toBeFocused();
  }
  await page.keyboard.press("Escape");
  await expect(page.locator("#helpOverlay")).toBeHidden();
  await expect(helpButton).toBeFocused();

  // Clipboard rejection may blur the opener; the fallback retains it anyway.
  expect(await page.evaluate(() => copyTextToClipboard("Unveränderter Prüftext"))).toBe(false);
  const fallback = page.locator("#copyFallbackOverlay");
  const text = page.locator("#copyFallbackText");
  await expect(fallback).toBeVisible();
  await expect(text).toBeFocused();
  await expect(text).toHaveValue("Unveränderter Prüftext");
  expect(await text.evaluate(el => el.selectionEnd - el.selectionStart)).toBe("Unveränderter Prüftext".length);
  for (const selector of ["#btnCopyFallbackClose", "#btnCopyFallbackDone", "#btnCopyFallbackSelect", "#copyFallbackText"]) {
    await page.keyboard.press("Shift+Tab");
    await expect(page.locator(selector)).toBeFocused();
  }
  await page.keyboard.press("Escape");
  await expect(fallback).toBeHidden();
  await expect(helpButton).toBeFocused();
  await page.evaluate(() => copyTextToClipboard("Erneute Prüfung"));
  await expect(text).toBeFocused();
  for (const selector of ["#btnCopyFallbackSelect", "#btnCopyFallbackDone"]) {
    await page.keyboard.press("Tab");
    await expect(page.locator(selector)).toBeFocused();
  }
  await page.keyboard.press("Enter");
  await expect(fallback).toBeHidden();
  await expect(helpButton).toBeFocused();
  expect(browserErrors).toEqual([]);
});

test("restore review traps keyboard focus and requires its confirmation before reloading", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, server_status: { status: "offline" }, write_gate: { allowed: true, read_allowed: true },
  } }));
  const filename = "synthetic-restore.zip";
  const backup = { filename, kind: "manual", size_mb: 1, date: "17.10.2026", file_count: 4,
    dir_count: 1, uncompressed_mb: 2, has_db: true, top_level_entries: ["db", "level.dat"] };
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await page.route("**/api/backups", route => route.fulfill({ json: { success: true, backups: [backup] } }));
  await page.route("**/api/backup/restore_preview", route => route.fulfill({ json: {
    success: true, backup, backup_token: "synthetic-preview", effects: [], target_world: { name: "Drag Test World" },
  } }));
  const restores = [];
  await page.route("**/api/restore_backup", route => {
    restores.push(route.request().postDataJSON());
    return route.fulfill({ json: { success: true, pre_restore_backup: "synthetic-before.zip" } });
  });
  let loads = 0;
  await openDragFixture(page, () => { loads++; return {}; });
  await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
  await page.locator('[data-tab-dash="dashBackups"]').click();
  const trigger = page.locator('.restore-btn');
  const overlay = page.locator('#restoreReviewOverlay');
  const input = page.locator('#restoreConfirmInput');
  const confirm = page.locator('#btnRestoreReviewConfirm');
  for (const width of [1280, 320]) {
    await page.setViewportSize({ width, height: 844 });
    // Resizing updates the responsive panel on the next browser frame.
    await expect(trigger).toBeVisible();
    await expect(trigger).toBeEnabled();
    await trigger.focus();
    await expect(trigger).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(overlay).toBeVisible();
    await expect(input).toBeFocused();
    await expect(confirm).toBeDisabled();
    await page.keyboard.press('Shift+Tab');
    await expect(page.locator('#btnRestoreReviewClose')).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(page.locator('#btnRestoreReviewCancel')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('#btnRestoreReviewClose')).toBeFocused();
    await input.fill('WIEDERHERSTELLEN');
    await expect(confirm).toBeEnabled();
    await confirm.focus();
    await page.keyboard.press('Tab');
    await expect(page.locator('#btnRestoreReviewClose')).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(confirm).toBeFocused();
    await captureBrowserEvidence(page, `restore-keyboard-${width}`);
    await page.keyboard.press('Escape');
    await expect(overlay).toBeHidden();
    await expect(trigger).toBeFocused();
    expect(restores).toHaveLength(0);
    expect(loads).toBe(1);
  }
  await page.keyboard.press('Enter');
  await expect(input).toHaveValue('');
  await input.fill('falsch');
  await expect(confirm).toBeDisabled();
  await input.fill('WIEDERHERSTELLEN');
  await confirm.focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => restores.length).toBe(1);
  expect(restores[0].backup_file).toBe(filename);
  expect(restores[0].backup_token).toBe('synthetic-preview');
  await expect.poll(() => loads).toBe(2);
  await expect(overlay).toBeHidden();
  await expect(page.locator('#loadingOverlay')).toBeHidden();
  expect(await page.evaluate(() => currentPlayerKey)).toBe('drag-player');
  expect(errors).toEqual([]);
});

test("player stats, abilities and hints remain inside every layout on mobile", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = collectBrowserErrors(page);
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  for (const locale of ["de", "en"]) {
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openDragFixture(page);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await selectSetting(page, "themeSelect", "light");
    for (const layout of ["classic", "studio", "focus"]) {
      await selectLayout(page, layout);
      await page.locator(`[data-workflow-view="${layout === "classic" ? "player" : "player-edit"}"]`).first().click();
      for (const tab of ["dashStats", "dashEffects"]) {
        await page.locator(`[data-tab-dash="${tab}"]`).click();
        const panel = page.locator(`#${tab}`);
        for (const width of [1440, 390, 320]) {
          await page.setViewportSize({ width, height: 900 });
          await expect(panel).toBeVisible();
          expect(await panel.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
          const clipped = await panel.evaluate(el => {
            const panel = el.getBoundingClientRect();
            return Array.from(el.querySelectorAll("input, select, label, .field-note")).filter(field => {
              if (!field.getClientRects().length) return false;
              const rect = field.getBoundingClientRect();
              return rect.left < panel.left - 1 || rect.right > panel.right + 1;
            }).map(field => field.id || field.textContent);
          });
          expect(clipped, `${locale}/${layout}/${tab}/${width}`).toEqual([]);
          if (process.env.MCBE_BROWSER_EVIDENCE_DIR) await panel.screenshot({
            path: `${process.env.MCBE_BROWSER_EVIDENCE_DIR}/player-values-${locale}-${layout}-${tab}-${width}.png`,
            animations: "disabled",
          });
        }
      }
    }
  }
  expect(errors).toEqual([]);
});

test("help and long confirmations remain reachable in narrow and short windows", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await openDragFixture(page);
  for (const layout of ["classic", "studio", "focus"]) {
    await selectLayout(page, layout);
    for (const theme of ["light", "dark"]) {
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
      for (const [width, height] of [[320, 740], [390, 844], [844, 390]]) {
        await page.setViewportSize({ width, height });
        await page.locator("#btnHelp").click();
        const help = page.locator(".help-box");
        await expect(help).toBeVisible();
        const box = await help.boundingBox();
        expect(box.y).toBeGreaterThanOrEqual(15);
        expect(box.y + box.height).toBeLessThanOrEqual(height - 15);
        expect(await help.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
        const content = page.locator(".help-content");
        expect(await content.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
        await content.evaluate(el => { el.scrollTop = el.scrollHeight; });
        await expect(page.locator(".help-hint")).toBeInViewport();
        await page.locator("#btnHelpClose").click();
        await expect(page.locator("#helpOverlay")).toBeHidden();

        await page.evaluate(() => {
          void showConfirmDialog("Wichtiger Hinweis: Prüfe die ausgewählte Welt und alle Änderungen.\n".repeat(15));
        });
        const confirm = page.locator("#confirmOverlay .modal-box");
        const confirmBox = await confirm.boundingBox();
        expect(confirmBox.y).toBeGreaterThanOrEqual(15);
        expect(confirmBox.y + confirmBox.height).toBeLessThanOrEqual(height - 15);
        await page.locator("#confirmCancel").click();
        await expect(page.locator("#confirmOverlay")).toBeHidden();
        await page.evaluate(() => { void openSaveReview(buildChangeSummary()); });
        const review = page.locator(".save-review-box");
        expect(await review.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
        await expect(page.locator("#btnSaveReviewConfirm")).toBeInViewport();
        await page.locator("#btnSaveReviewCancel").click();
        await expect(page.locator("#saveReviewOverlay")).toBeHidden();
      }
    }
  }
  expect(browserErrors).toEqual([]);
});

test("status entries keep the color of their kind and stay readable in every theme", async ({ page }) => {
  await openAppWithEmptyWorldScan(page);
  for (const theme of ["dark", "system", "light", "minecraft"]) {
    await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
    const entries = await page.evaluate(() => {
      const panel = document.getElementById("statusStackPanel");
      const rgba = value => {
        const [r, g, b, a = 1] = value.match(/[\d.]+/g).map(Number);
        return { r, g, b, a };
      };
      const over = (top, bottom) => Object.fromEntries(["r", "g", "b"].map(channel => [
        channel, top[channel] * top.a + bottom[channel] * (1 - top.a),
      ]).concat([["a", 1]]));
      const luminance = color => ["r", "g", "b"].map(channel => {
        const value = color[channel] / 255;
        return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
      const contrast = (first, second) => {
        const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
        return (light + 0.05) / (dark + 0.05);
      };
      const page = document.createElement("div");
      page.style.color = "var(--bg-main)";
      panel.appendChild(page);
      const panelBackground = over(rgba(getComputedStyle(panel).backgroundColor), rgba(getComputedStyle(page).color));
      page.remove();
      return Object.fromEntries(["success", "info", "warning", "error"].map(kind => {
        const probe = document.createElement("div");
        probe.className = `status-stack-entry save-status ${kind}`;
        probe.innerHTML = '<span class="status-stack-time">12:00</span>';
        panel.appendChild(probe);
        const style = getComputedStyle(probe);
        const background = over(rgba(style.backgroundColor), panelBackground);
        const entry = {
          color: style.color,
          text: Number(contrast(rgba(style.color), background).toFixed(2)),
          time: Number(contrast(rgba(getComputedStyle(probe.firstChild).color), background).toFixed(2)),
        };
        probe.remove();
        return [kind, entry];
      }));
    });
    const detail = `${theme}: ${JSON.stringify(entries)}`;
    // An error or a plain information must not look like a success.
    expect(new Set(Object.values(entries).map(entry => entry.color)).size, detail).toBe(4);
    for (const entry of Object.values(entries)) {
      expect(entry.text, detail).toBeGreaterThanOrEqual(4.5);
      expect(entry.time, detail).toBeGreaterThanOrEqual(4.5);
    }
  }
});

test("system theme matches explicit themes and follows preference changes", async ({ page }) => {
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page);
  const colors = () => page.evaluate(() => ["body", "#inventoryContainer", "#detailEditorPanel"].map(selector => {
    const style = getComputedStyle(document.querySelector(selector));
    return { color: style.color, background: style.backgroundColor, border: style.borderColor };
  }));
  const expected = {};
  for (const theme of ["light", "dark"]) {
    await selectSetting(page, "themeSelect", theme);
    expected[theme] = await colors();
  }
  await selectSetting(page, "themeSelect", "system");
  for (const colorScheme of ["light", "dark", "light"]) {
    await page.emulateMedia({ colorScheme });
    await expect.poll(colors).toEqual(expected[colorScheme]);
    await expect(page.locator("#themeSelect")).toHaveValue("system");
  }
  // A fixed choice ignores later operating-system changes.
  await selectSetting(page, "themeSelect", "dark");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.emulateMedia({ colorScheme: "light" });
  await expect.poll(colors).toEqual(expected.dark);
  await selectSetting(page, "themeSelect", "system");
  await page.reload();
  await expect(page.locator("#themeSelect")).toHaveValue("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("load errors and notifications stay opaque and readable in every theme and layout", async ({ page }) => {
  await openAppWithEmptyWorldScan(page);
  await page.evaluate(() => {
    MCBEWorldStatusView.applyLoadErrorPanel(document.getElementById("loadErrorPanel"),
      MCBEWorldStatusView.loadErrorHtml({ message: "Testfehler", pathText: "/worlds/test" }));
    for (const kind of ["success", "warning", "error"]) MCBEUiFeedback.showToast("Testmeldung", kind, 60000);
  });
  for (const layout of ["classic", "studio", "focus"]) {
    await selectLayout(page, layout);
    for (const [theme, colorScheme] of [["dark", "dark"], ["light", "light"], ["minecraft", "dark"], ["system", "light"]]) {
      await page.emulateMedia({ colorScheme });
      if (!(await page.locator("#themeSelect").isVisible())) await page.locator("#focusSettingsToggle").click();
      await selectSetting(page, "themeSelect", theme);
      const samples = await page.evaluate(() => {
        const panel = document.getElementById("loadErrorPanel");
        const backdrop = document.createElement("span");
        backdrop.style.color = "var(--bg-main)";
        panel.appendChild(backdrop);
        const base = getComputedStyle(backdrop).color;
        backdrop.remove();
        const ancestors = [];
        for (let node = panel.parentElement; node; node = node.parentElement) ancestors.unshift(getComputedStyle(node).backgroundColor);
        return {
          base, ancestors,
          error: getComputedStyle(panel.querySelector(".load-error-title")).color,
          errorBackgrounds: getComputedStyle(panel).backgroundImage.match(/rgba?\([^)]+\)/g),
          logBackground: getComputedStyle(document.getElementById("statusStackPanel")).backgroundColor,
          toasts: [...document.querySelectorAll(".toast")].map(node => ({
            kind: node.className, color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor,
          })),
        };
      });
      const detail = `${layout}/${theme}/${colorScheme}`;
      const parentBackground = samples.ancestors.reduce((background, layer) => compositeColor(layer, background), colorComponents(samples.base));
      for (const layer of samples.errorBackgrounds) {
        expect(contrastRatio(samples.error, compositeColor(layer, parentBackground)), `${detail} load error`).toBeGreaterThanOrEqual(4.5);
      }
      expect(colorComponents(samples.logBackground).a, `${detail} status log opacity`).toBe(1);
      for (const toast of samples.toasts) {
        expect(colorComponents(toast.background).a, `${detail} ${toast.kind} opacity`).toBe(1);
        expect(contrastRatio(toast.color, toast.background), `${detail} ${toast.kind} contrast`).toBeGreaterThanOrEqual(4.5);
      }
    }
  }
});

test("status overview follows the server status shown in the header", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const onlineGate = {
    allowed: false,
    reason: "Server läuft noch. Bitte Server stoppen.",
    server_status: { status: "online" },
  };
  let serverStatus = { success: true, server_status: onlineGate.server_status, write_gate: onlineGate };
  await page.route("**/api/server_status", route => route.fulfill({ json: serverStatus }));
  await page.clock.install();
  await openAppWithEmptyWorldScan(page);

  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  const hero = page.locator("#statusCenterPanel .status-hero");
  const writing = page.locator("#statusCenterPanel .status-tile").filter({ hasText: "Schreiben" });
  await expect(hero).toHaveClass(/\berror\b/);
  await expect(hero).toContainText("Prüfen");
  await expect(writing.locator("strong")).toHaveText("gesperrt");

  // Loading the diagnostics again keeps the server status of the header.
  const diagnostics = page.waitForResponse(response => response.url().endsWith("/api/diagnostics/status"));
  await page.locator("#btnRefreshRuntimeDiagnostics").click();
  await diagnostics;
  await expect(hero).toHaveClass(/\berror\b/);
  await expect(writing.locator("strong")).toHaveText("gesperrt");

  // The next poll after the server stopped clears the overview.
  const offlineGate = { allowed: true, server_status: { status: "offline" } };
  serverStatus = { success: true, server_status: offlineGate.server_status, write_gate: offlineGate };
  await page.clock.fastForward(10_000);
  await expect(writing.locator("strong")).toHaveText("bereit");
  await expect(hero).not.toHaveClass(/\berror\b/);

  // The test server runs in local mode without a server address: its answer
  // is an unknown status, and writing works after confirming it.
  await page.unroute("**/api/server_status");
  await page.clock.fastForward(10_000);
  await expect(writing.locator("strong")).toHaveText("nach Bestätigung");
  await expect(writing).toHaveClass(/\bwarning\b/);
  await expect(hero).not.toHaveClass(/\berror\b/);
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

async function selectSetting(page, id, value) {
  const select = page.locator(`#${id}`);
  if (!(await select.isVisible())) await page.locator("#focusSettingsToggle").click();
  await select.selectOption(value);
  if (await page.locator("#focusSettingsPanel").isVisible()) await page.locator("#focusSettingsToggle").click();
}

async function selectLayout(page, layout) {
  const select = page.locator("#layoutSelect");
  if (!(await select.isVisible())) await page.locator("#focusSettingsToggle").click();
  await select.selectOption(layout);
  await expect(page.locator("html")).toHaveAttribute("data-layout", layout);
  if (await page.locator("#focusSettingsPanel").isVisible()) {
    await page.locator("#focusSettingsToggle").click();
  }
}

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

test("Studio uses one stable inspector track for empty, single and multiple slot selections", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openDragFixture(page);
  await selectSetting(page, "layoutSelect", "studio");

  const measurements = async () => page.evaluate(() => {
    const slot = document.querySelector('.main-inventory-grid [data-slot="9"]');
    const workspace = document.querySelector(".workspace");
    return {
      slotWidth: slot.getBoundingClientRect().width,
      gridWidth: document.querySelector(".main-inventory-grid").getBoundingClientRect().width,
      columns: getComputedStyle(workspace).gridTemplateColumns,
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  });

  await expect(page.locator("#studioInspectorStandby")).toBeVisible();
  await expect(page.locator("#detailEditorPanel")).toBeHidden();
  await expect(page.locator("#dashboardPanel")).toBeHidden();
  await expect(page.locator("#safeEditBanner")).toBeHidden();
  const initial = await measurements();
  expect(initial.slotWidth).toBeGreaterThanOrEqual(44);
  expect(initial.slotWidth).toBeLessThanOrEqual(85);
  expect(initial.overflow).toBeLessThanOrEqual(0);

  await page.locator('.main-inventory-grid [data-slot="9"]').click();
  await expect(page.locator("#detailEditorPanel")).toBeVisible();
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  const single = await measurements();
  expect(single.slotWidth).toBeCloseTo(initial.slotWidth, 1);
  expect(single.gridWidth).toBeCloseTo(initial.gridWidth, 1);
  expect(single.columns).toBe(initial.columns);

  await page.locator('.main-inventory-grid [data-slot="10"]').click({ modifiers: ["Control"] });
  await expect(page.locator("#multiSelectPanel")).toBeVisible();
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  const multiple = await measurements();
  expect(multiple.slotWidth).toBeCloseTo(initial.slotWidth, 1);
  expect(multiple.columns).toBe(initial.columns);

  await page.locator("#btnClearSelection").click();
  await expect(page.locator("#studioInspectorStandby")).toBeVisible();
  await expect(page.locator("#multiSelectPanel")).toBeHidden();
  expect((await measurements()).slotWidth).toBeCloseTo(initial.slotWidth, 1);

  // The new placeholder is exclusively a Studio desktop feature; the real
  // forms and their selected data are shared unchanged across layouts.
  await selectSetting(page, "layoutSelect", "focus");
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  await selectLayout(page, "classic");
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  expect(errors).toEqual([]);
});

for (const width of [390, 1440]) {
test(`inventory review actions stay in the global change workflow (${width}px)`, async ({ page }) => {
  await page.setViewportSize({width, height: 900});
  await openDragFixture(page, {stack_limits: {"minecraft:stone": 64}});
  if (width === 390) await selectSetting(page, 'themeSelect', 'light');
  for (const layout of ['classic', 'studio', 'focus']) {
    await selectLayout(page, layout);
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    const before = await page.locator('#inventoryContainer').evaluate(el => el.getBoundingClientRect().top + scrollY);
    await page.locator('[data-slot="0"]').click();
    if (layout === 'classic' && width <= 1024) await page.locator('.btn-toggle[data-panel="right"]').click();
    await page.locator('#detailCount').fill(layout === 'classic' ? '2' : layout === 'studio' ? '3' : '4');
    await page.locator('#btnApplySingle').click();
    await expect(page.locator('#safeEditBanner')).toBeHidden();
    if (width > 1024) expect(await page.locator('#inventoryContainer').evaluate(el => el.getBoundingClientRect().top + scrollY)).toBeCloseTo(before, 0);
    await page.locator(layout === 'classic' ? '.app-workflow-nav [data-workflow-view="save"]' : '#layoutSaveAction').click();
    await expect(page.locator('#btnReviewDiscardChanges')).toBeVisible();
    await expect(page.locator('#btnReviewDiscardChanges')).toBeEnabled();
    await page.locator('#btnReviewDiscardChanges').click();
    await expect(page.locator('#confirmOverlay')).toBeVisible();
    await page.locator('#confirmCancel').click();
    await expect(page.locator('body')).toHaveClass(/app-dirty/);
  }
  await page.locator('#btnReviewDiscardChanges').click();
  await page.locator('#confirmOk').click();
  await expect(page.locator('body')).not.toHaveClass(/app-dirty/);
  await expect(page.locator('#btnReviewDiscardChanges')).toBeDisabled();
});
}

test("Studio sidebar only scrolls internally when the available height really demands it", async ({ page }) => {
  await openDragFixture(page);
  await selectSetting(page, "layoutSelect", "studio");

  for (const height of [650, 900]) {
    await page.setViewportSize({ width: 1440, height });
    const fit = await page.locator(".layout-controls").evaluate(rail => {
      rail.scrollTop = 100;
      return { extraHeight: rail.scrollHeight - rail.clientHeight, scrollTop: rail.scrollTop };
    });
    expect(fit.extraHeight, `unexpected rail scroll at ${height}px`).toBeLessThanOrEqual(1);
    expect(fit.scrollTop).toBe(0);
  }

  await page.setViewportSize({ width: 1440, height: 390 });
  const compact = await page.locator(".layout-controls").evaluate(rail => {
    const nav = rail.querySelector(".app-workflow-nav");
    const lastLink = nav.querySelector("#btnHelp");
    const saveArea = rail.querySelector(".layout-context-action");
    return {
      needsScroll: rail.scrollHeight > rail.clientHeight,
      linkBottom: lastLink.getBoundingClientRect().bottom,
      saveTop: saveArea.getBoundingClientRect().top,
    };
  });
  expect(compact.needsScroll).toBe(true);
  expect(compact.linkBottom).toBeLessThan(compact.saveTop);
  await page.locator(".layout-controls").evaluate(rail => { rail.scrollTop = rail.scrollHeight; });
  await expect(page.locator("#layoutSaveAction")).toBeInViewport();
});

test("player management dialogs preserve selection and return keyboard focus", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openDragFixture(page);
  await expect(page.locator(".player-manager-tools")).toBeHidden();
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  const selectedName = await page.locator('#playersList .player-row.active .player-name').innerText();
  for (const kind of ["Transfer", "Export", "Import"]) {
    const trigger = page.locator(`[data-player-tool="player${kind}Dialog"]`);
    const overlay = page.locator(`#player${kind}Dialog`);
    await trigger.click();
    await expect(overlay).toBeVisible();
    expect(await page.locator('.app-container').evaluate(el => el.inert)).toBe(true);
    if (kind !== "Transfer") await expect(overlay.locator('[data-player-tool-context]')).toHaveText(selectedName);
    await expect(overlay.locator('[data-close-player-tool]')).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    expect(await overlay.evaluate(el => el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Tab");
    await expect(overlay.locator('[data-close-player-tool]')).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(overlay).toBeHidden();
    await expect(trigger).toBeFocused();
    expect(await page.locator('.app-container').evaluate(el => el.inert)).toBe(false);
  }
  await expect(page.locator('#playersList .player-row.active .player-name')).toHaveText(selectedName);
  expect(errors).toEqual([]);
});

test("dimension conversion help is keyboard accessible and keeps safety guidance visible", async ({ page }) => {
  await openDragFixture(page);
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  const help = page.locator('#conversionHelp');
  await expect(help.locator('.location-conversion-explanation')).toBeHidden();
  await expect(page.locator('.location-conversion-safety')).toBeVisible();
  await expect(page.locator('#btnConvertOverworldNether')).toBeEnabled();
  await expect(page.locator('#locationConversionNote')).toBeHidden();
  await page.locator('#btnConversionHelp').focus();
  const healthTop = await page.locator('#statHealth').evaluate(el => el.getBoundingClientRect().top + scrollY);
  await page.keyboard.press('Enter');
  await expect(help.locator('.location-conversion-explanation')).toBeVisible();
  await expect(help).toContainText('Die Höhe (Y) bleibt unverändert');
  expect(await page.locator('#statHealth').evaluate(el => el.getBoundingClientRect().top + scrollY)).toBeCloseTo(healthTop, 0);
  await page.keyboard.press('Escape');
  await expect(help.locator('.location-conversion-explanation')).toBeHidden();
  await expect(page.locator('#btnConversionHelp')).toBeFocused();
  await page.locator('#btnConversionHelp').click();
  await help.getByRole('button', { name: 'Schließen' }).click();
  await expect(help).toBeHidden();
  await page.locator('#btnConversionHelp').click();
  await page.locator('#statHealth').click();
  await expect(help).toBeHidden();
  await page.locator('#statDimensionId').selectOption('1');
  await expect(page.locator('#btnConvertOverworldNether')).toBeEnabled();
});

test("player view survives resizing across the compact panel breakpoint", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await openDragFixture(page);
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  for (const layout of ["classic", "studio", "focus"]) {
    await page.setViewportSize({ width: 1280, height: 1000 });
    await selectSetting(page, "layoutSelect", layout);
    await page.locator(layout === "classic"
      ? '.app-section-nav button[data-workflow-view="player"]'
      : '.layout-context-chip[data-workflow-view="player"]').click();
    for (const width of [1080, 1025, 1024, 1000, 768, 390, 1280, 1000]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator('#playerManager')).toBeVisible();
    await expect(page.locator('#playersList')).toBeVisible();
    if (layout === "classic") await expect(page.locator('#dashboardPanel')).toBeVisible();
    await expect(page.locator('.panel-toggle')).toBeHidden();
    }
  }
});

test("modal dialogs isolate editor shortcuts and restore focus", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openDragFixture(page);
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  const state = () => page.evaluate(() => ({
    inventory: JSON.stringify(inventory), selection: [...selectedSlots], dirty: isDirty,
    undo: document.getElementById('btnUndo').dataset.historyCount,
  }));
  const before = await state();
  for (const layout of ['classic', 'studio', 'focus']) {
    await selectLayout(page, layout);
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    await page.locator('[data-tab-dash="dashIcons"]').click();
    await page.locator('#btnOpenIconSource').click();
    await page.locator('#btnCloseIconSource').focus();
    for (const key of ['Control+z', 'Control+y', 'Control+s', 'Control+Shift+p', 'Meta+Shift+p']) {
      await page.keyboard.press(key);
      expect(await state()).toEqual(before);
      await expect(page.locator('#dashIcons')).toBeVisible();
      await expect(page.locator('#iconSourceDialog')).toBeVisible();
    }
    await expect(page.locator('#iconSourceDialog')).toBeVisible();
    await expect(page.locator('#saveReviewOverlay')).toBeHidden();
    expect(await state()).toEqual(before);
    await page.keyboard.press('Escape');
    await expect(page.locator('#iconSourceDialog')).toBeHidden();
    await expect(page.locator('#btnOpenIconSource')).toBeFocused();
    expect(await state()).toEqual(before);
    await page.keyboard.press('Control+Shift+p');
    await expect(page.locator('#dashWorkspace')).toBeVisible();
    await page.locator('[data-workflow-view="player"]').first().evaluate(el => el.click());
    for (const dialog of ['playerTransferDialog', 'playerExportDialog', 'playerImportDialog']) {
      const opener = page.locator(`[data-player-tool="${dialog}"]`);
      await opener.click();
      await expect(page.locator(`#${dialog} [data-close-player-tool]`)).toBeFocused();
      const activeTab = await page.locator('.tab-content-dash.active').getAttribute('id');
      for (const key of ['Control+z', 'Control+y', 'Control+s', 'Control+Shift+p', 'Meta+Shift+p']) {
        await page.keyboard.press(key);
        expect(await state()).toEqual(before);
        await expect(page.locator('.tab-content-dash.active')).toHaveAttribute('id', activeTab);
      }
      await expect(page.locator('#saveReviewOverlay')).toBeHidden();
      await page.keyboard.press('Escape');
      await expect(page.locator(`#${dialog}`)).toBeHidden();
      await expect(opener).toBeFocused();
      expect(await state()).toEqual(before);
    }
  }
  expect(errors).toEqual([]);
});

test("catalog conflicts lock effect editing while preserving other editor controls", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const warning = 'Effekte: Kollidierende Einträge im numerischen Katalog. Betroffene IDs: 1, 99. Bearbeitung gesperrt; vorhandene Daten bleiben erhalten.';
  await openDragFixture(page, {
    effects: [{id: 1, amplifier: 0, duration: 200, show_particles: true}],
    effects_db: {}, catalog_warnings: [warning],
    ench_db: {17: {name_de: 'Haltbarkeit', name_en: 'Unbreaking', max_lvl: 3}},
  });
  await expect(page.locator('#statusStackButton')).toContainText('Betroffene IDs: 1, 99');
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('[data-tab-dash="dashEffects"]').click();
  await expect(page.locator('#btnOpenEffectPicker')).toBeDisabled();
  await expect(page.locator('#effectsContainer .effect-row')).toHaveCount(1);
  await expect(page.locator('#effectsContainer .eff-level')).toBeDisabled();
  await expect(page.locator('#effectsContainer .eff-duration')).toBeDisabled();
  await page.locator('[data-tab-dash="dashStats"]').click();
  await expect(page.locator('#statHealth')).toBeEnabled();
  expect(errors).toEqual([]);
});

test("main workflows retain their content across responsive breakpoints", async ({ page }) => {
  await openDragFixture(page);
  for (const layout of ['classic', 'studio', 'focus']) {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await selectSetting(page, 'layoutSelect', layout);
    for (const [view, content] of [['world', '#worldPicker'], ['player', '#playerManager'], ['inventory', '#inventoryContainer'], ['save', '#saveWorkflowPanel'], ['tools', '#dashboardPanel'], ['mounts', '#mountsPanel']]) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      // Use the existing navigation handler even when a layout places the action in its footer.
      await page.locator(`[data-workflow-view="${view}"]`).first().evaluate(el => el.click());
      for (const width of [1440, 1181, 1180, 1025, 1024, 1000, 761, 760, 390, 1025, 1440]) {
        await page.setViewportSize({ width, height: 1000 });
        await expect(page.locator(content), `${layout}/${view}/${width}`).toBeVisible();
      }
    }
  }
});

test("compact inventory preserves the chosen editor panel through resizes and navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await openDragFixture(page);
  await page.locator('.btn-toggle[data-panel="right"]').click();
  await expect(page.locator('.right-panel')).toBeVisible();
  for (const width of [1025, 1024, 390, 1000]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator('.right-panel')).toBeVisible();
  }
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('.app-section-nav button[data-workflow-view="inventory"]').click();
  await expect(page.locator('#inventoryContainer')).toBeVisible();
});

for (const width of [390, 1024, 1440]) {
  test(`design transitions preserve pending edits and the active editor (${width}px)`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await page.setViewportSize({ width, height: 900 });
    await openDragFixture(page, { stack_limits: { "minecraft:stone": 64, __default__: 64 } });
    if (width === 1024) await selectSetting(page, 'themeSelect', 'light');
    await selectLayout(page, 'studio');
    await page.locator('[data-slot="0"]').click();
    await page.locator('#detailCount').fill('12');
    await page.locator('#btnApplySingle').click();
    await expect(page.locator('body')).toHaveClass(/app-dirty/);
    await page.locator('#detailCustomName').fill('Unapplied slot draft');
    await page.locator('#detailLore').fill('Draft line one\nDraft line two');
    const unexpectedRequests = [];
    page.on('request', request => {
      if (/\/api\/(player\/(load|save)|world\/load|workspace\/save)(?:\?|$)/.test(request.url())) unexpectedRequests.push(request.url());
    });
    const initial = await page.evaluate(() => ({
      inventory: JSON.stringify(inventory), player: currentPlayerKey, world: worldPath,
    }));
    const transitions = ['focus', 'classic', 'studio', 'classic', 'focus', 'studio'];
    for (const layout of transitions) {
      await selectLayout(page, layout);
      await expect(page.locator('#detailEditorPanel')).toBeVisible();
      await expect(page.locator('#detailCustomName')).toHaveValue('Unapplied slot draft');
      await expect(page.locator('#detailLore')).toHaveValue('Draft line one\nDraft line two');
      await expect(page.locator('#detailSlotNum')).toHaveText('0');
      expect(await page.evaluate(() => ({
        inventory: JSON.stringify(inventory), player: currentPlayerKey, world: worldPath,
      }))).toEqual(initial);
      await expect(page.locator('body')).toHaveClass(/app-dirty/);
    }
    await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
    await page.locator('#statHealth').fill('13');
    await page.locator('[data-tab-dash="dashEffects"]').click();
    await page.locator('#abMovementSpeed').fill('0.17');
    for (const layout of transitions) {
      await selectLayout(page, layout);
      await expect(page.locator('#dashboardPanel')).toBeVisible();
      await expect(page.locator('#dashEffects')).toBeVisible();
      await expect(page.locator('#abMovementSpeed')).toHaveValue('0.17');
      await expect(page.locator('#statHealth')).toHaveValue('13');
      await expect(page.locator('body')).toHaveClass(/app-dirty/);
      expect(await page.evaluate(() => ({
        inventory: JSON.stringify(inventory), player: currentPlayerKey, world: worldPath,
      }))).toEqual(initial);
    }
    expect(unexpectedRequests).toEqual([]);
    expect(errors).toEqual([]);
  });
}

for (const layout of ['classic', 'studio', 'focus']) {
  test(`conversion can be reverted before applying and globally undone after applying (${layout})`, async ({ page }) => {
    await openDragFixture(page, { stats: { pos: [94.41, 71.62, 93.52], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 } });
    await selectLayout(page, layout);
    await page.locator(`.app-workflow-nav [data-workflow-view="${layout === 'classic' ? 'player' : 'player-edit'}"]`).click();
    const convert = page.locator('#btnConvertOverworldNether');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('11.80125');
    await expect(convert).toHaveText('Umrechnung zurücknehmen');
    await expect(page.locator('#btnUndo')).toBeDisabled();
    await page.locator('#statPosY').fill('75');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('94.41');
    await expect(page.locator('#statPosZ')).toHaveValue('93.52');
    await expect(page.locator('#statPosY')).toHaveValue('75');
    await expect(page.locator('#statDimensionId')).toHaveValue('0');
    await convert.click();
    await page.locator('#btnApplyStats').click();
    await expect(convert).toHaveText('Zur Oberwelt umrechnen (X/Z × 8)');
    await page.locator('#btnUndo').click();
    await expect(page.locator('#statDimensionId')).toHaveValue('0');
    await expect(page.locator('#statPosX')).toHaveValue('94.41');
    await page.locator('#btnRedo').click();
    await expect(page.locator('#statDimensionId')).toHaveValue('1');
    await expect(page.locator('#statPosX')).toHaveValue('11.80');
    expect(await page.evaluate(() => playerStats.pos[0])).toBe(11.80125);
    await page.locator('#statDimensionId').selectOption('0');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('94.41');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('11.80');
  });
}

test('effect cards use one to three columns based on available width in every design', async ({ page }) => {
  await openDragFixture(page, {
    effects: [1, 2, 3, 4].map(id => ({ id, amplifier: 0, duration: 600, show_particles: true })),
    effects_db: {1: ['Tempo', 'Speed'], 2: ['Langsamkeit', 'Slowness'], 3: ['Eile', 'Haste'], 4: ['Abbaulähmung', 'Mining Fatigue']},
  });
  for (const layout of ['classic', 'studio', 'focus']) {
    await selectLayout(page, layout);
    await page.locator(`.app-workflow-nav [data-workflow-view="${layout === 'classic' ? 'player' : 'player-edit'}"]`).click();
    await page.locator('[data-tab-dash="dashEffects"]').click();
    for (const theme of ['dark', 'light']) {
      await selectSetting(page, 'themeSelect', theme);
      for (const width of [390, 1024, 1830, 2560]) {
        await page.setViewportSize({width, height: 1000});
        const grid = page.locator('#effectsContainer');
        await expect(grid).toBeVisible();
        const geometry = await grid.evaluate(el => {
          const style = getComputedStyle(el);
          return { columns: style.gridTemplateColumns.split(' ').length, width: el.clientWidth,
            overflow: document.documentElement.scrollWidth - innerWidth };
        });
        const min = 23 * await page.locator('html').evaluate(el => parseFloat(getComputedStyle(el).fontSize));
        const expected = Math.min(3, Math.max(1, Math.floor((geometry.width + 12) / (min + 12))));
        expect(geometry.columns, `${layout}/${theme}/${width}`).toBe(expected);
        expect(geometry.overflow).toBeLessThanOrEqual(1);
      }
    }
  }
});

test('Focus header status labels share a font size at desktop and mobile widths', async ({ page }) => {
  await openDragFixture(page);
  await selectLayout(page, 'focus');
  for (const width of [390, 1440]) {
    await page.setViewportSize({width, height: 900});
    const fonts = await page.evaluate(() => {
      const status = getComputedStyle(document.getElementById('serverStatusBadge'), '::after');
      const messages = getComputedStyle(document.getElementById('statusStackButton'), '::after');
      return {status: status.fontSize, messages: messages.fontSize, statusWeight: status.fontWeight, messageWeight: messages.fontWeight};
    });
    expect(fonts.status).toBe(fonts.messages);
    console.log(`Focus header ${width}px: ${JSON.stringify(fonts)}`);
  }
});

for (const layout of ['classic', 'studio', 'focus']) for (const theme of ['dark', 'light']) for (const language of ['de', 'en']) {
  test(`database result summary (${layout}/${theme}/${language})`, async ({page}) => {
    test.setTimeout(60_000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.context().addCookies([{name: 'mcbe_locale', value: language, url: NORMAL_BASE_URL}]);
    await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: {
      status: 'ok', verification: {verified: true}, source_version_present: true,
      source_version: {resource_pack_release: 'v1.26.40.05'}, counts: {items: 2048, effects: 37, enchantments: 42},
    }}}));
    let state = 'available';
    let issues = [];
    await page.route('**/api/update_db', route => route.fulfill({json: {
      success: state !== 'incomplete', returncode: state === 'incomplete' ? 1 : 0,
      error: state === 'incomplete' ? 'Synthetic source failure' : undefined,
      output: 'Synthetic detailed log', update_review_token: 'a'.repeat(64), resource_pack_release: 'v1.26.50.4',
      summary: {schema: 1, status: state, scope: 'all', release: 'v1.26.50.4', blocked: [],
        sections: {items: {added: state === 'available' ? 124 : 0, removed: 0, changed: 0}},
        audit: {checked_items: 2164, issues, expected_name_differences: [
          ['bed', 'Weißes Bett', 'White Bed', 'Bett', 'Bed'],
          ['yellow_flower', 'Löwenzahn', 'Dandelion', 'Blume', 'Flower'],
          ['stonecutter', 'Steinsäge (alt, ohne Funktion)', 'Stonecutter (Legacy, No Function)', 'Steinsäge', 'Stonecutter'],
        ].flatMap(([id, de, en, sourceDe, sourceEn]) => [
          {id: `minecraft:${id}`, locale: 'de', catalog: de, source: sourceDe},
          {id: `minecraft:${id}`, locale: 'en', catalog: en, source: sourceEn},
        ])}},
    }}));
    await openAppWithEmptyWorldScan(page);
    await selectLayout(page, layout);
    await selectSetting(page, 'themeSelect', theme);
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    await page.locator('[data-tab-dash="dashUpdate"]').click();
    await expect(page.locator('.item-db-version-line')).toContainText('Mojang v1.26.40.05');
    await expect(page.locator('.item-db-status-hero')).not.toContainText(language === 'en' ? 'checked' : 'geprüft');
    const result = page.locator('#updateDbResult');
    for (const width of [390, 1440]) {
      await page.setViewportSize({width, height: 1000});
      await page.locator('#btnUpdateDbDryRun').click();
      await expect(result).toContainText(language === 'en' ? 'Update to Mojang v1.26.50.4 available' : 'Update auf Mojang v1.26.50.4 verfügbar');
      await expect(result).toContainText(language === 'en' ? '124 added' : '124 ergänzt');
      await expect(result).toContainText(language === 'en' ? 'No issues found' : 'Keine Auffälligkeiten');
      await expect(result).not.toContainText(language === 'en' ? 'Expected name differences' : 'Erwartete Namensabweichungen');
      await expect(page.locator('#updateDbOutput')).toBeHidden();
      await page.locator('#updateDbDetails summary').click();
      await expect(page.locator('#updateDbAudit')).toContainText(language === 'en' ? 'Expected name differences (3)' : 'Erwartete Namensabweichungen (3)');
      await expect(page.locator('#updateDbAudit')).toContainText('DE · minecraft:bed');
      await expect(page.locator('#updateDbAudit')).toContainText('EN · minecraft:bed');
      await expect(page.locator('#updateDbOutput')).toBeVisible();
      await page.locator('#updateDbDetails summary').click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      await capturePlayerLoadEvidence(page, `db-result-${layout}-${theme}-${language}-${width}`);
    }
    state = 'current';
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'No content changes' : 'Keine inhaltlichen Änderungen');
    await expect(result).not.toContainText('124');
    state = 'metadata_only';
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'Only source metadata changed' : 'Nur Quelleninformationen geändert');
    state = 'available';
    issues = [{code: 'name_differences_de', severity: 'info', count: 1, items: ['<img src=x onerror=alert(1)>']}];
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'Differing German names: 1' : 'Abweichende deutsche Namen: 1');
    await page.locator('#updateDbDetails summary').click();
    await expect(page.locator('#updateDbAudit')).toContainText('<img src=x');
    await expect(page.locator('#updateDbAudit img')).toHaveCount(0);
    state = 'incomplete';
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'Check incomplete or failed' : 'Prüfung unvollständig oder fehlgeschlagen');
    await expect(result).toContainText('Synthetic source failure');
    await expect(page.locator('#updateDbOutput')).toBeHidden();
    await page.locator('#btnClearUpdateOutput').click();
    await expect(page.locator('.update-db-output-wrapper')).toBeHidden();
    await expect(page.locator('#btnUpdateDbDryRun')).toBeFocused();
    expect(errors).toEqual([]);
  });
}

test("icon setup and missing-source previews remain usable on narrow screens", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = collectBrowserErrors(page);
  const iconData = { success: true, count: 0, icons: {}, warnings: [], sources: [{
    label: "Vanilla Icons aus Mojang/bedrock-samples", path: "", enabled: true, exists: false, count: 0,
  }], health: { enabled_sources: 1, existing_sources: 0, sample_found: 0, sample_total: 8,
    sample: ["diamond_sword", "apple", "stone", "bow", "carrot", "chest", "firework_rocket", "banner"]
      .map(id => ({ item_id: `minecraft:${id}`, found: false })),
  } };
  await page.route("**/api/icons/status*", route => route.fulfill({ json: iconData }));
  await page.route("**/api/icons/scan", route => route.fulfill({ json: iconData }));
  for (const locale of ["de", "en"]) {
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openAppWithEmptyWorldScan(page);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await selectSetting(page, "themeSelect", "light");
    for (const layout of ["classic", "studio", "focus"]) {
      await selectLayout(page, layout);
      await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
      await page.locator('[data-tab-dash="dashIcons"]').click();
      const panel = page.locator("#dashIcons");
      for (const width of [1440, 390, 320]) {
        await page.setViewportSize({ width, height: 900 });
        await expect(page.locator("#btnFocusIconSource")).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        expect(await panel.evaluate(el => el.scrollWidth - el.clientWidth), `${locale}/${layout}/${width}`).toBeLessThanOrEqual(1);
        if (process.env.MCBE_BROWSER_EVIDENCE_DIR) await panel.screenshot({
          path: `${process.env.MCBE_BROWSER_EVIDENCE_DIR}/icon-setup-${locale}-${layout}-${width}.png`,
          animations: "disabled",
        });
        await page.locator("#btnFocusIconSource").click();
        await expect(page.locator("#iconSourceDialog")).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(page.locator("#iconSourceDialog")).toBeHidden();
      }
    }
  }
  expect(errors).toEqual([]);
});

for (const layout of ['classic', 'studio', 'focus']) for (const theme of ['dark', 'light']) {
  test(`compact asset tools keep actions and diagnostics accessible (${layout}/${theme})`, async ({page}) => {
    test.setTimeout(60_000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const itemDb = {status: 'ok', verification: {verified: true}, source_version_present: true,
      source_version: {resource_pack_release: 'v1.26.40.05'}, counts: {items: 2164, effects: 37, enchantments: 42},
      schema_version: 3, history_count: 2, path: 'synthetic/item_db.json'};
    const iconData = {success: true, count: 1868, icons: {}, warnings: [], scanned_files: 1675,
      sources: [{label: 'Vanilla', path: 'synthetic/vanilla', enabled: true, exists: true, count: 1868}],
      health: {status: 'ok', enabled_sources: 1, existing_sources: 1, sample_found: 4, sample_total: 4,
        sample: ['diamond_sword', 'apple', 'stone', 'bow'].map(id => ({item_id: `minecraft:${id}`, found: true}))},
      cache: {state: 'hit', path: 'synthetic/cache.json'}, settings_path: 'synthetic/icon_sources.json'};
    await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: itemDb}}));
    await page.route('**/api/item-db/versions', route => route.fulfill({json: {success: true, entries: [{resource_pack_release: 'v1.26.40.05'}]}}));
    await page.route('**/api/icons/status*', route => route.fulfill({json: iconData}));
    await page.route('**/api/icons/scan', route => route.fulfill({json: iconData}));
    let updateRequest;
    await page.route('**/api/update_db', route => {
      updateRequest = route.request().postDataJSON();
      return route.fulfill({json: updateRequest.dry_run
        ? {success: true, output: 'Synthetic preview completed', update_review_token: 'synthetic-review', resource_pack_release: 'v1.26.40.05'}
        : {success: false, error: 'Synthetic update failure', returncode: 1}});
    });
    await page.route('**/api/icons/sources/add', route => route.fulfill({json:
      route.request().postDataJSON().path === 'bad' ? {success: false, error: 'Synthetic invalid source'} : iconData}));
    await page.route('**/api/icons/pick_pack', route => route.fulfill({json: {success: true, path: 'synthetic/pack.mcpack'}}));
    await page.route('**/api/icons/pick_folder', route => route.fulfill({json: {success: false, error: 'Synthetic picker unavailable'}}));
    await openAppWithEmptyWorldScan(page);
    await selectLayout(page, layout);
    await selectSetting(page, 'themeSelect', theme);
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    for (const width of [390, 1440]) {
      await page.setViewportSize({width, height: 1000});
      for (const tab of ['dashUpdate', 'dashIcons']) {
        await page.locator(`[data-tab-dash="${tab}"]`).click();
        await expect(page.locator(`#${tab}`)).toBeVisible();
        await captureBrowserEvidence(page, `compact-tools-${layout}-${theme}-${width}-${tab}`);
        const overflow = await page.evaluate(() => ({width: document.documentElement.scrollWidth - innerWidth,
          elements: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1 && el.getBoundingClientRect().width > 0).slice(-12).map(el => [el.id, el.className, el.getBoundingClientRect().width])}));
        expect(overflow.width, JSON.stringify(overflow.elements)).toBeLessThanOrEqual(1);
      }
      await expect(page.locator('#assetDataStatusPanel')).toBeHidden();
      await expect(page.locator('#iconManagerPanel .tool-status-line')).toContainText('1.868');
      await expect(page.locator('#iconManagerPanel .tool-facts')).toBeHidden();
      await page.locator('#btnOpenIconSource').click();
      await expect(page.locator('#iconSourceDialog')).toBeVisible();
      await page.locator('#iconSourceDialog summary').click();
      await expect(page.locator('#iconSourcePath')).toBeVisible();
      expect(await page.locator('#iconSourceDialog').evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
      await captureBrowserEvidence(page, `compact-tools-${layout}-${theme}-${width}-source-dialog`);
      await page.keyboard.press('Escape');
      await expect(page.locator('#iconSourceDialog')).toBeHidden();
      await expect(page.locator('#btnOpenIconSource')).toBeFocused();
      // Reset the native disclosure for the next viewport.
      await page.locator('#iconSourceDialog details').evaluate(el => { el.open = false; });
    }
    await page.locator('#iconManagerPanel summary').click();
    await expect(page.locator('#btnCopyIconDiagnostics')).toBeVisible();
    await page.locator('#btnRescanIcons').click();
    await expect(page.locator('#iconManagerPanel .tool-facts')).toBeVisible();
    await page.locator('#btnOpenIconSource').click();
    await page.locator('#btnPickIconFolder').click();
    await expect(page.locator('#iconSourceFeedback')).toHaveText('Synthetic picker unavailable');
    await page.locator('#iconSourceDialog summary').click();
    await page.locator('#iconSourcePath').fill('bad');
    await page.locator('#btnAddIconSource').click();
    await expect(page.locator('#iconSourceFeedback')).toHaveText('Synthetic invalid source');
    await expect(page.locator('#iconSourcePath')).toHaveValue('bad');
    await page.locator('#btnPickIconPack').click();
    await expect(page.locator('#iconSourceDialog')).toBeHidden();
    await page.locator('[data-tab-dash="dashUpdate"]').click();
    await expect(page.locator('.update-db-output-wrapper')).toBeHidden();
    await page.locator('[data-db-details] summary').click();
    await page.locator('[data-toggle-db-versions]').click();
    await expect(page.locator('.item-db-version-history')).toContainText('v1.26.40.05');
    await expect(page.locator('[data-db-details]')).toHaveAttribute('open', '');
    await page.locator('.update-db-options summary').click();
    await page.locator('#updateOnlySelect').selectOption('items');
    await page.locator('.update-db-options summary').click();
    await expect(page.locator('#updateScopeSummary')).toHaveText('Nur Items');
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(page.locator('#updateDbOutput')).toContainText('Synthetic preview completed');
    expect(updateRequest.only).toBe('items');
    expect(updateRequest.dry_run).toBe(true);
    await page.locator('#btnUpdateDbApply').click();
    await expect(page.locator('#confirmOverlay')).toBeVisible();
    await page.locator('#confirmCancel').click();
    await page.locator('#btnUpdateDbApply').click();
    await page.locator('#confirmOk').click();
    await expect(page.locator('#updateDbOutput')).toContainText('Synthetic update failure');
    expect(updateRequest.expected_update_review_token).toBe('synthetic-review');
    expect(updateRequest.only).toBe('items');
    await page.locator('#btnClearUpdateOutput').click();
    await expect(page.locator('.update-db-output-wrapper')).toBeHidden();
    await expect(page.locator('#btnUpdateDbDryRun')).toBeFocused();
    expect(errors).toEqual([]);
  });
}

for (const layout of ['classic', 'studio', 'focus']) {
  for (const theme of ['dark', 'light']) {
    test(`many-player search and bounded scrolling (${layout}/${theme})`, async ({ page }, testInfo) => {
      test.setTimeout(60_000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/world/presence', route => route.fulfill({json: {success: true, other_sessions: []}}));
      const players = Array.from({length: 150}, (_, i) => ({
        player_key: i === 0 ? 'drag-player' : `synthetic-key-${i}`,
        label: i === 0 ? 'Drag Test' : i === 80 ? 'VeryLongSyntheticPlayerName'.repeat(4) : `Testspieler ${i}`,
        kind: i === 0 ? 'local' : 'remote', editable: i !== 80, exportable: true,
        has_inventory_tag: true, has_ender_chest_tag: true,
      }));
      await openDragFixture(page, request => ({player: players.find(p => p.player_key === request.player_key)}), players);
      await selectLayout(page, layout);
      await selectSetting(page, 'themeSelect', theme);
      const list = page.locator('#playersList');
      const rows = list.locator('.player-row');
      const search = page.locator('#playerManagerSearch');
      async function openManager(currentLayout = layout) {
        await page.locator(currentLayout === 'classic'
          ? '.app-workflow-nav [data-workflow-view="player"]'
          : '.layout-context-chip[data-workflow-view="player"]').click();
        await expect(search).toBeVisible();
      }
      async function checkList(width, rail = false) {
        await expect(rows).toHaveCount(150);
        await list.scrollIntoViewIfNeeded();
        const bounds = await list.evaluate(el => ({
          height: el.clientHeight, content: el.scrollHeight, overflow: getComputedStyle(el).overflowY,
          horizontalOverflow: el.scrollWidth - el.clientWidth,
          pageOverflow: document.documentElement.scrollWidth - innerWidth,
          minRow: Math.min(...Array.from(el.children, row => row.getBoundingClientRect().height)),
        }));
        expect(bounds.height).toBeGreaterThan(100);
        expect(bounds.height).toBeLessThanOrEqual(Math.min(rail ? 650 : 420, (rail ? .58 : .52) * page.viewportSize().height) + 1);
        expect(bounds.content).toBeGreaterThan(bounds.height * 5);
        expect(bounds.overflow).toBe('auto');
        expect(bounds.minRow).toBeGreaterThanOrEqual(44);
        expect(bounds.horizontalOverflow).toBeLessThanOrEqual(1);
        expect(bounds.pageOverflow).toBeLessThanOrEqual(1);
        await list.evaluate(el => { el.scrollTop = el.scrollHeight; });
        const lastReachable = await rows.last().evaluate(el => {
          const row = el.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect();
          return row.top >= parent.top - 1 && row.bottom <= parent.bottom + 1;
        });
        expect(lastReachable).toBe(true);
        await list.evaluate(el => { el.scrollTop = 0; });
        await testInfo.attach(`${layout}-${theme}-${width}${rail ? '-rail' : ''}`, {
          body: await page.screenshot(), contentType: 'image/png',
        });
        await captureBrowserEvidence(page, `players-${layout}-${theme}-${width}-${await page.locator('body').getAttribute('data-workflow-view')}${rail ? '-rail' : ''}`);
      }
      for (const width of [390, 1024, 1830]) {
        await page.setViewportSize({width, height: width === 390 ? 844 : 1000});
        await openManager();
        await search.fill('');
        await checkList(width);
        await search.fill('TESTSPIELER 149');
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(page.locator('#playerManagerCount')).toHaveText('1 / 150');
        await search.fill('synthetic-KEY-80');
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(list.locator('.player-row:visible .player-name')).toHaveText(players[80].label);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        await search.fill('no matching synthetic player');
        await expect(list.locator('.player-row:visible')).toHaveCount(0);
        await expect(page.locator('#playerManagerSearchEmpty')).toBeVisible();
        await search.fill('');
        await expect(page.locator('#playerManagerSearchEmpty')).toBeHidden();
        await expect(list.locator('.player-row:visible')).toHaveCount(150);
        // Refresh recreates the rows; the query must still filter the new DOM.
        await search.fill('Testspieler 149');
        await page.locator('#btnRefreshPlayers').click();
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(list.locator('.player-row:visible')).toContainText('Testspieler 149');
        await list.locator('.player-row:visible').click();
        await expect.poll(() => page.evaluate(() => currentPlayerKey)).toBe('synthetic-key-149');
        await openManager();
        await search.fill('');
        await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
        if (layout === 'focus' && width > 760) {
          await checkList(width, true);
          await page.locator('#focusPlayerSearch').fill('Testspieler 149');
          await expect(list.locator('.player-row:visible')).toHaveCount(1);
          await openManager();
          await expect(search).toHaveValue('Testspieler 149');
          await search.fill('');
        } else if (layout === 'classic') {
          if (width <= 1024) await page.locator('.btn-toggle[data-panel="right"]').click();
          await expect(search).toBeVisible();
          await checkList(width);
        }
      }
      await openManager();
      await search.fill('Testspieler 149');
      for (const nextLayout of ['classic', 'studio', 'focus']) {
        await selectLayout(page, nextLayout);
        await openManager(nextLayout);
        await expect(search).toHaveValue('Testspieler 149');
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(page.locator('#playerManagerCount')).toHaveText('1 / 150');
      }
      await list.locator('.player-row:visible').click();
      await expect.poll(() => page.evaluate(() => currentPlayerKey)).toBe('synthetic-key-149');
      expect(errors).toEqual([]);
    });
  }
}
