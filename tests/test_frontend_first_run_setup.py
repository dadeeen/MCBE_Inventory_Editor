import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

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
        rows[id] = { item: fakeElement(), mark: fakeElement(), state: fakeElement(), button: fakeElement() };
    });
    return {
        documentObj,
        overlay: fakeElement(),
        closeButton: fakeElement(),
        banner: fakeElement(),
        bannerDetail: fakeElement(),
        bannerButton: fakeElement(),
        rows,
    };
}
"""


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", HARNESS + source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


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
            assert.strictEqual(c.elements.rows.item_db.button.disabled, true);
            assert.strictEqual(c.elements.rows.icons.button.disabled, true);

            // If another task is genuinely pending, an unknown row is shown as
            // unavailable rather than incorrectly checked or actionable.
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

            // The banner button reopens the overlay.
            c.elements.bannerButton.fire("click");
            assert.strictEqual(c.elements.overlay.style.display, "flex");
            assert.strictEqual(c.elements.banner.style.display, "none", "Ein offener Dialog muss den Banner ausblenden");
            """
        )
    )


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
                assert.ok(elements.rows.icons.state.textContent.includes("Netzwerk weg"));
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
                assert.ok(elements.rows.item_db.state.textContent.includes("Status konnte jedoch nicht bestätigt werden"));
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
