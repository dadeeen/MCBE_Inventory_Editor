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


def test_frontend_effects_logic_add_effect_decision() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_logic.js" });

            const logic = context.window.MCBEEffectsLogic;
            assert.strictEqual(
                JSON.stringify(logic.availableEffectIds([{ id: 2 }], { 1: ["Tempo"], 2: ["Stärke"], 4: ["Sprung"] })),
                JSON.stringify([1, 4]),
            );

            const protectedDecision = logic.addEffectDecision({ protectedActiveEffects: true });
            assert.strictEqual(protectedDecision.ok, false);
            assert.strictEqual(protectedDecision.reason, "protected_active_effects");
            assert.ok(protectedDecision.message.includes("ActiveEffects"));

            const noneDecision = logic.addEffectDecision({
                effects: [{ id: 1 }],
                effectsDb: { 1: ["Tempo"] },
            });
            assert.strictEqual(noneDecision.ok, false);
            assert.strictEqual(noneDecision.reason, "none_available");

            const addDecision = logic.addEffectDecision({
                effects: [{ id: 2 }],
                effectsDb: { 1: ["Tempo"], 2: ["Stärke"] },
                selectedEffectId: 1,
            });
            assert.strictEqual(addDecision.ok, true);
            assert.strictEqual(addDecision.label, "Tempo");
            assert.strictEqual(addDecision.toastMessage, "+ Tempo hinzugefügt");
            assert.strictEqual(addDecision.recordLabel, "Effekt hinzugefügt: Tempo");
            assert.strictEqual(addDecision.effect.id, 1);
            assert.strictEqual(addDecision.effect.duration, 600);
            assert.strictEqual(addDecision.effect.show_particles, true);

            const missingSelection = logic.addEffectDecision({
                effects: [],
                effectsDb: { 1: ["Tempo"] },
            });
            assert.strictEqual(missingSelection.ok, false);
            assert.strictEqual(missingSelection.reason, "selection_required");

            const options = logic.availableEffectOptions([], {
                1: ["Zweiter", "Second", "Zweite Beschreibung", "Second description"],
                2: ["Erster", "First", "Erste Beschreibung", "First description"],
            });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(options)), [
                { id: 2, label: "Erster", description: "First description" },
                { id: 1, label: "Zweiter", description: "Second description" },
            ]);
            assert.strictEqual(logic.effectDescription(999, {}), "Keine Beschreibung verfügbar.");
            """
        )
    )


def test_frontend_effects_logic_uses_english_effect_name_in_english_locale() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const catalog = JSON.parse(fs.readFileSync("static/i18n/en.json", "utf8"));
            const t = (text, params) => String(catalog[text] ?? text).replace(
                /\{(\w+)\}/g,
                (match, key) => params && key in params ? String(params[key]) : match,
            );
            const context = { window: { t, MCBEI18n: {
                locale: "en",
                localizedPair: (de, en) => ({ primary: en || "", secondary: "" }),
            } } };
            vm.runInNewContext(fs.readFileSync("static/effects_logic.js", "utf8"), context, {
                filename: "static/effects_logic.js",
            });

            const decision = context.window.MCBEEffectsLogic.addEffectDecision({
                effects: [],
                effectsDb: {
                    1: [
                        "Geschwindigkeit",
                        "Speed",
                        "Deutscher Beispieltext.",
                        "English sample text.",
                    ],
                },
                selectedEffectId: 1,
            });
            assert.strictEqual(decision.label, "Speed");
            assert.strictEqual(decision.toastMessage, "+ Speed added");
            assert.strictEqual(decision.recordLabel, "Effect added: Speed");
            assert.strictEqual(
                context.window.MCBEEffectsLogic.effectDescription(1, {
                    1: ["Geschwindigkeit", "Speed", "Deutscher Text.", "English text."],
                }),
                "English text.",
            );
            const missingEnglish = context.window.MCBEEffectsLogic.availableEffectOptions([], {
                2: ["Nur Deutsch", "", "Nur deutsche Beschreibung.", ""],
            });
            assert.strictEqual(missingEnglish[0].label, "2");
            assert.strictEqual(missingEnglish[0].description, "No description available.");
            """
        )
    )


def test_stats_form_clamps_manual_values_to_declared_input_range() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_logic.js" });

            const listeners = {};
            const xpProgress = {
                value: "0",
                min: "0",
                max: "99.99",
                addEventListener: (name, callback) => { listeners[name] = callback; },
            };
            const controller = context.window.MCBEEffectsLogic.createStatsFormController({
                elements: { xpProgress },
            });
            controller.wireTouchedTracking();

            xpProgress.value = "120";
            listeners.input();
            assert.strictEqual(xpProgress.value, "99.99");
            assert.strictEqual(controller.touchedFields.has("xp_progress"), true);

            xpProgress.value = "-5";
            listeners.change();
            assert.strictEqual(xpProgress.value, "0");

            xpProgress.value = "";
            listeners.input();
            assert.strictEqual(xpProgress.value, "");
            """
        )
    )


def test_stats_form_dimension_conversion_is_explicit_and_one_shot() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_logic.js" });

            function input(value) {
                const listeners = {};
                return {
                    value,
                    disabled: false,
                    listeners,
                    addEventListener(name, callback) { listeners[name] = callback; },
                };
            }
            const dimensionId = input("0");
            const posX = input("80");
            const posY = input("70");
            const posZ = input("-40");
            const convertLocation = input("");
            const abilityView = {
                readStatsFormValues: elements => ({
                    dimensionId: elements.dimensionId.value,
                    posX: elements.posX.value,
                    posY: elements.posY.value,
                    posZ: elements.posZ.value,
                }),
                locationConversionModel: ({ sourceDimension, targetDimension, blocked, converted }) => ({
                    disabled: blocked || converted || !(Number(sourceDimension) === 0 && Number(targetDimension) === 1),
                    label: converted ? "converted" : "convert",
                }),
                applyLocationConversionModel: (button, model) => {
                    button.disabled = model.disabled;
                    button.textContent = model.label;
                },
            };
            const abilityState = {
                convertPositionBetweenDimensions: (position, source, target) => (
                    Number(source) === 0 && Number(target) === 1
                        ? [Number(position[0]) / 8, Number(position[1]), Number(position[2]) / 8]
                        : null
                ),
            };
            const controller = context.window.MCBEEffectsLogic.createStatsFormController({
                elements: { dimensionId, posX, posY, posZ, convertLocation },
                getPlayerStats: () => ({ pos: [80, 70, -40], dimension_id: 0 }),
                abilityView,
                abilityState,
            });
            controller.wireTouchedTracking();

            dimensionId.value = "1";
            dimensionId.listeners.change();
            assert.strictEqual(posX.value, "80");
            assert.strictEqual(posZ.value, "-40");
            assert.strictEqual(convertLocation.disabled, false);

            convertLocation.listeners.click();
            assert.strictEqual(posX.value, "10");
            assert.strictEqual(posY.value, "70");
            assert.strictEqual(posZ.value, "-5");
            assert.strictEqual(convertLocation.disabled, true);
            assert.strictEqual(controller.touchedFields.has("dimension_id"), true);
            assert.strictEqual(controller.touchedFields.has("pos"), true);

            dimensionId.value = "0";
            dimensionId.listeners.change();
            dimensionId.value = "1";
            dimensionId.listeners.change();
            assert.strictEqual(convertLocation.disabled, true);
            """
        )
    )


def test_stats_form_disables_location_conversion_for_invalid_coordinates() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            for (const path of [
                "static/ability_state.js",
                "static/ability_view.js",
                "static/effects_logic.js",
            ]) {
                vm.runInNewContext(fs.readFileSync(path, "utf8"), context, { filename: path });
            }

            function input(value) {
                const listeners = {};
                return {
                    value,
                    disabled: false,
                    listeners,
                    addEventListener(name, callback) { listeners[name] = callback; },
                };
            }

            const elements = {
                dimensionId: input("0"),
                posX: input("80"),
                posY: input("70"),
                posZ: input("-40"),
                convertLocation: input(""),
            };
            const controller = context.window.MCBEEffectsLogic.createStatsFormController({
                elements,
                getPlayerStats: () => ({ pos: [80, 70, -40], dimension_id: 0 }),
            });
            controller.wireTouchedTracking();

            elements.dimensionId.value = "1";
            elements.dimensionId.listeners.change();
            assert.strictEqual(elements.convertLocation.disabled, false);

            elements.posX.value = "";
            elements.posX.listeners.input();
            assert.strictEqual(elements.convertLocation.disabled, true);
            assert.match(elements.convertLocation.title, /X, Y und Z/);

            elements.posX.value = "80";
            elements.posX.listeners.input();
            assert.strictEqual(elements.convertLocation.disabled, false);
            """
        )
    )


def test_frontend_effects_logic_apply_plan() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_logic.js" });

            const logic = context.window.MCBEEffectsLogic;
            let plan = logic.effectsAbilitiesApplyPlan({
                hasActiveEffectsTag: true,
                effectsCount: 0,
                effectsTouched: false,
                shouldSyncAbilities: false,
            });
            assert.strictEqual(plan.syncEffects, true);
            assert.strictEqual(plan.syncAbilities, false);
            assert.strictEqual(plan.hasWork, true);

            plan = logic.effectsAbilitiesApplyPlan({
                protectedActiveEffects: true,
                hasActiveEffectsTag: true,
                shouldSyncAbilities: true,
            });
            assert.strictEqual(plan.syncEffects, false);
            assert.strictEqual(plan.syncAbilities, true);
            assert.strictEqual(plan.hasWork, true);

            plan = logic.effectsAbilitiesApplyPlan({});
            assert.strictEqual(plan.syncEffects, false);
            assert.strictEqual(plan.syncAbilities, false);
            assert.strictEqual(plan.hasWork, false);
            """
        )
    )


def test_frontend_effects_logic_apply_outcome_requires_real_work() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_logic.js" });

            const logic = context.window.MCBEEffectsLogic;
            let outcome = logic.effectsAbilitiesApplyOutcome({
                plan: { syncEffects: false, syncAbilities: true },
                collectedAbilities: null,
            });
            assert.strictEqual(outcome.syncEffects, false);
            assert.strictEqual(outcome.applyAbilities, false);
            assert.strictEqual(outcome.hasWork, false);
            assert.strictEqual(outcome.collectedAbilities, null);

            outcome = logic.effectsAbilitiesApplyOutcome({
                plan: { syncEffects: false, syncAbilities: true },
                collectedAbilities: { mayfly: true },
            });
            assert.strictEqual(outcome.applyAbilities, true);
            assert.strictEqual(outcome.hasWork, true);
            assert.strictEqual(outcome.collectedAbilities.mayfly, true);

            outcome = logic.effectsAbilitiesApplyOutcome({
                plan: { syncEffects: true, syncAbilities: false },
                collectedAbilities: null,
            });
            assert.strictEqual(outcome.syncEffects, true);
            assert.strictEqual(outcome.applyAbilities, false);
            assert.strictEqual(outcome.hasWork, true);
            """
        )
    )


def test_frontend_effects_logic_remove_effect_decision() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_logic.js" });

            const logic = context.window.MCBEEffectsLogic;
            const protectedDecision = logic.removeEffectDecision({ protectedEffect: true });
            assert.strictEqual(protectedDecision.ok, false);
            assert.strictEqual(protectedDecision.reason, "protected_effect");
            assert.strictEqual(protectedDecision.toastMs, 3000);
            assert.ok(protectedDecision.message.includes("Geschützte Effekte"));

            const normalDecision = logic.removeEffectDecision({ protectedEffect: false });
            assert.strictEqual(normalDecision.ok, true);
            """
        )
    )


def test_effects_controller_keeps_dynamic_controls_read_only_when_editing_is_blocked() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            for (const path of [
                "static/ability_state.js",
                "static/ability_view.js",
                "static/effects_logic.js",
            ]) {
                vm.runInNewContext(fs.readFileSync(path, "utf8"), context, { filename: path });
            }

            const listenersFor = element => {
                element.listeners = {};
                element.addEventListener = (name, callback) => {
                    element.listeners[name] = callback;
                };
                return element;
            };
            const level = listenersFor({
                value: "1",
                min: "1",
                max: "256",
                disabled: false,
                dataset: {},
            });
            const duration = listenersFor({
                value: "30",
                min: "0",
                max: "107374182",
                disabled: false,
                dataset: {},
            });
            const particles = listenersFor({
                checked: true,
                disabled: false,
                dataset: {},
            });
            const remove = listenersFor({ disabled: false, dataset: {} });
            const rowControls = [level, duration, particles, remove];
            const row = {
                dataset: {},
                querySelector: selector => ({
                    ".eff-level": level,
                    ".eff-duration": duration,
                    ".eff-particles": particles,
                    ".effect-remove": remove,
                })[selector] || null,
                querySelectorAll: selector => selector === "input, select, textarea, button"
                    ? rowControls
                    : [],
            };
            context.window.MCBEEffectsView = {
                effectsListModel: () => ({
                    listStateHtml: "",
                    rowModels: [{ index: 0, isProtectedEffect: false }],
                }),
                effectRowElement: () => row,
                readEffectRowValues: () => ({
                    levelValue: level.value,
                    durationSecondsValue: duration.value,
                    showParticles: particles.checked,
                }),
                effectPatchFromRowValues: () => ({
                    amplifier: 99,
                    duration: 99,
                    show_particles: false,
                }),
            };

            const abilityIds = [
                "abMayfly",
                "abFlying",
                "abInvulnerable",
                "abMaybuild",
                "abInstabuild",
                "abFlySpeed",
                "abWalkSpeed",
            ];
            const elements = Object.fromEntries(abilityIds.map(id => [id, {
                checked: false,
                value: "",
                disabled: false,
                title: "",
            }]));
            elements.btnResetAbilitySpeeds = { disabled: false };
            const container = {
                innerHTML: "",
                children: [],
                appendChild(child) { this.children.push(child); },
            };
            elements.effectsContainer = container;
            const doc = {
                getElementById: id => elements[id] || null,
                querySelectorAll: () => [],
            };
            const effects = [{
                id: 1,
                amplifier: 0,
                duration: 600,
                show_particles: true,
            }];
            let dirtyCalls = 0;
            let undoCalls = 0;
            const controller = context.window.MCBEEffectsLogic.createEffectsAbilitiesController({
                doc,
                statsFormElements: () => ({}),
                getProtectedNbt: () => ({}),
                getPlayerEffects: () => effects,
                getPlayerAbilities: () => ({}),
                getEffectsDb: () => ({ 1: ["Tempo"] }),
                editingBlocked: () => true,
                setDirty: () => { dirtyCalls += 1; },
                pushUndo: () => { undoCalls += 1; },
            });

            controller.loadAbilitiesUI();
            abilityIds.forEach(id => assert.strictEqual(elements[id].disabled, true));
            assert.strictEqual(elements.btnResetAbilitySpeeds.disabled, true);

            controller.renderEffectsList();
            rowControls.forEach(control => assert.strictEqual(control.disabled, true));

            level.value = "7";
            level.listeners.input();
            remove.listeners.click();
            assert.strictEqual(effects.length, 1);
            assert.strictEqual(effects[0].amplifier, 0);
            assert.strictEqual(dirtyCalls, 0);
            assert.strictEqual(undoCalls, 0);
            """
        )
    )
