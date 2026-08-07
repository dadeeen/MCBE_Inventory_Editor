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


def test_discard_controls_have_unique_explicit_ids() -> None:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'id="btnDiscardChanges"' not in html
    assert html.count('id="btnDirtyDiscardChanges"') == 1
    assert html.count('id="btnSafeEditDiscardChanges"') == 1
    assert html.count('data-discard-changes="true"') == 2


def test_frontend_save_workflow_view_empty_states_are_owned_by_view_module() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_workflow_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_workflow_view.js" });

            const view = context.window.MCBESaveWorkflowView;
            assert.strictEqual(
                view.emptyWorkflowHtml(),
                '<div class="no-backups">Lade zuerst einen bearbeitbaren Spieler. Danach zeigt dieser Schritt exakt, welche Bereiche geschrieben werden.</div>',
            );
            assert.strictEqual(
                view.emptyDecisionLogHtml(),
                '<div class="no-backups">Noch kein Spieler geladen. Es gibt deshalb keinen Schreibplan.</div>',
            );
            assert.strictEqual(
                view.decisionLogHtml([]),
                '<div class="no-backups">Keine Entscheidungsdetails verfügbar.</div>',
            );
            """
        )
    )


def test_frontend_save_workflow_view_decision_log_html_escapes_rows() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_workflow_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_workflow_view.js" });

            const view = context.window.MCBESaveWorkflowView;
            const html = view.decisionLogHtml([{
                severity: 'warning" onclick="bad',
                title: "Titel <A>",
                text: "Text & Details",
            }]);

            assert.ok(html.includes("decision-log-row warning&quot; onclick=&quot;bad"));
            assert.ok(html.includes("Titel &lt;A&gt;"));
            assert.ok(html.includes("Text &amp; Details"));
            assert.ok(!html.includes("Titel <A>"));
            """
        )
    )


def test_frontend_save_workflow_view_applies_panel_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_workflow_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_workflow_view.js" });

            const view = context.window.MCBESaveWorkflowView;
            const elements = {
                summary: { innerHTML: "" },
                decisionLog: { innerHTML: "" },
                copyButton: { disabled: false },
                runButton: { disabled: false },
            };
            view.applyWorkflowPanelModel(elements, {
                summaryHtml: "<section>Summary</section>",
                decisionLogHtml: "<div>Log</div>",
                copyDisabled: true,
                runDisabled: true,
            });

            assert.strictEqual(elements.summary.innerHTML, "<section>Summary</section>");
            assert.strictEqual(elements.decisionLog.innerHTML, "<div>Log</div>");
            assert.strictEqual(elements.copyButton.disabled, true);
            assert.strictEqual(elements.runButton.disabled, true);
            """
        )
    )


def test_frontend_save_workflow_view_normalizes_legacy_discard_controls() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_workflow_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_workflow_view.js" });

            const view = context.window.MCBESaveWorkflowView;
            function button(id) {
                return {
                    id,
                    attributes: {},
                    setAttribute(name, value) { this.attributes[name] = value; },
                };
            }
            const legacyDirty = button("btnDiscardChanges");
            const legacySafeEdit = button("btnDiscardChanges");
            const explicit = button("btnExplicitDiscard");
            const doc = {
                getElementById(id) {
                    return {
                        btnDirtySave: button("btnDirtySave"),
                        btnDirtyReview: button("btnDirtyReview"),
                        btnShowSavePreview: button("btnShowSavePreview"),
                        btnDirtyDiscardChanges: legacyDirty.id === "btnDirtyDiscardChanges" ? legacyDirty : null,
                        btnSafeEditDiscardChanges: legacySafeEdit.id === "btnSafeEditDiscardChanges" ? legacySafeEdit : null,
                    }[id] || null;
                },
                querySelectorAll(selector) {
                    if (selector === "[data-discard-changes]") return [explicit];
                    if (selector === "#btnDiscardChanges") return [legacyDirty, legacySafeEdit];
                    return [];
                },
            };

            const elements = view.collectDirtyActionElements(doc);
            assert.strictEqual(elements.discardButtons.length, 3);
            assert.strictEqual(elements.discardButtons[0], explicit);
            assert.strictEqual(elements.discardButtons[1], legacyDirty);
            assert.strictEqual(elements.discardButtons[2], legacySafeEdit);
            assert.strictEqual(legacyDirty.id, "btnDirtyDiscardChanges");
            assert.strictEqual(legacySafeEdit.id, "btnSafeEditDiscardChanges");
            assert.strictEqual(explicit.id, "btnExplicitDiscard");
            for (const control of elements.discardButtons) {
                assert.strictEqual(control.attributes["data-discard-changes"], "true");
            }
        """
        )
    )


def test_frontend_save_workflow_view_only_discards_after_successful_reload() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_workflow_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_workflow_view.js" });

            (async () => {
                const view = context.window.MCBESaveWorkflowView;
                const events = [];
                let reloadResult = false;
                const controller = view.createDirtyActionsController({
                    getCurrentPlayerKey: () => "local",
                    loadPlayer: async (playerKey, skipDirtyCheck) => {
                        events.push(["reload", playerKey, skipDirtyCheck]);
                        return reloadResult;
                    },
                    showConfirmDialog: async () => true,
                    showToast: (message, type) => events.push(["toast", message, type]),
                });

                assert.strictEqual(await controller.discardChanges(), false);
                assert.deepStrictEqual(events, [
                    ["reload", "local", true],
                    [
                        "toast",
                        "Änderungen konnten nicht verworfen werden. Der gespeicherte Spielerstand wurde nicht neu geladen.",
                        "error",
                    ],
                ]);

                events.length = 0;
                reloadResult = true;
                assert.strictEqual(await controller.discardChanges(), true);
                assert.deepStrictEqual(events, [
                    ["reload", "local", true],
                    [
                        "toast",
                        "Änderungen verworfen. Zuletzt gespeicherter Stand wurde neu geladen.",
                        "success",
                    ],
                ]);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )
