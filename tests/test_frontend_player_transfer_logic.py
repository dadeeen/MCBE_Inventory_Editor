import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_player_transfer_logic_export_and_picker_plans() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_transfer_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_transfer_logic.js" });
            const logic = context.window.MCBEPlayerTransferLogic;
            const plain = value => JSON.parse(JSON.stringify(value));
            const eq = (actual, expected) => assert.deepStrictEqual(plain(actual), expected);

            eq(logic.exportPlayerPlan({ worldPath: "", currentPlayerKey: "p1" }), { ok: false, reason: "missing_player" });
            eq(logic.exportPlayerPlan({ worldPath: "C:/World", currentPlayerKey: "p1", writeBlocked: true }), {
                ok: false,
                reason: "write_blocked",
                statusMessage: "Export ist im Read-Only-Modus deaktiviert.",
                statusType: "warning",
            });
            const plan = logic.exportPlayerPlan({ worldPath: "C:/World", currentPlayerKey: "p1", isDirty: true });
            assert.strictEqual(plan.ok, true);
            assert.strictEqual(plan.statusType, "running");
            assert.strictEqual(plan.needsDirtyConfirmation, true);
            assert.ok(plan.dirtyConfirmationText.includes("ungespeicherte Änderungen"));
            eq(plan.requestBody, { world_path: "C:/World", player_key: "p1" });

            const exported = logic.exportPlayerOutcome({ success: true, export_path: "C:/exports/alex.mcbe-player.zip" });
            assert.strictEqual(exported.ok, true);
            assert.strictEqual(exported.statusMessage, "Spieler exportiert: C:/exports/alex.mcbe-player.zip");
            assert.strictEqual(exported.actionType, "export");
            eq(logic.exportPlayerOutcome({ success: false, error: "kaputt" }).toast, {
                message: "Export fehlgeschlagen: kaputt",
                type: "error",
                ms: 5000,
            });

            eq(logic.openExportFolderOutcome({ success: true, path: "C:/exports" }, ""), {
                ok: true,
                nextExportDir: "C:/exports",
                statusMessage: "Exportordner geöffnet: C:/exports",
                statusType: "success",
            });
            assert.strictEqual(logic.openExportFolderOutcome({ success: false, error: "kein Zugriff" }).statusMessage, "kein Zugriff");
            assert.strictEqual(
                logic.openExportFolderOutcome({ success: false, error: "kein Zugriff", details: "gesperrt" }).statusMessage,
                "kein Zugriff — gesperrt",
            );
            eq(logic.browseExportSelectionOutcome({ success: true, path: "C:/exports/alex.mcbe-player.zip" }), {
                ok: true,
                path: "C:/exports/alex.mcbe-player.zip",
            });
            eq(logic.browseExportSelectionOutcome({ success: false, error: "abgebrochen" }), {
                ok: false,
                statusMessage: "Fehler: abgebrochen",
                statusType: "error",
            });
            eq(logic.browseExportSelectionOutcome({ success: false }), { ok: false, reason: "cancelled" });
            """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_player_transfer_logic_import_plans_and_outcomes() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_transfer_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_transfer_logic.js" });
            const logic = context.window.MCBEPlayerTransferLogic;
            const plain = value => JSON.parse(JSON.stringify(value));
            const eq = (actual, expected) => assert.deepStrictEqual(plain(actual), expected);

            eq(logic.importPlayerPlan({ worldPath: "C:/World", exportPath: "", importAsExported: true }), {
                ok: false,
                reason: "missing_export_path",
                statusMessage: "Bitte zuerst eine Import-Datei (.mcbe-player.zip) auswählen.",
                statusType: "error",
            });
            eq(logic.importPlayerPlan({
                worldPath: "C:/World",
                exportPath: "C:/exports/alex.zip",
                importAsExported: false,
                currentPlayerKey: "p1",
                currentPlayerEditable: false,
            }), {
                ok: false,
                reason: "target_not_editable",
                statusMessage: "Bitte einen bearbeitbaren Zielspieler wählen oder Import als exportierter Spieler aktivieren.",
                statusType: "error",
            });
            eq(logic.importPlayerPlan({
                worldPath: "C:/World",
                exportPath: "C:/exports/alex.zip",
                importAsExported: true,
                currentImportPreview: null,
            }), {
                ok: false,
                reason: "preview_required",
                statusMessage: "Bitte zuerst eine passende erfolgreiche Import-Vorschau abwarten.",
                statusType: "error",
            });
            eq(logic.importPlayerPlan({
                worldPath: "C:/World",
                exportPath: "C:/exports/alex.zip",
                importAsExported: true,
                isDirty: true,
            }), {
                ok: false,
                reason: "open_changes",
                statusMessage: "Speichere oder verwirf zuerst die offenen Editor-Änderungen.",
                statusType: "warning",
            });
            eq(logic.importPlayerPlan({
                worldPath: "C:/WorldB",
                exportPath: "C:/exports/alex.zip",
                importAsExported: true,
                currentImportPreview: {
                    export_path: "C:/exports/alex.zip",
                    world_path: "C:/WorldA",
                    importable: true,
                    import_token: { version: 1 },
                },
            }), {
                ok: false,
                reason: "preview_required",
                statusMessage: "Bitte zuerst eine passende erfolgreiche Import-Vorschau abwarten.",
                statusType: "error",
            });
            eq(logic.importPlayerPlan({
                worldPath: "C:/World",
                exportPath: "C:/exports/alex.zip",
                importAsExported: true,
                currentImportPreview: {
                    export_path: "C:/exports/alex.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                    player: { label: "Steve" },
                },
            }), {
                ok: false,
                reason: "missing_exported_player_key",
                statusMessage: "Import als exportierter Spieler nicht möglich: Die Import-Vorschau enthält keinen Spieler-Key.",
                statusType: "error",
            });
            eq(logic.importPlayerPlan({
                worldPath: "C:/World",
                exportPath: "C:/exports/alex.zip",
                importAsExported: false,
                currentPlayerKey: "p1",
                currentPlayerEditable: true,
                currentImportPreview: {
                    export_path: "C:/exports/alex.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                },
            }), {
                ok: false,
                reason: "missing_target_revision",
                statusMessage: "Der geladene Zielspielerstand fehlt. Lade den Zielspieler neu und prüfe den Import erneut.",
                statusType: "warning",
            });

            const plan = logic.importPlayerPlan({
                worldPath: "C:/World",
                exportPath: " C:/exports/alex.zip ",
                importAsExported: false,
                currentPlayerKey: "p1",
                currentPlayerEditable: true,
                currentPlayerLabel: "Alex",
                currentPlayerRevision: "a".repeat(64),
                currentImportPreview: {
                    export_path: "C:/exports/alex.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                    player: { label: "Steve" },
                    source_world_name: "Survival",
                },
                worldPresenceSessionId: "s1",
            });
            assert.strictEqual(plan.ok, true);
            assert.strictEqual(plan.statusType, "running");
            assert.strictEqual(plan.exportPath, "C:/exports/alex.zip");
            assert.strictEqual(plan.worldPath, "C:/World");
            assert.strictEqual(plan.targetPlayerKey, "p1");
            assert.strictEqual(plan.baseRevision, "a".repeat(64));
            assert.strictEqual(plan.sessionId, "s1");
            assert.ok(plan.confirmationText.startsWith("Export: Steve aus Survival\n"));
            assert.ok(plan.confirmationText.includes("Der Import überschreibt Alex direkt in der gewählten Welt."));
            assert.ok(plan.confirmationText.includes("geprüftes Vollbackup"));

            const exportedPlan = logic.importPlayerPlan({
                worldPath: "C:/World",
                exportPath: "C:/exports/alex.zip",
                importAsExported: true,
                currentImportPreview: {
                    export_path: "C:/exports/alex.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                    player: { label: "Steve", player_key: "exported-player" },
                },
            });
            assert.strictEqual(exportedPlan.ok, true);
            assert.strictEqual(exportedPlan.targetPlayerKey, "exported-player");

            eq(logic.importRequestBody({
                exportPath: " C:/exports/alex.zip ",
                worldPath: "C:/World",
                targetPlayerKey: "p1",
                sessionId: "s1",
                importAsExported: false,
                importToken: { version: 1 },
                baseRevision: "a".repeat(64),
            }), {
                export_zip: "C:/exports/alex.zip",
                world_path: "C:/World",
                target_player_key: "p1",
                session_id: "s1",
                confirm_overwrite: true,
                import_as_exported_player: false,
                import_token: { version: 1 },
                base_revision: "a".repeat(64),
            });
            eq(logic.importRequestBody({
                exportPath: "C:/exports/alex.zip",
                worldPath: "C:/World",
                targetPlayerKey: "exported-player",
                sessionId: "s1",
                importAsExported: true,
                importToken: { version: 1 },
                confirmPresenceConflict: true,
            }), {
                export_zip: "C:/exports/alex.zip",
                world_path: "C:/World",
                target_player_key: "exported-player",
                session_id: "s1",
                confirm_overwrite: true,
                import_as_exported_player: true,
                import_token: { version: 1 },
                confirm_presence_conflict: true,
            });

            const imported = logic.importOutcome({
                success: true,
                created_new_player: true,
                backup_file: "world_before_import.zip",
                write_gate: { server_status: { running: false }, allowed: true },
            });
            assert.strictEqual(imported.ok, true);
            eq(imported.writeGate, { server_status: { running: false }, allowed: true });
            assert.ok(imported.toast.message.includes("Neuer Spieler-Key wurde angelegt."));
            assert.ok(imported.toast.message.includes("world_before_import.zip"));
            assert.strictEqual(imported.actionType, "import");
            assert.ok(imported.actionMessage.includes("nachvalidiert"));
            const directImport = logic.importOutcome({
                success: true,
                backup_file: "world_before_import.zip",
            });
            assert.strictEqual(directImport.ok, true);
            assert.ok(directImport.statusMessage.includes("gewählte Welt wurde aktualisiert"));
            assert.ok(directImport.statusMessage.includes("world_before_import.zip"));
            eq(logic.importOutcome({ success: false, error: "ungültiges ZIP", write_gate: { allowed: false } }).toast, {
                message: "Import fehlgeschlagen: ungültiges ZIP",
                type: "error",
                ms: 5000,
            });
            const rollbackFailure = logic.importOutcome({
                success: false,
                error: "write failed",
                backup_file: "world_before_import.zip",
                rollback_warning: "Import-Rollback unvollständig: rollback locked",
                cleanup_warning: "Import-Snapshot blieb zurück",
            });
            assert.strictEqual(rollbackFailure.ok, false);
            assert.ok(rollbackFailure.statusMessage.includes("rollback locked"));
            assert.ok(rollbackFailure.statusMessage.includes("world_before_import.zip"));
            assert.ok(rollbackFailure.statusMessage.includes("Import-Snapshot blieb zurück"));
            assert.strictEqual(rollbackFailure.toast.ms, 9000);
            eq(logic.presenceConflictRetryPlan(), {
                abortedStatusMessage: "Import wegen Bearbeitungskonflikt abgebrochen.",
                abortedStatusType: "warning",
                retryLoadingText: "Importiere trotz bestätigtem Bearbeitungskonflikt...",
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


def test_frontend_player_import_request_freezes_confirmed_plan_target() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_transfer_logic.js", "utf8");
            const context = { window: {}, console, fetch: null };
            vm.runInNewContext(code, context, { filename: "static/player_transfer_logic.js" });
            const logic = context.window.MCBEPlayerTransferLogic;

            (async () => {
                let worldPath = "C:/WorldA";
                let playerKey = "playerA";
                let playerRevision = "a".repeat(64);
                let sessionId = "session-A";
                const requests = [];
                context.fetch = async (_url, options) => {
                    requests.push(JSON.parse(options.body));
                    return { json: async () => ({ success: false, error: "stop" }) };
                };

                const controller = logic.createPlayerTransferController({
                    elements: {
                        importPathInput: { value: "C:/exports/alex.mcbe-player.zip" },
                        importAsExportedCheckbox: { checked: false },
                    },
                    withCsrf: () => ({}),
                    parseJsonResponse: response => response.json(),
                    getWorldPath: () => worldPath,
                    getCurrentPlayerKey: () => playerKey,
                    getCurrentPlayer: () => ({ editable: true }),
                    getCurrentPlayerRevision: () => playerRevision,
                    getCurrentPlayerLabel: () => "Alex",
                    getCurrentImportPreview: () => ({
                        export_path: "C:/exports/alex.mcbe-player.zip",
                        world_path: "C:/WorldA",
                        importable: true,
                    import_token: { version: 1 },
                        player: { label: "Steve" },
                    }),
                    getWorldPresenceSessionId: () => sessionId,
                    showConfirmDialog: async () => {
                        worldPath = "C:/WorldB";
                        playerKey = "playerB";
                        playerRevision = "b".repeat(64);
                        sessionId = "session-B";
                        return true;
                    },
                });

                await controller.importPlayer();
                assert.strictEqual(requests.length, 1);
                assert.deepStrictEqual(requests[0], {
                    export_zip: "C:/exports/alex.mcbe-player.zip",
                    world_path: "C:/WorldA",
                    target_player_key: "playerA",
                    session_id: "session-A",
                    confirm_overwrite: true,
                    import_as_exported_player: false,
                import_token: { version: 1 },
                    base_revision: "a".repeat(64),
                });
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


def test_frontend_successful_import_refreshes_selected_player() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const code = fs.readFileSync("static/player_transfer_logic.js", "utf8");
                const context = { window: {}, console, fetch: null };
                vm.runInNewContext(code, context, { filename: "static/player_transfer_logic.js" });
                const logic = context.window.MCBEPlayerTransferLogic;

                function controllerFor({ response, refreshed, refreshError = null, statuses = [] }) {
                    context.fetch = async () => ({ json: async () => response });
                    return logic.createPlayerTransferController({
                        elements: {
                            importPathInput: { value: "C:/exports/alex.mcbe-player.zip" },
                            importAsExportedCheckbox: { checked: false },
                        },
                        withCsrf: () => ({}),
                        parseJsonResponse: result => result.json(),
                        getWorldPath: () => "C:/World",
                        getCurrentPlayerKey: () => "playerA",
                        getCurrentPlayer: () => ({ editable: true }),
                        getCurrentPlayerRevision: () => "a".repeat(64),
                        getCurrentPlayerLabel: () => "Alex",
                        getCurrentImportPreview: () => ({
                            export_path: "C:/exports/alex.mcbe-player.zip",
                            world_path: "C:/World",
                            importable: true,
                            import_token: { version: 1 },
                            player: { label: "Steve" },
                        }),
                        showConfirmDialog: async () => true,
                        refreshImportedPlayer: async key => {
                            refreshed.push(key);
                            if (refreshError) throw refreshError;
                        },
                        logStatus: (message, type, options) => statuses.push({ message, type, options }),
                    });
                }

                (async () => {
                    const directRefreshes = [];
                    await controllerFor({
                        response: { success: true },
                        refreshed: directRefreshes,
                    }).importPlayer();
                    assert.deepStrictEqual(directRefreshes, ["playerA"]);

                    const failedRefreshes = [];
                    const statuses = [];
                    await controllerFor({
                        response: { success: true, backup_file: "world_backup.zip" },
                        refreshed: failedRefreshes,
                        refreshError: new Error("reload failed"),
                        statuses,
                    }).importPlayer();
                    assert.deepStrictEqual(failedRefreshes, ["playerA"]);
                    assert.strictEqual(statuses[0].type, "running");
                    assert.ok(statuses.every(entry => entry.options.key === "player-import"));
                    assert.ok(statuses.some(entry => entry.type === "warning" && entry.message.includes("Import wurde gespeichert")));
                    assert.ok(!statuses.some(entry => entry.message.includes("Verbindungsfehler beim Import")));

                    const uncertainRefreshes = [];
                    const uncertainStatuses = [];
                    await controllerFor({
                        response: {
                            success: false,
                            write_committed: true,
                            error: "Import-Rollback unvollständig",
                            backup_file: "world_backup.zip",
                        },
                        refreshed: uncertainRefreshes,
                        refreshError: new Error("reload failed"),
                        statuses: uncertainStatuses,
                    }).importPlayer();
                    assert.deepStrictEqual(uncertainRefreshes, ["playerA"]);
                    assert.ok(uncertainStatuses.some(entry => (
                        entry.type === "warning"
                        && entry.message.includes("Zielzustand")
                        && entry.message.includes("reload failed")
                    )));
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


def test_frontend_stale_import_token_triggers_fresh_preview() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const code = fs.readFileSync("static/player_transfer_logic.js", "utf8");
                const context = { window: {}, console, fetch: null };
                vm.runInNewContext(code, context, { filename: "static/player_transfer_logic.js" });
                const logic = context.window.MCBEPlayerTransferLogic;

                (async () => {
                    let refreshes = 0;
                    context.fetch = async () => ({
                        json: async () => ({
                            success: false,
                            preview_stale: true,
                            error: "Exportdatei wurde verändert. Bitte Vorschau neu laden.",
                        }),
                    });
                    const controller = logic.createPlayerTransferController({
                        elements: {
                            importPathInput: { value: "C:/exports/alex.mcbe-player.zip" },
                            importAsExportedCheckbox: { checked: false },
                        },
                        withCsrf: () => ({}),
                        parseJsonResponse: response => response.json(),
                        getWorldPath: () => "C:/World",
                        getCurrentPlayerKey: () => "playerA",
                        getCurrentPlayer: () => ({ editable: true }),
                        getCurrentPlayerRevision: () => "a".repeat(64),
                        getCurrentPlayerLabel: () => "Alex",
                        getCurrentImportPreview: () => ({
                            export_path: "C:/exports/alex.mcbe-player.zip",
                            world_path: "C:/World",
                            importable: true,
                            import_token: { version: 1 },
                            player: { label: "Steve" },
                        }),
                        showConfirmDialog: async () => true,
                        refreshPlayerImportPreview: async () => { refreshes += 1; },
                    });

                    await controller.importPlayer();
                    assert.strictEqual(refreshes, 1);
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


def test_frontend_stale_import_target_refreshes_player_without_refreshing_export_preview() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const code = fs.readFileSync("static/player_transfer_logic.js", "utf8");
                const context = { window: {}, console, fetch: null };
                vm.runInNewContext(code, context, { filename: "static/player_transfer_logic.js" });
                const logic = context.window.MCBEPlayerTransferLogic;

                (async () => {
                    const playerRefreshes = [];
                    let previewRefreshes = 0;
                    context.fetch = async () => ({
                        json: async () => ({
                            success: false,
                            preview_stale: false,
                            target_revision_stale: true,
                            error: "Zielspieler wurde geändert.",
                        }),
                    });
                    const controller = logic.createPlayerTransferController({
                        elements: {
                            importPathInput: { value: "C:/exports/alex.mcbe-player.zip" },
                            importAsExportedCheckbox: { checked: false },
                        },
                        withCsrf: () => ({}),
                        parseJsonResponse: response => response.json(),
                        getWorldPath: () => "C:/World",
                        getCurrentPlayerKey: () => "playerA",
                        getCurrentPlayer: () => ({ editable: true }),
                        getCurrentPlayerRevision: () => "a".repeat(64),
                        getCurrentPlayerLabel: () => "Alex",
                        getCurrentImportPreview: () => ({
                            export_path: "C:/exports/alex.mcbe-player.zip",
                            world_path: "C:/World",
                            importable: true,
                            import_token: { version: 1 },
                            player: { label: "Steve" },
                        }),
                        showConfirmDialog: async () => true,
                        refreshImportedPlayer: async key => { playerRefreshes.push(key); },
                        refreshPlayerImportPreview: async () => { previewRefreshes += 1; },
                    });

                    await controller.importPlayer();
                    assert.deepStrictEqual(playerRefreshes, ["playerA"]);
                    assert.strictEqual(previewRefreshes, 0);
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


def test_frontend_player_import_preview_ignores_stale_world_response() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const importViewCode = fs.readFileSync("static/player_import_view.js", "utf8");
            const transferCode = fs.readFileSync("static/player_transfer_logic.js", "utf8");
            const context = { window: {}, console, fetch: null, setTimeout, clearTimeout };
            vm.runInNewContext(importViewCode, context, { filename: "static/player_import_view.js" });
            vm.runInNewContext(transferCode, context, { filename: "static/player_transfer_logic.js" });
            const logic = context.window.MCBEPlayerTransferLogic;

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            (async () => {
                let worldPath = "C:/WorldA";
                let currentPreview = null;
                const previewUpdates = [];
                const requests = [];
                const responses = [];
                const elements = {
                    importPathInput: { value: "C:/exports/player.mcbe-player.zip" },
                    importAsExportedCheckbox: { checked: true },
                    importButton: { disabled: true },
                    targetHint: { textContent: "" },
                    preview: { style: {}, className: "", innerHTML: "" },
                    openExportFolderButton: { disabled: true, title: "" },
                };

                context.fetch = (_url, options) => {
                    const next = deferred();
                    requests.push(JSON.parse(options.body));
                    responses.push(next);
                    return next.promise;
                };

                const controller = logic.createPlayerImportPreviewController({
                    elements,
                    withCsrf: () => ({}),
                    parseJsonResponse: response => response.json(),
                    getWorldPath: () => worldPath,
                    getCurrentPlayer: () => ({ editable: true }),
                    getCurrentPlayerLabel: () => "Alex",
                    getCurrentImportPreview: () => currentPreview,
                    setCurrentImportPreview: value => {
                        currentPreview = value;
                        previewUpdates.push(value);
                    },
                    writeBlocked: () => false,
                    appConfig: { mode: "docker" },
                });

                const first = controller.refreshPlayerImportPreview();
                assert.deepStrictEqual(requests[0], {
                    export_zip: "C:/exports/player.mcbe-player.zip",
                    world_path: "C:/WorldA",
                });
                worldPath = "C:/WorldB";
                responses[0].resolve({ json: async () => ({ success: true, importable: true, import_token: { version: 1 }, player: { label: "Steve" } }) });
                await first;
                assert.strictEqual(currentPreview, null);
                assert.deepStrictEqual(previewUpdates, [null]);
                assert.strictEqual(elements.importButton.disabled, true);

                const second = controller.refreshPlayerImportPreview();
                responses[1].resolve({ json: async () => ({
                    success: true,
                    importable: true,
                    import_token: { version: 1 },
                    player: { label: "Steve", player_key: "exported-player" },
                }) });
                await second;
                assert.strictEqual(currentPreview.export_path, "C:/exports/player.mcbe-player.zip");
                assert.strictEqual(currentPreview.world_path, "C:/WorldB");
                assert.strictEqual(currentPreview.importable, true);
                assert.strictEqual(currentPreview.player.player_key, "exported-player");
                assert.strictEqual(elements.importButton.disabled, false);
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


def test_frontend_player_import_preview_ignores_older_response_for_same_context() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const importViewCode = fs.readFileSync("static/player_import_view.js", "utf8");
            const transferCode = fs.readFileSync("static/player_transfer_logic.js", "utf8");
            const context = { window: {}, console, fetch: null, setTimeout, clearTimeout };
            vm.runInNewContext(importViewCode, context, { filename: "static/player_import_view.js" });
            vm.runInNewContext(transferCode, context, { filename: "static/player_transfer_logic.js" });
            const logic = context.window.MCBEPlayerTransferLogic;

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            (async () => {
                let currentPreview = null;
                const responses = [];
                const elements = {
                    importPathInput: { value: "C:/exports/player.mcbe-player.zip" },
                    importAsExportedCheckbox: { checked: true },
                    importButton: { disabled: true },
                    targetHint: { textContent: "" },
                    preview: { style: {}, className: "", innerHTML: "" },
                    openExportFolderButton: { disabled: true, title: "" },
                };
                context.fetch = () => {
                    const next = deferred();
                    responses.push(next);
                    return next.promise;
                };

                const controller = logic.createPlayerImportPreviewController({
                    elements,
                    withCsrf: () => ({}),
                    parseJsonResponse: response => response.json(),
                    getWorldPath: () => "C:/World",
                    getCurrentPlayer: () => ({ editable: true }),
                    getCurrentImportPreview: () => currentPreview,
                    setCurrentImportPreview: value => { currentPreview = value; },
                    appConfig: { mode: "docker" },
                });

                const first = controller.refreshPlayerImportPreview();
                const second = controller.refreshPlayerImportPreview();
                responses[1].resolve({ json: async () => ({
                    success: true,
                    importable: true,
                    import_token: { version: 1 },
                    player: { label: "Neuer Stand", player_key: "new" },
                }) });
                await second;
                assert.strictEqual(currentPreview.player.player_key, "new");

                responses[0].resolve({ json: async () => ({
                    success: true,
                    importable: true,
                    import_token: { version: 1 },
                    player: { label: "Alter Stand", player_key: "old" },
                }) });
                await first;
                assert.strictEqual(currentPreview.player.player_key, "new");
                assert.strictEqual(elements.importButton.disabled, false);
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


def test_frontend_player_import_preview_surfaces_cleanup_warning_on_failure() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const importViewCode = fs.readFileSync("static/player_import_view.js", "utf8");
            const transferCode = fs.readFileSync("static/player_transfer_logic.js", "utf8");
            const context = { window: {}, console, fetch: null, setTimeout, clearTimeout };
            vm.runInNewContext(importViewCode, context, { filename: "static/player_import_view.js" });
            vm.runInNewContext(transferCode, context, { filename: "static/player_transfer_logic.js" });
            const logic = context.window.MCBEPlayerTransferLogic;

            (async () => {
                let currentPreview = null;
                const elements = {
                    importPathInput: { value: "C:/exports/player.mcbe-player.zip" },
                    importAsExportedCheckbox: { checked: true },
                    importButton: { disabled: false },
                    targetHint: { textContent: "" },
                    preview: { style: {}, className: "", innerHTML: "" },
                    openExportFolderButton: { disabled: true, title: "" },
                };
                context.fetch = async () => ({ json: async () => ({
                    success: false,
                    error: "Exportdatei ist beschädigt.",
                    cleanup_warning: "Privater Import-Snapshot blieb zurück: C:/snap.zip",
                    source_snapshot_path: "C:/snap.zip",
                }) });

                const controller = logic.createPlayerImportPreviewController({
                    elements,
                    withCsrf: () => ({}),
                    parseJsonResponse: response => response.json(),
                    getWorldPath: () => "C:/World",
                    getCurrentPlayer: () => ({ editable: true }),
                    getCurrentImportPreview: () => currentPreview,
                    setCurrentImportPreview: value => { currentPreview = value; },
                    appConfig: { mode: "docker" },
                });

                await controller.refreshPlayerImportPreview();
                assert.strictEqual(currentPreview.importable, false);
                assert.strictEqual(currentPreview.cleanup_warning, "Privater Import-Snapshot blieb zurück: C:/snap.zip");
                assert.ok(elements.preview.innerHTML.includes("Exportdatei ist beschädigt."));
                assert.ok(elements.preview.innerHTML.includes("Privater Import-Snapshot blieb zurück"));
                assert.strictEqual(elements.importButton.disabled, true);
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
