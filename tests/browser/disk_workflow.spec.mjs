import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";

const diskRoot = process.env.MCBE_BROWSER_SMOKE_DISK_ROOT;
const diskPython = process.env.MCBE_BROWSER_SMOKE_PYTHON;
const diskUrl = "http://127.0.0.1:8767";
test.use({ locale: "de-DE", viewport: { width: 1440, height: 1000 } });

function inspectDisk() {
  return JSON.parse(execFileSync(diskPython, ["-m", "tests.browser.disk_fixture", diskRoot], { encoding: "utf8" }));
}

async function post(page, target, body, csrf = true) {
  return page.evaluate(async ({ target, body, csrf }) => {
    const headers = { "Content-Type": "application/json" };
    if (csrf) headers["X-CSRF-Token"] = document.querySelector('meta[name="csrf-token"]').content;
    const response = await fetch(target, { method: "POST", headers, body: JSON.stringify(body) });
    return { status: response.status, body: await response.json() };
  }, { target, body, csrf });
}

async function finishWrite(page, responsePromise) {
  let response;
  let failure;
  responsePromise.then(value => { response = value; }, error => { failure = error; });
  await expect.poll(async () => {
    if (failure) throw failure;
    // A local installation without a BDS endpoint requires the explicit
    // unknown-server confirmation even for this disposable synthetic world.
    if (await page.locator("#confirmOverlay").isVisible()) await page.locator("#confirmOk").click();
    return Boolean(response);
  }).toBe(true);
  const payload = await response.json();
  expect(payload.success, JSON.stringify(payload)).toBe(true);
  return payload;
}

test("real browser authenticates, saves with backup, rejects stale/CSRF writes and restores exact disk records", async ({ page }) => {
  test.setTimeout(60_000);
  expect(diskRoot, "Run via npm run test:browser so the isolated disk server exists").toBeTruthy();
  expect(diskPython).toBeTruthy();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const before = inspectDisk();
  expect(before.count).toBe(1);
  expect(before.backups).toEqual({});
  await page.addInitScript(() => {
    localStorage.setItem("mcbe-inventory-editor:storageSchema", "v3-dark-session-history");
    localStorage.setItem("mcbe-inventory-editor:workspace", JSON.stringify({ first_run_setup_dismissed: true }));
  });
  await page.goto(diskUrl);
  await expect(page).toHaveURL(/\/login/);
  const loginCsrf = await page.locator('meta[name="csrf-token"]').getAttribute("content");
  await page.locator("#username").fill("browser-test");
  await page.locator("#password").fill("synthetic-incorrect");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page.locator(".status.error")).toContainText("Ungültiger");
  await page.locator("#username").fill("browser-test");
  await page.locator("#password").fill("synthetic-browser-test-only");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page.locator("#worldSection")).toBeVisible();
  expect(await page.locator('meta[name="csrf-token"]').getAttribute("content")).not.toBe(loginCsrf);
  await page.locator(".world-card").filter({ hasText: "Synthetic Browser World" }).click();
  const loadedPromise = page.waitForResponse(response => response.url().endsWith("/api/player/load") && response.status() === 200);
  await page.locator("#btnLoad").click();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  const loadedResponse = await loadedPromise;
  const loaded = await loadedResponse.json();
  const request = loadedResponse.request().postDataJSON();
  // Exercise the browser lifecycle wiring against the real presence endpoints.
  // The Node lifecycle tests separately check interval ownership/deduplication.
  const leftPromise = page.waitForResponse(response => response.url().endsWith("/api/world/presence/leave"));
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true })));
  expect((await leftPromise).status()).toBe(200);
  const resumedPromise = page.waitForResponse(response => response.url().endsWith("/api/world/presence"));
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
  const resumed = await resumedPromise;
  expect(resumed.status()).toBe(200);
  expect((await resumed.json()).success).toBe(true);
  expect(resumed.request().postDataJSON().world_path).toBe(request.world_path);
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailCount").fill("7");
  expect(await page.evaluate(() => inventory[0].count)).toBe(7);
  expect(inspectDisk()).toEqual(before);
  await page.keyboard.press("Control+s");
  await expect(page.locator("#saveReviewOverlay")).toBeVisible();
  const savedPromise = page.waitForResponse(response => response.url().endsWith("/api/player/save") && response.status() === 200);
  await page.locator("#btnSaveReviewConfirm").click();
  const saved = await finishWrite(page, savedPromise);
  expect(saved.backup_file).toBeTruthy();
  const after = inspectDisk();
  expect(after.count).toBe(7);
  expect(after.preserved).toBe("preserve-me");
  const playerKey = Buffer.from("~local_player").toString("hex");
  expect(after.records[playerKey]).not.toBe(before.records[playerKey]);
  expect({ ...after.records, [playerKey]: before.records[playerKey] }).toEqual(before.records);
  const backup = after.backups[saved.backup_file];
  expect(backup).toBeTruthy();
  for (const [name, hash] of Object.entries(before.files)) {
    if (name === "db/LOCK") continue;
    expect(backup[name], `backup bytes for ${name}`).toBe(hash);
  }
  const savedSlot = await page.evaluate(() => JSON.stringify(inventory[0]));
  await page.locator("#detailCount").fill("9");
  expect(inspectDisk()).toEqual(after);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(savedSlot);
  expect(await page.evaluate(() => isDirty)).toBe(false);
  await page.locator("#btnRedo").click();
  expect(await page.evaluate(() => inventory[0].count)).toBe(9);
  await page.keyboard.press("Control+s");
  await expect(page.locator("#saveReviewOverlay")).toBeVisible();
  const savedAgainPromise = page.waitForResponse(response => response.url().endsWith("/api/player/save") && response.status() === 200);
  await page.locator("#btnSaveReviewConfirm").click();
  const savedAgain = await finishWrite(page, savedAgainPromise);
  expect(savedAgain.player_revision).not.toBe(saved.player_revision);
  const afterSecondSave = inspectDisk();
  expect(afterSecondSave.count).toBe(9);
  expect(afterSecondSave.preserved).toBe("preserve-me");
  expect(afterSecondSave.backups[savedAgain.backup_file]).toBeTruthy();
  const fresh = await post(page, "/api/player/load", request);
  expect(fresh.body.inventory[0].count).toBe(9);
  expect(fresh.body.player_revision).not.toBe(loaded.player_revision);
  const stale = await post(page, "/api/player/save", {
    ...request, base_revision: loaded.player_revision, stats: { xp_level: 31 },
    server_guard_token: fresh.body.server_guard_token, server_guard_epoch: fresh.body.server_guard_epoch,
    confirm_unknown_server_status: true,
  });
  expect(stale.status).toBe(409);
  expect(stale.body.error).toContain("seit dem Laden");
  const csrf = await post(page, "/api/player/save", { ...request, stats: { xp_level: 31 } }, false);
  expect(csrf.status).toBe(403);
  expect(inspectDisk()).toEqual(afterSecondSave);

  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  await page.locator('[data-tab-dash="dashBackups"]').click();
  await page.locator(".backup-row").filter({ hasText: saved.backup_file }).locator(".restore-btn").click();
  await page.locator("#restoreConfirmInput").fill("WIEDERHERSTELLEN");
  const restoredPromise = page.waitForResponse(response => response.url().endsWith("/api/restore_backup") && response.status() === 200);
  await page.locator("#btnRestoreReviewConfirm").click();
  const restored = await finishWrite(page, restoredPromise);
  expect(restored.pre_restore_backup).toBeTruthy();
  const restoredDisk = inspectDisk();
  expect(restoredDisk.records).toEqual(before.records);
  expect(restoredDisk.count).toBe(1);
  expect(restoredDisk.backups[restored.pre_restore_backup]).toBeTruthy();
  expect((await post(page, "/api/player/load", request)).body.inventory[0].count).toBe(1);
  await page.locator("#focusSettingsToggle").click();
  await page.locator('form[action="/logout"] button').click();
  await expect(page.locator("#password")).toBeVisible();
  expect((await post(page, "/api/player/save", { ...request, stats: { xp_level: 31 } })).status).toBe(401);
  expect(inspectDisk()).toEqual(restoredDisk);
  expect(errors).toEqual([]);
});
