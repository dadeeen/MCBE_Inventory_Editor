"""A lost restore response must not leave stale data writable or invite a retry."""

import json
import textwrap

import pytest

from tests.node_runner import run_node


@pytest.mark.parametrize(
    "scenario",
    [
        "network",
        "body-read",
        "malformed",
        "http-contradiction",
        "unknown-conflict",
        "reload-conflict",
        "retry-network",
        "preview-network",
        "rejected",
        "changed-world",
        "changed-player-network",
        "changed-player-committed",
        "changed-player-rejected",
    ],
)
def test_restore_response_outcome_is_not_confused_with_a_rejection(scenario: str) -> None:
    result = run_node(
        "const scenario = "
        + json.dumps(scenario)
        + ";\n"
        + textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            let world = "world-a";
            let player = "player-a";
            let restoreRequests = 0;
            let resets = 0;
            let confirmations = 0;
            let reloads = 0;
            const reasons = [];
            const messages = [];
            const response = (body, status = 200, brokenBody = false) => ({
                ok: status < 400, status,
                headers: { get: () => "application/json" },
                text: async () => {
                    if (brokenBody) throw new Error("Response stream disconnected");
                    return typeof body === "string" ? body : JSON.stringify(body);
                },
            });
            const context = {
                window: {}, console: { error: () => {} },
                fetch: async url => {
                    if (url === "/api/backup/restore_preview") {
                        if (scenario === "preview-network") throw new Error("Preview disconnected");
                        return response({ success: true, backup_token: { version: 1 } });
                    }
                    assert.strictEqual(url, "/api/restore_backup");
                    restoreRequests++;
                    if (scenario === "changed-world") world = "world-b";
                    if (scenario.startsWith("changed-player-")) player = "player-b";
                    if (scenario === "changed-player-network") throw new Error("Disconnected after player switch");
                    if (scenario === "changed-player-committed") return response({ success: true });
                    if (["network", "changed-world"].includes(scenario)) throw new Error("Disconnected after POST");
                    if (scenario === "retry-network") {
                        if (restoreRequests === 1) return response({ success: false, presence_conflict: true }, 409);
                        throw new Error("Retry disconnected");
                    }
                    if (scenario === "body-read") return response("", 200, true);
                    if (scenario === "malformed") return response("<html>Bad gateway</html>", 502);
                    if (scenario === "http-contradiction") return response({ success: true, presence_conflict: true }, 500);
                    if (scenario === "unknown-conflict") return response({ success: false, write_outcome_unknown: true, presence_conflict: true }, 500);
                    if (scenario === "reload-conflict") {
                        return response({ success: false, reload_required: true, presence_conflict: true, error: "Reload required" }, 500);
                    }
                    return response({ success: false, error: "Backup token expired" }, 409);
                },
            };
            for (const file of ["api_client.js", "backup_restore_logic.js"]) {
                vm.runInNewContext(fs.readFileSync("static/" + file, "utf8"), context, { filename: file });
            }
            const api = context.window.MCBEApiClient.createApiClient();
            const controller = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
                parseJsonResponse: api.parseJsonResponse,
                getWorldPath: () => world,
                getCurrentPlayerKey: () => player,
                resetLoadedPlayerState: () => { resets++; player = ""; },
                markReloadRequired: reason => reasons.push(reason),
                confirmPresenceConflict: async () => { confirmations++; return true; },
                loadPlayersList: async () => { reloads++; return true; },
                logStatus: message => messages.push(message),
            });
            (async () => {
                await controller.restoreBackup("backup.zip");
                const changedPlayer = scenario.startsWith("changed-player-");
                const uncertain = !["preview-network", "rejected", "changed-world", "changed-player-rejected"].includes(scenario);
                assert.strictEqual(resets, uncertain && !changedPlayer ? 1 : 0, "Only uncertain committed requests invalidate the matching player");
                assert.strictEqual(reasons.length, uncertain ? 1 : 0, "Require an explicit reload before further writes");
                assert.strictEqual(player, changedPlayer ? "player-b" : uncertain ? "" : "player-a");
                assert.strictEqual(confirmations, scenario === "retry-network" ? 1 : 0, "Uncertain outcomes must not enter a retry dialog");
                assert.strictEqual(restoreRequests, scenario === "preview-network" ? 0 : scenario === "retry-network" ? 2 : 1);
                assert.strictEqual(reloads, 0, "Never turn an uncertain restore into an automatic success");
                if (uncertain && !changedPlayer) assert.ok(messages.some(message => /neu laden|Reload required/.test(message)), messages);
                console.log("restore-outcome-check-complete");
            })().catch(error => { console.error(error); process.exit(1); });
            """
        )
    )
    assert "restore-outcome-check-complete" in result.stdout


def test_unknown_restore_outcome_keeps_recovery_command_and_cleanup_warning() -> None:
    run_node(r"""
        const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
        const context = {window: {}};
        for (const file of ['api_client', 'backup_restore_logic']) {
            vm.runInNewContext(fs.readFileSync('static/' + file + '.js', 'utf8'), context);
        }
        const outcome = context.window.MCBEBackupRestoreLogic.restoreOutcome({
            success: false, write_outcome_unknown: true,
            error: 'Recovery required: python -m mcbe_editor.restore_recovery --world /world-a',
            cleanup_warning: 'Original world remains in /world-a_rollback_123',
        });
        assert.equal(outcome.ok, false);
        assert.ok(outcome.statusMessage.includes('python -m mcbe_editor.restore_recovery'));
        assert.ok(outcome.toast.message.includes('/world-a_rollback_123'));
    """)
