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


def test_unknown_server_confirmation_survives_presence_conflict_retry() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const dialogs = [];
            let okButton = null;

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
                  if (okButton && typeof okButton.onclick === "function") okButton.onclick();
                }, 0),
              };
            }

            okButton = element();
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
            const originalCreateElement = document.createElement;
            document.createElement = tag => {
              const node = originalCreateElement(tag);
              if (tag === "p") {
                Object.defineProperty(node, "textContent", {
                  get() { return this._text || ""; },
                  set(value) {
                    this._text = value;
                    if (String(value).includes("Serverstatus konnte nicht sicher geprüft werden")) dialogs.push(value);
                  },
                });
              }
              return node;
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
                  if (calls.length === 1) {
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
                  if (calls.length === 2) {
                    return response({ success: false, presence_conflict: { conflict: true } });
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
              .then(() => context.window.fetch("/api/restore_backup", {
                method: "POST",
                body: JSON.stringify({ world_path: "/worlds/w", backup_file: "b.zip", confirm_presence_conflict: true }),
              }))
              .then(() => {
                assert.strictEqual(calls.length, 3);
                assert.strictEqual(calls[0].body.confirm_unknown_server_status, undefined);
                assert.strictEqual(calls[1].body.confirm_unknown_server_status, true);
                assert.strictEqual(calls[2].body.confirm_unknown_server_status, true);
                assert.strictEqual(calls[2].body.confirm_presence_conflict, true);
                assert.strictEqual(dialogs.length, 1);
              })
              // Nach erfolgreichem Abschluss ist die Bestätigung verbraucht:
              // Ein späterer identischer Request wird nicht auto-bestätigt.
              .then(() => context.window.fetch("/api/restore_backup", {
                method: "POST",
                body: JSON.stringify({ world_path: "/worlds/w", backup_file: "b.zip" }),
              }))
              .then(() => {
                assert.strictEqual(calls.length, 4);
                assert.strictEqual(calls[3].body.confirm_unknown_server_status, undefined);
              })
              .catch(err => {
                console.error(err);
                process.exit(1);
              });
            """
        )
    )
