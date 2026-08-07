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


def test_frontend_world_analysis_view_empty_state_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_analysis_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_analysis_view.js" });

            const view = context.window.MCBEWorldAnalysisView;
            assert.strictEqual(
                view.emptyWorldAnalysisHtml(),
                '<div class="no-backups">Analyse wird nach dem Laden einer Welt angezeigt.</div>',
            );
            """
        )
    )


def test_frontend_world_analysis_view_html_escapes_dynamic_values() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_analysis_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_analysis_view.js" });

            const view = context.window.MCBEWorldAnalysisView;
            const html = view.worldAnalysisHtml({
                player: "<Alex & Steve>",
                players_total: 1,
                players_editable: 1,
                players_export_only: 0,
                has_ender_chest: true,
                inventory: { used: 1, damaged: 0, unknown: 0, enchantments: 0 },
                ender: { used: 0, enchantments: 0 },
                hidden: { inventory: 0, ender_chest: 0 },
                compat_errors: ['Fehler <&>'],
                compat_warnings: [],
                compat_notes: ['Notiz "A"'],
            });

            assert.ok(html.includes("&lt;Alex &amp; Steve&gt;"));
            assert.ok(html.includes("Fehler &lt;&amp;&gt;"));
            assert.ok(html.includes("Notiz &quot;A&quot;"));
            assert.ok(!html.includes("<Alex & Steve>"));
            """
        )
    )


def test_frontend_world_analysis_view_keeps_notes_only_status_ok() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_analysis_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_analysis_view.js" });

            const view = context.window.MCBEWorldAnalysisView;
            const html = view.worldAnalysisHtml({
                player: "Alex",
                players_total: 1,
                players_editable: 1,
                players_export_only: 0,
                has_ender_chest: true,
                inventory: { used: 1, damaged: 0, unknown: 0, enchantments: 0 },
                ender: { used: 0, enchantments: 0 },
                hidden: { inventory: 0, ender_chest: 0 },
                compat_errors: [],
                compat_warnings: [],
                compat_notes: ["Zusätzliche Weltdateien/-ordner vorhanden; sie werden nicht verändert."],
            });

            assert.ok(html.includes('<div class="overview-card ok">'));
            assert.ok(html.includes("<strong>OK</strong>"));
            assert.ok(html.includes("Zusatzdaten erhalten"));
            assert.ok(html.includes("Erhaltene Zusatzdaten"));
            assert.ok(!html.includes("Mit Hinweisen"));
            assert.ok(!html.includes('class="diagnostic-details-card warn"'));
            """
        )
    )
