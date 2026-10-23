import { expect, test } from "@playwright/test";
import {
  NORMAL_BASE_URL,
  collectBrowserErrors,
  openDragFixture,
  openChangeHistory,
  captureBrowserEvidence,
  selectSetting,
  selectLayout,
} from "./fixtures/app.mjs";

test("dragging an item icon moves and swaps the whole stack in the desktop host", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1440, height: 1280 });
  const iconUrl = "/api/icons/drag-fixture";
  await page.route("**/api/icons/drag-fixture", route => route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><path fill="#aaa" d="M0 0h32v32H0z"/></svg>',
  }));
  await page.route("**/api/icons/status*", route => route.fulfill({ json: {
    success: true, count: 2, sources: [], warnings: [],
    icons: { "minecraft:stone": { url: iconUrl }, "minecraft:carrot": { url: iconUrl } },
  } }));
  await openDragFixture(page, { inventory: {
    9: { slot: 9, name: "minecraft:stone", count: 12, damage: 0, custom_name: "Keep me" },
    11: { slot: 11, name: "minecraft:carrot", count: 5, damage: 0 },
  } });
  await page.evaluate(async () => {
    await loadLocalIconIndex({ rescan: false });
    // pywebview's default host cancels image/link drags. Item images must defer
    // to the draggable slot so a drag from the icon behaves like its border.
    document.addEventListener("dragstart", event => {
      if (["IMG", "A"].includes(event.target.tagName)) event.preventDefault();
    });
  });
  const slot = id => page.locator(`.main-inventory-grid [data-slot="${id}"]`);
  const icon = id => slot(id).locator(".item-visual img");
  await expect(icon(9)).toBeVisible();
  await expect.poll(() => icon(9).evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  const original = await page.evaluate(() => JSON.stringify(inventory));
  await icon(9).dragTo(slot(10));
  await expect.poll(() => page.evaluate(() => inventory[10]?.name)).toBe("minecraft:stone");
  expect(await page.evaluate(() => inventory[9])).toBeUndefined();
  expect(await page.evaluate(() => inventory[10])).toMatchObject({ count: 12, custom_name: "Keep me", source_slot: 9 });
  await icon(10).dragTo(icon(11));
  expect(await page.evaluate(() => inventory[10])).toMatchObject({ name: "minecraft:carrot", count: 5, source_slot: 11 });
  expect(await page.evaluate(() => inventory[11])).toMatchObject({ name: "minecraft:stone", count: 12, custom_name: "Keep me", source_slot: 9 });
  await page.locator("#btnUndo").click();
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => JSON.stringify(inventory))).toBe(original);
  expect(errors).toEqual([]);
});

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
    await expect(page.locator("#btnApplySingle")).toBeDisabled();
    await expect(page.locator("#detailFormError")).toContainText(message);
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
