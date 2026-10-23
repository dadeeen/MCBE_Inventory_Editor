import { expect, test } from "@playwright/test";
import {
  openSpecialFixture,
  NORMAL_BASE_URL,
  collectBrowserErrors,
  selectLayout,
  openSlotSyncFixture,
  dragSlot,
} from "./fixtures/app.mjs";

for (const pending of [false, true]) {
  for (const action of ['move', 'swap', 'cut', 'paste', 'context-cut', 'context-clear', 'context-paste', 'delete', 'quick-clear']) {
    test(`slot form synchronization: ${action} with ${pending ? 'pending' : 'unchanged'} inputs`, async ({ page }) => {
      const errors = collectBrowserErrors(page);
      await openSlotSyncFixture(page);
      const slot = id => page.locator(`.main-inventory-grid [data-slot="${id}"]`);
      if (action.includes('paste')) {
        await slot(11).click();
        await page.keyboard.press('Control+c');
      }
      const selected = action === 'swap' ? 11 : 9;
      await slot(selected).click();
      if (pending) {
        await page.locator('#detailCount').fill('7');
        await page.locator('#detailCustomName').fill('Pending name');
        await page.locator('#detailLore').fill('Pending lore');
        await page.locator('#detailSlotNum').click(); // Blur without selecting/resetting the slot.
      }
      const before = await page.evaluate(() => JSON.stringify(inventory));
      if (action === 'move' || action === 'swap') await dragSlot(page, slot(9), slot(action === 'move' ? 10 : 11));
      else if (action.startsWith('context-')) {
        await slot(9).click({ button: 'right' });
        await page.locator(`#slotContextMenu [data-action="${action.slice(8)}"]`).click();
      } else if (action === 'quick-clear') await page.locator('#btnQuickClearSlot').click();
      else {
        await slot(selected).focus();
        await page.keyboard.press({ cut: 'Control+x', paste: 'Control+Shift+v', delete: 'Delete' }[action]);
      }
      if (pending) {
        expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
        await expect(page.locator('#detailCount')).toHaveValue('7');
        await expect(page.locator('#detailCustomName')).toHaveValue('Pending name');
        await expect(page.locator('#detailLore')).toHaveValue('Pending lore');
        expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(true);
        await expect(page.locator('.toast').filter({ hasText: 'Bitte übernimm zuerst' }).last()).toBeVisible();
        await page.locator('#btnApplySingle').click();
        expect(await page.evaluate(id => inventory[id].display_name, selected)).toBe('Pending name');
        expect(await page.evaluate(id => inventory[id].count, selected)).toBe(7);
      } else {
        expect(await page.evaluate(() => JSON.stringify(inventory))).not.toBe(before);
        const after = await page.evaluate(() => JSON.stringify(inventory));
        const currentName = await page.evaluate(id => inventory[id]?.name || '', selected);
        await expect(page.locator('#detailItemSearch')).toHaveValue(currentName);
        expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
        await expect(page.locator('#btnApplySingle')).toBeDisabled();
        expect(await page.evaluate(() => inventory)).toEqual(JSON.parse(after));
      }
      expect(errors).toEqual([]);
    });
  }
}

test("slot form synchronization refreshes a semantically unchanged catalog variant", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 4,
    special_item: { kind: "banner", editable: true, data: { patterns: [] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.evaluate(() => slotDetailController.selectDetailItemVariant({ damage: 4, banner_type: 0 }));
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
  await expect(page.locator("#btnApplySingle")).toBeDisabled();
  await page.evaluate(() => { inventory[0].count = 2; updateGridVisuals(); });
  await expect(page.locator("#detailCount")).toHaveValue("2");
  await expect(page.locator("#detailFormError")).toBeHidden();
  await expect(page.locator("#btnApplySingle")).toBeDisabled();
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
});

test('slot form synchronization preserves unrelated drafts and rejects a stale source', async ({ page }) => {
  await openSlotSyncFixture(page);
  const slot = id => page.locator(`.main-inventory-grid [data-slot="${id}"]`);
  await slot(9).click();
  await page.locator('#detailCustomName').fill('Keep this draft');
  await page.locator('#detailLore').fill('Two\nlines');
  await dragSlot(page, slot(11), slot(12));
  expect(await page.evaluate(() => inventory[12]?.count)).toBe(5);
  await page.locator('#gridSearch').fill('stone');
  await expect(page.locator('#detailCustomName')).toHaveValue('Keep this draft');
  await expect(page.locator('#detailLore')).toHaveValue('Two\nlines');
  // A missed mutation notification must still never let an old form overwrite a newer item.
  await page.evaluate(() => { inventory[9] = { slot: 9, name: 'minecraft:diamond', count: 4, damage: 0 }; updateGridVisuals(); });
  await expect(page.locator('#btnApplySingle')).toBeDisabled();
  expect(await page.evaluate(() => inventory[9])).toEqual({ slot: 9, name: 'minecraft:diamond', count: 4, damage: 0 });
  await expect(page.locator('#detailCustomName')).toHaveValue('Keep this draft');
  await expect(page.locator('#detailLore')).toHaveValue('Two\nlines');
  await expect(page.locator('#detailFormError')).toContainText('Der Inhalt dieses Slots wurde inzwischen geändert');
});

test('slot form synchronization protects drafts during undo redo and context selection', async ({ page }) => {
  await openSlotSyncFixture(page);
  const slot = id => page.locator(`.main-inventory-grid [data-slot="${id}"]`);
  await slot(9).click();
  await page.locator('#detailCount').fill('13');
  await page.locator('#btnApplySingle').click();
  await page.locator('#btnUndo').click();
  expect(await page.evaluate(() => inventory[9].count)).toBe(12);
  await page.locator('#detailCount').fill('7');
  await page.locator('#btnRedo').click();
  expect(await page.evaluate(() => inventory[9].count)).toBe(12);
  await expect(page.locator('#detailCount')).toHaveValue('7');
  await slot(11).click({ button: 'right' });
  await page.locator('#slotContextMenu [data-action="copy"]').click();
  expect(await page.evaluate(() => selectedSlots)).toEqual([9]);
  await expect(page.locator('#detailCount')).toHaveValue('7');
  await page.locator('#btnApplySingle').click();
  await page.locator('#detailCount').fill('8');
  await page.locator('#btnUndo').click();
  expect(await page.evaluate(() => inventory[9].count)).toBe(7);
  await expect(page.locator('#detailCount')).toHaveValue('8');
});

test('slot form synchronization also refreshes and protects the ender chest editor', async ({ page }) => {
  await openSlotSyncFixture(page);
  const ender = page.locator('.inventory-slot[data-ender-slot="0"]');
  await ender.click();
  await page.keyboard.press('Control+x');
  await expect(page.locator('#detailItemSearch')).toHaveValue('');
  await page.keyboard.press('Control+Shift+v');
  await expect(page.locator('#detailCount')).toHaveValue('3');
  await page.locator('#detailCount').fill('8');
  await page.keyboard.press('Control+Shift+v');
  expect(await page.evaluate(() => enderChestInventory[0].count)).toBe(3);
  await expect(page.locator('#detailCount')).toHaveValue('8');
  await page.locator('#btnApplySingle').click();
  expect(await page.evaluate(() => enderChestInventory[0].count)).toBe(8);
});

for (const locale of ['de', 'en']) {
  test(`pending form guards: slot navigation requires explicit discard (${locale})`, async ({ page }) => {
    await page.context().addCookies([{ name: 'mcbe_locale', value: locale, url: NORMAL_BASE_URL }]);
    await openSlotSyncFixture(page);
    if (locale === 'en') await page.setViewportSize({ width: 1366, height: 768 });
    const slot = id => page.locator(`.inventory-slot[data-slot="${id}"]`);
    await slot(9).click();
    await page.locator('#detailCount').fill('8');
    await page.locator('#btnApplySingle').click();
    await page.locator('#detailCustomName').fill('Pending name');
    const before = await page.evaluate(() => JSON.stringify(inventory));
    const actions = [
      () => slot(11).click(),
      () => slot(11).click({ modifiers: ['Control'] }),
      () => slot(9).click(),
      () => page.locator('[data-ender-slot="0"]').click(),
      () => page.locator('#btnCloseDetail').click(),
      () => page.keyboard.press('Escape'),
    ];
    for (const action of actions) {
      await action();
      await expect(page.locator('#confirmOverlay')).toBeVisible();
      await expect(page.locator('#confirmCancel')).toHaveText(locale === 'en' ? 'Keep editing' : 'Weiter bearbeiten');
      await page.keyboard.press('Escape');
      await expect(page.locator('#confirmOverlay')).toBeHidden();
      await expect(page.locator('#detailCustomName')).toHaveValue('Pending name');
      expect(await page.evaluate(() => selectedSlots)).toEqual([9]);
      expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
      await expect(page.locator('#btnUndo')).toBeEnabled();
    }
    // Keyboard focus can move independently of the selected editor.
    await slot(11).focus();
    await page.keyboard.press('Delete');
    expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
    await expect(page.locator('#detailCustomName')).toHaveValue('Pending name');
    await page.locator('[data-ender-slot="0"]').click();
    await page.locator('#confirmOk').click();
    await expect(page.locator('#detailCount')).toHaveValue('3');
    expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(before);
    await page.locator('#detailCustomName').fill('Ender draft');
    await page.locator('#btnCloseDetail').click();
    await page.locator('#confirmCancel').click();
    await expect(page.locator('#detailCustomName')).toHaveValue('Ender draft');
    await page.locator('#btnCloseDetail').click();
    await page.locator('#confirmOk').click();
    expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
    await page.locator('#btnUndo').click();
    expect(await page.evaluate(() => inventory[9].count)).toBe(12);
  });
}

for (const form of ['slot', 'stats']) {
  test(`pending form guards: save waits for ${form} inputs to be applied`, async ({ page }) => {
    await page.route('**/api/server_status', route => route.fulfill({ json: {
      success: true, server_status: { status: 'offline' }, write_gate: { allowed: true, read_allowed: true },
    } }));
    await openSlotSyncFixture(page);
    const saves = [];
    await page.route('**/api/player/save', async route => {
      saves.push(route.request().postDataJSON());
      const savedItems = await page.evaluate(() => ({ inventory, ender_chest: enderChestInventory }));
      await route.fulfill({ json: { success: true, write_committed: true, player_revision: 'after-save', saved_items: savedItems } });
    });
    await page.locator('[data-slot="9"]').click();
    await page.locator('#detailCount').fill('8');
    await page.locator('#btnApplySingle').click();
    if (form === 'slot') {
      await page.locator('#detailCount').fill('7');
      await page.locator('#detailCustomName').fill('Pending name');
    } else {
      await selectLayout(page, 'studio');
      await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
      await page.locator('#statHealth').fill('13');
    }
    await page.keyboard.press('Control+s');
    await expect(page.locator('.toast').filter({ hasText: 'Bitte übernimm zuerst' }).last()).toBeVisible();
    await expect(page.locator('#btnSaveReviewConfirm')).toBeHidden();
    expect(saves).toEqual([]);
    await expect(page.locator('#btnUndo')).toBeEnabled();
    if (form === 'slot') {
      await expect(page.locator('#detailCount')).toHaveValue('7');
      await expect(page.locator('#detailCustomName')).toHaveValue('Pending name');
      expect(await page.evaluate(() => inventory[9].count)).toBe(8);
      await page.locator('#btnApplySingle').click();
    } else {
      await expect(page.locator('#statHealth')).toHaveValue('13');
      expect(await page.evaluate(() => playerStats.health)).toBe(20);
      await page.locator('#btnApplyStats').click();
    }
    await page.keyboard.press('Control+s');
    await page.locator('#btnSaveReviewConfirm').click();
    await expect.poll(() => saves.length).toBe(1);
    await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
    expect(await page.evaluate(() => hasUnsavedChanges())).toBe(false);
    if (form === 'slot') expect(saves[0].inventory.find(item => item.slot === 9)).toMatchObject({ count: 7, display_name: 'Pending name' });
    else expect(saves[0].stats).toMatchObject({ health: 13 });
  });
}

test('pending form guards: undo and redo retain unaccepted player stats', async ({ page }) => {
  await openSlotSyncFixture(page);
  await page.locator('[data-slot="9"]').click();
  await page.locator('#detailCount').fill('8');
  await page.locator('#btnApplySingle').click();
  await selectLayout(page, 'studio');
  await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
  const health = page.locator('#statHealth');
  const original = await health.inputValue();
  for (const [action, count, restored] of [['Undo', 8, 12], ['Redo', 12, 8]]) {
    await health.fill('13');
    await page.locator(`#btn${action}`).click();
    await expect(health).toHaveValue('13');
    expect(await page.evaluate(() => statsFormController.hasPendingChanges())).toBe(true);
    expect(await page.evaluate(() => inventory[9].count)).toBe(count);
    expect(await page.evaluate(() => playerStats.health)).toBe(20);
    await health.fill(original);
    await page.locator(`#btn${action}`).click();
    expect(await page.evaluate(() => inventory[9].count)).toBe(restored);
  }
});

test('pending form guards: context and container search cannot discard a slot draft implicitly', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1280 });
  await openSpecialFixture(page, { 0: { slot: 0, name: 'minecraft:undyed_shulker_box', count: 1, damage: 0,
    display_name: 'Original', special_item: { kind: 'shulker', editable: true, data: { items: [
      { slot: 3, source_index: 0, name: 'minecraft:diamond', count: 7, damage: 0 },
    ] } } } });
  const dialog = page.locator('#specialItemDialog');
  const slot = page.locator('[data-slot="0"]');
  await slot.click();
  for (const source of ['context', 'search']) {
    await page.locator('#detailCustomName').fill('Pending name');
    const open = async () => {
      if (source === 'context') {
        await slot.click({ button: 'right' });
        await page.locator('#slotContextMenu [data-action="special"]').click();
      } else {
        await page.locator('#gridSearch').fill('diamond');
        await page.locator('#gridSearchResults button').click();
      }
    };
    await open();
    await page.locator('#confirmCancel').click();
    await expect(dialog).toBeHidden();
    await expect(page.locator('#detailCustomName')).toHaveValue('Pending name');
    await open();
    await page.locator('#confirmOk').click();
    await expect(dialog).toBeVisible();
    if (source === 'search') await expect(dialog.getByLabel('Menge', { exact: true })).toHaveValue('7');
    await dialog.locator('footer [data-special="cancel"]').click();
    if (source === 'search') await dialog.locator('footer [data-special="cancel"]').click();
    await expect(dialog).toBeHidden();
    await expect(page.locator('#detailCustomName')).toHaveValue('Original');
    expect(await page.evaluate(() => isDirty)).toBe(false);
  }
});

test('special editor returns keyboard focus to the container slot being edited', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSpecialFixture(page, { 0: { slot: 0, name: 'minecraft:undyed_shulker_box', count: 1, damage: 0,
    special_item: { kind: 'shulker', editable: true, data: { items: [
      { slot: 26, source_index: 0, name: 'minecraft:diamond', count: 7, damage: 0 },
    ] } } } });
  const rootSlot = page.locator('.inventory-slot[data-slot="0"]');
  await rootSlot.focus(); await rootSlot.press('Shift+F10');
  await page.locator('#slotContextMenu [data-action="special"]').press('Enter');
  const dialog = page.locator('#specialItemDialog');
  const childSlot = dialog.getByRole('button', { name: /^Slot 27:/ });
  await childSlot.focus(); await childSlot.press('Enter');
  await dialog.getByLabel('Menge', { exact: true }).fill('8');
  await dialog.locator('[data-special="accept"]').press('Enter');
  await expect(childSlot).toBeFocused();
  await expect(childSlot).toBeInViewport();
  await childSlot.press('Enter');
  await expect(dialog.getByLabel('Menge', { exact: true })).toHaveValue('8');
  await page.keyboard.press('Escape');
  await expect(childSlot).toBeFocused();
  await expect(childSlot).toBeInViewport();
  await page.keyboard.press('Escape');
  await expect(rootSlot).toBeFocused();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
});

test('special editor keeps keyboard focus with reordered and removed book pages', async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: 'minecraft:written_book', count: 1, damage: 0,
    special_item: { kind: 'book', editable: true, data: { title: 'Focus test', author: 'Author',
      pages: [{ text: 'First' }, { text: 'Second' }, { text: 'Third' }] } } } });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator('#btnSpecialItem').click();
  const dialog = page.locator('#specialItemDialog');
  const pages = dialog.locator('.special-card');
  await pages.nth(1).getByRole('button', { name: 'Nach oben', exact: true }).press('Enter');
  await expect(pages.nth(0).locator('textarea')).toHaveValue('Second');
  await expect(pages.nth(0).getByRole('button', { name: 'Nach unten', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(pages.nth(1).locator('textarea')).toHaveValue('Second');
  await expect(pages.nth(1).getByRole('button', { name: 'Nach unten', exact: true })).toBeFocused();
  await pages.nth(1).getByRole('button', { name: 'Entfernen', exact: true }).press('Enter');
  await expect(pages).toHaveCount(2);
  await expect(pages.nth(1).getByRole('button', { name: 'Entfernen', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(pages).toHaveCount(1);
  await expect(pages.nth(0).getByRole('button', { name: 'Entfernen', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(dialog.getByRole('button', { name: 'Seite hinzufügen', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(pages.nth(0).locator('textarea')).toBeFocused();
  await pages.nth(0).locator('textarea').fill('Replacement');
  await dialog.locator('[data-special="accept"]').press('Enter');
  expect(await page.evaluate(() => inventory[0].special_edit.data.pages)).toEqual([{ text: 'Replacement' }]);
});

test('write protection disables and restores every enchantment action', async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: 'minecraft:diamond_sword', count: 1, damage: 0,
    enchantments: [{ id: 9, lvl: 2 }] } }, {
    ench_db: { 9: { name_de: 'Schärfe', name_en: 'Sharpness', max_lvl: 5 }, 17: { name_de: 'Haltbarkeit', name_en: 'Unbreaking', max_lvl: 3 } },
    enchantment_compatibility: { item_slots: { 'minecraft:diamond_sword': ['sword'] }, compatible_slots: { 9: ['sword'], 17: ['sword'] } },
  });
  await page.locator('[data-slot="0"]').click();
  await page.locator('[data-tab="tabEnchants"]').click();
  const remove = page.locator('#enchantsContainer .ench-remove');
  const level = page.locator('#enchantsContainer .ench-level');
  const add = page.locator('#enchantsContainer .ench-add select');
  await expect(remove).toBeEnabled();
  let allowed = false;
  await page.route('**/api/server_status', route => route.fulfill({ json: {
    success: true, server_status: { status: allowed ? 'offline' : 'online' },
    write_gate: { allowed, read_allowed: true, reason: allowed ? '' : 'Server läuft noch. Bitte Server stoppen.' },
  } }));
  await page.evaluate(() => refreshServerStatus());
  for (const control of [level, add, remove]) await expect(control).toBeDisabled();
  await expect(remove).toHaveAttribute('title', 'Server läuft noch. Bitte Server stoppen.');
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(false);
  allowed = true;
  await page.evaluate(() => refreshServerStatus());
  for (const control of [level, add, remove]) await expect(control).toBeEnabled();
  await remove.press('Enter');
  expect(await page.evaluate(() => slotDetailController.hasPendingChanges())).toBe(true);
  await page.locator('#btnApplySingleEnch').click();
  expect(await page.evaluate(() => inventory[0].enchantments)).toEqual([]);
});
