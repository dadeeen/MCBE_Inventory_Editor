import textwrap

from tests.node_runner import run_node


def test_frontend_player_compare_view_status_html() -> None:
    run_node(
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
