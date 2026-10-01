import textwrap

from tests.node_runner import run_node


def test_frontend_ability_view_movement_lock_note_model_and_applier() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
            const element = { hidden: true, textContent: "" };

            const modifiers = view.movementLockNoteModel({ reason: "modifiers" });
            assert.strictEqual(modifiers.hidden, false);
            assert.match(modifiers.text, /Modifikatoren, etwa durch Sprinten/);
            view.applyMovementLockNoteModel(element, modifiers);
            assert.strictEqual(element.hidden, false);
            assert.strictEqual(element.textContent, modifiers.text);

            assert.match(view.movementLockNoteModel({ reason: "missing" }).text, /kein Attribut minecraft:movement/);
            assert.match(view.movementLockNoteModel({ reason: "value" }).text, /unerwarteten Aufbau/);

            // Ein insgesamt geschützter abilities-Tag erklärt sich über die
            // Feld-Titel; der Hinweis zur Laufgeschwindigkeit bleibt dann aus.
            for (const model of [
                view.movementLockNoteModel({ reason: "" }),
                view.movementLockNoteModel({ abilitiesOpaque: true, reason: "modifiers" }),
            ]) {
                view.applyMovementLockNoteModel(element, model);
                assert.strictEqual(element.hidden, true);
                assert.strictEqual(element.textContent, "");
            }
            assert.strictEqual(view.abilityRiskNoteModel, undefined);
            """
        )
    )


def test_frontend_ability_view_control_models_and_applier() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
            const models = view.abilityControlModels({
                protectedFields: { fly_speed: "flySpeedOverride" },
                movementLock: "modifiers",
            });
            assert.deepStrictEqual(Array.from(models, model => model.id), ["abMovementSpeed", "abWalkSpeed", "abFlySpeed", "abVerticalFlySpeed"]);
            const byId = Object.fromEntries(models.map(model => [model.id, model]));

            assert.strictEqual(byId.abWalkSpeed.disabled, false);
            assert.strictEqual(byId.abWalkSpeed.title, "");
            assert.strictEqual(byId.abFlySpeed.disabled, true);
            assert.strictEqual(byId.abFlySpeed.title, "flySpeedOverride-Tag hat einen unerwarteten NBT-Typ und wird geschützt erhalten.");
            assert.strictEqual(byId.abMovementSpeed.disabled, true);
            assert.match(byId.abMovementSpeed.title, /Modifikatoren/);

            const elements = {};
            for (const model of models) elements[model.id] = { disabled: false, title: "stale" };
            const doc = {
                getElementById(id) {
                    return elements[id] || null;
                },
            };
            view.applyAbilityControlModels(doc, models);
            assert.strictEqual(elements.abVerticalFlySpeed.disabled, false);
            assert.strictEqual(elements.abVerticalFlySpeed.title, "");
            assert.strictEqual(elements.abFlySpeed.disabled, true);
            assert.strictEqual(elements.abFlySpeed.title, "flySpeedOverride-Tag hat einen unerwarteten NBT-Typ und wird geschützt erhalten.");

            const unlocked = view.abilityControlModels({});
            assert.strictEqual(unlocked.every(model => model.disabled === false), true);

            const disabledModels = view.abilityControlModels({ disabled: true });
            assert.strictEqual(disabledModels.every(model => model.disabled === true), true);
            assert.strictEqual(
                disabledModels[0].title,
                "abilities-Tag hat einen unbekannten NBT-Typ und wird geschützt erhalten.",
            );
            """
        )
    )


def test_frontend_ability_view_form_model_and_applier() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
            const model = view.abilityFormModel({
                movementSpeedValue: "0.2",
                walkSpeedValue: "0.12",
                flySpeedValue: "0.07",
                verticalFlySpeedValue: "3",
            });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(model)), {
                values: {
                    abMovementSpeed: "0.2",
                    abWalkSpeed: "0.12",
                    abFlySpeed: "0.07",
                    abVerticalFlySpeed: "3",
                },
            });

            const elements = {};
            for (const id of Object.keys(model.values)) elements[id] = { value: "" };
            const doc = {
                getElementById(id) {
                    return elements[id] || null;
                },
            };
            view.applyAbilityFormModel(doc, model);
            assert.strictEqual(elements.abMovementSpeed.value, "0.2");
            assert.strictEqual(elements.abWalkSpeed.value, "0.12");
            assert.strictEqual(elements.abFlySpeed.value, "0.07");
            assert.strictEqual(elements.abVerticalFlySpeed.value, "3");

            assert.strictEqual(view.abilityFormModel({}).values.abFlySpeed, "");
            """
        )
    )


def test_frontend_ability_view_reads_speed_values() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
            const elements = {
                abMovementSpeed: { value: "0.2" },
                abWalkSpeed: { value: "0.14" },
                abFlySpeed: { value: "0.08" },
                abVerticalFlySpeed: { value: "2.5" },
            };
            const doc = {
                getElementById(id) {
                    return elements[id] || null;
                },
            };

            assert.deepStrictEqual(JSON.parse(JSON.stringify(view.readAbilitySpeedValues(doc))), {
                movement_speed: "0.2",
                walk_speed: "0.14",
                fly_speed: "0.08",
                vertical_fly_speed: "2.5",
            });

            const missingDoc = { getElementById() { return null; } };
            assert.strictEqual(view.readAbilitySpeedValues(missingDoc).fly_speed, undefined);
            assert.strictEqual(view.readAbilityFormValues, undefined);
            """
        )
    )


def test_frontend_ability_view_stat_protection_models_and_applier() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
            const models = view.statProtectionControlModels({
                posOpaque: true,
                dimensionMissing: true,
                protectedFields: {
                    health: "HealthOverride",
                    xp_progress: "XPProgressOverride",
                },
            });
            const posX = models.find(model => model.key === "posX");
            const dimension = models.find(model => model.key === "dimensionId");
            const health = models.find(model => model.key === "health");
            const xpLevel = models.find(model => model.key === "xpLevel");
            const xpProgress = models.find(model => model.key === "xpProgress");

            assert.strictEqual(posX.disabled, true);
            assert.strictEqual(posX.title, "Pos-Tag hat einen unbekannten NBT-Typ und wird geschützt erhalten.");
            assert.strictEqual(dimension.disabled, true);
            assert.strictEqual(dimension.title, "Ein Dimensionswechsel benötigt eine sicher editierbare Spielerposition.");
            assert.strictEqual(health.disabled, true);
            assert.strictEqual(health.title, "HealthOverride-Tag hat einen unerwarteten NBT-Typ und wird geschützt erhalten.");
            assert.strictEqual(xpLevel.disabled, false);
            assert.strictEqual(xpLevel.title, "");
            assert.strictEqual(xpProgress.disabled, true);
            assert.strictEqual(xpProgress.title, "XPProgressOverride-Tag hat einen unerwarteten NBT-Typ und wird geschützt erhalten.");

            const elements = {};
            for (const model of models) elements[model.key] = { disabled: false, title: "stale" };
            view.applyStatProtectionControlModels(elements, models);
            assert.strictEqual(elements.posX.disabled, true);
            assert.strictEqual(elements.posX.title, "Pos-Tag hat einen unbekannten NBT-Typ und wird geschützt erhalten.");
            assert.strictEqual(elements.health.disabled, true);
            assert.strictEqual(elements.health.title, "HealthOverride-Tag hat einen unerwarteten NBT-Typ und wird geschützt erhalten.");
            assert.strictEqual(elements.xpLevel.disabled, false);
            assert.strictEqual(elements.xpLevel.title, "");
            """
        )
    )


def test_frontend_ability_view_stats_form_model_and_applier() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            // Ladereihenfolge wie in index.html: ability_state.js besitzt die
            // Positions-Rundungsregel, ability_view.js verwendet sie.
            vm.runInNewContext(fs.readFileSync("static/ability_state.js", "utf8"), context, { filename: "static/ability_state.js" });
            vm.runInNewContext(fs.readFileSync("static/ability_view.js", "utf8"), context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
                const model = view.statsFormModel({
                    pos: [1.234, 70, -3.25],
                    dimension_id: 1,
                health: 19.75,
                gamemode: 1,
                xp_level: 42,
                xp_progress: 0.56,
                food_level: 18,
                food_saturation: 7.25,
            });

            assert.strictEqual(model.values.dimensionId, "1");
            // Anzeige rundet auf zwei Nachkommastellen; den exakten Wert stellt
            // applyStatsUpdate für unveränderte Achsen wieder her.
            assert.strictEqual(model.values.posX, "1.23");
            assert.strictEqual(model.values.posY, "70.00");
            assert.strictEqual(model.values.posZ, "-3.25");
            assert.strictEqual(model.values.health, "19.8");
            assert.strictEqual(model.values.xpLevel, 42);
            assert.strictEqual(model.values.xpProgress, "56");
            assert.strictEqual(model.values.foodLevel, 18);
            assert.strictEqual(model.values.foodSaturation, "7.3");
            assert.strictEqual(model.gamemode.value, "Kreativ (Creative) · NBT-Wert 1");
            assert.strictEqual(model.gamemode.readOnly, true);

            const almostNextLevel = view.statsFormModel({
                pos: [0, 0, 0],
                health: 20,
                gamemode: 0,
                xp_level: 42,
                xp_progress: 0.9999,
                food_level: 20,
                food_saturation: 5,
            });
            assert.strictEqual(almostNextLevel.values.xpProgress, "99.99");
            assert.strictEqual(almostNextLevel.values.dimensionId, "");

            const elements = {};
            for (const key of Object.keys(model.values)) elements[key] = { value: "" };
            elements.gamemode = { value: "", readOnly: false, title: "" };
            view.applyStatsFormModel(elements, model);

            assert.strictEqual(elements.dimensionId.value, "1");
            assert.strictEqual(elements.posX.value, "1.23");
            assert.strictEqual(elements.health.value, "19.8");
            assert.strictEqual(elements.xpLevel.value, 42);
            assert.strictEqual(elements.gamemode.value, "Kreativ (Creative) · NBT-Wert 1");
            assert.strictEqual(elements.gamemode.readOnly, true);
            assert.strictEqual(
                elements.gamemode.title,
                "Read-only: Dieser Player-Gamemode wird nur angezeigt. Der Editor schreibt ihn nicht; Welt-/Servermodus kann abweichen.",
            );

            const unknown = view.gamemodeDisplayModel("future");
            assert.strictEqual(unknown.value, "Unbekannter oder serverspezifischer Wert · NBT-Wert ?");
            """
        )
    )


def test_frontend_ability_view_reads_stats_form_values() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
            const values = view.readStatsFormValues({
                dimensionId: { value: "1" },
                posX: { value: "1.0" },
                posY: { value: "70.0" },
                posZ: { value: "-2.0" },
                health: { value: "18.5" },
                xpLevel: { value: "12" },
                xpProgress: { value: "30" },
                foodLevel: { value: "19" },
                foodSaturation: { value: "4.5" },
            });

            assert.strictEqual(values.dimensionId, "1");
            assert.strictEqual(values.posX, "1.0");
            assert.strictEqual(values.posY, "70.0");
            assert.strictEqual(values.posZ, "-2.0");
            assert.strictEqual(values.health, "18.5");
            assert.strictEqual(values.xpLevel, "12");
            assert.strictEqual(values.xpProgress, "30");
            assert.strictEqual(values.foodLevel, "19");
            assert.strictEqual(values.foodSaturation, "4.5");
            assert.strictEqual(view.readStatsFormValues({}).health, undefined);
            """
        )
    )


def test_frontend_ability_view_location_conversion_models_are_explicit() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/ability_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/ability_view.js" });

            const view = context.window.MCBEAbilityView;
            const toNether = view.locationConversionModel({
                sourceDimension: 0,
                targetDimension: "1",
            });
            assert.strictEqual(toNether.disabled, false);
            assert.strictEqual(toNether.label, "Für Nether umrechnen (X/Z ÷ 8)");

            const toEnd = view.locationConversionModel({
                sourceDimension: 0,
                targetDimension: "2",
            });
            assert.strictEqual(toEnd.disabled, true);
            const invalidPosition = view.locationConversionModel({
                sourceDimension: 0,
                targetDimension: "1",
                positionInvalid: true,
            });
            assert.strictEqual(invalidPosition.disabled, true);
            assert.match(invalidPosition.title, /X, Y und Z/);
            assert.strictEqual(view.locationConversionModel({
                sourceDimension: null,
                targetDimension: "1",
            }).disabled, true);

            const button = { disabled: false, textContent: "", title: "" };
            view.applyLocationConversionModel(button, {
                disabled: true,
                label: "Koordinaten umgerechnet",
                title: "Prüfen",
            });
            assert.strictEqual(button.disabled, true);
            assert.strictEqual(button.textContent, "Koordinaten umgerechnet");
            assert.strictEqual(button.title, "Prüfen");

            // A disabled button never shows its title tooltip, so every reason for
            // being disabled has to be readable as visible text instead.
            assert.strictEqual(toNether.note, "");
            assert.match(toEnd.note, /Nur zwischen Oberwelt und Nether/);
            assert.match(invalidPosition.note, /X, Y und Z/);
            assert.match(view.locationConversionModel({
                sourceDimension: 0,
                targetDimension: "1",
                blocked: true,
            }).note, /gesperrt/);
            assert.match(view.locationConversionModel({
                sourceDimension: 0,
                targetDimension: "1",
                converted: true,
            }).note, /einmal angewendet/);

            // A wrong reason is worse than none: an unknown source dimension must not
            // be reported as "pick the other dimension", which the user already did.
            assert.match(view.locationConversionModel({
                sourceDimension: null,
                targetDimension: "1",
            }).note, /Ausgangsdimension der Welt ist nicht bekannt/);
            assert.match(view.locationConversionModel({
                sourceDimension: 2,
                targetDimension: "0",
            }).note, /Aus dem Ende/);

            const noteElement = { hidden: false, textContent: "alt" };
            view.applyLocationConversionNote(noteElement, { note: "" });
            assert.strictEqual(noteElement.hidden, true);
            assert.strictEqual(noteElement.textContent, "");
            view.applyLocationConversionNote(noteElement, { note: "Grund" });
            assert.strictEqual(noteElement.hidden, false);
            assert.strictEqual(noteElement.textContent, "Grund");
            """
        )
    )
