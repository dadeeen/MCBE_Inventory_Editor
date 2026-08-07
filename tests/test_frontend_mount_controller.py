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


def test_mount_controller_ignores_preview_from_previous_player_context() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/mount_controller.js", "utf8");

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            const context = { window: { confirm: () => false } };
            vm.runInNewContext(code, context, { filename: "static/mount_controller.js" });

            (async () => {
                const requests = { a: deferred(), b: deferred() };
                const state = { world: "world", playerKey: "a", player: { label: "A" } };
                const messages = [];
                const statusPanel = { className: "", textContent: "" };
                const doc = {
                    getElementById: id => id === "mountCreateStatus" ? statusPanel : null,
                    querySelectorAll: () => [],
                };
                const controller = context.window.MCBEMountController.createMountController({
                    doc,
                    apiClient: {
                        previewMountOrThrow: async ({ playerKey }) => requests[playerKey].promise,
                    },
                    getWorldPath: () => state.world,
                    getCurrentPlayerKey: () => state.playerKey,
                    getCurrentPlayer: () => state.player,
                    logStatus: message => messages.push(message),
                    render: { applyMountPanelState: () => {} },
                });

                const loadA = controller.loadPreview();
                state.playerKey = "b";
                state.player = { label: "B" };
                const loadB = controller.loadPreview();
                requests.b.resolve({
                    can_create: true,
                    mount_type: "minecraft:horse",
                    placement_search: { radius: 6 },
                    candidate_positions: [],
                });
                await loadB;
                requests.a.resolve({
                    can_create: true,
                    mount_type: "minecraft:camel",
                    placement_search: { radius: 12 },
                    candidate_positions: [],
                });
                await loadA;

                assert.deepStrictEqual(messages, ["Mount-Vorschau geladen"]);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_mount_controller_reads_every_stat_field_generically_including_temper() -> None:
    """The field list lives only in the view; the controller reads data-stat-key.

    A new field must reach the staged mount without a second registration here.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/mount_controller.js", "utf8");
            const context = { window: { confirm: () => true } };
            vm.runInNewContext(code, context, { filename: "static/mount_controller.js" });

            const input = (key, value, min, max) => ({
                value,
                min,
                max,
                getAttribute: name => (name === "data-stat-key" ? key : null),
                addEventListener: () => {},
            });
            const statFields = [input("health", "24", "15", "30"), input("temper", "77", "0", "99")];
            const doc = {
                getElementById: () => null,
                querySelectorAll: selector => (selector.includes("mount-stat-field") ? statFields : []),
            };

            (async () => {
                const controller = context.window.MCBEMountController.createMountController({
                    doc,
                    apiClient: {
                        previewMountOrThrow: async () => ({
                            can_create: true,
                            mount_type: "minecraft:donkey",
                            mount_label: "Esel",
                            placement_search: { radius: 6 },
                            selected_candidate_id: "east_2",
                            selected_position: { x: 2, y: 64, z: 0 },
                            candidate_positions: [{ id: "east_2", x: 2, y: 64, z: 0, offset: { x: 2, y: 0, z: 0 }, safe_to_place: true }],
                        }),
                    },
                    getWorldPath: () => "world",
                    getCurrentPlayerKey: () => "player",
                    getCurrentPlayer: () => ({ label: "Alex" }),
                    render: { applyMountPanelState: () => {} },
                });

                await controller.loadPreview();
                await controller.queueMount();

                const staged = controller.getPendingMounts();
                assert.strictEqual(staged.length, 1, "Mount wurde nicht vorgemerkt");
                // JSON-Vergleich: Objekte aus der VM haben einen anderen Realm-Prototyp.
                assert.strictEqual(JSON.stringify(staged[0].mountStats), JSON.stringify({ health: 24, temper: 77 }));
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_horse_temper_live_hint_updates_on_input() -> None:
    """Protect the actual listener, not only the matching markup id."""

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/mount_controller.js", "utf8");
            const context = { window: { confirm: () => false } };
            vm.runInNewContext(code, context, { filename: "static/mount_controller.js" });

            const listeners = {};
            const horseTemperInput = {
                value: "40",
                addEventListener: (name, callback) => { listeners[name] = callback; },
            };
            const horseTemperHint = { textContent: "alter Hinweis" };
            const doc = {
                getElementById: id => ({
                    mountHorseTemperInput: horseTemperInput,
                    mountHorseTemperHint: horseTemperHint,
                })[id] || null,
                querySelectorAll: () => [],
            };
            const controller = context.window.MCBEMountController.createMountController({
                doc,
                render: {
                    applyMountPanelState: () => {},
                    temperHintText: value => `Temper ${value}`,
                },
            });

            controller.refresh();
            assert.strictEqual(typeof listeners.input, "function", "Temper-Eingabe hat keinen input-Listener");
            horseTemperInput.value = "95";
            listeners.input();
            assert.strictEqual(horseTemperHint.textContent, "Temper 95", "Temper-Hinweis wurde nicht aktualisiert");
            """
        )
    )


def test_open_disclosures_survive_a_re_render() -> None:
    """A re-render replaces the panel markup, so <details> lose their state.

    Without restoring it, reading the preview notes and then clicking a
    candidate would snap the list shut again.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/mount_controller.js", "utf8");
            const context = { window: { confirm: () => false } };
            vm.runInNewContext(code, context, { filename: "static/mount_controller.js" });

            const node = key => ({ open: false, getAttribute: name => (name === "data-disclosure" ? key : null) });
            const notes = node("preview-notes");
            const ranges = node("profile-ranges");
            // Fremdes <details> ausserhalb des Panels: darf nie angefasst werden.
            const foreign = node("preview-notes");
            const panel = { querySelectorAll: sel => (sel.includes("data-disclosure") ? [notes, ranges] : []) };
            const doc = {
                getElementById: id => (id === "mountsPanel" ? panel : null),
                querySelectorAll: sel => (sel.includes("data-disclosure") ? [notes, ranges, foreign] : []),
            };
            const controller = context.window.MCBEMountController.createMountController({
                doc,
                // Ein echtes Re-Render ersetzt innerHTML; frisches Markup ist zu.
                render: { applyMountPanelState: () => { notes.open = false; ranges.open = false; } },
            });

            notes.open = true;
            controller.refresh();
            assert.strictEqual(notes.open, true, "aufgeklappte Hinweise ueberleben das Re-Render nicht");
            assert.strictEqual(ranges.open, false, "zugeklappter Block wurde faelschlich geoeffnet");

            controller.refresh();
            assert.strictEqual(notes.open, true, "Zustand geht beim zweiten Render verloren");

            notes.open = false;
            controller.refresh();
            assert.strictEqual(notes.open, false, "zugeklappt muss zugeklappt bleiben");

            // Ein gleichnamiges <details> ausserhalb des Panels bleibt unberuehrt.
            notes.open = true;
            foreign.open = false;
            controller.refresh();
            assert.strictEqual(foreign.open, false, "fremdes Aufklapp-Element wurde mitgeoeffnet");
            """
        )
    )


def test_mount_controller_clears_committed_mounts_but_renders_validation_failure() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/mount_controller.js", "utf8");
            const context = { window: { confirm: () => false } };
            vm.runInNewContext(code, context, { filename: "static/mount_controller.js" });

            const models = [];
            const pendingChanges = [];
            const doc = {
                getElementById: () => null,
                querySelectorAll: () => [],
            };
            const controller = context.window.MCBEMountController.createMountController({
                doc,
                onPendingChanged: mounts => pendingChanges.push(mounts),
                render: { applyMountPanelState: model => models.push(model) },
            });
            controller.setPendingMounts([{ id: "mount-1" }], { renderPanel: false });
            controller.finalizePendingMounts(
                [{ mount_type: "minecraft:horse", post_create_validation: { ok: false } }],
                { validationFailed: true }
            );

            assert.strictEqual(controller.getPendingMounts().length, 0);
            assert.strictEqual(pendingChanges.at(-1).length, 0);
            assert.strictEqual(models.at(-1).status, "error");
            assert.ok(models.at(-1).message.includes("Nachvalidierung ist fehlgeschlagen"));
            assert.ok(models.at(-1).message.includes("Nicht erneut speichern"));
            """
        )
    )


def test_mount_controller_finalize_tolerates_count_mismatch_without_throwing() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/mount_controller.js", "utf8");
            const context = { window: { confirm: () => false } };
            vm.runInNewContext(code, context, { filename: "static/mount_controller.js" });

            const models = [];
            const pendingChanges = [];
            const doc = { getElementById: () => null, querySelectorAll: () => [] };
            const controller = context.window.MCBEMountController.createMountController({
                doc,
                onPendingChanged: mounts => pendingChanges.push(mounts),
                render: { applyMountPanelState: model => models.push(model) },
            });
            controller.setPendingMounts([{ id: "mount-1" }, { id: "mount-2" }], { renderPanel: false });

            // The atomic batch is already committed, but the response only echoes one
            // of the two mounts. finalize must NOT throw (that would let the save
            // button re-enable and rewrite the committed batch).
            controller.finalizePendingMounts([
                { mount_type: "minecraft:horse", post_create_validation: { ok: true } },
            ]);

            assert.strictEqual(controller.getPendingMounts().length, 0);
            assert.strictEqual(pendingChanges.at(-1).length, 0);
            assert.strictEqual(models.at(-1).status, "error");
            assert.ok(models.at(-1).message.includes("unvollständig"));
            assert.ok(models.at(-1).message.includes("Nicht erneut speichern"));
            """
        )
    )
