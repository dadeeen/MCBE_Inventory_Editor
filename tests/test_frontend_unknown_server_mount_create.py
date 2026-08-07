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


def _client_source() -> str:
    return textwrap.dedent(
        r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync("static/mount_api.js", "utf8");
        const context = { console, window: {} };
        vm.runInNewContext(code, context, { filename: "static/mount_api.js" });

        const calls = [];
        let responses = [];
        const client = context.window.MCBEMountApi.createMountApiClient({
          fetchFn: async (url, init) => ({ url, body: JSON.parse(init.body) }),
          withCsrf: () => ({}),
          parseJsonResponse: async request => {
            calls.push(request.body);
            return responses.shift();
          },
        });
        """
    )


def test_mount_create_serializes_the_public_api_contract() -> None:
    _run_node(
        _client_source()
        + textwrap.dedent(
            r"""
            responses = [{ success: true }];
            client.createMount({
              worldPath: "/worlds/w",
              playerKey: "player",
              mountType: "minecraft:donkey",
              serverGuardEpoch: 7,
              serverGuardToken: "guard-token",
              preferredOffset: { x: 2, y: 0, z: -1 },
              placementRadius: 9,
              mountStats: { health: 24 },
              tamed: true,
              allowUncheckedPlacement: true,
            }).then(result => {
              assert.strictEqual(result.success, true);
              assert.strictEqual(calls.length, 1);
              assert.deepStrictEqual(JSON.parse(JSON.stringify(calls[0])), {
                world_path: "/worlds/w",
                player_key: "player",
                mount_type: "minecraft:donkey",
                create_mode: "synthetic_full",
                placement_radius: 9,
                allow_unchecked_placement: true,
                server_guard_epoch: 7,
                server_guard_token: "guard-token",
                preferred_offset: { x: 2, y: 0, z: -1 },
                mount_stats: { health: 24 },
                tamed: true,
              });
            }).catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )
    )


def test_unknown_server_status_confirmation_retries_mount_create_with_flag() -> None:
    _run_node(
        _client_source()
        + textwrap.dedent(
            r"""
            const gates = [];
            responses = [
              {
                success: false,
                error: "Serverstatus unbekannt.",
                write_gate: {
                  allowed: false,
                  requires_unknown_server_confirmation: true,
                  reason: "Serverstatus unbekannt.",
                  server_status: { status: "unknown", message: "keine Antwort" },
                },
              },
              { success: true, mount_type: "minecraft:donkey" },
            ];

            client.createMountOrThrow({
              worldPath: "/worlds/w",
              playerKey: "player",
              mountType: "minecraft:donkey",
              onUnknownServerStatus: async writeGate => { gates.push(writeGate); return true; },
            }).then(result => {
              assert.strictEqual(result.success, true);
              assert.strictEqual(calls.length, 2);
              assert.strictEqual(calls[0].confirm_unknown_server_status, undefined);
              assert.strictEqual(calls[1].confirm_unknown_server_status, true);
              assert.strictEqual(calls[1].mount_type, "minecraft:donkey");
              assert.strictEqual(gates.length, 1);
              assert.strictEqual(gates[0].requires_unknown_server_confirmation, true);
            }).catch(err => {
              console.error(err);
              process.exit(1);
            });
            """
        )
    )


def test_unknown_server_status_declined_aborts_without_retry() -> None:
    _run_node(
        _client_source()
        + textwrap.dedent(
            r"""
            responses = [
              {
                success: false,
                error: "Serverstatus unbekannt.",
                write_gate: {
                  allowed: false,
                  requires_unknown_server_confirmation: true,
                  reason: "Serverstatus unbekannt.",
                  server_status: { status: "unknown" },
                },
              },
            ];

            client.createMountOrThrow({
              worldPath: "/worlds/w",
              playerKey: "player",
              mountType: "minecraft:mule",
              onUnknownServerStatus: async () => false,
            }).then(() => {
              console.error("erwarteter Abbruch blieb aus");
              process.exit(1);
            }).catch(err => {
              assert.strictEqual(err.unknownServerDeclined, true);
              assert.strictEqual(calls.length, 1);
            });
            """
        )
    )


def test_other_create_errors_do_not_trigger_unknown_server_dialog() -> None:
    _run_node(
        _client_source()
        + textwrap.dedent(
            r"""
            const gates = [];
            responses = [
              { success: false, error: "digp enthält den Actor-Suffix nicht" },
            ];

            client.createMountOrThrow({
              worldPath: "/worlds/w",
              playerKey: "player",
              onUnknownServerStatus: async writeGate => { gates.push(writeGate); return true; },
            }).then(() => {
              console.error("erwarteter Fehler blieb aus");
              process.exit(1);
            }).catch(err => {
              assert.strictEqual(gates.length, 0);
              assert.strictEqual(calls.length, 1);
              assert.ok(err.message.includes("digp"));
            });
            """
        )
    )


def test_committed_mount_error_preserves_structured_response_on_exception() -> None:
    _run_node(
        _client_source()
        + textwrap.dedent(
            r"""
            responses = [
              {
                success: false,
                write_committed: true,
                validation_failed: true,
                error_phase: "post_write",
                error: "Mount wurde bereits geschrieben; Nachvalidierung fehlgeschlagen.",
                backup_file: "backup.zip",
              },
            ];

            client.createMountOrThrow({
              worldPath: "/worlds/w",
              playerKey: "player",
            }).then(() => {
              console.error("erwarteter Fehler blieb aus");
              process.exit(1);
            }).catch(err => {
              assert.strictEqual(err.writeCommitted, true);
              assert.strictEqual(err.validationFailed, true);
              assert.strictEqual(err.errorPhase, "post_write");
              assert.strictEqual(err.data.write_committed, true);
              assert.strictEqual(err.data.backup_file, "backup.zip");
              assert.ok(err.message.includes("bereits geschrieben"));
            });
            """
        )
    )
