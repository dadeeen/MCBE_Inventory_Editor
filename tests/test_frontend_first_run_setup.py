import textwrap

from tests.node_runner import run_node


HARNESS = r"""
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
vm.runInNewContext(fs.readFileSync("static/update_db_view.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("static/first_run_setup_view.js", "utf8"), context, { filename: "static/first_run_setup_view.js" });
const view = context.window.MCBEFirstRunSetupView;

function fakeElement() {
    const handlers = {};
    return {
        style: { display: "none" },
        textContent: "",
        disabled: false,
        focused: false,
        classList: { flags: {}, toggle(name, on) { this.flags[name] = Boolean(on); } },
        addEventListener(event, handler) { (handlers[event] = handlers[event] || []).push(handler); },
        fire(event) { (handlers[event] || []).forEach(h => h()); },
        focus() { this.focused = true; },
    };
}

function buildElements() {
    const documentHandlers = {};
    const documentObj = {
        activeElement: null,
        addEventListener(event, handler) { (documentHandlers[event] = documentHandlers[event] || []).push(handler); },
        fire(event, payload = {}) {
            (documentHandlers[event] || []).forEach(handler => handler({
                preventDefault() {},
                ...payload,
            }));
        },
    };
    const rows = {};
    view.TODO_IDS.forEach(id => {
        rows[id] = { item: fakeElement(), mark: fakeElement(), state: fakeElement(), button: fakeElement(),
            details: {...fakeElement(), hidden: true, open: false},
            detailsSummary: {...fakeElement(), style: {display: ''}},
            detailsContent: {...fakeElement(), style: {display: ''}},
        };
    });
    return {
        documentObj,
        overlay: fakeElement(),
        closeButton: {...fakeElement(), style: {display: ''}},
        banner: fakeElement(),
        bannerDetail: fakeElement(),
        bannerButton: fakeElement(),
        rows,
    };
}
"""


def _run_node(source: str) -> None:
    run_node(HARNESS + source)


def test_setup_distinguishes_fallback_success_partial_commit_and_source_failure() -> None:
    _run_node(
        r"""
        vm.runInNewContext(fs.readFileSync("static/data_source_view.js", "utf8"), context);
        const sourceView = context.window.MCBEDataSourceView;
        const fallback = {schema: 1, sections: {effects: {
            status: "checked", locales: {de: {total: 1, official: 0,
                fallbacks: [{id: "freezing", source: "curated"}]}},
        }}};
        const partial = {schema: 1, sections: {effects: {
            status: "blocked", release: "v-old", reason: "Doppelte numerische IDs",
        }}};
        (async () => {
            for (const mode of ["fallback", "partial", "failure"]) {
                const elements = buildElements();
                let pending = true, refreshes = 0, status = {};
                const result = mode === "fallback"
                    ? {success: true, update_committed: true, outcome: "updated"}
                    : mode === "partial"
                        ? {success: false, update_committed: true, outcome: "partial"}
                        : {success: false, outcome: "failed", error: "Keine Änderung übernommen.",
                            summary: {blocked: [{section: "source", reason: "Sprachdatei fehlt"}]}};
                const controller = view.createFirstRunSetupController({
                    elements, isItemDbPending: () => pending, isIconsPending: () => false,
                    getItemDbFeedback: () => sourceView.itemDbSetupFeedback(status),
                    runItemDbUpdate: async () => result,
                    refreshItemDbStatus: async () => {
                        refreshes++;
                        pending = mode !== "fallback";
                        status = {update_quality: mode === "fallback" ? fallback : partial};
                    },
                });
                controller.maybeOpenOnStart();
                await controller.runTodo("item_db");
                const row = elements.rows.item_db;
                assert.equal(refreshes, mode === "failure" ? 0 : 1);
                if (mode === "fallback") {
                    assert.equal(row.mark.textContent, "✓");
                    assert.equal(row.state.textContent, 'Erledigt.');
                    assert.match(row.detailsContent.textContent, /Geprüfte Editor-Namen/);
                    assert.match(row.detailsContent.textContent, /Kein Handlungsbedarf wegen der Namen/);
                    assert.equal(sourceView.itemDbSetupFeedback(status).warnings, false);
                    assert.equal(row.button.style.display, "none");
                    assert.equal(row.item.classList.flags["is-error"], false);
                } else if (mode === "partial") {
                    assert.equal(row.mark.textContent, "!");
                    assert.equal(row.state.textContent, 'Teilweise aktualisiert. Details prüfen.');
                    assert.match(row.detailsContent.textContent, /Doppelte numerische IDs/);
                    assert.match(row.detailsContent.textContent, /v-old/);
                    assert.equal(row.item.classList.flags["is-warning"], true);
                    assert.equal(row.item.classList.flags["is-done"], false);
                    assert.equal(row.item.classList.flags["is-error"], false);
                    assert.equal(row.button.disabled, false);
                } else {
                    assert.equal(row.mark.textContent, "○");
                    assert.equal(row.state.textContent, 'Fehlgeschlagen. Details prüfen.');
                    assert.match(row.detailsContent.textContent, /Sprachdatei fehlt/);
                    assert.equal(row.item.classList.flags["is-error"], true);
                }
                assert.equal(row.details.hidden, false);
                assert.equal(row.details.open, false);
                controller.render();
                assert.equal(row.item.classList.flags["is-done"], mode === "fallback");
            }
        })().catch(error => { console.error(error); process.exitCode = 1; });
        """
    )


def test_frontend_first_run_setup_opens_only_while_a_todo_is_open_and_undismissed() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            function controllerFor({ itemDbPending, iconsPending, dismissed }) {
                const elements = buildElements();
                const controller = view.createFirstRunSetupController({
                    elements,
                    isItemDbPending: () => itemDbPending,
                    isIconsPending: () => iconsPending,
                    loadWorkspace: () => ({ first_run_setup_dismissed: dismissed }),
                });
                return { controller, elements };
            }

            // Fresh install: something to do and never dismissed -> overlay opens.
            let c = controllerFor({ itemDbPending: true, iconsPending: true, dismissed: false });
            assert.strictEqual(c.controller.maybeOpenOnStart(), true);
            assert.strictEqual(c.elements.overlay.style.display, "flex");
            assert.strictEqual(c.elements.banner.style.display, "none", "Banner und Overlay duerfen nie gleichzeitig erscheinen");

            // A stale browser marker from an older /data volume is not authoritative.
            {
                const elements = buildElements();
                const controller = view.createFirstRunSetupController({
                    elements,
                    isItemDbPending: () => true,
                    isIconsPending: () => false,
                    loadWorkspace: () => ({ first_run_item_db_verified: true }),
                });
                assert.strictEqual(controller.maybeOpenOnStart(), true);
                assert.strictEqual(elements.rows.item_db.mark.textContent, "○");
            }

            // Everything already set up -> no overlay, no banner.
            c = controllerFor({ itemDbPending: false, iconsPending: false, dismissed: false });
            assert.strictEqual(c.controller.maybeOpenOnStart(), false);
            assert.strictEqual(c.elements.overlay.style.display, "none");
            assert.strictEqual(c.elements.banner.style.display, "none");

            // A failed status request is unknown, not proof that an update is
            // needed. Fresh browser storage must therefore stay quiet.
            c = controllerFor({ itemDbPending: null, iconsPending: null, dismissed: false });
            assert.strictEqual(c.controller.maybeOpenOnStart(), false);
            assert.strictEqual(c.elements.overlay.style.display, "none");
            assert.strictEqual(c.elements.banner.style.display, "none");
            assert.strictEqual(c.elements.rows.item_db.mark.textContent, "–");
            assert.strictEqual(c.elements.rows.icons.mark.textContent, "–");
            assert.strictEqual(c.elements.rows.item_db.button.disabled, false);
            assert.strictEqual(c.elements.rows.icons.button.disabled, false);
            assert.strictEqual(c.elements.rows.icons.button.textContent, "Status erneut prüfen");

            // If another task is genuinely pending, an unknown row is shown as
            // unavailable, with a status-only retry instead of a download.
            c = controllerFor({ itemDbPending: null, iconsPending: true, dismissed: false });
            assert.strictEqual(c.controller.maybeOpenOnStart(), true);
            assert.strictEqual(c.elements.rows.item_db.mark.textContent, "–");
            assert.ok(c.elements.rows.item_db.state.textContent.includes("Status nicht verfügbar"));
            assert.strictEqual(c.elements.closeButton.textContent, "Später");

            // Dismissed but still open todos -> banner takes over as the way back.
            c = controllerFor({ itemDbPending: false, iconsPending: true, dismissed: true });
            assert.strictEqual(c.controller.maybeOpenOnStart(), false);
            assert.strictEqual(c.elements.overlay.style.display, "none");
            assert.strictEqual(c.elements.banner.style.display, "");
            assert.ok(c.elements.bannerDetail.textContent.includes("Item-Icons"));
            assert.ok(!c.elements.bannerDetail.textContent.includes("Item-Datenbank"));
            assert.ok(!c.elements.bannerDetail.textContent.includes("Item-Daten auf Aktualität"));

            // The banner button reopens the overlay.
            c.elements.bannerButton.fire("click");
            assert.strictEqual(c.elements.overlay.style.display, "flex");
            assert.strictEqual(c.elements.banner.style.display, "none", "Ein offener Dialog muss den Banner ausblenden");

            // Completed icon setup must not retain the fallback warning while
            // only item-data verification is still pending.
            c = controllerFor({ itemDbPending: true, iconsPending: false, dismissed: true });
            c.controller.maybeOpenOnStart();
            assert.ok(c.elements.bannerDetail.textContent.includes("Item-Datenbank"));
            assert.ok(!c.elements.bannerDetail.textContent.includes("Ersatzsymbole"));
            """
        )
    )


def test_setup_details_keep_all_causes_collapsed_and_keyboard_accessible_until_recovery() -> None:
    _run_node(r"""
        vm.runInNewContext(fs.readFileSync('static/data_source_view.js', 'utf8'), context);
        const elements = buildElements(), row = elements.rows.item_db;
        let pending = true, fail = true;
        const causes = Array.from({length: 12}, (_, i) => `Cause ${i}: <script>text only</script>`);
        const controller = view.createFirstRunSetupController({
            elements, isItemDbPending: () => pending, isIconsPending: () => false,
            runItemDbUpdate: async () => fail
                ? {success: false, error: 'Shared source damaged', hint: 'Retry later',
                    summary: {blocked: causes.map(reason => ({section: 'items', reason}))}}
                : {success: true, update_committed: true},
            refreshItemDbStatus: async () => {pending = false;},
        });
        (async () => {
            controller.open();
            await controller.runTodo('item_db');
            assert.equal(row.state.textContent, 'Fehlgeschlagen. Details prüfen.');
            for (const cause of causes) assert.ok(row.detailsContent.textContent.includes(cause));
            assert.match(row.detailsContent.textContent, /Retry later/);
            assert.equal(row.details.hidden, false);
            assert.equal(row.details.open, false);
            row.details.open = true;
            controller.render();
            assert.equal(row.details.open, true, 'Unchanged status must not close the details');
            elements.documentObj.activeElement = row.detailsSummary;
            elements.documentObj.fire('keydown', {key: 'Tab'});
            assert.equal(row.detailsContent.focused, true);
            elements.documentObj.activeElement = row.detailsContent;
            elements.documentObj.fire('keydown', {key: 'Tab'});
            assert.equal(row.button.focused, true);
            elements.documentObj.activeElement = row.detailsSummary;
            elements.documentObj.fire('keydown', {key: 'Tab', shiftKey: true});
            assert.equal(elements.closeButton.focused, true);
            fail = false;
            await controller.runTodo('item_db');
            assert.equal(row.state.textContent, 'Erledigt.');
            assert.equal(row.details.hidden, true);
            assert.equal(row.details.open, false);
            assert.equal(row.detailsContent.textContent, '');
        })().catch(error => {console.error(error); process.exitCode = 1;});
    """)


def test_setup_saved_partial_result_retains_causes_when_status_refresh_fails() -> None:
    _run_node(r"""
        vm.runInNewContext(fs.readFileSync('static/data_source_view.js', 'utf8'), context);
        (async () => {
            for (const partial of [false, true]) {
                const elements = buildElements(), row = elements.rows.item_db;
                let pending = true;
                const controller = view.createFirstRunSetupController({
                    elements, isItemDbPending: () => pending, isIconsPending: () => false,
                    runItemDbUpdate: async () => ({success: !partial, update_committed: true,
                        outcome: partial ? 'partial' : 'updated',
                        summary: {blocked: partial ? [{section: 'effects', reason: 'Effect IDs conflict'}] : []}}),
                    refreshItemDbStatus: async () => {pending = null; throw new Error('Status HTTP 503');},
                });
                await controller.runTodo('item_db');
                assert.equal(row.state.textContent, 'Änderungen gespeichert. Status erneut prüfen.');
                assert.equal(row.button.textContent, 'Status erneut prüfen');
                assert.equal(row.item.classList.flags['is-error'], false);
                assert.equal(row.item.classList.flags['is-warning'], true);
                assert.match(row.detailsContent.textContent, /Status HTTP 503/);
                if (partial) assert.match(row.detailsContent.textContent, /Effect IDs conflict/);
                assert.equal(row.details.open, false);
                await controller.runTodo('item_db');
                assert.equal(row.state.textContent, 'Änderungen gespeichert. Status erneut prüfen.');
                if (partial) assert.match(row.detailsContent.textContent, /Effect IDs conflict/);
            }
        })().catch(error => {console.error(error); process.exitCode = 1;});
    """)


def test_verified_current_receipt_survives_failed_status_only_retries():
    _run_node(r"""
        (async () => {
            const elements = buildElements(), row = elements.rows.item_db;
            let pending = true, writes = 0;
            const controller = view.createFirstRunSetupController({
                elements, isItemDbPending: () => pending, isIconsPending: () => false,
                runItemDbUpdate: async () => {
                    writes++; return {success:true, outcome:'current', update_committed:true, item_db:{verification:{verified:true}}};
                },
                refreshItemDbStatus: async () => {pending = null; throw new Error('Read failed');},
            });
            for (let attempt = 0; attempt < 2; attempt++) {
                await controller.runTodo('item_db');
                assert.equal(writes, 1);
                assert.equal(row.state.textContent, 'Datenbank geprüft. Status erneut prüfen.');
                assert.equal(row.item.classList.flags['is-warning'], true);
                assert.equal(row.item.classList.flags['is-error'], false);
                assert.match(row.detailsContent.textContent, /Read failed/);
            }
        })().catch(error => {console.error(error); process.exitCode = 1;});
    """)


def test_frontend_first_run_setup_accepts_a_successful_no_op_as_verified() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const elements = buildElements();
            let itemDbPending = true;
            let ran = 0;
            let refreshed = 0;
            let workspace = {};

            const controller = view.createFirstRunSetupController({
                elements,
                isItemDbPending: () => itemDbPending,
                isIconsPending: () => false,
                runItemDbUpdate: async () => { ran += 1; return { success: true }; },
                refreshItemDbStatus: async () => { refreshed += 1; itemDbPending = false; },
                loadWorkspace: () => workspace,
                saveWorkspace: patch => { workspace = { ...workspace, ...patch }; },
            });

            const flush = () => new Promise(resolve => setTimeout(resolve, 0));

            (async () => {
                controller.maybeOpenOnStart();
                assert.strictEqual(elements.rows.item_db.mark.textContent, "○");

                // A successful no-op becomes done only after the refreshed
                // server status exposes its artifact-bound verification receipt.
                elements.rows.item_db.button.fire("click");
                await flush();
                assert.strictEqual(ran, 1);
                assert.strictEqual(refreshed, 1);
                assert.strictEqual(workspace.first_run_item_db_verified, undefined);
                assert.strictEqual(elements.rows.item_db.mark.textContent, "✓");
                assert.strictEqual(elements.rows.item_db.item.classList.flags["is-done"], true);
                assert.strictEqual(elements.closeButton.textContent, "Fertig");

                // A finished todo must not run again.
                elements.rows.item_db.button.fire("click");
                await flush();
                assert.strictEqual(ran, 1, "Ein erledigtes Todo darf nicht erneut laufen");
            })().catch(err => { console.error(err); process.exit(1); });
            """
        )
    )


def test_frontend_first_run_setup_reports_a_failed_update_without_ticking_it() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const elements = buildElements();
            const controller = view.createFirstRunSetupController({
                elements,
                isItemDbPending: () => false,
                isIconsPending: () => true,
                // This matches the productive controller contract: failures are
                // returned after their toast/log handling, not thrown.
                runIconsUpdate: async () => ({ success: false, error: "Netzwerk weg" }),
                loadWorkspace: () => ({}),
            });

            controller.maybeOpenOnStart();
            elements.rows.icons.button.fire("click");
            setTimeout(() => {
                assert.strictEqual(elements.rows.icons.mark.textContent, "○");
                assert.equal(elements.rows.icons.state.textContent, 'Fehlgeschlagen. Details prüfen.');
                assert.ok(elements.rows.icons.detailsContent.textContent.includes("Netzwerk weg"));
                assert.strictEqual(elements.rows.icons.item.classList.flags["is-error"], true);
                assert.strictEqual(elements.rows.icons.button.disabled, false, "Ein Fehlschlag muss erneut versuchbar bleiben");
            }, 0);
            """
        )
    )


def test_frontend_first_run_setup_requires_a_confirmed_status_after_update() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const elements = buildElements();
            let itemDbPending = true;
            const controller = view.createFirstRunSetupController({
                elements,
                isItemDbPending: () => itemDbPending,
                isIconsPending: () => false,
                runItemDbUpdate: async () => ({ success: true }),
                refreshItemDbStatus: async () => { itemDbPending = null; },
                loadWorkspace: () => ({}),
            });

            controller.maybeOpenOnStart();
            elements.rows.item_db.button.fire("click");
            setTimeout(() => {
                assert.strictEqual(elements.rows.item_db.mark.textContent, "–");
                assert.equal(elements.rows.item_db.state.textContent, 'Status nicht verfügbar. Bitte erneut prüfen.');
                assert.ok(elements.rows.item_db.detailsContent.textContent.includes("Status konnte jedoch nicht bestätigt werden"));
                assert.strictEqual(elements.rows.item_db.item.classList.flags["is-error"], true);
                assert.strictEqual(elements.closeButton.textContent, "Später");
            }, 0);
            """
        )
    )


def test_frontend_first_run_setup_blocks_updates_in_read_only_mode() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const elements = buildElements();
            let ran = 0;
            const controller = view.createFirstRunSetupController({
                elements,
                isItemDbPending: () => true,
                isIconsPending: () => true,
                runItemDbUpdate: async () => { ran += 1; },
                canWriteAppState: () => false,
                loadWorkspace: () => ({}),
                readOnlyMessage: "Nur ansehen",
            });

            controller.maybeOpenOnStart();
            assert.strictEqual(elements.rows.item_db.button.disabled, true);
            assert.strictEqual(elements.rows.item_db.state.textContent, "Nur ansehen");
            elements.rows.item_db.button.fire("click");
            setTimeout(() => { assert.strictEqual(ran, 0); }, 0);
            """
        )
    )


def test_frontend_first_run_setup_serializes_downloads_and_unlocks_after_failure() -> None:
    _run_node(r"""
        (async () => {
            const elements = buildElements();
            let finish;
            let iconCalls = 0;
            const controller = view.createFirstRunSetupController({
                elements,
                isItemDbPending: () => true,
                isIconsPending: () => true,
                runItemDbUpdate: () => new Promise(resolve => { finish = resolve; }),
                runIconsUpdate: async () => { iconCalls += 1; return { success: false }; },
            });
            const first = controller.runTodo('item_db');
            assert.equal(elements.rows.item_db.button.disabled, true);
            assert.equal(elements.rows.icons.button.disabled, true);
            await controller.runTodo('icons');
            assert.equal(iconCalls, 0);
            finish({ success: false, error: 'offline' });
            await first;
            assert.equal(elements.rows.icons.button.disabled, false);
            await controller.runTodo('icons');
            assert.equal(iconCalls, 1);
        })().catch(error => { console.error(error); process.exitCode = 1; });
    """)


def test_frontend_first_run_setup_remembers_dismissal() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const elements = buildElements();
            let stored = {};
            const controller = view.createFirstRunSetupController({
                elements,
                isItemDbPending: () => true,
                isIconsPending: () => false,
                loadWorkspace: () => stored,
                saveWorkspace: patch => { stored = { ...stored, ...patch }; },
            });

            controller.maybeOpenOnStart();
            assert.strictEqual(elements.overlay.style.display, "flex");

            elements.closeButton.fire("click");
            assert.strictEqual(stored.first_run_setup_dismissed, true);
            assert.strictEqual(elements.overlay.style.display, "none");
            // Closing hands over to the banner in the same tick.
            assert.strictEqual(elements.banner.style.display, "");
            assert.strictEqual(controller.maybeOpenOnStart(), false);

            // Reopening hides the banner, focuses the first pending action and
            // Escape returns to the non-modal state.
            elements.bannerButton.fire("click");
            assert.strictEqual(elements.banner.style.display, "none");
            assert.strictEqual(elements.rows.item_db.button.focused, true);
            elements.documentObj.fire("keydown", { key: "Escape" });
            assert.strictEqual(elements.overlay.style.display, "none");
            assert.strictEqual(elements.banner.style.display, "");
            """
        )
    )


def test_setup_status_retry_preserves_errors_and_never_downloads_in_read_only_mode() -> None:
    _run_node(r"""
        (async () => {
            for (const id of view.TODO_IDS) {
                const elements = buildElements();
                let pending = null, reads = 0, writes = 0, finish;
                const refresh = async () => {
                    reads++;
                    if (reads === 1) throw new Error('HTTP 503: Dienst vorübergehend nicht erreichbar');
                    await new Promise(resolve => { finish = resolve; });
                    pending = false;
                };
                const controller = view.createFirstRunSetupController({
                    elements,
                    isItemDbPending: () => id === 'item_db' ? pending : false,
                    isIconsPending: () => id === 'icons' ? pending : false,
                    refreshItemDbStatus: refresh,
                    refreshIconSources: refresh,
                    runItemDbUpdate: async () => { writes++; },
                    runIconsUpdate: async () => { writes++; },
                    canWriteAppState: () => false,
                });
                controller.open();
                const row = elements.rows[id];
                assert.equal(row.button.disabled, false);
                await controller.runTodo(id);
                assert.equal(row.state.textContent, 'Status nicht verfügbar. Bitte erneut prüfen.');
                assert.match(row.detailsContent.textContent, /HTTP 503: Dienst vorübergehend nicht erreichbar/);
                assert.equal(row.button.disabled, false);
                const retry = controller.runTodo(id);
                assert.equal(row.state.textContent, 'Status wird geprüft…');
                assert.equal(row.button.disabled, true);
                await controller.runTodo(id);
                assert.equal(reads, 2, 'No duplicate read while a retry is pending');
                finish();
                await retry;
                assert.equal(row.state.textContent, 'Erledigt.');
                assert.equal(row.button.style.display, 'none');
                assert.equal(writes, 0, 'Status retries must never download assets');
            }
        })().catch(error => { console.error(error); process.exitCode = 1; });
    """)


def test_setup_status_retry_requires_another_click_before_downloading_missing_icons() -> None:
    _run_node(r"""
        (async () => {
            const elements = buildElements();
            let pending = null, message = 'HTTP 503: Icon-Dienst nicht erreichbar', writes = 0;
            const controller = view.createFirstRunSetupController({
                elements,
                isIconsPending: () => pending,
                getStatusError: () => message,
                refreshIconSources: async () => { message = ''; pending = writes === 0; },
                runIconsUpdate: async () => { writes++; return { success: true }; },
            });
            controller.open();
            const row = elements.rows.icons;
            assert.match(row.detailsContent.textContent, /HTTP 503: Icon-Dienst nicht erreichbar/);
            await controller.runTodo('icons');
            assert.equal(writes, 0);
            assert.equal(row.button.textContent, 'Jetzt laden');
            assert.equal(row.button.disabled, false);
            assert.equal(row.state.textContent, '');
            await controller.runTodo('icons');
            assert.equal(writes, 1);
            assert.equal(row.mark.textContent, '✓');
        })().catch(error => { console.error(error); process.exitCode = 1; });
    """)


def test_setup_uses_current_status_errors_and_clears_old_retry_errors_after_external_refresh() -> None:
    _run_node(r"""
        (async () => {
            const elements = buildElements();
            let pending = null, message = '';
            const controller = view.createFirstRunSetupController({
                elements,
                isIconsPending: () => pending,
                getStatusError: () => message,
                refreshIconSources: async () => { throw new Error('First retry failed'); },
            });
            await controller.runTodo('icons');
            const row = elements.rows.icons;
            assert.match(row.detailsContent.textContent, /First retry failed/);
            // A later automatic refresh from the item-DB update supplies its
            // own error or a valid pending result, replacing the old error.
            message = 'HTTP 429: Bitte 10s warten.';
            controller.render();
            assert.match(row.detailsContent.textContent, /HTTP 429: Bitte 10s warten/);
            assert.ok(!row.detailsContent.textContent.includes('First retry failed'));
            message = '';
            pending = true;
            controller.render();
            assert.equal(row.state.textContent, '');
            assert.equal(row.item.classList.flags['is-error'], false);
            assert.equal(row.details.hidden, true);
            assert.equal(row.detailsContent.textContent, '');
            assert.equal(row.button.textContent, 'Jetzt laden');
        })().catch(error => { console.error(error); process.exitCode = 1; });
    """)
