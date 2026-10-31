import { expect, test } from "@playwright/test";
import { captureBrowserEvidence, dismissFirstRunSetup, openAppWithSmokeWorldScan } from "./fixtures/app.mjs";

async function prepare(page) {
  await page.route("**/api/server_status", route => route.fulfill({ json: {
    success: true, status: "online", write_gate: { allowed: false, read_allowed: true, reason: "Server läuft noch." },
  } }));
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await page.route("**/api/icons/status*", route => route.fulfill({ json: { success: true, icons: {}, count: 0 } }));
  await page.route("**/api/icons/scan", route => route.fulfill({ json: { success: true, icons: {}, count: 0 } }));
  await page.route("**/api/item-db/status", route => route.fulfill({ json: { item_db: { status: "ok", verification: { verified: true }, counts: { items: 8 } } } }));
  await openAppWithSmokeWorldScan(page);
  await page.locator(".world-card").click();
}

test("a slow first world read stays visible beyond fifteen seconds and loads on its first attempt", async ({ page }) => {
  test.setTimeout(45000);
  let id, starts = 0, polls = 0, finish = false;
  const player = { player_key: "synthetic", label: "Testspieler", editable: true, exportable: true };
  const pending = () => ({ success: true, pending: true, read_id: id, progress: { phase: "scanning", current: polls * 256, elapsed_seconds: polls } });
  await page.route("**/api/players", route => {
    starts++;
    id = route.request().headers()["x-mcbe-read-id"];
    return route.fulfill({ status: 202, json: pending() });
  });
  await page.route("**/api/world_reads/*", route => {
    polls++;
    return route.fulfill({ status: finish ? 200 : 202, json: finish
      ? { success: true, world_name: "Synthetic world", players: [player] } : pending() });
  });
  await page.route("**/api/player/load", route => route.fulfill({ json: {
    success: true, player, player_revision: "synthetic-revision", inventory: {}, ender_chest: {},
    stats: { pos: [0, 64, 0], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 },
    items_db: {}, ench_db: {}, server_guard_epoch: 1, player_server_guard_epoch: 0,
    server_guard_stale: true, server_guard_stale_reason: "Nur ansehen: Der Bedrock-Server war online, als dieser Spieler geladen wurde.",
    write_gate: { allowed: false, read_allowed: true, reason: "Server läuft noch." },
  } }));
  await prepare(page);
  await page.locator("#btnLoad").click();
  await expect.poll(() => polls, { timeout: 22000 }).toBeGreaterThanOrEqual(17);
  await expect(page.locator("#loadingText")).toContainText("Datensätze geprüft");
  await expect(page.locator("#loadErrorPanel")).toBeHidden();
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("#cancelWorldRead")).toBeInViewport();
    await captureBrowserEvidence(page, `world-read-progress-${width}`);
  }
  finish = true;
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  await expect(page.locator("#btnSave")).toBeDisabled();
  expect(starts).toBe(1);
});

test("the loading overlay can be cancelled with the keyboard and retried", async ({ page }) => {
  let id, cancelled = 0;
  await page.route("**/api/players", route => {
    id = route.request().headers()["x-mcbe-read-id"];
    return route.fulfill({ status: 202, json: { success: true, pending: true, read_id: id, progress: { phase: "waiting" } } });
  });
  await page.route("**/api/world_reads/*", route => {
    if (route.request().method() === "DELETE") cancelled++;
    return route.fulfill({ status: 202, json: { success: true, pending: true, read_id: id, progress: { phase: "waiting" } } });
  });
  await prepare(page);
  await page.locator("#btnLoad").click();
  await expect(page.locator("#cancelWorldRead")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#cancelWorldRead")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator("#cancelWorldRead")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect(page.locator("#btnLoad")).toBeEnabled();
  await expect(page.locator("#loadErrorPanel")).toBeHidden();
  await expect.poll(() => cancelled).toBe(1);
  const previousId = id;
  await page.locator("#btnLoad").click();
  await expect.poll(() => id).not.toBe(previousId);
  await expect(page.locator("#cancelWorldRead")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect.poll(() => cancelled).toBe(2);
});

test("a gateway timeout names its cause and a retry resumes the previous job", async ({ page }) => {
  const ids = [];
  await page.route("**/api/players", route => {
    ids.push(route.request().headers()["x-mcbe-read-id"]);
    return ids.length === 1
      ? route.fulfill({ status: 504, contentType: "text/html", body: "<html>Gateway timeout</html>" })
      : route.fulfill({ json: { success: true, players: [], world_name: "Synthetic world" } });
  });
  await prepare(page);
  await page.locator("#btnLoad").click();
  const error = page.locator("#loadErrorPanel");
  await expect(error).toContainText("Zeitüberschreitung");
  await expect(error).toContainText("HTTP 504");
  await expect(error).not.toContainText("Schließe Minecraft");
  await expect(error).not.toContainText("Pfad ist ausgewählt");
  await captureBrowserEvidence(page, "world-read-timeout");
  await page.locator("#btnLoad").click();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect(error).toBeHidden();
  expect(ids).toHaveLength(2);
  expect(ids[0]).toBe(ids[1]);
});

function syntheticPlayer(token = "guard-A", epoch = 1) {
  return {
    success: true, player: { player_key: "synthetic", label: "Testspieler", editable: true, exportable: true },
    player_revision: `revision-${token}`, inventory: {}, ender_chest: {}, items_db: {}, ench_db: {},
    stats: { pos: [0, 64, 0], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 },
    server_guard_epoch: epoch, player_server_guard_epoch: epoch,
    server_guard_token: token, player_server_guard_token: token, server_status_revision: epoch,
    server_guard_stale: false, server_status: { status: "offline" },
    write_gate: { allowed: true, read_allowed: true, server_status: { status: "offline" } },
  };
}

test("a resumed player snapshot cannot turn a newer online status into an editing permission", async ({ page }) => {
  const ids = [];
  let fresh = false;
  await page.route("**/api/players", route => route.fulfill({ json: {
    success: true, world_name: "Synthetic", players: [syntheticPlayer().player],
  } }));
  await page.route("**/api/player/load", route => {
    ids.push(route.request().headers()["x-mcbe-read-id"]);
    return ids.length === 1
      ? route.fulfill({ status: 504, contentType: "text/html", body: "Gateway timeout after completed read" })
      : route.fulfill({ json: fresh ? syntheticPlayer("guard-B", 2) : syntheticPlayer() });
  });
  await prepare(page);
  let status = syntheticPlayer();
  await page.route("**/api/server_status", route => route.fulfill({ json: status }));
  await page.evaluate(() => refreshServerStatus());
  await page.locator("#btnLoad").click();
  await expect(page.locator("#loadErrorPanel")).toContainText("HTTP 504");
  status = { ...syntheticPlayer("guard-B", 2), server_status: { status: "online" },
    write_gate: { allowed: false, read_allowed: true, reason: "Server läuft noch.", server_status: { status: "online" } } };
  await page.evaluate(() => refreshServerStatus());
  await page.locator("#btnLoad").click();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  expect(await page.evaluate(() => writeBlocked())).toBe(true);
  expect(await page.evaluate(() => currentServerGuardToken)).toBe("guard-B");
  expect(ids[0]).toBe(ids[1]);
  await captureBrowserEvidence(page, "resumed-player-keeps-online-guard");
  fresh = true;
  status = syntheticPlayer("guard-B", 2);
  await page.evaluate(() => refreshServerStatus());
  await page.locator('.app-section-nav [data-workflow-view="world"]').click();
  await page.locator("#btnLoad").click();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  expect(ids).toHaveLength(3);
  expect(ids[2]).not.toBe(ids[1]);
  expect(await page.evaluate(() => writeBlocked())).toBe(false);
});

for (const withPlayer of [false, true]) {
  test(`a stalled presence request does not hold the completed ${withPlayer ? "player" : "empty world"} load open`, async ({ page }) => {
    let releasePresence, presenceRequests = 0;
    const pending = new Promise(resolve => { releasePresence = resolve; });
    await page.route("**/api/players", route => route.fulfill({ json: {
      success: true, world_name: "Synthetic", players: withPlayer ? [syntheticPlayer().player] : [],
    } }));
    await page.route("**/api/player/load", route => route.fulfill({ json: syntheticPlayer() }));
    await prepare(page);
    await page.route("**/api/world/presence", async route => {
      presenceRequests++;
      await pending;
      await route.fulfill({ status: 504, json: { success: false } });
    });
    try {
      await page.locator("#btnLoad").click();
      await expect(page.locator("#loadingOverlay")).toBeHidden({ timeout: 3000 });
      await expect.poll(() => presenceRequests).toBeGreaterThan(0);
      await expect(page.locator("#cancelWorldRead")).toBeHidden();
      await expect(page.locator("#btnLoad")).toBeEnabled();
      await expect(page.locator("#loadErrorPanel")).toBeHidden();
      if (withPlayer) await expect(page.locator("#inventoryContainer")).toBeVisible();
    } finally {
      releasePresence();
    }
  });
}

test("early browser cancellation is remembered by the backend before a delayed start arrives", async ({ page }) => {
  let delayed, releaseStart, starts = 0;
  const heldStart = new Promise(resolve => { releaseStart = resolve; });
  await page.route("**/api/players", async route => {
    starts++;
    if (starts > 1) return route.fulfill({ json: { success: true, world_name: "Synthetic", players: [] } });
    delayed = { headers: route.request().headers(), data: route.request().postDataJSON() };
    await heldStart;
    await route.abort().catch(() => {});
  });
  await prepare(page);
  try {
    await page.locator("#btnLoad").click();
    await expect.poll(() => Boolean(delayed)).toBe(true);
    const cancellation = page.waitForResponse(response => response.url().includes("/api/world_reads/")
      && response.request().method() === "DELETE");
    await page.locator("#cancelWorldRead").click();
    expect((await cancellation).status()).toBe(408);
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    const late = await page.request.post("/api/players", {
      data: delayed.data,
      headers: { "X-CSRF-Token": delayed.headers["x-csrf-token"], "X-MCBE-Read-ID": delayed.headers["x-mcbe-read-id"] },
    });
    expect(late.status()).toBe(408);
    expect((await late.json()).code).toBe("read_cancelled");
    releaseStart();
    await page.locator("#btnLoad").click();
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    await expect(page.locator("#loadErrorPanel")).toBeHidden();
    expect(starts).toBe(2);
  } finally {
    releaseStart();
  }
});

test("cancelling a retry preserves cancellation of a completed result whose response was lost", async ({ page }) => {
  const diskUrl = "http://127.0.0.1:8767";
  expect(process.env.MCBE_BROWSER_SMOKE_DISK_ROOT, "Run via npm run test:browser so the isolated disk server exists").toBeTruthy();
  const ids = [];
  let delayed, releaseRetry;
  const heldRetry = new Promise(resolve => { releaseRetry = resolve; });
  await page.route("**/api/players", async route => {
    const headers = route.request().headers();
    const id = headers["x-mcbe-read-id"];
    ids.push(id);
    if (ids.length === 1) {
      const accepted = await route.fetch();
      expect([200, 202]).toContain(accepted.status());
      let result = await accepted.json();
      // Complete the real job before losing its response. The retry must not
      // merely cancel a still-running job or create a missing-ID reservation.
      await expect.poll(async () => {
        if (result.pending === true) {
          const response = await page.request.get(`${diskUrl}/api/world_reads/${id}`, {
            headers: { "X-CSRF-Token": headers["x-csrf-token"] },
          });
          expect([200, 202]).toContain(response.status());
          result = await response.json();
        }
        return result.pending === true;
      }).toBe(false);
      expect(result.success, JSON.stringify(result)).toBe(true);
      expect(result.players.length).toBeGreaterThan(0);
      return route.fulfill({ status: 504, contentType: "text/html", body: "Controlled lost completed response" });
    }
    if (ids.length === 2) {
      delayed = { headers, data: route.request().postDataJSON() };
      await heldRetry;
      return route.abort().catch(() => {});
    }
    return route.continue();
  });
  await dismissFirstRunSetup(page);
  await page.goto(diskUrl);
  await page.locator("#username").fill("browser-test");
  await page.locator("#password").fill("synthetic-browser-test-only");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await page.locator(".world-card").filter({ hasText: "Synthetic Browser World" }).click();
  try {
    await page.locator("#btnLoad").click();
    await expect(page.locator("#loadErrorPanel")).toContainText("HTTP 504");
    await page.locator("#btnLoad").click();
    await expect.poll(() => Boolean(delayed)).toBe(true);
    expect(ids[1]).toBe(ids[0]);
    const cancellation = page.waitForResponse(response => response.url().endsWith(`/api/world_reads/${ids[0]}`)
      && response.request().method() === "DELETE");
    await page.locator("#cancelWorldRead").click();
    const cancelled = await cancellation;
    expect(cancelled.status()).toBe(408);
    expect((await cancelled.json()).code).toBe("read_cancelled");
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    const late = await page.request.post(`${diskUrl}/api/players`, {
      data: delayed.data,
      headers: { "X-CSRF-Token": delayed.headers["x-csrf-token"], "X-MCBE-Read-ID": delayed.headers["x-mcbe-read-id"] },
    });
    expect(late.status()).toBe(408);
    expect((await late.json()).code).toBe("read_cancelled");
    releaseRetry();
    await page.locator("#btnLoad").click();
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    await expect(page.locator("#inventoryContainer")).toBeVisible();
    await expect(page.locator("#loadErrorPanel")).toBeHidden();
    expect(ids).toHaveLength(3);
    expect(ids[2]).not.toBe(ids[0]);
  } finally {
    releaseRetry();
  }
});

async function preparePlayerToolReads(page) {
  const players = [
    { player_key: "target", label: "Zielspieler", editable: true, exportable: true },
    { player_key: "source-a", label: "Quelle A", editable: true, exportable: true },
    { player_key: "source-b", label: "Quelle B", editable: true, exportable: true },
  ];
  const jobs = new Map();
  const heldSources = new Set(["source-a", "source-b"]);
  let worldLoads = 0;
  const pending = id => ({ success: true, pending: true, read_id: id, progress: { phase: "scanning" } });
  const busy = () => [...jobs.values()].filter(job => !job.cancelled).length >= 2;
  const rejectBusy = route => route.fulfill({ status: 429, json: { success: false, code: "read_jobs_busy", error: "Lesekapazität belegt." } });
  await page.route("**/api/players", route => {
    worldLoads++;
    return busy() ? rejectBusy(route) : route.fulfill({ json: { success: true, world_name: "Synthetic", players } });
  });
  await page.route("**/api/player/load", route => {
    if (busy()) return rejectBusy(route);
    const key = route.request().postDataJSON().player_key;
    if (!heldSources.has(key)) {
      return route.fulfill({ json: { ...syntheticPlayer(), player: players.find(player => player.player_key === key) } });
    }
    const id = route.request().headers()["x-mcbe-read-id"];
    jobs.set(id, { id, key, polls: 0, cancelled: false });
    return route.fulfill({ status: 202, json: pending(id) });
  });
  await page.route("**/api/world_reads/*", route => {
    const id = route.request().url().split("/").at(-1);
    const job = jobs.get(id);
    expect(job).toBeTruthy();
    if (route.request().method() === "DELETE") job.cancelled = true;
    else job.polls++;
    return route.fulfill(job.cancelled
      ? { status: 408, json: { success: false, code: "read_cancelled" } }
      : { status: 202, json: pending(id) });
  });
  await prepare(page);
  await page.route("**/api/server_status", route => route.fulfill({ json: syntheticPlayer() }));
  await page.evaluate(() => refreshServerStatus());
  await page.locator("#btnLoad").click();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  const openTools = async () => {
    await page.locator('.app-section-nav [data-workflow-view="player"]').click();
    await page.locator('.tab-btn-dash[data-tab-dash="dashPlayerTools"]').click();
  };
  await openTools();
  return { jobs, heldSources, openTools, worldLoads: () => worldLoads };
}

test("superseded comparisons stop polling when comparing again or loading another player or world", async ({ page }) => {
  const fixture = await preparePlayerToolReads(page);
  const compare = async (key, count) => {
    await page.locator("#comparePlayerSelect").selectOption(key);
    await page.locator("#btnComparePlayer").click();
    await expect.poll(() => fixture.jobs.size).toBe(count);
    const job = [...fixture.jobs.values()].at(-1);
    await expect.poll(() => job.polls).toBeGreaterThan(0);
    return job;
  };
  const first = await compare("source-a", 1);
  const second = await compare("source-b", 2);
  await expect.poll(() => first.cancelled).toBe(true);
  expect(second.cancelled).toBe(false);
  expect(second.id).not.toBe(first.id);

  fixture.heldSources.delete("source-a");
  await page.locator('#playersList [data-player-key="source-a"]').click();
  await expect.poll(() => second.cancelled).toBe(true);
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  expect(await page.evaluate(() => currentPlayerKey)).toBe("source-a");
  await expect(page.locator("#loadErrorPanel")).toBeHidden();

  await fixture.openTools();
  const third = await compare("source-b", 3);
  await page.locator('.app-section-nav [data-workflow-view="world"]').click();
  await page.locator("#btnToggleManualWorld").click();
  await page.locator("#worldPath").fill("tests/fixtures/worlds/OtherSyntheticWorld");
  await page.locator("#btnLoad").click();
  await expect.poll(() => third.cancelled).toBe(true);
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  await expect(page.locator("#inventoryContainer")).toBeVisible();
  await expect(page.locator("#loadErrorPanel")).toBeHidden();
  expect(fixture.worldLoads()).toBe(2);
  expect(await page.evaluate(() => currentPlayerKey)).toBe("target");
  expect(await page.evaluate(() => worldPath)).toBe("tests/fixtures/worlds/OtherSyntheticWorld");
  const stoppedPolls = [first.polls, second.polls, third.polls];
  // Observe a full polling interval: discarded comparisons must not renew leases.
  await page.waitForTimeout(1200);
  expect([first.polls, second.polls, third.polls]).toEqual(stoppedPolls);
});

test("copying a player snapshot can be cancelled without changing the loaded player", async ({ page }) => {
  const fixture = await preparePlayerToolReads(page);
  const before = await page.evaluate(() => ({ inventory, isDirty, currentPlayerKey }));
  await page.locator("#copySourcePlayerSelect").selectOption("source-a");
  await page.locator("#btnCopyFromPlayer").click();
  await page.locator("#confirmOk").click();
  await expect.poll(() => fixture.jobs.size).toBe(1);
  const job = [...fixture.jobs.values()][0];
  await expect.poll(() => job.polls).toBeGreaterThan(0);
  await expect(page.locator("#cancelWorldRead")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect.poll(() => job.cancelled).toBe(true);
  await expect(page.locator("#loadingOverlay")).toBeHidden();
  expect(await page.evaluate(() => ({ inventory, isDirty, currentPlayerKey }))).toEqual(before);
  await expect(page.locator("#loadErrorPanel")).toBeHidden();
  const stoppedPolls = job.polls;
  await page.waitForTimeout(1200);
  expect(job.polls).toBe(stoppedPolls);
  await expect(page.locator("#btnCopyFromPlayer")).toBeEnabled();
});
