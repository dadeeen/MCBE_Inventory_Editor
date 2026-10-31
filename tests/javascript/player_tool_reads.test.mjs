import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function harness({ holdSource = false, holdPlayer = false } = {}) {
    let now = 0, timerId = 0, readId = 0;
    const timers = new Map(), jobs = new Map(), calls = [], held = [];
    const state = { worldPath: "world-A", currentPlayerKey: "target", players: [] };
    const feedback = { errors: [], toasts: [], records: [], inventoryWrites: 0, undoWrites: 0, overlay: false, onCancel: null };
    const panel = { innerHTML: "" }, selected = { value: "source-A" };
    const context = {
        window: {}, AbortController, console: { error() {}, warn() {} }, Date: { now: () => now },
        setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, at: now + ms }); return id; },
        clearTimeout(id) { timers.delete(id); },
    };
    for (const name of ["api_client", "player_api", "player_view_models", "player_compare_view", "player_tools", "player_load_controller", "player_load_app"]) {
        vm.runInNewContext(readFileSync(`static/${name}.js`, "utf8"), context);
    }
    const snapshot = key => ({ success: true, player: { label: key, editable: true }, inventory: { 0: { name: "minecraft:apple", count: 1 } }, stats: {} });
    const pending = id => ({ success: true, pending: true, read_id: id, progress: { phase: "scanning" } });
    const active = () => [...jobs.values()].filter(job => !job.result).length;
    const fetchFn = async (url, options = {}) => {
        const method = options.method || "GET";
        const id = options.headers?.["X-MCBE-Read-ID"] || url.split("/").at(-1);
        const body = options.body ? JSON.parse(options.body) : null;
        calls.push({ url, method, id, body, signal: options.signal });
        if (method === "DELETE") {
            const result = { success: false, code: "read_cancelled", http_status: 408 };
            jobs.set(id, { result });
            return result;
        }
        if (method === "GET") return jobs.get(id)?.result || pending(id);
        if (active() >= 2) return { success: false, code: "read_jobs_busy", http_status: 429 };
        if (body.player_key?.startsWith("source-")) {
            jobs.set(id, {});
            if (holdSource) return new Promise(resolve => held.push({ id, resolve, body }));
            return pending(id);
        }
        if (holdPlayer && url === "/api/player/load") return new Promise(resolve => held.push({ id, resolve, body }));
        return url === "/api/players" ? { success: true, players: [], world_name: "Synthetic" } : snapshot(body.player_key);
    };
    const createApi = () => context.window.MCBEPlayerApi.createPlayerApiClient({
        fetchFn, parseJsonResponse: data => data,
        withCsrf: () => ({ "X-CSRF-Token": "synthetic" }),
        createReadId: () => (++readId).toString(16).padStart(32, "0"),
    });
    const showLoading = (_message, options = {}) => { feedback.overlay = true; feedback.onCancel = options.onCancel; };
    const hideLoading = () => { feedback.overlay = false; feedback.onCancel = null; };
    const tools = context.window.MCBEPlayerTools.createPlayerToolsController({
        api: createApi(), elements: {
            comparePlayerSelect: selected, copySourcePlayerSelect: selected, playerToolsPanel: panel,
            copyInventoryArea: { checked: true }, copyEnderArea: { checked: false }, copyStatsArea: { checked: false },
        },
        getWorldPath: () => state.worldPath, getCurrentPlayerKey: () => state.currentPlayerKey,
        getPlayers: () => [{ player_key: selected.value, label: selected.value }],
        showConfirmDialog: async () => true, showLoading, hideLoading,
        showToast: (message, type) => feedback.toasts.push({ message, type }),
        recordAction: message => feedback.records.push(message),
        setInventory: () => { feedback.inventoryWrites++; }, pushUndo: () => { feedback.undoWrites++; },
    });
    // Exercise the production app bridge as well as the load controller: a
    // controller-only test would miss an unwired cancellation dependency.
    const app = context.window.MCBEPlayerLoadApp.createInventoryPlayerLoadApp({
        doc: { getElementById: () => null },
        state: { getPlayerLoadState: () => state, assignAppState: patch => Object.assign(state, patch) },
        feedback: { showLoading, hideLoading },
        actions: {
            cancelPlayerToolReads: () => tools.cancelPendingReads(),
            renderLoadError: error => feedback.errors.push(error),
        },
        controllerFactory: deps => context.window.MCBEPlayerLoadController.createInventoryPlayerLoadController({ ...deps, api: createApi() }),
    });
    const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
    const advance = async milliseconds => {
        const target = now + milliseconds;
        await flush();
        while (true) {
            const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
            if (!next || next[1].at > target) break;
            now = next[1].at;
            timers.delete(next[0]);
            next[1].fn();
            await flush();
        }
        now = target;
        await flush();
    };
    const posts = () => calls.filter(call => call.method === "POST");
    const deletes = () => calls.filter(call => call.method === "DELETE");
    const polls = id => calls.filter(call => call.method === "GET" && call.id === id).length;
    return { tools, app, state, feedback, panel, selected, jobs, calls, held, timers, snapshot, active, flush, advance, posts, deletes, polls };
}

for (const sameSource of [false, true]) {
    test(`a replacement comparison cancels the obsolete ${sameSource ? "same" : "different"} source without reusing its cancelled ID`, async () => {
        const h = harness();
        const first = h.tools.compareSelectedPlayer();
        await h.advance(200);
        const oldId = h.posts()[0].id;
        const oldPolls = h.polls(oldId);
        if (!sameSource) h.selected.value = "source-B";
        const second = h.tools.compareSelectedPlayer();
        await h.flush();
        assert.deepEqual(h.deletes().map(call => call.id), [oldId]);
        assert.equal(await first, false);
        const newId = h.posts()[1].id;
        assert.notEqual(newId, oldId);
        assert.equal(h.active(), 1);
        assert.equal(h.deletes()[0].signal.aborted, false, "DELETE has an independent transport");
        h.jobs.get(newId).result = h.snapshot(h.selected.value);
        await h.advance(200);
        assert.equal(await second, true);
        await h.advance(3000);
        assert.equal(h.polls(oldId), oldPolls);
        assert.match(h.panel.innerHTML, new RegExp(h.selected.value));
        assert.equal(h.feedback.records.length, 1);
        assert.deepEqual(h.feedback.toasts, []);
        assert.equal(h.timers.size, 0);
    });
}

for (const transition of ["world", "player", "reset", "list"]) {
    test(`${transition} transition cancels tool polling through the app bridge and frees read capacity`, async () => {
        const h = harness();
        const comparing = h.tools.compareSelectedPlayer();
        await h.advance(200);
        const oldId = h.posts()[0].id;
        const oldPolls = h.polls(oldId);
        // Another session already owns the other globally bounded read slot.
        h.jobs.set("other-session", {});
        let loading;
        if (transition === "world") {
            h.state.worldPath = "world-B";
            loading = h.app.loadWorldFromInput();
        } else if (transition === "player") loading = h.app.loadPlayer("next-player", true);
        else if (transition === "list") loading = h.app.loadPlayersList(false);
        else h.app.resetLoadedPlayerState();
        await h.flush();
        assert.deepEqual(h.deletes().map(call => call.id), [oldId]);
        assert.equal(await comparing, false);
        if (loading) assert.equal(await loading, true, "the fresh load has capacity without waiting for the old lease");
        await h.advance(3000);
        assert.equal(h.polls(oldId), oldPolls);
        assert.equal(h.active(), 1, "only the unrelated session remains active");
        assert.deepEqual(h.feedback.errors, []);
        assert.deepEqual(h.feedback.toasts, []);
        assert.equal(h.timers.size, 0);
    });
}

test("copy replaces a comparison of the same source and user cancellation cannot apply inventory or undo state", async () => {
    const h = harness();
    const comparing = h.tools.compareSelectedPlayer();
    await h.flush();
    const oldId = h.posts()[0].id;
    const copying = h.tools.copyFromSelectedPlayer();
    await h.flush();
    assert.deepEqual(h.deletes().map(call => call.id), [oldId]);
    assert.equal(await comparing, false);
    const copyId = h.posts()[1].id;
    assert.notEqual(copyId, oldId);
    assert.equal(h.feedback.overlay, true);
    assert.equal(typeof h.feedback.onCancel, "function");
    h.feedback.onCancel();
    await h.flush();
    assert.equal(await copying, false);
    assert.deepEqual(h.deletes().map(call => call.id), [oldId, copyId]);
    assert.equal(h.feedback.overlay, false);
    assert.equal(h.feedback.inventoryWrites, 0);
    assert.equal(h.feedback.undoWrites, 0);
    assert.equal(h.active(), 0);
    assert.deepEqual(h.feedback.toasts.filter(toast => toast.type === "error"), []);
    assert.equal(h.timers.size, 0);
});

test("an aborted copy's late response and finally cannot modify the new player or hide its loading overlay", async () => {
    const h = harness({ holdSource: true, holdPlayer: true });
    const copying = h.tools.copyFromSelectedPlayer();
    await h.flush();
    assert.equal(h.held.length, 1);
    const oldRequest = h.held[0];
    const loading = h.app.loadPlayer("next-player", true);
    await h.flush();
    assert.deepEqual(h.deletes().map(call => call.id), [oldRequest.id]);
    assert.equal(await copying, false);
    assert.equal(h.held.length, 2);
    assert.equal(h.feedback.overlay, true);
    assert.equal(h.app.isLoading(), true);
    oldRequest.resolve(h.snapshot("source-A"));
    await h.flush();
    assert.equal(h.feedback.overlay, true, "the old copy does not own the new load overlay");
    assert.equal(h.feedback.inventoryWrites, 0);
    assert.equal(h.feedback.undoWrites, 0);
    assert.deepEqual(h.feedback.toasts.filter(toast => toast.type === "error"), []);
    h.held[1].resolve(h.snapshot("next-player"));
    assert.equal(await loading, true);
    assert.equal(h.state.currentPlayerKey, "next-player");
    assert.equal(h.feedback.overlay, false);
    assert.equal(h.timers.size, 0);
});
