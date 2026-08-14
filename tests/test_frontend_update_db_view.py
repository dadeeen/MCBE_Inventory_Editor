from __future__ import annotations

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


def test_database_update_replaces_running_status_with_success() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const context = { window: {}, console };
                vm.runInNewContext(fs.readFileSync("static/status_store.js", "utf8"), context);
                vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);

                const store = context.window.MCBEStatusStore.createStatusStore();
                const outputEl = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
                let reloadFinished = false;
                const controller = context.window.MCBEUpdateDbView.createUpdateDbController({
                    outputEl,
                    fetchImpl: async () => ({ payload: { success: true, reloaded: true } }),
                    parseJsonResponse: async response => response.payload,
                    withCsrf: () => ({ "X-CSRF-Token": "test" }),
                    logStatus: (message, type, options) => store.addNotice({ message, type, ...options }),
                    onReloaded: async () => {
                        await Promise.resolve();
                        reloadFinished = true;
                    },
                });

                (async () => {
                    await controller.run(false, true);
                    assert.strictEqual(reloadFinished, true);
                    const notices = store.allNotices();
                    assert.strictEqual(notices.length, 1);
                    assert.strictEqual(notices[0].key, "database-update:apply");
                    assert.strictEqual(notices[0].type, "success");
                    assert.strictEqual(notices[0].message, "Update erfolgreich.");
                    assert.strictEqual(notices[0].active, false);
                })().catch(error => { console.error(error); process.exit(1); });
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_database_update_can_force_full_scope_without_mutating_tools_selection() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);

            const requests = [];
            const onlySelect = {
                value: "items",
                disabled: false,
                selectedIndex: 1,
                options: [
                    { value: "", text: "Alles" },
                    { value: "items", text: "Nur Items" },
                ],
            };
            const outputEl = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
            const controller = context.window.MCBEUpdateDbView.createUpdateDbController({
                outputEl,
                onlySelect,
                fetchImpl: async (_url, options) => {
                    requests.push(JSON.parse(options.body));
                    return { payload: { success: true, reloaded: true } };
                },
                parseJsonResponse: async response => response.payload,
                withCsrf: () => ({}),
            });

            (async () => {
                await controller.run(false, true, { only: null });
                assert.strictEqual(requests.length, 1);
                assert.strictEqual(requests[0].only, null);
                assert.strictEqual(onlySelect.value, "items");
                assert.match(outputEl.textContent, /Bereich: Alles/);
            })().catch(error => { console.error(error); process.exit(1); });
            """
        )
    )


def test_database_update_surfaces_loaded_player_refresh_warning() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(fs.readFileSync("static/status_store.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);

            const store = context.window.MCBEStatusStore.createStatusStore();
            const toasts = [];
            const outputEl = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
            const controller = context.window.MCBEUpdateDbView.createUpdateDbController({
                outputEl,
                fetchImpl: async () => ({ payload: { success: true, reloaded: true } }),
                parseJsonResponse: async response => response.payload,
                withCsrf: () => ({ "X-CSRF-Token": "test" }),
                logStatus: (message, type, options) => store.addNotice({ message, type, ...options }),
                showToast: (message, type, duration) => toasts.push({ message, type, duration }),
                onReloaded: async () => ({ warning: "Spieler später neu laden." }),
            });

            (async () => {
                await controller.run(false, true);
                const notice = store.allNotices()[0];
                assert.strictEqual(notice.type, "warning");
                assert.strictEqual(notice.active, true);
                assert.strictEqual(notice.message, "Spieler später neu laden.");
                assert.strictEqual(toasts.length, 1);
                assert.strictEqual(toasts[0].type, "warning");
                assert.strictEqual(toasts[0].duration, 8000);
                assert.match(outputEl.textContent, /Datenbank aktualisiert und Server neu geladen/);
                assert.match(outputEl.textContent, /Spieler später neu laden/);
            })().catch(error => { console.error(error); process.exit(1); });
            """
        )
    )


def test_loaded_player_refresh_policy_preserves_dirty_state_and_refreshes_clean_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);
            const refresh = context.window.MCBEUpdateDbView.refreshLoadedPlayerAfterDbUpdate;

            (async () => {
                const calls = [];
                const loadPlayer = async (...args) => {
                    calls.push(args);
                    return true;
                };

                assert.deepStrictEqual(
                    JSON.parse(JSON.stringify(await refresh({ currentPlayerKey: "", loadPlayer }))),
                    {},
                );
                assert.strictEqual(calls.length, 0);

                const dirty = await refresh({
                    currentPlayerKey: "local_player",
                    isDirty: true,
                    loadPlayer,
                });
                assert.match(dirty.warning, /ungespeicherter Änderungen/);
                assert.strictEqual(calls.length, 0);

                const clean = await refresh({
                    currentPlayerKey: "local_player",
                    isDirty: false,
                    loadPlayer,
                });
                assert.strictEqual(clean.warning, undefined);
                assert.strictEqual(calls.length, 1);
                assert.strictEqual(
                    JSON.stringify(calls[0]),
                    JSON.stringify(["local_player", true, { showLoadingOverlay: false }]),
                );

                const failed = await refresh({
                    currentPlayerKey: "local_player",
                    loadPlayer: async () => false,
                });
                assert.match(failed.warning, /manuell neu/);
            })().catch(error => { console.error(error); process.exit(1); });
            """
        )
    )


def test_app_wires_current_player_state_into_database_refresh_policy() -> None:
    source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    callback = source.split("// --- DB Update Management ---", 1)[1].split("// --- End DB Update Management ---", 1)[0]

    assert "async onReloaded(data)" in callback
    assert "refreshLoadedPlayerAfterDbUpdate({" in callback
    assert "currentPlayerKey," in callback
    assert "isDirty," in callback
    assert "loadPlayer," in callback


def test_update_controllers_do_not_expose_manual_release_cache_controls() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const elements = {};
            const document = { getElementById: id => elements[id] || null };
            const context = { window: {}, document, console, fetch: async () => ({}) };
            vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/icon_sources_controller.js", "utf8"), context);

            const dbElements = context.window.MCBEUpdateDbView.collectUpdateDbElements(document);
            const iconElements = context.window.MCBEIconSourcesController.collectInventoryIconSourceElements(document);
            assert.strictEqual(Object.hasOwn(dbElements, "useCacheCheckbox"), false);
            assert.strictEqual(Object.hasOwn(iconElements, "useCacheCheckbox"), false);

            const payload = context.window.MCBEUpdateDbView.updateDbPayload({
                dryRun: true,
                force: false,
                onlySelect: { value: "items" },
            });
            assert.strictEqual(Object.hasOwn(payload, "use_cache"), false);
            """
        )
    )


def test_apply_uses_source_receipt_from_matching_successful_dry_run() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);

            const requests = [];
            const responses = [
                { success: true, output: "preview", update_review_token: "a".repeat(64), resource_pack_release: "v1.26.40.5" },
                { success: true, output: "apply", reloaded: true },
            ];
            const onlySelect = {
                value: "items",
                options: [{ value: "items", text: "Nur Items" }],
                addEventListener() {},
            };
            const outputEl = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
            const controller = context.window.MCBEUpdateDbView.createUpdateDbController({
                outputEl,
                onlySelect,
                fetchImpl: async (_url, options) => {
                    requests.push(JSON.parse(options.body));
                    return { payload: responses.shift() };
                },
                parseJsonResponse: async response => response.payload,
                withCsrf: () => ({}),
            });

            (async () => {
                await controller.run(true, false);
                await controller.run(false, true);
                assert.strictEqual(requests.length, 2);
                assert.strictEqual(Object.hasOwn(requests[0], "expected_update_review_token"), false);
                assert.strictEqual(requests[1].expected_update_review_token, "a".repeat(64));
                assert.match(outputEl.textContent, /im Dry-Run geprüfte Quellen \(Mojang v1\.26\.40\.5\)/);
            })().catch(error => { console.error(error); process.exit(1); });
            """
        )
    )


def test_dry_run_does_not_resolve_apply_reload_warning() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(fs.readFileSync("static/status_store.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);

            const store = context.window.MCBEStatusStore.createStatusStore();
            const responses = [
                { success: true, update_committed: true, reload_warning: "Neustart erforderlich." },
                { success: true, reloaded: false },
            ];
            const outputEl = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
            const controller = context.window.MCBEUpdateDbView.createUpdateDbController({
                outputEl,
                fetchImpl: async () => ({ payload: responses.shift() }),
                parseJsonResponse: async response => response.payload,
                withCsrf: () => ({ "X-CSRF-Token": "test" }),
                logStatus: (message, type, options) => store.addNotice({ message, type, ...options }),
            });

            (async () => {
                await controller.run(false, true);
                await controller.run(true, false);
                const notices = store.allNotices();
                const applyNotice = notices.find(entry => entry.key === "database-update:apply");
                const dryRunNotice = notices.find(entry => entry.key === "database-update:dry-run");
                assert.strictEqual(applyNotice.type, "warning");
                assert.strictEqual(applyNotice.active, true);
                assert.strictEqual(applyNotice.message, "Neustart erforderlich.");
                assert.strictEqual(dryRunNotice.type, "success");
                assert.strictEqual(dryRunNotice.active, false);
            })().catch(error => { console.error(error); process.exit(1); });
            """
        )
    )


def test_update_output_normalizes_spacing_and_classifies_web_formatting() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);

            const view = context.window.MCBEUpdateDbView;
            const output = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
            view.appendOutput(output, "--- 1/4 · Resource Pack herunterladen ---\n\n");
            view.appendOutput(output, "  Alles aktuell, keine Änderungen.\n");

            assert.strictEqual(
                output.textContent,
                "--- 1/4 · Resource Pack herunterladen ---\n  Alles aktuell, keine Änderungen.\n",
            );
            assert.strictEqual(view.outputLineType("=== Update gestartet ==="), "banner");
            assert.strictEqual(view.outputLineType("--- 3/4 · Items verarbeiten ---"), "step");
            assert.strictEqual(view.outputLineType("Alles aktuell, keine Änderungen."), "success");
            assert.strictEqual(view.outputLineType("Fehler: Download fehlgeschlagen"), "error");

            const document = {
                createDocumentFragment() {
                    return { children: [], appendChild(node) { this.children.push(node); } };
                },
                createElement() {
                    return { className: "", textContent: "" };
                },
                createTextNode(text) {
                    return { textContent: text, textNode: true };
                },
            };
            const rendered = {
                ownerDocument: document,
                replaceChildren(fragment) { this.children = fragment.children; },
            };
            view.renderOutput(rendered, "<script>alert(1)</script>\n--- 3/4 · Items verarbeiten ---");
            assert.strictEqual(rendered.children[0].textContent, "<script>alert(1)</script>");
            assert.strictEqual(rendered.children[0].className, "");
            assert.strictEqual(rendered.children[2].className, "update-log-step");
            """
        )
    )
