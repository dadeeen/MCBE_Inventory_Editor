import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function harness(names = [], extras = {}) {
    const timers = new Map();
    let serial = 0;
    const context = {
        window: {}, AbortController, console: { error() {}, warn() {} },
        setTimeout(callback) { timers.set(++serial, callback); return serial; },
        clearTimeout(id) { timers.delete(id); },
        ...extras,
    };
    for (const name of ["api_client", ...names]) {
        vm.runInNewContext(readFileSync(`static/${name}.js`, "utf8"), context);
    }
    return { context, timers, expire() { for (const callback of [...timers.values()]) callback(); } };
}

for (const phase of ["headers", "body"]) {
    test(`read deadline covers stalled ${phase}, aborts transport and clears resources`, async () => {
        let signal;
        const h = harness();
        const request = h.context.window.MCBEApiClient.readJson("/read", {}, {
            fetchFn: (_url, options) => {
                signal = options.signal;
                return phase === "headers" ? new Promise(() => {}) : Promise.resolve({});
            },
            parseJsonResponse: () => new Promise(() => {}),
        });
        const failed = assert.rejects(request, { name: "TimeoutError" });
        await Promise.resolve();
        h.expire();
        await failed;
        assert.equal(signal.aborted, true);
        assert.equal(h.timers.size, 0);
    });
}

test("external cancellation settles ignored signals and removes its listener; success and errors clear timers", async () => {
    const h = harness();
    const parent = new AbortController();
    let added = 0, removed = 0, calls = 0;
    const add = parent.signal.addEventListener.bind(parent.signal);
    const remove = parent.signal.removeEventListener.bind(parent.signal);
    parent.signal.addEventListener = (...args) => { added++; add(...args); };
    parent.signal.removeEventListener = (...args) => { removed++; remove(...args); };
    const fetchFn = () => { calls++; return new Promise(() => {}); };
    const read = h.context.window.MCBEApiClient.readJson;
    const pending = read("/read", {}, { fetchFn, signal: parent.signal });
    const rejected = assert.rejects(pending, { name: "AbortError" });
    parent.abort();
    await rejected;
    assert.equal(h.timers.size, 0);
    assert.equal(added, removed);
    await assert.rejects(read("/read", {}, { fetchFn, signal: parent.signal }), { name: "AbortError" });
    assert.equal(calls, 1, "a canceled read must not start or retry its transport");
    assert.equal(added, removed);
    assert.equal(await read("/read", {}, { fetchFn: async () => ({ json: async () => 7 }) }), 7);
    await assert.rejects(read("/read", {}, { fetchFn: async () => { throw new Error("offline"); } }), /offline/);
    assert.equal(h.timers.size, 0);
});

test("player read endpoints use deadlines while state-transfer writes retain their original transport", async () => {
    const calls = [];
    const h = harness(["player_api"]);
    const api = h.context.window.MCBEPlayerApi.createPlayerApiClient({
        fetchFn: (url, options) => { calls.push({ url, options }); return new Promise(() => {}); },
    });
    for (const invoke of [() => api.listPlayers("w"), () => api.loadPlayer("w", "p"), () => api.previewStateTransfer("w", "a", "b")]) {
        const pending = assert.rejects(invoke(), { name: "TimeoutError" });
        h.expire();
        await pending;
        assert.equal(calls.at(-1).options.signal.aborted, true);
    }
    api.applyStateTransfer({ worldPath: "w", sourcePlayerKey: "a", targetPlayerKey: "b" });
    assert.equal(calls.length, 4);
    assert.equal(calls.at(-1).options.signal, undefined);
    assert.equal(h.timers.size, 0, "writes must not acquire read deadlines or retries");
});

test("superseded player loads abort promptly and cannot unlock a pending newer load", async () => {
    const calls = [], errors = [], busy = [];
    const h = harness(["player_api", "player_view_models", "player_load_controller"]);
    const api = h.context.window.MCBEPlayerApi.createPlayerApiClient({
        fetchFn: (_url, options) => new Promise(resolve => calls.push({ options, resolve })),
        parseJsonResponse: response => response,
    });
    const state = { worldPath: "w", players: [] };
    const controller = h.context.window.MCBEPlayerLoadController.createPlayerLoadController({
        api, getState: () => state, setState: patch => Object.assign(state, patch),
        renderLoadError: error => errors.push(error), onLoadBusyChanged: value => busy.push(value),
    });
    const first = controller.loadPlayer("a");
    const second = controller.loadPlayer("b");
    assert.equal(calls[0].options.signal.aborted, true);
    assert.equal(await first, false);
    assert.equal(controller.isLoading(), true);
    assert.equal(errors.length, 0);
    calls[1].resolve({ success: false, error: "read rejected" });
    assert.equal(await second, false);
    assert.equal(controller.isLoading(), false);
    assert.equal(errors.length, 1);
    assert.equal(busy.at(-1), false);
    assert.equal(h.timers.size, 0);
});

test("a new world selection aborts pending world and player reads", async () => {
    const calls = [];
    const h = harness(["player_api", "player_view_models", "player_load_controller"]);
    const api = h.context.window.MCBEPlayerApi.createPlayerApiClient({
        fetchFn: (_url, options) => new Promise(resolve => calls.push({ options, resolve })),
        parseJsonResponse: response => response,
    });
    const state = { worldPath: "w", players: [] };
    const input = { value: "one" };
    const controller = h.context.window.MCBEPlayerLoadController.createPlayerLoadController({
        api, getState: () => state, setState: patch => Object.assign(state, patch),
        elements: { worldPathInput: input },
    });
    const player = controller.loadPlayer("a");
    const first = controller.loadWorldFromInput();
    await Promise.resolve();
    assert.equal(calls[0].options.signal.aborted, true);
    input.value = "two";
    const second = controller.loadWorldFromInput();
    await Promise.resolve();
    assert.equal(calls[1].options.signal.aborted, true);
    assert.equal(await player, false);
    assert.equal(await first, false);
    calls[2].resolve({ success: false, error: "read rejected" });
    assert.equal(await second, false);
    assert.equal(h.timers.size, 0);
});

test("a timed-out current player load releases its busy state and overlay", async () => {
    const h = harness(["player_api", "player_view_models", "player_load_controller"]);
    const api = h.context.window.MCBEPlayerApi.createPlayerApiClient({ fetchFn: () => new Promise(() => {}) });
    let overlay = false, failures = 0;
    const controller = h.context.window.MCBEPlayerLoadController.createPlayerLoadController({
        api, getState: () => ({ worldPath: "w" }),
        showLoading() { overlay = true; }, hideLoading() { overlay = false; },
        renderLoadError() { failures++; },
    });
    const pending = controller.loadPlayer("p");
    assert.equal(controller.isLoading(), true);
    assert.equal(overlay, true);
    h.expire();
    assert.equal(await pending, false);
    assert.equal(controller.isLoading(), false);
    assert.equal(overlay, false);
    assert.equal(failures, 1);
    assert.equal(h.timers.size, 0);
});

test("presence polls share one read, recover after timeout, and cancel on selection or page exit", async () => {
    const calls = [];
    const h = harness(["presence_view"], {
        fetch: (_url, options) => new Promise(resolve => calls.push({ options, resolve })),
    });
    let world = "a", intervalCalls = 0, intervalClears = 0;
    const controller = h.context.window.MCBEPresenceView.createWorldPresenceController({
        win: {
            sessionStorage: { setItem() {} },
            setInterval() { intervalCalls++; return 1; },
            clearInterval() { intervalClears++; },
        },
        getWorldPath: () => world, getCurrentPlayerKey: () => "p",
        parseJsonResponse: response => response,
    });
    controller.startPolling(); controller.startPolling();
    assert.equal(intervalCalls, 1);
    const first = controller.update();
    assert.equal(controller.update(), first);
    assert.equal(calls.length, 1);
    h.expire();
    assert.equal(await first, null);
    assert.equal(calls[0].options.signal.aborted, true);
    const previousWorld = controller.update();
    world = "b";
    controller.scheduleUpdate();
    assert.equal(calls[1].options.signal.aborted, true);
    assert.equal(await previousWorld, null);
    const current = controller.update();
    assert.equal(calls.length, 3);
    controller.stopPolling();
    assert.equal(await current, null);
    assert.equal(calls[2].options.signal.aborted, true);
    assert.equal(intervalClears, 1);
    assert.equal(h.timers.size, 0);
});

test("BFCache restore restarts presence polling and refreshes immediately without duplicate reads", async () => {
    const calls = [], events = {};
    let starts = 0, stops = 0;
    const h = harness(["presence_view"], {
        fetch: (url, options) => new Promise(resolve => calls.push({ url, options, resolve })),
    });
    const controller = h.context.window.MCBEPresenceView.createWorldPresenceController({
        win: {
            sessionStorage: { setItem() {} },
            addEventListener(name, callback) { events[name] = callback; },
            setInterval() { return ++starts; },
            clearInterval() { stops++; },
        },
        getWorldPath: () => "world", getCurrentPlayerKey: () => "player",
        parseJsonResponse: response => response,
    });
    controller.wireBeforeUnload();
    controller.startPolling();
    const original = controller.update();
    events.pagehide({ persisted: true });
    assert.equal(await original, null);
    assert.equal(calls[0].options.signal.aborted, true);
    assert.equal(calls[1].url, "/api/world/presence/leave");
    assert.equal(stops, 1);

    events.pageshow({ persisted: false });
    assert.equal(starts, 1, "ordinary pageshow must not duplicate initial polling");
    assert.equal(calls.length, 2);
    events.pageshow({ persisted: true });
    assert.equal(starts, 2);
    assert.equal(calls.length, 3, "a restored page must refresh without waiting for the interval");
    assert.equal(calls[2].url, "/api/world/presence");
    const restored = controller.update();
    events.pageshow({ persisted: true });
    assert.equal(starts, 2, "only one polling interval may run after restore");
    assert.equal(calls.length, 3, "the restored selection keeps one active presence read");
    calls[2].resolve({ success: false });
    assert.equal(await restored, null);
    events.pagehide({ persisted: true });
    assert.equal(calls[3].url, "/api/world/presence/leave", "a failed refresh must not suppress the next leave");
    assert.equal(stops, 2);
    assert.equal(h.timers.size, 0);
});
