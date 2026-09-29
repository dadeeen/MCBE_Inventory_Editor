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


def test_frontend_player_watch_reports_only_a_changed_revision() -> None:
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

            const loaded = { worldPath: "/w", playerKey: "p", loadedFingerprint: "F0", revision: "R1" };
            let watch = view.nextPlayerWatch(null, loaded);
            const key = watch.key;
            assert.ok(key);
            assert.strictEqual(watch.baseline, "F0");
            assert.strictEqual(watch.changed, false);
            let request = view.playerWatchRequest(watch);
            assert.strictEqual(request.fingerprint_baseline, "F0");
            assert.strictEqual(request.fingerprint_seen, "");

            const answer = (data, options = {}) => view.nextPlayerWatch(watch, loaded, { data, requestKey: key, ...options });
            watch = answer({ world_fingerprint: "F0" });
            assert.strictEqual(watch.seen, "");
            // Changed, and still changing on the next poll: no read yet.
            watch = answer({ world_fingerprint: "F1" });
            assert.strictEqual(watch.seen, "F1");
            watch = answer({ world_fingerprint: "F2" });
            assert.strictEqual(watch.seen, "F2");
            assert.strictEqual(view.playerWatchRequest(watch).fingerprint_seen, "F2");
            // Stable: the server read the player, which the change did not touch.
            watch = answer({ world_fingerprint: "F2", player_revision: "R1" });
            assert.strictEqual(watch.changed, false);
            assert.strictEqual(watch.baseline, "F2");
            assert.strictEqual(watch.seen, "");
            // A later change of the player itself.
            watch = answer({ world_fingerprint: "F3" });
            const beforeRead = watch;
            watch = answer({ world_fingerprint: "F3", player_revision: "R2" });
            assert.strictEqual(watch.changed, true);
            // A response while the page saves or loads, or to an older request,
            // may describe a revision the page has not received yet.
            const busy = view.nextPlayerWatch(beforeRead, loaded, { data: { world_fingerprint: "F3", player_revision: "R2" }, requestKey: key, busy: true });
            assert.strictEqual(busy.changed, false);
            const older = view.nextPlayerWatch(beforeRead, loaded, { data: { world_fingerprint: "F3", player_revision: "R2" }, requestKey: "older" });
            assert.strictEqual(older.changed, false);
            // Reloading brings a new revision and fingerprint and starts over.
            const reloaded = view.nextPlayerWatch(watch, { ...loaded, loadedFingerprint: "F3", revision: "R2" });
            assert.notStrictEqual(reloaded.key, key);
            assert.strictEqual(reloaded.changed, false);
            assert.strictEqual(reloaded.baseline, "F3");
            // Without a loaded player nothing is watched.
            const none = view.nextPlayerWatch(watch, { ...loaded, playerKey: "" });
            assert.strictEqual(none.key, "");
            assert.strictEqual(Object.keys(view.playerWatchRequest(none)).length, 0);
            """
        )
    )


def test_frontend_presence_controller_shows_the_changed_player_hint_and_reloads() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/presence_view.js", "utf8");
            const requests = [];
            const responses = [];
            const context = {
                window: {},
                fetch: (_url, options) => {
                    requests.push(JSON.parse(options.body));
                    return Promise.resolve({});
                },
            };
            vm.runInNewContext(code, context, { filename: "static/presence_view.js" });
            const view = context.window.MCBEPresenceView;

            const state = { revision: "R1", fingerprint: "F0", dirty: false, busy: false };
            const toasts = [];
            const confirms = [];
            let confirmAnswer = false;
            let reloads = 0;
            const handlers = {};
            const banner = { style: { display: "none" } };
            const storage = {};
            const controller = view.createWorldPresenceController({
                win: {
                    crypto: null,
                    sessionStorage: { getItem: key => storage[key] || "", setItem: (key, value) => { storage[key] = value; } },
                    addEventListener: () => {},
                    setInterval: () => 1,
                },
                sessionKey: "presence-test",
                elements: {
                    playerChangedBanner: banner,
                    playerChangedButton: { addEventListener: (name, handler) => { handlers[name] = handler; } },
                },
                withCsrf: () => ({}),
                parseJsonResponse: async () => responses.shift(),
                getWorldPath: () => "/w",
                getCurrentPlayerKey: () => "p",
                getCurrentPlayerLabel: () => "Alex",
                getCurrentPlayerRevision: () => state.revision,
                getLoadedWorldFingerprint: () => state.fingerprint,
                getIsDirty: () => state.dirty,
                getIsBusy: () => state.busy,
                reloadPlayer: () => { reloads += 1; return true; },
                showToast: (text, kind) => toasts.push([text, kind]),
                showConfirmDialog: async text => { confirms.push(text); return confirmAnswer; },
            });

            (async () => {
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.strictEqual(requests[0].fingerprint_baseline, "F0");
                assert.strictEqual(requests[0].fingerprint_seen, "");
                assert.strictEqual(banner.style.display, "none");

                responses.push({ success: true, world_fingerprint: "F1", player_revision: "R2" });
                await controller.update();
                assert.strictEqual(requests[1].fingerprint_seen, "F1");
                assert.strictEqual(banner.style.display, "flex");
                assert.strictEqual(toasts.length, 1);
                assert.strictEqual(toasts[0][1], "warning");
                assert.ok(toasts[0][0].includes("seit dem Laden verändert"));

                // The hint stays without repeating the toast.
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.strictEqual(banner.style.display, "flex");
                assert.strictEqual(toasts.length, 1);

                // While the page saves, it asks for no check.
                state.busy = true;
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.strictEqual(requests[3].fingerprint_baseline, undefined);
                state.busy = false;

                // Reloading asks first when there are unsaved changes.
                controller.wirePlayerChangedBanner();
                assert.strictEqual(typeof handlers.click, "function");
                state.dirty = true;
                assert.strictEqual(await controller.reloadChangedPlayer(), false);
                assert.strictEqual(confirms.length, 1);
                assert.strictEqual(reloads, 0);
                confirmAnswer = true;
                assert.strictEqual(await controller.reloadChangedPlayer(), true);
                assert.strictEqual(reloads, 1);
                state.dirty = false;
                assert.strictEqual(await controller.reloadChangedPlayer(), true);
                assert.strictEqual(confirms.length, 2);

                // The reloaded player has a new revision; the hint goes away.
                state.revision = "R2";
                state.fingerprint = "F1";
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.strictEqual(banner.style.display, "none");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )
