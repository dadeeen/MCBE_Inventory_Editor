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


def test_frontend_backups_view_explains_each_kind_with_a_retention_tooltip() -> None:
    """The badge names the kind, the tooltip says what it means for retention.

    Only manual backups survive every rotation, and pre-restore archives hold
    their own quota so a run of ordinary saves cannot push them out. That
    difference decides which archive is still there later, so it belongs on the
    badge rather than in the documentation alone.
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

            const chips = [...html.matchAll(/<span class="backup-kind backup-kind-([a-z_]+)"(?: title="([^"]*)")?>/g)]
                .map(match => ({ kind: match[1], title: match[2] }));
            assert.deepStrictEqual(
                chips.map(chip => chip.kind),
                ["automatic", "manual", "pre_restore", "legacy", "future_kind"],
            );
            assert.strictEqual(chips[0].title, "Created automatically before every save.");
            assert.strictEqual(chips[1].title, "Created by hand. Kept until you delete it.");
            assert.strictEqual(chips[2].title, "Own quota, separate from the save backups.");
            assert.strictEqual(chips[3].title, "Older archive without metadata.");
            // An unknown future kind gets no invented retention promise.
            assert.strictEqual(chips[4].title, undefined);

            // A missing kind is styled and labelled as legacy everywhere else,
            // so it must carry the legacy explanation rather than none at all.
            const withoutKind = context.window.MCBEBackupsView.backupsListHtml({
                success: true,
                backups: [{ filename: "n.zip", date: "", size_mb: 1 }, { filename: "e.zip", kind: "", date: "", size_mb: 1 }],
            });
            const untyped = [...withoutKind.matchAll(/<span class="backup-kind backup-kind-([a-z_]+)"(?: title="([^"]*)")?>/g)]
                .map(match => ({ kind: match[1], title: match[2] }));
            assert.deepStrictEqual(untyped.map(chip => chip.kind), ["legacy", "legacy"]);
            assert.ok(untyped.every(chip => chip.title === "Older archive without metadata."), withoutKind);
            """
        )
    )


def test_frontend_backups_view_renders_localized_timestamps_with_utc_tooltip() -> None:
    """The list date follows the page language; legacy archives keep theirs.

    ``created_at`` is null for archives without metadata, and only then does the
    server fall back to an mtime-derived string -- so dropping that fallback
    would blank the date on exactly the oldest backups.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const code = fs.readFileSync("static/backups_view.js", "utf8");
            const translations = { "UTC-Zeitstempel: {value}": "UTC timestamp: {value}" };
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
                    { filename: "300125__legacy.zip", kind: "legacy", date: "12.07.2026 12:00:00", size_mb: 1.25 },
                ],
            });

            assert.ok(html.includes("Aug 3, 2026"), html);
            assert.ok(!html.includes("03.08.2026 18:56:29"), html);
            assert.ok(html.includes('title="UTC timestamp: 2026-08-03T16:56:29Z"'), html);
            assert.ok(html.includes("12.07.2026 12:00:00"), html);
            // The archive without an ISO value gets no tooltip it cannot fill.
            assert.strictEqual((html.match(/UTC timestamp/g) || []).length, 1);
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
