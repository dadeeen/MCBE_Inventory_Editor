import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../../static/layout_controller.js", import.meta.url), "utf8");

// Exercise the production controller with a small DOM and Storage contract.
// This runs with plain Node and requires no Flask or npm dependencies.
function editorHarness(initial = {}, { blockStorage = false, missingElements = false } = {}) {
    const values = new Map(Object.entries(initial));
    const observers = [];
    const listeners = {};
    const storage = {
        getItem(key) { if (blockStorage) throw Error("blocked storage"); return values.get(key) ?? null; },
        setItem(key, value) { if (blockStorage) throw Error("blocked storage"); values.set(key, value); },
    };
    const root = { dataset: { theme: "minecraft" } };
    const classes = new Set();
    const body = {
        dataset: { workflowView: "world" },
        classList: {
            contains: cls => classes.has(cls),
            toggle: (cls, enabled) => enabled ? classes.add(cls) : classes.delete(cls),
        },
    };
    const select = {
        value: "classic",
        addEventListener(name, handler) { (listeners[name] ??= []).push(handler); },
        dispatch(name) { for (const handler of listeners[name] ?? []) handler(); },
    };
    const heading = { textContent: "" };
    const description = { textContent: "" };
    const contextWorld = { textContent: "" };
    const contextPlayer = { textContent: "" };
    const saveStatus = { textContent: "" };
    const worldSource = { textContent: "" };
    const playerSource = { textContent: "" };
    const mode = { textContent: "" };
    const inspector = () => ({
        style: { display: "none" }, scrolls: 0, scrollOptions: null,
        scrollIntoView(options) { this.scrolls += 1; this.scrollOptions = options; },
    });
    const panel = inspector();
    const multiPanel = inspector();
    const elements = { layoutSelect: select, layoutViewTitle: heading, layoutViewDescription: description, layoutModeLabel: mode, detailEditorPanel: panel, multiSelectPanel: multiPanel, layoutCurrentWorld: contextWorld, layoutCurrentPlayer: contextPlayer, layoutSaveStatus: saveStatus, worldName: worldSource, playerSummaryName: playerSource };
    const callbacks = {};
    const doc = {
        readyState: "loading",
        documentElement: root,
        body,
        addEventListener(name, handler) { callbacks[name] = handler; },
        getElementById(id) { return missingElements ? null : elements[id] ?? null; },
    };
    const window = {
        t: (value, params) => `[translated] ${value.replace(/\{(\w+)\}/g, (match, key) => params?.[key] ?? match)}`,
        innerWidth: 430,
        requestAnimationFrame: handler => handler(),
        matchMedia: () => ({ matches: false }),
    };
    class MutationObserver {
        constructor(callback) { this.callback = callback; observers.push(this); }
        observe(target, options) { this.target = target; this.options = options; }
        trigger() { this.callback([{ type: "attributes", target: this.target }]); }
    }
    vm.runInNewContext(source, { window, document: doc, localStorage: storage, MutationObserver });
    callbacks.DOMContentLoaded?.();
    return { window, doc, values, storage, root, body, select, panel, multiPanel, heading, description, contextWorld, contextPlayer, saveStatus, worldSource, playerSource, mode, observers, listeners };
}

test("initializes to classic on clean installation and keeps the theme", () => {
    const h = editorHarness();
    assert.equal(h.root.dataset.layout, "classic");
    assert.equal(h.root.dataset.theme, "minecraft");
    assert.equal(h.select.value, "classic");
    assert.equal(h.values.get("mcbe-inventory-editor:layout"), "classic");
    assert.equal(h.heading.textContent, "[translated] Welt auswählen");
    assert.equal(h.contextWorld.textContent, "[translated] Welt auswählen");
    assert.equal(h.contextPlayer.textContent, "[translated] Spieler auswählen");
});

test("persisted layout restores independently of color theme and preserves arbitrary workspace data", () => {
    const h = editorHarness({
        "mcbe-inventory-editor:layout": "studio",
        "mcbe-inventory-editor:theme": "light",
        "mcbe-inventory-editor:workspace": "{\"inventory\":{\"slot\":32}}",
    });
    assert.equal(h.root.dataset.layout, "studio");
    assert.equal(h.select.value, "studio");
    h.select.value = "focus";
    h.select.dispatch("change");
    assert.equal(h.root.dataset.layout, "focus");
    assert.equal(h.values.get("mcbe-inventory-editor:layout"), "focus");
    assert.equal(h.values.get("mcbe-inventory-editor:theme"), "light");
    assert.equal(h.values.get("mcbe-inventory-editor:workspace"), '{"inventory":{"slot":32}}');
    assert.equal(h.mode.textContent, "[translated] Fokus · Arbeitsbereiche");
    assert.equal(h.listeners.change.length, 1);
});

test("invalid persisted and selected layout values fall back to classic", () => {
    const h = editorHarness({ "mcbe-inventory-editor:layout": "<script>alert(1)</script>" });
    assert.equal(h.root.dataset.layout, "classic");
    h.select.value = "invalid";
    h.select.dispatch("change");
    assert.equal(h.root.dataset.layout, "classic");
    assert.equal(h.values.get("mcbe-inventory-editor:layout"), "classic");
});

test("independent destinations explain the current work area without fake steps", () => {
    const h = editorHarness({ "mcbe-inventory-editor:layout": "focus" });
    const views = [
        ["world", "Welt auswählen"],
        ["player", "Spieler auswählen"],
        ["inventory", "Inventar bearbeiten"],
        ["player-edit", "Spielerdaten bearbeiten"],
        ["mounts", "Mounts (experimentell)"],
        ["save", "Änderungen prüfen & speichern"],
        ["tools", "Werkzeuge & Diagnose"],
    ];
    const observer = h.observers.find(o => o.target === h.body);
    assert(observer);
    for (const [view, title] of views) {
        h.body.dataset.workflowView = view;
        observer.trigger();
        assert.equal(h.heading.textContent, `[translated] ${title}`);
        assert(h.description.textContent.length > 12);
    }
    assert.equal(h.doc.getElementById("layoutStepIndex"), null, "no fake stage counter");
});

test("context shows real world/player names, gated placeholders, and dirty save status", () => {
    const h = editorHarness({ "mcbe-inventory-editor:layout": "studio" });
    const bodyObserver = h.observers.find(o => o.target === h.body);
    const worldObserver = h.observers.find(o => o.target === h.worldSource);
    const playerObserver = h.observers.find(o => o.target === h.playerSource);
    assert(worldObserver && playerObserver);
    h.worldSource.textContent = "Meine Testwelt";
    h.playerSource.textContent = "Spieler Zwei";
    worldObserver.trigger();
    playerObserver.trigger();
    assert.equal(h.contextWorld.textContent, "[translated] Welt auswählen", "hidden stale labels without world state");
    h.body.classList.toggle("app-world-loaded", true);
    bodyObserver.trigger();
    assert.equal(h.contextWorld.textContent, "Meine Testwelt");
    assert.equal(h.contextPlayer.textContent, "[translated] Spieler auswählen");
    h.body.classList.toggle("app-player-loaded", true);
    bodyObserver.trigger();
    assert.equal(h.contextPlayer.textContent, "Spieler Zwei");
    assert.equal(h.saveStatus.textContent, "[translated] Keine Änderungen");
    h.body.classList.toggle("app-dirty", true);
    bodyObserver.trigger();
    assert.equal(h.saveStatus.textContent, "[translated] Ungespeicherte Änderungen");
    h.body.classList.toggle("app-player-loaded", false);
    h.body.classList.toggle("app-world-loaded", false);
    bodyObserver.trigger();
    assert.equal(h.contextWorld.textContent, "[translated] Welt auswählen");
    assert.equal(h.contextPlayer.textContent, "[translated] Spieler auswählen");
});

test("returning to Classic from player data restores the original player view", () => {
    const h = editorHarness({ "mcbe-inventory-editor:layout": "focus" });
    h.body.dataset.workflowView = "player-edit";
    let redirected = 0;
    h.window.setWorkflowView = (view, opts) => {
        assert.equal(view, "player");
        assert.equal(opts.scroll, false);
        assert.equal(opts.preserveEditor, true);
        redirected++;
        h.body.dataset.workflowView = "player";
    };
    h.select.value = "classic";
    h.select.dispatch("change");
    assert.equal(h.root.dataset.layout, "classic");
    assert.equal(h.body.dataset.workflowView, "player");
    assert.equal(redirected, 1);
});

test("existing save status distinguishes drafts from accepted change counts", () => {
    const h = editorHarness({ "mcbe-inventory-editor:layout": "focus" });
    const observer = h.observers.find(o => o.target === h.body);
    assert(observer.options.attributeFilter.includes("data-slot-draft-pending"));
    assert(observer.options.attributeFilter.includes("data-change-count"));
    assert.equal(h.saveStatus.textContent, "[translated] Keine Änderungen");
    h.body.dataset.slotDraftPending = "true";
    observer.trigger();
    assert.equal(h.saveStatus.textContent, "[translated] Eingaben offen");
    h.body.classList.toggle("app-dirty", true);
    h.body.dataset.changeCount = "2";
    observer.trigger();
    assert.equal(h.saveStatus.textContent, "[translated] Eingaben offen", "new input keeps the accepted changes pending");
    h.body.dataset.slotDraftPending = "false";
    observer.trigger();
    assert.equal(h.saveStatus.textContent, "[translated] 2 Änderungen");
    h.body.dataset.changeCount = "1";
    observer.trigger();
    assert.equal(h.saveStatus.textContent, "[translated] 1 Änderung");
});

test("Classic player editing maps to the alternative editor without resetting forms", () => {
    const h = editorHarness();
    h.body.dataset.workflowView = "player";
    const redirects = [];
    h.window.setWorkflowView = (view, options) => redirects.push({ view, ...options });
    h.select.value = "studio";
    h.select.dispatch("change");
    assert.equal(redirects.length, 0, "unloaded player selection stays on selection");
    h.select.value = "classic";
    h.select.dispatch("change");
    h.body.classList.toggle("app-player-loaded", true);
    h.select.value = "focus";
    h.select.dispatch("change");
    assert.deepEqual(redirects, [{ view: "player-edit", scroll: false, preserveEditor: true }]);
});

test("stacked layouts only scroll to the inspector on newly opened slot selections", () => {
    const h = editorHarness({ "mcbe-inventory-editor:layout": "focus" });
    const observer = h.observers.find(o => o.target === h.panel);
    assert(observer);
    h.body.dataset.workflowView = "inventory";
    h.panel.style.display = "flex";
    observer.trigger();
    assert.equal(h.panel.scrolls, 1);
    observer.trigger();
    assert.equal(h.panel.scrolls, 1);
    h.panel.style.display = "none";
    observer.trigger();
    h.window.innerWidth = 1440;
    h.panel.style.display = "flex";
    observer.trigger();
    assert.equal(h.panel.scrolls, 1, "desktop does not jump away from the grid");
    h.panel.style.display = "none";
    observer.trigger();
    h.window.innerWidth = 430;
    h.select.value = "classic";
    h.select.dispatch("change");
    h.panel.style.display = "flex";
    observer.trigger();
    assert.equal(h.panel.scrolls, 1, "classic leaves the original panel behavior alone");
});

test("single and multiple selections stay reachable at each layout's actual inspector breakpoint", () => {
    for (const [layout, breakpoint] of [["focus", 1279], ["studio", 1180]]) {
        const h = editorHarness({ "mcbe-inventory-editor:layout": layout });
        h.body.dataset.workflowView = "inventory";
        for (const panel of [h.panel, h.multiPanel]) {
            const observer = h.observers.find(o => o.target === panel);
            assert(observer);
            for (const width of [390, 1180, 1181, 1200, 1279, 1280, 1320]) {
                h.window.innerWidth = width;
                const before = panel.scrolls;
                panel.style.display = "flex";
                observer.trigger();
                assert.equal(panel.scrolls - before, width <= breakpoint ? 1 : 0, `${layout} at ${width}px`);
                panel.style.display = "none";
                observer.trigger();
            }
        }
    }
});

test("scheduled inspector scrolling respects motion preference and cancels after leaving the view", () => {
    const h = editorHarness({ "mcbe-inventory-editor:layout": "focus" });
    const observer = h.observers.find(o => o.target === h.panel);
    h.body.dataset.workflowView = "inventory";
    h.window.innerWidth = 1200;
    h.window.matchMedia = () => ({ matches: true });
    let nextFrame;
    h.window.requestAnimationFrame = callback => { nextFrame = callback; };
    h.panel.style.display = "flex";
    observer.trigger();
    assert.equal(h.panel.scrolls, 0, "waits for the layout to settle");
    nextFrame();
    assert.equal(h.panel.scrolls, 1);
    assert.equal(h.panel.scrollOptions.behavior, "instant");
    assert.equal(h.panel.scrollOptions.block, "start");
    for (const leave of [
        () => { h.body.dataset.workflowView = "player"; },
        () => { h.select.value = "classic"; h.select.dispatch("change"); },
        () => { h.panel.style.display = "none"; },
        () => { h.window.innerWidth = 1440; },
    ]) {
        h.select.value = "focus";
        h.select.dispatch("change");
        h.body.dataset.workflowView = "inventory";
        h.window.innerWidth = 1200;
        h.panel.style.display = "none";
        observer.trigger();
        h.panel.style.display = "flex";
        observer.trigger();
        leave();
        nextFrame();
        assert.equal(h.panel.scrolls, 1, "does not scroll into a stale or side-by-side inspector");
    }
});

test("works with blocked localStorage and missing optional elements", () => {
    const h = editorHarness({}, { blockStorage: true, missingElements: true });
    assert.equal(h.root.dataset.layout, "classic");
    assert.equal(h.observers.length, 1, "only the available body is observed");
    assert.doesNotThrow(() => h.window.MCBELayoutController.normalizeLayout(undefined));
});

test("wire is idempotent and selection event does not register twice", () => {
    const h = editorHarness();
    const controller = h.window.MCBELayoutController.createLayoutController({
        storage: h.storage, root: h.root, select: h.select, body: h.body,
        observerFactory: handler => new class { observe() {} }(),
    });
    const originalCount = h.listeners.change.length;
    controller.wire();
    controller.wire();
    assert.equal(h.listeners.change.length, originalCount + 1);
});
