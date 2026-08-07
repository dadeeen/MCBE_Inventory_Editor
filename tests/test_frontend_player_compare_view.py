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


def test_frontend_player_compare_view_status_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_compare_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_compare_view.js" });

            const view = context.window.MCBEPlayerCompareView;
            assert.strictEqual(view.comparisonLoadingHtml(), '<div class="no-backups">Vergleich wird geladen...</div>');
            const errorHtml = view.comparisonErrorHtml('Fehler <unsafe>');
            assert.ok(errorHtml.includes('Fehler &lt;unsafe&gt;'));
            assert.ok(!errorHtml.includes('Fehler <unsafe>'));
            """
        )
    )
