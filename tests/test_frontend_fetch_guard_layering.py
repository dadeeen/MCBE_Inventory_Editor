"""Regression tests for fetch-guard layering.

The app loads api_client.js before ui_feedback.js (templates/index.html).
Only ui_feedback.js may install the global unknown-server-status fetch guard:
a second wrapper would stack on top of it and show a duplicate confirmation
dialog for the same blocked write — including a path where a user who already
declined gets prompted again and can accidentally proceed.
"""

import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

_HARNESS = r"""
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
const stubFetch = async (input, init = {}) => {
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
  return response({ success: true });
};

const context = {
  console,
  document,
  Response,
  setTimeout,
  window: {
    location: { href: "http://127.0.0.1/" },
    confirm: () => { throw new Error("native window.confirm darf nicht verwendet werden"); },
    fetch: stubFetch,
  },
};
context.window.document = document;

// Reale Ladereihenfolge aus templates/index.html: erst api_client.js, dann ui_feedback.js.
vm.runInNewContext(fs.readFileSync("static/api_client.js", "utf8"), context, { filename: "static/api_client.js" });
assert.strictEqual(context.window.fetch, stubFetch, "api_client.js darf window.fetch nicht wrappen");
vm.runInNewContext(fs.readFileSync("static/ui_feedback.js", "utf8"), context, { filename: "static/ui_feedback.js" });
assert.notStrictEqual(context.window.fetch, stubFetch, "ui_feedback.js muss den Fetch-Guard installieren");
"""


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_only_ui_feedback_installs_fetch_guard_and_prompts_exactly_once() -> None:
    _run_node(
        _HARNESS
        + textwrap.dedent(
            r"""
            context.window.fetch("/api/player/import", {
                method: "POST",
                body: JSON.stringify({ world_path: "/worlds/w", target_player_key: "p", export_zip: "e.mcbe-player.zip", confirm_overwrite: true }),
            })
              .then(() => {
                assert.strictEqual(dialogs.length, 1, "genau ein Bestätigungsdialog");
                assert.strictEqual(calls.length, 2, "genau ein Retry");
                assert.strictEqual(calls[0].body.confirm_unknown_server_status, undefined);
                assert.strictEqual(calls[1].body.confirm_unknown_server_status, true);
              })
              .catch(err => {
                console.error(err);
                process.exit(1);
              });
            """
        )
    )


def test_backup_create_is_covered_by_unknown_server_fetch_guard() -> None:
    _run_node(
        _HARNESS
        + textwrap.dedent(
            r"""
            context.window.fetch("/api/backup/create", {
                method: "POST",
                body: JSON.stringify({ world_path: "/worlds/w" }),
            })
              .then(() => {
                assert.strictEqual(dialogs.length, 1, "genau ein Bestätigungsdialog");
                assert.strictEqual(calls.length, 2, "genau ein Retry");
                assert.strictEqual(calls[1].body.confirm_unknown_server_status, true);
              })
              .catch(err => {
                console.error(err);
                process.exit(1);
              });
            """
        )
    )


def test_player_state_transfer_is_covered_by_unknown_server_fetch_guard() -> None:
    _run_node(
        _HARNESS
        + textwrap.dedent(
            r"""
            context.window.fetch("/api/player/state_transfer", {
                method: "POST",
                body: JSON.stringify({
                    world_path: "/worlds/w",
                    source_player_key: "local",
                    target_player_key: "remote",
                    transfer_token: { version: 4 },
                    confirm_transfer: true,
                }),
            })
              .then(() => {
                assert.strictEqual(dialogs.length, 1, "genau ein Bestätigungsdialog");
                assert.strictEqual(calls.length, 2, "genau ein Retry");
                assert.strictEqual(calls[0].body.confirm_unknown_server_status, undefined);
                assert.strictEqual(calls[1].body.confirm_unknown_server_status, true);
              })
              .catch(err => {
                console.error(err);
                process.exit(1);
              });
            """
        )
    )
