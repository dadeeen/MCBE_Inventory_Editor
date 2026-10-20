import { expect, test } from "@playwright/test";

test.use({ locale: "de-DE" });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("mcbe-inventory-editor:storageSchema", "v3-dark-session-history");
    localStorage.setItem("mcbe-inventory-editor:workspace", JSON.stringify({ first_run_setup_dismissed: true }));
  });
});

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
