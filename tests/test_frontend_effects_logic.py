import textwrap

from tests.node_runner import run_node


def test_sync_effects_preserves_disabled_opaque_and_unknown_rows() -> None:
    run_node(r"""
        const assert = require("node:assert/strict");
        const fs = require("fs");
        const vm = require("vm");
        const context = {window: {}};
        for (const file of ["static/effects_view.js", "static/effects_logic.js"]) {
            vm.runInNewContext(fs.readFileSync(file, "utf8"), context);
        }
        const effects = [
            {id: 1, amplifier: 0, duration: -1, show_particles: true, opaque: true},
            {id: 100, amplifier: 400, duration: -20, show_particles: true},
            {id: 3, amplifier: 0, duration: 601, show_particles: true},
        ];
        const before = JSON.stringify(effects.slice(0, 2));
        const db = {1: ["Tempo", "Speed"], 3: ["Eile", "Haste"]};
        const rows = effects.map((effect, index) => {
            const model = context.window.MCBEEffectsView.effectRowModel(effect, index, db);
            const controls = {
                ".eff-level": {value: String(model.level), disabled: model.isProtectedEffect},
                ".eff-duration": {value: String(model.durationSeconds), disabled: model.isProtectedEffect},
                ".eff-particles": {checked: model.showParticles, disabled: model.isProtectedEffect},
            };
            return {dataset: {index: String(index)}, querySelector: selector => controls[selector]};
        });
        rows[2].querySelector(".eff-duration").value = "60";
        const controller = context.window.MCBEEffectsLogic.createEffectsAbilitiesController({
            doc: {querySelectorAll: () => rows}, getPlayerEffects: () => effects, getEffectsDb: () => db,
        });
        controller.syncEffectsFromUI();
        assert.equal(JSON.stringify(effects.slice(0, 2)), before);
        assert.equal(effects[2].duration, 1200);
    """)


def test_frontend_effects_logic_add_effect_decision() -> None:
    run_node(
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
    run_node(
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
    run_node(
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


def test_stats_form_pending_drafts_preserve_values_and_ignore_reverted_or_stale_controls() -> None:
    run_node(r"""
        const assert = require("node:assert/strict");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        for (const path of ["static/ability_state.js", "static/ability_view.js", "static/effects_logic.js"]) {
            vm.runInNewContext(fs.readFileSync(path, "utf8"), context, { filename: path });
        }
        const elements = Object.fromEntries([
            "dimensionId", "posX", "posY", "posZ", "health", "xpLevel", "xpProgress", "foodLevel", "foodSaturation", "convertLocation",
        ].map(key => [key, {
            value: "", listeners: {},
            addEventListener(name, callback) { this.listeners[name] = callback; },
        }]));
        const stats = {
            dimension_id: 0, pos: [80.1234567, 70.345678, -40.56789], health: 20,
            xp_level: 17, xp_progress: 0.123456, food_level: 20, food_saturation: 5,
        };
        const original = JSON.stringify(stats);
        let playerContext = "world/player-a";
        const controller = context.window.MCBEEffectsLogic.createStatsFormController({
            elements, getPlayerStats: () => stats, getContextKey: () => playerContext,
        });
        controller.wireTouchedTracking();
        assert.equal(controller.hasPendingChanges(), false);
        controller.render();
        assert.equal(controller.hasPendingChanges(), false);
        for (const [key, value] of [
            ["health", "19.5"], ["xpLevel", "18"], ["xpProgress", "12.9"], ["foodLevel", "19"], ["foodSaturation", "4.5"],
            ["dimensionId", "1"], ["posX", "100"], ["posY", "80"], ["posZ", "-20"],
        ]) {
            const previous = elements[key].value;
            elements[key].value = value;
            elements[key].listeners.input();
            assert.equal(controller.hasPendingChanges(), true, key);
            assert.equal(JSON.stringify(stats), original, "query must not apply a draft");
            elements[key].value = String(Number(previous)) + ".000";
            // Only use alternate trailing-zero spelling for integer baselines.
            if (!Number.isInteger(Number(previous))) elements[key].value = String(Number(previous));
            assert.equal(controller.hasPendingChanges(), false, key + " reverted");
        }
        elements.posX.value = "";
        const touchedBefore = [...controller.touchedFields];
        assert.equal(controller.hasPendingChanges(), true, "blank is not zero");
        assert.deepEqual([...controller.touchedFields], touchedBefore);
        controller.render();
        elements.convertLocation.listeners.click();
        assert.equal(controller.hasPendingChanges(), true);
        elements.convertLocation.listeners.click();
        assert.equal(Number(elements.posY.value), stats.pos[1], "conversion leaves exact unchanged Y in the form");
        assert.equal(controller.hasPendingChanges(), false, "undoing conversion preserves source precision");
        elements.health.value = "19";
        assert.equal(controller.hasPendingChanges(), true);
        playerContext = "world/player-b";
        assert.equal(controller.hasPendingChanges(), false, "a new player cannot inherit an old form draft");
        controller.render();
        elements.health.value = "19";
        playerContext = null;
        assert.equal(controller.hasPendingChanges(), false, "unloaded controls are not an editor draft");
        assert.equal(JSON.stringify(stats), original);
        playerContext = "world/player-a";
        stats.pos[0] = 0;
        controller.render();
        elements.posX.value = "";
        assert.equal(controller.hasPendingChanges(), true, "blank must not normalize to the zero baseline");
        stats.pos[0] = 0.004;
        controller.render();
        elements.posX.value = "-0.004";
        assert.equal(controller.hasPendingChanges(), true, "position precision preserves a change across zero");
        elements.posX.value = "0.004";
        assert.equal(controller.hasPendingChanges(), false, "unchanged stored coordinate precision is not a draft");
        elements.posX.value = "0.02";
        assert.equal(controller.hasPendingChanges(), true, "a coordinate change visible at stored display precision is a draft");
        stats.pos[0] = -0.004;
        controller.render();
        elements.posX.value = "0.004";
        assert.equal(controller.hasPendingChanges(), true, "negative rounded zero also detects crossing to positive");
        elements.posX.value = "-0.004";
        assert.equal(controller.hasPendingChanges(), false, "restoring the exact negative source is not a draft");
        elements.convertLocation.listeners.click();
        elements.convertLocation.listeners.click();
        assert.equal(controller.hasPendingChanges(), false, "conversion undo retains negative source precision");
        stats.xp_level = 10;
        stats.food_level = 10;
        controller.render();
        for (const key of ["xpLevel", "foodLevel"]) {
            elements[key].value = "1e1";
            assert.equal(controller.hasPendingChanges(), false, "equivalent exponent notation is not a draft");
            elements[key].value = "2e1";
            assert.equal(controller.hasPendingChanges(), true, "changed exponent notation is a draft");
            elements[key].value = "10.0";
            assert.equal(controller.hasPendingChanges(), false, "alternate integer spelling is not a draft");
        }
    """)


def test_stats_apply_rebases_accepted_drafts_but_keeps_invalid_positions_pending() -> None:
    run_node(r"""
        const assert = require("node:assert/strict");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        for (const path of ["static/ability_state.js", "static/ability_view.js", "static/effects_logic.js"]) {
            vm.runInNewContext(fs.readFileSync(path, "utf8"), context, { filename: path });
        }
        const control = () => ({value: "", listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; }});
        const fields = Object.fromEntries([
            "dimensionId", "posX", "posY", "posZ", "health", "xpLevel", "xpProgress", "foodLevel", "foodSaturation",
        ].map(key => [key, control()]));
        const applyButton = control();
        let stats = {dimension_id: 0, pos: [1, 70, 2], health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5};
        const form = context.window.MCBEEffectsLogic.createStatsFormController({elements: fields, getPlayerStats: () => stats});
        form.wireTouchedTracking();
        form.render();
        let accepted = 0;
        let dirtyCalls = 0;
        const controller = context.window.MCBEEffectsLogic.createEffectsAbilitiesController({
            doc: {getElementById: id => id === "btnApplyStats" ? applyButton : null, querySelectorAll: () => []},
            statsFormElements: () => fields, getPlayerStats: () => stats, setPlayerStats: next => { stats = next; },
            getTouchedStatsFields: () => form.touchedFields,
            onStatsApplied: () => { accepted += 1; form.resetConversion(); form.captureFormBaseline(); },
            setDirty: () => { dirtyCalls += 1; },
        });
        controller.wire();
        fields.health.value = ""; // Existing apply policy accepts the unchanged default of 20.
        fields.health.listeners.input();
        assert.equal(form.hasPendingChanges(), true);
        applyButton.listeners.click();
        assert.equal(accepted, 1, "successful no-op Apply still accepts the form draft");
        assert.equal(form.hasPendingChanges(), false);
        assert.equal(dirtyCalls, 0);
        fields.health.value = "19";
        fields.health.listeners.input();
        applyButton.listeners.click();
        assert.equal(stats.health, 19);
        assert.equal(accepted, 2);
        assert.equal(dirtyCalls, 1);
        assert.equal(form.hasPendingChanges(), false);
        fields.posX.value = "";
        fields.posX.listeners.input();
        applyButton.listeners.click();
        assert.equal(accepted, 2, "rejected position must not rebase the draft");
        assert.equal(form.hasPendingChanges(), true);
        assert.deepEqual(Array.from(stats.pos), [1, 70, 2]);
    """)


def test_stats_form_dimension_conversion_is_explicit_and_reversible() -> None:
    run_node(
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
                    disabled: blocked || (!converted && !(Number(sourceDimension) === 0 && Number(targetDimension) === 1)),
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
            assert.strictEqual(convertLocation.disabled, false);
            assert.strictEqual(controller.touchedFields.has("dimension_id"), true);
            assert.strictEqual(controller.touchedFields.has("pos"), true);

            dimensionId.value = "0";
            dimensionId.listeners.change();
            dimensionId.value = "1";
            dimensionId.listeners.change();
            assert.strictEqual(convertLocation.disabled, false);
            posY.value = "75";
            convertLocation.listeners.click();
            assert.strictEqual(posX.value, "80");
            assert.strictEqual(posZ.value, "-40");
            assert.strictEqual(posY.value, "75");
            assert.strictEqual(dimensionId.value, "1");
            convertLocation.listeners.click();
            assert.strictEqual(posX.value, "10");
            controller.resetConversion();
            assert.strictEqual(convertLocation.textContent, "convert");
            """
        )
    )


def test_stats_form_disables_location_conversion_for_invalid_coordinates() -> None:
    run_node(
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
    run_node(
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
    run_node(
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
    run_node(
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
    run_node(
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
                "abMovementSpeed",
                "abWalkSpeed",
                "abFlySpeed",
                "abVerticalFlySpeed",
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


def test_effects_controller_couples_walk_speed_and_resets_only_editable_speeds() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            // Im Browser stellt static/i18n.js die globale Funktion t bereit.
            const context = { window: {}, t: text => text };
            for (const path of [
                "static/ability_state.js",
                "static/ability_view.js",
                "static/effects_logic.js",
            ]) {
                vm.runInNewContext(fs.readFileSync(path, "utf8"), context, { filename: path });
            }

            const input = (id, value, max) => {
                const element = { id, value, min: "0", max, disabled: false, title: "", dataset: {}, listeners: {} };
                element.addEventListener = (name, callback) => { element.listeners[name] = callback; };
                return element;
            };
            const elements = {
                abMovementSpeed: input("abMovementSpeed", "", "1"),
                abWalkSpeed: input("abWalkSpeed", "", "1"),
                abFlySpeed: input("abFlySpeed", "", "1"),
                abVerticalFlySpeed: input("abVerticalFlySpeed", "", "20"),
                btnResetAbilitySpeeds: input("btnResetAbilitySpeeds", "", ""),
                abilityMovementLockNote: { hidden: true, textContent: "" },
            };
            const doc = {
                getElementById: id => elements[id] || null,
                querySelectorAll: selector => selector === "#dashEffects .abilities-section input"
                    ? ["abMovementSpeed", "abWalkSpeed", "abFlySpeed", "abVerticalFlySpeed"].map(id => elements[id])
                    : [],
            };
            let protectedNbt = {};
            let abilities = { movement_speed: 0.1, walk_speed: 0.1, fly_speed: 0.05, vertical_fly_speed: 1 };
            let undoCalls = 0;
            const controller = context.window.MCBEEffectsLogic.createEffectsAbilitiesController({
                doc,
                statsFormElements: () => ({}),
                getProtectedNbt: () => protectedNbt,
                getPlayerAbilities: () => abilities,
                setPlayerAbilities: value => { abilities = value; },
                setAbilitiesTouched: () => {},
                setDirty: () => {},
                pushUndo: () => { undoCalls += 1; },
                showToast: () => {},
                recordAction: () => {},
            });
            controller.wire();
            controller.loadAbilitiesUI();
            assert.strictEqual(elements.abMovementSpeed.value, "0.1");
            assert.strictEqual(elements.abVerticalFlySpeed.value, "1");
            assert.strictEqual(elements.abilityMovementLockNote.hidden, true);

            // Die Laufgeschwindigkeit zieht das Lauf-Sichtfeld mit, damit das
            // Sichtfeld beim Laufen normal bleibt.
            elements.abMovementSpeed.value = "0.4";
            elements.abMovementSpeed.listeners.input();
            assert.strictEqual(elements.abWalkSpeed.value, "0.4");
            assert.strictEqual(abilities.movement_speed, 0.4);
            assert.strictEqual(abilities.walk_speed, 0.4);

            // Das Lauf-Sichtfeld allein lässt die Laufgeschwindigkeit unverändert.
            elements.abWalkSpeed.value = "0.3";
            elements.abWalkSpeed.listeners.change();
            assert.strictEqual(abilities.walk_speed, 0.3);
            assert.strictEqual(abilities.movement_speed, 0.4);

            elements.abVerticalFlySpeed.value = "50";
            elements.abVerticalFlySpeed.listeners.input();
            assert.strictEqual(elements.abVerticalFlySpeed.value, "20");
            assert.strictEqual(abilities.vertical_fly_speed, 20);

            // Gesperrte Laufgeschwindigkeit: sichtbarer Grund, kein Mitziehen,
            // der Reset setzt nur die editierbaren Felder zurück.
            protectedNbt = { movement_speed_locked: "modifiers" };
            abilities = { movement_speed: 0.13, walk_speed: 0.3, fly_speed: 0.5, vertical_fly_speed: 20 };
            controller.loadAbilitiesUI();
            assert.strictEqual(elements.abMovementSpeed.disabled, true);
            assert.strictEqual(elements.abMovementSpeed.value, "0.13");
            assert.strictEqual(elements.abilityMovementLockNote.hidden, false);
            assert.match(elements.abilityMovementLockNote.textContent, /Modifikatoren/);
            assert.strictEqual(elements.btnResetAbilitySpeeds.disabled, false);

            undoCalls = 0;
            elements.btnResetAbilitySpeeds.listeners.click();
            assert.strictEqual(undoCalls, 1);
            assert.strictEqual(elements.abMovementSpeed.value, "0.13");
            assert.strictEqual(elements.abWalkSpeed.value, "0.1");
            assert.strictEqual(elements.abFlySpeed.value, "0.05");
            assert.strictEqual(elements.abVerticalFlySpeed.value, "1");
            assert.deepStrictEqual(JSON.parse(JSON.stringify(abilities)), { walk_speed: 0.1, fly_speed: 0.05, vertical_fly_speed: 1 });

            // Schon auf Standard: kein weiterer Undo-Schritt.
            elements.btnResetAbilitySpeeds.listeners.click();
            assert.strictEqual(undoCalls, 1);
            """
        )
    )
