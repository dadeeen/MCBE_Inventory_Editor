import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_world_source_labels_use_active_locale_and_preserve_custom_labels() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const catalog = JSON.parse(fs.readFileSync("static/i18n/en.json", "utf8"));
                const t = text => catalog[text] ?? text;
                const context = { window: { t, MCBEI18n: { compare: (a, b) => a.localeCompare(b, "en") } } };
                vm.runInNewContext(fs.readFileSync("static/world_browser.js", "utf8"), context, {
                    filename: "static/world_browser.js",
                });

                const labels = context.window.MCBEWorldBrowser.sourceLabelForWorld;
                assert.strictEqual(labels({ source_kind: "configured-root", source_label: "Konfigurierter Welt-Root" }), "Configured world root");
                assert.strictEqual(labels({ source_kind: "minecraft-default", source_label: "Minecraft-Standardordner" }), "Minecraft default folder");
                assert.strictEqual(labels({ source_kind: "user-root", source_label: "Meine Welten" }), "Meine Welten");
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_world_scan_ignores_older_response() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");

                function deferred() {
                    let resolve;
                    const promise = new Promise(done => { resolve = done; });
                    return { promise, resolve };
                }

                const responses = [];
                const context = {
                    console,
                    fetch: () => {
                        const next = deferred();
                        responses.push(next);
                        return next.promise;
                    },
                    window: {
                        MCBEWorldCardsView: {
                            applyWorldCardsRender: () => true,
                            worldSearchStatusHtml: (title, body) => `${title}:${body}`,
                            applyWorldDiagnostics: () => {},
                        },
                        MCBEScanPathsView: { scanRootKindLabel: () => "root" },
                        MCBEPlayerDiagnostics: {
                            buildWorldDiagnosticsText: () => "",
                            buildPlayersDiagnosticsText: () => "",
                        },
                    },
                };
                vm.runInNewContext(fs.readFileSync("static/world_browser.js", "utf8"), context, { filename: "static/world_browser.js" });

                (async () => {
                    let lastScan = null;
                    const rendered = [];
                    const loading = { style: {} };
                    const controller = context.window.MCBEWorldBrowser.createWorldBrowserController({
                        elements: {
                            worldList: { innerHTML: "", querySelectorAll: () => [] },
                            worldPicker: { style: {} },
                            scanLoading: loading,
                            scanWarning: { style: {}, textContent: "" },
                            scanEmpty: { style: {}, innerHTML: "" },
                            countHint: { textContent: "" },
                        },
                        getLastWorldScan: () => lastScan,
                        setLastWorldScan: value => { lastScan = value; },
                        setLastRenderedWorlds: worlds => rendered.push(worlds.map(world => world.name)),
                        parseJsonResponse: response => response.json(),
                    });

                    const first = controller.scanWorlds();
                    const second = controller.scanWorlds();
                    responses[1].resolve({ json: async () => ({ success: true, worlds: [{ name: "new", path: "/new" }] }) });
                    await second;
                    assert.strictEqual(lastScan.worlds[0].name, "new");
                    assert.strictEqual(loading.style.display, "none");

                    responses[0].resolve({ json: async () => ({ success: true, worlds: [{ name: "old", path: "/old" }] }) });
                    await first;
                    assert.strictEqual(lastScan.worlds[0].name, "new");
                    assert.deepStrictEqual(rendered[rendered.length - 1], ["new"]);
                    assert.strictEqual(loading.style.display, "none");
                })().catch(error => {
                    console.error(error);
                    process.exit(1);
                });
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_world_folder_picker_replaces_running_status_with_terminal_status() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const statuses = [];
                const selected = [];
                const worldPathInput = { value: "" };
                const context = {
                    window: {},
                    fetch: async () => ({ payload: { success: true, path: "C:/World" } }),
                };
                vm.runInNewContext(fs.readFileSync("static/world_browser.js", "utf8"), context, {
                    filename: "static/world_browser.js",
                });
                const controller = context.window.MCBEWorldBrowser.createWorldBrowserController({
                    elements: { worldPathInput },
                    parseJsonResponse: async response => response.payload,
                    updateSelectedWorld: world => selected.push(world),
                    logStatus: (message, type, options) => statuses.push({ message, type, options }),
                });

                (async () => {
                    await controller.browseWorldFolder();
                    assert.strictEqual(worldPathInput.value, "C:/World");
                    assert.strictEqual(selected.length, 1);
                    assert.strictEqual(statuses[0].type, "running");
                    assert.strictEqual(statuses.at(-1).type, "success");
                    assert.ok(statuses.every(entry => entry.options.key === "world-folder-picker"));
                })().catch(error => {
                    console.error(error);
                    process.exit(1);
                });
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
