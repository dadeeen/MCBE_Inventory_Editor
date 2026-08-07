from __future__ import annotations

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


def test_frontend_i18n_centralizes_locale_sensitive_behavior() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const catalog = {
                "{count} Item": "{count} Item",
                "{count} Items": "{count} Items",
            };
            const document = {
                documentElement: { lang: "en" },
                readyState: "loading",
                getElementById: id => id === "i18nCatalog" ? { textContent: JSON.stringify(catalog) } : null,
                addEventListener() {},
                querySelector() { return null; },
            };
            const context = { window: {}, document, Intl, Date };
            vm.runInNewContext(fs.readFileSync("static/i18n.js", "utf8"), context, { filename: "static/i18n.js" });

            const i18n = context.window.MCBEI18n;
            assert.strictEqual(i18n.locale, "en");
            assert.strictEqual(i18n.localeTag, "en-US");
            assert.strictEqual(i18n.isEnglish(), true);
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(i18n.localizedPair("Diamant", "Diamond"))),
                { primary: "Diamond", secondary: "" },
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(i18n.localizedPair("Nur Deutsch", ""))),
                { primary: "", secondary: "" },
            );
            assert.strictEqual(i18n.compare("Apple", "Zebra") < 0, true);
            assert.strictEqual(i18n.formatNumber(1234.5), "1,234.5");
            assert.strictEqual(i18n.tp(1, "{count} Item", "{count} Items"), "1 Item");
            assert.strictEqual(i18n.tp(2, "{count} Item", "{count} Items"), "2 Items");
            """
        )
    )


def test_frontend_i18n_keeps_english_as_secondary_name_in_german_locale() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const document = {
                documentElement: { lang: "de" },
                readyState: "loading",
                getElementById: () => null,
                addEventListener() {},
            };
            const context = { window: {}, document, Intl, Date };
            vm.runInNewContext(fs.readFileSync("static/i18n.js", "utf8"), context, { filename: "static/i18n.js" });

            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(context.window.MCBEI18n.localizedPair("Diamant", "Diamond"))),
                { primary: "Diamant", secondary: "Diamond" },
            );
            """
        )
    )


def test_only_i18n_module_reads_the_raw_frontend_locale() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "static").glob("*.js")):
        if path.name == "i18n.js":
            continue
        source = path.read_text(encoding="utf-8")
        if "MCBEI18n?.locale" in source or "MCBEI18n.locale" in source:
            offenders.append(path.name)
    assert not offenders, f"Use centralized MCBEI18n helpers instead of raw locale checks: {offenders}"


def test_frontend_has_no_legacy_dom_translation_fallback() -> None:
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    source = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    style = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "data-i18n-legacy" not in template
    assert "translateLegacyDom" not in source
    assert "translateDom" not in source
    assert "data-expand-label=\"{{ t('Aufklappen') }}\"" in template
    assert "content: 'Aufklappen'" not in style
    assert "content: 'Einklappen'" not in style
