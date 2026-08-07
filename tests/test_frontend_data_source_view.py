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


def test_frontend_data_source_view_asset_status_html_formats_current_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/data_source_view.js", "utf8");
            const document = {
                documentElement: { lang: "de" },
                readyState: "loading",
                getElementById: id => id === "i18nCatalog" ? { textContent: "{}" } : null,
                addEventListener() {},
                querySelector() { return null; },
            };
            const context = { window: {}, document, Intl, Date };
            vm.runInNewContext(fs.readFileSync("static/i18n.js", "utf8"), context, { filename: "static/i18n.js" });
            vm.runInNewContext(code, context, { filename: "static/data_source_view.js" });

            const view = context.window.MCBEDataSourceView;
            const html = view.assetDataStatusHtml({
                itemDbStatus: {
                    status: "ok",
                    counts: { items: 1200, effects: 33, enchantments: 42 },
                    source_version_present: true,
                    source_version: { resource_pack_release: "1.21.80" },
                    verification: { verified: true, verified_at: "2026-08-04T12:00:00+00:00" },
                },
                iconSummary: {
                    count: 120,
                    scanned_files: 300,
                    warnings: [],
                    sources: [{ enabled: true, exists: true }],
                },
                unknownItems: 3,
                hasCurrentPlayer: true,
            });

            assert.ok(html.includes("Datenquellenstatus"));
            assert.ok(html.includes("data-open-db-status"));
            assert.ok(html.includes("1.200 Items"));
            assert.ok(html.includes("Mojang 1.21.80"));
            assert.ok(html.includes("geprüft"));
            assert.ok(html.includes("120 lokale Icons"));
            assert.ok(html.includes("3 ID(s)"));
            assert.ok(html.includes("Item-Daten werden erhalten; DB-Stand prüfen."));
            """
        )
    )


def test_frontend_data_source_view_item_db_status_html_formats_history_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/data_source_view.js", "utf8");
            const document = {
                documentElement: { lang: "de" },
                readyState: "loading",
                getElementById: id => id === "i18nCatalog" ? { textContent: "{}" } : null,
                addEventListener() {},
                querySelector() { return null; },
            };
            const context = { window: {}, document, Intl, Date };
            vm.runInNewContext(fs.readFileSync("static/i18n.js", "utf8"), context, { filename: "static/i18n.js" });
            vm.runInNewContext(code, context, { filename: "static/data_source_view.js" });

            const view = context.window.MCBEDataSourceView;
            const html = view.itemDbStatusHtml({
                itemDbStatus: {
                    status: "metadata-missing",
                    schema_version: 4,
                    path: "C:\\Data\\item_db.json",
                    is_configured_persistent: true,
                    history_count: 2,
                    counts: { items: 5, effects: 6, enchantments: 7 },
                    source_version_present: false,
                },
                appItemDbPath: "fallback.json",
                historyVisible: true,
                historyEntries: [{
                    generated_at: "<today>",
                    resource_pack_release: "1.21",
                    wiki_revision_id: "abcdef1234567890",
                    wiki_content_hash: "fedcba9876543210",
                    wiki_fetched_at: "now",
                }],
            });

            assert.ok(html.includes("item-db-status-hero warning"));
            assert.ok(html.includes("Herkunft fehlt"));
            assert.ok(html.includes('aria-expanded="true"'));
            assert.ok(html.includes("Versionen ausblenden"));
            assert.ok(html.includes("2 Versionseinträge"));
            assert.ok(html.includes("Datenordner"));
            assert.ok(html.includes("C:\\Data\\item_db.json"));
            assert.ok(html.includes("&lt;today&gt;"));
            assert.ok(!html.includes("<today>"));
            assert.ok(!html.includes("abcdef123456"));
            assert.ok(!html.includes("fedcba987654"));
            assert.ok(!html.includes("Wiki"));
            """
        )
    )


def test_frontend_data_source_view_warns_when_item_db_has_no_server_verification() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const document = {
                documentElement: { lang: "de" },
                readyState: "loading",
                getElementById: id => id === "i18nCatalog" ? { textContent: "{}" } : null,
                addEventListener() {},
                querySelector() { return null; },
            };
            const context = { window: {}, document, Intl, Date };
            vm.runInNewContext(fs.readFileSync("static/i18n.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);

            const view = context.window.MCBEDataSourceView;
            const status = {
                status: "ok",
                source_version_present: true,
                source_version: { resource_pack_release: "1.21.80" },
                verification: { verified: false, reason: "missing" },
            };
            assert.strictEqual(view.itemDbStatusRank(status), 1);
            assert.strictEqual(view.itemDbStatusValue(status), "Prüfung offen");
            """
        )
    )


def test_frontend_data_source_view_distinguishes_unavailable_status_from_missing_data() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const document = {
                documentElement: { lang: "de" },
                readyState: "loading",
                getElementById: id => id === "i18nCatalog" ? { textContent: "{}" } : null,
                addEventListener() {},
                querySelector() { return null; },
            };
            const context = { window: {}, document, Intl, Date };
            vm.runInNewContext(fs.readFileSync("static/i18n.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);

            const view = context.window.MCBEDataSourceView;
            const unavailable = {
                status: "unavailable",
                message: "Item-DB-Status konnte nicht geladen werden.",
                counts: {},
            };
            assert.strictEqual(view.itemDbStatusValue(unavailable), "Status nicht verfügbar");
            assert.strictEqual(view.itemDbSourceText(unavailable), "Item-DB-Status konnte nicht geladen werden.");
            assert.strictEqual(view.iconStateSummary({ status: "loading" }).value, "lädt");
            assert.strictEqual(view.iconStateSummary({ status: "unavailable" }).value, "Status nicht verfügbar");
            """
        )
    )


def test_frontend_data_source_view_keeps_no_wiki_trace_in_the_source_summary() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const document = {
                documentElement: { lang: "de" },
                readyState: "loading",
                getElementById: id => id === "i18nCatalog" ? { textContent: "{}" } : null,
                addEventListener() {},
                querySelector() { return null; },
            };
            const context = { window: {}, document, Intl, Date };
            vm.runInNewContext(fs.readFileSync("static/i18n.js", "utf8"), context, { filename: "static/i18n.js" });
            vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context, { filename: "static/data_source_view.js" });

            const view = context.window.MCBEDataSourceView;
            const html = view.assetDataStatusHtml({
                itemDbStatus: {
                    status: "ok",
                    counts: { items: 1200, effects: 33, enchantments: 42 },
                    source_version_present: true,
                    source_version: { resource_pack_release: "1.21.80", wiki_revision_id: 3648146 },
                },
            });

            assert.ok(html.includes("Mojang 1.21.80"));
            assert.ok(!html.includes("3648146"));
            assert.ok(!html.includes("Wiki"));
            """
        )
    )


def test_frontend_data_source_controller_notifies_every_status_consumer() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);

            let currentStatus = null;
            const calls = [];
            const controller = context.window.MCBEDataSourceView.createDataSourceController({
                getItemDbStatus: () => currentStatus,
                setItemDbStatus: status => {
                    currentStatus = status;
                    calls.push(["state", status]);
                },
                renderStatusCenter: () => calls.push(["status-center", currentStatus]),
                onItemDbStatusApplied: status => calls.push(["setup", status]),
            });
            const verified = { status: "ok", verification: { verified: true } };

            assert.strictEqual(controller.applyItemDbStatus(verified), verified);
            assert.strictEqual(currentStatus, verified);
            assert.deepStrictEqual(calls.map(call => call[0]), ["state", "status-center", "setup"]);
            assert.strictEqual(calls[2][1], verified);
            """
        )
    )
