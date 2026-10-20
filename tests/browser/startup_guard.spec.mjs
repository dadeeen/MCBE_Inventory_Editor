import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test.use({ locale: "de-DE" });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("mcbe-inventory-editor:storageSchema", "v3-dark-session-history");
    localStorage.setItem("mcbe-inventory-editor:workspace", JSON.stringify({ first_run_setup_dismissed: true }));
  });
});

async function missingInspectorMarkup(page) {
  await page.route("http://127.0.0.1:8765/", async route => {
    const response = await route.fetch();
    const html = (await response.text()).replace('id="itemInspectorTree"', 'id="oldInspectorTree"');
    await route.fulfill({ response, body: html });
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 568 }]) {
  test(`startup failure replaces the endless scan and offers keyboard recovery at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors = [];
    const scans = [];
    page.on("pageerror", error => errors.push(error));
    page.on("request", request => { if (request.url().endsWith("/api/scan_worlds")) scans.push(request.url()); });
    await missingInspectorMarkup(page);
    await page.goto("/");
    const notice = page.locator("#startupNotice");
    await expect(notice).toBeVisible();
    await expect(notice).toHaveAttribute("role", "alert");
    await expect(page.locator("#autoPathHint")).toHaveText("Editor konnte nicht gestartet werden");
    await expect(page.locator("#statusStackSummary")).not.toContainText("läuft");
    await expect(page.locator("#worldScanLoading")).toBeHidden();
    expect(await page.locator(".app-container").evaluate(node => node.inert)).toBe(true);
    // The first missing-element access can change as the inspector evolves.
    // Its original exception must remain available for diagnosis either way.
    expect(errors.some(error => error.stack?.includes("/static/nbt_inspector.js"))).toBe(true);
    expect(scans).toEqual([]);
    if (viewport.width === 320) {
      // This failure precedes theme initialization. Exercise the notice with
      // explicit light-theme tokens as well as the default dark error surface.
      await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    }
    // Measure the settled layout, not the inherited toast entrance animation.
    await notice.evaluate(async element => { await Promise.all(element.getAnimations().map(animation => animation.finished)); });
    const box = await notice.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    await page.keyboard.press("Tab");
    await expect(page.locator("#startupReload")).toBeFocused();
    if (process.env.MCBE_STARTUP_QA_DIR) {
      fs.mkdirSync(process.env.MCBE_STARTUP_QA_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.MCBE_STARTUP_QA_DIR, `startup-${viewport.width}.png`) });
    }
    await page.unroute("http://127.0.0.1:8765/");
    await Promise.all([page.waitForResponse("**/api/scan_worlds"), page.keyboard.press("Enter")]);
    await expect(notice).toBeHidden();
    await expect(page.locator(".world-card").first()).toBeVisible();
  });
}

for (const brokenScript of ["blocked", "empty", "syntax"]) {
  test(`startup guard reports ${brokenScript} application script`, async ({ page }) => {
    await page.route("**/static/app.js", route => brokenScript === "blocked" ? route.abort()
      : route.fulfill({ contentType: "application/javascript", body: brokenScript === "syntax" ? "const = ;" : "" }));
    await page.goto("/");
    await expect(page.locator("#startupFailure")).toBeVisible();
    await expect(page.locator("#startupNotice")).toHaveCount(1);
  });
}

test("a duplicate start explains reuse, removes its URL marker and remains dismissible", async ({ page }) => {
  await page.goto("/?already_running=1&test=value#world");
  await expect(page.locator("#startupExisting")).toBeVisible();
  await expect(page.locator("#startupNotice")).toHaveAttribute("role", "status");
  expect(page.url()).toContain("?test=value#world");
  expect(page.url()).not.toContain("already_running");
  expect(await page.locator(".app-container").evaluate(node => node.inert)).toBe(false);
  await page.locator("#startupDismiss").click();
  await expect(page.locator("#startupNotice")).toBeHidden();
  await page.reload();
  await expect(page.locator(".world-card").first()).toBeVisible();
  await expect(page.locator("#startupNotice")).toBeHidden();
});

test("failed resources unrelated to scripts and later runtime errors do not report a failed startup", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".world-card").first()).toBeVisible();
  await page.evaluate(() => {
    window.dispatchEvent(new ErrorEvent("error", { message: "later error", filename: `${location.origin}/static/app.js` }));
    const image = document.createElement("img");
    document.body.append(image);
    image.dispatchEvent(new Event("error", { bubbles: false }));
    image.remove();
  });
  await expect(page.locator("#startupNotice")).toBeHidden();
});

test("the failure message is translated even when i18n.js fails to load", async ({ page, context }) => {
  await context.addCookies([{ name: "mcbe_locale", value: "en", url: "http://127.0.0.1:8765" }]);
  await page.route("**/static/i18n.js", route => route.abort());
  await page.goto("/");
  await expect(page.locator("#startupFailureTitle")).toHaveText("The editor could not start");
  await expect(page.locator("#startupReload")).toHaveText("Reload page");
});

test.describe("touch recovery", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  test("reload remains usable with touch after a failed startup", async ({ page }) => {
    await missingInspectorMarkup(page);
    await page.goto("/");
    await expect(page.locator("#startupFailure")).toBeVisible();
    await page.unroute("http://127.0.0.1:8765/");
    await Promise.all([page.waitForResponse("**/api/scan_worlds"), page.locator("#startupReload").tap()]);
    await expect(page.locator(".world-card").first()).toBeVisible();
    await expect(page.locator("#startupNotice")).toBeHidden();
  });
});
