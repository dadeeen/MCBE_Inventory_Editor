import { expect, test } from "@playwright/test";
import { openDragFixture, collectBrowserErrors } from "./fixtures/app.mjs";

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
