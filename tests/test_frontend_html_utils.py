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
