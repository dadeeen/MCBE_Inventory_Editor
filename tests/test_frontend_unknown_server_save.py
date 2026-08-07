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


def test_unknown_server_status_confirmation_retries_save_with_flag() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_controller.js", "utf8");
            const context = {
              console,
              window: {
                MCBESavePayloadLogic: { payloadContainsUserChanges: () => true },
              },
            };
            vm.runInNewContext(code, context, { filename: "static/save_controller.js" });

            const calls = [];
            const dialogs = [];
            const controller = context.window.MCBESaveController.createSaveController({
              applyCreatedTagState: () => {},
              buildChangeSummary: () => ({ total: 1 }),
              buildSavePayload: () => ({ world_path: "/worlds/w", player_key: "local_player", inventory: [{ Slot: 0 }] }),
              confirmPresenceConflict: async () => false,
              currentPlayerLabel: () => "Spieler",
              flashSaveButton: () => {},
              getCreateRequiresConfirmation: () => ({}),
              getCurrentPlayerKey: () => "local_player",
              getCurrentWriteGate: () => ({ allowed: true }),
              getIsDirty: () => true,
              getWorldPath: () => "/worlds/w",
              hideLoading: () => {},
              loadBackupsList: () => {},
              logStatus: () => {},
              markCleanState: () => {},
              normalizeOriginsToCurrentSavedState: () => {},
              openSaveReview: async () => true,
              payloadContainsUserChanges: () => true,
              postSavePayload: async payload => {
                calls.push({ ...payload });
                if (calls.length === 1) {
                  assert.strictEqual(dialogs.length, 0);
                  return {
                    success: false,
                    error: "Serverstatus unbekannt.",
                    write_gate: {
                      allowed: false,
                      requires_unknown_server_confirmation: true,
                      reason: "Serverstatus unbekannt.",
                      server_status: { status: "unknown", message: "keine Antwort" },
                    },
                  };
                }
                return { success: true, backup_file: "backup.zip", player_revision: "r2" };
              },
              recordAction: () => {},
              renderWriteGate: () => {},
              setPrimarySaveDisabled: () => {},
              setReviewConfirmDisabled: () => {},
              showConfirmDialog: async (message, options) => {
                dialogs.push({ message, options });
                return true;
              },
              showLoading: () => {},
              showToast: () => {},
              updateCurrentPlayerRevision: () => {},
              updateWorldPresence: async () => {},
              updateWriteControls: () => {},
              validateInventoryState: () => ({ errors: 0 }),
              writeBlocked: () => false,
            });

            controller.saveCurrentPlayer().then(() => {
              assert.strictEqual(calls.length, 2);
              assert.strictEqual(calls[0].confirm_unknown_server_status, undefined);
              assert.strictEqual(calls[1].confirm_unknown_server_status, true);
              assert.strictEqual(dialogs.length, 1);
              assert.ok(dialogs[0].message.includes("Serverstatus konnte nicht sicher geprüft werden"));
              assert.strictEqual(dialogs[0].options.okLabel, "Ich bin sicher, der Server ist gestoppt");
            }).catch(err => {
              console.error(err);
              process.exit(1);
            });
            """
        )
    )


def test_unknown_server_status_confirmation_cancel_does_not_retry() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_controller.js", "utf8");
            const context = {
              console,
              window: {
                MCBESavePayloadLogic: { payloadContainsUserChanges: () => true },
              },
            };
            vm.runInNewContext(code, context, { filename: "static/save_controller.js" });

            let calls = 0;
            const controller = context.window.MCBESaveController.createSaveController({
              applyCreatedTagState: () => {},
              buildChangeSummary: () => ({ total: 1 }),
              buildSavePayload: () => ({ world_path: "/worlds/w", player_key: "local_player", inventory: [{ Slot: 0 }] }),
              confirmPresenceConflict: async () => false,
              currentPlayerLabel: () => "Spieler",
              flashSaveButton: () => {},
              getCreateRequiresConfirmation: () => ({}),
              getCurrentPlayerKey: () => "local_player",
              getCurrentWriteGate: () => ({ allowed: true }),
              getIsDirty: () => true,
              getWorldPath: () => "/worlds/w",
              hideLoading: () => {},
              loadBackupsList: () => {},
              logStatus: () => {},
              markCleanState: () => {},
              normalizeOriginsToCurrentSavedState: () => {},
              openSaveReview: async () => true,
              payloadContainsUserChanges: () => true,
              postSavePayload: async () => {
                calls += 1;
                return {
                  success: false,
                  error: "Serverstatus unbekannt.",
                  write_gate: {
                    allowed: false,
                    requires_unknown_server_confirmation: true,
                    reason: "Serverstatus unbekannt.",
                    server_status: { status: "unknown" },
                  },
                };
              },
              recordAction: () => {},
              renderWriteGate: () => {},
              setPrimarySaveDisabled: () => {},
              setReviewConfirmDisabled: () => {},
              showConfirmDialog: async () => false,
              showLoading: () => {},
              showToast: () => {},
              updateCurrentPlayerRevision: () => {},
              updateWorldPresence: async () => {},
              updateWriteControls: () => {},
              validateInventoryState: () => ({ errors: 0 }),
              writeBlocked: () => false,
            });

            controller.saveCurrentPlayer().then(() => {
              assert.strictEqual(calls, 1);
            }).catch(err => {
              console.error(err);
              process.exit(1);
            });
            """
        )
    )


def test_unknown_server_fetch_guard_retries_restore_and_import_with_flag() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            function element() {
              return {
                style: {},
                className: "",
                textContent: "",
                value: "",
                replaceChildren: () => {},
                appendChild: () => {},
                append: () => {},
                focus: () => setTimeout(() => {
                  if (typeof okButton.onclick === "function") okButton.onclick();
                }, 0),
              };
            }
            const okButton = element();
            const cancelButton = element();
            const messageEl = element();
            const overlay = element();
            const document = {
              body: { appendChild: () => {} },
              querySelector: () => null,
              createElement: () => element(),
              getElementById: id => ({
                confirmOverlay: overlay,
                confirmMessage: messageEl,
                confirmOk: okButton,
                confirmCancel: cancelButton,
              })[id] || element(),
            };
            function response(data) {
              return { clone: () => response(data), json: async () => data };
            }

            const calls = [];
            const context = {
              console,
              document,
              Response,
              setTimeout,
              window: {
                location: { href: "http://127.0.0.1/" },
                fetch: async (input, init = {}) => {
                  calls.push({ input, body: JSON.parse(init.body || "{}") });
                  if (calls.length % 2 === 1) {
                    return response({
                      success: false,
                      error: "Serverstatus unbekannt.",
                      write_gate: {
                        allowed: false,
                        requires_unknown_server_confirmation: true,
                        reason: "Serverstatus unbekannt.",
                        server_status: { status: "unknown", message: "keine Antwort" },
                      },
                    });
                  }
                  return response({ success: true });
                },
              },
            };
            context.window.document = document;
            const code = fs.readFileSync("static/ui_feedback.js", "utf8");
            vm.runInNewContext(code, context, { filename: "static/ui_feedback.js" });

            Promise.resolve()
              .then(() => context.window.fetch("/api/restore_backup", {
                method: "POST",
                body: JSON.stringify({ world_path: "/worlds/w", backup_file: "b.zip" }),
              }))
              .then(() => context.window.fetch("/api/player/import", {
                method: "POST",
                body: JSON.stringify({ world_path: "/worlds/w", export_zip: "p.zip" }),
              }))
              .then(() => {
                assert.strictEqual(calls.length, 4);
                assert.strictEqual(calls[0].body.confirm_unknown_server_status, undefined);
                assert.strictEqual(calls[1].body.confirm_unknown_server_status, true);
                assert.strictEqual(calls[2].body.confirm_unknown_server_status, undefined);
                assert.strictEqual(calls[3].body.confirm_unknown_server_status, true);
                assert.strictEqual(okButton.textContent, "Fortfahren");
              })
              .catch(err => {
                console.error(err);
                process.exit(1);
              });
            """
        )
    )
