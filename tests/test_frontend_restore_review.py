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


def test_frontend_restore_review_localizes_the_backup_timestamp() -> None:
    """The confirmation dialog must not disagree with the list it came from.

    This is the screen on which somebody commits to overwriting a world, so a
    date that reads as a different month here than in the backup list is the
    most expensive place for the two formats to drift apart.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const restoreCode = fs.readFileSync("static/restore_review.js", "utf8");
            const translations = { "UTC-Zeitstempel: {value}": "UTC timestamp: {value}", "Geändert": "Modified" };
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            context.window.MCBEI18n = {
                formatDate: (date, options) =>
                    new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(date),
            };
            context.window.t = (text, params) =>
                String(translations[text] || text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m));
            vm.runInNewContext(restoreCode, context, { filename: "static/restore_review.js" });

            const view = context.window.MCBERestoreReview;
            const render = backup => view.restoreReviewHtml(view.restoreReviewModel(
                { backup, target_world: { name: "Ziel" } },
                backup.filename,
                { worldPath: "C:/World" },
            ));

            const html = render({
                filename: "300125__automatic__20260803T165629Z.zip",
                modified: "03.08.2026 18:56:29",
                created_at: "2026-08-03T16:56:29Z",
                size_mb: 236.59,
                uncompressed_mb: 240,
                file_count: 12,
                dir_count: 3,
                has_db: true,
            });
            assert.ok(html.includes("Aug 3, 2026"), html);
            assert.ok(!html.includes("03.08.2026 18:56:29"), html);
            assert.ok(html.includes('title="UTC timestamp: 2026-08-03T16:56:29Z"'), html);

            // Legacy archives keep the server string and get no tooltip.
            const legacy = render({ filename: "old.zip", modified: "12.07.2026 12:00:00", has_db: true });
            assert.ok(legacy.includes("12.07.2026 12:00:00"), legacy);
            assert.ok(!legacy.includes("UTC timestamp"), legacy);

            // A preview without any timestamp must not render an empty cell.
            const unknown = render({ filename: "old.zip", has_db: true });
            assert.ok(unknown.includes("unbekannt"), unknown);
            """
        )
    )
