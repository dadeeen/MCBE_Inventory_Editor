import textwrap

from tests.node_runner import run_node


def test_frontend_player_api_posts_player_requests_with_csrf_headers() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_api.js", "utf8");
            const calls = [];
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_api.js" });

            (async () => {
                const api = context.window.MCBEPlayerApi.createPlayerApiClient({
                    fetchFn: async (url, options) => {
                        calls.push({ url, options });
                        return { payload: { success: true, players: [] } };
                    },
                    withCsrf: () => ({ "Content-Type": "application/json", "X-CSRFToken": "token" }),
                    parseJsonResponse: async response => response.payload,
                });

                await api.listPlayers("C:/World");
                await api.loadPlayer("C:/World", "local_player");

                assert.deepStrictEqual(calls.map(call => call.url), ["/api/players", "/api/player/load"]);
                assert.strictEqual(calls[0].options.method, "POST");
                assert.strictEqual(calls[0].options.headers["X-CSRFToken"], "token");
                assert.strictEqual(calls[0].options.body, JSON.stringify({ world_path: "C:/World" }));
                assert.strictEqual(calls[1].options.body, JSON.stringify({
                    world_path: "C:/World",
                    player_key: "local_player",
                }));
            })();
            """
        )
    )


def test_frontend_player_api_load_player_or_throw_uses_error_builder() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_api.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_api.js" });

            (async () => {
                const api = context.window.MCBEPlayerApi.createPlayerApiClient({
                    fetchFn: async () => ({ payload: { success: false, error: "Backend detail" } }),
                    parseJsonResponse: async response => response.payload,
                    buildErrorMessage: (data, fallback) => `${fallback}: ${data.error}`,
                });

                await assert.rejects(
                    () => api.loadPlayerOrThrow("C:/World", "player", "Spieler konnte nicht geladen werden."),
                    /Spieler konnte nicht geladen werden\.: Backend detail/,
                );
            })();
            """
        )
    )
