import { expect, test } from "@playwright/test";
import { openDragFixture, collectBrowserErrors, selectLayout } from "./fixtures/app.mjs";

for (const draft of ["", "-", "1e"]) {
  test(`stats apply preserves values with ${draft ? `unfinished ${draft}` : "empty"} number inputs`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await openDragFixture(page, {
      stats: { pos: [1, 64, 2], dimension_id: 0, health: 7, xp_level: 42, xp_progress: 0.5,
        food_level: 6, food_saturation: 3, gamemode: 0 },
    });
    await selectLayout(page, "studio");
    await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
    for (const [id, key] of [["statHealth", "health"], ["statXpLevel", "xp_level"], ["statXpProgress", "xp_progress"],
      ["statFoodLevel", "food_level"], ["statFoodSaturation", "food_saturation"]]) {
      const before = await page.evaluate(() => JSON.stringify(playerStats));
      const input = page.locator(`#${id}`);
      await input.fill("");
      if (draft) {
        await input.pressSequentially(draft);
        expect(await input.evaluate(node => node.validity.badInput)).toBe(true);
      }
      await page.locator("#btnApplyStats").click();
      expect(await page.evaluate(() => JSON.stringify(playerStats))).toBe(before);
      expect(await page.evaluate(() => statsFormController.hasPendingChanges())).toBe(true);
      await expect(input).toBeFocused();
      await expect(page.locator(".toast").filter({ hasText: "Bitte eine gültige Zahl eingeben." }).last()).toBeVisible();
      await input.fill("10");
      await page.locator("#btnApplyStats").click();
      expect(await page.evaluate(key => playerStats[key], key)).toBe(key === "xp_progress" ? 0.1 : 10);
      expect(await page.evaluate(() => statsFormController.hasPendingChanges())).toBe(false);
    }
    expect(errors).toEqual([]);
  });
}

for (const action of ["fill", "count"]) {
  test(`bulk ${action} honors valid exponent notation in number inputs`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await openDragFixture(page, {
      addable_items: ["minecraft:stone", "minecraft:carrot", "minecraft:iron_helmet"],
      stack_limits: { __default__: 64, "minecraft:stone": 64, "minecraft:carrot": 64 },
    });
    await page.locator('[data-slot="0"]').click();
    await page.locator('[data-slot="2"]').click({ modifiers: ["Control"] });
    if (action === "fill") await page.locator("#bulkItemSearch").fill("minecraft:stone");
    await page.locator("#bulkCount").fill("1e1");
    await page.locator(action === "fill" ? "#btnBulkFill" : "#btnBulkSetCount").click();
    expect(await page.evaluate(() => [inventory[0].count, inventory[2].count])).toEqual([10, 10]);
    await page.locator("#btnUndo").click();
    expect(await page.evaluate(() => [inventory[0].count, inventory[2].count])).toEqual([1, 1]);
    expect(errors).toEqual([]);
  });
}

test("bulk fill keeps selected items when quantity or damage is unfinished", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openDragFixture(page, {
    addable_items: ["minecraft:stone", "minecraft:carrot"],
    stack_limits: { "minecraft:stone": 64, "minecraft:carrot": 64 },
  });
  await page.locator('[data-slot="0"]').click();
  await page.locator('[data-slot="2"]').click({ modifiers: ["Control"] });
  await page.locator("#bulkItemSearch").fill("minecraft:stone");
  const before = await page.evaluate(() => JSON.stringify(inventory));
  for (const [id, valid] of [["bulkCount", "10"], ["bulkDamage", "0"]]) {
    const input = page.locator(`#${id}`);
    for (const draft of ["", "1e"]) {
      await input.fill("");
      if (draft) await input.pressSequentially(draft);
      await page.locator("#btnBulkFill").click();
      expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
      expect(await page.evaluate(() => selectedSlots)).toEqual([0, 2]);
      await expect(page.locator(".toast").filter({ hasText: "Bitte eine gültige Zahl eingeben." }).last()).toBeVisible();
    }
    await input.fill(valid);
  }
  await page.locator("#btnBulkFill").click();
  expect(await page.evaluate(() => [inventory[0].count, inventory[2].count])).toEqual([10, 10]);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
  expect(errors).toEqual([]);
});

test("effect edits honor exponent notation without truncating level or duration", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openDragFixture(page, {
    effects: [{ id: 1, amplifier: 0, duration: 601, show_particles: true }],
    effects_db: { 1: ["Tempo", "Speed"] },
    protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true,
      has_abilities_tag: true, has_active_effects_tag: true },
  });
  await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
  await page.locator('[data-tab-dash="dashEffects"]').click();
  await page.locator(".eff-level").fill("1e2");
  expect(await page.evaluate(() => playerEffects[0])).toMatchObject({ amplifier: 99, duration: 601 });
  await page.locator(".eff-duration").fill("1e5");
  expect(await page.evaluate(() => playerEffects[0])).toMatchObject({ amplifier: 99, duration: 2_000_000 });
  expect(errors).toEqual([]);
});
