import textwrap

from tests.node_runner import run_node


def test_late_status_responses_preserve_applied_update_and_open_history() -> None:
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/data_source_view.js');
(async () => {
    for (const fails of [false, true]) {
        const panel = { innerHTML: '', querySelector: () => null };
        const applied = [], warnings = [];
        let status = null, finishOld;
        console.warn = (...args) => warnings.push(args);
        global.fetch = url => {
            if (url.endsWith('/versions')) return Promise.resolve({ json: async () => ({
                success: true, entries: [{ resource_pack_release: 'new-release' }],
            }) });
            return new Promise((resolve, reject) => {
                finishOld = () => fails ? reject(new Error('late old request failed'))
                    : resolve({ json: async () => ({ item_db: { status: 'metadata-missing', history_count: 0 } }) });
            });
        };
        const controller = MCBEDataSourceView.createDataSourceController({
            elements: { itemDbStatusPanel: panel },
            getItemDbStatus: () => status,
            setItemDbStatus: value => { status = value; applied.push(value); },
        });
        const oldLoad = controller.loadItemDbStatus();
        const updated = { status: 'ok', history_count: 1, verification: { verified: true } };
        controller.applyItemDbStatus(updated);
        await controller.toggleVersionHistory();
        const currentHistory = panel.innerHTML;
        assert.match(currentHistory, /new-release/);
        finishOld();
        await oldLoad;
        assert.equal(status, updated, `stale ${fails ? 'error' : 'success'} must not replace update status`);
        assert.equal(panel.innerHTML, currentHistory, 'stale status must not close or invalidate the new history');
        assert.equal(applied.length, 1);
        assert.equal(warnings.length, 0);
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
""")


def test_status_refresh_uses_latest_request_and_still_reports_current_failure() -> None:
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/data_source_view.js');
(async () => {
    const responses = [], warnings = [], applied = [];
    let status = null;
    console.warn = (...args) => warnings.push(args);
    global.fetch = () => new Promise(resolve => responses.push(resolve));
    const controller = MCBEDataSourceView.createDataSourceController({
        getItemDbStatus: () => status,
        setItemDbStatus: value => { status = value; applied.push(value); },
    });
    const older = controller.loadItemDbStatus();
    const newer = controller.loadItemDbStatus();
    const current = { status: 'ok', verification: { verified: true } };
    responses[1]({ json: async () => ({ item_db: current }) });
    await newer;
    responses[0]({ json: async () => ({ item_db: { status: 'metadata-missing' } }) });
    await older;
    assert.equal(status, current);
    assert.equal(applied.length, 1);

    global.fetch = async () => { throw new Error('current refresh failed'); };
    await controller.loadItemDbStatus();
    assert.equal(status.status, 'unavailable');
    assert.equal(status.message, 'current refresh failed');
    assert.equal(applied.length, 2);
    assert.equal(warnings.length, 1);

    global.fetch = async () => ({ json: async () => ({ success: false, error: 'HTTP 503: Statusdienst nicht erreichbar' }) });
    await controller.loadItemDbStatus();
    assert.equal(status.message, 'HTTP 503: Statusdienst nicht erreichbar');
})().catch(error => { console.error(error); process.exitCode = 1; });
""")


def test_version_history_retries_failures_caches_success_and_refreshes_after_db_update() -> None:
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/data_source_view.js');
(async () => {
    const panel = { innerHTML: '', querySelector: () => null };
    let requests = 0;
    global.fetch = async () => {
        requests++;
        if (requests === 1) throw new Error('temporary history failure');
        return { json: async () => ({ success: true,
            entries: requests === 2 ? [] : [{ resource_pack_release: 'updated-release' }],
        }) };
    };
    const controller = MCBEDataSourceView.createDataSourceController({
        elements: { itemDbStatusPanel: panel },
    });
    await controller.toggleVersionHistory();
    assert.match(panel.innerHTML, /temporary history failure/);
    await controller.toggleVersionHistory();
    await controller.toggleVersionHistory();
    assert.equal(requests, 2);
    assert.ok(!panel.innerHTML.includes('temporary history failure'));
    await controller.toggleVersionHistory();
    await controller.toggleVersionHistory();
    assert.equal(requests, 2);
    await controller.toggleVersionHistory();
    controller.applyItemDbStatus({ history_count: 1 });
    await controller.toggleVersionHistory();
    assert.equal(requests, 3);
    assert.match(panel.innerHTML, /updated-release/);
    await controller.toggleVersionHistory();
    await controller.toggleVersionHistory();
    assert.equal(requests, 3);

    // A response started before the database update must not repopulate its cache.
    let resolveOld;
    controller.applyItemDbStatus({ history_count: 2 });
    global.fetch = () => new Promise(resolve => { resolveOld = resolve; });
    const oldLoad = controller.toggleVersionHistory();
    controller.applyItemDbStatus({ history_count: 3 });
    global.fetch = async () => ({ json: async () => ({ success: true,
        entries: [{ resource_pack_release: 'current-release' }],
    }) });
    await controller.toggleVersionHistory();
    resolveOld({ json: async () => ({ success: true,
        entries: [{ resource_pack_release: 'outdated-release' }],
    }) });
    await oldLoad;
    assert.match(panel.innerHTML, /current-release/);
    assert.ok(!panel.innerHTML.includes('outdated-release'));
})().catch(error => { console.error(error); process.exitCode = 1; });
""")


def test_catalog_conflicts_override_verified_status_and_escape_diagnostics():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/data_source_view.js');
const status = {status: 'conflict', verification: {verified: true}, message: 'Effekte: IDs 1, 99 <blocked>'};
const html = MCBEDataSourceView.itemDbStatusHtml({itemDbStatus: status});
assert.match(html, /Katalogbereich gesperrt/);
assert.match(html, /IDs 1, 99 &lt;blocked&gt;/);
assert.ok(!html.includes('<blocked>'));
const notice = MCBEDataSourceView.assetDataStatusHtml({itemDbStatus: status});
assert.match(notice, /Katalogbereich gesperrt/);
assert.match(notice, /data-open-db-status/);
""")


def test_frontend_data_source_view_asset_status_html_formats_current_state() -> None:
    run_node(
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

            assert.ok(html.includes("data-open-db-status"));
            assert.ok(!html.includes('status-tile'));
            assert.ok(html.includes("3 ID(s)"));
            assert.ok(html.includes("Item-Daten werden erhalten; DB-Stand prüfen."));
            assert.strictEqual(view.assetDataStatusHtml({
                itemDbStatus: {status: 'ok', verification: {verified: true}},
                iconSummary: {count: 120}, hasCurrentPlayer: true,
            }), '');
            assert.ok(view.assetDataStatusHtml({
                itemDbStatus: {status: 'unavailable', message: '<failed>'},
            }).includes('&lt;failed&gt;'));
            """
        )
    )


def test_frontend_data_source_view_item_db_status_html_formats_history_state() -> None:
    run_node(
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
            assert.ok(html.includes("Versionsverlauf (1)"));
            assert.ok(html.includes("2 Versionseinträge"));
            assert.ok(html.includes("data-db-details"));
            assert.ok(html.includes("C:\\Data\\item_db.json"));
            assert.ok(html.includes("&lt;today&gt;"));
            assert.ok(!html.includes("<today>"));
            assert.ok(!html.includes("abcdef123456"));
            assert.ok(!html.includes("fedcba987654"));
            assert.ok(!html.includes("Wiki"));
            const timestamp = "2026-10-17T14:16:23+00:00";
            const datedHistory = view.itemDbVersionHistoryHtml({visible: true, entries: [{generated_at: timestamp}]});
            assert.ok(datedHistory.includes(context.window.MCBEI18n.formatDate(new Date(timestamp))));
            assert.ok(!datedHistory.includes(timestamp));
            """
        )
    )


def test_frontend_data_source_view_warns_when_item_db_has_no_server_verification() -> None:
    run_node(
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
    run_node(
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
            assert.strictEqual(view.iconStateSummary({ status: "unavailable", message: "HTTP 503: Icon-Dienst nicht erreichbar" }).detail,
                "HTTP 503: Icon-Dienst nicht erreichbar");
            const html = view.assetDataStatusHtml({ iconSummary: { status: "unavailable", message: "<failed>" } });
            assert.ok(html.includes("&lt;failed&gt;"));
            assert.ok(!html.includes("<failed>"));
            """
        )
    )


def test_frontend_data_source_view_keeps_no_wiki_trace_in_the_source_summary() -> None:
    run_node(
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
    run_node(
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
