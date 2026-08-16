import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_icon_sources_controller_loads_applies_and_renders() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            const panel = {
                innerHTML: "",
                querySelector() { return null; },
                querySelectorAll() { return []; },
            };
            const calls = [];
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel },
                fetchImpl: async url => {
                    calls.push({ url });
                    return { ok: true, headers: { get: () => "application/json" }, text: async () => "{}" };
                },
                parseJsonResponse: async () => ({
                    success: true,
                    icons: { "minecraft:apple": "/icons/apple.png" },
                    count: 1,
                    sources: [],
                    cache: { state: "hit" },
                    health: { existing_sources: 1, enabled_sources: 1 },
                }),
                withCsrf: () => ({ "Content-Type": "application/json", "X-CSRF-Token": "token" }),
                iconManagerView: {
                    iconManagerHtml(summary) { return `count:${summary.count}`; },
                    iconManagerSummaryText(summary) { return `summary:${summary.count}`; },
                },
                onIconData: payload => calls.push({ payload }),
                onIconDataApplied: () => calls.push({ applied: true }),
            });

            await controller.loadLocalIconIndex();
            assert.strictEqual(panel.innerHTML, "count:1");
            assert.deepStrictEqual(calls.find(call => call.payload).payload.icons, { "minecraft:apple": "/icons/apple.png" });
            assert.strictEqual(calls.find(call => call.payload).payload.summary.count, 1);
            assert.ok(calls.some(call => call.applied));
            assert.ok(calls.some(call => call.url === "/api/icons/status"));
            })();
            """
        )
    )


def test_frontend_icon_sources_controller_reports_unavailable_status_without_fake_empty_result() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console: { warn() {} } };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            const calls = [];
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                fetchImpl: async () => ({}),
                parseJsonResponse: async () => { throw new Error("Statusdienst nicht erreichbar"); },
                withCsrf: () => ({}),
                iconManagerView: {
                    iconManagerHtml() { return ""; },
                    iconManagerSummaryText() { return ""; },
                },
                onIconData: payload => calls.push({ payload }),
                onIconStatusUnavailable: error => calls.push({ unavailable: error.message }),
            });

            await controller.loadLocalIconIndex();
            assert.deepStrictEqual(calls, [{ unavailable: "Statusdienst nicht erreichbar" }]);
            await assert.rejects(
                controller.loadLocalIconIndex({ throwOnError: true }),
                /Statusdienst nicht erreichbar/,
            );
            assert.strictEqual(calls.filter(call => call.unavailable).length, 2);
            assert.ok(!calls.some(call => call.payload));
            })();
            """
        )
    )


def test_frontend_icon_sources_controller_wires_source_actions_and_move() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            function element() {
                return {
                    listeners: {},
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                };
            }

            const calls = [];
            const loading = [];
            const addButton = element();
            const rescanButton = element();
            const sourcePathInput = element();
            sourcePathInput.value = "C:/packs/main.mcpack";
            const panel = {
                innerHTML: "",
                querySelector() { return null; },
                querySelectorAll(selector) {
                    if (selector === ".icon-source-move") {
                        return [{
                            dataset: { path: "C:/packs/main.mcpack", direction: "down" },
                            addEventListener(type, fn) { calls.push({ moveListener: type, fn }); },
                        }];
                    }
                    return [];
                },
            };
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, sourcePathInput, addButton, rescanButton },
                fetchImpl: async (url, options = {}) => {
                    calls.push({ url, options });
                    return { ok: true, headers: { get: () => "application/json" }, text: async () => "{}" };
                },
                parseJsonResponse: async () => ({ success: true, icons: {}, count: 2, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json", "X-CSRF-Token": "token" }),
                iconManagerView: {
                    iconManagerHtml(summary) { return `count:${summary.count}`; },
                    iconManagerSummaryText(summary) { return `summary:${summary.count}`; },
                },
                showToast: (message, type) => calls.push({ toast: message, type }),
                showLoading: message => loading.push(["show", message]),
                hideLoading: () => loading.push(["hide"]),
            });

            controller.wire();
            await addButton.listeners.click();
            assert.ok(calls.some(call => call.url === "/api/icons/sources/add"));
            assert.strictEqual(sourcePathInput.value, "");

            loading.length = 0;
            await rescanButton.listeners.click();
            assert.ok(calls.some(call => call.url === "/api/icons/scan"));
            assert.ok(calls.some(call => call.toast === "Icon-Scan abgeschlossen: 2 Icons."));
            assert.deepStrictEqual(loading, [
                ["show", "Icon-Quellen werden erneut gescannt..."],
                ["hide"],
            ]);
            assert.strictEqual(rescanButton.disabled, false);

            await calls.find(call => call.moveListener === "click").fn();
            const moveCall = calls.find(call => call.url === "/api/icons/sources/move");
            assert.ok(moveCall);
            assert.strictEqual(JSON.parse(moveCall.options.body).direction, "down");
            })();
            """
        )
    )


def test_frontend_icon_rescan_reports_failure_instead_of_stale_success() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            const rescanButton = {
                disabled: false,
                listeners: {},
                addEventListener(type, fn) { this.listeners[type] = fn; },
            };
            const toasts = [];
            const loading = [];
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { rescanButton },
                fetchImpl: async () => ({ ok: false }),
                parseJsonResponse: async () => ({ success: false, error: "LevelDB-Scan fehlgeschlagen." }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView: {
                    iconManagerHtml() { return ""; },
                    iconManagerSummaryText() { return ""; },
                },
                showToast: (message, type) => toasts.push({ message, type }),
                showLoading: message => loading.push(["show", message]),
                hideLoading: () => loading.push(["hide"]),
                consoleObj: { warn() {}, error() {} },
            });

            controller.applyIconIndexData({ success: true, count: 7, icons: {} });
            controller.wire();
            await rescanButton.listeners.click();

            assert.deepStrictEqual(toasts, [
                { message: "LevelDB-Scan fehlgeschlagen.", type: "error" },
            ]);
            assert.deepStrictEqual(loading, [
                ["show", "Icon-Quellen werden erneut gescannt..."],
                ["hide"],
            ]);
            assert.strictEqual(rescanButton.disabled, false);
            })();
            """
        )
    )


def test_frontend_icon_sources_controller_does_not_apply_failed_mutations() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            const calls = [];
            const sourcePathInput = { value: "C:/missing" };
            const panel = {
                innerHTML: "before",
                querySelector() { return null; },
                querySelectorAll() { return []; },
            };
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, sourcePathInput },
                fetchImpl: async () => ({ ok: false, headers: { get: () => "application/json" }, text: async () => "{}" }),
                parseJsonResponse: async () => ({ success: false, error: "Pfad fehlt." }),
                withCsrf: () => ({ "Content-Type": "application/json", "X-CSRF-Token": "token" }),
                iconManagerView: {
                    iconManagerHtml(summary) { return `count:${summary.count}`; },
                    iconManagerSummaryText(summary) { return `summary:${summary.count}`; },
                },
                onIconData: payload => calls.push({ payload }),
                onIconDataApplied: () => calls.push({ applied: true }),
                showToast: (message, type) => calls.push({ toast: message, type }),
            });

            await controller.addIconSource(sourcePathInput.value);
            assert.strictEqual(panel.innerHTML, "before");
            assert.strictEqual(sourcePathInput.value, "C:/missing");
            assert.ok(!calls.some(call => call.payload));
            assert.ok(!calls.some(call => call.applied));
            assert.deepStrictEqual(calls.find(call => call.toast), { toast: "Pfad fehlt.", type: "error" });
            })();
            """
        )
    )


def test_frontend_icon_sources_controller_uses_status_in_read_only_even_when_rescan_requested() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            const calls = [];
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                appConfig: { read_only: true },
                fetchImpl: async (url, options = {}) => {
                    calls.push({ url, options });
                    return { ok: true, headers: { get: () => "application/json" }, text: async () => "{}" };
                },
                parseJsonResponse: async () => ({ success: true, icons: {}, count: 0, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json", "X-CSRF-Token": "token" }),
                iconManagerView: {
                    iconManagerHtml(summary) { return `count:${summary.count}`; },
                    iconManagerSummaryText(summary) { return `summary:${summary.count}`; },
                },
            });

            await controller.loadLocalIconIndex({ rescan: true });

            assert.strictEqual(controller.canRescanIcons(), false);
            assert.ok(calls.some(call => call.url === "/api/icons/status"));
            assert.ok(!calls.some(call => call.url === "/api/icons/scan"));
            })();
            """
        )
    )


def test_frontend_icon_sources_controller_prefers_central_permissions_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            const create = context.window.MCBEIconSourcesController.createIconSourcesController;
            const view = {
                iconManagerHtml() { return ""; },
                iconManagerSummaryText() { return ""; },
            };

            // Zentrales Permission-Modell gewinnt gegenüber appConfig.
            const blocked = create({
                appConfig: {},
                permissions: () => ({ canRescanIcons: false }),
                fetchImpl: async () => ({}),
                iconManagerView: view,
            });
            assert.strictEqual(blocked.canRescanIcons(), false);

            const allowed = create({
                appConfig: { read_only: true },
                permissions: () => ({ canRescanIcons: true }),
                fetchImpl: async () => ({}),
                iconManagerView: view,
            });
            assert.strictEqual(allowed.canRescanIcons(), true);

            // Ohne injiziertes Modell bleibt der appConfig-Fallback erhalten.
            const fallback = create({ appConfig: { read_only: true }, fetchImpl: async () => ({}), iconManagerView: view });
            assert.strictEqual(fallback.canRescanIcons(), false);
            """
        )
    )


def test_frontend_icon_sources_controller_locks_write_controls_in_read_only() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            function element() {
                return {
                    disabled: false,
                    title: "",
                    listeners: {},
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                };
            }

            const addButton = element();
            const pickPackButton = element();
            const pickFolderButton = element();
            const updateVanillaButton = element();
            const sourcePathInput = element();
            const removeButton = element();
            removeButton.dataset = { path: "C:/packs" };
            const panel = {
                innerHTML: "",
                querySelector() { return null; },
                querySelectorAll(selector) {
                    return selector === ".icon-source-remove" ? [removeButton] : [];
                },
            };

            const calls = [];
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, sourcePathInput, addButton, pickPackButton, pickFolderButton, updateVanillaButton },
                permissions: () => ({ canWriteAppState: false, canRescanIcons: false }),
                fetchImpl: async (url, options = {}) => {
                    calls.push({ url, options });
                    return { ok: true, headers: { get: () => "application/json" }, text: async () => "{}" };
                },
                parseJsonResponse: async () => ({ success: true, icons: {}, count: 0, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView: {
                    iconManagerHtml() { return ""; },
                    iconManagerSummaryText() { return ""; },
                },
                showToast: (message, type) => calls.push({ toast: message, type }),
            });

            controller.wire();
            assert.strictEqual(controller.canWriteAppState(), false);
            for (const control of [addButton, pickPackButton, pickFolderButton, updateVanillaButton, sourcePathInput]) {
                assert.strictEqual(control.disabled, true);
                assert.ok(control.title.includes("Read-Only"));
            }

            // Per-Quelle-Buttons werden beim Rendern deaktiviert statt verdrahtet.
            controller.renderIconManager({ count: 0 });
            assert.strictEqual(removeButton.disabled, true);
            assert.ok(removeButton.title.includes("Read-Only"));
            assert.strictEqual(removeButton.listeners.click, undefined);

            // Aktionen brechen mit Hinweis ab, ohne das Backend anzusprechen.
            await controller.addIconSource("C:/packs");
            await controller.removeIconSource("C:/packs");
            await controller.setIconSourceEnabled("C:/packs", false);
            await controller.moveIconSource("C:/packs", "up");
            await controller.pickIconSource("pack");
            await controller.updateVanillaIcons();
            assert.ok(!calls.some(call => call.url));
            assert.strictEqual(calls.filter(call => call.toast && call.toast.includes("Read-Only")).length, 6);
            })();
            """
        )
    )


_HINT_BANNER_HARNESS = r"""
    const assert = require("assert");
    const fs = require("fs");
    const vm = require("vm");
    const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
    const context = { window: {}, console };
    vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

    function bannerElement() {
        return {
            style: {},
            innerHTML: "",
            buttons: {},
            querySelector(selector) {
                if (!this.innerHTML.includes(selector.slice(1))) return null;
                if (!this.buttons[selector]) {
                    this.buttons[selector] = {
                        listeners: {},
                        addEventListener(type, fn) { this.listeners[type] = fn; },
                    };
                }
                return this.buttons[selector];
            },
        };
    }

    const panel = { innerHTML: "", querySelector() { return null; }, querySelectorAll() { return []; } };
    const iconManagerView = {
        iconManagerHtml(summary) { return `count:${summary.count}`; },
        iconManagerSummaryText(summary) { return `summary:${summary.count}`; },
    };
"""


def test_frontend_icon_hint_banner_shows_and_dismisses_via_workspace() -> None:
    _run_node(
        _HINT_BANNER_HARNESS
        + textwrap.dedent(
            r"""
            (async () => {
            const hintBanner = bannerElement();
            const emptyStateHint = { style: {} };
            let workspace = {};
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, hintBanner, emptyStateHint },
                fetchImpl: async () => ({ ok: true, headers: { get: () => "application/json" }, text: async () => "{}" }),
                parseJsonResponse: async () => ({ success: true, icons: {}, count: 0, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView,
                loadWorkspace: () => workspace,
                saveWorkspace: patch => { workspace = { ...workspace, ...patch }; return workspace; },
                isInventoryOpen: () => true,
            });

            await controller.loadLocalIconIndex();
            assert.strictEqual(hintBanner.style.display, "");
            assert.ok(hintBanner.innerHTML.includes("btnIconHintVanilla"));
            assert.ok(hintBanner.innerHTML.includes("btnIconHintDismiss"));
            assert.ok(!hintBanner.innerHTML.includes("disabled"));
            assert.strictEqual(emptyStateHint.style.display, "");

            hintBanner.buttons["#btnIconHintDismiss"].listeners.click();
            assert.strictEqual(workspace.icon_hint_dismissed, true);
            assert.strictEqual(hintBanner.style.display, "none");
            assert.strictEqual(hintBanner.innerHTML, "");
            // Der Empty-State-Hinweis bleibt als passiver Tipp sichtbar.
            assert.strictEqual(emptyStateHint.style.display, "");
            })();
            """
        )
    )


def test_frontend_icon_hint_banner_hidden_when_icons_exist_or_inventory_closed() -> None:
    _run_node(
        _HINT_BANNER_HARNESS
        + textwrap.dedent(
            r"""
            (async () => {
            // Mit vorhandenen Icons verschwinden Banner und Empty-State-Hinweis.
            const hintBanner = bannerElement();
            const emptyStateHint = { style: {} };
            const withIcons = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, hintBanner, emptyStateHint },
                fetchImpl: async () => ({ ok: true, headers: { get: () => "application/json" }, text: async () => "{}" }),
                parseJsonResponse: async () => ({ success: true, icons: { "minecraft:apple": "/i/a.png" }, count: 1, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView,
                loadWorkspace: () => ({}),
                isInventoryOpen: () => true,
            });
            await withIcons.loadLocalIconIndex();
            assert.strictEqual(hintBanner.style.display, "none");
            assert.strictEqual(emptyStateHint.style.display, "none");

            // Ohne offenes Inventar bleibt der Banner trotz fehlender Icons aus.
            const closedBanner = bannerElement();
            const closedHint = { style: {} };
            const closed = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, hintBanner: closedBanner, emptyStateHint: closedHint },
                fetchImpl: async () => ({ ok: true, headers: { get: () => "application/json" }, text: async () => "{}" }),
                parseJsonResponse: async () => ({ success: true, icons: {}, count: 0, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView,
                loadWorkspace: () => ({}),
                isInventoryOpen: () => false,
            });
            await closed.loadLocalIconIndex();
            assert.strictEqual(closedBanner.style.display, "none");
            assert.strictEqual(closedHint.style.display, "");

            // Bereits abgelehnter Hinweis bleibt dauerhaft aus.
            const dismissedBanner = bannerElement();
            const dismissed = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, hintBanner: dismissedBanner },
                fetchImpl: async () => ({ ok: true, headers: { get: () => "application/json" }, text: async () => "{}" }),
                parseJsonResponse: async () => ({ success: true, icons: {}, count: 0, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView,
                loadWorkspace: () => ({ icon_hint_dismissed: true }),
                isInventoryOpen: () => true,
            });
            await dismissed.loadLocalIconIndex();
            assert.strictEqual(dismissedBanner.style.display, "none");
            })();
            """
        )
    )


def test_frontend_icon_hint_banner_vanilla_button_confirms_and_updates() -> None:
    _run_node(
        _HINT_BANNER_HARNESS
        + textwrap.dedent(
            r"""
            (async () => {
            const hintBanner = bannerElement();
            const calls = [];
            let iconCount = 0;
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, hintBanner },
                fetchImpl: async (url, options = {}) => {
                    calls.push({ url, options });
                    return { ok: true, headers: { get: () => "application/json" }, text: async () => "{}" };
                },
                parseJsonResponse: async () => {
                    if (calls.some(call => call.url === "/api/icons/vanilla/update")) iconCount = 5;
                    return { success: true, icons: {}, count: iconCount, sources: [] };
                },
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView,
                loadWorkspace: () => ({}),
                isInventoryOpen: () => true,
                showConfirmDialog: async message => { calls.push({ confirm: message }); return true; },
            });

            await controller.loadLocalIconIndex();
            assert.strictEqual(hintBanner.style.display, "");

            await hintBanner.buttons["#btnIconHintVanilla"].listeners.click();
            assert.ok(calls.some(call => call.confirm && call.confirm.includes("Vanilla-Icons")));
            assert.ok(calls.some(call => call.url === "/api/icons/vanilla/update"));
            // Nach erfolgreichem Laden verschwindet der Banner automatisch.
            assert.strictEqual(hintBanner.style.display, "none");
            })();
            """
        )
    )


def test_frontend_icon_update_output_localizes_its_heading() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
            const context = {
                window: {
                    t: text => text === "Vanilla-Icons" ? "Vanilla icons" : text,
                },
                console,
            };
            vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });

            const output = [];
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                fetchImpl: async () => ({ ok: true, headers: { get: () => "application/json" }, text: async () => "{}" }),
                parseJsonResponse: async () => ({
                    success: true,
                    output: "Icons: 1/1 inventory items mapped",
                    icons: {},
                    count: 1,
                    sources: [],
                    manifest: { mapped_items: 1, known_items: 1 },
                }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView: {
                    iconManagerHtml() { return ""; },
                    iconManagerSummaryText() { return ""; },
                },
                appendUpdateOutput: message => output.push(message),
            });

            await controller.updateVanillaIcons();

            assert.ok(output[0].startsWith("\n=== Vanilla icons ===\n"));
            assert.ok(output[0].includes("Icons: 1/1 inventory items mapped"));
            })();
            """
        )
    )


def test_frontend_icon_hint_banner_locks_vanilla_button_in_read_only() -> None:
    _run_node(
        _HINT_BANNER_HARNESS
        + textwrap.dedent(
            r"""
            (async () => {
            const hintBanner = bannerElement();
            const controller = context.window.MCBEIconSourcesController.createIconSourcesController({
                elements: { panel, hintBanner },
                permissions: () => ({ canWriteAppState: false, canRescanIcons: false }),
                fetchImpl: async () => ({ ok: true, headers: { get: () => "application/json" }, text: async () => "{}" }),
                parseJsonResponse: async () => ({ success: true, icons: {}, count: 0, sources: [] }),
                withCsrf: () => ({ "Content-Type": "application/json" }),
                iconManagerView,
                loadWorkspace: () => ({}),
                isInventoryOpen: () => true,
            });

            await controller.loadLocalIconIndex();
            assert.strictEqual(hintBanner.style.display, "");
            assert.ok(hintBanner.innerHTML.includes("disabled"));
            assert.ok(hintBanner.innerHTML.includes("Read-Only"));
            })();
            """
        )
    )
