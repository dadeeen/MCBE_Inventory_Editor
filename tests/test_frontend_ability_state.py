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


def test_frontend_ability_state_apply_stats_update_clamps_touched_values() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const state = context.window.MCBEAbilityState;
            const result = state.applyStatsUpdate({
                stats: {
                    pos: [0, 70, 0],
                    health: 20,
                    xp_level: 2,
                    xp_progress: 0.1,
                    food_level: 20,
                    food_saturation: 20,
                },
                values: {
                    posX: "1.5",
                    posY: "64.25",
                    posZ: "-3",
                    health: "2048",
                    xpLevel: "99999",
                    xpProgress: "37",
                    foodLevel: "-8",
                    foodSaturation: "7.5",
                },
                touchedFields: ["pos", "health", "xp_level", "xp_progress", "food_level", "food_saturation"],
            });

            assert.strictEqual(result.changed, true);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(result.nextStats)), {
                pos: [1.5, 64.25, -3],
                health: 1024,
                xp_level: 24791,
                xp_progress: 0.37,
                food_level: 0,
                food_saturation: 7.5,
            });
            """
        )
    )


def test_frontend_ability_state_keeps_xp_progress_below_next_level_boundary() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const result = context.window.MCBEAbilityState.applyStatsUpdate({
                stats: { xp_progress: 0 },
                values: { xpProgress: "120" },
                touchedFields: ["xp_progress"],
            });

            assert.strictEqual(result.changed, true);
            assert.ok(Math.abs(result.nextStats.xp_progress - 0.9999) < 1e-12);
            """
        )
    )


def test_frontend_ability_state_apply_stats_update_respects_protected_fields() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const state = context.window.MCBEAbilityState;
            const stats = {
                pos: [0, 70, 0],
                health: 20,
                xp_level: 2,
                food_level: 20,
            };
            const result = state.applyStatsUpdate({
                stats,
                values: {
                    posX: "10",
                    posY: "20",
                    posZ: "30",
                    health: "4",
                    xpLevel: "12",
                    foodLevel: "5",
                },
                touchedFields: new Set(["pos", "health", "xp_level", "food_level"]),
                protectedNbt: {
                    pos_opaque: true,
                    stat_fields_opaque: {
                        health: "Health",
                        food_level: "foodLevel",
                    },
                },
            });

            assert.strictEqual(result.changed, true);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(result.nextStats)), {
                pos: [0, 70, 0],
                health: 20,
                xp_level: 12,
                food_level: 20,
            });
            assert.deepStrictEqual(stats.pos, [0, 70, 0]);
            """
        )
    )


def test_frontend_ability_state_apply_stats_update_ignores_untouched_or_equal_values() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const state = context.window.MCBEAbilityState;
            const result = state.applyStatsUpdate({
                stats: {
                    pos: [0, 70, 0],
                    health: 20,
                    xp_level: 2,
                    xp_progress: 0.1,
                },
                values: {
                    posX: "0",
                    posY: "70",
                    posZ: "0",
                    health: "5",
                    xpLevel: "2",
                    xpProgress: "10",
                },
                touchedFields: ["pos", "xp_level", "xp_progress"],
            });

            assert.strictEqual(result.changed, false);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(result.nextStats)), {
                pos: [0, 70, 0],
                health: 20,
                xp_level: 2,
                xp_progress: 0.1,
            });
            """
        )
    )


def test_frontend_ability_state_updates_location_and_converts_only_on_request() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const state = context.window.MCBEAbilityState;
            const result = state.applyStatsUpdate({
                stats: {
                    pos: [80, 70, -40],
                    dimension_id: 0,
                },
                values: {
                    dimensionId: "1",
                    posX: "80",
                    posY: "70",
                    posZ: "-40",
                },
                touchedFields: ["dimension_id"],
            });
            assert.strictEqual(result.changed, true);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(result.nextStats)), {
                pos: [80, 70, -40],
                dimension_id: 1,
            });

            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.convertPositionBetweenDimensions([80, 70, -40], 0, 1))),
                [10, 70, -5],
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.convertPositionBetweenDimensions([10, 70, -5], 1, 0))),
                [80, 70, -40],
            );
            assert.strictEqual(state.convertPositionBetweenDimensions([1, 70, 1], 0, 2), null);
            assert.strictEqual(state.convertPositionBetweenDimensions([1, 70, 1], null, 1), null);
            """
        )
    )


def test_frontend_ability_state_rejects_incomplete_location_without_defaults() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const result = context.window.MCBEAbilityState.applyStatsUpdate({
                stats: {
                    pos: [80, 70, -40],
                    dimension_id: 0,
                },
                values: {
                    dimensionId: "1",
                    posX: "",
                    posY: "70",
                    posZ: "-40",
                },
                touchedFields: ["dimension_id"],
            });

            assert.strictEqual(result.changed, false);
            assert.strictEqual(result.error, "X, Y und Z müssen vollständig ausgefüllte, endliche Zahlen sein.");
            assert.deepStrictEqual(JSON.parse(JSON.stringify(result.nextStats)), {
                pos: [80, 70, -40],
                dimension_id: 0,
            });

            const invalidDimension = context.window.MCBEAbilityState.applyStatsUpdate({
                stats: {
                    pos: [80, 70, -40],
                    dimension_id: 0,
                },
                values: {
                    dimensionId: "",
                    posX: "10",
                    posY: "70",
                    posZ: "-5",
                },
                touchedFields: ["pos", "dimension_id"],
            });
            assert.strictEqual(invalidDimension.changed, false);
            assert.strictEqual(invalidDimension.error, "Bitte eine unterstützte Spielerdimension auswählen.");
            assert.deepStrictEqual(JSON.parse(JSON.stringify(invalidDimension.nextStats)), {
                pos: [80, 70, -40],
                dimension_id: 0,
            });
            """
        )
    )


def test_frontend_ability_state_dimension_switch_keeps_exact_position() -> None:
    """Ein reiner Dimensionswechsel darf den Spieler nicht verschieben.

    Die Position wird bei jedem Dimensionswechsel atomar mitgeschrieben. Weil
    das Formular auf zwei Nachkommastellen rundet, muss applyStatsUpdate für
    jede unveränderte Achse den exakten Ausgangswert zurückgewinnen -- sonst
    versetzt jeder Wechsel den Spieler um bis zu 5 mm pro Achse.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const state = context.window.MCBEAbilityState;
            const exactPosition = [123.45600128173828, 71.62001037597656, -87.30000305175781];
            const displayed = {
                posX: state.formatPositionForDisplay(exactPosition[0]),
                posY: state.formatPositionForDisplay(exactPosition[1]),
                posZ: state.formatPositionForDisplay(exactPosition[2]),
            };

            // Nur die Dimension angefasst: alle drei Achsen bleiben bitgenau.
            const switched = state.applyStatsUpdate({
                stats: { pos: exactPosition.slice(), dimension_id: 0 },
                values: { ...displayed, dimensionId: "1" },
                touchedFields: ["dimension_id"],
            });
            assert.strictEqual(switched.changed, true);
            assert.strictEqual(switched.nextStats.dimension_id, 1);
            // Array.from: nextStats stammt aus dem vm-Realm, dessen
            // Array-Prototyp deepStrictEqual sonst als Unterschied wertet.
            assert.deepStrictEqual(Array.from(switched.nextStats.pos), exactPosition);

            // Eine bewusst geänderte Achse übernimmt den Nutzerwert, die
            // übrigen behalten trotzdem ihre volle Genauigkeit.
            const moved = state.applyStatsUpdate({
                stats: { pos: exactPosition.slice(), dimension_id: 0 },
                values: { ...displayed, posY: "80", dimensionId: "0" },
                touchedFields: ["pos"],
            });
            assert.strictEqual(moved.changed, true);
            assert.deepStrictEqual(Array.from(moved.nextStats.pos), [exactPosition[0], 80, exactPosition[2]]);
            """
        )
    )


def test_frontend_ability_state_checkbox_change_keeps_exact_speeds() -> None:
    """Eine Checkbox-Änderung darf die Fluggeschwindigkeit nicht kürzen.

    collectAbilitiesFromValues sammelt bei jeder Fähigkeitsänderung den gesamten
    Satz ein, also auch die Tempofelder. Weil deren Anzeige auf vier
    Nachkommastellen kürzt, muss ein unverändert aussehendes Feld auf den exakten
    Ausgangswert zurückfallen -- wie bei den Positionskoordinaten.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_state.js" });

            const state = context.window.MCBEAbilityState;
            const exactFly = 0.1234567;
            const exactWalk = 0.33333333;
            const abilities = { fly_speed: exactFly, walk_speed: exactWalk, mayfly: false };
            const displayed = {
                fly_speed: state.formatAbilitySpeed(exactFly, 0.05),
                walk_speed: state.formatAbilitySpeed(exactWalk, 0.1),
            };
            assert.strictEqual(displayed.fly_speed, "0.1235");

            // Nur die Checkbox angefasst: beide Tempi bleiben bitgenau.
            const toggled = state.collectAbilitiesFromValues(abilities, {}, { mayfly: true }, displayed);
            assert.strictEqual(toggled.mayfly, true);
            assert.strictEqual(toggled.fly_speed, exactFly);
            assert.strictEqual(toggled.walk_speed, exactWalk);

            // Eine echte Tempoänderung wird weiterhin übernommen.
            const retyped = state.collectAbilitiesFromValues(
                abilities,
                {},
                { mayfly: true },
                { fly_speed: "0.2", walk_speed: displayed.walk_speed },
            );
            assert.strictEqual(retyped.fly_speed, 0.2);
            assert.strictEqual(retyped.walk_speed, exactWalk);

            // Ohne Ausgangswert greift weiterhin der Standardwert.
            const fresh = state.collectAbilitiesFromValues({}, {}, { mayfly: true }, { fly_speed: "", walk_speed: "" });
            assert.strictEqual(fresh.fly_speed, 0.05);
            assert.strictEqual(fresh.walk_speed, 0.1);
            """
        )
    )
