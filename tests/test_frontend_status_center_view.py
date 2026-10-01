import textwrap

from tests.node_runner import run_node


def test_frontend_status_center_view_model_ranks_runtime_and_state() -> None:
    run_node(
        textwrap.dedent(r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);
        vm.runInNewContext(fs.readFileSync("static/status_center_view.js", "utf8"), context);
        const view = context.window.MCBEStatusCenterView;
        const model = view.statusCenterModel({
            runtimeDiagnostics: {
                write_gate_setup: { local_world_access_warning: true },
                write_gate: { allowed: false, server_status: { status: "online" } },
            },
            appConfig: { mode: "local" },
            currentCompatibility: {
                world: { status: "warning", warnings: ["World"] },
                player: { status: "ok", warnings: [] },
            },
            iconSummary: {
                count: 0,
                sources: [{ enabled: true, exists: false }],
                warnings: ["Icon"],
            },
            itemDbStatus: {
                status: "metadata-missing",
                counts: { items: 2, effects: 3, enchantments: 4 },
            },
            lastWorldScan: { roots: [{ status: "error" }] },
            isDirty: true,
            worldPath: "C:/World",
            selectedWorldPath: "C:/Selected",
            currentPlayerLabel: "Alex",
            hasCurrentPlayer: true,
            compatibilitySummary: "Kompatibilitätshinweis",
        });
        assert.strictEqual(model.heroClass, "error");
        assert.strictEqual(model.headline, "Prüfen");
        assert.strictEqual(model.tiles.length, 6);
        assert.strictEqual(model.tiles[0].detail, "C:/Selected");
        assert.strictEqual(model.tiles[1].value, "gesperrt");
        assert.ok(model.tiles[2].detail.includes("Kompatibilitätshinweis"));
    """)
    )


def test_frontend_status_center_view_html_escapes_hero_text_and_tiles() -> None:
    run_node(
        textwrap.dedent(r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/html_utils.js", "utf8"), context);
        vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);
        vm.runInNewContext(fs.readFileSync("static/status_center_view.js", "utf8"), context);
        const html = context.window.MCBEStatusCenterView.statusCenterHtml({
            heroClass: "warning",
            headline: "<Prüfen>",
            subtitle: "Lokal & Alex",
            detail: "Details <unten>",
            tiles: [{ label: "Welt", value: "<offen>", detail: "Pfad & Hinweis", rank: 1 }],
        });
        assert.ok(html.includes("&lt;Prüfen&gt;"));
        assert.ok(html.includes("Lokal &amp; Alex"));
        assert.ok(html.includes("Details &lt;unten&gt;"));
        assert.ok(html.includes("&lt;offen&gt;"));
        assert.ok(!html.includes("<Prüfen>"));
    """)
    )


def test_frontend_status_center_treats_world_notes_as_ok() -> None:
    run_node(
        textwrap.dedent(r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);
        vm.runInNewContext(fs.readFileSync("static/status_center_view.js", "utf8"), context);
        const view = context.window.MCBEStatusCenterView;
        const note = "Zusätzliche Weltdateien/-ordner vorhanden; sie werden nicht verändert.";
        const compatibility = {
            world: { status: "ok", warnings: [], notes: [note] },
            player: { status: "ok", warnings: [], notes: [] },
        };
        const model = view.statusCenterModel({
            runtimeDiagnostics: {
                write_gate: { allowed: true, server_status: { status: "offline" } },
            },
            appConfig: { mode: "docker" },
            currentCompatibility: compatibility,
            iconSummary: { count: 1, warnings: [] },
            itemDbStatus: {
                status: "ok",
                counts: { items: 2, effects: 3, enchantments: 4 },
                source_version_present: true,
                verification: { verified: true },
            },
            lastWorldScan: { roots: [] },
            worldPath: "C:/World",
            currentPlayerLabel: "Alex",
            hasCurrentPlayer: true,
        });
        const tile = model.tiles.find(tile => tile.label === "Kompatibilität");
        assert.strictEqual(tile.value, "OK");
        assert.strictEqual(tile.rank, 0);
        assert.strictEqual(tile.detail, "Zusatzdaten werden erhalten");
        assert.strictEqual(model.heroClass, "ok");
        const text = view.statusCenterText({
            currentCompatibility: compatibility,
            iconSummary: { count: 1 },
            worldPath: "C:/World",
            currentPlayerLabel: "Alex",
        });
        assert.ok(text.includes("Kompatibilität: ok"));
        assert.ok(text.includes("Kompatibilitätshinweise: -"));
        assert.ok(text.includes(`Erhaltene Zusatzdaten: ${note}`));
    """)
    )


def test_frontend_status_center_shows_the_write_gate_of_the_header() -> None:
    run_node(
        textwrap.dedent(r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);
        vm.runInNewContext(fs.readFileSync("static/status_center_view.js", "utf8"), context);
        const view = context.window.MCBEStatusCenterView;
        const healthy = {
            iconSummary: { count: 1, warnings: [] },
            itemDbStatus: { status: "ok", counts: {}, verification: { verified: true } },
        };
        const writing = model => model.tiles.find(tile => tile.label === "Schreiben");
        const docker = { mode: "docker", require_server_offline: true };

        // The live gate wins over an older diagnostics snapshot.
        const online = view.statusCenterModel({
            ...healthy,
            appConfig: docker,
            writeGate: { allowed: false, server_status: { status: "online" } },
            runtimeDiagnostics: { write_gate: { allowed: true, server_status: { status: "offline" } } },
        });
        assert.strictEqual(online.heroClass, "error");
        assert.strictEqual(online.headline, "Prüfen");
        assert.deepStrictEqual(
            [writing(online).value, writing(online).detail, writing(online).rank],
            ["gesperrt", "Schreibsperre aktiv", 2],
        );

        // Without any gate the overview says it is still checking, not "Alles OK".
        const unknown = view.statusCenterModel({ ...healthy, appConfig: docker });
        assert.strictEqual(unknown.headline, "Hinweise");
        assert.deepStrictEqual(
            [writing(unknown).value, writing(unknown).detail, writing(unknown).rank],
            ["wird geprüft", "Status wird geladen", 1],
        );

        const rankOf = (writeGate, appConfig = docker) => {
            const tile = writing(view.statusCenterModel({ ...healthy, appConfig, writeGate }));
            return [tile.value, tile.detail, tile.rank];
        };
        // A player loaded while the server was online stays blocked after it stopped.
        assert.deepStrictEqual(
            rankOf({ allowed: false, stale_loaded_player: true, server_status: { status: "offline" } }),
            ["gesperrt", "Schreibsperre aktiv", 2],
        );
        // An unknown status can be confirmed before writing: a notice, not an error.
        assert.deepStrictEqual(
            rankOf({ allowed: false, requires_unknown_server_confirmation: true, server_status: { status: "unknown" } }),
            ["nach Bestätigung", "Serverstatus unbekannt.", 1],
        );
        // A failed check keeps the last status but is never "Alles OK".
        assert.deepStrictEqual(
            rankOf({
                allowed: false,
                requires_unknown_server_confirmation: true,
                status_check_failed: true,
                server_status: { status: "offline" },
            }),
            ["nach Bestätigung", "Serverstatus konnte nicht abgefragt werden.", 1],
        );
        assert.deepStrictEqual(
            rankOf({ allowed: false, status_check_failed: true, server_status: { status: "online" } }),
            ["gesperrt", "Serverstatus konnte nicht abgefragt werden.", 2],
        );
        assert.deepStrictEqual(
            rankOf({ allowed: false, read_only: true, server_status: { status: "online" } }),
            ["gesperrt", "Read-Only-Modus", 0],
        );
        assert.deepStrictEqual(
            rankOf({ allowed: true, server_status: { status: "online" } }, { mode: "docker", require_server_offline: false }),
            ["bereit", "Schreiben erlaubt", 0],
        );
        assert.deepStrictEqual(
            rankOf({ allowed: true, server_status: { status: "offline" } }, { mode: "local", require_server_offline: true }),
            ["bereit", "Schreiben erlaubt", 0],
        );
        // The local mode without the offline requirement warns before diagnostics load.
        assert.deepStrictEqual(
            rankOf(
                { allowed: false, requires_unknown_server_confirmation: true, server_status: { status: "unknown" } },
                { mode: "local", require_server_offline: false },
            ),
            ["nach Bestätigung", "Keine Serverprüfung: Welt nur öffnen, wenn Minecraft/Server geschlossen ist.", 1],
        );

        const text = view.statusCenterText({
            appConfig: docker,
            writeGate: { allowed: false, server_status: { status: "online" } },
            runtimeDiagnostics: { write_gate: { allowed: true, server_status: { status: "offline" } } },
        });
        assert.ok(text.includes("Schreiben: gesperrt"));
        assert.ok(text.includes("Serverstatus: online"));
        assert.ok(view.statusCenterText({ appConfig: docker }).includes("Schreiben: wird geprüft"));
        assert.ok(view.statusCenterText({ appConfig: docker }).includes("Lokalmodus-Hinweis: -"));
        assert.ok(
            view.statusCenterText({ appConfig: { mode: "local", require_server_offline: false } })
                .includes("Lokalmodus-Hinweis: keine Serverprüfung"),
        );
    """)
    )


def test_frontend_status_center_controller_renders_only_a_changed_overview() -> None:
    run_node(
        textwrap.dedent(r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/html_utils.js", "utf8"), context);
        vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);
        vm.runInNewContext(fs.readFileSync("static/status_center_view.js", "utf8"), context);
        let html = "";
        let writes = 0;
        const panel = {
            get innerHTML() { return html; },
            set innerHTML(value) { html = value; writes += 1; },
        };
        let gate = { allowed: true, server_status: { status: "offline" } };
        const controller = context.window.MCBEStatusCenterView.createStatusCenterController({
            panel,
            getWriteGate: () => gate,
            getAppConfig: () => ({ mode: "docker", require_server_offline: true }),
        });

        controller.render();
        controller.render();
        assert.strictEqual(writes, 1);
        assert.ok(html.includes("Schreiben erlaubt"));

        gate = { allowed: false, server_status: { status: "online" } };
        controller.render();
        assert.strictEqual(writes, 2);
        assert.ok(html.includes("Schreibsperre aktiv"));
        assert.strictEqual(controller.snapshot().writeGate, gate);

        // Cleared from outside, the overview is drawn again.
        panel.innerHTML = "";
        controller.render();
        assert.strictEqual(writes, 4);
        assert.ok(html.includes("Schreibsperre aktiv"));
    """)
    )
