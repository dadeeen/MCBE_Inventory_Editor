import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function harness(fetchFn, extra = {}) {
    let now = 0, serial = 0;
    const timers = new Map();
    const context = {
        window: {}, AbortController, console: { error() {} }, Date: { now: () => now },
        setTimeout(fn, ms) { const id = ++serial; timers.set(id, { fn, at: now + ms }); return id; },
        clearTimeout(id) { timers.delete(id); },
    };
    for (const name of ["api_client", "player_api", "player_view_models", "player_load_controller", "world_status_view", "write_status_view", "presence_view"]) {
        vm.runInNewContext(readFileSync(`static/${name}.js`, "utf8"), context);
    }
    const id = "a".repeat(32);
    const api = context.window.MCBEPlayerApi.createPlayerApiClient({
        fetchFn, parseJsonResponse: response => response,
        withCsrf: () => ({ "X-CSRF-Token": "synthetic" }), createReadId: () => id, ...extra,
    });
    const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
    const advance = async () => {
        await flush();
        const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
        assert.ok(next, "expected a bounded wait");
        now = next[1].at;
        timers.delete(next[0]);
        next[1].fn();
        await flush();
    };
    return { api, context, timers, advance, flush, id, now: () => now };
}

test("a 25-second first scan finishes via short polls without restarting discovery", async () => {
    const calls = [], progress = [];
    const h = harness(async (url, options) => {
        calls.push({ url, options });
        return h.now() < 25000
            ? { success: true, pending: true, read_id: h.id, progress: { phase: "scanning", current: calls.length * 256 } }
            : { success: true, players: [{ label: "Synthetic player" }] };
    });
    let result;
    const pending = h.api.listPlayers("/synthetic/world", { onProgress: value => progress.push(value) }).then(value => { result = value; });
    for (let i = 0; i < 40 && !result; i++) await h.advance();
    await pending;
    assert.equal(result.players[0].label, "Synthetic player");
    assert.ok(h.now() > 15000);
    assert.equal(calls.filter(call => call.options.method === "POST").length, 1);
    assert.ok(progress.length > 15);
    assert.equal(calls[0].options.headers["X-MCBE-Read-ID"], h.id);
    assert.ok(calls.every(call => call.options.headers["X-CSRF-Token"] === "synthetic"));
    assert.equal(h.timers.size, 0);
});

test("a lost start response times out and a manual retry resumes the same read ID", async () => {
    const ids = [];
    let created = 0;
    const h = harness(async (_url, options) => {
        ids.push(options.headers["X-MCBE-Read-ID"]);
        if (ids.length === 1) return new Promise(() => {});
        return { success: true, players: [] };
    }, { createReadId: () => (++created).toString(16).padStart(32, "0") });
    const failure = assert.rejects(h.api.listPlayers("world"), { name: "TimeoutError" });
    await h.advance();
    await failure;
    assert.equal((await h.api.listPlayers("world")).success, true);
    assert.equal(created, 1);
    assert.equal(ids[0], ids[1]);
    assert.equal(h.timers.size, 0);
});

test("cancellation during the poll delay cancels the job and prevents further polls", async () => {
    const calls = [];
    const h = harness(async (url, options) => {
        calls.push({ url, options });
        return { success: true, pending: true, read_id: h.id };
    });
    const controller = new AbortController();
    const request = h.api.listPlayers("world", { signal: controller.signal });
    const failure = assert.rejects(request, { name: "AbortError" });
    await h.flush();
    controller.abort();
    await failure;
    await h.flush();
    assert.deepEqual(calls.map(call => call.options.method), ["POST", "DELETE"]);
    assert.equal(calls[1].options.signal.aborted, false, "cancellation needs its own transport");
    assert.equal(h.timers.size, 0);
    await assert.rejects(h.api.listPlayers("other", { signal: controller.signal }), { name: "AbortError" });
    assert.equal(calls.length, 2);
});

test("healthy polls cannot keep a stuck read alive beyond its overall deadline", async () => {
    const calls = [];
    const h = harness(async (_url, options) => {
        calls.push(options.method);
        return { success: true, pending: true, read_id: h.id };
    }, { operationTimeoutMs: 2000 });
    let stopped = false;
    const request = assert.rejects(h.api.listPlayers("world"), { name: "TimeoutError", code: "read_timeout" }).then(() => { stopped = true; });
    for (let i = 0; i < 8 && !stopped; i++) await h.advance();
    await request;
    assert.equal(calls.filter(method => method === "DELETE").length, 1);
    assert.equal(h.timers.size, 0);
});

test("gateway timeouts retain the resumable ID and are not presented as path errors", async () => {
    const ids = [];
    const h = harness(async (_url, options) => {
        ids.push(options.headers["X-MCBE-Read-ID"]);
        return ids.length === 1 ? { success: false, http_status: 504, response_unreadable: true }
            : { success: true, players: [] };
    });
    const errors = [];
    const state = { worldPath: "world", players: [] };
    const controller = h.context.window.MCBEPlayerLoadController.createPlayerLoadController({
        api: h.api, getState: () => state, setState: patch => Object.assign(state, patch),
        buildErrorMessage: h.context.window.MCBEApiClient.buildErrorMessage,
        renderLoadError: data => errors.push(data),
    });
    assert.equal(await controller.loadWorldFromInput(), false);
    assert.equal(controller.isLoading(), false);
    assert.equal(errors[0].code, "read_response_timeout");
    const message = h.context.window.MCBEApiClient.buildErrorMessage(errors[0]);
    assert.match(message, /Zeitüberschreitung/);
    assert.match(message, /HTTP 504/);
    const html = h.context.window.MCBEWorldStatusView.loadErrorHtml({ ...errors[0], message });
    assert.doesNotMatch(html, /Schließe Minecraft|Pfad ist ausgewählt/);
    assert.equal(await controller.loadWorldFromInput(), true);
    assert.equal(ids[0], ids[1]);
});

test("bare errors preserve useful details without duplicating a complete message", () => {
    const h = harness(async () => ({}));
    const build = h.context.window.MCBEApiClient.buildErrorMessage;
    assert.equal(build({ error: "Laden fehlgeschlagen", details: "Zeitlimit" }), "Laden fehlgeschlagen — Zeitlimit");
    assert.equal(build({ error: "Zeitlimit", details: "Zeitlimit" }), "Zeitlimit");
    assert.equal(build(null), "Unbekannter Fehler");
});

for (const newerStatus of ["online", "offline"]) {
    test(`resuming a lost player response cannot replace a newer ${newerStatus} guard, while a fresh read can`, async () => {
        let serial = 0;
        const ids = [];
        const result = (token, epoch) => ({
            success: true, player: { editable: true }, inventory: {}, stats: {}, player_revision: `revision-${token}`,
            server_guard_epoch: epoch, player_server_guard_epoch: epoch,
            server_guard_token: token, player_server_guard_token: token, server_status_revision: epoch,
            server_guard_stale: false, server_status: { status: "offline" },
            write_gate: { allowed: true, read_allowed: true, server_status: { status: "offline" } },
        });
        const h = harness(async (_url, options) => {
            ids.push(options.headers["X-MCBE-Read-ID"]);
            if (ids.length === 1) throw new Error("completed response lost");
            return ids.length === 2 ? result("guard-A", 1) : result("guard-B", 2);
        }, { createReadId: () => (++serial).toString(16).padStart(32, "0") });
        const state = { worldPath: "synthetic", players: [], currentPlayerKey: "", currentServerGuardEpoch: 1,
            currentServerGuardToken: "guard-A", currentServerStatusRevision: 1, stale: "", gate: { allowed: true } };
        const config = { require_server_offline: true };
        const gate = h.context.window.MCBEWriteStatusView.createWriteGateController({
            appConfig: config,
            getCurrentWriteGate: () => state.gate, setCurrentWriteGate: value => { state.gate = value; },
            getCurrentServerGuardEpoch: () => state.currentServerGuardEpoch, setCurrentServerGuardEpoch: value => { state.currentServerGuardEpoch = value; },
            getCurrentServerGuardToken: () => state.currentServerGuardToken, setCurrentServerGuardToken: value => { state.currentServerGuardToken = value; },
            getCurrentServerStatusRevision: () => state.currentServerStatusRevision, setCurrentServerStatusRevision: value => { state.currentServerStatusRevision = value; },
            getCurrentPlayerServerGuardEpoch: () => state.currentPlayerServerGuardEpoch,
            getCurrentPlayerServerGuardToken: () => state.currentPlayerServerGuardToken,
            getCurrentPlayerStaleReason: () => state.stale, setCurrentPlayerStaleReason: value => { state.stale = value; },
            getCurrentPlayerKey: () => state.currentPlayerKey,
        });
        const loader = h.context.window.MCBEPlayerLoadController.createPlayerLoadController({
            api: h.api, appConfig: config, getState: () => state, setState: patch => Object.assign(state, patch),
            beginServerStatusRequest: gate.beginServerStatusRequest, renderServerStatus: gate.renderServerStatus,
            clearLoadedPlayerStaleState: gate.clearLoadedPlayerStaleState, markLoadedPlayerStale: gate.markLoadedPlayerStale,
        });
        assert.equal(await loader.loadPlayer("synthetic-player"), false);
        gate.renderServerStatus({
            server_guard_epoch: 2, server_guard_token: "guard-B", server_status_revision: 2,
            server_status: { status: newerStatus },
            write_gate: { allowed: newerStatus === "offline", read_allowed: true, server_status: { status: newerStatus } },
        }, { requestOrder: gate.beginServerStatusRequest() });
        assert.equal(await loader.loadPlayer("synthetic-player"), true);
        assert.equal(ids[0], ids[1]);
        assert.equal(state.currentServerGuardToken, "guard-B");
        assert.equal(state.currentPlayerServerGuardToken, "guard-A");
        assert.equal(state.gate.server_status.status, newerStatus);
        assert.equal(gate.writeBlocked(), true);
        assert.ok(state.stale);
        assert.equal(await loader.loadPlayer("synthetic-player"), true);
        assert.notEqual(ids[1], ids[2], "a completed operation must not keep reusing its snapshot");
        assert.equal(state.currentPlayerServerGuardToken, "guard-B");
        assert.equal(state.gate.server_status.status, "offline");
        assert.equal(gate.writeBlocked(), false);
        assert.equal(state.stale, "");
    });
}

for (const mode of ["empty", "player"]) {
    test(`a completed ${mode} world leaves the overlay before a stalled presence request`, async () => {
        const player = { player_key: "synthetic-player", editable: true };
        const h = harness(async url => url === "/api/players"
            ? { success: true, world_name: "Synthetic", players: mode === "player" ? [player] : [] }
            : { success: true, player, stats: {}, inventory: {} });
        const state = { worldPath: "synthetic", players: [] };
        const requests = [];
        let loader, overlay = false, settled = false;
        h.context.fetch = (_url, options) => { requests.push(options); return new Promise(() => {}); };
        const presence = h.context.window.MCBEPresenceView.createWorldPresenceController({
            win: { sessionStorage: { setItem() {} } },
            getWorldPath: () => state.worldPath, getCurrentPlayerKey: () => state.currentPlayerKey,
            getIsBusy: () => loader.isLoading(), parseJsonResponse: response => response,
        });
        loader = h.context.window.MCBEPlayerLoadController.createPlayerLoadController({
            api: h.api, getState: () => state, setState: patch => Object.assign(state, patch),
            showLoading: () => { overlay = true; }, hideLoading: () => { overlay = false; },
            // The old implementation awaited update() and could not cancel it.
            updateWorldPresence: presence.update,
            scheduleWorldPresenceUpdate: () => presence.scheduleUpdate(0),
        });
        const load = loader.loadWorldFromInput().then(value => { settled = true; return value; });
        await h.flush();
        assert.equal(settled, true, "presence is not part of completing a world read");
        assert.equal(await load, true);
        assert.equal(overlay, false);
        assert.equal(loader.isLoading(), false);
        await h.advance();
        assert.equal(requests.length, 1);
        assert.equal(requests[0].signal.aborted, false);
        assert.equal(overlay, false);
        await h.advance();
        assert.equal(requests[0].signal.aborted, true, "background presence still has its own deadline");
        assert.equal(loader.isLoading(), false);
        assert.equal(state.worldPath, "synthetic");
    });
}
