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


def test_frontend_presence_controller_reports_the_changed_player_until_it_is_reloaded() -> None:
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
            const notices = new Map();
            const storage = {};
            const controller = view.createWorldPresenceController({
                win: {
                    crypto: null,
                    sessionStorage: { getItem: key => storage[key] || "", setItem: (key, value) => { storage[key] = value; } },
                    addEventListener: () => {},
                    setInterval: () => 1,
                },
                sessionKey: "presence-test",
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
                logStatus: (text, type, options) => notices.set(options.key, { text, type, options }),
                clearStatus: key => notices.delete(key),
                showToast: (text, kind, duration, action) => toasts.push({ text, kind, duration, action }),
                showConfirmDialog: async text => { confirms.push(text); return confirmAnswer; },
            });

            (async () => {
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.strictEqual(requests[0].fingerprint_baseline, "F0");
                assert.strictEqual(requests[0].fingerprint_seen, "");
                assert.strictEqual(notices.size, 0);

                // A lasting error in the status area, like a player the server
                // guard made read-only, and one toast that offers the reload.
                responses.push({ success: true, world_fingerprint: "F1", player_revision: "R2" });
                await controller.update();
                assert.strictEqual(requests[1].fingerprint_seen, "F1");
                const notice = notices.get("player-changed");
                assert.strictEqual(notice.type, "error");
                assert.strictEqual(notice.options.active, true);
                assert.ok(notice.text.includes("seit dem Laden verändert"));
                assert.strictEqual(toasts.length, 1);
                assert.strictEqual(toasts[0].kind, "error");
                assert.strictEqual(toasts[0].text, notice.text);
                assert.strictEqual(toasts[0].action.label, "Spieler neu laden");

                // The notice stays without repeating the toast.
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.ok(notices.has("player-changed"));
                assert.strictEqual(toasts.length, 1);

                // While the page saves, it asks for no check.
                state.busy = true;
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.strictEqual(requests[3].fingerprint_baseline, undefined);
                state.busy = false;

                // The toast's reload asks first when there are unsaved changes.
                state.dirty = true;
                toasts[0].action.onClick();
                await new Promise(resolve => setImmediate(resolve));
                assert.strictEqual(confirms.length, 1);
                assert.strictEqual(reloads, 0);
                confirmAnswer = true;
                assert.strictEqual(await controller.reloadChangedPlayer(), true);
                assert.strictEqual(confirms.length, 2);
                assert.strictEqual(reloads, 1);
                state.dirty = false;
                assert.strictEqual(await controller.reloadChangedPlayer(), true);
                assert.strictEqual(confirms.length, 2);
                assert.strictEqual(reloads, 2);

                // The reloaded player has a new revision; the notice goes away.
                state.revision = "R2";
                state.fingerprint = "F1";
                responses.push({ success: true, world_fingerprint: "F1" });
                await controller.update();
                assert.strictEqual(notices.size, 0);
                assert.strictEqual(toasts.length, 1);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_presence_controller_ignores_a_poll_that_answers_late() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/presence_view.js", "utf8");
            const pending = [];
            const context = {
                window: {},
                fetch: (_url, options) => new Promise(resolve => {
                    pending.push({ body: JSON.parse(options.body), answer: resolve });
                }),
            };
            vm.runInNewContext(code, context, { filename: "static/presence_view.js" });
            const view = context.window.MCBEPresenceView;

            const toasts = [];
            const notices = new Map();
            const storage = {};
            const controller = view.createWorldPresenceController({
                win: {
                    crypto: null,
                    sessionStorage: { getItem: key => storage[key] || "", setItem: (key, value) => { storage[key] = value; } },
                    addEventListener: () => {},
                    setInterval: () => 1,
                },
                sessionKey: "presence-test",
                withCsrf: () => ({}),
                parseJsonResponse: async response => response,
                getWorldPath: () => "/w",
                getCurrentPlayerKey: () => "p",
                getCurrentPlayerLabel: () => "Alex",
                getCurrentPlayerRevision: () => "R1",
                getLoadedWorldFingerprint: () => "F0",
                getIsDirty: () => false,
                getIsBusy: () => false,
                logStatus: (text, type, options) => notices.set(options.key, text),
                clearStatus: key => notices.delete(key),
                showToast: (text, kind) => toasts.push([text, kind]),
            });

            (async () => {
                const first = controller.update();
                pending[0].answer({ success: true, world_fingerprint: "F1" });
                await first;

                // Two polls for the same world, player and revision overlap,
                // and the newer one answers first with the changed player.
                const older = controller.update();
                const newer = controller.update();
                assert.strictEqual(pending[1].body.fingerprint_seen, "F1");
                assert.strictEqual(pending[2].body.fingerprint_seen, "F1");
                pending[2].answer({ success: true, world_fingerprint: "F1", player_revision: "R2" });
                await newer;
                assert.ok(notices.has("player-changed"));
                pending[1].answer({ success: true, world_fingerprint: "F1", player_revision: "R1" });
                const late = await older;
                assert.ok(notices.has("player-changed"));
                assert.strictEqual(late, null);

                // The next poll builds on the newer answer, and the notice
                // stays without a second toast.
                const next = controller.update();
                assert.strictEqual(pending[3].body.fingerprint_baseline, "F1");
                assert.strictEqual(pending[3].body.fingerprint_seen, "");
                pending[3].answer({ success: true, world_fingerprint: "F1" });
                await next;
                assert.ok(notices.has("player-changed"));
                assert.strictEqual(toasts.length, 1);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )
