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


def test_frontend_app_bootstrap_builds_runtime_context_and_reports_missing_csrf() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/app_bootstrap.js", "utf8");
            const errors = [];
            const context = {
                window: {
                    MCBEApiClient: {
                        createApiClient({ csrfToken }) {
                            return {
                                csrfToken,
                                withCsrf() { return { "X-CSRF-Token": csrfToken }; },
                                parseJsonResponse: "parse",
                                buildErrorMessage: "build",
                            };
                        },
                    },
                },
                document: {},
                console: { error(message) { errors.push(message); } },
            };
            vm.runInNewContext(code, context, { filename: "static/app_bootstrap.js" });

            const doc = {
                getElementById(id) {
                    if (id === "appConfigJson") return { textContent: '{"mode":"local","feature":true}' };
                    return null;
                },
                querySelector(selector) {
                    if (selector === 'meta[name="csrf-token"]') return { getAttribute: () => "csrf-123" };
                    return null;
                },
            };
            const runtime = context.window.MCBEAppBootstrap.createRuntimeContext({
                doc,
                win: context.window,
                consoleObj: context.console,
            });
            assert.strictEqual(runtime.csrfToken, "csrf-123");
            assert.strictEqual(runtime.withCsrf()["X-CSRF-Token"], "csrf-123");
            assert.strictEqual(runtime.appConfig.mode, "local");
            assert.strictEqual(runtime.appConfig.feature, true);
            assert.strictEqual(runtime.storageKeys.theme, "mcbe-inventory-editor:theme");
            assert.strictEqual(runtime.constants.inventorySlotCount, 36);
            assert.strictEqual(runtime.constants.itemIdPattern, "^[a-z0-9_.-]+:[a-z0-9_.-]+$");
            assert.deepStrictEqual(errors, []);

            const noTokenDoc = {
                getElementById() { return { textContent: "not-json" }; },
                querySelector() { return null; },
            };
            const noTokenRuntime = context.window.MCBEAppBootstrap.createRuntimeContext({
                doc: noTokenDoc,
                win: context.window,
                consoleObj: context.console,
            });
            assert.strictEqual(noTokenRuntime.csrfToken, "");
            assert.deepStrictEqual(Object.keys(noTokenRuntime.appConfig), []);
            assert.strictEqual(errors.length, 1);
            assert.ok(errors[0].includes("CSRF-Meta-Tag fehlt"));
            """
        )
    )


def test_frontend_app_bootstrap_icon_error_fallback_replaces_failed_images() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/app_bootstrap.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/app_bootstrap.js" });

            const listeners = [];
            const replaced = [];
            function fakeImg({ tagName = "IMG", fallback = null } = {}) {
                return {
                    tagName,
                    getAttribute(name) { return name === "data-icon-fallback" ? fallback : null; },
                    replaceWith(node) { replaced.push(node.textContent); },
                };
            }
            const doc = {
                addEventListener(type, handler, capture) { listeners.push({ type, handler, capture }); },
                createElement() { return { textContent: "" }; },
            };

            const bootstrap = context.window.MCBEAppBootstrap;
            assert.strictEqual(bootstrap.installIconErrorFallback(doc), true);
            // Doppelte Installation wird verhindert.
            assert.strictEqual(bootstrap.installIconErrorFallback(doc), false);
            assert.strictEqual(listeners.length, 1);
            assert.strictEqual(listeners[0].type, "error");
            assert.strictEqual(listeners[0].capture, true);

            const handler = listeners[0].handler;
            // Icon-Bild mit Fallback wird ersetzt.
            handler({ target: fakeImg({ fallback: "🗡️" }) });
            assert.deepStrictEqual(replaced, ["🗡️"]);
            // Leerer Fallback nutzt den generischen Platzhalter.
            handler({ target: fakeImg({ fallback: "" }) });
            assert.deepStrictEqual(replaced, ["🗡️", "□"]);
            // Bilder ohne data-icon-fallback und Nicht-Bilder bleiben unberührt.
            handler({ target: fakeImg({ fallback: null }) });
            handler({ target: { tagName: "DIV", getAttribute: () => "x" } });
            handler({ target: null });
            assert.strictEqual(replaced.length, 2);

            // Fake-Dokumente ohne addEventListener werden ignoriert.
            assert.strictEqual(bootstrap.installIconErrorFallback({}), false);
            """
        )
    )


def test_frontend_app_bootstrap_icon_tint_handler_multiplies_grayscale_icons() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/app_bootstrap.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/app_bootstrap.js" });

            const listeners = [];
            const ops = [];
            const fakeCtx = {
                globalCompositeOperation: "source-over",
                fillStyle: "",
                drawImage() { ops.push(["draw", this.globalCompositeOperation]); },
                fillRect() { ops.push(["fill", this.globalCompositeOperation, this.fillStyle]); },
            };
            const doc = {
                addEventListener(type, handler, capture) { listeners.push({ type, handler, capture }); },
                createElement(tag) {
                    return tag === "canvas"
                        ? { width: 0, height: 0, getContext: () => fakeCtx, toDataURL: () => "data:image/png;base64,TINTED" }
                        : { textContent: "" };
                },
            };

            const bootstrap = context.window.MCBEAppBootstrap;
            assert.strictEqual(bootstrap.installIconTintHandler(doc), true);
            assert.strictEqual(bootstrap.installIconTintHandler(doc), false);
            assert.strictEqual(listeners.length, 1);
            assert.strictEqual(listeners[0].type, "load");
            assert.strictEqual(listeners[0].capture, true);

            const handler = listeners[0].handler;
            const img = {
                tagName: "IMG",
                naturalWidth: 16,
                naturalHeight: 16,
                src: "/api/icons/abc",
                getAttribute(name) { return name === "data-icon-tint" ? "#a06540" : null; },
            };
            handler({ target: img });
            assert.strictEqual(img.src, "data:image/png;base64,TINTED");
            // Multiply-Tint mit Alpha-Wiederherstellung in der richtigen Reihenfolge.
            assert.deepStrictEqual(ops, [
                ["draw", "source-over"],
                ["fill", "multiply", "#a06540"],
                ["draw", "destination-in"],
            ]);

            // Zweites load-Event (durch den src-Tausch) wird ignoriert.
            handler({ target: img });
            assert.strictEqual(ops.length, 3);

            // Bilder ohne Tint-Attribut bleiben unangetastet.
            const plain = { tagName: "IMG", naturalWidth: 16, naturalHeight: 16, src: "x", getAttribute: () => null };
            handler({ target: plain });
            assert.strictEqual(plain.src, "x");
            """
        )
    )
