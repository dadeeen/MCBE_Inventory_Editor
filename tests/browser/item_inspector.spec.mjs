import { expect, test } from "@playwright/test";
import path from "node:path";

const WORLD_PATH = "tests/fixtures/worlds/SmokeWorld";
const PLAYER_KEY = "inspector-player";
const scalar = (type, value) => ({ type: `${type}Tag`, value });
const compound = value => scalar("Compound", value);

function inspectedItem(overrides = {}) {
  return {
    slot: 0, name: "minecraft:diamond_pickaxe", count: 1, damage: 237,
    display_name: "Bergwerk", lore: ["Synthetisches Beispiel"],
    enchantments: [{ id: 15, lvl: 3 }], source_item_digest: "a".repeat(64),
    source_slot: 0, source_player_key: PLAYER_KEY, source_container: "inventory", source_world_path: WORLD_PATH,
    nbt_view: compound({
      Name: scalar("String", "minecraft:diamond_pickaxe"),
      Count: scalar("Byte", 1), Damage: scalar("Short", 0),
      tag: compound({
        Damage: scalar("Int", 237),
        display: compound({ Name: scalar("String", "Bergwerk"), Lore: scalar("List", [scalar("String", "Synthetisches Beispiel")]) }),
        UniqueID: scalar("Long", "9223372036854775807"),
        "key.with[brackets]": scalar("String", "<img src=x onerror=window.__nbtInjected=true>"),
        EmptyText: scalar("String", ""),
        EmptyList: { ...scalar("List", []), list_type_id: 10 },
      }),
    }),
    ...overrides,
  };
}

async function openInspectorFixture(page, overrides = {}, baseURL = "http://127.0.0.1:8765", locale = "de") {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: baseURL }]);
  await page.addInitScript(() => {
    localStorage.setItem("mcbe-inventory-editor:storageSchema", "v3-dark-session-history");
    localStorage.setItem("mcbe-inventory-editor:workspace", JSON.stringify({ first_run_setup_dismissed: true }));
    window.__copiedInspectorText = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async text => { window.__copiedInspectorText.push(text); } },
    });
  });
  const player = { player_key: PLAYER_KEY, label: "Synthetic Inspector Player", editable: true, exportable: true,
    has_inventory_tag: true, has_ender_chest_tag: true };
  for (const [url, response] of Object.entries({
    "**/api/scan_worlds": { success: true, worlds: [{ path: WORLD_PATH, name: "Synthetic Inspector World", folder: "SmokeWorld", source_kind: "configured-root" }] },
    "**/api/players": { success: true, world_name: "Synthetic Inspector World", players: [player] },
    "**/api/server_status": { success: true, status: "offline", write_gate: { allowed: true, read_allowed: true } },
    "**/api/item-db/status": { item_db: { status: "ok", verification: { verified: true }, counts: { items: 3 } } },
    "**/api/icons/status*": { success: true, icons: {}, banner_patterns: {}, count: 0, sources: [], warnings: [] },
    "**/api/icons/scan": { success: true, icons: {}, count: 0 },
    "**/api/world/presence": { success: true, other_sessions: [] },
    "**/api/heartbeat": { success: true, other_sessions: [] },
  })) await page.route(url, route => route.fulfill({ json: response }));
  await page.route("**/api/player/load", route => route.fulfill({ json: {
    success: true, player, player_revision: "inspector-revision", inventory: { 0: inspectedItem() },
    ender_chest: {}, has_ender_chest: true,
    stats: { pos: [0, 64, 0], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 },
    protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true },
    hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
    items_db: { "minecraft:diamond_pickaxe": ["Diamantspitzhacke", "Diamond Pickaxe"], "minecraft:stone": ["Stein", "Stone"] },
    ench_db: { 15: { name_de: "Effizienz", name_en: "Efficiency", max_lvl: 5 } },
    stack_limits: { __default__: 64, "minecraft:diamond_pickaxe": 1 },
    max_damage: { __default__: 0, "minecraft:diamond_pickaxe": 1561 },
    ...overrides,
  } }));
  await page.goto(`${baseURL}/`);
  await page.locator(".world-card").click();
  await page.locator("#btnLoad").click();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  return errors;
}

async function openInspector(page, slot = 0) {
  await page.locator(`.inventory-slot[data-slot="${slot}"]`).click();
  if (!(await page.locator("#btnInspectSlotNbt").isVisible())) await page.locator('.btn-toggle[data-panel="right"]').click();
  await page.locator("#btnInspectSlotNbt").click();
  const dialog = page.locator("#slotInspectorPanel");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveJSProperty("open", true);
  return dialog;
}

const tab = (dialog, name) => dialog.locator(`[data-inspector-tab="${name}"]`);
const node = (dialog, nodePath) => dialog.locator(`[role="treeitem"][data-path=${JSON.stringify(nodePath)}]`);

async function selectSetting(page, id, value) {
  const select = page.locator(`#${id}`);
  if (!(await select.isVisible())) await page.locator("#focusSettingsToggle").click();
  await select.selectOption(value);
  if (await page.locator("#focusSettingsPanel").isVisible()) await page.locator("#focusSettingsToggle").click();
}

test("item inspector is a read-only modal with keyboard navigation and safe typed copying", async ({ page }) => {
  const errors = await openInspectorFixture(page);
  const before = await page.evaluate(() => ({ inventory: JSON.stringify(inventory), dirty: isDirty }));
  const dialog = await openInspector(page);
  await expect(tab(dialog, "overview")).toHaveAttribute("aria-selected", "true");
  await expect(dialog).toContainText("Bergwerk");
  await expect(dialog).toContainText("minecraft:diamond_pickaxe");
  await expect(dialog).toContainText("237");

  await tab(dialog, "overview").focus();
  await page.keyboard.press("ArrowRight");
  await expect(tab(dialog, "tree")).toBeFocused();
  await expect(tab(dialog, "tree")).toHaveAttribute("aria-selected", "true");
  const root = dialog.getByRole("treeitem").first();
  await root.focus();
  await page.keyboard.press("Home");
  await expect(root).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(root).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("ArrowRight");
  await expect(root).not.toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(root).toBeFocused();

  await dialog.locator("#itemInspectorSearch").fill("9223372036854775807");
  await expect(dialog.locator("#itemInspectorSearchStatus")).toContainText("1");
  const longNode = node(dialog, "$.tag.UniqueID");
  await expect(longNode).toBeVisible();
  await longNode.click();
  await expect(longNode).toContainText("Long");
  await dialog.locator("#itemInspectorCopyPath").click();
  await dialog.locator("#itemInspectorCopyValue").click();
  await tab(dialog, "json").click();
  await dialog.locator("#itemInspectorCopyJson").click();
  await expect(dialog.locator("#itemInspectorCopyStatus")).toHaveAttribute("role", "status");
  await expect(dialog.locator("#itemInspectorCopyStatus")).toHaveText("NBT-JSON kopiert.");
  await expect(dialog.locator("#itemInspectorCopyStatus")).toBeVisible();
  const copied = await page.evaluate(() => window.__copiedInspectorText);
  expect(copied[0]).toBe("$.tag.UniqueID");
  expect(copied[1]).toContain("9223372036854775807");
  expect(JSON.parse(copied[2])).toEqual(inspectedItem().nbt_view);
  for (const text of copied) {
    expect(text).not.toContain(WORLD_PATH);
    expect(text).not.toContain("Synthetic Inspector Player");
  }
  await tab(dialog, "tree").click();
  await dialog.locator("#itemInspectorSearch").fill("EmptyText");
  await node(dialog, "$.tag.EmptyText").click();
  await dialog.locator("#itemInspectorCopyValue").click();
  expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe("");
  await expect(dialog.locator("#itemInspectorCopyStatus")).toHaveText("NBT-Wert kopiert.");
  await dialog.locator("#itemInspectorSearch").fill("EmptyList");
  await node(dialog, "$.tag.EmptyList").click();
  await expect(dialog.locator("#itemInspectorExplanation")).toContainText("NBT-ID): 10");
  await dialog.locator("#itemInspectorCopyValue").click();
  expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe("[]");
  expect(await dialog.locator("img[src=x]").count()).toBe(0);
  expect(await page.evaluate(() => window.__nbtInjected)).toBeUndefined();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.locator("#btnInspectSlotNbt")).toBeFocused();
  expect(await page.evaluate(() => ({ inventory: JSON.stringify(inventory), dirty: isDirty }))).toEqual(before);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(errors).toEqual([]);
});

test("item inspector search reveals ancestors and preserves unambiguous paths", async ({ page }) => {
  await openInspectorFixture(page);
  const dialog = await openInspector(page);
  await tab(dialog, "tree").click();
  await dialog.locator("#itemInspectorCollapse").click();
  const search = dialog.locator("#itemInspectorSearch");
  await search.fill("Damage");
  await expect(dialog.locator("#itemInspectorSearchStatus")).toContainText("2");
  await dialog.locator("#itemInspectorNext").click();
  await expect(node(dialog, "$.tag.Damage")).toBeVisible();
  await dialog.locator("#itemInspectorCopyPath").click();
  await dialog.locator("#itemInspectorPrevious").click();
  await dialog.locator("#itemInspectorCopyPath").click();
  expect(new Set(await page.evaluate(() => window.__copiedInspectorText))).toEqual(new Set(["$.Damage", "$.tag.Damage"]));
  await search.fill("key.with[brackets]");
  await expect(dialog.locator("#itemInspectorSearchStatus")).toContainText("1");
  await dialog.locator("#itemInspectorCopyPath").click();
  expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe('$.tag["key.with[brackets]"]');
  await search.fill("does-not-exist");
  await expect(dialog.locator("#itemInspectorNext")).toBeDisabled();
  await expect(dialog.locator("#itemInspectorPrevious")).toBeDisabled();
});

for (const [width, height] of [[1440, 1000], [390, 844]]) {
  test(`item inspector contains wheel scrolling and restores page scrolling at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await openInspectorFixture(page, { inventory: { 0: inspectedItem({ nbt_view: compound({
      LongText: scalar("String", "Long NBT value\n".repeat(100)),
      ...Object.fromEntries(Array.from({ length: 70 }, (_, i) => [`Field${i}`, scalar("Int", i)])),
    }) }) } });
    const dialog = await openInspector(page);
    const background = await page.evaluate(() => window.scrollY);
    await tab(dialog, "tree").click();
    const tree = dialog.locator("#itemInspectorTree");
    await tree.hover();
    await page.mouse.wheel(0, 250);
    await expect.poll(() => tree.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    await tree.evaluate(el => { el.scrollTop = el.scrollHeight; });
    const body = dialog.locator(".inspector-body");
    const bodyTop = await body.evaluate(el => el.scrollTop);
    await page.mouse.wheel(0, 500);
    await page.waitForTimeout(200); // Wheel scrolling is asynchronous.
    expect(await body.evaluate(el => el.scrollTop)).toBe(bodyTop);
    expect(await page.evaluate(() => window.scrollY)).toBe(background);
    await dialog.locator("#itemInspectorSearch").fill("LongText");
    const value = dialog.locator("#itemInspectorValue");
    await value.hover();
    await page.mouse.wheel(0, 250);
    await expect.poll(() => value.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    await value.evaluate(el => { el.scrollTop = el.scrollHeight; });
    await page.mouse.wheel(0, 1000);
    await dialog.locator(".inspector-header").hover();
    await page.mouse.wheel(0, 1000);
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => window.scrollY)).toBe(background);
    if (process.env.MCBE_QA_INSPECTOR_DIR) await page.screenshot({ path: path.join(process.env.MCBE_QA_INSPECTOR_DIR, `scroll-${width}.png`) });
    await dialog.locator("#btnCloseSlotInspector").focus();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.mouse.move(width / 2, height / 2);
    await page.mouse.wheel(0, 300);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  });
}

for (const [locale, width, height] of [["de", 1440, 1000], ["en", 1024, 768], ["de", 320, 568], ["en", 390, 844]]) {
  test(`item inspector compact details preserve full values and paths in ${locale} at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const longKey = "example_addon:original_container_configuration_with_custom_item_metadata";
    const fullPath = `$.tag[${JSON.stringify(longKey)}].Description`;
    const fullValue = "Long description: " + "A complete original value with spaces, quotes \" and Unicode ä. ".repeat(5);
    const multiline = "First line\nSecond line";
    const errors = await openInspectorFixture(page, { inventory: { 0: inspectedItem({ nbt_view: compound({
      Count: scalar("Byte", 1), Short: scalar("String", "short"), Empty: scalar("String", ""),
      Multiline: scalar("String", multiline),
      tag: compound({ [longKey]: compound({ Description: scalar("String", fullValue) }) }),
    }) }) } }, undefined, locale);
    const dialog = await openInspector(page);
    await tab(dialog, "tree").click();
    const search = dialog.locator("#itemInspectorSearch");
    const detail = dialog.locator("#itemInspectorValue");
    for (const key of ["Count", "Short", "Empty"]) {
      await search.fill(key);
      await expect(node(dialog, `$.${key}`)).toHaveAttribute("aria-selected", "true");
      await expect(detail).toBeHidden();
    }
    await search.fill("Count");
    await expect(dialog.locator("#itemInspectorExplanation")).toHaveText(locale === "de" ? "Gespeicherte Anzahl im Stapel." : "Stored stack count.");
    await expect(dialog.locator("#itemInspectorCopyPath")).toHaveText(locale === "de" ? "Pfad kopieren" : "Copy path");
    await dialog.locator("#itemInspectorCopyValue").click();
    expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe("1");
    if (process.env.MCBE_QA_INSPECTOR_DIR) {
      await page.screenshot({ path: path.join(process.env.MCBE_QA_INSPECTOR_DIR, `compact-${locale}-${width}-count.png`), animations: "disabled" });
    }
    await search.fill("Long description:");
    await expect(node(dialog, fullPath)).toHaveAttribute("aria-selected", "true");
    await expect(detail).toBeVisible();
    expect(await detail.textContent()).toBe(fullValue);
    await expect(dialog.locator("#itemInspectorPath")).toHaveText(fullPath);
    await dialog.locator("#itemInspectorCopyPath").click();
    expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe(fullPath);
    await dialog.locator("#itemInspectorCopyValue").click();
    expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe(fullValue);
    for (const locator of [detail, dialog.locator("#itemInspectorPath"), dialog.locator("#itemInspectorNode")]) {
      expect(await locator.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    }
    if (await detail.evaluate(el => el.scrollHeight > el.clientHeight)) {
      await detail.focus();
      await page.keyboard.press("End");
      await expect.poll(() => detail.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThanOrEqual(1);
      await page.keyboard.press("Home");
      await expect.poll(() => detail.evaluate(el => el.scrollTop)).toBe(0);
    }
    if (process.env.MCBE_QA_INSPECTOR_DIR) {
      await page.screenshot({ path: path.join(process.env.MCBE_QA_INSPECTOR_DIR, `compact-${locale}-${width}-long.png`), animations: "disabled" });
    }
    await search.fill("Multiline");
    await expect(detail).toBeVisible();
    expect(await detail.textContent()).toBe(multiline);
    await tab(dialog, "overview").click();
    await tab(dialog, "tree").click();
    await expect(detail).toBeVisible();
    expect(await page.evaluate(() => isDirty)).toBe(false);
    expect(errors).toEqual([]);
  });
}

test("item inspector updates clipped value details when the viewport changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const value = "W".repeat(45);
  const errors = await openInspectorFixture(page, { inventory: { 0: inspectedItem({ nbt_view: compound({
    Name: scalar("String", value),
  }) }) } });
  const dialog = await openInspector(page);
  await tab(dialog, "tree").click();
  await node(dialog, "$.Name").click();
  const detail = dialog.locator("#itemInspectorValue");
  await expect(detail).toBeHidden();
  await page.setViewportSize({ width: 320, height: 568 });
  await expect(detail).toBeVisible();
  await expect(detail).toHaveText(value);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(detail).toBeHidden();
  await dialog.locator("#btnCloseSlotInspector").click();
  await openInspector(page);
  await tab(dialog, "tree").click();
  await node(dialog, "$.Name").click();
  await expect(detail).toBeHidden();
  expect(errors).toEqual([]);
});

test("item inspector searches literal string values without JSON escaping", async ({ page }) => {
  const values = {
    Quoted: 'He said "hello" today',
    FilePath: "C:\\World\\level.dat",
    Tabbed: "alpha\tbeta",
  };
  const errors = await openInspectorFixture(page, {
    inventory: { 0: inspectedItem({ nbt_view: compound(Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, scalar("String", value)]),
    )) }) },
  });
  const before = await page.evaluate(() => JSON.stringify(inventory));
  const dialog = await openInspector(page);
  await tab(dialog, "tree").click();
  for (const [key, value] of Object.entries(values)) {
    await dialog.locator("#itemInspectorSearch").fill(value);
    await expect(dialog.locator("#itemInspectorSearchStatus")).toHaveText("Treffer 1 von 1");
    await expect(node(dialog, `$.${key}`)).toHaveAttribute("aria-selected", "true");
    await dialog.locator("#itemInspectorCopyValue").click();
    expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe(value);
  }
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  expect(errors).toEqual([]);
});

test("item inspector retains the loaded baseline after editing and moving an item", async ({ page }) => {
  await openInspectorFixture(page);
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailDamage").fill("238");
  await page.locator("#detailSlotNum").click();
  expect(await page.evaluate(() => inventory[0].nbt_view)).toBeUndefined();
  let dialog = await openInspector(page);
  await expect(dialog).toContainText("238");
  await dialog.locator("#btnCloseSlotInspector").focus();
  await page.keyboard.press("Control+z");
  expect(await page.evaluate(() => inventory[0].damage)).toBe(238);
  await expect(dialog).toBeVisible();
  await tab(dialog, "json").click();
  await dialog.locator("#itemInspectorCopyJson").click();
  expect(JSON.parse(await page.evaluate(() => window.__copiedInspectorText.at(-1)))).toEqual(inspectedItem().nbt_view);
  await page.keyboard.press("Escape");
  await page.locator('.inventory-slot[data-slot="0"]').dragTo(page.locator('.inventory-slot[data-slot="3"]'));
  dialog = await openInspector(page, 3);
  await tab(dialog, "json").click();
  await dialog.locator("#itemInspectorCopyJson").click();
  expect(JSON.parse(await page.evaluate(() => window.__copiedInspectorText.at(-1)))).toEqual(inspectedItem().nbt_view);
  await page.keyboard.press("Escape");
  await page.locator("#btnUndo").click();
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].damage)).toBe(237);
  expect(await page.evaluate(() => isDirty)).toBe(false);
});

test("item inspector distinguishes a new item from loaded NBT and supports the context menu", async ({ page }) => {
  await openInspectorFixture(page, { inventory: { 0: { slot: 0, name: "minecraft:stone", count: 8, damage: 0 } } });
  const slot = page.locator('.inventory-slot[data-slot="0"]');
  await slot.click({ button: "right" });
  await page.locator("#slotContextMenu").getByText("NBT-Details", { exact: true }).click();
  const dialog = page.locator("#slotInspectorPanel");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("minecraft:stone");
  await tab(dialog, "tree").click();
  await expect(dialog.getByRole("treeitem")).toHaveCount(0);
  await expect(dialog).toContainText(/keine.*Original|Original.*verfügbar/i);
  await tab(dialog, "json").click();
  await expect(dialog.locator("#itemInspectorCopyJson")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(slot).toBeFocused();
});

test("item inspector reports protected slots without pretending to show editable NBT", async ({ page }) => {
  await openInspectorFixture(page, { inventory: {}, hidden_unknown_slots: { inventory: 0, ender_chest: 0, inventory_protected_known_slots: [0] } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  const dialog = page.locator("#slotInspectorPanel");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(/geschützt|Read-only/i);
  await tab(dialog, "tree").click();
  await expect(dialog.getByRole("treeitem")).toHaveCount(0);
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => inventory)).toEqual({});
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("item inspector remains usable in viewer mode and closes on player reload", async ({ page }) => {
  const errors = await openInspectorFixture(page, {}, "http://127.0.0.1:8766");
  const dialog = await openInspector(page);
  await tab(dialog, "json").click();
  await dialog.locator("#itemInspectorCopyJson").click();
  expect(JSON.parse(await page.evaluate(() => window.__copiedInspectorText.at(-1)))).toEqual(inspectedItem().nbt_view);
  await page.evaluate(() => loadPlayer(currentPlayerKey, true));
  await expect(dialog).toBeHidden();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  expect(await page.evaluate(() => isDirty)).toBe(false);
  expect(errors).toEqual([]);
});

test("item inspector identifies excerpts and keeps typed array values exact", async ({ page }) => {
  const excerpt = compound({
    Empty: compound({}),
    Coordinates: { ...scalar("LongArray", ["9223372036854775807"]),
      truncation: { reason: "items", shown: 1, total: 81 }, truncated: "80 weitere Werte" },
  });
  await openInspectorFixture(page, { inventory: { 0: inspectedItem({ nbt_view: excerpt }) } });
  const dialog = await openInspector(page);
  await tab(dialog, "tree").click();
  await expect(dialog).toContainText(/Auszug|gekürzt/);
  await dialog.locator("#itemInspectorSearch").fill("9223372036854775807");
  const value = node(dialog, "$.Coordinates[0]");
  await expect(value).toBeVisible();
  await expect(value).toContainText("Long");
  await value.click();
  await dialog.locator("#itemInspectorCopyValue").click();
  expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toContain("9223372036854775807");
  await tab(dialog, "json").click();
  await expect(dialog).toContainText(/Auszug|gekürzt/);
  await dialog.locator("#itemInspectorCopyJson").click();
  expect(JSON.parse(await page.evaluate(() => window.__copiedInspectorText.at(-1)))).toEqual(excerpt);
});

test("item inspector retains every NBT type and signed zero through navigation and copying", async ({ page }) => {
  const view = compound({
    ByteValue: scalar("Byte", -128), ShortValue: scalar("Short", -32768),
    IntValue: scalar("Int", -2147483648), LongValue: scalar("Long", "9223372036854775807"),
    FloatValue: scalar("Float", "NaN"), DoubleValue: scalar("Double", "-Infinity"),
    NegativeFloat: scalar("Float", "-0"), PositiveFloat: scalar("Float", 0),
    NegativeDouble: scalar("Double", "-0"), PositiveDouble: scalar("Double", 0),
    EmptyText: scalar("String", ""), EmptyCompound: compound({}),
    List: { ...scalar("List", [scalar("String", "nested value")]), list_type_id: 8 },
    Bytes: scalar("ByteArray", [-128, 127]),
    Ints: scalar("IntArray", [-2147483648, 2147483647]),
    Longs: scalar("LongArray", ["-9223372036854775808", "9223372036854775807"]),
  });
  const errors = await openInspectorFixture(page, { inventory: { 0: inspectedItem({ nbt_view: view }) } });
  const before = await page.evaluate(() => JSON.stringify(inventory));
  const dialog = await openInspector(page);
  await tab(dialog, "tree").click();
  const root = node(dialog, "$"), longs = node(dialog, "$.Longs");
  await root.focus();
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowUp");
  await expect(root).toBeFocused();
  await page.keyboard.press("End");
  await expect(longs).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(longs).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(longs).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("ArrowRight");
  await expect(node(dialog, "$.Longs[0]")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(node(dialog, "$.Longs[1]")).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(longs).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(longs).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Space");
  await expect(longs).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Enter");
  await expect(longs).toHaveAttribute("aria-expanded", "false");

  const leaves = Object.entries(view.value).filter(([, tag]) => !["CompoundTag", "ListTag", "ByteArrayTag", "IntArrayTag", "LongArrayTag"].includes(tag.type));
  for (const [key, tag] of [
    ...leaves,
    ["EmptyCompound", scalar("Compound", {})],
    ["List[0]", scalar("String", "nested value")],
    ["Bytes[1]", scalar("Byte", 127)],
    ["Ints[1]", scalar("Int", 2147483647)],
    ["Longs[0]", scalar("Long", "-9223372036854775808")],
  ]) {
    await dialog.locator("#itemInspectorSearch").fill(`$.${key}`);
    await expect(node(dialog, `$.${key}`)).toHaveAttribute("aria-selected", "true");
    await expect(node(dialog, `$.${key}`).locator(".inspector-type")).toHaveText(tag.type.replace(/Tag$/, ""));
    await dialog.locator("#itemInspectorCopyValue").click();
    expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toBe(typeof tag.value === "string" ? tag.value : JSON.stringify(tag.value));
  }
  const search = dialog.locator("#itemInspectorSearch");
  await search.fill("-0");
  await expect(dialog.locator("#itemInspectorSearchStatus")).toHaveText("Treffer 1 von 2");
  await search.press("Shift+Enter");
  await expect(node(dialog, "$.NegativeDouble")).toHaveAttribute("aria-selected", "true");
  await search.press("Enter");
  await expect(node(dialog, "$.NegativeFloat")).toHaveAttribute("aria-selected", "true");
  await tab(dialog, "json").click();
  await dialog.locator("#itemInspectorCopyJson").click();
  expect(JSON.parse(await page.evaluate(() => window.__copiedInspectorText.at(-1)))).toEqual(view);
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(errors).toEqual([]);
});

test("item inspector bounds large and malformed trees and prevents copying incomplete values", async ({ page }) => {
  const wide = compound({ Large: scalar("IntArray", Array.from({ length: 3000 }, (_, index) => index)) });
  let deep = scalar("String", "beyond-the-client-depth-limit");
  for (let depth = 0; depth < 40; depth++) deep = scalar("List", [deep]);
  const malformed = compound({
    Compound: scalar("Compound", "unexpected scalar"),
    List: scalar("List", {}),
    Array: scalar("IntArray", [{ unexpected: 1 }]),
    Text: { ...scalar("String", "available excerpt"), truncation: { reason: "string", shown: 17, total: 5000 } },
  });
  const views = [wide, compound({ Deep: deep }), malformed];
  const errors = await openInspectorFixture(page, {
    inventory: Object.fromEntries(views.map((nbt_view, slot) => [slot, inspectedItem({ slot, source_slot: slot, nbt_view })])),
  });
  const before = await page.evaluate(() => JSON.stringify(inventory));
  for (let slot = 0; slot < views.length; slot++) {
    const dialog = await openInspector(page, slot);
    await tab(dialog, "tree").click();
    await expect(dialog).toContainText("Auszug");
    if (slot === 0) {
      await expect(dialog.locator("#itemInspectorSearchStatus")).toHaveText("2048 NBT-Knoten");
      await dialog.locator("#itemInspectorSearch").fill("$.Large[2045]");
      await expect(node(dialog, "$.Large[2045]")).toHaveAttribute("aria-selected", "true");
      await dialog.locator("#itemInspectorSearch").fill("$.Large[2046]");
      await expect(dialog.locator("#itemInspectorSearchStatus")).toHaveText("Keine Treffer in den angezeigten Daten.");
      await node(dialog, "$.Large").click();
      await expect(dialog.locator("#itemInspectorCopyValue")).toBeDisabled();
    } else if (slot === 1) {
      await expect(dialog.locator("#itemInspectorSearchStatus")).toHaveText("33 NBT-Knoten");
      await dialog.locator("#itemInspectorSearch").fill("beyond-the-client-depth-limit");
      await expect(dialog.locator("#itemInspectorSearchStatus")).toHaveText("Keine Treffer in den angezeigten Daten.");
    } else {
      for (const key of ["Compound", "List", "Array[0]", "Text"]) {
        await dialog.locator("#itemInspectorSearch").fill(`$.${key}`);
        await expect(node(dialog, `$.${key}`)).toHaveAttribute("aria-selected", "true");
        await expect(dialog.locator("#itemInspectorExplanation")).toContainText("gekürzt");
        await expect(dialog.locator("#itemInspectorCopyValue")).toBeDisabled();
      }
    }
    await tab(dialog, "json").click();
    await expect(dialog.locator("#itemInspectorCopyJson")).toHaveText("JSON-Auszug kopieren");
    await dialog.locator("#itemInspectorCopyJson").click();
    expect(JSON.parse(await page.evaluate(() => window.__copiedInspectorText.at(-1)))).toEqual(views[slot]);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  }
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  expect(errors).toEqual([]);
});

test("item inspector summarizes every special item without changing its draft", async ({ page }) => {
  const cases = [
    ["bundle", "bundle", { items: [{ slot: 0, name: "minecraft:stone", count: 16 }] }, { "Belegte Plätze": "1", "Bundle-Auslastung": "16 / 64 Gewichtseinheiten" }],
    ["undyed_shulker_box", "shulker", { items: [{ slot: 3, name: "minecraft:stone", count: 8 }] }, { "Belegte Plätze": "1" }],
    ["written_book", "book", { pages: [{ text: "first" }, { text: "second" }], title: "Inspector Book", author: "Author" }, { "Seiten": "2", "Buchtitel": "Inspector Book", "Autor": "Author" }],
    ["firework_rocket", "fireworks", { flight: 2, explosions: [{ colors: [1] }] }, { "Flugdauer": "2", "Feuerwerkseffekte": "1" }],
    ["firework_star", "firework_star", { explosions: [{ colors: [2] }] }, { "Feuerwerkseffekte": "1" }],
    ["banner", "banner", { patterns: [] }, { "Bannermuster": "0" }],
  ];
  const inventoryFixture = Object.fromEntries(cases.map(([id, kind, data], slot) => [slot, inspectedItem({
    slot, source_slot: slot, name: `minecraft:${id}`, damage: 0,
    nbt_view: compound({ Name: scalar("String", `minecraft:${id}`) }),
    special_item: { kind, editable: true, data },
  })]));
  inventoryFixture[6] = inspectedItem({ slot: 6, source_slot: 6, name: "minecraft:banner",
    nbt_view: compound({ Name: scalar("String", "minecraft:banner") }),
    special_item: { kind: "banner", editable: false, data: {} } });
  const errors = await openInspectorFixture(page, {
    inventory: inventoryFixture,
    stack_limits: { __default__: 64, "minecraft:stone": 64 },
  });
  const before = await page.evaluate(() => JSON.stringify(inventory));
  for (let slot = 0; slot < cases.length; slot++) {
    const dialog = await openInspector(page, slot);
    const properties = await dialog.locator(".inspector-properties").evaluate(list => Object.fromEntries(
      Array.from(list.querySelectorAll("dt"), label => [label.textContent, label.nextElementSibling.textContent]),
    ));
    expect(properties).toMatchObject(cases[slot][3]);
    if (slot === 1) await expect(dialog.locator(".inspector-contents")).toHaveText("Platz 4: 8 × Stein");
    if (slot === 5) await expect(dialog.locator(".inspector-banner")).toContainText("ohne geladene Mustertexturen nicht verfügbar");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  }
  const protectedDialog = await openInspector(page, 6);
  await expect(protectedDialog.locator("#inspectorOverview")).toContainText("Geschützter Aufbau");
  await expect(protectedDialog.locator(".inspector-banner")).toHaveCount(0);
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(errors).toEqual([]);
});

test("item inspector keeps delayed banner rendering with the current item", async ({ page }) => {
  const errors = await openInspectorFixture(page, {
    inventory: Object.fromEntries([0, 1].map(slot => [slot, inspectedItem({
      slot, source_slot: slot, name: "minecraft:banner", damage: slot,
      nbt_view: compound({ Name: scalar("String", "minecraft:banner"), Damage: scalar("Short", slot) }),
      special_item: { kind: "banner", editable: true, data: { patterns: [], base_color: slot } },
    })])),
  });
  const before = await page.evaluate(() => JSON.stringify(inventory));
  const baseImage = await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 20; canvas.height = 40;
    const context = canvas.getContext("2d"); context.fillStyle = "#ffffff"; context.fillRect(0, 0, 20, 40);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  let releaseTexture, markRequested;
  const textureGate = new Promise(resolve => { releaseTexture = resolve; });
  const textureRequested = new Promise(resolve => { markRequested = resolve; });
  await page.route("**/api/icons/inspector-late-base", async route => {
    markRequested();
    await textureGate;
    await route.fulfill({ contentType: "image/png", body: Buffer.from(baseImage, "base64") });
  });
  await page.route("**/api/icons/status*", route => route.fulfill({ json: {
    success: true, icons: {}, banner_patterns: { base: { url: "/api/icons/inspector-late-base" } }, count: 0, sources: [], warnings: [],
  } }));
  await page.evaluate(() => loadLocalIconIndex());
  const dialog = await openInspector(page, 0);
  await textureRequested;
  await expect(dialog.locator(".inspector-banner canvas")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await openInspector(page, 1);
  releaseTexture();
  const canvas = dialog.locator(".inspector-banner canvas");
  await expect(canvas).toHaveCount(1);
  await expect(canvas).toHaveAccessibleName("Bannervorschau");
  const color = await page.evaluate(() => JSON.parse(document.getElementById("specialItemSchema").textContent).color_hex[1]);
  expect(await canvas.evaluate(element => Array.from(element.getContext("2d").getImageData(0, 0, 1, 1).data)))
    .toEqual([1, 3, 5].map(offset => Number.parseInt(color.slice(offset, offset + 2), 16)).concat(255));
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(errors).toEqual([]);
});

test("item inspector offers an accessible inline fallback when clipboard access fails", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await openInspectorFixture(page);
  await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw new Error("Synthetic clipboard rejection"); }; });
  const dialog = await openInspector(page);
  await tab(dialog, "json").click();
  const copy = dialog.locator("#itemInspectorCopyJson");
  await copy.click();
  const fallback = dialog.locator("#itemInspectorCopyFallback");
  const text = dialog.locator("#itemInspectorCopyText");
  await expect(fallback).toBeVisible();
  await expect(text).toBeFocused();
  expect(JSON.parse(await text.inputValue())).toEqual(inspectedItem().nbt_view);
  expect(await text.evaluate(element => element.selectionEnd - element.selectionStart)).toBe((await text.inputValue()).length);
  await expect(page.locator("#copyFallbackOverlay")).toBeHidden();
  if (process.env.MCBE_QA_INSPECTOR_DIR) await dialog.screenshot({ path: path.join(process.env.MCBE_QA_INSPECTOR_DIR, "clipboard-fallback-320.png"), animations: "disabled" });
  await dialog.locator("#itemInspectorCopyDismiss").click();
  await expect(fallback).toBeHidden();
  await expect(dialog.locator("#btnCloseSlotInspector")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  expect(await page.evaluate(() => isDirty)).toBe(false);
});

test("item inspector keeps clipboard feedback with the latest copy request", async ({ page }) => {
  const errors = await openInspectorFixture(page);
  await page.evaluate(() => {
    window.__pendingInspectorCopies = [];
    navigator.clipboard.writeText = text => new Promise((resolve, reject) => {
      window.__pendingInspectorCopies.push({ text, resolve, reject });
    });
  });
  const dialog = await openInspector(page);
  await tab(dialog, "json").click();
  const fallback = dialog.locator("#itemInspectorCopyFallback");
  const status = dialog.locator("#itemInspectorCopyStatus");
  const copyJson = dialog.locator("#itemInspectorCopyJson");
  const copyContext = dialog.locator("#btnCopySlotInspector");
  await copyJson.click();
  await copyContext.click();
  await page.evaluate(() => window.__pendingInspectorCopies[1].resolve());
  await expect(status).toHaveText("Diagnose kopiert.");
  await page.evaluate(() => window.__pendingInspectorCopies[0].reject(new Error("Delayed older copy failure")));
  await expect(fallback).toBeHidden();
  await expect(status).toHaveText("Diagnose kopiert.");

  await copyJson.click();
  await page.evaluate(() => window.__pendingInspectorCopies[2].reject(new Error("Current copy failure")));
  await expect(fallback).toBeVisible();
  expect(JSON.parse(await dialog.locator("#itemInspectorCopyText").inputValue())).toEqual(inspectedItem().nbt_view);
  await copyContext.click();
  await page.evaluate(() => window.__pendingInspectorCopies[3].resolve());
  await expect(fallback).toBeHidden();
  await expect(status).toHaveText("Diagnose kopiert.");

  await copyJson.click();
  await copyContext.click();
  await page.evaluate(() => window.__pendingInspectorCopies[5].resolve());
  await expect(status).toHaveText("Diagnose kopiert.");
  await page.evaluate(() => window.__pendingInspectorCopies[4].resolve());
  await expect(status).toHaveText("Diagnose kopiert.");

  await copyJson.click();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await openInspector(page);
  await page.evaluate(() => window.__pendingInspectorCopies[6].reject(new Error("Copy from a closed inspector")));
  await expect(fallback).toBeHidden();
  await expect(status).toHaveText("");
  await tab(dialog, "json").click();
  await copyJson.click();
  await page.evaluate(() => loadPlayer(currentPlayerKey, true));
  await expect(dialog).toBeHidden();
  await page.evaluate(() => window.__pendingInspectorCopies[7].resolve());
  await expect(dialog).toBeHidden();
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(errors).toEqual([]);
});

test("item inspector supports touch navigation on a mobile viewport", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  try {
    const page = await context.newPage();
    const errors = await openInspectorFixture(page);
    await page.locator('.inventory-slot[data-slot="0"]').tap();
    if (!(await page.locator("#btnInspectSlotNbt").isVisible())) await page.locator('.btn-toggle[data-panel="right"]').tap();
    await page.locator("#btnInspectSlotNbt").tap();
    const dialog = page.locator("#slotInspectorPanel");
    await expect(dialog).toBeVisible();
    await tab(dialog, "tree").tap();
    await dialog.locator("#itemInspectorSearch").fill("UniqueID");
    await node(dialog, "$.tag.UniqueID").tap();
    await dialog.locator("#itemInspectorCopyValue").tap();
    expect(await page.evaluate(() => window.__copiedInspectorText.at(-1))).toContain("9223372036854775807");
    await expect(dialog.locator("#itemInspectorCopyStatus")).toBeVisible();
    await dialog.locator("#btnCloseSlotInspector").tap();
    await expect(dialog).toBeHidden();
    expect(await page.evaluate(() => isDirty)).toBe(false);
    expect(errors).toEqual([]);
  } finally {
    await context.close();
  }
});

for (const [layout, theme, width, height] of [
  ["studio", "dark", 2246, 1124],
  ["studio", "dark", 1440, 1000], ["classic", "light", 1024, 768],
  ["focus", "dark", 390, 844], ["studio", "light", 320, 568],
]) {
  test(`item inspector fits ${layout} ${theme} at ${width}px and keeps all actions reachable`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const errors = await openInspectorFixture(page);
    await selectSetting(page, "layoutSelect", layout);
    await selectSetting(page, "themeSelect", theme);
    const dialog = await openInspector(page);
    for (const name of ["overview", "tree", "json"]) {
      await tab(dialog, name).click();
      if (name === "tree") {
        await dialog.locator("#itemInspectorSearch").fill("key.with[brackets]");
        await expect(dialog.locator("#itemInspectorSearchStatus")).toContainText("1");
        const searchBounds = await dialog.locator("#itemInspectorSearch").evaluate(element => {
          const input = element.getBoundingClientRect();
          const body = document.querySelector("#slotInspectorBody").getBoundingClientRect();
          return { top: input.top, bottom: input.bottom, bodyTop: body.top, bodyBottom: body.bottom };
        });
        expect(searchBounds.top).toBeGreaterThanOrEqual(searchBounds.bodyTop);
        expect(searchBounds.bottom).toBeLessThanOrEqual(searchBounds.bodyBottom);
        // Fractional CSS pixels can trim less than one pixel at the inner scroll edge.
        // A result hidden by the footer still fails this bound.
        await expect(dialog.locator('[role="treeitem"][aria-selected="true"]')).toBeInViewport({ ratio: 0.99 });
      }
      const dimensions = await dialog.evaluate(element => {
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          client: element.clientWidth, scroll: element.scrollWidth };
      });
      expect(dimensions.left).toBeGreaterThanOrEqual(0);
      expect(dimensions.right).toBeLessThanOrEqual(width + 1);
      expect(dimensions.top).toBeGreaterThanOrEqual(0);
      expect(dimensions.bottom).toBeLessThanOrEqual(height + 1);
      expect(Math.abs(dimensions.left - (width - dimensions.right))).toBeLessThanOrEqual(1);
      expect(Math.abs(dimensions.top - (height - dimensions.bottom))).toBeLessThanOrEqual(1);
      expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client + 1);
      await expect(dialog.locator("#btnCloseSlotInspector")).toBeInViewport();
      if (process.env.MCBE_QA_INSPECTOR_DIR) {
        await page.screenshot({ path: path.join(process.env.MCBE_QA_INSPECTOR_DIR, `${layout}-${theme}-${width}-${name}.png`), animations: "disabled" });
      }
    }
    const close = dialog.locator("#btnCloseSlotInspector");
    await close.focus();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.querySelector("#slotInspectorPanel").contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Shift+Tab");
    await expect(close).toBeFocused();
    await close.click();
    await expect(dialog).toBeHidden();
    await expect(page.locator("#btnInspectSlotNbt")).toBeFocused();
    expect(errors).toEqual([]);
  });
}
