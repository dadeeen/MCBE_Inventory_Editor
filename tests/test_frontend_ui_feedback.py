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


def test_new_confirmation_cancels_previous_promise_before_reusing_overlay() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const overlay = { style: {} };
            const message = { replaceChildren() {}, textContent: "" };
            const ok = { style: {}, textContent: "", onclick: null, focus() {} };
            const cancel = { style: {}, textContent: "", onclick: null };
            const document = {
                getElementById(id) {
                    return {
                        confirmOverlay: overlay,
                        confirmMessage: message,
                        confirmOk: ok,
                        confirmCancel: cancel,
                    }[id] || null;
                },
                createElement() {
                    return {
                        append() {},
                        appendChild() {},
                        className: "",
                        textContent: "",
                    };
                },
            };
            const context = { document, setTimeout, window: {} };
            context.window.document = document;
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, {
                filename: "static/ui_feedback.js",
            });

            (async () => {
                const first = context.window.MCBEUiFeedback.showConfirmDialog("erste Aktion");
                const second = context.window.MCBEUiFeedback.showConfirmDialog("zweite Aktion");

                assert.strictEqual(await first, false, "die verdrängte Aktion muss sicher abgebrochen werden");
                assert.strictEqual(message.textContent, "zweite Aktion");
                assert.strictEqual(typeof ok.onclick, "function");
                ok.onclick();
                assert.strictEqual(await second, true);
                assert.strictEqual(ok.onclick, null);
                assert.strictEqual(cancel.onclick, null);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_confirmation_temporarily_yields_to_active_loading_overlay() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const confirmOverlay = { style: { display: "none" } };
            const loadingOverlay = { style: { display: "flex" } };
            const message = { replaceChildren() {}, textContent: "" };
            const ok = { style: {}, textContent: "", onclick: null, focus() {} };
            const cancel = { style: {}, textContent: "", onclick: null };
            const document = {
                getElementById(id) {
                    return {
                        confirmOverlay,
                        confirmMessage: message,
                        confirmOk: ok,
                        confirmCancel: cancel,
                        loadingOverlay,
                    }[id] || null;
                },
                createElement() {
                    return {
                        append() {},
                        appendChild() {},
                        className: "",
                        textContent: "",
                    };
                },
            };
            const context = { document, setTimeout, window: {} };
            context.window.document = document;
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, {
                filename: "static/ui_feedback.js",
            });

            (async () => {
                const confirmation = context.window.MCBEUiFeedback.showConfirmDialog("Sicherheitsabfrage");
                assert.strictEqual(loadingOverlay.style.display, "none");
                assert.strictEqual(confirmOverlay.style.display, "flex");
                ok.onclick();
                assert.strictEqual(await confirmation, true);
                assert.strictEqual(confirmOverlay.style.display, "none");
                assert.strictEqual(loadingOverlay.style.display, "flex");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_replaced_confirmation_does_not_restore_a_finished_loading_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const confirmOverlay = { style: { display: "none" } };
            const loadingOverlay = { style: { display: "none" } };
            const loadingText = { textContent: "" };
            const message = { replaceChildren() {}, textContent: "" };
            const ok = { style: {}, textContent: "", onclick: null, focus() {} };
            const cancel = { style: {}, textContent: "", onclick: null };
            const document = {
                getElementById(id) {
                    return {
                        confirmOverlay,
                        confirmMessage: message,
                        confirmOk: ok,
                        confirmCancel: cancel,
                        loadingOverlay,
                        loadingText,
                    }[id] || null;
                },
                createElement() {
                    return {
                        append() {},
                        appendChild() {},
                        className: "",
                        textContent: "",
                    };
                },
            };
            const context = { document, setTimeout, window: {} };
            context.window.document = document;
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, {
                filename: "static/ui_feedback.js",
            });

            (async () => {
                const feedback = context.window.MCBEUiFeedback;
                feedback.showLoading("erste Aktion läuft");
                const first = feedback.showConfirmDialog("erste Sicherheitsabfrage");
                const second = feedback.showConfirmDialog("zweite Sicherheitsabfrage");

                assert.strictEqual(await first, false);
                feedback.hideLoading();
                assert.strictEqual(loadingOverlay.style.display, "none");

                ok.onclick();
                assert.strictEqual(await second, true);
                assert.strictEqual(loadingOverlay.style.display, "none");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_clipboard_fallback_is_informational_and_cleared_when_dialog_closes() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const overlay = { style: {} };
            const textEl = {
                value: "",
                focus() {},
                select() { this.selected = true; },
            };
            const statuses = [];
            const cleared = [];
            const context = {
                navigator: {},
                setTimeout(callback) { callback(); },
                window: {},
            };
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, {
                filename: "static/ui_feedback.js",
            });

            const controller = context.window.MCBEUiFeedback.createClipboardFeedbackController({
                elements: { overlay, textEl },
                clipboard: { async writeText() { throw new Error("blocked"); } },
                logStatus: (...args) => statuses.push(args),
                clearStatus: key => cleared.push(key),
                showToastFn() {},
            });

            (async () => {
                assert.strictEqual(await controller.copyTextToClipboard("Diagnose"), false);
                assert.strictEqual(overlay.style.display, "flex");
                assert.strictEqual(textEl.value, "Diagnose");
                assert.strictEqual(textEl.selected, true);
                assert.strictEqual(statuses.length, 1);
                assert.strictEqual(statuses[0][1], "info");
                assert.strictEqual(statuses[0][2].key, "clipboard-copy:fallback");
                assert.strictEqual(statuses[0][2].active, false);

                controller.closeFallback();
                assert.strictEqual(overlay.style.display, "none");
                assert.deepStrictEqual(cleared, ["clipboard-copy:fallback"]);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_missing_clipboard_fallback_remains_a_real_warning() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const statuses = [];
            const context = { navigator: {}, setTimeout, window: {} };
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context);
            const controller = context.window.MCBEUiFeedback.createClipboardFeedbackController({
                elements: {},
                clipboard: { async writeText() { throw new Error("blocked"); } },
                logStatus: (...args) => statuses.push(args),
                showToastFn() {},
            });

            (async () => {
                assert.strictEqual(await controller.copyTextToClipboard("Diagnose"), false);
                assert.strictEqual(statuses.length, 1);
                assert.strictEqual(statuses[0][1], "warning");
                assert.strictEqual(statuses[0][2].active, true);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_focus_keeper_returns_the_focus_once_the_app_is_usable_again() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const document = { body: { name: "body" }, documentElement: {}, activeElement: null, modalOpen: false };
            document.querySelector = selector => (selector.startsWith(".modal-overlay") && document.modalOpen ? {} : null);
            document.activeElement = document.body;
            let observed = null;
            const window = {
                MutationObserver: class {
                    constructor(callback) { this.callback = callback; }
                    observe(target, options) { observed = { callback: this.callback, target, options }; }
                },
            };
            const context = { document, setTimeout, window };
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, {
                filename: "static/ui_feedback.js",
            });
            const feedback = context.window.MCBEUiFeedback;

            const elements = [];
            function element(attributes = {}) {
                const node = {
                    attributes, isConnected: true, inside: true, disabled: false, blocked: false, visible: true,
                    getAttribute: name => (name in attributes ? attributes[name] : null),
                    closest: selector => (selector === "[inert], [hidden]" && node.blocked ? {} : null),
                    getClientRects: () => (node.visible ? [{}] : []),
                    focus(options) { node.focusOptions = options; document.activeElement = node; },
                };
                elements.push(node);
                return node;
            }
            let focusin = null;
            const container = {
                inert: false,
                contains: node => Boolean(node?.inside),
                addEventListener: (type, handler) => { if (type === "focusin") focusin = handler; },
                querySelector: selector => elements.find(node => node.isConnected
                    && Object.entries(node.attributes).some(([name, value]) => selector === `[${name}="${value}"]`)) || null,
            };
            const keeper = feedback.createFocusKeeper({ container, doc: document, win: window });
            assert.strictEqual(observed.target, container);
            assert.deepStrictEqual([...observed.options.attributeFilter], ["inert"]);
            const lift = () => { container.inert = false; observed.callback(); };

            // The lock drops the focus; lifting it returns the focus without scrolling.
            const button = element({ id: "btnStatus" });
            focusin({ target: button });
            container.inert = true;
            document.activeElement = document.body;
            lift();
            assert.strictEqual(document.activeElement, button);
            assert.strictEqual(button.focusOptions.preventScroll, true);

            // An element rendered anew is found by its slot or player key.
            const slot = element({ "data-slot": "3" });
            focusin({ target: slot });
            slot.isConnected = false;
            const newSlot = element({ "data-slot": "3" });
            document.activeElement = document.body;
            lift();
            assert.strictEqual(document.activeElement, newSlot);
            const row = element({ "data-player-key": "p1" });
            focusin({ target: row });
            row.isConnected = false;
            const newRow = element({ "data-player-key": "p1" });
            document.activeElement = document.body;
            assert.strictEqual(keeper.restore(), true);
            assert.strictEqual(document.activeElement, newRow);

            // It takes nothing from another element or an open dialog, and
            // gives the focus only to a usable element.
            const other = element({ id: "dialogButton" });
            other.inside = false;
            document.activeElement = other;
            assert.strictEqual(keeper.restore(), false);
            document.activeElement = document.body;
            document.modalOpen = true;
            assert.strictEqual(keeper.restore(), false);
            document.modalOpen = false;
            container.inert = true;
            assert.strictEqual(keeper.restore(), false);
            container.inert = false;
            for (const change of [
                node => { node.disabled = true; },
                node => { node.blocked = true; },
                node => { node.visible = false; },
                node => { node.inside = false; },
            ]) {
                const target = element({ id: `target${elements.length}` });
                focusin({ target });
                change(target);
                document.activeElement = document.body;
                assert.strictEqual(keeper.restore(), false);
                assert.strictEqual(document.activeElement, document.body);
            }

            // Without the app area there is nothing to keep.
            assert.strictEqual(feedback.createFocusKeeper({ container: null }).restore(), false);
            // Locators quote their value.
            assert.strictEqual(feedback.focusLocator(element({ id: 'a"b\\c' })), '[id="a\\"b\\\\c"]');
            assert.strictEqual(feedback.focusLocator(element({ "data-ender-slot": "0" })), '[data-ender-slot="0"]');
            assert.strictEqual(feedback.focusLocator(element({})), "");
            """
        )
    )
