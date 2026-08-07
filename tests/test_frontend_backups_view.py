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


def test_frontend_backups_view_status_html_and_error_fallback() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const view = context.window.MCBEBackupsView;
            assert.strictEqual(
                view.backupsStatusHtml("loading"),
                '<div class="no-backups">Lade Sicherheitskopien...</div>',
            );
            assert.strictEqual(
                view.backupsStatusHtml("error"),
                '<div class="no-backups error">Fehler beim Laden der Backups.</div>',
            );
            assert.strictEqual(view.backupsListHtml({ success: false }), view.backupsStatusHtml("error"));
            """
        )
    )


def test_frontend_backups_view_folder_controls_and_applier() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const view = context.window.MCBEBackupsView;
            const controls = view.backupFolderControls({ backupDir: "C:/Backups", dockerMode: false });
            assert.strictEqual(controls.copyDisabled, false);
            assert.strictEqual(controls.openDisabled, false);
            assert.strictEqual(controls.openTitle, "Backupordner im Dateimanager öffnen");

            const buttons = {
                copyButton: { disabled: true },
                openButton: { disabled: true, title: "" },
            };
            view.applyBackupFolderControls(buttons, controls);
            assert.strictEqual(buttons.copyButton.disabled, false);
            assert.strictEqual(buttons.openButton.disabled, false);
            assert.strictEqual(buttons.openButton.title, "Backupordner im Dateimanager öffnen");

            const dockerControls = view.backupFolderControls({ backupDir: "C:/Backups", dockerMode: true });
            view.applyBackupFolderControls(buttons, dockerControls);
            assert.strictEqual(buttons.copyButton.disabled, false);
            assert.strictEqual(buttons.openButton.disabled, true);
            assert.strictEqual(buttons.openButton.title, "Im Docker-/LAN-Modus nur Pfad kopieren.");
            """
        )
    )


def test_frontend_backups_view_manual_backup_creates_and_refreshes() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const fetchCalls = [];
            const context = {
                window: {},
                console,
                fetch: async (url, init) => {
                    fetchCalls.push({ url, body: JSON.parse(init.body || "{}") });
                    if (url === "/api/backup/create") {
                        return { json: async () => ({ success: true, backup_file: "Welt_20260704.zip" }) };
                    }
                    return { json: async () => ({ success: true, backups: [], backup_dir: "C:/Backups" }) };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const toasts = [];
            const statuses = [];
            const createButton = { disabled: false, title: "", listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } };
            const container = { innerHTML: "", querySelectorAll: () => [] };
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { container, createButton },
                appConfig: { read_only: false },
                withCsrf: () => ({}),
                parseJsonResponse: response => response.json(),
                getWorldPath: () => "C:/world",
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
                showToast: (message, type) => toasts.push({ message, type }),
            });
            controller.wire();

            Promise.resolve()
                .then(() => createButton.listeners.click())
                .then(() => {
                    assert.strictEqual(fetchCalls[0].url, "/api/backup/create");
                    assert.strictEqual(fetchCalls[0].body.world_path, "C:/world");
                    // Nach dem Erstellen wird die Liste neu geladen.
                    assert.strictEqual(fetchCalls[1].url, "/api/backups");
                    assert.strictEqual(toasts[0].type, "success");
                    assert.ok(toasts[0].message.includes("Welt_20260704.zip"));
                    assert.strictEqual(statuses[0].type, "running");
                    assert.strictEqual(statuses.at(-1).type, "success");
                    assert.ok(statuses.at(-1).message.includes("Welt_20260704.zip"));
                    assert.ok(statuses.every(entry => entry.options.key === "backup-create"));
                    assert.strictEqual(createButton.disabled, false);
                })
                .catch(err => { console.error(err); process.exit(1); });
            """
        )
    )


def test_frontend_backups_view_manual_backup_keeps_write_gate_blocked_button_disabled() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const context = {
                window: {},
                console,
                fetch: async (url) => {
                    if (url === "/api/backup/create") {
                        return { json: async () => ({ success: false, error: "Server läuft noch." }) };
                    }
                    return { json: async () => ({ success: true, backups: [], backup_dir: "C:/Backups" }) };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const createButton = {
                disabled: true,
                title: "Server läuft noch.",
                dataset: { writeGateBlocked: "true" },
                listeners: {},
                addEventListener(type, fn) { this.listeners[type] = fn; },
            };
            const loading = [];
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { createButton },
                appConfig: { read_only: false },
                withCsrf: () => ({}),
                parseJsonResponse: response => response.json(),
                getWorldPath: () => "C:/world",
                showToast: () => {},
                showLoading: message => loading.push(["show", message]),
                hideLoading: () => loading.push(["hide"]),
            });
            controller.wire();

            Promise.resolve()
                .then(() => controller.createBackup())
                .then(() => {
                    assert.strictEqual(createButton.disabled, true);
                    assert.strictEqual(createButton.title, "Server läuft noch.");
                    assert.deepStrictEqual(loading, [
                        ["show", "Backup wird erstellt..."],
                        ["hide"],
                    ]);
                })
                .catch(err => { console.error(err); process.exit(1); });
            """
        )
    )


def test_frontend_backups_view_manual_backup_disabled_in_read_only_mode() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const createButton = { disabled: false, title: "", listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } };
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { createButton },
                appConfig: { read_only: true },
            });
            controller.wire();
            assert.strictEqual(createButton.disabled, true);
            assert.ok(createButton.title.includes("Read-Only"));
            """
        )
    )


def test_frontend_backups_view_ignores_out_of_order_world_response() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            const requests = { A: deferred(), B: deferred() };
            let worldPath = "A";
            const context = {
                window: {},
                console,
                fetch: async (_url, init) => requests[JSON.parse(init.body).world_path].promise,
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            (async () => {
                const container = { innerHTML: "", querySelectorAll: () => [] };
                const controller = context.window.MCBEBackupsView.createBackupsController({
                    elements: { container },
                    getWorldPath: () => worldPath,
                    parseJsonResponse: response => response.json(),
                });

                const loadA = controller.loadBackupsList();
                worldPath = "B";
                const loadB = controller.loadBackupsList();
                requests.B.resolve({
                    json: async () => ({
                        success: true,
                        backup_dir: "B:/Backups",
                        backups: [{ filename: "B.zip", date: "heute", size_mb: 1 }],
                    }),
                });
                await loadB;
                requests.A.resolve({
                    json: async () => ({
                        success: true,
                        backup_dir: "A:/Backups",
                        backups: [{ filename: "A.zip", date: "gestern", size_mb: 1 }],
                    }),
                });
                await loadA;

                assert.ok(container.innerHTML.includes("B.zip"));
                assert.ok(!container.innerHTML.includes("A.zip"));
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_backups_view_manual_backup_warns_after_successful_create_cleanup_failure() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const context = {
                window: {},
                console,
                fetch: async (url) => {
                    if (url === "/api/backup/create") {
                        return { json: async () => ({
                            success: true,
                            backup_file: "Welt_20260704.zip",
                            cleanup_warning: "Alte Backups konnten nicht bereinigt werden.",
                        }) };
                    }
                    return { json: async () => ({ success: true, backups: [], backup_dir: "C:/Backups" }) };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const toasts = [];
            const statuses = [];
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { createButton: { disabled: false, dataset: {} } },
                appConfig: { read_only: false },
                withCsrf: () => ({}),
                parseJsonResponse: response => response.json(),
                getWorldPath: () => "C:/world",
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
                showToast: (message, type, ms) => toasts.push({ message, type, ms }),
            });

            Promise.resolve()
                .then(() => controller.createBackup())
                .then(() => {
                    assert.strictEqual(toasts[0].type, "warning");
                    assert.strictEqual(toasts[0].ms, 7000);
                    assert.ok(toasts[0].message.includes("Welt_20260704.zip"));
                    assert.ok(toasts[0].message.includes("Alte Backups konnten nicht bereinigt werden."));
                    assert.strictEqual(statuses[0].type, "running");
                    assert.strictEqual(statuses.at(-1).type, "warning");
                    assert.ok(statuses.at(-1).message.includes("Alte Backups konnten nicht bereinigt werden."));
                    assert.ok(statuses.every(entry => entry.options.key === "backup-create"));
                })
                .catch(err => { console.error(err); process.exit(1); });
            """
        )
    )


def test_frontend_backups_view_renders_retention_classes_and_kind_badges() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const html = context.window.MCBEBackupsView.backupsListHtml({
                success: true,
                backup_dir: "C:/Backups",
                max_backups_per_world: 20,
                max_pre_restore_backups_per_world: 5,
                backups: [{
                    filename: "World__manual__20260712T100000Z__abc.zip",
                    kind: "manual",
                    kind_label: "Manuell",
                    date: "12.07.2026 12:00:00",
                    size_mb: 1.25,
                }],
            });
            assert.ok(html.includes("Automatisch/Legacy: max. 20"));
            assert.ok(html.includes("Vor Wiederherstellung: max. 5"));
            assert.ok(html.includes("Manuell: bis zur Löschung geschützt"));
            assert.ok(html.includes("backup-kind-manual"));
            assert.ok(html.includes(">Manuell<"));
            assert.ok(html.includes("data-delete-backup-filename"));
            """
        )
    )


def test_frontend_backups_view_deletes_backup_after_confirmation_and_refreshes() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const fetchCalls = [];
            const context = {
                window: {},
                console,
                fetch: async (url, init) => {
                    fetchCalls.push({ url, body: JSON.parse(init.body || "{}") });
                    if (url === "/api/backup/delete") {
                        return { json: async () => ({ success: true, backup_file: "manual.zip" }) };
                    }
                    return { json: async () => ({ success: true, backups: [], backup_dir: "C:/Backups" }) };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const toasts = [];
            const statuses = [];
            const container = { innerHTML: "", querySelectorAll: () => [] };
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { container },
                appConfig: { read_only: false },
                withCsrf: () => ({}),
                parseJsonResponse: response => response.json(),
                getWorldPath: () => "C:/world",
                confirmDelete: filename => filename === "manual.zip",
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
                showToast: (message, type) => toasts.push({ message, type }),
            });

            Promise.resolve()
                .then(() => controller.deleteBackup("manual.zip"))
                .then(result => {
                    assert.strictEqual(result, true);
                    assert.strictEqual(fetchCalls[0].url, "/api/backup/delete");
                    assert.strictEqual(fetchCalls[0].body.world_path, "C:/world");
                    assert.strictEqual(fetchCalls[0].body.backup_file, "manual.zip");
                    assert.strictEqual(fetchCalls[1].url, "/api/backups");
                    assert.strictEqual(toasts[0].type, "success");
                    assert.strictEqual(statuses[0].type, "running");
                    assert.strictEqual(statuses.at(-1).type, "success");
                    assert.ok(statuses.every(entry => entry.options.key === "backup-delete:manual.zip"));
                })
                .catch(err => { console.error(err); process.exit(1); });
            """
        )
    )


def test_frontend_backups_view_does_not_delete_without_confirmation() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            let fetchCount = 0;
            const context = {
                window: {},
                fetch: async () => { fetchCount += 1; return { json: async () => ({ success: true }) }; },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });
            const controller = context.window.MCBEBackupsView.createBackupsController({
                getWorldPath: () => "C:/world",
                confirmDelete: () => false,
            });

            Promise.resolve()
                .then(() => controller.deleteBackup("manual.zip"))
                .then(result => {
                    assert.strictEqual(result, false);
                    assert.strictEqual(fetchCount, 0);
                })
                .catch(err => { console.error(err); process.exit(1); });
            """
        )
    )


def test_frontend_backups_view_deduplicates_concurrent_delete_requests() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            let resolveDelete;
            let deleteCalls = 0;
            const deleteResponse = new Promise(resolve => { resolveDelete = resolve; });
            const context = {
                window: {},
                fetch: async url => {
                    if (url === "/api/backup/delete") {
                        deleteCalls += 1;
                        return deleteResponse;
                    }
                    return { json: async () => ({ success: true, backups: [] }) };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { container: { innerHTML: "", querySelectorAll: () => [] } },
                appConfig: { read_only: false },
                getWorldPath: () => "C:/world",
                confirmDelete: () => true,
            });

            (async () => {
                const first = controller.deleteBackup("manual.zip");
                const second = await controller.deleteBackup("manual.zip");
                assert.strictEqual(second, false);
                assert.strictEqual(deleteCalls, 1);
                resolveDelete({ json: async () => ({ success: true, backup_file: "manual.zip" }) });
                assert.strictEqual(await first, true);
                assert.strictEqual(deleteCalls, 1);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )
