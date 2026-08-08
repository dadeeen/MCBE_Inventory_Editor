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


def test_frontend_html_utils_escape_html_and_attributes() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/html_utils.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/html_utils.js" });

            const { escapeHtml, escapeAttr } = context.window.MCBEHtmlUtils;
            assert.strictEqual(escapeHtml("&<>\"'`"), "&amp;&lt;&gt;&quot;&#39;&#96;");
            assert.strictEqual(escapeAttr("a\" onclick=\"x"), "a&quot; onclick=&quot;x");
            assert.strictEqual(escapeHtml(null), "null");
            assert.strictEqual(escapeHtml(undefined), "undefined");
            """
        )
    )


def test_frontend_html_utils_format_timestamp_localizes_and_falls_back() -> None:
    """A backup timestamp has to read unambiguously in every supported locale.

    A purely numeric ``03.08.2026`` is the 3rd of August to a German reader and
    the 8th of March to an American one, and this date decides which archive
    somebody restores -- hence the month name. Older API responses without an
    ISO value keep the server-rendered string instead of showing nothing at all.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/html_utils.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/html_utils.js" });
            const { formatTimestamp } = context.window.MCBEHtmlUtils;

            // The locale tag stands in for the page language i18n.js resolves at
            // runtime; the pinned time zone keeps the expectation reproducible.
            const seenOptions = [];
            const formatDateWith = tag => (date, options) => {
                seenOptions.push(options);
                return new Intl.DateTimeFormat(tag, { ...options, timeZone: "UTC" }).format(date);
            };

            context.window.MCBEI18n = { formatDate: formatDateWith("en-US") };
            const english = formatTimestamp("2026-08-03T16:56:29Z", "03.08.2026 18:56:29");
            assert.ok(english.includes("Aug 3, 2026"), english);
            assert.ok(english.includes("4:56:29"), english);
            assert.ok(!english.includes("03.08.2026"), english);

            context.window.MCBEI18n = { formatDate: formatDateWith("de-DE") };
            const german = formatTimestamp("2026-08-03T16:56:29Z", "03.08.2026 18:56:29");
            assert.ok(german.includes("03.08.2026"), german);
            assert.ok(german.includes("16:56:29"), german);

            assert.strictEqual(seenOptions.length, 2);
            assert.ok(seenOptions.every(o => o.dateStyle === "medium" && o.timeStyle === "medium"));

            // Older API responses may carry no ISO value; the server string stands in.
            assert.strictEqual(formatTimestamp(null, "12.07.2026 12:00:00"), "12.07.2026 12:00:00");
            assert.strictEqual(formatTimestamp("", "12.07.2026 12:00:00"), "12.07.2026 12:00:00");
            assert.strictEqual(formatTimestamp(null, ""), "");
            assert.strictEqual(formatTimestamp(null), "");
            assert.strictEqual(formatTimestamp("kein Datum", "12.07.2026"), "12.07.2026");
            assert.strictEqual(formatTimestamp("kein Datum", ""), "kein Datum");

            // Without the i18n module the helper must still render a time.
            context.window.MCBEI18n = undefined;
            const bare = formatTimestamp("2026-08-03T16:56:29Z", "03.08.2026 18:56:29");
            assert.ok(bare.length > 0);
            assert.notStrictEqual(bare, "03.08.2026 18:56:29");

            // An Intl implementation without dateStyle/timeStyle throws. That
            // must stay contained here: the caller renders a whole list around
            // this value, and a raised error would surface to the user as a
            // failed load rather than as one oddly formatted date.
            context.window.MCBEI18n = { formatDate: () => { throw new RangeError("dateStyle unsupported"); } };
            const survived = formatTimestamp("2026-08-03T16:56:29Z", "03.08.2026 18:56:29");
            assert.ok(survived.length > 0, survived);
            assert.ok(survived.includes("2026"), survived);
            """
        )
    )
