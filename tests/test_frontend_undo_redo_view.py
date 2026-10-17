import textwrap

from tests.node_runner import run_node


def test_frontend_undo_redo_view_button_models_and_applier() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_view.js" });

            const view = context.window.MCBEUndoRedoView;
            const model = view.undoRedoButtonModels({
                undoLabels: ["Slot geändert"],
                redoLabels: [],
                undoCount: 1,
                redoCount: 0,
            });
            assert.strictEqual(model.undo.disabled, false);
            assert.strictEqual(model.undo.text, "↩");
            assert.strictEqual(model.undo.title, "Rückgängig: Slot geändert");
            assert.strictEqual(model.redo.disabled, true);
            assert.strictEqual(model.redo.text, "↪");
            assert.strictEqual(model.redo.title, "Wiederholen (Ctrl+Y)");

            const buttons = {
                undoButton: { disabled: true, textContent: "", title: "", dataset: {}, setAttribute(key,value) { this[key]=value; } },
                redoButton: { disabled: false, textContent: "", title: "", dataset: {}, setAttribute(key,value) { this[key]=value; } },
            };
            view.applyUndoRedoButtonModels(buttons, model);
            assert.strictEqual(buttons.undoButton.disabled, false);
            assert.strictEqual(buttons.undoButton.textContent, "↩");
            assert.strictEqual(buttons.undoButton.title, "Rückgängig: Slot geändert · Verfügbare Schritte: 1");
            assert.strictEqual(buttons.redoButton.disabled, true);
            assert.strictEqual(buttons.redoButton.textContent, "↪");
            assert.strictEqual(buttons.redoButton.dataset.historyCount, "");
            view.applyUndoRedoButtonModels(buttons, view.undoRedoButtonModels({undoCount: 120}));
            assert.strictEqual(buttons.undoButton.dataset.historyCount, "99+");
            assert.ok(buttons.undoButton["aria-label"].includes("120"));
            """
        )
    )


def test_frontend_undo_redo_view_panel_html_escapes_labels() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_view.js" });

            const view = context.window.MCBEUndoRedoView;
            assert.ok(view.undoRedoPanelHtml({}).includes("Noch keine Bearbeitung zum Rückgängigmachen."));

            const html = view.undoRedoPanelHtml({
                undoLabels: ["Slot <A>"],
                redoLabels: ["Redo & Test"],
                undoCount: 1,
                redoCount: 1,
            });
            assert.ok(html.includes("Als Nächstes rückgängig:"));
            assert.ok(html.includes("Slot &lt;A&gt;"));
            assert.ok(html.includes("Redo &amp; Test"));
            assert.ok(!html.includes("Slot <A>"));
            const status = { textContent: "", dataset: {} };
            view.applyHistorySaveState(status, {});
            assert.strictEqual(status.dataset.state, "empty");
            view.applyHistorySaveState(status, {hasPlayer: true, isDirty: true});
            assert.strictEqual(status.dataset.state, "dirty");
            view.applyHistorySaveState(status, {hasPlayer: true, isDirty: false});
            assert.strictEqual(status.dataset.state, "clean");
            """
        )
    )
