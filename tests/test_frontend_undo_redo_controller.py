import textwrap

from tests.node_runner import run_node


def test_finished_input_groups_drop_only_their_unchanged_undo_step() -> None:
    run_node(r"""
        const assert = require('assert'), fs = require('fs'), vm = require('vm');
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync('static/undo_redo_controller.js', 'utf8'), context);
        let value = 1;
        const history = context.window.MCBEUndoRedoController.createUndoRedoController({
            takeSnapshot: () => ({ value }), snapshotHash: JSON.stringify,
        });
        const first = {}, second = {};
        history.pushUndo('first', { mergeKey: first });
        value = 2;
        assert.equal(history.finishUndoGroup(first), true);
        history.pushUndo('second', { mergeKey: second });
        value = 3;
        history.pushUndo('second', { mergeKey: second });
        value = 2;
        assert.equal(history.finishUndoGroup(first), true, 'unrelated group cannot remove a step');
        assert.equal(history.state().undoCount, 2);
        assert.equal(history.finishUndoGroup(second), false);
        assert.equal(history.state().undoCount, 1);
        value = history.undo().snapshot.value;
        assert.equal(value, 1);
        value = history.redo().snapshot.value;
        assert.equal(value, 2);
        history.pushUndo('new edit', { mergeKey: second });
        value = 4;
        assert.equal(history.finishUndoGroup(second), true);
        assert.equal(history.undo().snapshot.value, 2);
        history.reset();
        assert.equal(history.finishUndoGroup(second), true);
        assert.equal(history.state().undoCount, 0);
    """)


def test_frontend_undo_redo_controller_pushes_dedupes_and_trims() -> None:
    run_node(
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


def test_reverted_input_group_preserves_full_history_and_accepted_groups_enforce_limit() -> None:
    run_node(r"""
        const assert = require('assert'), fs = require('fs'), vm = require('vm');
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync('static/undo_redo_controller.js', 'utf8'), context);
        for (const finish of ['explicit', 'undo', 'new-action']) {
            let value = 0;
            const history = context.window.MCBEUndoRedoController.createUndoRedoController({
                takeSnapshot: () => ({ value }), snapshotHash: JSON.stringify, maxUndo: 2,
            });
            history.pushUndo('first'); value = 1;
            history.pushUndo('second'); value = 2;
            const group = {};
            history.pushUndo('typing', { mergeKey: group }); value = 3;
            history.pushUndo('typing', { mergeKey: group }); value = 2;
            if (finish === 'explicit') {
                assert.equal(history.finishUndoGroup(group), false);
                assert.equal(history.state().undoCount, 2);
            }
            if (finish === 'new-action') {
                history.pushUndo('third'); value = 4;
                assert.equal(history.state().undoCount, 2);
                value = history.undo().snapshot.value;
                assert.equal(value, 2);
                assert.equal(history.undo().snapshot.value, 1);
                assert.equal(history.undo(), null);
                continue;
            }
            value = history.undo().snapshot.value;
            assert.equal(value, 1);
            value = history.undo().snapshot.value;
            assert.equal(value, 0);
            value = history.redo().snapshot.value;
            value = history.redo().snapshot.value;
            assert.equal(value, 2);
            history.pushUndo('accepted typing', { mergeKey: {} }); value = 5;
            value = history.undo().snapshot.value;
            assert.equal(value, 2);
            value = history.undo().snapshot.value;
            assert.equal(value, 1);
            assert.equal(history.undo(), null, 'accepted groups enforce maxUndo');
        }
    """)


def test_frontend_undo_redo_controller_undo_redo_transitions_and_reset() -> None:
    run_node(
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


def test_frontend_undo_groups_typing_but_separates_other_actions_and_history() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require('assert');
            const fs = require('fs');
            const vm = require('vm');
            const context = {window: {}};
            vm.runInNewContext(fs.readFileSync('static/undo_redo_controller.js', 'utf8'), context);
            let current = {name: '', count: 1};
            const controller = context.window.MCBEUndoRedoController.createUndoRedoController({
                takeSnapshot: () => ({...current}), snapshotHash: JSON.stringify,
            });
            const mergeKey = {};
            for (const name of ['A', 'Ab', 'Abc']) {
                controller.pushUndo(name, {mergeKey});
                current.name = name;
            }
            assert.equal(controller.state().undoCount, 1);
            current = controller.undo().snapshot;
            assert.equal(current.name, '');
            current = controller.redo().snapshot;
            assert.equal(current.name, 'Abc');
            controller.pushUndo('after redo', {mergeKey});
            current.name = 'Abcd';
            assert.equal(controller.state().undoCount, 2);
            controller.pushUndo('different action');
            current.count = 2;
            controller.pushUndo('new typing', {mergeKey});
            current.name = 'Abcde';
            current = controller.undo().snapshot;
            assert.equal(current.name, 'Abcd');
            assert.equal(current.count, 2);
            current = controller.undo().snapshot;
            assert.equal(current.count, 1);
            controller.reset();
            controller.pushUndo('after save', {mergeKey});
            current.name = 'F';
            assert.equal(controller.state().undoCount, 1);
            current = controller.undo().snapshot;
            assert.equal(current.name, 'Abcd');
            """
        )
    )


def test_frontend_undo_redo_app_restores_mount_drafts_and_dirty_state() -> None:
    run_node(
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
    run_node(
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
            vm.runInNewContext(fs.readFileSync("static/undo_redo_view.js", "utf8"), context);
            let blocked = true;
            const button = () => ({dataset: {}, setAttribute(key, value) { this[key] = value; }});
            const buttons = { undo: button(), redo: button(), historyUndo: button(), historyRedo: button() };
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
            assert.strictEqual(buttons.historyUndo.disabled, true);
            assert.strictEqual(buttons.undo.title, "Nur ansehen");
            assert.strictEqual(controller.undo(), false);
            assert.strictEqual(current.inv[0].name, "minecraft:stone");

                blocked = false;
                controller.updateUndoButtons();
                assert.strictEqual(buttons.undo.disabled, false);
                assert.strictEqual(buttons.historyUndo.disabled, false);
                controller.undo();
                assert.strictEqual(JSON.stringify(current.inv), "{}");
            """
        )
    )


def test_frontend_undo_redo_controller_uses_the_translated_default_label() -> None:
    """DEFAULT_LABEL is a function; using it unevaluated leaks its source text."""

    run_node(
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
