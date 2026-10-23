import { expect, test } from "@playwright/test";
import {
  openSpecialFixture,
  ITEM_AVAILABILITY,
  collectBrowserErrors,
  colorComponents,
  compositeColor,
  contrastRatio,
  openAppAndWaitForScan,
  openAppWithSmokeWorldScan,
  openDragFixture,
  selectSetting,
} from "./fixtures/app.mjs";
import fs from "node:fs";

test("item browser keeps keyboard focus on newly revealed results", async ({ page }) => {
  const items = Object.fromEntries(Array.from({length: 450}, (_, index) => {
    const name = `test_item_${String(index).padStart(3, "0")}`;
    return [`minecraft:${name}`, [name, name]];
  }));
  await openSpecialFixture(page, {0: {slot: 0, name: "minecraft:undyed_shulker_box", count: 1, damage: 0}}, {
    items_db: items, addable_items: Object.keys(items), stack_limits: Object.fromEntries(Object.keys(items).map(id => [id, 64])),
  });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.locator(".special-slot").first().click();
  await expect(dialog.getByLabel("Item-ID", {exact: true})).toBeFocused();
  await dialog.getByRole("button", {name: "📖 Item-Browser", exact: true}).click();
  const picker = page.locator("#itemBrowserOverlay");
  const cards = picker.locator(".browser-item");
  const more = picker.locator(".browser-load-more");
  for (const [previous, next] of [[200, 400], [400, 450]]) {
    await expect(cards).toHaveCount(previous);
    await more.focus();
    await page.keyboard.press("Enter");
    await expect(cards).toHaveCount(next);
    await expect(cards.nth(previous)).toBeFocused();
    await expect(cards.nth(previous)).toBeInViewport();
  }
  await expect(more).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect(picker).toBeHidden();
  await expect(dialog.locator(".special-item-name")).toHaveValue("minecraft:test_item_400");
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
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
  await page.locator("#bulkItemSearch").fill("stone");
  await expect(page.locator("#bulkItemAutocomplete")).toBeVisible();
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
  await expect(cardFor(/^minecraft:potion · Datenwert 0$/).locator(".item-availability-badge")).toHaveCount(0);
  await expect(cardFor(/^minecraft:black_wool_double_slab$/)).toHaveCount(0);
  await expect(cardFor(/^minecraft:bedrock$/).locator(".item-availability-badge")).toHaveAttribute(
    "title",
    "Im Kreativinventar verfügbar, im normalen Überlebensmodus nicht als Gegenstand erhältlich.",
  );
  await expect(cardFor(/^minecraft:white_cushion$/).locator(".item-availability-badge")).toHaveAttribute(
    "title",
    unreviewedDescription,
  );

  await cardFor(/^minecraft:potion · Datenwert 0$/).click();
  await expect(page.locator("#itemBrowserOverlay")).toBeHidden();
  await expect(page.locator("#detailPreviewAvailability")).toBeHidden();
  await page.locator("#detailDataVariant").selectOption("36");
  await expect(page.locator("#detailPreviewAvailability")).toBeVisible();
  await expect(page.locator("#detailPreviewAvailability")).toHaveText("Kreativ");
  await page.locator("#detailDataVariant").selectOption("0");
  await expect(page.locator("#detailPreviewAvailability")).toBeHidden();
  expect(await page.evaluate(() => inventory[0].name)).toBe("minecraft:apple");
  await page.locator("#btnApplySingle").click();
  expect(await page.evaluate(() => inventory[0].name)).toBe("minecraft:potion");

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

  // Enter selects the exact match and leaves the suggestion list closed.
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

  expect(await page.evaluate(() => inventory[0].name)).toBe("minecraft:cobblestone");
  await page.locator("#btnApplySingle").click();
  expect(await page.evaluate(() => inventory[0].name)).toBe("minecraft:dark_oak_fence");

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
  await page.locator('#confirmOk').click();
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
