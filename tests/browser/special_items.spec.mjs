import { expect, test } from "@playwright/test";
import {
  openSpecialProperties,
  openSpecialFixture,
  NORMAL_BASE_URL,
  collectBrowserErrors,
  contrastRatio,
  selectSetting,
} from "./fixtures/app.mjs";

test("contained drag without randomUUID preserves drafts, rejects overwrite and undoes as one edit", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.addInitScript(() => Object.defineProperty(window.crypto, "randomUUID", { value: undefined }));
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 0, source_index: 3, name: "minecraft:diamond", count: 2, damage: 0, lore: ["Keep"], has_preserved_nbt: true },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailCustomName").fill("Parent draft");
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const slot = n => dialog.locator(`[data-special-slot="${n}"]`);
  await slot(0).click();
  await dialog.getByLabel("Menge", { exact: true }).fill("3");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await page.keyboard.down("Control");
  await slot(0).dragTo(slot(1));
  await page.keyboard.up("Control");
  await expect(slot(1)).toContainText("3");
  await page.keyboard.down("Control"); await slot(0).dragTo(slot(1)); await page.keyboard.up("Control");
  await expect(dialog.getByRole("alert")).toContainText("Zielplatz leer");
  await slot(1).dragTo(slot(2));
  await expect(slot(1)).toContainText("Leerer Slot");
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  const result = await page.evaluate(() => inventory[0]);
  expect(result.display_name).toBe("Parent draft");
  expect(result.special_edit.data.items).toMatchObject([
    { slot: 0, source_index: 3, count: 3, lore: ["Keep"] },
    { slot: 2, copy_source_index: 3, count: 3, lore: ["Keep"] },
  ]);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  expect(errors).toEqual([]);
});

test("bundle drag copies work without randomUUID and wait for confirmation", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.addInitScript(() => Object.defineProperty(window.crypto, "randomUUID", { value: undefined }));
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:bundle", count: 1, damage: 0,
    special_item: { kind: "bundle", editable: true, data: { items: [
      { slot: 0, source_index: 0, name: "minecraft:diamond", count: 2, damage: 0 },
    ] } } } });
  await page.locator('[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await page.keyboard.down("Control");
  await dialog.locator('[data-special-slot="0"]').dragTo(dialog.getByRole("button", { name: "Item hinzufügen", exact: true }));
  await page.keyboard.up("Control");
  await expect(dialog.locator(".special-slot-count")).toHaveText("4");
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0].count)).toBe(4);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  expect(errors).toEqual([]);
});

test("bundle contents hide positions and keyboard copies enforce total capacity", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:bundle", count: 1, damage: 0,
    special_item: { kind: "bundle", editable: true, data: { items: [
      { slot: 9, source_index: 0, name: "minecraft:diamond", count: 32, damage: 0 },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').focus();
  await page.keyboard.press("Shift+F10");
  await page.locator('#slotContextMenu [data-action="special"]').click();
  const dialog = page.locator("#specialItemDialog");
  await expect(dialog.locator(".special-slot-number")).toHaveCount(0);
  if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/bundle-copy-mobile.png` });
  await dialog.locator('[data-special-slot="9"]').focus(); await page.keyboard.press("Control+c");
  await dialog.getByRole("button", { name: "Item hinzufügen", exact: true }).focus(); await page.keyboard.press("Control+v");
  await expect(dialog).toContainText("64 / 64 Gewichtseinheiten");
  await dialog.getByRole("button", { name: "Item hinzufügen", exact: true }).focus(); await page.keyboard.press("Control+v");
  await expect(dialog.getByRole("alert")).toContainText("zu voll");
  await expect(dialog.locator(".special-slot-count")).toHaveCount(1);
  await expect(dialog.locator(".special-slot-count")).toHaveText("64");
  await dialog.locator('[data-special-slot="9"]').click();
  await expect(dialog.locator(".special-selected-slot")).toHaveCount(0);
  await page.keyboard.press("Escape"); await page.keyboard.press("Escape");
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
});

test("bundle additions merge after quantity edits and repeated paste keeps its original amount", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:bundle", count: 1, damage: 0,
    special_item: { kind: "bundle", editable: true, data: { items: [
      { slot: 9, source_index: 0, stack_key: "plain", name: "minecraft:diamond", count: 2, damage: 0 },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.locator('[data-special-slot="9"]').click();
  await dialog.getByLabel("Menge", { exact: true }).fill("3");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Item hinzufügen", exact: true }).click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await dialog.getByLabel("Item-ID", { exact: true }).press("Tab");
  await dialog.getByLabel("Menge", { exact: true }).fill("2");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog.locator(".special-slot-count")).toHaveCount(1);
  await expect(dialog.locator(".special-slot-count")).toHaveText("5");
  await dialog.locator('[data-special-slot="9"]').focus();
  await page.keyboard.press("Control+c");
  for (const total of [10, 15]) {
    await dialog.getByRole("button", { name: "Item hinzufügen", exact: true }).focus();
    await page.keyboard.press("Control+v");
    await expect(dialog.locator(".special-slot-count")).toHaveText(String(total));
  }
  await dialog.locator('[data-special="accept"]').click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items)).toMatchObject([
    { slot: 9, source_index: 0, name: "minecraft:diamond", count: 15 },
  ]);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  expect(errors).toEqual([]);
});

test("banner type round trip is a no-op and the detail heading uses the actual motif", async ({ page }) => {
  await openSpecialFixture(page, {
    0: { slot: 0, name: "minecraft:banner", count: 1, damage: 4,
      special_item: { kind: "banner", editable: true, data: { patterns: [] } } },
    1: { slot: 1, name: "minecraft:banner", count: 1, damage: 15,
      special_item: { kind: "banner", editable: true, data: { type: 1, patterns: [] } } },
  });
  const before = await page.evaluate(() => JSON.stringify(inventory[0]));
  await page.locator('.inventory-slot[data-slot="1"]').click();
  await expect(page.locator("#slotQuickTitle")).toHaveText("Ominöses Banner");
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("1");
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("0");
  await dialog.locator('[data-special="accept"]').click();
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(before);
  await page.locator('.inventory-slot[data-slot="1"]').click();
  await expect(page.locator("#slotQuickTitle")).toHaveText("Ominöses Banner");
});

test("copied container children stay editable independently and can be copied again", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 0, source_index: 3, name: "minecraft:diamond", count: 2, damage: 0, lore: ["Keep"], has_preserved_nbt: true },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const slot = n => dialog.locator(`[data-special-slot="${n}"]`);
  await slot(0).focus(); await page.keyboard.press("Control+c");
  await slot(1).focus(); await page.keyboard.press("Control+v");
  await slot(1).click();
  await dialog.getByLabel("Menge", { exact: true }).fill("3");
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Anzeigename", { exact: true }).fill("Independent copy");
  await dialog.locator('[data-special="accept"]').click();
  await slot(1).focus(); await page.keyboard.press("Control+c");
  await slot(2).focus(); await page.keyboard.press("Control+v");
  await slot(1).click();
  await dialog.getByRole("button", { name: "Item entfernen", exact: true }).click();
  await dialog.locator('[data-special="accept"]').click();
  const children = await page.evaluate(() => inventory[0].special_edit.data.items);
  expect(children).toMatchObject([
    { slot: 0, source_index: 3, count: 2, lore: ["Keep"] },
    { slot: 2, copy_source_index: 3, count: 3, display_name: "Independent copy", lore: ["Keep"], has_preserved_nbt: true },
  ]);
  expect(children[1].source_index).toBeUndefined();
  expect(errors).toEqual([]);
});

for (const locale of ["de", "en"]) {
  test(`ominous banner picker and shared icons retain draft fields ${locale}`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 4, lore: ["Keep"],
      special_item: { kind: "banner", editable: true, data: { patterns: [] } } } });
    const root = page.locator('.inventory-slot[data-slot="0"]');
    await expect(root.locator("img")).toHaveAttribute("src", /^data:image\/svg/);
    const blue = await root.locator("img").getAttribute("src");
    expect(decodeURIComponent(blue)).toContain("#3c44aa");
    await root.click(); await page.locator("#detailCustomName").fill("Draft name");
    await page.locator("#detailItemSearch").fill(locale === "de" ? "ominöses" : "ominous banner");
    await page.locator("#detailItemAutocomplete .autocomplete-item").first().click();
    await expect(page.locator("#detailCustomName")).toHaveValue("Draft name");
    await expect(page.locator("#detailDataVariant")).toBeHidden();
    expect(await page.evaluate(() => inventory[0].display_name)).toBe("Draft name");
    await page.locator("#detailSlotNum").click();
    await page.locator("#btnSpecialItem").click();
    const dialog = page.locator("#specialItemDialog");
    await expect(dialog.getByLabel(locale === "de" ? "Bannerart" : "Banner type")).toHaveValue("1");
    await expect(dialog.locator(".special-banner-layers")).toBeHidden();
    await dialog.locator('[data-special="accept"]').click();
    const result = await page.evaluate(() => inventory[0]);
    expect(result.special_edit.data.type).toBe(1);
    expect(result.damage).toBe(15); expect(result.lore).toEqual(["Keep"]);
    expect(result.display_name).toBe("Draft name");
    expect(errors).toEqual([]);
  });
}

test("contained banner selection and type conversion preserve pending name and lore", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0 } });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.locator('[data-special-slot="0"]').click();
  await dialog.locator(".special-item-name").fill("ominöses");
  await dialog.locator(".special-item-suggestions .autocomplete-item").first().click();
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Anzeigename", { exact: true }).fill("Contained draft");
  await dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true }).fill("Keep this lore");
  await expect(dialog.getByLabel("Variante", { exact: true })).toBeHidden();
  await dialog.getByRole("button", { name: "Banner bearbeiten", exact: true }).click();
  await expect(dialog.getByLabel("Bannerart", { exact: true })).toHaveValue("1");
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("0");
  await dialog.getByRole("button", { name: "Muster hinzufügen", exact: true }).click();
  await dialog.getByLabel("Farbe", { exact: true }).selectOption("4");
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("1");
  await dialog.locator('[data-special="accept"]').click();
  await expect(dialog.getByLabel("Anzeigename", { exact: true })).toHaveValue("Contained draft");
  await expect(dialog.getByLabel("Variante", { exact: true })).toBeHidden();
  await dialog.locator('[data-special="accept"]').click();
  await dialog.locator('[data-special="accept"]').click();
  const child = await page.evaluate(() => inventory[0].special_edit.data.items[0]);
  expect(child).toMatchObject({ name: "minecraft:banner", damage: 15, display_name: "Contained draft", lore: ["Keep this lore"],
    special_edit: { kind: "banner", data: { type: 1, patterns: [] } } });
  expect(errors).toEqual([]);
});

for (const locale of ["de", "en"]) {
  test.describe(`item damage policy ${locale}`, () => {
    test.use({ viewport: { width: 1440, height: 1000 } });

    const names = {
      "minecraft:stone": ["Stein", "Stone"],
      "minecraft:diamond_sword": ["Diamantschwert", "Diamond Sword"],
      "minecraft:goat_horn": ["Ziegenhorn", "Goat Horn"],
      "minecraft:potion": ["Trank", "Potion"],
      "minecraft:undyed_shulker_box": ["Shulkerkiste", "Shulker Box"],
    };
    const catalog = {
      items_db: names, addable_items: Object.keys(names),
      stack_limits: { "minecraft:stone": 64, "minecraft:diamond_sword": 1, "minecraft:goat_horn": 1,
        "minecraft:potion": 1, "minecraft:undyed_shulker_box": 1 },
      max_damage: { __default__: 32767, "minecraft:diamond_sword": 1561 },
    };
    const parent = items => ({ slot: 4, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
      special_item: { kind: "shulker", editable: true, data: { items } } });

    test("both editors offer only meaningful wear and named variant controls", async ({ page }) => {
      const errors = collectBrowserErrors(page);
      await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
      const samples = [
        { slot: 0, name: "minecraft:stone", count: 1, damage: 0 },
        { slot: 1, name: "minecraft:diamond_sword", count: 1, damage: 37 },
        { slot: 2, name: "minecraft:potion", count: 1, damage: 21, display_name: "Personal label", lore: ["Keep lore"] },
      ];
      await openSpecialFixture(page, { ...Object.fromEntries(samples.map(item => [item.slot, item])),
        4: parent(samples.map((item, source_index) => ({ ...item, source_index }))) }, catalog);
      const before = await page.evaluate(() => JSON.stringify(inventory));
      const dialog = page.locator("#specialItemDialog");
      for (const contained of [false, true]) {
        if (contained) {
          await page.locator('.inventory-slot[data-slot="4"]').click();
          await page.locator("#btnSpecialItem").click();
        }
        for (const sample of samples) {
          if (contained) {
            await dialog.getByRole("button", { name: new RegExp(`^Slot ${sample.slot + 1}:`) }).click();
            await openSpecialProperties(dialog);
            await expect(dialog.getByLabel(locale === "de" ? "Zielslot" : "Target slot", { exact: true })).toHaveCount(0);
          } else await page.locator(`.inventory-slot[data-slot="${sample.slot}"]`).click();
          const wear = contained ? dialog.getByLabel(locale === "de" ? "Abnutzung" : "Wear", { exact: true }) : page.locator("#detailDamage");
          const variant = contained ? dialog.getByLabel(locale === "de" ? "Variante" : "Variant", { exact: true }) : page.locator("#detailDataVariant");
          const note = contained ? dialog.locator(".special-damage-note") : page.locator("#detailDamageNote");
          if (sample.slot === 0) {
            await expect(wear).toBeHidden();
            await expect(variant).toBeHidden();
            await expect(note).toBeHidden();
          } else if (sample.slot === 1) {
            await expect(wear).toBeVisible();
            await expect(wear).toHaveValue("37");
            await expect(wear).toHaveAttribute("max", "1561");
            await expect(variant).toBeHidden();
            await expect(note).toContainText(locale === "de" ? "Verbleibende Haltbarkeit: 1524 von 1561" : "Remaining durability: 1524 of 1561");
            await wear.fill("38");
            await expect(note).toContainText("1523");
            if (contained) await wear.fill("37");
            else {
              expect(await page.evaluate(() => inventory[1].damage)).toBe(38);
              await page.locator("#btnUndo").click();
              await expect(wear).toHaveValue("37");
            }
          } else {
            await expect(wear).toBeHidden();
            await expect(variant).toBeVisible();
            await expect(variant.locator("option")).toHaveCount(47);
            await expect(variant).toHaveValue("21");
            await expect(variant.locator('option[value="46"]')).toContainText(locale === "de" ? "Verseuchung" : "Infestation");
            await variant.selectOption("46");
            await expect(wear).toHaveValue("46");
            const custom = contained ? dialog.getByLabel(locale === "de" ? "Anzeigename" : "Custom name", { exact: true }) : page.locator("#detailCustomName");
            await expect(custom).toHaveValue("Personal label");
            if (contained) await variant.selectOption("21");
            else {
              expect(await page.evaluate(() => inventory[2].damage)).toBe(46);
              await page.locator("#btnUndo").click();
              await expect(variant).toHaveValue("21");
            }
          }
          if (contained) await dialog.locator('footer [data-special="cancel"]').click();
        }
        if (contained) await dialog.locator('footer [data-special="cancel"]').click();
      }
      expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
      expect(errors).toEqual([]);
    });

    test("both editors preserve unknown originals and allow undoing a variant selection", async ({ page }) => {
      test.setTimeout(60_000);
      const errors = collectBrowserErrors(page);
      await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
      const samples = [
        { slot: 0, name: "minecraft:stone", count: 1, damage: -7 },
        { slot: 1, name: "minecraft:stone", count: 1, damage: 40000 },
        { slot: 2, name: "minecraft:goat_horn", count: 1, damage: 99 },
        { slot: 3, name: "minecraft:diamond_sword", count: 1, damage: 2000 },
      ].map(item => ({ ...item, display_name: "Original", lore: ["Keep lore"],
        has_preserved_nbt: true, preserved_nbt_summary: ["Keep custom data"] }));
      const children = samples.map((item, source_index) => ({ ...item, source_index }));
      await openSpecialFixture(page, { ...Object.fromEntries(samples.map(item => [item.slot, item])), 4: parent(children) }, catalog);
      const dialog = page.locator("#specialItemDialog");
      for (const contained of [false, true]) {
        if (contained) {
          await page.locator('.inventory-slot[data-slot="4"]').click();
          await page.locator("#btnSpecialItem").click();
        }
        for (const sample of samples) {
          if (contained) {
            await dialog.getByRole("button", { name: new RegExp(`^Slot ${sample.slot + 1}:`) }).click();
            await openSpecialProperties(dialog);
          } else await page.locator(`.inventory-slot[data-slot="${sample.slot}"]`).click();
          const wear = contained ? dialog.getByLabel(locale === "de" ? "Abnutzung" : "Wear", { exact: true }) : page.locator("#detailDamage");
          const variant = contained ? dialog.getByLabel(locale === "de" ? "Variante" : "Variant", { exact: true }) : page.locator("#detailDataVariant");
          const note = contained ? dialog.locator(".special-damage-note") : page.locator("#detailDamageNote");
          await expect(note).toContainText(String(sample.damage));
          if (sample.slot < 2) {
            await expect(wear).toBeHidden();
            await expect(variant).toBeHidden();
            await expect(note).toContainText(locale === "de" ? "unverändert erhalten" : "preserved unchanged");
          } else if (sample.slot === 2) {
            await expect(variant).toHaveValue("99");
            await expect(variant.locator('option[value="99"]')).toContainText(locale === "de" ? "Unbekannter Datenwert" : "Unknown data value");
            await variant.selectOption("5");
            await expect(wear).toHaveValue("5");
            if (contained) await variant.selectOption("99");
            else {
              expect(await page.evaluate(() => inventory[2].damage)).toBe(5);
              await page.locator("#btnUndo").click();
            }
            await expect(wear).toHaveValue("99");
            await expect(variant).toHaveAttribute("aria-invalid", "false");
          } else {
            await expect(wear).toBeVisible();
            await expect(wear).toHaveValue("2000");
            await expect(wear).toHaveAttribute("aria-invalid", "false");
            await expect(note).not.toContainText(locale === "de" ? "Verbleibende Haltbarkeit" : "Remaining durability");
          }
          const custom = contained ? dialog.getByLabel(locale === "de" ? "Anzeigename" : "Custom name", { exact: true }) : page.locator("#detailCustomName");
          await custom.fill(`Renamed ${sample.slot}`);
          if (contained) await dialog.locator('[data-special="accept"]').click();
          else {
            await page.locator("#detailSlotNum").click();
            expect(await page.evaluate(slot => inventory[slot], sample.slot)).toMatchObject({ ...sample, display_name: `Renamed ${sample.slot}` });
          }
        }
        if (contained) {
          // Editing children is isolated until the parent is accepted.
          expect(await page.evaluate(() => inventory[4].special_edit)).toBeUndefined();
          await dialog.locator('[data-special="accept"]').click();
          const actual = await page.evaluate(() => inventory[4].special_edit.data.items);
          expect(actual).toHaveLength(children.length);
          for (const sample of children) expect(actual.find(item => item.slot === sample.slot)).toMatchObject({ ...sample, display_name: `Renamed ${sample.slot}` });
          await page.locator("#btnUndo").click();
          expect(await page.evaluate(() => inventory[4].special_edit)).toBeUndefined();
          expect(await page.evaluate(() => inventory[4].special_item.data.items)).toEqual(children);
        }
      }
      expect(errors).toEqual([]);
    });

    test("the clicked container slot is fixed and neighbouring originals survive creation and undo", async ({ page }) => {
      const errors = collectBrowserErrors(page);
      await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
      const neighbour = { slot: 7, source_index: 0, name: "minecraft:stone", count: 17, damage: 40000,
        display_name: "Keep neighbour", lore: ["Keep metadata"], has_preserved_nbt: true };
      await openSpecialFixture(page, { 4: parent([neighbour]) }, catalog);
      await page.locator('.inventory-slot[data-slot="4"]').click();
      await page.locator("#btnSpecialItem").click();
      const dialog = page.locator("#specialItemDialog");
      await dialog.locator('[data-special-slot="5"]').click();
      await expect(dialog.locator(".special-selected-slot")).toHaveText(locale === "de" ? "Ausgewählter Slot: 6" : "Selected slot: 6");
      await dialog.locator(".special-item-name").fill("minecraft:stone");
      await dialog.getByLabel(locale === "de" ? "Menge" : "Count", { exact: true }).fill("7");
      await openSpecialProperties(dialog);
      await expect(dialog.getByLabel(locale === "de" ? "Zielslot" : "Target slot", { exact: true })).toHaveCount(0);
      await expect(dialog.getByLabel(locale === "de" ? "Abnutzung" : "Wear", { exact: true })).toBeHidden();
      await expect(dialog.getByLabel(locale === "de" ? "Variante" : "Variant", { exact: true })).toBeHidden();
      await dialog.getByLabel(locale === "de" ? "Anzeigename" : "Custom name", { exact: true }).fill("New stone");
      await dialog.locator('[data-special="accept"]').click();
      await expect(dialog.locator('[data-special-slot="5"]')).toContainText("New stone");
      await dialog.locator('[data-special="accept"]').click();
      const actual = await page.evaluate(() => inventory[4].special_edit.data.items);
      expect(actual).toHaveLength(2);
      expect(actual.find(item => item.slot === 5)).toMatchObject({ slot: 5, name: "minecraft:stone", count: 7, damage: 0, display_name: "New stone" });
      expect(actual.find(item => item.slot === 7)).toEqual(neighbour);
      await page.locator("#btnUndo").click();
      expect(await page.evaluate(() => inventory[4].special_edit)).toBeUndefined();
      expect(await page.evaluate(() => inventory[4].special_item.data.items)).toEqual([neighbour]);
      expect(errors).toEqual([]);
    });
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
  await dialog.locator('[data-special-slot="0"]').click();
  await dialog.getByLabel("Menge", { exact: true }).fill("2");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  for (const [slot, invalid, valid] of [[2, "16", "15"], [3, "1", "2"]]) {
    await dialog.getByRole("button", { name: new RegExp(`Slot ${slot}:`) }).click();
    await openSpecialProperties(dialog);
    // A forged value must still be rejected behind the registered variant picker.
    await dialog.getByLabel("Abnutzung", { exact: true }).evaluate((input, value) => {
      input.value = value; input.dispatchEvent(new Event("input", { bubbles: true }));
    }, invalid);
    await expect(dialog.getByRole("button", { name: "Übernehmen und zurück" })).toBeDisabled();
    await expect(dialog.getByRole("alert")).toContainText("Datenwert");
    await openSpecialProperties(dialog);
    await dialog.getByLabel("Variante", { exact: true }).selectOption(valid);
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
  await dialog.locator('[data-special-slot="0"]').click();
  await dialog.getByLabel("Menge", { exact: true }).fill("2");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({ ...original, count: 2 });
  await page.locator("#btnSpecialItem").click();
  await dialog.locator('[data-special-slot="0"]').click();
  await openSpecialProperties(dialog);
  const lore = dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true });
  for (const text of [Array(51).fill("Zeile").join("\n"), "x".repeat(511) + "🦜"]) {
    await lore.fill(text);
    await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Beschreibung");
    await expect(lore).toHaveValue(text);
  }
  await page.keyboard.press("Escape");
  await dialog.locator('[data-special-slot="1"]').click();
  await openSpecialProperties(dialog);
  // Programmatic input also reaches the builder's limit check; maxlength
  // alone must not permit oversized replacement text.
  await dialog.getByLabel("Anzeigename", { exact: true }).evaluate(input => {
    input.value = "y".repeat(513); input.dispatchEvent(new Event("input", {bubbles: true}));
  });
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Anzeigename");
  await page.keyboard.press("Escape");
  await dialog.locator('[data-special-slot="1"]').click();
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
    await dialog.locator('[data-special-slot="0"]').click();
    await dialog.getByRole("button", { name: "Inhalte bearbeiten", exact: true }).click();
  }
  await dialog.locator('[data-special-slot="0"]').click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await expect(dialog.getByRole("button", { name: "Übernehmen und zurück" })).toBeDisabled();
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
  const slot = dialog.locator('[data-special-slot="0"]');
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
  await dialog.locator('[data-special-slot="5"]').click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:written_book");
  await dialog.getByLabel("Menge", { exact: true }).fill("3");
  await openSpecialProperties(dialog);
  await expect(dialog.getByLabel("Zielslot", { exact: true })).toHaveCount(0);
  await expect(dialog.locator(".special-selected-slot")).toHaveText("Ausgewählter Slot: 6");
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Anzeigename", { exact: true }).fill("Mein Entwurf");
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true }).fill("Unveröffentlicht");
  await dialog.getByRole("button", { name: "Buch bearbeiten", exact: true }).click();
  await dialog.getByLabel("Titel", { exact: true }).fill("Verwerfen");
  await page.keyboard.press("Escape");
  await expect(dialog.getByLabel("Item-ID", { exact: true })).toHaveValue("minecraft:written_book");
  await expect(dialog.getByLabel("Menge", { exact: true })).toHaveValue("3");
  await openSpecialProperties(dialog);
  await expect(dialog.locator(".special-selected-slot")).toHaveText("Ausgewählter Slot: 6");
  await openSpecialProperties(dialog);
  await expect(dialog.getByLabel("Anzeigename", { exact: true })).toHaveValue("Mein Entwurf");
  await openSpecialProperties(dialog);
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
  await dialog.locator('[data-special-slot="0"]').click();
  await openSpecialProperties(dialog);
  const levels = dialog.getByLabel("Stufe", { exact: true });
  await expect(levels.first()).toHaveValue("2");
  await expect(levels.first().locator("option")).toHaveText(["1", "2", "3", "4", "5"]);
  await dialog.getByLabel("Anzeigename", { exact: true }).fill("Mein Schwert");
  await dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true }).fill("Erste Zeile\nZweite Zeile");
  await dialog.getByLabel("Abnutzung", { exact: true }).fill("37");
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844], ["narrow", 320, 568]]) {
    await page.setViewportSize({ width, height });
    await levels.first().scrollIntoViewIfNeeded();
    expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    const header = await dialog.locator("header").evaluate(el => ({ top: el.getBoundingClientRect().top, closeTop: el.querySelector("button").getBoundingClientRect().top }));
    expect(header.closeTop - header.top).toBeLessThan(30);
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/enchantments-${name}.png`, animations: "disabled" });
  }
  await levels.first().selectOption("5");
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Verzauberung hinzufügen", { exact: true }).selectOption("17");
  await expect(levels.nth(1)).toHaveValue("1");
  await levels.nth(1).selectOption("3");
  await expect(dialog.getByLabel("Anzeigename", { exact: true })).toHaveValue("Mein Schwert");
  await expect(dialog.getByLabel("Beschreibung (eine Zeile je Eintrag)", { exact: true })).toHaveValue("Erste Zeile\nZweite Zeile");
  await expect(dialog.getByLabel("Abnutzung", { exact: true })).toHaveValue("37");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0].enchantments)).toEqual([{ id: 9, lvl: 5 }, { id: 17, lvl: 3 }]);
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({
    display_name: "Mein Schwert", lore: ["Erste Zeile", "Zweite Zeile"], damage: 37,
  });
  expect(errors).toEqual([]);
});

for (const locale of ["de", "en"]) {
  test(`container layout keeps slot positions and open inputs in ${locale}`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    const sword = { slot: 0, source_index: 0, name: "minecraft:diamond_sword", count: 1, damage: 7,
      display_name: "Original", lore: ["Original lore"], enchantments: [{ id: 9, lvl: 2 }] };
    const neighbor = { slot: 8, source_index: 1, name: "minecraft:diamond", count: 12, damage: 0 };
    await openSpecialFixture(page, {
      0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
        special_item: { kind: "shulker", editable: true, data: { items: [sword, neighbor] } } },
      1: { slot: 1, name: "minecraft:bundle", count: 1, damage: 0,
        special_item: { kind: "bundle", editable: true, data: { items: [
          { slot: 0, source_index: 0, name: "minecraft:diamond", count: 8, damage: 0 },
          { slot: 1, source_index: 1, name: "minecraft:firework_rocket", count: 4, damage: 0 },
        ] } } },
      2: { ...sword, slot: 2 },
    }, {
      ench_db: { 9: { name_de: "Schärfe", name_en: "Sharpness", max_lvl: 5 }, 17: { name_de: "Haltbarkeit", name_en: "Unbreaking", max_lvl: 3 } },
      enchantment_compatibility: { item_slots: { "minecraft:diamond_sword": ["sword"] }, compatible_slots: { 9: ["sword"], 17: ["sword"] } },
    });
    await selectSetting(page, "themeSelect", locale === "en" ? "light" : "dark");
    const original = await page.evaluate(() => JSON.stringify(inventory));
    const dialog = page.locator("#specialItemDialog");
    const capture = async name => {
      if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/${name}-${locale}.png`, animations: "disabled" });
    };
    await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
    for (const [width, height] of [[1440, 1000], [1024, 768], [390, 844], [320, 568]]) {
      await page.setViewportSize({ width, height });
      const grid = dialog.locator(".special-shulker-grid");
      await expect(grid.locator("button")).toHaveCount(27);
      expect(await grid.evaluate(el => getComputedStyle(el).gridTemplateColumns.split(" ").length)).toBe(9);
      expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await capture(`shulker-${width}`);
      const last = grid.getByRole("button", { name: /^Slot 27:/ });
      await last.focus(); await last.press("Enter");
      await expect(dialog.locator(".special-selected-slot")).toContainText("27");
      await dialog.locator('footer [data-special="cancel"]').click();
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await dialog.locator('[data-special-slot="0"]').click(); await openSpecialProperties(dialog);
    const name = dialog.getByLabel(locale === "de" ? "Anzeigename" : "Custom name", { exact: true });
    const lore = dialog.locator("textarea");
    const wear = dialog.getByLabel(locale === "de" ? "Abnutzung" : "Wear", { exact: true });
    const add = dialog.getByLabel(locale === "de" ? "Verzauberung hinzufügen" : "Add enchantment", { exact: true });
    await name.fill("Entwurf 世界"); await lore.fill("Line one\nLine two"); await wear.fill("");
    await add.selectOption("17");
    await dialog.locator('[data-enchantment-id="9"] .ench-level').selectOption("4");
    for (const [width, height] of [[1440, 1000], [1024, 768], [390, 844], [320, 568]]) {
      await page.setViewportSize({ width, height });
      await expect(name).toHaveValue("Entwurf 世界"); await expect(lore).toHaveValue("Line one\nLine two");
      await expect(wear).toHaveValue(""); await expect(dialog.locator('[data-special="accept"]')).toBeDisabled();
      await expect(dialog.locator(".lore-hint")).not.toHaveText("");
      await dialog.locator(".ench-editor").scrollIntoViewIfNeeded();
      const columns = await dialog.locator(".ench-row").evaluateAll(rows => rows.map(row => ({
        level: row.querySelector(".ench-level").getBoundingClientRect().x,
        remove: row.querySelector(".ench-remove").getBoundingClientRect().x,
      })));
      expect(Math.abs(columns[0].level - columns[1].level)).toBeLessThan(1);
      expect(Math.abs(columns[0].remove - columns[1].remove)).toBeLessThan(1);
      expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await capture(`item-${width}`);
    }
    expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(original);
    await page.setViewportSize({ width: 1440, height: 1000 }); await wear.fill("11");
    await dialog.locator('[data-special="accept"]').click(); await dialog.locator('[data-special="accept"]').click();
    const children = await page.evaluate(() => inventory[0].special_edit.data.items);
    expect(children[0]).toMatchObject({ slot: 0, source_index: 0, display_name: "Entwurf 世界", lore: ["Line one", "Line two"], damage: 11,
      enchantments: [{ id: 9, lvl: 4 }, { id: 17, lvl: 1 }] });
    expect(children[1]).toEqual(neighbor);
    await page.locator('.inventory-slot[data-slot="1"]').click(); await page.locator("#btnSpecialItem").click();
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await expect(dialog.locator(".special-bundle-grid .special-slot")).toHaveCount(3);
      expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await capture(`bundle-${width}`);
    }
    await dialog.locator('footer [data-special="cancel"]').click();
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('.inventory-slot[data-slot="2"]').click();
    await page.locator("#detailCustomName").fill("Slot draft"); await page.locator("#detailLore").fill("Kept\nTogether");
    await page.locator('[data-tab="tabEnchants"]').click();
    await page.locator("#enchantsContainer .ench-add select").selectOption("17");
    await page.locator('#enchantsContainer [data-enchantment-id="9"] .ench-level').selectOption("5");
    if (process.env.MCBE_QA_SPECIAL_DIR) await page.locator("#tabEnchants").screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/ordinary-enchantments-${locale}.png` });
    await page.locator('[data-tab="tabGeneral"]').click();
    await expect(page.locator("#detailCustomName")).toHaveValue("Slot draft");
    await expect(page.locator("#detailLore")).toHaveValue("Kept\nTogether");
    expect(await page.evaluate(() => inventory[2].display_name)).toBe("Slot draft");
    expect(errors).toEqual([]);
  });
}

test("special unchanged child editing preserves unsorted original container contents", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [
      { slot: 20, source_index: 0, name: "minecraft:diamond", count: 1, damage: 0 },
      { slot: 1, source_index: 1, name: "minecraft:diamond", count: 2, damage: 0 },
    ] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.locator('[data-special-slot="20"]').click();
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
  await dialog.locator('[data-special-slot="0"]').click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.locator('[data-special-slot="0"]').click();
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
      await page.locator("#detailSlotNum").click();
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

for (const [locale, width, height] of [["de", 1440, 1000], ["en", 1024, 768], ["de", 320, 568], ["en", 390, 844]]) {
  test(`special compact item form enforces stack and bundle limits in ${locale} at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    const ids = ["bundle", "undyed_shulker_box", "diamond", "diamond_sword", "ender_pearl"];
    await openSpecialFixture(page, {
      0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0 },
      1: { slot: 1, name: "minecraft:bundle", count: 1, damage: 0, special_item: { kind: "bundle", editable: true,
        data: { items: [{ slot: 0, name: "minecraft:diamond", count: 60, damage: 0 }] } } },
      2: { slot: 2, name: "minecraft:undyed_shulker_box", count: 1, damage: 0, special_item: { kind: "shulker", editable: true,
        data: { items: [{ slot: 0, name: "minecraft:diamond", count: 65, damage: 0, source_index: 0 }] } } },
    }, {
      items_db: Object.fromEntries(ids.map(id => [`minecraft:${id}`, [id, id]])), addable_items: ids.map(id => `minecraft:${id}`),
      stack_limits: { __default__: 64, "minecraft:diamond": 64, "minecraft:ender_pearl": 16, "minecraft:diamond_sword": 1 },
    });
    const dialog = page.locator("#specialItemDialog");
    const accept = dialog.locator('[data-special="accept"]');
    const name = dialog.locator('.special-item-name');
    const count = dialog.locator('.special-item-primary input[type="number"]');
    const open = async slot => {
      await page.locator(`.inventory-slot[data-slot="${slot}"]`).focus();
      await page.keyboard.press("Shift+F10");
      await page.locator('#slotContextMenu [data-action="special"]').click();
    };
    await open(0);
    await dialog.locator(".special-slot").first().click();
    await expect(dialog.locator("h2")).toHaveText(locale === "de" ? "Item hinzufügen" : "Add item");
    const properties = dialog.locator(".special-properties");
    await expect(properties).not.toHaveAttribute("open");
    await expect(properties.locator("summary")).toHaveText(locale === "de" ? "Weitere Eigenschaften" : "More properties");
    await expect(accept).toBeDisabled();
    await name.fill("minecraft:diamond_sword");
    await expect(count).toHaveAttribute("max", "1");
    await expect(count).toHaveAttribute("readonly");
    await count.focus(); await page.keyboard.press("ArrowUp");
    await expect(count).toHaveValue("1");
    await expect(accept).toBeEnabled();
    if (process.env.MCBE_QA_SPECIAL_DIR) await page.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/compact-${locale}-${width}.png` });
    await name.fill("minecraft:diamond");
    await expect(count).not.toHaveAttribute("readonly");
    await expect(count).toHaveAttribute("max", "64");
    for (const invalid of ["65", "0", "0.5", ""]) {
      await count.fill(invalid);
      await expect(accept).toBeDisabled();
      await expect(count).toHaveValue(invalid);
    }
    await count.fill("64");
    await properties.locator("summary").focus(); await page.keyboard.press("Enter");
    await expect(properties).toHaveAttribute("open");
    await properties.locator('input[maxlength="512"]').fill("Custom name");
    if (process.env.MCBE_QA_SPECIAL_DIR) await page.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/properties-${locale}-${width}.png` });
    await properties.locator("summary").click();
    await accept.click(); await accept.click();
    expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({ count: 64, display_name: "Custom name" });

    await open(1);
    await dialog.locator(".special-slot").last().click();
    await name.fill("minecraft:ender_pearl");
    await expect(count).toHaveAttribute("max", "1");
    await expect(accept).toBeEnabled();
    await name.fill("minecraft:diamond_sword");
    await expect(count).toHaveAttribute("max", "0");
    await expect(accept).toBeDisabled();
    await name.fill("minecraft:diamond");
    await expect(count).toHaveAttribute("max", "4");
    await openSpecialProperties(dialog);
    await dialog.locator('.special-properties input[maxlength="512"]').fill("Separate stack");
    await count.fill("5"); await expect(accept).toBeDisabled();
    await count.fill("4"); await accept.click();
    await dialog.locator(".special-slot").first().click();
    await expect(count).toHaveAttribute("max", "60");
    await expect(count).toHaveValue("60");
    await expect(accept).toBeEnabled();
    await count.fill("61"); await expect(accept).toBeDisabled();
    await count.fill("60"); await accept.click(); await accept.click();
    expect(await page.evaluate(() => inventory[1].special_edit.data.items.map(item => item.count))).toEqual([60, 4]);

    await open(2); await dialog.locator(".special-slot").first().click();
    await expect(count).toHaveValue("65");
    await expect(accept).toBeEnabled();
    await count.fill("66"); await expect(accept).toBeDisabled();
    await count.fill("65"); await accept.click(); await accept.click();
    expect(await page.evaluate(() => inventory[2].special_edit)).toBeUndefined();
  });
}

test("special compact item form supports touch editing on mobile", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  try {
    const page = await context.newPage();
    await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:bundle", count: 1, damage: 0 } });
    await page.locator('.inventory-slot[data-slot="0"]').tap();
    await page.locator('.btn-toggle[data-panel="right"]').tap();
    await page.locator("#btnSpecialItem").tap();
    const dialog = page.locator("#specialItemDialog");
    await dialog.locator(".special-slot").tap();
    await dialog.locator('.special-item-name').fill("minecraft:diamond");
    await dialog.locator('.special-item-primary input[type="number"]').fill("64");
    await dialog.locator("summary").tap();
    await expect(dialog.locator(".special-properties")).toHaveAttribute("open");
    await dialog.locator('input[maxlength="512"]').fill("Touch item");
    await dialog.locator("summary").tap();
    await dialog.locator('[data-special="accept"]').tap();
    await dialog.locator('[data-special="accept"]').tap();
    await expect(dialog).toBeHidden();
    expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({ count: 64, display_name: "Touch item" });
  } finally { await context.close(); }
});

test("special contained numeric edits reject invalid input without silently clamping", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0,
    special_item: { kind: "shulker", editable: true, data: { items: [{ slot: 0, source_index: 0, name: "minecraft:diamond", count: 10, damage: 0 }] } } } },
    { max_damage: { __default__: 0, "minecraft:diamond_sword": 100 } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.locator('[data-special-slot="0"]').click();
  await dialog.getByLabel("Menge", { exact: true }).fill("65");
  await expect(dialog.getByRole("button", { name: "Übernehmen und zurück" })).toBeDisabled();
  await expect(dialog.getByRole("alert")).toContainText("Stacklimits");
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond_sword");
  await dialog.getByLabel("Menge", { exact: true }).click();
  await expect(dialog.getByLabel("Menge", { exact: true })).toHaveValue("1");
  await expect(dialog.getByLabel("Menge", { exact: true })).toHaveAttribute("readonly");
  for (const value of ["", "0.5", "101"]) {
    await openSpecialProperties(dialog);
    await dialog.getByLabel("Abnutzung", { exact: true }).fill(value);
    await expect(dialog.getByRole("button", { name: "Übernehmen und zurück" })).toBeDisabled();
    await expect(dialog.getByRole("alert")).toContainText("Datenwert");
  }
  await openSpecialProperties(dialog);
  await dialog.getByLabel("Abnutzung", { exact: true }).fill("1e1");
  await dialog.getByRole("button", { name: "Übernehmen und zurück" }).click();
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.items[0])).toMatchObject({ name: "minecraft:diamond_sword", count: 1, damage: 10 });
});

test("item numeric previews agree with the applied numeric values", async ({page}) => {
  await openSpecialFixture(page, {
    0: {slot: 0, name: "minecraft:diamond", count: 1, damage: 0},
    1: {slot: 1, name: "minecraft:diamond_sword", count: 1, damage: 0},
  }, {max_damage: {__default__: 0, "minecraft:diamond_sword": 100}});
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailCount").fill("1e1");
  await expect(page.locator("#detailPreviewMeta")).toContainText("10x");
  await page.locator("#detailSlotNum").click();
  expect(await page.evaluate(() => inventory[0].count)).toBe(10);
  await page.locator('.inventory-slot[data-slot="1"]').click();
  await page.locator("#detailDamage").fill("1e1");
  await expect(page.locator("#detailPreviewMeta")).toContainText("Abnutzung 10");
  await page.locator("#detailSlotNum").click();
  expect(await page.evaluate(() => inventory[1].damage)).toBe(10);
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
  await dialog.locator('[data-special-slot="2"]').click();
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
  await dialog.locator('[data-special-slot="2"]').click();
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

for (const [width, height] of [[2240, 1122], [390, 844], [320, 568]]) {
  test(`special editors stay centered at ${width}px`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await page.setViewportSize({ width, height });
    const names = ["bundle", "undyed_shulker_box", "written_book", "firework_rocket", "firework_star", "banner"];
    await openSpecialFixture(page, Object.fromEntries(names.map((name, slot) => [slot, { slot, name: `minecraft:${name}`, count: 1, damage: 0 }])));
    const dialog = page.locator("#specialItemDialog");
    for (const [slot, name] of names.entries()) {
      const inventorySlot = page.locator(`.inventory-slot[data-slot="${slot}"]`);
      await inventorySlot.focus();
      await page.keyboard.press("Shift+F10");
      await page.locator('#slotContextMenu [data-action="special"]').click();
      await expect(dialog).toBeVisible();
      const box = await dialog.boundingBox();
      expect(Math.abs(box.x * 2 + box.width - width)).toBeLessThanOrEqual(1);
      expect(Math.abs(box.y * 2 + box.height - height)).toBeLessThanOrEqual(1);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      await expect(dialog.locator('footer [data-special="cancel"]')).toBeInViewport();
      await expect(dialog.locator('footer [data-special="accept"]')).toBeInViewport();
      if (process.env.MCBE_QA_SPECIAL_DIR) {
        await page.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/centered-${name}-${width}.png`, animations: "disabled" });
      }
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(inventorySlot).toBeFocused();
    }
    await expect(page.locator("#btnUndo")).toBeDisabled();
    expect(errors).toEqual([]);
  });
}

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
  await dialog.locator('[data-special-slot="1"]').click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:diamond");
  await expect(dialog.getByRole("button", { name: "Übernehmen und zurück" })).toBeDisabled();
  await expect(dialog.getByRole("alert")).toContainText("nicht genügend Platz");
  await page.keyboard.press("Escape"); // Dismiss the shared item suggestions first.
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
  await dialog.locator('[data-special-slot="26"]').click();
  await dialog.getByLabel("Item-ID", { exact: true }).fill("minecraft:bundle");
  await dialog.getByRole("button", { name: "Inhalte bearbeiten" }).click();
  await dialog.locator('[data-special-slot="0"]').click();
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
  await page.locator("#detailCustomName").fill("Neuer Name"); await page.locator("#detailSlotNum").click();
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
