import { expect, test } from "@playwright/test";
import { NORMAL_BASE_URL, captureBrowserEvidence, collectBrowserErrors, openAppWithEmptyWorldScan } from "./fixtures/app.mjs";

const readyIcons = { success: true, icons: {}, count: 1, sources: [], warnings: [], missing_banner_patterns: [] };
const initialFailure = { success: false, error: "HTTP 503: Icon-Status vorübergehend nicht erreichbar" };

for (const [cacheState, hint] of [["damaged", "Einige Vanilla-Icons fehlen"], ["stale", "Icon-Zuordnung muss geprüft werden"]]) {
  test(`setup repairs a ${cacheState} vanilla cache with a nonzero count and a complete banner list`, async ({page}) => {
    let state = cacheState, downloads = 0;
    const localIcons = () => ({...readyIcons, vanilla_cache: {state}});
    await page.route("**/api/item-db/status", route => route.fulfill({json: {success: true, item_db: {status: "ok", verification: {verified: true}}}}));
    await page.route("**/api/icons/status*", route => {
      expect(new URL(route.request().url()).searchParams.get("world_path")).toBe("");
      return route.fulfill({json: localIcons()});
    });
    await page.route("**/api/icons/vanilla/update", route => {
      downloads++;
      state = "current";
      return route.fulfill({json: {...localIcons(), icon_update: {already_current: false}}});
    });
    await openAppWithEmptyWorldScan(page);
    await page.locator("#btnSetupTodoBanner").click();
    const row = page.locator('[data-first-run-todo="icons"]');
    await expect(row).toContainText(hint);
    await expect(row).not.toHaveClass(/is-done/);
    expect(downloads).toBe(0);
    await row.getByRole("button", {name: "Icons abgleichen"}).click();
    await expect(row).toHaveClass(/is-done/);
    expect(downloads).toBe(1);
  });
}

test("a saved partial update keeps its reload warning until a new receipt verifies the database", async ({page}) => {
  const restart = "Der laufende Editor konnte den neuen Katalog nicht laden.";
  let updates = 0, readsAfterWrite = 0, repaired = false;
  await page.route("**/api/icons/status*", route => route.fulfill({json: readyIcons}));
  await page.route("**/api/item-db/status", route => {
    if (updates && ++readsAfterWrite === 1) return route.fulfill({json: {success: false, error: "Status vorübergehend nicht verfügbar."}});
    const verified = !updates || repaired;
    return route.fulfill({json: {success: true, item_db: {status: "ok", verification: {verified}, reload_warning: verified ? "" : restart}}});
  });
  await page.route("**/api/update_db", route => {
    updates++;
    return route.fulfill({json: {success: false, outcome: "partial", update_committed: true, reloaded: false, reload_warning: restart,
      summary: {status: "incomplete", blocked: [{section: "effects", reason: "Effect registry missing"}]}}});
  });
  await openAppWithEmptyWorldScan(page);
  await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
  await page.locator('[data-tab-dash="dashUpdate"]').click();
  await page.locator("#btnUpdateDbApply").click();
  await page.locator("#confirmOk").click();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await page.locator('.app-section-nav [data-workflow-view="world"]').click();
  await page.locator("#btnSetupTodoBanner").click();
  const row = page.locator('[data-first-run-todo="item_db"]');
  await expect(row).not.toHaveClass(/is-done/);
  await expect(row.locator('[data-role="details-content"]')).toContainText(restart);
  const retry = row.getByRole("button", {name: "Status erneut prüfen"});
  await retry.click();
  await expect(row.locator('[data-role="state"]')).toHaveText("Bitte den Editor neu starten.");
  repaired = true;
  await retry.click();
  await expect(row.locator('[data-role="state"]')).toHaveText("Erledigt.");
  await expect(row).not.toContainText(restart);
  expect(updates).toBe(1);
});

async function prepareStatusRecovery(page, responses, { width, locale }) {
  await page.setViewportSize({ width, height: 900 });
  await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
  const browserErrors = collectBrowserErrors(page);
  let verified = false, statusReads = 0, iconDownloads = 0;
  const itemDb = () => ({ status: "ok", verification: { verified }, counts: { items: 1623 } });
  await page.route("**/api/item-db/status", route => route.fulfill({ json: { success: true, item_db: itemDb() } }));
  await page.route("**/api/update_db", route => {
    verified = true;
    return route.fulfill({ json: {
      success: true, returncode: 0, update_committed: true, reloaded: true,
      item_db: itemDb(), output: "Alles aktuell, keine Änderungen.",
    } });
  });
  await page.route("**/api/icons/status*", route => {
    const response = responses[Math.min(statusReads++, responses.length - 1)];
    return route.fulfill({ status: response.success ? 200 : 503, json: response });
  });
  await page.route("**/api/icons/vanilla/update", route => {
    iconDownloads++;
    return route.fulfill({ json: readyIcons });
  });
  await page.route("**/api/scan_worlds", route => route.fulfill({ json: { success: true, worlds: [] } }));
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, status: "offline", write_gate: { allowed: true, read_allowed: true },
  } }));
  await page.route("**/api/diagnostics/status", route => route.fulfill({ json: {
    success: true, mode: "local", data_root: { writable: true }, write_gate: { allowed: true, read_allowed: true },
  } }));
  await page.goto(NORMAL_BASE_URL + "/");
  const overlay = page.locator("#firstRunSetupOverlay");
  await expect(overlay).toBeVisible();
  const iconRow = overlay.locator('[data-first-run-todo="icons"]');
  await expect(iconRow).toContainText(responses[0].error);
  await expect(iconRow.locator('[data-role="state"]')).not.toContainText(responses[0].error);
  await expect(iconRow.locator('[data-role="details-content"]')).toBeHidden();
  return {
    overlay, iconRow,
    counts: () => ({ statusReads, iconDownloads }),
    unexpectedErrors: () => browserErrors.filter(error => !error.startsWith("Failed to load resource: the server responded with a status of 503")),
  };
}

for (const [width, locale] of [[1440, "de"], [390, "en"]]) {
  test(`filesystem status error stays unknown and retries without a download (${width}/${locale})`, async ({ page }) => {
    const failure = {
      success: false, status: "unavailable", code: "icons_status_unavailable",
      error: locale === "de" ? "Icon-Status konnte nicht geprüft werden: Permission denied"
        : "The icon status could not be checked: Permission denied",
    };
    const flow = await prepareStatusRecovery(page, [failure, readyIcons], { width, locale });
    const retry = flow.iconRow.locator('[data-role="run"]');
    await expect(retry).toHaveText(locale === "de" ? "Status erneut prüfen" : "Check status again");
    await expect(flow.iconRow.locator('[data-role="mark"]')).toHaveText("–");
    await captureBrowserEvidence(page, `icon-permission-retry-${width}-${locale}`, ".first-run-box");
    await retry.focus();
    await page.keyboard.press("Enter");
    await expect(flow.iconRow.locator('[data-role="mark"]')).toHaveText("✓");
    await expect(flow.iconRow).not.toContainText("Permission denied");
    expect(flow.counts()).toEqual({ statusReads: 2, iconDownloads: 0 });
    expect(flow.unexpectedErrors()).toEqual([]);
  });

  for (const entry of ["setup", "tools"]) {
    test(`item DB update rechecks a failed icon status through ${entry} (${width}/${locale})`, async ({ page }) => {
      const flow = await prepareStatusRecovery(page, [initialFailure, readyIcons], { width, locale });
      const retry = flow.iconRow.locator('[data-role="run"]');
      await expect(retry).toBeEnabled();
      await expect(retry).toHaveText(locale === "de" ? "Status erneut prüfen" : "Check status again");
      if (entry === "setup") {
        await flow.overlay.locator('[data-first-run-todo="item_db"] [data-role="run"]').click();
      } else {
        await page.locator("#btnFirstRunSetupClose").click();
        await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
        await page.locator('.tab-btn-dash[data-tab-dash="dashUpdate"]').click();
        await page.locator("#btnUpdateDbApply").click();
        await page.locator("#confirmOk").click();
      }
      await expect(flow.iconRow.locator('[data-role="mark"]')).toHaveText("✓");
      await expect(flow.iconRow).not.toContainText(initialFailure.error);
      await expect(flow.overlay.locator('[data-first-run-todo="item_db"] [data-role="mark"]')).toHaveText("✓");
      expect(flow.counts()).toEqual({ statusReads: 2, iconDownloads: 0 });
      if (entry === "setup") {
        await expect(page.locator("#btnFirstRunSetupClose")).toHaveText(locale === "de" ? "Fertig" : "Done");
        await captureBrowserEvidence(page, `icon-status-recovered-${width}-${locale}`, ".first-run-box");
      }
      expect(flow.unexpectedErrors()).toEqual([]);
    });
  }

  test(`persistent icon failure keeps the DB success and can be retried without downloading (${width}/${locale})`, async ({ page }) => {
    const afterUpdateFailure = { success: false, error: "HTTP 503: Icon-Index wird noch aufgebaut" };
    const retryFailure = { success: false, error: "HTTP 503: Icon-Dienst weiterhin nicht erreichbar" };
    const emptyIcons = { ...readyIcons, count: 0 };
    const flow = await prepareStatusRecovery(page,
      [initialFailure, afterUpdateFailure, retryFailure, emptyIcons, readyIcons], { width, locale });
    const dbRow = flow.overlay.locator('[data-first-run-todo="item_db"]');
    await dbRow.locator('[data-role="run"]').click();
    await expect(dbRow.locator('[data-role="state"]')).toHaveText(locale === "de" ? "Erledigt." : "Done.");
    await expect(flow.iconRow).toContainText(afterUpdateFailure.error);
    await expect(flow.iconRow).not.toContainText(initialFailure.error);
    await expect(page.locator("#assetDataStatusPanel")).toContainText(afterUpdateFailure.error);
    const retry = flow.iconRow.locator('[data-role="run"]');
    await expect(retry).toBeEnabled();
    await retry.focus();
    await page.keyboard.press("Enter");
    await expect(flow.iconRow).toContainText(retryFailure.error);
    await expect(retry).toBeEnabled();
    expect(flow.counts()).toEqual({ statusReads: 3, iconDownloads: 0 });
    await captureBrowserEvidence(page, `icon-status-retry-error-${width}-${locale}`, ".first-run-box");
    expect(await flow.overlay.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);

    await retry.click();
    await expect(flow.iconRow.locator('[data-role="mark"]')).toHaveText("○");
    await expect(retry).toHaveText(locale === "de" ? "Jetzt laden" : "Load now");
    await expect(flow.iconRow).not.toContainText(retryFailure.error);
    await expect(page.locator("#assetDataStatusPanel")).not.toContainText(retryFailure.error);
    expect(flow.counts()).toEqual({ statusReads: 4, iconDownloads: 0 });
    // Missing icons are downloaded only on this separate, explicit click.
    await retry.click();
    await expect(flow.iconRow.locator('[data-role="mark"]')).toHaveText("✓");
    expect(flow.counts()).toEqual({ statusReads: 5, iconDownloads: 1 });
    expect(flow.unexpectedErrors()).toEqual([]);
  });
}
