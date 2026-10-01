import textwrap

from tests.node_runner import run_node


def test_new_confirmation_cancels_previous_promise_before_reusing_overlay() -> None:
    run_node(
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
    run_node(
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
    run_node(
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
    run_node(
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
    run_node(
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
    run_node(
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
                    closest: selector => ((selector === "[inert]" && node.blocked) || (selector === "[hidden]" && node.hiddenAbove) ? {} : null),
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
                node => { node.hiddenAbove = true; },
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


def test_focus_keeper_lands_in_the_new_view_only_for_an_element_no_longer_shown() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const document = { body: { name: "body" }, documentElement: {}, querySelector: () => null };
            document.activeElement = document.body;
            let lift = null;
            const window = {
                MutationObserver: class {
                    constructor(callback) { lift = callback; }
                    observe() {}
                },
            };
            const context = { document, setTimeout, window };
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, {
                filename: "static/ui_feedback.js",
            });
            function element(attributes = {}) {
                const node = {
                    attributes, isConnected: true, disabled: false, visible: true,
                    getAttribute: name => (name in attributes ? attributes[name] : null),
                    closest: () => null,
                    getClientRects: () => (node.visible ? [{}] : []),
                    focus() { document.activeElement = node; },
                };
                return node;
            }
            let focusin = null;
            const container = {
                inert: false,
                contains: () => true,
                addEventListener: (type, handler) => { if (type === "focusin") focusin = handler; },
                querySelector: () => null,
            };
            const heading = element({ "data-view-landing": "inventory" });
            let landings = 0;
            context.window.MCBEUiFeedback.createFocusKeeper({
                container, doc: document, win: window, landing: () => { landings += 1; return heading; },
            });

            // Nothing focused in the app yet: the lock moves no focus.
            lift();
            assert.strictEqual(document.activeElement, document.body);
            assert.strictEqual(landings, 0);

            // The load button is hidden after the view changed.
            const load = element({ id: "btnLoad" });
            focusin({ target: load });
            load.visible = false;
            lift();
            assert.strictEqual(document.activeElement, heading);

            // An element gone without a replacement lands there as well.
            const gone = element({});
            focusin({ target: gone });
            gone.isConnected = false;
            document.activeElement = document.body;
            lift();
            assert.strictEqual(document.activeElement, heading);

            // A disabled button that is still shown keeps the focus where it is.
            const save = element({ id: "btnSave" });
            focusin({ target: save });
            save.disabled = true;
            document.activeElement = document.body;
            landings = 0;
            lift();
            assert.strictEqual(document.activeElement, document.body);
            assert.strictEqual(landings, 0);
            """
        )
    )


def test_dialogs_return_the_focus_to_the_element_that_opened_them() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const document = { body: { name: "body" }, documentElement: {} };
            document.activeElement = document.body;
            function element(name, parent = null) {
                const node = {
                    name, parent, style: {}, textContent: "", onclick: null, isConnected: true, disabled: false,
                    closest: () => null,
                    getClientRects: () => [{}],
                    contains: other => { for (let at = other; at; at = at.parent) if (at === node) return true; return false; },
                    focus() { document.activeElement = node; },
                    addEventListener(type, handler) { (node.listeners ||= {})[type] = handler; },
                };
                return node;
            }
            const overlay = element("confirmOverlay");
            const ok = element("confirmOk", overlay);
            const cancel = element("confirmCancel", overlay);
            const message = element("confirmMessage", overlay);
            message.replaceChildren = () => {};
            const byId = { confirmOverlay: overlay, confirmOk: ok, confirmCancel: cancel, confirmMessage: message };
            document.getElementById = id => byId[id] || null;
            document.addEventListener = () => {};
            const context = { document, setTimeout, window: { document } };
            vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, {
                filename: "static/ui_feedback.js",
            });
            const feedback = context.window.MCBEUiFeedback;

            (async () => {
                // Cancelling returns the focus to the button that asked.
                const discard = element("discard");
                discard.focus();
                const first = feedback.showConfirmDialog("Verwerfen?");
                assert.strictEqual(document.activeElement, ok);
                cancel.onclick();
                assert.strictEqual(await first, false);
                assert.strictEqual(document.activeElement, discard);

                // A dialog replacing another still returns to the first opener.
                const second = feedback.showConfirmDialog("Erste Frage");
                const third = feedback.showConfirmDialog("Zweite Frage");
                assert.strictEqual(await second, false);
                assert.strictEqual(document.activeElement, ok);
                ok.onclick();
                assert.strictEqual(await third, true);
                assert.strictEqual(document.activeElement, discard);

                // It takes nothing from an element focused meanwhile, and
                // gives nothing to an opener that is disabled by then.
                const fourth = feedback.showConfirmDialog("Frage");
                const other = element("other");
                other.focus();
                ok.onclick();
                await fourth;
                assert.strictEqual(document.activeElement, other);
                discard.focus();
                const fifth = feedback.showConfirmDialog("Frage");
                discard.disabled = true;
                ok.onclick();
                await fifth;
                assert.strictEqual(document.activeElement, ok);
                discard.disabled = false;

                // Help returns the focus to its button as well.
                const helpOverlay = element("helpOverlay");
                const helpClose = element("helpClose", helpOverlay);
                const helpButton = element("helpButton");
                const help = feedback.createHelpOverlayController({
                    doc: document, openButton: helpButton, closeButton: helpClose, overlay: helpOverlay,
                });
                helpButton.focus();
                help.open();
                assert.strictEqual(helpOverlay.style.display, "flex");
                helpClose.focus();
                help.close();
                assert.strictEqual(helpOverlay.style.display, "none");
                assert.strictEqual(document.activeElement, helpButton);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )
