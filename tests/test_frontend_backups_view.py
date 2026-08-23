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


def test_frontend_backups_view_reconciles_new_restore_buttons_with_write_gate() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const restoreButton = {
                disabled: false,
                dataset: { backupFilename: "manual.zip" },
                addEventListener() {},
            };
            let renderedHtml = "";
            let syncCalls = 0;
            const container = {
                get innerHTML() { return renderedHtml; },
                set innerHTML(value) { renderedHtml = value; },
                querySelectorAll(selector) {
                    if (selector.startsWith(".restore-btn") && renderedHtml.includes("restore-btn")) {
                        return [restoreButton];
                    }
                    return [];
                },
            };
            const context = {
                window: {},
                console,
                fetch: async () => ({
                    json: async () => ({
                        success: true,
                        backup_dir: "C:/Backups",
                        backups: [{ filename: "manual.zip", date: "heute", size_mb: 1, kind: "manual" }],
                    }),
                }),
            };
            vm.runInNewContext(
                fs.readFileSync("static/backups_view.js", "utf8"),
                context,
                { filename: "static/backups_view.js" },
            );
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { container },
                getWorldPath: () => "C:/World",
                syncWriteControls: () => {
                    syncCalls += 1;
                    container.querySelectorAll(".restore-btn").forEach(button => { button.disabled = true; });
                },
            });

            (async () => {
                assert.strictEqual(await controller.loadBackupsList(), true);
                assert.strictEqual(syncCalls, 1);
                assert.strictEqual(restoreButton.disabled, true);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
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
            assert.strictEqual(controls.copyTitle, "Backupordner-Pfad kopieren");
            assert.strictEqual(controls.openDisabled, false);
            assert.strictEqual(controls.openTitle, "Backupordner im Dateimanager öffnen");

            const buttons = {
                copyButton: { disabled: true, title: "" },
                openButton: { disabled: true, title: "" },
            };
            view.applyBackupFolderControls(buttons, controls);
            assert.strictEqual(buttons.copyButton.disabled, false);
            assert.strictEqual(buttons.copyButton.title, "Backupordner-Pfad kopieren");
            assert.strictEqual(buttons.openButton.disabled, false);
            assert.strictEqual(buttons.openButton.title, "Backupordner im Dateimanager öffnen");

            const dockerControls = view.backupFolderControls({ backupDir: "C:/Backups", dockerMode: true });
            view.applyBackupFolderControls(buttons, dockerControls);
            assert.strictEqual(buttons.copyButton.disabled, false);
            assert.strictEqual(buttons.openButton.disabled, true);
            assert.strictEqual(buttons.openButton.title, "Im Docker-/LAN-Modus nur Pfad kopieren.");

            const noWorld = view.backupFolderControls({ dockerMode: true, folderState: "no-world" });
            view.applyBackupFolderControls(buttons, noWorld);
            assert.strictEqual(buttons.copyButton.disabled, true);
            assert.strictEqual(buttons.openButton.disabled, true);
            assert.strictEqual(buttons.copyButton.title, "Bitte zuerst eine Welt laden.");
            assert.strictEqual(buttons.openButton.title, "Bitte zuerst eine Welt laden.");

            const loading = view.backupFolderControls({ folderState: "loading" });
            view.applyBackupFolderControls(buttons, loading);
            assert.strictEqual(buttons.copyButton.title, "Backupordner wird geladen...");
            assert.strictEqual(buttons.openButton.title, "Backupordner wird geladen...");

            const unavailable = view.backupFolderControls({ folderState: "unavailable" });
            view.applyBackupFolderControls(buttons, unavailable);
            assert.strictEqual(buttons.copyButton.title, "Backupordner ist derzeit nicht verfügbar.");
            assert.strictEqual(buttons.openButton.title, "Backupordner ist derzeit nicht verfügbar.");
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
                        return { json: async () => ({
                            success: false,
                            error: "Server läuft noch.",
                            write_gate: {
                                allowed: false,
                                reason: "Server läuft noch.",
                                server_status: { status: "online" },
                            },
                        }) };
                    }
                    return { json: async () => ({ success: true, backups: [], backup_dir: "C:/Backups" }) };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const createButton = {
                disabled: false,
                title: "",
                dataset: { writeGateBlocked: "false" },
                listeners: {},
                addEventListener(type, fn) { this.listeners[type] = fn; },
            };
            const loading = [];
            const renderedGates = [];
            const controller = context.window.MCBEBackupsView.createBackupsController({
                elements: { createButton },
                appConfig: { read_only: false },
                withCsrf: () => ({}),
                parseJsonResponse: response => response.json(),
                getWorldPath: () => "C:/world",
                showToast: () => {},
                showLoading: message => loading.push(["show", message]),
                hideLoading: () => loading.push(["hide"]),
                beginServerStatusRequest: () => 41,
                renderWriteGate: (gate, options) => {
                    renderedGates.push({ gate, options });
                    createButton.dataset.writeGateBlocked = "true";
                    createButton.disabled = true;
                    createButton.title = gate.reason;
                },
            });
            controller.wire();

            Promise.resolve()
                .then(() => controller.createBackup())
                .then(() => {
                    assert.strictEqual(createButton.disabled, true);
                    assert.strictEqual(createButton.title, "Server läuft noch.");
                    assert.strictEqual(renderedGates.length, 1);
                    assert.strictEqual(renderedGates[0].gate.server_status.status, "online");
                    assert.strictEqual(renderedGates[0].options.requestOrder, 41);
                    assert.deepStrictEqual(loading, [
                        ["show", "Backup wird erstellt..."],
                        ["hide"],
                    ]);
                })
                .catch(err => { console.error(err); process.exit(1); });
            """
        )
    )


def test_frontend_backups_view_manual_backup_runtime_guard_prevents_stale_click() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            let fetchCalls = 0;
            const context = {
                window: {},
                console,
                fetch: async () => {
                    fetchCalls += 1;
                    return { json: async () => ({ success: true }) };
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/backups_view.js", "utf8"),
                context,
                { filename: "static/backups_view.js" },
            );

            let guardCalls = 0;
            const controller = context.window.MCBEBackupsView.createBackupsController({
                getWorldPath: () => "C:/World",
                guardWorldWriteAction: () => {
                    guardCalls += 1;
                    return true;
                },
            });

            (async () => {
                assert.strictEqual(await controller.createBackup(), false);
                assert.strictEqual(guardCalls, 1);
                assert.strictEqual(fetchCalls, 0);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
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


def test_frontend_backups_view_shows_what_actually_failed() -> None:
    """A concrete server message tells the user what to do; the blanket one does not.

    The payload is localized from ``message_key`` at the display boundary rather
    than taken from the server's already-rendered ``message``, so an API locale
    negotiated separately cannot leak into the active page language.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const view = (() => {
                const context = { window: {} };
                vm.runInNewContext(code, context, { filename: "static/backups_view.js" });
                return context.window.MCBEBackupsView;
            })();

            // The rendered message wins over the blanket text ...
            assert.ok(
                view.backupsListHtml({ success: false }, { errorMessage: "Welt-Ordner existiert nicht." })
                    .includes("Welt-Ordner existiert nicht."),
            );
            // ... and is escaped, because it crosses the server boundary.
            assert.ok(
                view.backupsListHtml({ success: false }, { errorMessage: "<img src=x onerror=alert(1)>" })
                    .includes("&lt;img"),
            );
            // Without a message the blanket text stays as the last resort.
            assert.strictEqual(view.backupsListHtml({ success: false }), view.backupsStatusHtml("error"));
            assert.strictEqual(view.backupsListHtml({ success: false }, { errorMessage: "   " }), view.backupsStatusHtml("error"));

            // The controller must localize message_key rather than reuse message.
            const translations = { "Welt-Ordner {path} existiert nicht.": "World folder {path} does not exist." };
            const translate = (text, params) =>
                String(translations[text] || text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m));
            const context = {
                window: { t: translate },
                console,
                fetch: async () => ({
                    json: async () => ({
                        success: false,
                        code: "invalid_request",
                        message_key: "Welt-Ordner {path} existiert nicht.",
                        params: { path: "C:/Gone" },
                        message: "Welt-Ordner C:/Gone existiert nicht.",
                    }),
                }),
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            (async () => {
                const container = { innerHTML: "", querySelectorAll: () => [] };
                const controller = context.window.MCBEBackupsView.createBackupsController({
                    elements: { container },
                    getWorldPath: () => "C:/Gone",
                    parseJsonResponse: response => response.json(),
                    buildErrorMessage: (data, fallback) =>
                        (data?.message_key ? context.window.t(data.message_key, data.params) : data?.error) || fallback,
                });

                await controller.loadBackupsList();
                assert.ok(container.innerHTML.includes("World folder C:/Gone does not exist."), container.innerHTML);
                assert.ok(!container.innerHTML.includes("Fehler beim Laden"), container.innerHTML);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_backups_view_asks_for_a_world_instead_of_reporting_an_error() -> None:
    """Without a world there is nothing to load, and that is not a failure.

    The endpoint rejects an empty world path, so the view used to render the red
    "Error loading the backups" box before the user had picked anything -- which
    reads as if existing archives had become unreadable. The folder buttons must
    not keep pointing at the previously loaded world either.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");

            let worldPath = "C:/World";
            const fetchCalls = [];
            const context = {
                window: {},
                console,
                fetch: async (url, init) => {
                    fetchCalls.push(JSON.parse(init.body).world_path);
                    return { json: async () => ({ success: true, backup_dir: "C:/Backups", backups: [] }) };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            (async () => {
                const container = { innerHTML: "", querySelectorAll: () => [] };
                const copyButton = { disabled: false };
                const openButton = { disabled: false, title: "" };
                const controller = context.window.MCBEBackupsView.createBackupsController({
                    elements: { container, copyFolderButton: copyButton, openFolderButton: openButton },
                    getWorldPath: () => worldPath,
                    parseJsonResponse: response => response.json(),
                });

                await controller.loadBackupsList();
                assert.deepStrictEqual(fetchCalls, ["C:/World"]);
                assert.strictEqual(copyButton.disabled, false);

                // The world is released again: no request, no error box.
                worldPath = "";
                const loaded = await controller.loadBackupsList();
                assert.strictEqual(loaded, false);
                assert.deepStrictEqual(fetchCalls, ["C:/World"]);
                assert.ok(container.innerHTML.includes("Bitte zuerst eine Welt laden."), container.innerHTML);
                assert.ok(!container.innerHTML.includes("Fehler beim Laden"), container.innerHTML);
                assert.ok(!container.innerHTML.includes("no-backups error"), container.innerHTML);
                assert.strictEqual(copyButton.disabled, true);
                assert.strictEqual(openButton.disabled, true);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
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


def test_frontend_backups_view_invalidates_stale_folder_during_load_and_after_failures() -> None:
    """Folder actions must always belong to the currently rendered world.

    A successful response for world A used to leave its directory enabled while
    world B was loading and even after B failed. Copying then silently copied
    A's path although the list showed B's error.
    """

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

            const responseB = deferred();
            let worldPath = "A";
            const context = {
                window: {},
                console,
                fetch: async (_url, init) => {
                    const requestedWorld = JSON.parse(init.body).world_path;
                    if (requestedWorld === "A") {
                        return { json: async () => ({ success: true, backup_dir: "A:/Backups", backups: [] }) };
                    }
                    if (requestedWorld === "B") return responseB.promise;
                    throw new Error("network unavailable");
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            (async () => {
                const copied = [];
                const container = { innerHTML: "", querySelectorAll: () => [] };
                const copyButton = {
                    disabled: false,
                    title: "",
                    listeners: {},
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                };
                const openButton = {
                    disabled: false,
                    title: "",
                    listeners: {},
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                };
                const controller = context.window.MCBEBackupsView.createBackupsController({
                    elements: { container, copyFolderButton: copyButton, openFolderButton: openButton },
                    getWorldPath: () => worldPath,
                    parseJsonResponse: response => response.json(),
                    copyTextToClipboard: value => copied.push(value),
                });
                controller.wire();

                await controller.loadBackupsList();
                assert.strictEqual(copyButton.disabled, false);
                assert.strictEqual(openButton.disabled, false);
                copyButton.listeners.click();
                assert.deepStrictEqual(copied, ["A:/Backups"]);

                worldPath = "B";
                const loadingB = controller.loadBackupsList();
                assert.strictEqual(copyButton.disabled, true);
                assert.strictEqual(openButton.disabled, true);
                assert.strictEqual(copyButton.title, "Backupordner wird geladen...");
                assert.strictEqual(openButton.title, "Backupordner wird geladen...");
                // Even direct/programmatic dispatch cannot reuse A's path.
                copyButton.listeners.click();
                assert.deepStrictEqual(copied, ["A:/Backups"]);

                responseB.resolve({ json: async () => ({ success: false, error: "B fehlt" }) });
                await loadingB;
                assert.ok(container.innerHTML.includes("B fehlt"), container.innerHTML);
                assert.strictEqual(copyButton.disabled, true);
                assert.strictEqual(openButton.disabled, true);
                assert.strictEqual(copyButton.title, "Backupordner ist derzeit nicht verfügbar.");
                assert.strictEqual(openButton.title, "Backupordner ist derzeit nicht verfügbar.");
                copyButton.listeners.click();
                assert.deepStrictEqual(copied, ["A:/Backups"]);

                worldPath = "C";
                const loadedC = await controller.loadBackupsList();
                assert.strictEqual(loadedC, false);
                assert.ok(container.innerHTML.includes("Fehler beim Laden der Backups."), container.innerHTML);
                assert.strictEqual(copyButton.disabled, true);
                assert.strictEqual(openButton.disabled, true);
                assert.strictEqual(copyButton.title, "Backupordner ist derzeit nicht verfügbar.");
                assert.strictEqual(openButton.title, "Backupordner ist derzeit nicht verfügbar.");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_backups_view_ignores_stale_open_folder_response_after_world_switch() -> None:
    """A native folder-open response must remain bound to its requested world."""

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

            const openResponseA = deferred();
            let worldPath = "A";
            const context = {
                window: {
                    MCBEBackupRestoreLogic: {
                        openBackupFolderOutcome(data) {
                            return data.success
                                ? {
                                    ok: true,
                                    nextBackupDir: data.path || "",
                                    toast: { message: "Backupordner geöffnet.", type: "success", ms: 2500 },
                                }
                                : {
                                    ok: false,
                                    toast: { message: "Fehler", type: "error", ms: 5000 },
                                };
                        },
                    },
                },
                console,
                fetch: async (url, init) => {
                    const requestedWorld = JSON.parse(init.body).world_path;
                    if (url === "/api/open_backup_folder") {
                        assert.strictEqual(requestedWorld, "A");
                        return openResponseA.promise;
                    }
                    return {
                        json: async () => ({
                            success: true,
                            backup_dir: `${requestedWorld}:/Backups`,
                            backups: [],
                        }),
                    };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            (async () => {
                const copied = [];
                const toasts = [];
                const container = { innerHTML: "", querySelectorAll: () => [] };
                const copyButton = {
                    disabled: false,
                    title: "",
                    listeners: {},
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                };
                const openButton = {
                    disabled: false,
                    title: "",
                    addEventListener() {},
                };
                const controller = context.window.MCBEBackupsView.createBackupsController({
                    elements: { container, copyFolderButton: copyButton, openFolderButton: openButton },
                    getWorldPath: () => worldPath,
                    parseJsonResponse: response => response.json(),
                    copyTextToClipboard: value => copied.push(value),
                    showToast: (...args) => toasts.push(args),
                });
                controller.wire();

                await controller.loadBackupsList();
                const openingA = controller.openBackupFolder();

                worldPath = "B";
                await controller.loadBackupsList();
                copyButton.listeners.click();
                assert.deepStrictEqual(copied, ["B:/Backups"]);

                openResponseA.resolve({ json: async () => ({ success: true, path: "A:/Backups" }) });
                assert.strictEqual(await openingA, false);
                copyButton.listeners.click();

                assert.deepStrictEqual(copied, ["B:/Backups", "B:/Backups"]);
                assert.deepStrictEqual(toasts, []);
                assert.strictEqual(copyButton.disabled, false);
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


def test_frontend_backups_view_localizes_kind_badges_from_the_stable_kind() -> None:
    """The badge text must follow the page language, not the server's source string.

    ``kind_label`` arrives in German because the API can be negotiated
    separately from the active page, so the badge is translated at the display
    boundary via the stable ``kind`` key.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const translations = {
                "Automatisch": "Automatic",
                "Manuell": "Manual",
                "Vor Wiederherstellung": "Pre-restore",
                "Legacy": "Legacy",
            };
            const context = { window: { t: text => translations[text] || text } };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const html = context.window.MCBEBackupsView.backupsListHtml({
                success: true,
                backup_dir: "C:/Backups",
                backups: [
                    { filename: "a.zip", kind: "automatic", kind_label: "Automatisch", date: "", size_mb: 1 },
                    { filename: "m.zip", kind: "manual", kind_label: "Manuell", date: "", size_mb: 1 },
                    { filename: "p.zip", kind: "pre_restore", kind_label: "Vor Wiederherstellung", date: "", size_mb: 1 },
                    { filename: "l.zip", kind: "legacy", kind_label: "Legacy", date: "", size_mb: 1 },
                    { filename: "f.zip", kind: "future_kind", kind_label: "Neue Art", date: "", size_mb: 1 },
                ],
            });
            assert.ok(html.includes(">Automatic<"));
            assert.ok(html.includes(">Manual<"));
            assert.ok(html.includes(">Pre-restore<"));
            assert.ok(html.includes(">Legacy<"));
            assert.ok(!html.includes(">Automatisch<"));
            assert.ok(!html.includes(">Vor Wiederherstellung<"));
            // An unknown future kind keeps the server label instead of being
            // mislabelled as a legacy backup.
            assert.ok(html.includes(">Neue Art<"));
            """
        )
    )


def test_frontend_backups_view_explains_each_kind_with_an_accessible_disclosure() -> None:
    """The badge names the kind and a native disclosure explains retention.

    Only manual backups survive every rotation, and pre-restore archives hold
    their own quota so a run of ordinary saves cannot push them out. That
    difference decides which archive is still there later. A ``details`` /
    ``summary`` control keeps it available to keyboard and touch users instead
    of hiding it in a pointer-only title attribute.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const translations = {
                "Automatisch vor jedem Speichervorgang erstellt. Der älteste Eintrag entfällt, sobald das Limit erreicht ist.":
                    "Created automatically before every save.",
                "Von Hand erstellt. Bleibt erhalten, bis du es löschst.": "Created by hand. Kept until you delete it.",
                "Zustand der Welt unmittelbar vor einer Wiederherstellung. Eigenes Kontingent, unabhängig von den Speicher-Backups.":
                    "Own quota, separate from the save backups.",
                "Älteres Archiv ohne Metadaten. Wird wie ein automatisches Backup rotiert.": "Older archive without metadata.",
            };
            const context = { window: { t: text => translations[text] || text } };
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const html = context.window.MCBEBackupsView.backupsListHtml({
                success: true,
                backup_dir: "C:/Backups",
                backups: [
                    { filename: "a.zip", kind: "automatic", date: "", size_mb: 1 },
                    { filename: "m.zip", kind: "manual", date: "", size_mb: 1 },
                    { filename: "p.zip", kind: "pre_restore", date: "", size_mb: 1 },
                    { filename: "l.zip", kind: "legacy", date: "", size_mb: 1 },
                    { filename: "f.zip", kind: "future_kind", kind_label: "Neue Art", date: "", size_mb: 1 },
                ],
            });

            const chips = [...html.matchAll(/<span class="backup-kind backup-kind-([a-z_]+)">/g)]
                .map(match => match[1]);
            assert.deepStrictEqual(
                chips,
                ["automatic", "manual", "pre_restore", "legacy", "future_kind"],
            );
            assert.strictEqual((html.match(/<details class="backup-kind-details">/g) || []).length, 4);
            assert.strictEqual((html.match(/<summary class="backup-title-line" role="button" aria-expanded="false">/g) || []).length, 4);
            assert.ok(html.includes('<div class="backup-kind-explanation">Created automatically before every save.</div>'));
            assert.ok(html.includes('<div class="backup-kind-explanation">Created by hand. Kept until you delete it.</div>'));
            assert.ok(html.includes('<div class="backup-kind-explanation">Own quota, separate from the save backups.</div>'));
            assert.ok(html.includes('<div class="backup-kind-explanation">Older archive without metadata.</div>'));
            assert.ok(!html.includes('title="Created automatically before every save."'));
            // An unknown future kind gets no invented retention promise and is
            // therefore the only row without a disclosure.
            assert.strictEqual((html.match(/backup-kind-explanation/g) || []).length, 4);

            // A missing kind is styled and labelled as legacy everywhere else,
            // so it must carry the legacy explanation rather than none at all.
            const withoutKind = context.window.MCBEBackupsView.backupsListHtml({
                success: true,
                backups: [{ filename: "n.zip", date: "", size_mb: 1 }, { filename: "e.zip", kind: "", date: "", size_mb: 1 }],
            });
            const untyped = [...withoutKind.matchAll(/<span class="backup-kind backup-kind-([a-z_]+)">/g)]
                .map(match => match[1]);
            assert.deepStrictEqual(untyped, ["legacy", "legacy"]);
            assert.strictEqual((withoutKind.match(/<details class="backup-kind-details">/g) || []).length, 2);
            assert.strictEqual((withoutKind.match(/Older archive without metadata\./g) || []).length, 2);

            const listeners = {};
            const attributes = {};
            const summary = {
                dataset: {},
                addEventListener(type, listener) { listeners[type] = listener; },
                setAttribute(name, value) { attributes[name] = value; },
            };
            const detailsListeners = {};
            const details = {
                open: false,
                querySelector: () => summary,
                addEventListener(type, listener) { detailsListeners[type] = listener; },
            };
            context.window.MCBEBackupsView.wireBackupKindDisclosures({ querySelectorAll: () => [details] });
            assert.strictEqual(attributes["aria-expanded"], "false");
            let prevented = false;
            listeners.keydown({ key: "Enter", preventDefault() { prevented = true; } });
            assert.strictEqual(prevented, true);
            assert.strictEqual(details.open, true);
            assert.strictEqual(attributes["aria-expanded"], "true");
            listeners.keydown({ key: " ", preventDefault() {} });
            assert.strictEqual(details.open, false);
            assert.strictEqual(attributes["aria-expanded"], "false");
            details.open = true;
            detailsListeners.toggle();
            assert.strictEqual(attributes["aria-expanded"], "true");
            """
        )
    )


def test_frontend_backups_view_renders_localized_timestamps_with_utc_tooltip() -> None:
    """The list date follows the page language for modern and legacy archives.

    ``created_at`` is null for archives without metadata, but ``modified_at`` is
    an ISO-UTC filesystem timestamp. The German server string remains only as a
    compatibility fallback for older API responses.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const translations = {
                "UTC-Zeitstempel: {value}": "UTC timestamp: {value}",
                "UTC-Änderungszeit: {value}": "UTC modification time: {value}",
            };
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            context.window.MCBEI18n = {
                formatDate: (date, options) =>
                    new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(date),
            };
            context.window.t = (text, params) =>
                String(translations[text] || text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m));
            vm.runInNewContext(code, context, { filename: "static/backups_view.js" });

            const html = context.window.MCBEBackupsView.backupsListHtml({
                success: true,
                backup_dir: "C:/Backups",
                backups: [
                    {
                        filename: "300125__automatic__20260803T165629Z.zip",
                        kind: "automatic",
                        created_at: "2026-08-03T16:56:29Z",
                        date: "03.08.2026 18:56:29",
                        size_mb: 236.59,
                    },
                    {
                        filename: "300125__legacy.zip",
                        kind: "legacy",
                        modified_at: "2026-07-12T10:00:00Z",
                        date: "12.07.2026 12:00:00",
                        size_mb: 1.25,
                    },
                ],
            });

            assert.ok(html.includes("Aug 3, 2026"), html);
            assert.ok(!html.includes("03.08.2026 18:56:29"), html);
            assert.ok(html.includes('title="UTC timestamp: 2026-08-03T16:56:29Z"'), html);
            assert.ok(html.includes("Jul 12, 2026"), html);
            assert.ok(!html.includes("12.07.2026 12:00:00"), html);
            assert.ok(html.includes('title="UTC modification time: 2026-07-12T10:00:00Z"'), html);
            assert.strictEqual((html.match(/UTC timestamp/g) || []).length, 1);
            assert.strictEqual((html.match(/UTC modification time/g) || []).length, 1);
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
