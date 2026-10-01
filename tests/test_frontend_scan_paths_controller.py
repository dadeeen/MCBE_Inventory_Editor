import textwrap

from tests.node_runner import run_node


def test_frontend_scan_paths_controller_loads_adds_and_refreshes() -> None:
    run_node(
        textwrap.dedent(
            r"""
            (async () => {
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/scan_paths_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/scan_paths_controller.js" });

            function button() {
                return {
                    listeners: {},
                    classList: { toggle(name, value) { this[name] = value; } },
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                    setAttribute(name, value) { this[name] = value; },
                };
            }

            const calls = [];
            const openButton = button();
            const confirmButton = button();
            const panel = { style: { display: "none" } };
            const list = { innerHTML: "", querySelectorAll: () => [] };
            const manualInput = { style: { display: "none" } };
            const textInput = { value: "C:/Worlds", focus() { this.focused = true; } };
            const status = { textContent: "old" };
            const controller = context.window.MCBEScanPathsController.createScanPathsController({
                elements: { panel, list, openButton, confirmButton, textInput, manualInput, status },
                fetchImpl: async (url, options = {}) => {
                    calls.push({ url, options });
                    return { ok: true, headers: { get: () => "application/json" }, text: async () => "{}" };
                },
                parseJsonResponse: async res => res.parsed || { success: true, scan_roots: [], default_path: "C:/Default" },
                withCsrf: () => ({ "X-CSRF-Token": "token" }),
                scanPathsHtml: () => "<p>paths</p>",
                updateAutoPathHint: (text, type) => calls.push({ hint: text, type }),
                scanWorlds: async () => calls.push({ scanWorlds: true }),
            });

            controller.wire();
            await openButton.listeners.click();
            assert.strictEqual(panel.style.display, "block");
            assert.strictEqual(list.innerHTML, "<p>paths</p>");
            assert.ok(calls.some(call => call.hint === "Standardordner erkannt: C:/Default"));

            await confirmButton.listeners.click();
            assert.strictEqual(textInput.value, "");
            assert.strictEqual(manualInput.style.display, "none");
            assert.ok(calls.some(call => call.url === "/api/scan_paths/add"));
            assert.ok(calls.some(call => call.scanWorlds));
            })();
            """
        )
    )
