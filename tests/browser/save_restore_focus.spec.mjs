import { expect, test } from "@playwright/test";
import {
  collectBrowserErrors,
  openDragFixture,
  captureBrowserEvidence,
  selectLayout,
} from "./fixtures/app.mjs";

for (const draft of ["stats", "slot", "ability", "effect"]) {
  test(`external-change reload confirms an uncommitted ${draft} draft`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const stored = { revision: "draft-revision", fingerprint: "draft-world" };
    await page.route("**/api/world/presence", route => route.fulfill({ json: {
      success: true, other_sessions: 0, world_fingerprint: stored.fingerprint,
      player_revision: stored.revision,
    } }));
    let loads = 0;
    await openDragFixture(page, () => {
      loads++;
      return { player_revision: stored.revision, world_fingerprint: stored.fingerprint,
        stack_limits: { __default__: 64, "minecraft:stone": 64 },
        abilities: { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.05, vertical_fly_speed: 1 },
        effects: [{ id: 1, amplifier: 0, duration: 600, show_particles: true }],
        effects_db: { 1: ["Tempo", "Speed"] },
        protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true,
          has_abilities_tag: true, has_active_effects_tag: true } };
    });
    let field;
    if (draft === "stats") {
      await selectLayout(page, "studio");
      await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
      field = page.locator("#statHealth");
    } else if (draft === "slot") {
      await page.locator('[data-slot="0"]').click();
      field = page.locator("#detailCount");
    } else {
      await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
      await page.locator('[data-tab-dash="dashEffects"]').click();
      field = page.locator(draft === "ability" ? "#abFlySpeed" : ".eff-duration");
    }
    const original = await field.inputValue();
    const pending = draft === "stats" ? "7" : "";
    await field.fill(pending);
    expect(await page.evaluate(() => ({ dirty: isDirty, pending: hasUnsavedChanges() })))
      .toEqual({ dirty: false, pending: true });
    stored.revision = "external-revision";
    stored.fingerprint = "external-world";
    await page.evaluate(() => updateWorldPresence());
    await page.evaluate(() => updateWorldPresence());
    const reload = page.locator(".toast-error").getByRole("button", { name: "Spieler neu laden" });
    await reload.click();
    await expect(page.locator("#confirmOverlay")).toBeVisible();
    await page.locator("#confirmCancel").click();
    await expect(field).toHaveValue(pending);
    expect(loads).toBe(1);
    await page.locator("#statusStackButton").click();
    await page.locator("#statusStackPanel").getByRole("button", { name: "Spieler neu laden" }).click();
    await page.locator("#confirmOk").click();
    await expect.poll(() => loads).toBe(2);
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    if (draft === "slot") await page.locator('[data-slot="0"]').click();
    await expect(field).toHaveValue(original);
    expect(await page.evaluate(() => hasUnsavedChanges())).toBe(false);
    expect(errors).toEqual([]);
  });
}

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
  await page.keyboard.press("Tab");
  await expect(page.locator("#btnSaveReviewClose")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator("#btnSaveReviewConfirm")).toBeFocused();
  await expect(page.getByRole("dialog", { name: "Änderungsübersicht", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#saveReviewOverlay")).toBeHidden();
  await expect(slot).toBeFocused();
  expect(saves).toBe(0);
  // A blocked review still has a reachable initial control and skips its
  // disabled save button while cycling through the available actions.
  await page.evaluate(() => { void openSaveReview(buildChangeSummary(), { errors: 1 }); });
  await expect(page.locator("#btnSaveReviewConfirm")).toBeDisabled();
  await expect(page.locator("#btnSaveReviewCancel")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#btnSaveReviewClose")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator("#btnSaveReviewCancel")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(slot).toBeFocused();
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
