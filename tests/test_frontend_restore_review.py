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


def test_frontend_restore_review_html_formats_and_escapes_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const restoreCode = fs.readFileSync("static/restore_review.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(restoreCode, context, { filename: "static/restore_review.js" });

            const view = context.window.MCBERestoreReview;
            const model = view.restoreReviewModel({
                backup: {
                    filename: "backup <one>.zip",
                    modified: "2026-06-29",
                    size_mb: 12.5,
                    uncompressed_mb: 40,
                    file_count: 123,
                    dir_count: 7,
                    has_db: false,
                    levelname: "World & Test",
                },
                target_world: { name: "Ziel <Welt>" },
            }, "fallback.zip", {
                worldPath: "C:\\World & Path",
            });
            const html = view.restoreReviewHtml(model);

            assert.ok(html.includes("restore-target-card"));
            assert.ok(html.includes("Ziel &lt;Welt&gt;"));
            assert.ok(html.includes("C:\\World &amp; Path"));
            assert.ok(html.includes("backup &lt;one&gt;.zip"));
            assert.ok(html.includes("12.5 MB"));
            assert.ok(html.includes("40 MB"));
            assert.ok(html.includes("Einträge: 123 Dateien / 7 Ordner"));
            assert.ok(html.includes("levelname.txt: World &amp; Test"));
            assert.ok(html.includes("restore-check warn"));
            assert.ok(html.includes("Backup enthält db/"));
            assert.ok(!html.includes("Ziel <Welt>"));
            """
        )
    )
