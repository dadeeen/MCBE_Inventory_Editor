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
