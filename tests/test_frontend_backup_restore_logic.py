import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_backup_restore_logic_plans_and_outcomes() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backup_restore_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/backup_restore_logic.js" });
            const logic = context.window.MCBEBackupRestoreLogic;
            const plain = value => JSON.parse(JSON.stringify(value));
            const eq = (actual, expected) => assert.deepStrictEqual(plain(actual), expected);

            eq(logic.openBackupFolderOutcome({ success: true, path: "C:/World/backups" }), {
                ok: true,
                nextBackupDir: "C:/World/backups",
                toast: { message: "Backupordner geöffnet.", type: "success", ms: 2500 },
            });
            eq(logic.openBackupFolderOutcome({ success: false, error: "kein Zugriff" }).toast, {
                message: "kein Zugriff",
                type: "error",
                ms: 5000,
            });
            eq(logic.restorePreviewRequestBody({ worldPath: "C:/World", filename: "backup.zip" }), {
                world_path: "C:/World",
                backup_file: "backup.zip",
            });
            eq(logic.restorePreviewFailure({}), {
                statusMessage: "Restore-Vorschau fehlgeschlagen: Unbekannter Fehler",
                statusType: "error",
                toast: {
                    message: "Restore-Vorschau fehlgeschlagen: Unbekannter Fehler",
                    type: "error",
                    ms: 5000,
                },
            });
            eq(logic.restoreCancelledOutcome(), {
                statusMessage: "Wiederherstellung abgebrochen.",
                statusType: "warning",
            });
            eq(logic.restoreStartPlan(), {
                loadingText: "Stelle Backup wieder her...",
                statusMessage: "Stelle Backup wieder her...",
                statusType: "running",
            });
            const backupToken = {
                version: 1,
                world_id: "a".repeat(64),
                filename: "backup.zip",
                size_bytes: 123,
                sha256: "b".repeat(64),
            };
            eq(logic.restoreRequestBody({ worldPath: "C:/World", filename: "backup.zip", backupToken, sessionId: "s1" }), {
                world_path: "C:/World",
                backup_file: "backup.zip",
                backup_token: backupToken,
                session_id: "s1",
            });
            eq(logic.restoreRequestBody({ worldPath: "C:/World", filename: "backup.zip", backupToken, sessionId: "s1", confirmPresenceConflict: true }), {
                world_path: "C:/World",
                backup_file: "backup.zip",
                backup_token: backupToken,
                session_id: "s1",
                confirm_presence_conflict: true,
            });
            eq(logic.restorePresenceConflictRetryPlan(), {
                abortedStatusMessage: "Restore wegen Bearbeitungskonflikt abgebrochen.",
                abortedStatusType: "warning",
                retryLoadingText: "Stelle Backup trotz bestätigtem Bearbeitungskonflikt wieder her...",
            });

            const success = logic.restoreOutcome({ success: true, pre_restore_backup: "before.zip", write_gate: { allowed: true } });
            assert.strictEqual(success.ok, true);
            eq(success.writeGate, { allowed: true });
            assert.strictEqual(success.toast.message, "Backup erfolgreich wiederhergestellt. Vorheriges Backup: before.zip Welt wird neu geladen...");
            assert.strictEqual(success.toast.type, "success");
            assert.strictEqual(success.reloadLoadingText, "Welt nach Restore neu laden...");

            const cleanupWarning = logic.restoreOutcome({
                success: true,
                pre_restore_backup: "before.zip",
                cleanup_warning: "Alte Backups konnten nicht bereinigt werden.",
            });
            assert.strictEqual(cleanupWarning.ok, true);
            assert.strictEqual(cleanupWarning.toast.type, "warning");
            assert.strictEqual(cleanupWarning.toast.ms, 7000);
            assert.ok(cleanupWarning.toast.message.includes("Alte Backups konnten nicht bereinigt werden."));

            const failed = logic.restoreOutcome({ success: false, error: "kaputt", write_gate: { allowed: false } });
            assert.strictEqual(failed.ok, false);
            eq(failed.writeGate, { allowed: false });
            eq(failed.toast, { message: "Wiederherstellung fehlgeschlagen: kaputt", type: "error", ms: 5000 });

            const failedCleanup = logic.restoreOutcome({
                success: false,
                error: "kaputt",
                cleanup_warning: "Snapshot blieb zurück: C:/snap.zip",
            });
            assert.ok(failedCleanup.statusMessage.includes("Snapshot blieb zurück"));
            assert.strictEqual(failedCleanup.toast.ms, 9000);
            """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_backup_restore_logic_player_reload_plans() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backup_restore_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/backup_restore_logic.js" });
            const logic = context.window.MCBEBackupRestoreLogic;
            const plain = value => JSON.parse(JSON.stringify(value));
            const eq = (actual, expected) => assert.deepStrictEqual(plain(actual), expected);

            eq(logic.restorePlayersLoadFailureOutcome(), {
                ok: false,
                statusMessage: "Backup wiederhergestellt, automatisches Neuladen fehlgeschlagen. Bitte Welt neu laden.",
                statusType: "warning",
                toast: {
                    message: "Backup wiederhergestellt, aber die Welt konnte danach nicht automatisch neu geladen werden. Bitte Welt neu laden.",
                    type: "warning",
                    ms: 7000,
                },
            });
            const reloadCleanup = logic.restorePlayersLoadFailureOutcome("Snapshot blieb unter C:/snap.zip zurück.");
            assert.ok(reloadCleanup.statusMessage.includes("C:/snap.zip"));
            assert.ok(reloadCleanup.toast.message.includes("C:/snap.zip"));
            assert.strictEqual(reloadCleanup.toast.ms, 9000);
            eq(logic.restoredPlayerReloadPlan({ players: [{ player_key: "readonly", editable: false }], preferredPlayerKey: "p1" }), {
                hasEditablePlayer: false,
                statusMessage: "Backup wiederhergestellt. Kein editierbarer Spieler gefunden.",
                statusType: "warning",
                toast: { message: "Backup wiederhergestellt. Kein editierbarer Spieler gefunden.", type: "warning", ms: 5200 },
            });
            eq(logic.restoredPlayerReloadPlan({
                players: [{ player_key: "first", editable: true }, { player_key: "preferred", editable: true }],
                preferredPlayerKey: "preferred",
            }), { hasEditablePlayer: true, playerKey: "preferred", usedFallbackPlayer: false });
            eq(logic.restoredPlayerReloadPlan({
                players: [{ player_key: "first", editable: true }],
                preferredPlayerKey: "missing",
            }), { hasEditablePlayer: true, playerKey: "first", usedFallbackPlayer: true });

            eq(logic.restoredPlayerLoadOutcome({ expectedPlayerKey: "p1", currentPlayerKey: "other" }), {
                ok: false,
                statusMessage: "Backup wiederhergestellt, aber der Spieler konnte nicht automatisch neu geladen werden. Bitte Spieler neu laden.",
                statusType: "warning",
                toast: {
                    message: "Backup wiederhergestellt, aber der Spieler konnte nicht automatisch neu geladen werden. Bitte Spieler neu laden.",
                    type: "warning",
                    ms: 7000,
                },
            });
            eq(logic.restoredPlayerLoadOutcome({ expectedPlayerKey: "first", currentPlayerKey: "first", usedFallbackPlayer: true }), {
                ok: true,
                statusMessage: "Backup wiederhergestellt. Der vorherige Spieler wurde nicht gefunden; erster editierbarer Spieler wurde geladen.",
                statusType: "warning",
                toast: {
                    message: "Backup wiederhergestellt. Vorheriger Spieler nicht gefunden; erster editierbarer Spieler geladen.",
                    type: "warning",
                    ms: 5200,
                },
            });
            eq(logic.restoredPlayerLoadOutcome({ expectedPlayerKey: "p1", currentPlayerKey: "p1" }), {
                ok: true,
                statusMessage: "Backup wiederhergestellt. Spieler wurde aus dem wiederhergestellten Stand neu geladen.",
                statusType: "success",
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


def test_frontend_backup_restore_controller_renders_write_gate_on_restore_failure() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backup_restore_logic.js", "utf8");
            const writeGate = {
                allowed: false,
                reason: "Serverstatus unbekannt.",
                blocked_operation: "final_write_gate",
                server_status: { status: "unknown" },
            };
            const requests = [];
            const context = {
                window: {},
                fetch: async (url, options = {}) => {
                    requests.push({ url, body: options.body || "" });
                    if (url === "/api/backup/restore_preview") {
                        return {
                            payload: {
                                success: true,
                                backup_token: {
                                    version: 1,
                                    world_id: "a".repeat(64),
                                    filename: "backup.zip",
                                    size_bytes: 123,
                                    sha256: "b".repeat(64),
                                },
                            },
                        };
                    }
                    return {
                        payload: {
                            success: false,
                            error: "Restore abgelehnt: Serverstatus unbekannt.",
                            write_gate: writeGate,
                        },
                    };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backup_restore_logic.js" });

            const renderedWriteGates = [];
            const statuses = [];
            const toasts = [];
            const controller = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
                withCsrf: () => ({ "X-CSRF-Token": "t" }),
                parseJsonResponse: async response => response.payload,
                getWorldPath: () => "C:/World",
                getWorldPresenceSessionId: () => "s1",
                renderWriteGate: gate => renderedWriteGates.push(gate),
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
                showToast: (message, type, ms) => toasts.push({ message, type, ms }),
            });

            (async () => {
                await controller.restoreBackup("backup.zip");
                assert.strictEqual(requests.length, 2);
                assert.strictEqual(requests[1].url, "/api/restore_backup");
                assert.deepStrictEqual(JSON.parse(requests[1].body), {
                    world_path: "C:/World",
                    backup_file: "backup.zip",
                    backup_token: {
                        version: 1,
                        world_id: "a".repeat(64),
                        filename: "backup.zip",
                        size_bytes: 123,
                        sha256: "b".repeat(64),
                    },
                    session_id: "s1",
                });
                assert.deepStrictEqual(renderedWriteGates, [writeGate]);
                assert.strictEqual(statuses[0].type, "running");
                assert.ok(statuses.every(entry => entry.options.key === "backup-restore"));
                assert.ok(statuses.some(entry => entry.message.includes("Restore abgelehnt") && entry.type === "error"));
                assert.ok(toasts.some(entry => entry.message.includes("Restore abgelehnt") && entry.type === "error"));
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


def test_frontend_restore_aborts_when_world_changes_after_preview() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backup_restore_logic.js", "utf8");
            let worldPath = "C:/WorldA";
            const requests = [];
            const statuses = [];
            const toasts = [];
            const token = {
                version: 1,
                world_id: "a".repeat(64),
                filename: "backup.zip",
                size_bytes: 123,
                sha256: "b".repeat(64),
            };
            const context = {
                window: {},
                fetch: async (url, options = {}) => {
                    requests.push({ url, body: options.body || "" });
                    if (url === "/api/backup/restore_preview") {
                        worldPath = "C:/WorldB";
                        return { payload: { success: true, backup_token: token } };
                    }
                    throw new Error("Restore request must not be sent");
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backup_restore_logic.js" });
            const controller = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
                parseJsonResponse: async response => response.payload,
                getWorldPath: () => worldPath,
                getWorldName: () => "World A",
                logStatus: (message, type) => statuses.push({ message, type }),
                showToast: (message, type, ms) => toasts.push({ message, type, ms }),
            });

            (async () => {
                await controller.restoreBackup("backup.zip");
                assert.strictEqual(requests.length, 1);
                assert.strictEqual(JSON.parse(requests[0].body).world_path, "C:/WorldA");
                assert.ok(statuses.some(entry => entry.message.includes("Welt wurde seit der Vorschau gewechselt") && entry.type === "warning"));
                assert.ok(toasts.some(entry => entry.message.includes("Vorschau erneut öffnen") && entry.type === "warning"));
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


def test_frontend_restore_reports_reload_failure_after_successful_commit() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backup_restore_logic.js", "utf8");
            const statuses = [];
            const toasts = [];
            const token = {
                version: 1,
                world_id: "a".repeat(64),
                filename: "backup.zip",
                size_bytes: 123,
                sha256: "b".repeat(64),
            };
            const context = {
                window: {},
                console,
                fetch: async url => {
                    if (url === "/api/backup/restore_preview") {
                        return { payload: { success: true, backup_token: token } };
                    }
                    return {
                        payload: {
                            success: true,
                            pre_restore_backup: "before.zip",
                            cleanup_warning: "Snapshot blieb unter C:/snap.zip zurück.",
                        },
                    };
                },
            };
            vm.runInNewContext(code, context, { filename: "static/backup_restore_logic.js" });
            const controller = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
                parseJsonResponse: async response => response.payload,
                getWorldPath: () => "C:/World",
                getWorldName: () => "World",
                loadPlayersList: async () => { throw new Error("reload failed"); },
                logStatus: (message, type) => statuses.push({ message, type }),
                showToast: (message, type, ms) => toasts.push({ message, type, ms }),
            });

            (async () => {
                await controller.restoreBackup("backup.zip");
                assert.ok(statuses.some(entry => entry.message.includes("Backup wiederhergestellt") && entry.type === "warning"));
                assert.ok(toasts.some(entry => entry.message.includes("Welt konnte danach nicht automatisch neu geladen werden") && entry.type === "warning"));
                assert.ok(toasts.some(entry => entry.message.includes("C:/snap.zip")));
                assert.ok(!statuses.some(entry => entry.message === "Fehler bei der Verbindung zur Wiederherstellung."));
                assert.ok(!toasts.some(entry => entry.message === "Fehler bei der Verbindung zur Wiederherstellung."));
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


def test_frontend_restore_keeps_cleanup_warning_after_successful_reload() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backup_restore_logic.js", "utf8");
            const statuses = [];
            let currentPlayerKey = "";
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/backup_restore_logic.js" });
            const controller = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
                getPlayers: () => [{ player_key: "player-1", editable: true }],
                getCurrentPlayerKey: () => currentPlayerKey,
                loadPlayersList: async () => true,
                loadBackupsList: async () => {},
                loadPlayer: async playerKey => { currentPlayerKey = playerKey; },
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
            });

            (async () => {
                const reloaded = await controller.reloadWorldAfterRestore(
                    "player-1",
                    "Snapshot blieb unter C:/snap.zip zurück.",
                );
                assert.strictEqual(reloaded, true);
                assert.strictEqual(statuses.at(-1).type, "warning");
                assert.strictEqual(statuses.at(-1).options.key, "backup-restore");
                assert.ok(statuses.at(-1).message.includes("Backup wiederhergestellt"));
                assert.ok(statuses.at(-1).message.includes("C:/snap.zip"));
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


def test_frontend_restore_preview_failure_is_kept_in_status_overview() -> None:
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/backup_restore_logic.js", "utf8");
            const statuses = [];
            const context = {
                window: {},
                fetch: async () => ({ payload: { success: false, error: "Backup beschädigt" } }),
            };
            vm.runInNewContext(code, context, { filename: "static/backup_restore_logic.js" });
            const controller = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
                parseJsonResponse: async response => response.payload,
                getWorldPath: () => "C:/World",
                getWorldName: () => "World",
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
            });

            (async () => {
                await controller.restoreBackup("backup.zip");
                assert.strictEqual(statuses.at(-1).type, "error");
                assert.strictEqual(statuses.at(-1).options.key, "backup-restore");
                assert.ok(statuses.at(-1).message.includes("Backup beschädigt"));
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
