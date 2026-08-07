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


def test_frontend_undo_redo_view_button_models_and_applier() -> None:
    _run_node(
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
            assert.strictEqual(model.undo.text, "↩ 1");
            assert.strictEqual(model.undo.title, "Rückgängig: Slot geändert");
            assert.strictEqual(model.redo.disabled, true);
            assert.strictEqual(model.redo.text, "↪");
            assert.strictEqual(model.redo.title, "Wiederholen (Ctrl+Y)");

            const buttons = {
                undoButton: { disabled: true, textContent: "", title: "" },
                redoButton: { disabled: false, textContent: "", title: "" },
            };
            view.applyUndoRedoButtonModels(buttons, model);
            assert.strictEqual(buttons.undoButton.disabled, false);
            assert.strictEqual(buttons.undoButton.textContent, "↩ 1");
            assert.strictEqual(buttons.undoButton.title, "Rückgängig: Slot geändert");
            assert.strictEqual(buttons.redoButton.disabled, true);
            assert.strictEqual(buttons.redoButton.textContent, "↪");
            """
        )
    )


def test_frontend_undo_redo_view_panel_html_escapes_labels() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_view.js" });

            const view = context.window.MCBEUndoRedoView;
            assert.ok(view.undoRedoPanelHtml({}).includes("Noch kein Undo/Redo-Stapel vorhanden."));

            const html = view.undoRedoPanelHtml({
                undoLabels: ["Slot <A>"],
                redoLabels: ["Redo & Test"],
                undoCount: 1,
                redoCount: 1,
            });
            assert.ok(html.includes("Rückgängig möglich (1)"));
            assert.ok(html.includes("Slot &lt;A&gt;"));
            assert.ok(html.includes("Redo &amp; Test"));
            assert.ok(!html.includes("Slot <A>"));
            """
        )
    )
