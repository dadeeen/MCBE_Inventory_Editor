import { expect, test } from "@playwright/test";
import { openDragFixture, openSpecialFixture, openPlayerSwitchFixture, collectBrowserErrors } from "./fixtures/app.mjs";

const precisePlayerFields = {
  abilities: { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.123456789, vertical_fly_speed: 1 },
  effects: [{ id: 1, amplifier: 0, duration: 601, show_particles: true }],
  effects_db: { 1: ["Tempo", "Speed"] },
  protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true, has_abilities_tag: true, has_active_effects_tag: true },
};

async function showEffects(page) {
  await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
  await page.locator('[data-tab-dash="dashEffects"]').click();
}

for (const action of ["clear", "count"]) {
  test(`unchanged bulk ${action} preserves redo and changed targets undo together`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await openDragFixture(page, { stack_limits: { __default__: 64, "minecraft:stone": 64, "minecraft:carrot": 64 } });
    await page.locator('[data-slot="0"]').click();
    await page.locator("#detailCount").fill("2");
    await page.locator("#detailSlotNum").click();
    await page.locator("#btnUndo").click();
    const before = await page.evaluate(() => inventory);
    const selectPair = async (first, second) => {
      await page.locator(`[data-slot="${first}"]`).click();
      await page.locator(`[data-slot="${second}"]`).click({ modifiers: ["Control"] });
    };
    await selectPair(...(action === "clear" ? [9, 10] : [0, 2]));
    if (action === "count") await page.locator("#bulkCount").fill("1");
    const button = page.locator(action === "clear" ? "#btnBulkClear" : "#btnBulkSetCount");
    await button.click();
    expect(await page.evaluate(() => inventory)).toEqual(before);
    expect(await page.evaluate(() => isDirty)).toBe(false);
    await expect(page.locator("#btnUndo")).toBeDisabled();
    await expect(page.locator("#btnRedo")).toHaveAttribute("data-history-count", "1");
    await page.locator("#btnRedo").click();
    expect(await page.evaluate(() => inventory[0].count)).toBe(2);

    await selectPair(0, 2);
    const beforeChanged = await page.evaluate(() => inventory);
    if (action === "count") await page.locator("#bulkCount").fill("5");
    await button.click();
    const afterChanged = await page.evaluate(() => inventory);
    if (action === "clear") {
      expect(afterChanged[0]).toBeUndefined();
      expect(afterChanged[2]).toBeUndefined();
    } else {
      expect(afterChanged[0].count).toBe(5);
      expect(afterChanged[2].count).toBe(5);
    }
    await page.locator("#btnUndo").click();
    expect(await page.evaluate(() => inventory)).toEqual(beforeChanged);
    await page.locator("#btnRedo").click();
    expect(await page.evaluate(() => inventory)).toEqual(afterChanged);
    expect(errors).toEqual([]);
  });
}

test("fractional speed values remain editable and do not block saving other changes", async ({ page }) => {
  await openDragFixture(page, precisePlayerFields);
  expect(await page.evaluate(() => hasUnsavedChanges())).toBe(false);
  await showEffects(page);
  const field = page.locator("#abFlySpeed");
  await field.fill("0.2345");
  expect(await page.evaluate(() => playerAbilities.fly_speed)).toBe(0.2345);
  await field.fill("0.1235");
  await field.press("Tab");
  expect(await page.evaluate(() => playerAbilities.fly_speed)).toBe(precisePlayerFields.abilities.fly_speed);
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  await page.keyboard.press("Control+s");
  await expect(page.locator("#saveReviewOverlay")).toBeVisible();
});

for (const kind of ["ability", "effect"]) {
  test(`reverting ${kind} after another edit preserves the loaded precision`, async ({ page }) => {
    await openDragFixture(page, { ...precisePlayerFields,
      abilities: { ...precisePlayerFields.abilities, fly_speed: 0.05000000074505806 } });
    await showEffects(page);
    const original = await page.evaluate(() => ({ abilities: playerAbilities, effects: playerEffects }));
    const field = page.locator(kind === "ability" ? "#abFlySpeed" : ".eff-duration");
    const displayed = await field.inputValue();
    await field.fill(kind === "ability" ? "0.2" : "60");
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
    await showEffects(page);
    await field.fill(displayed);
    await field.press("Tab");
    expect(await page.evaluate(() => ({ abilities: playerAbilities, effects: playerEffects }))).toEqual(original);
    expect(await page.evaluate(() => inventory[1]?.name)).toBe("minecraft:stone");
  });

  test(`switching players confirms and clears incomplete ${kind} input`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const fixture = await openPlayerSwitchFixture(page);
    await showEffects(page);
    const field = page.locator(kind === "ability" ? "#abFlySpeed" : ".eff-duration");
    await field.fill("");
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    const otherPlayer = page.locator(".player-row").filter({ hasText: "Spieler B" });
    await otherPlayer.click();
    await expect(page.locator("#confirmOverlay")).toBeVisible();
    await page.locator("#confirmCancel").click();
    await expect(field).toHaveValue("");
    expect(await page.evaluate(() => currentPlayerKey)).toBe("a");
    await otherPlayer.click();
    const request = page.waitForRequest("**/api/player/load");
    await page.locator("#confirmOk").click();
    await request;
    await fixture.finishLoad(true);
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    expect(await page.evaluate(() => ({ key: currentPlayerKey, pending: hasUnsavedChanges() })))
      .toEqual({ key: "b", pending: false });
    await expect(field).not.toHaveValue("");
    expect(errors).toEqual([]);
  });
}

test("reverted ability input preserves an absent ability record", async ({ page }) => {
  await openDragFixture(page, { ...precisePlayerFields, abilities: {},
    protected_nbt: { ...precisePlayerFields.protected_nbt, has_abilities_tag: false } });
  await showEffects(page);
  const original = await page.evaluate(() => playerAbilities);
  const field = page.locator("#abFlySpeed");
  const displayed = await field.inputValue();
  await field.fill("0.2");
  await field.fill(displayed);
  await field.press("Tab");
  expect(await page.evaluate(() => playerAbilities)).toEqual(original);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("a newly added effect keeps its chosen duration when other fields change", async ({ page }) => {
  await openDragFixture(page, precisePlayerFields);
  await showEffects(page);
  await page.locator(".effect-remove").click();
  await page.locator("#btnOpenEffectPicker").click();
  await page.locator('.effect-picker-option[data-effect-id="1"]').click();
  await page.locator("#btnAddEffect").click();
  expect(await page.evaluate(() => playerEffects[0].duration)).toBe(600);
  await page.locator(".eff-level").fill("2");
  expect(await page.evaluate(() => playerEffects[0].duration)).toBe(600);
  await page.locator(".eff-duration").fill("60");
  await page.locator(".eff-duration").fill("30");
  await page.locator("#btnApplyEffects").click();
  expect(await page.evaluate(() => playerEffects[0].duration)).toBe(600);
});

test("reverting displayed name and lore preserves their original stored representation", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:diamond", count: 2, damage: 0,
    display_name: "First\nSecond", lore: ["First\r\nSecond", "Third\rFourth"] } });
  await page.locator('[data-slot="0"]').click();
  const original = await page.evaluate(() => JSON.stringify(inventory[0]));
  for (const field of [page.locator("#detailCustomName"), page.locator("#detailLore")]) {
    const displayed = await field.inputValue();
    await field.fill("Temporary");
    await field.fill(displayed);
    await page.locator("#detailSlotNum").click();
    expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(original);
    expect(await page.evaluate(() => isDirty)).toBe(false);
    await expect(page.locator("#btnUndo")).toBeDisabled();
  }
  await page.locator("#detailCustomName").fill("Temporary");
  await page.locator("#detailCount").fill("7");
  await page.locator("#detailCustomName").fill("FirstSecond");
  expect(await page.evaluate(() => inventory[0])).toMatchObject({ count: 7, display_name: "First\nSecond" });
  await page.locator("#detailCount").fill("2");
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(original);
  expect(errors).toEqual([]);
});

for (const kind of ["ability", "effect"]) {
  test(`reverted ${kind} typing leaves earlier undo and redo steps usable`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await openDragFixture(page, {
      abilities: { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.05000000074505806, vertical_fly_speed: 1 },
      effects: [{ id: 1, amplifier: 0, duration: 601, show_particles: true }],
      effects_db: { 1: ["Tempo", "Speed"] },
      protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true, has_abilities_tag: true, has_active_effects_tag: true },
    });
    await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    await page.locator('[data-tab-dash="dashEffects"]').click();
    const original = await page.evaluate(() => ({ abilities: playerAbilities, effects: playerEffects }));
    const field = page.locator(kind === "ability" ? "#abFlySpeed" : ".eff-duration");
    const displayed = await field.inputValue();
    await field.fill(kind === "ability" ? "0.2" : "60");
    await field.fill(displayed);
    await field.press("Tab");
    expect(await page.evaluate(() => ({ abilities: playerAbilities, effects: playerEffects }))).toEqual(original);
    await expect(page.locator("#btnUndo")).toHaveAttribute("data-history-count", "1");
    await page.locator("#btnUndo").click();
    expect(await page.evaluate(() => inventory[0]?.name)).toBe("minecraft:stone");
    expect(await page.evaluate(() => isDirty)).toBe(false);
    await page.locator("#btnRedo").click();
    expect(await page.evaluate(() => inventory[1]?.name)).toBe("minecraft:stone");
    expect(errors).toEqual([]);
  });
}

test("confirming unchanged player fields and correcting an empty default create no undo step", async ({ page }) => {
  await openDragFixture(page, {
    abilities: { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.05, vertical_fly_speed: 1 },
    effects: [{ id: 1, amplifier: 0, duration: 601, show_particles: true }],
    effects_db: { 1: ["Tempo", "Speed"] },
    protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true, has_abilities_tag: true, has_active_effects_tag: true },
  });
  await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
  await page.locator('[data-tab-dash="dashEffects"]').click();
  await page.locator("#btnApplyEffects").click();
  await expect(page.locator("#btnUndo")).toBeDisabled();
  await page.locator("#abFlySpeed").fill("");
  await page.locator("#btnResetAbilitySpeeds").click();
  await expect(page.locator("#abFlySpeed")).toHaveValue("0.05");
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(await page.evaluate(() => hasUnsavedChanges())).toBe(false);
});

for (const kind of ["ability", "effect"]) {
  test(`incomplete ${kind} input preserves accepted values and blocks save`, async ({ page }) => {
    let writes = 0;
    page.on("request", request => { if (request.url().endsWith("/api/player/save")) writes++; });
    await openDragFixture(page, {
      abilities: { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.25, vertical_fly_speed: 1 },
      effects: [{ id: 1, amplifier: 0, duration: 601, show_particles: true }],
      effects_db: { 1: ["Tempo", "Speed"] },
      protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true, has_abilities_tag: true, has_active_effects_tag: true },
    });
    await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    await page.locator('[data-tab-dash="dashEffects"]').click();
    const original = await page.evaluate(() => ({ abilities: playerAbilities, effects: playerEffects }));
    const field = page.locator(kind === "ability" ? "#abFlySpeed" : ".eff-duration");
    const displayed = await field.inputValue();
    await field.fill("");
    expect(await page.evaluate(() => ({ abilities: playerAbilities, effects: playerEffects }))).toEqual(original);
    expect(await page.evaluate(() => hasUnsavedChanges())).toBe(true);
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    await page.locator('[data-tab-dash="dashEffects"]').click();
    await expect(field).toHaveValue("");
    await page.keyboard.press("Control+s");
    await expect(page.locator("#saveReviewOverlay")).toBeHidden();
    await page.locator("#btnUndo").click();
    expect(await page.evaluate(() => inventory[1]?.name)).toBe("minecraft:stone");
    await field.fill(displayed);
    await page.locator("#btnUndo").click();
    expect(await page.evaluate(() => isDirty)).toBe(false);
    expect(writes).toBe(0);
  });
}

for (const kind of ["ability", "effect"]) {
  test(`${kind} follow-up edits remain undoable and save the accepted value`, async ({ page }) => {
    const requests = [];
    await page.route("**/api/player/save", async route => {
      requests.push(route.request().postDataJSON());
      await route.fulfill({ json: { success: true, player_revision: "history-follow-up" } });
    });
    await openDragFixture(page, {
      abilities: { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.25, vertical_fly_speed: 1 },
      effects: [{ id: 1, amplifier: 0, duration: 601, show_particles: true }],
      effects_db: { 1: ["Tempo", "Speed"] },
      protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true, has_abilities_tag: true, has_active_effects_tag: true },
    });
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    await page.locator('[data-tab-dash="dashEffects"]').click();
    const field = page.locator(kind === "ability" ? "#abFlySpeed" : ".eff-duration");
    const first = kind === "ability" ? "0.3" : "60";
    const second = kind === "ability" ? "0.4" : "90";
    await field.fill(first);
    await field.fill("");
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    await page.locator('[data-tab-dash="dashEffects"]').click();
    await expect(field).toHaveValue("");
    await field.fill(first);
    await page.locator("#btnUndo").click();
    await page.locator("#btnRedo").click();
    await expect(field).toHaveValue(first);
    await field.fill(second);
    await page.locator("#btnUndo").click();
    await expect(field).toHaveValue(first);
    await page.locator("#btnRedo").click();
    await expect(field).toHaveValue(second);
    await page.keyboard.press("Control+s");
    await expect(page.locator("#saveReviewOverlay")).toBeVisible();
    await page.locator("#btnSaveReviewConfirm").click();
    await expect.poll(() => requests.length).toBe(1);
    await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
    expect(kind === "ability" ? requests[0].abilities.fly_speed : requests[0].effects[0].duration)
      .toBe(kind === "ability" ? 0.4 : 1800);
    await expect(page.locator("#btnUndo")).toBeDisabled();
    expect(await page.evaluate(() => isDirty)).toBe(false);
  });
}
