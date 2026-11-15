import { expect, test } from "@playwright/test";
import { collectBrowserErrors, openAppWithEmptyWorldScan } from "./fixtures/app.mjs";

for (const accepted of [true, false]) {
  test(`reopening scan paths keeps a pending toggle locked until ${accepted ? "success" : "rejection"}`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const writes = [];
    let enabled = true;
    await page.route("**/api/scan_paths", route => route.fulfill({ json: {
      success: true,
      scan_roots: [
        { path: "/worlds/custom", kind: "user-root", enabled, removable: true },
        { path: "/worlds/fixed", kind: "configured-root", enabled: true, removable: false },
      ],
    } }));
    await page.route("**/api/scan_paths/set_enabled", route => { writes.push(route); });
    await openAppWithEmptyWorldScan(page);
    await page.locator("#btnScanPaths").click();
    const checkbox = page.locator('[data-scan-path-toggle][data-path="/worlds/custom"]');
    await expect(checkbox).toBeEnabled();
    const original = await checkbox.elementHandle();
    await checkbox.uncheck();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0].request().postDataJSON()).toEqual({ path: "/worlds/custom", enabled: false });

    await page.locator("#btnCloseScanPaths").click();
    await page.locator("#btnScanPaths").click();
    await expect.poll(() => original.evaluate(node => node.isConnected)).toBe(false);
    await expect(checkbox).toBeDisabled();
    await checkbox.evaluate(node => node.click());
    expect(writes).toHaveLength(1);

    if (accepted) enabled = false;
    await writes[0].fulfill({ json: { success: accepted, error: accepted ? "" : "Write rejected" } });
    await expect(checkbox).toBeEnabled();
    await expect(checkbox).toBeChecked({ checked: !accepted });
    await expect(page.locator('[data-scan-path-toggle][data-path="/worlds/fixed"]')).toBeDisabled();
    if (!accepted) await expect(page.locator("#scanPathStatus")).toContainText("Write rejected");
    expect(errors).toEqual([]);
  });
}
