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


def test_frontend_presence_view_world_presence_model_and_applier() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/presence_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/presence_view.js" });

            const view = context.window.MCBEPresenceView;
            const hidden = view.worldPresenceModel({ other_sessions: 0 }, { worldPath: "C:/World" });
            assert.strictEqual(hidden.visible, false);
            assert.strictEqual(hidden.className, "presence-warning");

            const model = view.worldPresenceModel({
                other_sessions: 2,
                same_player_sessions: 1,
                other_dirty_sessions: 1,
                same_player_dirty_sessions: 1,
            }, { worldPath: "C:/World", playerLabel: "Alex" });
            assert.strictEqual(model.visible, true);
            assert.strictEqual(model.className, "presence-warning strong");
            assert.strictEqual(model.alertKey, "2:1:1:1");
            assert.ok(model.text.includes("denselben Spieler (Alex)"));
            assert.ok(model.text.includes("2 weiterer Browser-Sitzungen"));

            const element = { className: "", textContent: "", style: { display: "" } };
            view.applyWorldPresenceModel(element, model);
            assert.strictEqual(element.className, "presence-warning strong");
            assert.strictEqual(element.textContent, model.text);
            assert.strictEqual(element.style.display, "block");

            view.applyWorldPresenceModel(element, hidden);
            assert.strictEqual(element.className, "presence-warning");
            assert.strictEqual(element.textContent, "");
            assert.strictEqual(element.style.display, "none");
            """
        )
    )


def test_frontend_presence_view_conflict_text_lists_dirty_sessions() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/presence_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/presence_view.js" });

            const view = context.window.MCBEPresenceView;
            const text = view.presenceConflictText({
                error: "Konflikt",
                presence_conflict: {
                    dirty_relevant_sessions: 2,
                    sessions: [
                        { player_label: "Alex", idle_seconds: 12 },
                        { player_label: "Steve", idle_seconds: 30 },
                    ],
                },
            });
            assert.ok(text.includes("Konflikt"));
            assert.ok(text.includes("2 andere Sitzungen"));
            assert.ok(text.includes("Alex, seit 12s"));
            assert.ok(text.includes("Trotzdem fortfahren?"));
            """
        )
    )


def test_frontend_presence_leave_uses_pagehide_and_deduplicates_signals() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/presence_view.js", "utf8");
            const fetchCalls = [];
            const events = {};
            const context = {
                window: {},
                fetch: (url, options) => {
                    fetchCalls.push([url, options]);
                    return Promise.resolve({ ok: true });
                },
            };
            vm.runInNewContext(code, context, { filename: "static/presence_view.js" });

            const storage = {};
            const win = {
                crypto: null,
                sessionStorage: {
                    getItem: key => storage[key] || "",
                    setItem: (key, value) => { storage[key] = value; },
                },
                addEventListener: (name, handler) => { events[name] = handler; },
                setInterval: () => 1,
            };
            const view = context.window.MCBEPresenceView;
            const controller = view.createWorldPresenceController({
                win,
                sessionKey: "presence-test",
                withCsrf: () => ({ "Content-Type": "application/json", "X-CSRF-Token": "csrf" }),
                parseJsonResponse: async () => ({ success: true }),
                getWorldPath: () => "/tmp/world",
                getCurrentPlayerKey: () => "player",
                getCurrentPlayerLabel: () => "Alex",
                getIsDirty: () => true,
            });

            controller.wireBeforeUnload();
            assert.strictEqual(typeof events.pagehide, "function");
            assert.strictEqual(events.beforeunload, undefined);

            events.pagehide();
            controller.leave();

            assert.strictEqual(fetchCalls.length, 1);
            assert.strictEqual(fetchCalls[0][0], "/api/world/presence/leave");
            assert.strictEqual(fetchCalls[0][1].method, "POST");
            assert.strictEqual(fetchCalls[0][1].keepalive, true);
            assert.strictEqual(fetchCalls[0][1].headers["X-CSRF-Token"], "csrf");
            const payload = JSON.parse(fetchCalls[0][1].body);
            assert.ok(payload.session_id.startsWith("web-"));
            """
        )
    )
