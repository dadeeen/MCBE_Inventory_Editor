import { expect, test } from "@playwright/test";
import {
  collectBrowserErrors,
  captureBrowserEvidence,
  openBackupSettings,
  openBackupSettingsApp,
} from "./fixtures/app.mjs";

test("backup size setting persists through reload without selecting a world", async ({ page }, testInfo) => {
  const errors = collectBrowserErrors(page);
  await openBackupSettingsApp(page);
  await openBackupSettings(page);
  const input = page.locator("#backupMaxSizeGib");
  await expect(input).toBeEnabled();
  const original = await input.inputValue();
  await input.fill("2.5");
  const savedResponse = page.waitForResponse(response => response.url().endsWith("/api/backup/settings") && response.request().method() === "POST");
  await page.locator("#btnSaveBackupSettings").click();
  expect((await (await savedResponse).json()).settings.max_uncompressed_mib).toBe(2560);
  await page.reload();
  await openBackupSettings(page);
  await expect(input).toHaveValue("2.5");
  await page.locator("#backupSettingsPanel").screenshot({ path: testInfo.outputPath("backup-settings.png") });
  await input.fill(original);
  const resetResponse = page.waitForResponse(response => response.url().endsWith("/api/backup/settings") && response.request().method() === "POST");
  await page.locator("#btnSaveBackupSettings").click();
  expect((await resetResponse).ok()).toBe(true);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({width, height: 900});
    await captureBrowserEvidence(page, `backup-size-setting-${width}`, '#backupSettingsPanel');
  }
  expect(errors).toEqual([]);
});

test("operator backup limit is visible but cannot be edited", async ({ page }) => {
  await page.route("**/api/backup/settings", route => route.fulfill({ json: {
    success: true, settings: { max_uncompressed_mib: 4096, source: "environment", editable: false },
  } }));
  await openBackupSettingsApp(page);
  await openBackupSettings(page);
  await expect(page.locator("#backupMaxSizeGib")).toHaveValue("4");
  await expect(page.locator("#backupMaxSizeGib")).toBeDisabled();
  await expect(page.locator("#btnSaveBackupSettings")).toBeDisabled();
  await expect(page.locator("#backupSettingsStatus")).toContainText("MCBE_BACKUP_MAX_UNCOMPRESSED_MIB");
});

test("backup limit error offers a direct link to its settings", async ({ page }) => {
  await openBackupSettingsApp(page);
  await page.evaluate(async () => {
    const response = new Response(JSON.stringify({ success: false, code: "backup_limit_exceeded", error: "limit" }), {
      status: 400, headers: { "Content-Type": "application/json" },
    });
    await window.MCBEApiClient.createApiClient().parseJsonResponse(response);
  });
  await page.locator(".toast-container .toast button").click();
  await expect(page.locator("#backupSettingsPanel")).toBeVisible();
  await expect(page.locator("#backupSettingsPanel")).toBeFocused();
});
