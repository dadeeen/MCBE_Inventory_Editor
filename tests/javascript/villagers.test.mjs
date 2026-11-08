import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const load = (context, name) => vm.runInNewContext(readFileSync(`static/${name}.js`, "utf8"), context, { filename: name });
const plain = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const row = (id = "actor:a", patch = {}) => ({ id, revision: id.repeat(8), unique_id: "-9007199254740993", name: id,
    identifier: "minecraft:villager_v2", profession: { id: "librarian", label: "Bibliothekar" }, trade_tier: 4, trade_tier_label: "Meister",
    health: { current: 12, max: 20, editable: true, max_editable: true }, position: { x: 1, y: 64, z: 1 }, dimension: 0,
    editable: true, issues: [], ...patch });
const context = { window: {}, AbortController, Date, setTimeout, clearTimeout };
load(context, "villager_model");
load(context, "villager_inventory");
const model = context.window.MCBEVillagerModel;

test("villager search preserves 64-bit IDs and filters unknown dimensions and tier zero precisely", () => {
    const rows = [row("a"), row("b", { unique_id: "-9007199254740994", dimension: null, trade_tier: 0 }), row("c", { dimension: 1 })];
    assert.deepEqual(plain(model.filterRows(rows, { query: "-9007199254740993" }).map(r => r.id)), ["a", "c"]);
    assert.deepEqual(plain(model.filterRows(rows, { dimension: "unknown", tier: "0" }).map(r => r.id)), ["b"]);
    assert.equal(model.displayName(rows[0], { a: "Hauptbibliothek" }), "a");
    assert.equal(model.displayName({ ...rows[0], name: "" }, { a: "Hauptbibliothek" }), "Hauptbibliothek");
});

test("legacy aliases follow exact stable IDs through reused slots and chunk moves", () => {
    const a = row("legacy:chunk-a:0", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740993" });
    const b = row("legacy:chunk-a:1", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740994" });
    const aliases = { [a.id]: "Unsafe positional alias", [a.alias_key]: "Library", [b.alias_key]: "Farm" };
    assert.equal(model.displayName(a, aliases), "Library");
    assert.equal(model.displayName(b, aliases), "Farm");
    const reused = { ...b, id: a.id }, moved = { ...a, id: "legacy:chunk-b:0" };
    assert.equal(model.displayName(reused, aliases), "Farm");
    assert.equal(model.displayName(moved, aliases), "Library");
    assert.deepEqual(plain(model.filterRows([reused, moved], { query: "Library" }, { aliases }).map(row => row.id)), [moved.id]);
    assert.deepEqual(plain(model.sortedRows([moved, reused], "name", "asc", { aliases }).map(row => row.id)), [reused.id, moved.id]);
    for (const unsupported of [{ ...a, alias_key: null }, row(a.id, { storage: "legacy" }), row(a.id)]) {
        assert.equal(model.aliasKey(unsupported), "");
        assert.equal(model.displayName(unsupported, aliases), unsupported.name || `Dorfbewohner #${model.shortId(unsupported)}`);
    }
    assert.equal(model.aliasKey(row("actor:modern")), "actor:modern");
});

test("injury filtering excludes dead and invalid-health records consistently with scan totals", () => {
    const rows = [row("living", { health: { current: 0.5, max: 20 } }), row("dead", { health: { current: 0, max: 20 } }),
        row("invalid", { health: { current: -2, max: 20 } }), row("healthy", { health: { current: 20, max: 20 } })];
    assert.deepEqual(plain(model.filterRows(rows, { injured: true }).map(row => row.id)), ["living"]);
});

test("named regions are dimension-specific, inclusive, support Y and overlapping membership", () => {
    const a = { id: "a", name: "Town", dimension: 0, min_x: 0, max_x: 1, min_z: 0, max_z: 1 };
    const b = { ...a, id: "b", min_y: 64, max_y: 65 };
    assert.equal(model.matchingRegions(row(), [a, b]).length, 2);
    assert.equal(model.matchingRegions(row("nether", { dimension: 1 }), [a, b]).length, 0);
    assert.equal(model.matchingRegions(row("unknown", { dimension: null }), [a, b]).length, 0);
    assert.equal(model.matchingRegions(row("low", { position: { x: 1, y: 63, z: 1 } }), [a, b]).length, 1);
    assert.equal(model.filterRows([row()], { region: "none" }, { regions: [a] }).length, 0);
});

test("health sorts numerically and unknown values stay last in either direction", () => {
    const rows = [row("a", { health: { current: 40 } }), row("b", { health: { current: 2 } }), row("c", { health: { current: null } })];
    assert.deepEqual(plain(model.sortedRows(rows, "health").map(r => r.id)), ["b", "a", "c"]);
    assert.deepEqual(plain(model.sortedRows(rows, "health", "desc").map(r => r.id)), ["a", "b", "c"]);
    assert.deepEqual(plain(model.pageRows(rows, 99, 2).rows.map(r => r.id)), ["c"]);
});

test("column sorting keeps missing names, professions, regions and invalid numeric values last", () => {
    const preferences = { aliases: { b: "Alpha" }, regions: [
        { id: "alpha", name: "Alpha", dimension: 1, min_x: 0, max_x: 2, min_z: 0, max_z: 2 },
        { id: "zulu", name: "Zulu", dimension: 0, min_x: 0, max_x: 2, min_z: 0, max_z: 2 },
    ] };
    const a = row("a", { name: "Zoe", profession: { id: "farmer", label: "Farmer" }, trade_tier: 0, dimension: 1, health: { current: 2 } });
    const b = row("b", { name: "Beta", profession: { id: "librarian", label: "Bibliothekar" }, trade_tier: 4, dimension: 0, health: { current: 40 } });
    const c = row("c", { name: "", profession: { id: "unknown", label: "Unbekannt" }, trade_tier: Number.NaN, dimension: Infinity,
        position: null, health: { current: Number.NaN } });
    for (const [criterion, expected] of Object.entries({ name: ["b", "a", "c"], profession: ["b", "a", "c"], tier: ["a", "b", "c"],
        health: ["a", "b", "c"], region: ["a", "b", "c"], dimension: ["b", "a", "c"] })) {
        assert.deepEqual(plain(model.sortedRows([c, a, b], criterion, "asc", preferences).map(row => row.id)), expected, criterion);
        assert.deepEqual(plain(model.sortedRows([c, a, b], criterion, "desc", preferences).map(row => row.id)), [expected[1], expected[0], expected[2]], criterion);
    }
});

test("profession sorting uses translated labels and stable IDs break ties", () => {
    const ctx = { window: { t: value => ({ Farmer: "Z farmer", Bibliothekar: "A librarian" })[value] || value } };
    load(ctx, "villager_model");
    const rows = [row("b", { profession: { id: "farmer", label: "Farmer" } }), row("c"), row("a")];
    const sorted = ctx.window.MCBEVillagerModel.sortedRows;
    assert.deepEqual(plain(sorted(rows, "profession", "asc").map(row => row.id)), ["a", "c", "b"]);
    assert.deepEqual(plain(sorted(rows, "profession", "desc").map(row => row.id)), ["b", "a", "c"]);
});

test("health actions distinguish untouched values from explicit healing and reject invalid numbers", () => {
    assert.deepEqual(plain(model.healthChanges({ max: "40", current: "12", heal: true })), { max_health: 40, heal: true });
    assert.deepEqual(plain(model.healthChanges({ current: "1.5" })), { current_health: 1.5 });
    for (const max of ["", "0", "-1", "2049", "NaN", "Infinity", "letters"]) assert.throws(() => model.healthChanges({ max }));
    assert.throws(() => model.healthChanges({ max: "20", current: "40" }));
});

test("map coordinates never overflow and do not mix dimensions or infer unknown locations", () => {
    const points = model.mapPoints([row(), row("b", { position: { x: 1e308, y: 64, z: -1e308 } }), row("n", { dimension: 1 })], 0);
    assert.equal(points.total, 1);
    assert.equal(points.points[0].x, 50);
    assert.equal(points.points[0].z, 50);
    assert.equal(model.healthNumber(1e308), "1e+308");
    const bounds = model.mapPoints([row("a", { position: { x: -(2 ** 35), y: 0, z: 2 ** 35 } }), row("b", { position: { x: 2 ** 35, y: 0, z: -(2 ** 35) } })], 0);
    assert.ok(bounds.points.every(point => Number.isFinite(point.x) && Number.isFinite(point.z) && point.x >= 0 && point.x <= 100));
});

test("region inputs require complete optional Y bounds and ordered finite coordinates", () => {
    const valid = { id: "a", name: " Village ", dimension: "0", min_x: "-10", max_x: "10", min_z: "-5", max_z: "5" };
    assert.deepEqual(plain(model.normalizeRegion(valid)), { id: "a", name: "Village", dimension: 0, min_x: -10, max_x: 10, min_z: -5, max_z: 5 });
    for (const patch of [{ min_y: "4" }, { min_x: "11" }, { max_z: "Infinity" }, { name: "" }, { dimension: "" }]) assert.throws(() => model.normalizeRegion({ ...valid, ...patch }));
});

test("world, server guard and fingerprint each invalidate a snapshot independently", () => {
    const snapshot = { worldPath: "A", worldRevision: "v1", guardToken: "t1", guardEpoch: 3 };
    for (const patch of [{ worldPath: "B" }, { guardToken: "t2" }, { guardEpoch: 4 }, { serverOnline: true }, { worldRevision: "v2" }]) {
        assert.equal(model.snapshotIsStale(snapshot, { worldPath: "A", ...patch }), true);
    }
    assert.equal(model.snapshotIsStale(snapshot, { worldPath: "A", worldRevision: "v1", guardToken: "t1", guardEpoch: 99 }), false);
});

test("typed NBT view escapes untrusted names and handles scalar arrays without losing 64-bit strings", () => {
    const ctx = { window: {} };
    load(ctx, "html_utils"); load(ctx, "villager_model"); load(ctx, "villager_inventory"); load(ctx, "villager_view");
    const html = ctx.window.MCBEVillagerView.nbtTree({ type: "CompoundTag", value: {
        '<img src="x">': { type: "StringTag", value: "<script>throw 1</script>" },
        data: { type: "LongArrayTag", value: ["9223372036854775807", -3] },
    } });
    assert.ok(!html.includes("<img") && !html.includes("<script>"));
    assert.ok(html.includes("9223372036854775807") && html.includes("-3"));
    assert.ok(!html.includes("Weitere Rohdaten"));
    const shortened = ctx.window.MCBEVillagerView.nbtTree({ type: "StringTag", value: "a...", truncated: "200 weitere Zeichen" });
    assert.ok(shortened.includes("200 weitere Zeichen"));
    const limited = ctx.window.MCBEVillagerView.nbtTree({ type: "ByteArrayTag", value: [1, 2, 3] }, "data", { left: 2 });
    assert.ok(limited.includes("Weitere Rohdaten sind ausgeblendet."));
});

function viewHarness() {
    const ctx = { window: {} };
    load(ctx, "html_utils"); load(ctx, "villager_model"); load(ctx, "villager_inventory"); load(ctx, "villager_view");
    const nodes = new Map();
    const node = id => {
        if (!nodes.has(id)) nodes.set(id, { value: "", innerHTML: "", textContent: "", open: false, dataset: {}, contains: () => false,
            classList: { toggle() {} }, setAttribute() {}, addEventListener() {}, querySelectorAll: () => id === "villagerRegionForm" ? [node("regionName")] : [] });
        return nodes.get(id);
    };
    return { node, view: ctx.window.MCBEVillagerView.createVillagerView({ doc: { activeElement: null, getElementById: node } }) };
}

test("equipment shows seven empty saved slots in armor and hand groups with zero occupied", () => {
    const { node, view } = viewHarness(), state = harness().controller.getState();
    const slots = ["Armor", "Mainhand", "Offhand"].flatMap(container => Array.from({ length: container === "Armor" ? 5 : 1 }, (_, index) => ({
        container, index, slot: `${container}[${index}]`, state: "empty", item: { name: "", count: 0 },
    })));
    view.renderDetail(row("a", { equipment: { slots, total: 7, occupied_count: 0 } }), state);
    const html = node("villagerDetail").innerHTML;
    assert.match(html, /Ausrüstung \(0 belegt\)/);
    assert.match(html, /Rüstung \(Armor\)/);
    assert.match(html, /Haupt- und Nebenhand/);
    for (const label of ["Kopf", "Brust", "Beine", "Füße", "Zusatzslot (Body)", "Haupthand", "Nebenhand"]) assert.ok(html.includes(label));
    assert.equal((html.match(/class="villager-equipment-empty">Leer</g) || []).length, 7);
    assert.doesNotMatch(html, /0 × Unbekannt/);
});

test("equipment preserves unknown extra slots, escapes items, and never offers equipment edits", () => {
    const { node, view } = viewHarness(), state = harness().controller.getState();
    view.renderDetail(row("a", { equipment: { total: 2, occupied_count: 1, unknown_count: 1, slots: [
        { container: "Mainhand", index: 0, slot: "Mainhand[0]", state: "occupied", item: { name: "minecraft:carrot", count: 12 } },
        { container: "Armor", index: 5, slot: "Armor[5]", state: "unknown", item: { name: "<img src=x onerror=alert(1)>", count: null } },
    ] } }), state);
    const html = node("villagerDetail").innerHTML.split('<details id="villagerEquipmentDetails"')[1].split("</details>")[0];
    assert.match(html, /Ausrüstung \(1 belegt, weitere unklar\)/);
    assert.match(html, /12 × minecraft:carrot/);
    assert.match(html, /Zusätzlicher Rüstungsplatz 6/);
    assert.match(html, /Nicht eindeutig lesbar/);
    assert.match(html, /&lt;img/);
    assert.doesNotMatch(html, /<img|<input|<select|<button|<form/);
});

test("equipment distinguishes opaque containers from absent slots and exposes truncation", () => {
    const { node, view } = viewHarness(), state = harness().controller.getState();
    view.renderDetail(row("a", { equipment: { total: 81, occupied_count: 2, unknown_containers: ["Armor"], slots: [], containers: [
        { container: "Armor", present: true, total: null },
        { container: "Mainhand", present: true, total: 81, truncated: true },
        { container: "Offhand", present: false, total: 0 },
    ] } }), state);
    const html = node("villagerDetail").innerHTML;
    assert.match(html, /Ausrüstung \(2 belegt, weitere unklar\)/);
    assert.match(html, /Nicht eindeutig lesbar/);
    assert.match(html, /Nicht gespeichert/);
    assert.match(html, /Weitere gespeicherte Plätze sind ausgeblendet/);
    view.renderDetail(row("a", { equipment: { slots: [], containers: [{ container: "Armor", present: true, total: 0 }] } }), state);
    assert.match(node("villagerDetail").innerHTML, /Keine Plätze gespeichert\./);
});

test("preferences writes disable alias and region inputs without replacing their pending text", () => {
    const h = harness(), { node, view } = viewHarness();
    const state = h.controller.getState();
    state.activeId = "a"; state.detail = row("a");
    state.preferencesBusy = true;
    node("villagerAlias").value = "Keep this draft";
    view.render(state);
    assert.equal(node("villagerAlias").disabled, true);
    assert.equal(node("regionName").disabled, true);
    assert.equal(node("villagerAlias").value, "Keep this draft");
    state.preferencesBusy = false;
    view.render(state);
    assert.equal(node("villagerAlias").disabled, false);
    assert.equal(node("regionName").disabled, false);
});

test("legacy records without stable identity explain and disable alias editing", () => {
    const h = harness(), { node, view } = viewHarness();
    const state = h.controller.getState();
    state.detail = row("legacy:chunk:0", { name: "", storage: "legacy", alias_key: null });
    state.activeId = state.detail.id;
    state.preferences.aliases[state.activeId] = "Unsafe positional alias";
    view.renderDetail(state.detail, state); view.render(state);
    assert.equal(node("villagerAlias").disabled, true);
    assert.equal(node("villagerAliasSave").disabled, true);
    assert.match(node("villagerDetail").innerHTML, /keine eindeutige, dauerhafte Kennung/);
    assert.doesNotMatch(node("villagerDetail").innerHTML, /Unsafe positional alias/);
});

test("region dimensions remain selectable even when no villager is present in that dimension", () => {
    const h = harness(), { node, view } = viewHarness();
    const state = h.controller.getState();
    state.preferences.regions = [{ id: "remote", name: "Remote village", dimension: 7, min_x: 0, max_x: 10, min_z: 0, max_z: 10 }];
    view.render(state);
    assert.match(node("villagerRegionDimension").innerHTML, /<option value="7">Dimension 7<\/option>/);
    node("villagerRegionDimension").value = "7";
    view.render(state);
    assert.equal(node("villagerRegionDimension").value, "7");
});

function harness({ rows = [row("a"), row("b")], readOnly = false } = {}) {
    let now = 100;
    const nodes = new Map();
    const doc = { activeElement: null, defaultView: { innerWidth: 1440, getSelection: () => ({ toString: () => "" }) } };
    const matches = (node, selector) => {
        const inputs = /(?:Max|Current|Heal|Alias|Search|RegionName|RegionMin[XYZ]|RegionMax[XYZ])$/.test(node.id);
        if (selector.split(",").some(part => part.trim() === `#${node.id}`)) return true;
        return inputs && selector.split(",").some(part => ["input", "textarea", "select"].includes(part.trim()));
    };
    const node = id => {
        if (!nodes.has(id)) nodes.set(id, {
            id, value: "", checked: false, open: false, disabled: false, listeners: {}, dataset: {}, validity: { badInput: false },
            isConnected: true, classList: { toggle() {}, contains: () => false },
            showModal() { this.open = true; }, close() { this.open = false; },
            reset() {
                if (id === "villagerRegionForm") for (const [key, control] of nodes) {
                    if (key.startsWith("villagerRegion") && !key.endsWith("Dimension")) control.value = "";
                    if (key === "villagerRegionDimension") control.value = "0";
                }
            },
            focus() { doc.activeElement = this; }, scrollIntoView() {},
            matches(selector) { return matches(this, selector); },
            contains(other) {
                if (!other) return false;
                if (id === "villagerDetail") return other.id.startsWith("villagerDetail") || other.id.startsWith("villagerAlias");
                if (id === "villagerRows") return other.dataset?.action === "detail";
                return other === this;
            },
            closest(selector) {
                if (matches(this, selector)) return this;
                for (const [prefix, form] of [["villagerDetail", "villagerDetailHealthForm"], ["villagerAlias", "villagerAliasForm"], ["villagerBatch", "villagerBatchForm"], ["villagerRegion", "villagerRegionForm"]]) {
                    if (id.startsWith(prefix) && selector.includes(`#${form}`)) return node(form);
                }
                if ((id.startsWith("villagerDetail") || id.startsWith("villagerAlias")) && selector.includes("#villagerDetail")) return node("villagerDetail");
                return null;
            },
            querySelectorAll(selector) {
                if (id === "villagerRows" && selector.includes("detail")) return rows.map(row => node(`row:${row.id}`));
                return [];
            },
            addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
            dispatch(type, event = {}) { for (const handler of this.listeners[type] || []) handler({ target: this, preventDefault() {}, ...event }); },
        });
        return nodes.get(id);
    };
    doc.getElementById = node;
    doc.querySelector = selector => selector.includes("dialog") && node("villagerPreviewDialog").open ? node("villagerPreviewDialog") : null;
    for (const row of rows) node(`row:${row.id}`).dataset = { id: row.id, action: "detail" };
    const world = { path: "A", view: "villagers", guard: { token: "guard-1", epoch: 1 }, gate: { allowed: true }, revision: "v1" };
    const calls = { scans: [], details: [], previews: [], saves: [], preferences: [], confirmations: [], toasts: [], busy: [], detailRenders: [], previewRenders: [] };
    const response = () => ({ success: true, villagers: plain(rows), world_revision: world.revision, server_guard_epoch: 1, server_guard_token: "guard-1",
        preferences: { revision: "p1", aliases: {}, regions: [] }, diagnostics: [] });
    const api = {
        scan: async (...args) => { calls.scans.push(args); return response(); },
        detail: async (payload, opts) => { calls.details.push([payload, opts]); return { success: true, villager: plain(rows.find(row => row.id === payload.id)) }; },
        preview: async (payload, opts) => { calls.previews.push([payload, opts]); return { success: true, rows: [], change_count: 1, preview_token: "token" }; },
        save: async payload => {
            calls.saves.push(payload); world.revision = "v2";
            const requested = calls.previews.at(-1)?.[0];
            for (const selected of requested?.selection || []) {
                const target = rows.find(row => row.id === selected.id);
                if (!target?.editable) continue;
                target.health.max = requested.changes.max_health ?? target.health.max;
                target.health.current = requested.changes.heal ? target.health.max : requested.changes.current_health ?? target.health.current;
            }
            return { success: true, write_committed: true, changed_count: 1 };
        },
        savePreferences: async payload => { calls.preferences.push(payload); return { success: true, preferences: { ...payload, revision: "p2" } }; },
    };
    const view = { element: node, render: state => model.pageRows(model.filterRows(state.rows, state.filters, state.preferences), state.page, state.pageSize),
        renderDetail: (row, state, options = {}) => {
            calls.detailRenders.push(row);
            if (options.loading || options.error) return;
            node("villagerDetailMax").value = String(row?.health?.max ?? "");
            node("villagerDetailCurrent").value = String(row?.health?.current ?? "");
            node("villagerDetailHeal").checked = false;
            node("villagerAlias").value = row ? state.preferences.aliases[model.aliasKey(row)] || "" : "";
        }, renderPreview: row => calls.previewRenders.push(row) };
    const ctx = { window: { MCBEVillagerModel: model }, AbortController, Date: { now: () => now }, setTimeout, clearTimeout };
    load(ctx, "villager_controller");
    let confirmation = true;
    const controller = ctx.window.MCBEVillagerController.createVillagerController({ doc, api, view, getWorldPath: () => world.path,
        getWorldLabel: () => world.path, getActiveView: () => world.view, getWriteGate: () => world.gate, getServerGuard: () => world.guard, getReadOnly: () => readOnly,
        getSessionId: () => "session-1", showConfirmDialog: async (...args) => { calls.confirmations.push(args); return confirmation; }, confirmPresenceConflict: async () => confirmation,
        showToast: (...args) => calls.toasts.push(args), onBusyChanged: () => calls.busy.push(controller.isSaving()),
    });
    controller.wire();
    const prepare = async () => {
        await controller.scan();
        controller.getState().selected.add("a");
        node("villagerBatchHeal").checked = true;
        await controller.preview();
    };
    return { controller, api, calls, nodes, node, doc, world, rows, response, prepare,
        setNow: value => { now = value; }, confirm: value => { confirmation = value; } };
}

async function commit(h) {
    await h.controller.save();
    if (!h.controller.getPendingChanges().length) return;
    const result = await h.api.save({ session_id: "session-1" });
    h.controller.finalizePending(result);
    await h.controller.refreshAfterSave();
}

test("world switching cancels scans and a late previous-world response cannot populate the new world", async () => {
    const h = harness(), pending = deferred();
    h.api.scan = async (...args) => { h.calls.scans.push(args); return pending.promise; };
    const scan = h.controller.scan();
    h.world.path = "B";
    h.controller.updateContext();
    assert.equal(h.calls.scans[0][1].signal.aborted, true);
    pending.resolve(h.response()); await scan;
    assert.equal(h.controller.getState().worldPath, "B");
    assert.equal(h.controller.getState().loaded, false);
    assert.equal(h.controller.getState().rows.length, 0);
});

test("selecting a different villager aborts the old detail and ignores reversed response order", async () => {
    const h = harness(), a = deferred(), b = deferred();
    await h.controller.scan();
    h.api.detail = async (payload, opts) => { h.calls.details.push([payload, opts]); return payload.id === "a" ? a.promise : b.promise; };
    const first = h.controller.openDetail("a"), second = h.controller.openDetail("b");
    assert.equal(h.calls.details[0][1].signal.aborted, true);
    b.resolve({ success: true, villager: h.rows[1] }); await second;
    a.resolve({ success: true, villager: h.rows[0] }); await first;
    assert.equal(h.controller.getState().detail.id, "b");
    assert.equal(h.calls.detailRenders.at(-1).id, "b");
});

test("old presence polls do not stale a new scan, while new fingerprints block details and writes", async () => {
    const h = harness();
    await h.prepare();
    h.controller.observeWorldStatus({ world_fingerprint: "old" }, { worldPath: "A", startedAt: 99 });
    assert.equal(h.controller.getState().staleReason, "");
    h.controller.observeWorldStatus({ world_fingerprint: "new" }, { worldPath: "A", startedAt: 101 });
    assert.ok(h.controller.getState().staleReason);
    assert.equal(h.controller.getState().preview, null);
    await h.controller.openDetail("a"); await commit(h);
    assert.equal(h.calls.details.length, 0);
    assert.equal(h.calls.saves.length, 0);
});

test("preview includes exact selected record revisions and never submits current health with heal", async () => {
    const h = harness(); await h.controller.scan();
    h.controller.getState().selected.add("a"); h.controller.getState().selected.add("b");
    h.node("villagerBatchMax").value = "40"; h.node("villagerBatchCurrent").value = "17"; h.node("villagerBatchHeal").checked = true;
    await h.controller.preview();
    const payload = h.calls.previews[0][0];
    assert.deepEqual(plain(payload.selection), h.rows.map(({ id, revision }) => ({ id, revision })));
    assert.deepEqual(plain(payload.changes), { max_health: 40, heal: true });
    assert.equal(payload.world_revision, "v1");
    assert.equal(payload.server_guard_token, "guard-1");
});

test("changing an input during delayed preview cancels it and releases busy state", async () => {
    const h = harness(), pending = deferred(); await h.controller.scan();
    await h.controller.openDetail("a");
    h.controller.getState().selected.add("a"); h.node("villagerBatchHeal").checked = true;
    h.api.preview = async (payload, options) => { h.calls.previews.push([payload, options]); return pending.promise; };
    const preview = h.controller.preview();
    assert.equal(h.controller.getState().busy, true);
    input(h, "villagerAlias", "Changed during preview");
    assert.equal(h.calls.previews[0][1].signal.aborted, true);
    assert.equal(h.controller.getState().busy, false);
    pending.resolve({ success: true, change_count: 1, preview_token: "obsolete" }); await preview;
    assert.equal(h.controller.getState().preview, null);
    assert.equal(h.node("villagerPreviewDialog").open, false);
});

test("closing the inspector cancels its pending health preview", async () => {
    const h = harness(), pending = deferred();
    await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailCurrent", "18");
    h.api.preview = async (payload, options) => { h.calls.previews.push([payload, options]); return pending.promise; };
    const preview = h.controller.preview(true);
    await h.controller.closeDetail();
    assert.equal(h.controller.getState().activeId, "");
    assert.equal(h.calls.previews[0][1].signal.aborted, true);
    pending.resolve({ success: true, rows: [], change_count: 1, preview_token: "closed-inspector" });
    await preview;
    assert.equal(h.controller.getState().preview, null);
    assert.equal(h.controller.getState().busy, false);
    assert.equal(h.node("villagerPreviewDialog").open, false);
});

test("a delayed preview cannot open a modal in another workspace", async () => {
    const h = harness(), pending = deferred();
    await h.controller.scan();
    h.controller.getState().selected.add("a");
    input(h, "villagerBatchMax", "40");
    h.api.preview = async () => pending.promise;
    const preview = h.controller.preview();
    h.world.view = "inventory";
    h.node("otherWorkspaceControl").focus();
    pending.resolve({ success: true, rows: [], change_count: 1, preview_token: "hidden-workspace" });
    await preview;
    assert.equal(h.node("villagerPreviewDialog").open, false);
    assert.equal(h.controller.getState().preview, null);
    assert.equal(h.controller.getState().busy, false);
    assert.equal(h.controller.getState().message, "");
    assert.equal(h.doc.activeElement, h.node("otherWorkspaceControl"));
    assert.equal(h.node("villagerBatchMax").value, "40");
    assert.equal(h.controller.getState().batchDirty, true);
});

test("leaving and returning to the workspace invalidates an old preview without discarding drafts", async () => {
    const h = harness(), pending = deferred();
    await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailCurrent", "18");
    input(h, "villagerAlias", "Pending alias");
    input(h, "villagerRegionName", "Pending region");
    h.controller.getState().selected.add("b");
    input(h, "villagerBatchMax", "40");
    h.api.preview = async (payload, options) => { h.calls.previews.push([payload, options]); return pending.promise; };
    const preview = h.controller.preview();
    h.world.view = "inventory";
    h.controller.deactivate();
    assert.equal(h.calls.previews[0][1].signal.aborted, true);
    h.world.view = "villagers";
    await h.controller.activate();
    pending.resolve({ success: true, rows: [], change_count: 1, preview_token: "prior-visit" });
    await preview;
    assert.equal(h.node("villagerPreviewDialog").open, false);
    assert.equal(h.controller.getState().busy, false);
    assert.equal(h.controller.getState().message, "");
    for (const dirty of ["detailDirty", "aliasDirty", "regionDirty", "batchDirty"]) assert.equal(h.controller.getState()[dirty], true, dirty);
    assert.equal(h.node("villagerDetailCurrent").value, "18");
    assert.equal(h.node("villagerAlias").value, "Pending alias");
    assert.equal(h.node("villagerRegionName").value, "Pending region");
    assert.equal(h.node("villagerBatchMax").value, "40");
    assert.deepEqual([...h.controller.getState().selected], ["b"]);
});

test("maximum-protected records can still preview current health without resubmitting maximum", async () => {
    const h = harness({ rows: [row("a", { health: { current: 12, max: 20, editable: true, max_editable: false } })] });
    await h.controller.scan(); await h.controller.openDetail("a");
    h.node("villagerDetailMax").value = "20"; h.node("villagerDetailCurrent").value = "19";
    await h.controller.preview(true);
    assert.deepEqual(plain(h.calls.previews[0][0].changes), { current_health: 19 });
});

test("single edits preserve untouched fractional health and still reject new values below one", async () => {
    const h = harness({ rows: [row("a", { health: { current: 0.5, max: 20, editable: true, max_editable: true } })] });
    await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailMax", "40");
    await h.controller.preview(true);
    assert.equal(h.calls.previews.length, 1);
    assert.deepEqual(plain(h.calls.previews[0][0].changes), { max_health: 40 });
    await commit(h);
    assert.equal(h.rows[0].health.max, 40);
    assert.equal(h.rows[0].health.current, 0.5);
    input(h, "villagerDetailCurrent", "0.75");
    await h.controller.preview(true);
    assert.equal(h.calls.previews.length, 1);
    assert.equal(h.node("villagerPreviewDialog").open, false);
});

test("preview acceptance only stages changes and never writes or creates a backup", async () => {
    const h = harness(); await h.prepare();
    await h.controller.save(); await h.controller.save();
    assert.equal(h.calls.saves.length, 0);
    assert.equal(h.calls.scans.length, 1);
    assert.equal(h.controller.getPendingChanges().length, 1);
    assert.equal(h.controller.getPendingChanges()[0].token, "token");
    assert.equal(h.controller.getState().preview, null);
    assert.equal(h.controller.hasPendingChanges(), true);
    h.controller.removePending(0);
    assert.equal(h.controller.getPendingChanges().length, 0);
});

test("rescan discards queued previews only after confirmation", async () => {
    const h = harness(); await h.prepare(); await h.controller.save();
    h.confirm(false); await h.controller.scan();
    assert.equal(h.controller.getPendingChanges().length, 1);
    h.confirm(true); await h.controller.scan();
    assert.equal(h.controller.getPendingChanges().length, 0);
    assert.equal(h.calls.saves.length, 0);
});

test("preference conflicts preserve drafts and never silently resubmit a replacement", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerAlias", "new");
    h.api.savePreferences = async payload => { h.calls.preferences.push(payload); return { success: false, code: "villager_preferences_stale", error: "Changed elsewhere" }; };
    await h.controller.savePreferences({ aliases: { a: "new" }, regions: [] });
    assert.equal(h.calls.preferences.length, 1);
    assert.equal(h.controller.getState().preferences.revision, "p1");
    assert.equal(h.controller.getState().aliasDirty, true);
});

test("saving region settings cannot re-render away an unrelated pending alias", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerAlias", "Pending alias");
    const count = h.calls.detailRenders.length;
    await h.controller.savePreferences({ aliases: {}, regions: [] });
    assert.equal(h.calls.detailRenders.length, count);
    assert.equal(h.controller.getState().aliasDirty, true);
});

test("alias edits save under stable legacy identity and reject an unavailable identity", async () => {
    const legacy = row("legacy:chunk:0", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740993" });
    const h = harness({ rows: [legacy] });
    h.api.scan = async () => ({ ...h.response(), preferences: { revision: "p1", aliases: { [legacy.alias_key]: "Stored alias" }, regions: [] } });
    await h.controller.scan(); await h.controller.openDetail(legacy.id);
    assert.equal(h.node("villagerAlias").value, "Stored alias");
    input(h, "villagerAlias", "New alias");
    h.node("villagersPanel").dispatch("submit", { target: h.node("villagerAliasForm") });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(plain(h.calls.preferences[0].aliases), { [legacy.alias_key]: "New alias" });
    assert.equal(h.controller.getState().aliasDirty, false);
    input(h, "villagerAlias", "");
    h.node("villagersPanel").dispatch("submit", { target: h.node("villagerAliasForm") });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(plain(h.calls.preferences[1].aliases), {});
    assert.equal(h.controller.getState().aliasDirty, false);

    legacy.alias_key = null;
    await h.controller.scan({ discard: true }); await h.controller.openDetail(legacy.id);
    input(h, "villagerAlias", "Cannot be assigned safely");
    h.node("villagersPanel").dispatch("submit", { target: h.node("villagerAliasForm") });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.controller.getState().aliasDirty, false);
    assert.equal(h.calls.preferences.length, 2);
});

function input(h, id, value) {
    const control = h.node(id);
    if (typeof value === "boolean") control.checked = value;
    else control.value = value;
    control.focus();
    h.node("villagersPanel").dispatch("input", { target: control });
}

test("health, alias and region dirty states clear when the actual original values are restored", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailMax", "20.00");
    assert.equal(h.controller.getState().detailDirty, false);
    input(h, "villagerDetailCurrent", "18");
    assert.equal(h.controller.getState().detailDirty, true);
    input(h, "villagerDetailCurrent", "12");
    assert.equal(h.controller.getState().detailDirty, false);
    input(h, "villagerDetailHeal", true);
    assert.equal(h.controller.getState().detailDirty, true);
    input(h, "villagerDetailHeal", false);
    assert.equal(h.controller.getState().detailDirty, false);
    h.node("villagerDetailCurrent").validity.badInput = true;
    input(h, "villagerDetailCurrent", "");
    assert.equal(h.controller.getState().detailDirty, true);
    h.node("villagerDetailCurrent").validity.badInput = false;
    input(h, "villagerDetailCurrent", "12");
    input(h, "villagerAlias", "Village librarian");
    assert.equal(h.controller.getState().aliasDirty, true);
    input(h, "villagerAlias", "");
    assert.equal(h.controller.getState().aliasDirty, false);
    input(h, "villagerRegionName", "Main village");
    assert.equal(h.controller.getState().regionDirty, true);
    input(h, "villagerRegionName", "");
    assert.equal(h.controller.getState().regionDirty, false);
    assert.equal(h.controller.hasPendingChanges(), false);
});

test("discarding health drafts preserves selection and unrelated alias and region drafts", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    h.controller.getState().selected.add("a");
    input(h, "villagerAlias", "Do not discard my alias");
    input(h, "villagerRegionName", "Do not discard my region");
    input(h, "villagerDetailCurrent", "18");
    input(h, "villagerBatchMax", "40");
    await h.controller.resetDetail();
    assert.equal(h.node("villagerDetailCurrent").value, "12");
    assert.equal(h.controller.getState().detailDirty, false);
    assert.equal(h.controller.getState().batchDirty, true);
    await h.controller.resetBatch();
    assert.equal(h.node("villagerBatchMax").value, "");
    assert.equal(h.controller.getState().batchDirty, false);
    assert.deepEqual([...h.controller.getState().selected], ["a"]);
    assert.equal(h.node("villagerAlias").value, "Do not discard my alias");
    assert.equal(h.node("villagerRegionName").value, "Do not discard my region");
    assert.equal(h.controller.getState().aliasDirty, true);
    assert.equal(h.controller.getState().regionDirty, true);
});

test("an accepted health write and automatic rescan preserve unsaved editor metadata", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerAlias", "Unsaved alias");
    input(h, "villagerRegionName", "Unsaved region");
    input(h, "villagerRegionMinX", "-20");
    input(h, "villagerRegionMaxX", "20");
    input(h, "villagerRegionMinZ", "-10");
    input(h, "villagerRegionMaxZ", "10");
    h.controller.getState().selected.add("b");
    input(h, "villagerBatchMax", "40"); input(h, "villagerBatchHeal", true);
    await h.controller.preview(); await commit(h);
    assert.equal(h.calls.saves.length, 1);
    assert.equal(h.calls.scans.length, 2);
    assert.equal(h.node("villagerAlias").value, "Unsaved alias");
    assert.equal(h.node("villagerRegionName").value, "Unsaved region");
    assert.equal(h.node("villagerRegionMinX").value, "-20");
    assert.equal(h.node("villagerRegionMaxZ").value, "10");
    assert.equal(h.controller.getState().aliasDirty, true);
    assert.equal(h.controller.getState().regionDirty, true);
    assert.equal(h.controller.getState().batchDirty, false);
    assert.equal(h.controller.hasPendingChanges(), true);
    assert.equal(h.calls.preferences.length, 0);
});

test("a batch write preserves only the independently edited single-health fields over fresh values", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailCurrent", "17");
    h.controller.getState().selected.add("a");
    input(h, "villagerBatchMax", "40"); input(h, "villagerBatchHeal", true);
    await h.controller.preview(); await commit(h);
    assert.equal(h.rows[0].health.max, 40);
    assert.equal(h.rows[0].health.current, 40);
    assert.equal(h.node("villagerDetailMax").value, "40");
    assert.equal(h.node("villagerDetailCurrent").value, "17");
    assert.equal(h.controller.getState().detailDirty, true);
    assert.equal(h.controller.getState().batchDirty, false);
});

test("a single-villager save keeps a separate unconfirmed batch draft and selection", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    h.controller.getState().selected.add("b");
    input(h, "villagerBatchMax", "40");
    input(h, "villagerDetailCurrent", "18");
    await h.controller.preview(true); await commit(h);
    assert.deepEqual([...h.controller.getState().selected], ["b"]);
    assert.equal(h.node("villagerBatchMax").value, "40");
    assert.equal(h.controller.getState().batchDirty, true);
    assert.equal(h.controller.getState().detailDirty, false);
    assert.equal(h.rows[0].health.current, 18);
    assert.equal(h.rows[1].health.max, 20);
});

test("automatic refresh follows a moved legacy detail without assigning its drafts to a reused slot", async () => {
    const a = row("legacy:chunk-a:0", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740993" });
    const b = row("legacy:chunk-a:1", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740994" });
    const h = harness({ rows: [a, b, row("actor:c")] });
    await h.controller.scan(); await h.controller.openDetail(a.id);
    input(h, "villagerDetailCurrent", "17");
    input(h, "villagerAlias", "Pending library alias");
    h.controller.getState().selected.add("actor:c");
    input(h, "villagerBatchMax", "40");
    const save = h.api.save;
    h.api.save = async payload => {
        const result = await save(payload);
        b.id = a.id; a.id = "legacy:chunk-b:0";
        a.revision = "moved-library"; b.revision = "reused-slot";
        return result;
    };
    await h.controller.preview(); await commit(h);
    assert.equal(h.controller.getState().staleReason, "");
    assert.equal(h.controller.getState().activeId, a.id);
    assert.equal(h.controller.getState().detail.alias_key, a.alias_key);
    assert.equal(h.node("villagerDetailCurrent").value, "17");
    assert.equal(h.node("villagerAlias").value, "Pending library alias");
    assert.equal(h.controller.getState().detailDirty, true);
    assert.equal(h.controller.getState().aliasDirty, true);
    h.node("villagersPanel").dispatch("submit", { target: h.node("villagerAliasForm") });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(plain(h.calls.preferences[0].aliases), { [a.alias_key]: "Pending library alias" });
    assert.equal(model.displayName(b, h.controller.getState().preferences.aliases), b.name || `Dorfbewohner #${model.shortId(b)}`);
});

test("automatic refresh preserves and blocks a vanished legacy detail instead of transplanting its drafts", async () => {
    const a = row("legacy:chunk:0", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740993" });
    const b = row("legacy:chunk:1", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740994" });
    const h = harness({ rows: [a, b, row("actor:c")] });
    await h.controller.scan(); await h.controller.openDetail(a.id);
    input(h, "villagerDetailCurrent", "17");
    input(h, "villagerAlias", "Pending library alias");
    h.controller.getState().selected.add("actor:c");
    input(h, "villagerBatchMax", "40");
    const save = h.api.save;
    h.api.save = async payload => {
        const result = await save(payload);
        h.rows.splice(0, 1); b.id = a.id; b.revision = "reused-slot";
        return result;
    };
    await h.controller.preview(); await commit(h);
    assert.ok(h.controller.getState().staleReason);
    assert.match(h.controller.getState().message, /nicht mehr vorhanden/);
    assert.equal(h.controller.getState().detail.alias_key, a.alias_key);
    assert.equal(h.node("villagerDetailCurrent").value, "17");
    assert.equal(h.node("villagerAlias").value, "Pending library alias");
    assert.equal(h.controller.getState().detailDirty, true);
    assert.equal(h.controller.getState().aliasDirty, true);
    assert.equal(h.calls.details.length, 1);
    await h.controller.preview(true);
    assert.equal(h.calls.previews.length, 1);
});

test("automatic refresh retains batch selections by legacy identity without selecting replacements", async () => {
    for (const removed of [false, true]) {
        const a = row("legacy:chunk:0", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740993" });
        const b = row("legacy:chunk:1", { name: "", storage: "legacy", alias_key: "legacy-uid:-9007199254740994" });
        const h = harness({ rows: [a, b, row("actor:c")] });
        await h.controller.scan(); await h.controller.openDetail("actor:c");
        h.controller.getState().selected.add(a.id);
        input(h, "villagerBatchMax", "40");
        input(h, "villagerDetailCurrent", "18");
        const save = h.api.save;
        h.api.save = async payload => {
            const result = await save(payload);
            b.id = a.id;
            if (removed) h.rows.splice(0, 1);
            else a.id = "legacy:other-chunk:0";
            return result;
        };
        await h.controller.preview(true); await commit(h);
        assert.equal(h.controller.getState().staleReason, "");
        assert.deepEqual([...h.controller.getState().selected], removed ? [] : [a.id]);
        assert.equal(h.controller.getState().batchDirty, true);
        assert.equal(h.node("villagerBatchMax").value, "40");
        assert.equal(h.controller.getState().selected.has(b.id), false);
    }
});

test("health-save rescans refresh a clean region baseline but retain the original revision for pending settings", async () => {
    for (const draft of ["none", "alias", "region"]) {
        const h = harness();
        const original = { id: "town", name: "Town", dimension: 0, min_x: 0, max_x: 10, min_z: 0, max_z: 10 };
        h.api.scan = async (...args) => {
            h.calls.scans.push(args);
            const changed = h.calls.scans.length > 1;
            return { ...h.response(), preferences: { revision: changed ? "p2" : "p1", aliases: changed ? { a: "External alias" } : {},
                regions: [{ ...original, ...(changed ? { name: "Expanded town", max_x: 50 } : {}) }] } };
        };
        await h.controller.scan(); await h.controller.openDetail("a");
        const editButton = { disabled: false, dataset: { action: "edit-region", id: "town" }, closest(selector) { return selector === "button" ? this : null; } };
        h.node("villagersPanel").dispatch("click", { target: editButton });
        await new Promise(resolve => setImmediate(resolve));
        if (draft === "alias") input(h, "villagerAlias", "My pending alias");
        if (draft === "region") input(h, "villagerRegionMaxX", "15");
        h.controller.getState().selected.add("b");
        input(h, "villagerBatchMax", "40");
        await h.controller.preview(); await commit(h);
        assert.equal(h.calls.saves.length, 1, draft);
        assert.equal(h.calls.scans.length, 2, draft);
        assert.equal(h.node("villagerRegionMaxX").value, draft === "none" ? "50" : draft === "region" ? "15" : "10", draft);
        assert.equal(h.controller.getState().regionDirty, draft === "region", draft);
        assert.equal(h.controller.getState().preferences.revision, draft === "none" ? "p2" : "p1", draft);
        if (draft === "none") {
            assert.equal(h.node("villagerRegionName").value, "Expanded town");
            input(h, "villagerRegionMaxX", "51");
            input(h, "villagerRegionMaxX", "50");
            assert.equal(h.controller.getState().regionDirty, false);
        } else {
            assert.match(h.controller.getState().message, /zwischenzeitlich geändert/);
            if (draft === "alias") assert.equal(h.node("villagerAlias").value, "My pending alias");
            h.api.savePreferences = async payload => {
                h.calls.preferences.push(payload);
                return { success: false, code: "villager_preferences_stale", error: "Changed elsewhere" };
            };
            await h.controller.savePreferences(h.controller.getState().preferences);
            assert.equal(h.calls.preferences[0].revision, "p1", draft);
            assert.equal(h.controller.hasPendingChanges(), true, draft);
        }
    }
});

test("Ctrl+S previews an active single-villager draft even when an old batch selection exists", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    h.controller.getState().selected.add("b");
    input(h, "villagerBatchMax", "40");
    input(h, "villagerDetailCurrent", "18");
    let prevented = false;
    h.controller.handleKeyboard({ key: "s", ctrlKey: true, target: h.node("villagerDetailCurrent"), preventDefault() { prevented = true; } });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(prevented, true);
    assert.equal(h.calls.previews.length, 1);
    assert.deepEqual(plain(h.calls.previews[0][0].selection.map(row => row.id)), ["a"]);
    assert.equal(h.calls.previews[0][0].changes.current_health, 18);
    assert.equal(h.calls.saves.length, 0);
});

test("Ctrl+S in an unchanged health form stays silent and does not review a different form's draft", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    h.controller.getState().selected.add("b");
    const shortcut = async id => {
        let prevented = false;
        h.controller.handleKeyboard({ key: "s", ctrlKey: true, target: h.node(id), preventDefault() { prevented = true; } });
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(prevented, true);
    };
    for (const id of ["villagerDetailCurrent", "villagerBatchMax", "row:a"]) await shortcut(id);
    input(h, "villagerBatchMax", "40");
    await shortcut("villagerDetailCurrent");
    await h.controller.resetBatch();
    input(h, "villagerDetailCurrent", "18");
    await shortcut("villagerBatchMax");
    assert.equal(h.calls.previews.length, 0);
    assert.equal(h.calls.saves.length, 0);
    assert.equal(h.calls.toasts.length, 0);
    assert.equal(h.controller.getState().message, "");
    assert.equal(h.controller.getState().detailDirty, true);
    assert.equal(h.node("villagerDetailCurrent").value, "18");
});

test("Ctrl+S rejects unfinished numbers instead of reviewing a partial health change", async () => {
    for (const single of [false, true]) for (const field of ["Max", "Current"]) {
        const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
        h.controller.getState().selected.add("b");
        const prefix = single ? "villagerDetail" : "villagerBatch";
        input(h, `${prefix}Max`, "40"); input(h, `${prefix}Current`, "18");
        h.node(`${prefix}${field}`).validity.badInput = true;
        input(h, `${prefix}${field}`, "");
        h.controller.handleKeyboard({ key: "s", ctrlKey: true, target: h.node(`${prefix}${field}`), preventDefault() {} });
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(h.calls.previews.length, 0, `${prefix}${field}`);
        assert.equal(h.node("villagerPreviewDialog").open, false);
        assert.equal(h.controller.getState()[single ? "detailDirty" : "batchDirty"], true);
    }
});

test("direct healing validates an unfinished maximum but ignores a replaced current-health input", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    h.node("villagerDetailMax").validity.badInput = true;
    input(h, "villagerDetailMax", "");
    await h.controller.healDetail();
    assert.equal(h.calls.previews.length, 0);
    assert.equal(h.node("villagerPreviewDialog").open, false);
    h.node("villagerDetailMax").validity.badInput = false;
    input(h, "villagerDetailMax", "20");
    h.node("villagerDetailCurrent").validity.badInput = true;
    input(h, "villagerDetailCurrent", "");
    await h.controller.healDetail();
    assert.equal(h.calls.previews.length, 1);
    assert.equal(h.calls.previews[0][0].changes.heal, true);
    assert.equal(h.calls.previews[0][0].changes.current_health, undefined);
});

test("Ctrl+S does not drop unfinished optional Y bounds while saving a region", async () => {
    const h = harness(); await h.controller.scan();
    for (const [id, value] of [["Name", "Town"], ["MinX", "0"], ["MaxX", "10"], ["MinZ", "0"], ["MaxZ", "10"]]) input(h, `villagerRegion${id}`, value);
    h.node("villagerRegionMinY").validity.badInput = true;
    input(h, "villagerRegionMinY", "");
    h.controller.handleKeyboard({ key: "s", ctrlKey: true, target: h.node("villagerRegionMinY"), preventDefault() {} });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.calls.preferences.length, 0);
    assert.equal(h.controller.getState().regionDirty, true);
    assert.equal(h.node("villagerRegionName").value, "Town");
});

test("late preview dismissal cannot steal focus after changing world or workspace", async () => {
    for (const changed of ["world", "workspace"]) {
        const h = harness(); await h.controller.scan();
        h.controller.getState().selected.add("a");
        input(h, "villagerBatchMax", "40");
        h.node("villagerBatchPreview").focus();
        await h.controller.preview();
        assert.equal(h.node("villagerPreviewDialog").open, true);
        if (changed === "world") { h.world.path = "B"; h.controller.updateContext(); }
        else h.world.view = "inventory";
        h.node("otherWorkspaceControl").focus();
        h.node("villagerPreviewDialog").dispatch("cancel");
        h.node("villagerPreviewDialog").dispatch("close");
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(h.doc.activeElement, h.node("otherWorkspaceControl"), changed);
        assert.equal(h.calls.saves.length, 0, changed);
    }
});

test("a late detail response leaves a newer search focus in place", async () => {
    const h = harness(), pending = deferred(); await h.controller.scan();
    h.api.detail = async () => pending.promise;
    const detail = h.controller.openDetail("a");
    h.node("villagerSearch").focus();
    pending.resolve({ success: true, villager: h.rows[0] }); await detail;
    assert.equal(h.controller.getState().detail.id, "a");
    assert.equal(h.doc.activeElement, h.node("villagerSearch"));
});

test("closing an inspector returns focus to its row, while cancelled discard keeps the draft", async () => {
    const h = harness(); await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailCurrent", "18"); h.confirm(false);
    await h.controller.closeDetail();
    assert.equal(h.controller.getState().activeId, "a");
    assert.equal(h.node("villagerDetailCurrent").value, "18");
    h.confirm(true);
    await h.controller.resetDetail(); await h.controller.closeDetail();
    assert.equal(h.controller.getState().activeId, "");
    assert.equal(h.doc.activeElement, h.node("row:a"));
});

test("optional map and region panels preserve pending region fields when toggled", async () => {
    const h = harness(); await h.controller.scan();
    h.node("villagerRegionsToggle").dispatch("click");
    input(h, "villagerRegionName", "Keep this region");
    h.node("villagerRegionsToggle").dispatch("click");
    h.node("villagerMapToggle").dispatch("click");
    h.node("villagerRegionsToggle").dispatch("click");
    assert.equal(h.node("villagerRegionName").value, "Keep this region");
    assert.equal(h.controller.getState().regionDirty, true);
    assert.equal(h.controller.getState().regionsOpen, true);
    assert.equal(h.calls.preferences.length, 0);
});

test("reopening the region already being edited preserves its draft without a discard prompt", async () => {
    const h = harness(); await h.controller.scan();
    h.controller.getState().preferences.regions = [{ id: "town", name: "Town", dimension: 0, min_x: 0, max_x: 10, min_z: 0, max_z: 10 }];
    const editButton = { disabled: false, dataset: { action: "edit-region", id: "town" }, closest(selector) { return selector === "button" ? this : null; } };
    h.node("villagersPanel").dispatch("click", { target: editButton });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.node("villagerRegionName").value, "Town");
    input(h, "villagerRegionName", "Trading town");
    h.node("villagerSearch").focus();
    h.node("villagersPanel").dispatch("click", { target: editButton });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.node("villagerRegionName").value, "Trading town");
    assert.equal(h.controller.getState().regionDirty, true);
    assert.equal(h.doc.activeElement, h.node("villagerRegionName"));
    assert.equal(h.calls.confirmations.length, 0);
    assert.equal(h.calls.preferences.length, 0);
});

test("select-all refuses more than 1000 rows rather than silently editing a subset", async () => {
    const h = harness({ rows: Array.from({ length: 1001 }, (_, index) => row(String(index))) });
    await h.controller.scan();
    h.node("villagerSelectFiltered").dispatch("click");
    assert.equal(h.controller.getState().selected.size, 0);
    assert.match(h.controller.getState().message, /1000/);
});

test("read-only mode still scans and inspects but cannot create previews or preference writes", async () => {
    const h = harness({ readOnly: true }); await h.controller.scan(); await h.controller.openDetail("a");
    h.controller.getState().selected.add("a"); h.node("villagerBatchHeal").checked = true;
    await h.controller.preview(); await h.controller.savePreferences({ aliases: {}, regions: [] });
    assert.equal(h.calls.details.length, 1);
    assert.equal(h.calls.previews.length, 0);
    assert.equal(h.calls.preferences.length, 0);
});

test("all villager reads use shared cancellable jobs, while save transport is not retried", async () => {
    const calls = [];
    const ctx = { window: { MCBEPlayerApi: { createPlayerApiClient: () => ({ readWorld: (...args) => { calls.push(args); return Promise.resolve({ success: true }); } }) } } };
    load(ctx, "villager_api");
    const api = ctx.window.MCBEVillagerApi.createVillagerApiClient({ fetchFn: async () => { throw new Error("offline"); }, parseJsonResponse: x => x });
    const options = { signal: new AbortController().signal };
    await api.scan("A", options); await api.detail({ world_path: "A", id: "a" }, options); await api.preview({ world_path: "A" }, options);
    assert.deepEqual(calls.map(call => call[0]), ["/api/villagers/scan", "/api/villagers/detail", "/api/villagers/preview"]);
    assert.ok(calls.every(call => call[2] === options));
    await assert.rejects(api.save({ preview_token: "one" }), /offline/);
});

test("villager navigation requires a world but never a player record", () => {
    const ctx = { window: {} }; load(ctx, "workflow_state");
    const nav = ctx.window.MCBEWorkflowState;
    assert.equal(nav.viewAllowed("villagers", {}), false);
    assert.equal(nav.viewAllowed("villagers", { worldPath: "A" }), true);
    assert.equal(nav.resolvedView("villagers", { worldPath: "A" }), "villagers");
    assert.equal(nav.unavailableMessage("villagers"), "Lade zuerst eine Welt.");
});

test("presence watches a villager world without a player and ignores a late poll from another world", async () => {
    let world = "A";
    const calls = [], observations = [], pending = [];
    const ctx = { window: {}, AbortController, setTimeout, clearTimeout, Date: { now: () => 123 }, console,
        fetch: async (_url, options) => { calls.push(options); const request = deferred(); pending.push(request); return request.promise; } };
    load(ctx, "api_client"); load(ctx, "presence_view");
    const presence = ctx.window.MCBEPresenceView.createWorldPresenceController({
        win: { sessionStorage: { setItem() {} } }, getWorldPath: () => world, getCurrentPlayerKey: () => "",
        getWatchWorld: () => true, parseJsonResponse: x => x, onWorldStatus: (data, context) => observations.push([data, context]),
    });
    const first = presence.update();
    assert.equal(JSON.parse(calls[0].body).watch_world, true);
    pending[0].resolve({ success: true, world_fingerprint: "first" }); await first;
    assert.equal(observations.length, 1);
    assert.deepEqual(plain(observations[0][1]), { worldPath: "A", startedAt: 123 });
    const second = presence.update(); world = "B";
    pending[1].resolve({ success: true, world_fingerprint: "stale" }); await second;
    assert.equal(observations.length, 1);
});

test("deleting the last saved region of a dimension preserves another region draft's dimension", () => {
    const h = harness(), { node, view } = viewHarness();
    const state = h.controller.getState();
    const remote = { id: "remote", name: "Remote village", dimension: 7, min_x: 0, max_x: 10, min_z: 0, max_z: 10 };
    state.preferences = { revision: "p1", aliases: {}, regions: [remote] };
    view.render(state);
    node("villagerRegionDimension").value = "7";
    node("villagerRegionName").value = "Another remote village";
    state.regionDirty = true;
    state.preferences = { revision: "p2", aliases: {}, regions: [] };
    view.render(state);
    assert.match(node("villagerRegionDimension").innerHTML, /<option value="7">Dimension 7<\/option>/);
    assert.equal(node("villagerRegionDimension").value, "7");
    assert.equal(node("villagerRegionName").value, "Another remote village");
    assert.equal(state.regionDirty, true);
    // Once that draft is discarded, an obsolete dimension must not leak into
    // a clean form or the next world's available choices.
    state.regionDirty = false;
    view.render(state);
    assert.doesNotMatch(node("villagerRegionDimension").innerHTML, /<option value="7">/);
    assert.equal(node("villagerRegionDimension").value, "0");
});

test("a delayed preview cannot cover a pending discard confirmation with another modal", async () => {
    const h = harness(), pending = deferred(), confirmation = deferred();
    await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailCurrent", "18");
    h.api.preview = async () => pending.promise;
    const preview = h.controller.preview(true);
    h.confirm(confirmation.promise);
    const close = h.controller.closeDetail();
    let confirmationOpen = true;
    h.doc.querySelectorAll = () => confirmationOpen ? [{ getClientRects: () => [{}] }] : [];
    h.node("confirmCancel").focus();
    pending.resolve({ success: true, rows: [], change_count: 1, preview_token: "late-preview" });
    await preview;
    const coveredConfirmation = h.node("villagerPreviewDialog").open;
    const previewState = h.controller.getState().preview;
    const focus = h.doc.activeElement;
    confirmationOpen = false; confirmation.resolve(false); await close;
    assert.equal(coveredConfirmation, false);
    assert.equal(previewState, null);
    assert.equal(focus, h.node("confirmCancel"));
    assert.equal(h.controller.getState().busy, false);
    assert.equal(h.controller.getState().activeId, "a");
    assert.equal(h.controller.getState().detailDirty, true);
    assert.equal(h.node("villagerDetailCurrent").value, "18");
    h.api.preview = async () => ({ success: true, rows: [], change_count: 1, preview_token: "fresh-preview" });
    await h.controller.preview(true);
    assert.equal(h.controller.getState().preview.preview_token, "fresh-preview");
    assert.equal(h.node("villagerPreviewDialog").open, true);
});

test("small positive health remains visibly positive with and without localized number formatting", () => {
    const tiny = 0.001;
    assert.equal(Number(model.healthNumber(tiny)) > 0, true);
    const ctx = { window: { MCBEI18n: { formatNumber: (number, options) => new Intl.NumberFormat("de-DE", options).format(number) } } };
    load(ctx, "villager_model"); load(ctx, "villager_inventory");
    assert.equal(ctx.window.MCBEVillagerModel.healthNumber(tiny), "0,001");
    assert.equal(ctx.window.MCBEVillagerModel.healthNumber(0), "0");
    assert.equal(ctx.window.MCBEVillagerModel.healthNumber(12.3456), "12,35");
    assert.equal(model.healthNumber(12.3456), "12.35");
});

test("Ctrl+S in the alias form cannot start a settings write during a health preview", async () => {
    const h = harness(), previewResponse = deferred(), settingsResponse = deferred();
    await h.controller.scan(); await h.controller.openDetail("a");
    input(h, "villagerDetailCurrent", "18");
    input(h, "villagerAlias", "Pending alias");
    h.api.preview = async (payload, options) => { h.calls.previews.push([payload, options]); return previewResponse.promise; };
    h.api.savePreferences = async payload => { h.calls.preferences.push(payload); return settingsResponse.promise; };
    const preview = h.controller.preview(true);
    h.node("villagerAlias").focus();
    let prevented = false;
    const shortcut = () => h.controller.handleKeyboard({ key: "s", ctrlKey: true, target: h.node("villagerAlias"), preventDefault() { prevented = true; } });
    shortcut();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(prevented, true);
    assert.equal(h.controller.getState().busy, true);
    assert.equal(h.calls.preferences.length, 0);
    assert.equal(h.controller.getState().preferencesBusy, false);
    assert.equal(h.controller.getState().aliasDirty, true);
    previewResponse.resolve({ success: true, rows: [], change_count: 1, preview_token: "health-preview" });
    await preview; await commit(h);
    assert.equal(h.calls.saves.length, 1);
    assert.equal(h.calls.scans.length, 2);
    assert.equal(h.controller.getState().staleReason, "");
    assert.equal(h.controller.getState().aliasDirty, true);
    assert.equal(h.node("villagerAlias").value, "Pending alias");
    shortcut();
    assert.equal(h.calls.preferences.length, 1);
    settingsResponse.resolve({ success: true, preferences: { revision: "p2", aliases: { a: "Pending alias" }, regions: [] } });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.controller.getState().preferencesBusy, false);
    assert.equal(h.controller.getState().aliasDirty, false);
});


test("finishing an alias save updates a clean reopened form without creating a reversal draft", async () => {
    for (const [before, saved] of [["", "Library"], ["Library", ""]]) {
        const h = harness(), pending = deferred();
        await h.controller.scan();
        h.controller.getState().preferences.aliases = before ? { a: before } : {};
        await h.controller.openDetail("a");
        input(h, "villagerAlias", saved);
        h.api.savePreferences = async payload => { h.calls.preferences.push(payload); return pending.promise; };
        h.node("villagersPanel").dispatch("submit", { target: h.node("villagerAliasForm") });
        assert.equal(h.controller.getState().preferencesBusy, true);
        await h.controller.closeDetail();
        await h.controller.openDetail("a");
        assert.equal(h.node("villagerAlias").value, before);
        assert.equal(h.controller.getState().aliasDirty, false);
        pending.resolve({ success: true, preferences: { revision: "p2", aliases: saved ? { a: saved } : {}, regions: [] } });
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(h.node("villagerAlias").value, saved);
        assert.equal(h.controller.getState().aliasDirty, false);
        assert.equal(h.controller.hasPendingChanges(), false);
        assert.equal(h.calls.preferences.length, 1);
    }
});


test("overlapping health previews cannot silently replace an already staged change", async () => {
    const h = harness();
    h.api.preview = async () => ({success: true, preview_token: "signed", change_count: 1,
        rows: [{id: "a", status: "changed", before: {current: 12, max: 20}, after: {current: 20, max: 20}}]});
    await h.prepare();
    await h.controller.save();
    assert.equal(h.controller.getPendingChanges().length, 1);
    h.controller.getState().selected.add("a");
    input(h, "villagerBatchCurrent", "18");
    await h.controller.preview();
    await h.controller.save();
    assert.equal(h.controller.getPendingChanges().length, 1);
    assert.match(h.controller.getState().previewNotice, /bereits vorgemerkt/);
    assert.equal(h.calls.saves.length, 0);
    h.world.path = "B"; h.controller.updateContext();
    assert.equal(h.controller.getPendingChanges().length, 0);
});


test("Minecraft name validation counts Unicode code points and rejects controls before trimming", () => {
    for (const name of ["Ä".repeat(79) + "🐑", "Jörg <&> 👨‍🌾", ""]) assert.deepEqual(plain(model.nameChanges(name)), { name });
    assert.deepEqual(plain(model.nameChanges("  Egon  ")), { name: "Egon" });
    for (const name of ["🐑".repeat(81), "\n", "X\0", "X\ud800", "X\u2028"]) assert.throws(() => model.nameChanges(name));
});
