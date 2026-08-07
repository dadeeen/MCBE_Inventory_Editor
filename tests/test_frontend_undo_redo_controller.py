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


def test_frontend_undo_redo_controller_pushes_dedupes_and_trims() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_controller.js" });

            let current = { value: 1 };
            const controller = context.window.MCBEUndoRedoController.createUndoRedoController({
                takeSnapshot: () => ({ ...current }),
                snapshotHash: snapshot => JSON.stringify(snapshot),
                maxUndo: 2,
            });

            controller.pushUndo("one");
            controller.pushUndo("duplicate");
            assert.deepStrictEqual(JSON.parse(JSON.stringify(controller.state())), {
                undoLabels: ["one"],
                redoLabels: [],
                undoCount: 1,
                redoCount: 0,
            });

            current = { value: 2 };
            controller.pushUndo("two");
            current = { value: 3 };
            controller.pushUndo("three");

            assert.deepStrictEqual(JSON.parse(JSON.stringify(controller.state())), {
                undoLabels: ["two", "three"],
                redoLabels: [],
                undoCount: 2,
                redoCount: 0,
            });
            """
        )
    )


def test_frontend_undo_redo_controller_undo_redo_transitions_and_reset() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_controller.js" });

            let current = { value: 1 };
            const controller = context.window.MCBEUndoRedoController.createUndoRedoController({
                takeSnapshot: () => ({ ...current }),
                snapshotHash: snapshot => JSON.stringify(snapshot),
                maxUndo: 3,
            });

            controller.pushUndo("before edit");
            current = { value: 2 };
            const undo = controller.undo();
            assert.deepStrictEqual(JSON.parse(JSON.stringify(undo.snapshot)), { value: 1 });
            assert.strictEqual(undo.label, "before edit");
            assert.deepStrictEqual(JSON.parse(JSON.stringify(controller.state())), {
                undoLabels: [],
                redoLabels: ["before edit"],
                undoCount: 0,
                redoCount: 1,
            });

            current = undo.snapshot;
            const redo = controller.redo();
            assert.deepStrictEqual(JSON.parse(JSON.stringify(redo.snapshot)), { value: 2 });
            assert.strictEqual(redo.label, "before edit");
            assert.deepStrictEqual(JSON.parse(JSON.stringify(controller.state())), {
                undoLabels: ["before edit"],
                redoLabels: [],
                undoCount: 1,
                redoCount: 0,
            });

            controller.reset();
            assert.deepStrictEqual(JSON.parse(JSON.stringify(controller.state())), {
                undoLabels: [],
                redoLabels: [],
                undoCount: 0,
                redoCount: 0,
            });
            assert.strictEqual(controller.undo(), null);
            assert.strictEqual(controller.redo(), null);
            """
        )
    )


def test_frontend_undo_redo_app_restores_mount_drafts_and_dirty_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_controller.js", "utf8");
            const context = {
                window: {
                    MCBEUndoRedoView: {
                        undoRedoButtonModels: () => ({ undo: { disabled: true }, redo: { disabled: true } }),
                        applyUndoRedoButtonModels: () => {},
                        undoRedoPanelHtml: () => "",
                    },
                },
            };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_controller.js" });

            let current = { inv: {}, ec: {}, stats: {}, effects: [], abilities: {}, mounts: [] };
            const dirtyStates = [];
            const snapshot = () => JSON.parse(JSON.stringify(current));
            const controller = context.window.MCBEUndoRedoController.createUndoRedoAppController({
                takeSnapshot: snapshot,
                snapshotHash: value => JSON.stringify(value),
                setInventory: value => { current.inv = value; },
                setEnderChestInventory: value => { current.ec = value; },
                setPlayerStats: value => { current.stats = value; },
                setPlayerEffects: value => { current.effects = value; },
                setPlayerAbilities: value => { current.abilities = value; },
                setPendingMounts: value => { current.mounts = value; },
                setDirty: value => dirtyStates.push(value),
            });

            controller.markCleanState();
            controller.pushUndo("Pferd vormerken");
            current.mounts = [{ id: "mount-1", mountType: "minecraft:horse" }];

            controller.undo();
            assert.strictEqual(JSON.stringify(current.mounts), "[]");
            assert.strictEqual(dirtyStates.at(-1), false);

            controller.redo();
            assert.strictEqual(current.mounts.length, 1);
            assert.strictEqual(current.mounts[0].id, "mount-1");
            assert.strictEqual(dirtyStates.at(-1), true);
            """
        )
    )


def test_frontend_undo_redo_app_respects_editing_block() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_controller.js", "utf8");
            const context = {
                window: {
                    MCBEUndoRedoView: {
                        undoRedoButtonModels: state => ({
                            undo: { disabled: state.undoCount === 0, title: "undo" },
                            redo: { disabled: state.redoCount === 0, title: "redo" },
                        }),
                        applyUndoRedoButtonModels: (elements, model) => {
                            elements.undoButton.disabled = model.undo.disabled;
                            elements.undoButton.title = model.undo.title;
                            elements.redoButton.disabled = model.redo.disabled;
                            elements.redoButton.title = model.redo.title;
                        },
                        undoRedoPanelHtml: () => "",
                    },
                },
            };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_controller.js" });

            let current = { inv: {}, ec: {}, stats: {}, effects: [], abilities: {}, mounts: [] };
            let blocked = true;
            const buttons = { undo: {}, redo: {} };
            const snapshot = () => JSON.parse(JSON.stringify(current));
            const controller = context.window.MCBEUndoRedoController.createUndoRedoAppController({
                buttons,
                takeSnapshot: snapshot,
                snapshotHash: value => JSON.stringify(value),
                setInventory: value => { current.inv = value; },
                setEnderChestInventory: value => { current.ec = value; },
                setPlayerStats: value => { current.stats = value; },
                setPlayerEffects: value => { current.effects = value; },
                setPlayerAbilities: value => { current.abilities = value; },
                setPendingMounts: value => { current.mounts = value; },
                editingBlocked: () => blocked,
                getEditingBlockedReason: () => "Nur ansehen",
            });

            controller.pushUndo("Inventar ändern");
            current.inv = { 0: { name: "minecraft:stone" } };
            controller.updateUndoButtons();
            assert.strictEqual(buttons.undo.disabled, true);
            assert.strictEqual(buttons.undo.title, "Nur ansehen");
            assert.strictEqual(controller.undo(), false);
            assert.strictEqual(current.inv[0].name, "minecraft:stone");

                blocked = false;
                controller.updateUndoButtons();
                assert.strictEqual(buttons.undo.disabled, false);
                controller.undo();
                assert.strictEqual(JSON.stringify(current.inv), "{}");
            """
        )
    )


def test_frontend_undo_redo_controller_uses_the_translated_default_label() -> None:
    """DEFAULT_LABEL is a function; using it unevaluated leaks its source text."""

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/undo_redo_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/undo_redo_controller.js" });

            let counter = 0;
            const controller = context.window.MCBEUndoRedoController.createUndoRedoController({
                takeSnapshot: () => ({ value: counter++ }),
                snapshotHash: value => JSON.stringify(value),
            });

            // "node -e" cannot carry non-ASCII through the Windows console
            // codepage, so the expected label stays escaped.
            const expected = "\u00c4nderung";

            // Arrays cross the vm realm boundary, so compare scalars only.
            const state = controller.pushUndo();
            assert.strictEqual(state.undoLabels.length, 1);
            assert.strictEqual(state.undoLabels[0], expected);

            controller.pushUndo();
            const undone = controller.undo();
            assert.strictEqual(undone.label, expected);
            assert.strictEqual(undone.state.redoLabels[0], expected);

            const redone = controller.redo();
            assert.strictEqual(redone.label, expected);
            """
        )
    )
