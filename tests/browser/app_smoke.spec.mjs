import { expect, test } from "@playwright/test";
import {
  collectBrowserErrors,
  openAppAndWaitForScan,
} from "./fixtures/app.mjs";

test("app starts without JavaScript bootstrap errors and renders discovered worlds", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);

  const scanResponse = await openAppAndWaitForScan(page);
  expect(scanResponse.status()).toBe(200);
  const scanPayload = await scanResponse.json();
  expect(scanPayload.success).toBe(true);
  expect(scanPayload.worlds).toHaveLength(1);
  expect(scanPayload.worlds[0].path).toContain("SmokeWorld");

  await expect(page.locator("#worldSection")).toBeVisible();
  await expect(page.locator(".world-card")).toHaveCount(1);
  await expect(page.locator(".world-card")).toContainText("Smoke Test World");
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});
