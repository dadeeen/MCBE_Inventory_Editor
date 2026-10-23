import { expect, test } from "@playwright/test";
import {
  prepareBannerTextures,
  NORMAL_BASE_URL,
  collectBrowserErrors,
  dismissFirstRunSetup,
  openAppWithEmptyWorldScan,
  captureBrowserEvidence,
} from "./fixtures/app.mjs";

for (const [width, locale] of [[1440, "de"], [390, "en"]]) {
  test(`legacy item icons keep banner setup pending until all faces are available (${width}/${locale})`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await page.setViewportSize({ width, height: 900 });
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await page.route("**/api/item-db/status", route => route.fulfill({ json: {
      success: true, item_db: { status: "ok", verification: { verified: true }, counts: { items: 1 } },
    } }));
    let current = { success: true, icons: {}, banner_patterns: {}, missing_banner_patterns: ["base", "illager"], count: 1, sources: [], warnings: [] };
    await page.route("**/api/icons/status*", route => route.fulfill({ json: current }));
    await openAppWithEmptyWorldScan(page);
    const { response } = await prepareBannerTextures(page, { synthetic: true, publish: false });
    const complete = { ...response, count: 1, missing_banner_patterns: [] };
    const partial = { ...complete, banner_patterns: { ...complete.banner_patterns }, missing_banner_patterns: ["illager"] };
    delete partial.banner_patterns.illager;
    let attempts = 0;
    await page.route("**/api/icons/vanilla/update", route => {
      attempts++;
      if (attempts === 1) return route.fulfill({ json: { success: false, error: "Synthetic interrupted update" } });
      current = attempts === 2 ? partial : complete;
      return route.fulfill({ json: current });
    });

    const hint = locale === "de" ? /Bannermuster fehlen/ : /missing banner patterns/;
    const banner = page.locator("#setupTodoBanner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(hint);
    await expect(banner).not.toContainText(/Slots zeigen Ersatzsymbole|Slots show placeholders/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await captureBrowserEvidence(page, `banner-upgrade-notice-${width}-${locale}`, "#setupTodoBanner");
    await page.locator("#btnSetupTodoBanner").click();
    const row = page.locator('[data-first-run-todo="icons"]');
    const run = row.locator('[data-role="run"]');
    await expect(row).toContainText(hint);
    await expect(run).toBeFocused();
    await run.click();
    await expect(row).toContainText("Synthetic interrupted update");
    await expect(run).toBeEnabled();
    await run.click();
    await expect(row.locator('[data-role="mark"]')).toHaveText("○");
    await expect(row.locator('[data-role="state"]')).toContainText(/weiterhin offen|still pending/);
    await expect(page.locator(".toast-warning")).toContainText(/weiterhin Bannermuster|banner patterns are still missing/);
    await page.locator("#btnFirstRunSetupClose").click();
    await expect(banner).toContainText(hint);
    await page.locator("#btnSetupTodoBanner").click();
    await run.click();
    await expect(row.locator('[data-role="mark"]')).toHaveText("✓");
    await expect(run).toBeHidden();
    await expect(page.locator(".toast-success")).toContainText(/Vanilla-Icons aktualisiert|Vanilla icons updated/);
    await page.locator("#btnFirstRunSetupClose").click();
    await expect(banner).toBeHidden();
    expect(attempts).toBe(3);
    expect(errors).toEqual([]);
  });
}

test("fresh browser storage does not turn unavailable data statuses into setup work", async ({ page }) => {
  await page.route("**/api/item-db/status", route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ success: false, error: "Item-DB status unavailable" }),
  }));
  await page.route("**/api/icons/status", route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ success: false, error: "Icon status unavailable" }),
  }));
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));

  await page.goto(NORMAL_BASE_URL + "/");

  await expect(page.locator("#assetDataStatusPanel")).toContainText(/Status nicht verfügbar|status unavailable/);
  await expect(page.locator("#firstRunSetupOverlay")).toBeHidden();
  await expect(page.locator("#setupTodoBanner")).toBeHidden();
  expect(await page.evaluate(() => window.localStorage.getItem("mcbe-inventory-editor:workspace"))).toBeNull();
});

test("regular tools update refreshes the dismissed setup banner and resolves releases automatically", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await dismissFirstRunSetup(page);
  // This flow exercises asset updates; server polling is covered separately
  // and must not consume the shared read budget of the smoke-test process.
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, status: "offline", write_gate: { allowed: true, read_allowed: true },
  } }));
  // Opening Tools also refreshes the diagnostic panel, which is outside this
  // asset-update flow and must not depend on earlier tests' shared read budget.
  await page.route("**/api/diagnostics/status", route => route.fulfill({ json: {
    success: true, mode: "local", data_root: { writable: true },
    write_gate: { allowed: true, read_allowed: true },
  } }));
  let updateRequest = null;
  await page.route("**/api/item-db/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      item_db: {
        status: "ok",
        verification: { verified: false, reason: "missing" },
        source_version_present: true,
        source_version: {},
        counts: { items: 2048, effects: 37, enchantments: 42 },
      },
    }),
  }));
  await page.route("**/api/icons/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      icons: { "minecraft:apple": "/api/icons/minecraft:apple" },
      display_icons: {},
      count: 1,
      sources: [{ enabled: true, exists: true }],
      warnings: [],
    }),
  }));
  await page.route("**/api/update_db", route => {
    updateRequest = route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        returncode: 0,
        output: "Alles aktuell, keine Änderungen.",
        update_committed: true,
        reloaded: true,
        item_db: {
          status: "ok",
          verification: { verified: true, reason: "verified" },
          source_version_present: true,
          source_version: {},
          counts: { items: 2048, effects: 37, enchantments: 42 },
        },
      }),
    });
  });
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));

  await page.goto(NORMAL_BASE_URL + "/");

  const banner = page.locator("#setupTodoBanner");
  await expect(page.locator("#firstRunSetupOverlay")).toBeHidden();
  await expect(banner).toBeVisible();
  await expect(banner.locator("[data-role='detail']")).toContainText(/Item-Datenbank|Item database/);
  await expect(banner.locator("[data-role='detail']")).not.toContainText(/Item-Icons|Item icons/);

  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashUpdate"]').click();
  await expect(page.locator("#updateDbUseCache")).toHaveCount(0);
  await expect(page.locator("#btnUpdateDbApply")).toBeEnabled();

  await page.locator("#btnUpdateDbApply").click();
  await expect(page.locator("#confirmOverlay")).toBeVisible();
  const updateResponse = page.waitForResponse(response => response.url().endsWith("/api/update_db"));
  await page.locator("#confirmOk").click();
  await updateResponse;
  await expect(page.locator("#itemDbStatusPanel")).toContainText(/geprüft|verified/);
  expect(Object.hasOwn(updateRequest || {}, "use_cache")).toBe(false);

  await page.locator('.tab-btn-dash[data-tab-dash="dashIcons"]').click();
  await expect(page.locator("#updateIconsUseCache")).toHaveCount(0);
  await expect(page.locator("#dashIcons")).toContainText(/automatisch geprüft|checked automatically/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashIcons"]').click();
  await expect(page.locator("#dashIcons")).toContainText(/automatisch geprüft|checked automatically/);

  await page.locator('.app-section-nav button[data-workflow-view="world"]').click();
  await expect(banner).toBeHidden();
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});

test("first-run setup overlay guides through item DB and icons, then hands over to the banner", async ({ page }) => {
  // Force the fresh-install state: bundled item snapshot, no icons yet.
  let itemDbVerified = false;
  let requestedUpdateScope = undefined;
  await page.route("**/api/item-db/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      item_db: {
        status: "ok",
        matches_bundled_snapshot: true,
        verification: { verified: itemDbVerified, reason: itemDbVerified ? "verified" : "missing" },
        source_version_present: true,
        source_version: {},
        counts: { items: 2048, effects: 37, enchantments: 42 },
      },
    }),
  }));
  await page.route("**/api/icons/status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, icons: {}, display_icons: {}, count: 0, sources: [], warnings: [] }),
  }));
  await page.route("**/api/update_db", route => {
    itemDbVerified = true;
    requestedUpdateScope = route.request().postDataJSON().only;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        returncode: 0,
        output: "Alles aktuell, keine Änderungen.",
        update_committed: true,
        reloaded: true,
        item_db: {
          status: "ok",
          matches_bundled_snapshot: true,
          verification: { verified: true, reason: "verified" },
          source_version_present: true,
          source_version: {},
          counts: { items: 2048, effects: 37, enchantments: 42 },
        },
      }),
    });
  });
  await page.route("**/api/scan_worlds", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ success: true, worlds: [] }),
  }));

  await page.goto(NORMAL_BASE_URL + "/");

  const overlay = page.locator("#firstRunSetupOverlay");
  await expect(overlay).toBeVisible();
  await expect(overlay.locator("[data-first-run-todo='item_db'] [data-role='mark']")).toHaveText("○");
  await expect(overlay.locator("[data-first-run-todo='icons'] [data-role='mark']")).toHaveText("○");

  const banner = page.locator("#setupTodoBanner");
  await expect(banner).toBeHidden();

  // The setup action must remain a full verification run even if the tools
  // workspace currently points at a partial update scope.
  await page.locator("#updateOnlySelect").evaluate(select => { select.value = "items"; });
  await overlay.locator("[data-first-run-todo='item_db'] [data-role='run']").click();
  await expect(overlay.locator("[data-first-run-todo='item_db'] [data-role='mark']")).toHaveText("✓");
  await expect(overlay.locator("[data-first-run-todo='item_db'] [data-role='state']")).toHaveText(/^(Erledigt|Done)\.$/);
  expect(requestedUpdateScope).toBeNull();
  expect(await page.evaluate(() => JSON.parse(
    window.localStorage.getItem("mcbe-inventory-editor:workspace") || "{}",
  ).first_run_item_db_verified)).toBeUndefined();

  await page.locator("#btnFirstRunSetupClose").click();
  await expect(overlay).toBeHidden();

  // Dismissing must not lose the todos: the banner is the documented way back.
  await expect(banner).toBeVisible();
  await expect(banner.locator("[data-role='detail']")).toContainText(/Item-Icons|Item icons/);
  await expect(banner.locator("[data-role='detail']")).not.toContainText(/Item-Datenbank|Item database/);
  await page.locator("#btnSetupTodoBanner").click();
  await expect(overlay).toBeVisible();
  await expect(banner).toBeHidden();
  await expect(overlay.locator("[data-first-run-todo='icons'] [data-role='run']")).toBeFocused();

  // Modal keyboard behavior must return to the banner without leaving focus
  // behind the overlay.
  await page.keyboard.press("Escape");
  await expect(overlay).toBeHidden();
  await expect(banner).toBeVisible();
  await expect(page.locator("#btnSetupTodoBanner")).toBeFocused();
});
