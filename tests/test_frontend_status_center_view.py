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


def test_frontend_status_center_view_model_ranks_runtime_and_state() -> None:
    _run_node(
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
    _run_node(
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
    _run_node(
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
