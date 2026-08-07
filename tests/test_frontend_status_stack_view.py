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


def test_frontend_status_stack_view_builds_models_and_escapes_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const statusStackCode = fs.readFileSync("static/status_stack_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(statusStackCode, context, { filename: "static/status_stack_view.js" });

            const view = context.window.MCBEStatusStackView;
            const warningModel = view.statusStackModel({
                visibleNotices: [
                    { time: "12:00", type: "warning", message: "Achtung <prüfen>", active: true },
                    { time: "12:01", type: "success", message: "Gespeichert", active: false },
                ],
                statusText: "Fallback wird ignoriert",
                statusClassName: "save-status success",
                isDirty: true,
            });
            assert.strictEqual(warningModel.countText, "1");
            assert.strictEqual(warningModel.hasWarning, true);
            assert.strictEqual(warningModel.severity, "warning");
            assert.strictEqual(warningModel.headline, "Hinweise");
            assert.strictEqual(warningModel.summary, "Achtung <prüfen>");

            const warningWithNewSuccess = view.statusStackModel({
                visibleNotices: [
                    { time: "12:02", type: "success", message: "Icon-Update erfolgreich.", active: false },
                    { time: "12:01", type: "warning", message: "Neustart erforderlich.", active: true },
                ],
            });
            assert.strictEqual(warningWithNewSuccess.severity, "warning");
            assert.strictEqual(warningWithNewSuccess.summary, "Neustart erforderlich.");
            assert.strictEqual(warningWithNewSuccess.liveMessage, "Erfolgreich: Icon-Update erfolgreich.");

            const warningHtml = view.statusStackPanelHtml(warningModel.entries);
            assert.ok(warningHtml.includes("status-stack-entry save-status warning"));
            assert.ok(warningHtml.includes("status-stack-kind"));
            assert.ok(warningHtml.includes("Warnung"));
            assert.ok(warningHtml.includes("12:00"));
            assert.ok(warningHtml.includes("Achtung &lt;prüfen&gt;"));
            assert.ok(!warningHtml.includes("Achtung <prüfen>"));

            const resolvedModel = view.statusStackModel({
                visibleNotices: [
                    { time: "12:02", type: "success", message: "Update erfolgreich.", active: false },
                    { time: "12:01", type: "warning", message: "Historischer Hinweis", active: false },
                ],
            });
            assert.strictEqual(resolvedModel.countText, "✓");
            assert.strictEqual(resolvedModel.severity, "success");
            assert.strictEqual(resolvedModel.headline, "Status");
            assert.strictEqual(resolvedModel.summary, "Update erfolgreich.");

            const errorModel = view.statusStackModel({
                visibleNotices: [
                    { time: "12:03", type: "warning", message: "Warnung", active: true },
                    { time: "12:02", type: "error", message: "Fehler", active: true },
                ],
            });
            assert.strictEqual(errorModel.countText, "2");
            assert.strictEqual(errorModel.severity, "error");
            assert.strictEqual(errorModel.headline, "Fehler");
            assert.strictEqual(errorModel.summary, "Fehler");

            const fallbackModel = view.statusStackModel({
                visibleNotices: [],
                statusText: "Bereit",
                statusClassName: "save-status success",
                isDirty: false,
            });
            assert.strictEqual(fallbackModel.countText, "✓");
            assert.strictEqual(fallbackModel.severity, "success");
            assert.strictEqual(fallbackModel.headline, "Status");
            assert.strictEqual(fallbackModel.summary, "Bereit");
            assert.strictEqual(
                JSON.stringify(fallbackModel.entries),
                JSON.stringify([{ time: "", type: "success", message: "Bereit", active: false }]),
            );

            const hiddenTransientModel = view.statusStackModel({
                visibleNotices: [],
                statusText: "Ungespeicherte Änderungen vorhanden",
                statusClassName: "save-status warning",
                isDirty: false,
                isTransientDirtyStatusText: text => text === "Ungespeicherte Änderungen vorhanden",
            });
            assert.strictEqual(hiddenTransientModel.countText, "i");
            assert.strictEqual(hiddenTransientModel.summary, "Keine Hinweise");
            assert.strictEqual(view.statusStackPanelHtml(hiddenTransientModel.entries), '<div class="status-stack-entry save-status">Keine Hinweise</div>');
            """
        )
    )


def test_frontend_status_stack_view_applies_dom_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const statusStackCode = fs.readFileSync("static/status_stack_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(statusStackCode, context, { filename: "static/status_stack_view.js" });

            const toggles = [];
            const attributes = [];
            const elements = {
                button: {
                    classList: { toggle(name, enabled) { toggles.push([name, enabled]); } },
                    setAttribute(name, value) { attributes.push([name, value]); },
                },
                count: { textContent: "" },
                headline: { textContent: "" },
                summary: { textContent: "" },
                panel: { innerHTML: "" },
                live: { textContent: "" },
            };
            const model = {
                countText: "1",
                headline: "Hinweise",
                summary: "Achtung <prüfen>",
                hasWarning: true,
                severity: "warning",
                ariaLabel: "Hinweise: Achtung prüfen. 1 offen.",
                liveMessage: "Warnung: Achtung prüfen.",
                entries: [{ time: "12:00", type: "warning", message: "Achtung <prüfen>", active: true }],
            };

            const view = context.window.MCBEStatusStackView;
            view.applyStatusStackModel(elements, model);

            assert.strictEqual(elements.count.textContent, "1");
            assert.strictEqual(elements.headline.textContent, "Hinweise");
            assert.strictEqual(elements.summary.textContent, "Achtung <prüfen>");
            assert.deepStrictEqual(toggles, [
                ["info", false],
                ["success", false],
                ["running", false],
                ["warning", true],
                ["error", false],
            ]);
            assert.deepStrictEqual(attributes, [["aria-label", "Hinweise: Achtung prüfen. 1 offen."]]);
            assert.strictEqual(elements.live.textContent, "Warnung: Achtung prüfen.");
            assert.ok(elements.panel.innerHTML.includes("status-stack-entry save-status warning"));
            assert.ok(elements.panel.innerHTML.includes("Achtung &lt;prüfen&gt;"));
            assert.ok(!elements.panel.innerHTML.includes("Achtung <prüfen>"));
            """
        )
    )


def test_clearing_status_updates_header_without_reannouncing_history() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            for (const file of ["static/html_utils.js", "static/status_store.js", "static/status_stack_view.js", "static/session_log.js"]) {
                vm.runInNewContext(fs.readFileSync(file, "utf8"), context, { filename: file });
            }

            let statusText = "";
            const statusMsg = {
                className: "save-status",
                get textContent() { return statusText; },
                set innerText(value) { statusText = value; },
            };
            const live = { textContent: "" };
            const elements = {
                statusMsg,
                statusStackButton: { classList: { toggle() {} }, setAttribute() {} },
                statusStackPanel: { innerHTML: "" },
                statusStackCount: { textContent: "" },
                statusStackHeadline: { textContent: "" },
                statusStackSummary: { textContent: "" },
                statusStackLive: live,
            };
            const store = context.window.MCBEStatusStore.createStatusStore();
            const controller = context.window.MCBESessionLog.createStatusSessionController({
                elements,
                statusNoticeStore: store,
                getIsDirty: () => true,
            });

            controller.logStatus("Ungespeicherte Änderungen vorhanden", "warning", { key: "dirty", active: true });
            controller.logStatus("Icon-Update erfolgreich.", "success", { key: "icons", active: false });
            assert.strictEqual(live.textContent, "Erfolgreich: Icon-Update erfolgreich.");
            assert.strictEqual(controller.clearStatus("dirty"), true);
            assert.strictEqual(live.textContent, "", "Auflösung kündigt keinen alten Verlaufseintrag erneut an");
            assert.strictEqual(elements.statusStackSummary.textContent, "Icon-Update erfolgreich.");
            assert.strictEqual(elements.statusStackCount.textContent, "✓");
            assert.strictEqual(controller.clearStatus("icons"), true);
            assert.strictEqual(statusText, "");
            assert.strictEqual(elements.statusStackSummary.textContent, "Keine Hinweise");
            """
        )
    )
