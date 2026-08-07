(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function effectLabel(effectId, effectsDb = {}) {
        const info = effectsDb[effectId];
        if (!info) return String(effectId);
        const names = window.MCBEI18n?.localizedPair?.(info[0], info[1]);
        return names ? names.primary || String(effectId) : info[0] || info[1] || String(effectId);
    }

    function effectDescription(effectId, effectsDb = {}) {
        const info = effectsDb[effectId];
        const descriptions = window.MCBEI18n?.localizedPair?.(info?.[2], info?.[3]);
        return String(descriptions ? descriptions.primary || t("Keine Beschreibung verfügbar.") : info?.[3] || info?.[2] || t("Keine Beschreibung verfügbar."));
    }

    function availableEffectIds(effects = [], effectsDb = {}) {
        const usedIds = new Set(effects.map(effect => Number(effect.id)));
        return Object.keys(effectsDb)
            .map(Number)
            .filter(id => !usedIds.has(id))
            .sort((a, b) => a - b);
    }

    function availableEffectOptions(effects = [], effectsDb = {}) {
        return availableEffectIds(effects, effectsDb)
            .map(id => ({
                id,
                label: effectLabel(id, effectsDb),
                description: effectDescription(id, effectsDb),
            }))
            .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
    }

    function clampInputToDeclaredRange(input) {
        if (!input || input.value === "") return false;
        const value = Number(input.value);
        if (!Number.isFinite(value)) return false;
        const minText = String(input.min ?? "");
        const maxText = String(input.max ?? "");
        const min = minText === "" ? null : Number(minText);
        const max = maxText === "" ? null : Number(maxText);
        if (Number.isFinite(min) && value < min) {
            input.value = String(min);
            return true;
        }
        if (Number.isFinite(max) && value > max) {
            input.value = String(max);
            return true;
        }
        return false;
    }

    function newEffect(effectId) {
        return {
            id: effectId,
            amplifier: 0,
            duration: 600,
            ambient: false,
            show_particles: true,
            show_icon: true,
        };
    }

    function addEffectDecision({
        protectedActiveEffects = false,
        effects = [],
        effectsDb = {},
        selectedEffectId = null,
    } = {}) {
        if (protectedActiveEffects) {
            return {
                ok: false,
                reason: "protected_active_effects",
                message: t("ActiveEffects hat einen unbekannten NBT-Typ und wird geschützt erhalten."),
                toastMs: 4000,
            };
        }
        const available = availableEffectIds(effects, effectsDb);
        if (available.length === 0) {
            return {
                ok: false,
                reason: "none_available",
                message: t("Keine weiteren Effekte verfügbar."),
                toastMs: 3000,
            };
        }
        const effectId = Number(selectedEffectId);
        if (!Number.isInteger(effectId) || !available.includes(effectId)) {
            return {
                ok: false,
                reason: "selection_required",
                message: t("Wähle zuerst einen verfügbaren Effekt aus."),
                toastMs: 2500,
            };
        }
        const label = effectLabel(effectId, effectsDb);
        return {
            ok: true,
            effect: newEffect(effectId),
            label,
            toastMessage: t("+ {label} hinzugefügt", { label }),
            recordLabel: t("Effekt hinzugefügt: {label}", { label }),
        };
    }

    function effectsAbilitiesApplyPlan({
        protectedActiveEffects = false,
        hasActiveEffectsTag = false,
        effectsCount = 0,
        effectsTouched = false,
        shouldSyncAbilities = false,
    } = {}) {
        const syncEffects = !protectedActiveEffects && (hasActiveEffectsTag || effectsCount > 0 || effectsTouched);
        const syncAbilities = Boolean(shouldSyncAbilities);
        return {
            syncEffects,
            syncAbilities,
            hasWork: syncEffects || syncAbilities,
        };
    }

    function effectsAbilitiesApplyOutcome({
        plan = {},
        collectedAbilities = null,
    } = {}) {
        const applyAbilities = Boolean(plan.syncAbilities) && collectedAbilities !== null;
        const syncEffects = Boolean(plan.syncEffects);
        return {
            syncEffects,
            applyAbilities,
            hasWork: syncEffects || applyAbilities,
            collectedAbilities: applyAbilities ? collectedAbilities : null,
        };
    }

    function removeEffectDecision({ protectedEffect = false } = {}) {
        if (protectedEffect) {
            return {
                ok: false,
                reason: "protected_effect",
                message: t("Geschützte Effekte werden nicht gelöscht oder normalisiert."),
                toastMs: 3000,
            };
        }
        return { ok: true };
    }

    window.MCBEEffectsLogic = {
        addEffectDecision,
        availableEffectIds,
        availableEffectOptions,
        clampInputToDeclaredRange,
        effectDescription,
        effectLabel,
        effectsAbilitiesApplyOutcome,
        effectsAbilitiesApplyPlan,
        newEffect,
        removeEffectDecision,
    };
}());

(function () {
    "use strict";

    const logic = window.MCBEEffectsLogic || {};


    function createStatsFormController({
        elements = {},
        getPlayerStats = () => ({}),
        touchedFields = new Set(),
        abilityView = window.MCBEAbilityView,
        abilityState = window.MCBEAbilityState,
    } = {}) {
        const statsFields = [
            [elements.dimensionId, "dimension_id"],
            [elements.posX, "pos"],
            [elements.posY, "pos"],
            [elements.posZ, "pos"],
            [elements.health, "health"],
            [elements.xpLevel, "xp_level"],
            [elements.xpProgress, "xp_progress"],
            [elements.foodLevel, "food_level"],
            [elements.foodSaturation, "food_saturation"],
        ];
        let conversionApplied = false;

        function formElements() {
            return elements;
        }

        function markTouched(field) {
            if (field) touchedFields.add(field);
        }

        function render() {
            const model = abilityView.statsFormModel(getPlayerStats?.() || {});
            abilityView.applyStatsFormModel(formElements(), model);
            conversionApplied = false;
            refreshLocationConversion();
        }

        function refreshLocationConversion() {
            if (!abilityView?.locationConversionModel || !abilityView?.applyLocationConversionModel) return;
            const values = abilityView.readStatsFormValues(formElements());
            const sourceDimension = getPlayerStats?.()?.dimension_id;
            const targetDimension = values.dimensionId;
            const source = Number(sourceDimension);
            const target = Number(targetDimension);
            const supportedPair = (source === 0 && target === 1) || (source === 1 && target === 0);
            const convertedPosition = supportedPair
                ? abilityState?.convertPositionBetweenDimensions?.(
                    [values.posX, values.posY, values.posZ],
                    sourceDimension,
                    targetDimension,
                )
                : null;
            const locationBlocked = Boolean(
                elements.dimensionId?.disabled
                || elements.posX?.disabled
                || elements.posY?.disabled
                || elements.posZ?.disabled
            );
            const model = abilityView.locationConversionModel({
                sourceDimension,
                targetDimension,
                blocked: locationBlocked,
                converted: conversionApplied,
                positionInvalid: supportedPair && !conversionApplied && !convertedPosition,
            });
            abilityView.applyLocationConversionModel(elements.convertLocation, model);
            abilityView.applyLocationConversionNote?.(elements.convertLocationNote, model);
        }

        function wireTouchedTracking() {
            statsFields.forEach(([input, field]) => {
                input?.addEventListener("input", () => {
                    logic.clampInputToDeclaredRange(input);
                    markTouched(field);
                    if (field === "dimension_id") {
                        refreshLocationConversion();
                    } else if (field === "pos") {
                        refreshLocationConversion();
                    }
                });
                input?.addEventListener("change", () => {
                    logic.clampInputToDeclaredRange(input);
                    markTouched(field);
                    if (field === "dimension_id") {
                        refreshLocationConversion();
                    } else if (field === "pos") {
                        refreshLocationConversion();
                    }
                });
            });
            elements.convertLocation?.addEventListener("click", () => {
                const values = abilityView.readStatsFormValues(formElements());
                const position = [values.posX, values.posY, values.posZ];
                const converted = abilityState?.convertPositionBetweenDimensions?.(
                    position,
                    getPlayerStats?.()?.dimension_id,
                    values.dimensionId,
                );
                if (!converted) return;
                [elements.posX, elements.posY, elements.posZ].forEach((input, index) => {
                    if (input) input.value = String(converted[index]);
                });
                conversionApplied = true;
                markTouched("pos");
                markTouched("dimension_id");
                refreshLocationConversion();
            });
        }

        return {
            elements: formElements,
            markTouched,
            refreshLocationConversion,
            render,
            touchedFields,
            wireTouchedTracking,
        };
    }


    function createConfiguredStatsFormController({
        doc = document,
        getPlayerStats = () => ({}),
    } = {}) {
        return createStatsFormController({
            elements: {
                dimensionId: doc.getElementById("statDimensionId"),
                posX: doc.getElementById("statPosX"),
                posY: doc.getElementById("statPosY"),
                posZ: doc.getElementById("statPosZ"),
                health: doc.getElementById("statHealth"),
                gamemode: doc.getElementById("statGamemode"),
                xpLevel: doc.getElementById("statXpLevel"),
                xpProgress: doc.getElementById("statXpProgress"),
                foodLevel: doc.getElementById("statFoodLevel"),
                foodSaturation: doc.getElementById("statFoodSaturation"),
                convertLocation: doc.getElementById("btnConvertOverworldNether"),
                convertLocationNote: doc.getElementById("locationConversionNote"),
            },
            getPlayerStats,
        });
    }

    function createEffectsAbilitiesController({
        doc = document,
        statsFormElements,
        getTouchedStatsFields,
        getProtectedNbt,
        getPlayerStats,
        setPlayerStats,
        getPlayerEffects,
        getPlayerAbilities,
        setPlayerAbilities,
        getEffectsDb,
        getEffectsTouched,
        setEffectsTouched,
        setAbilitiesTouched,
        getShouldSyncAbilitiesFromUIForSave,
        editingBlocked = () => false,
        pushUndo,
        setDirty,
        logStatus,
        showToast,
        recordAction,
    } = {}) {
        const abilityState = window.MCBEAbilityState;
        const abilityView = window.MCBEAbilityView;
        const effectsView = window.MCBEEffectsView;

        function protectedNbt() {
            return getProtectedNbt?.() || {};
        }

        function playerEffects() {
            return getPlayerEffects?.() || [];
        }

        function playerAbilities() {
            const abilities = getPlayerAbilities?.();
            return abilities && typeof abilities === "object" ? abilities : {};
        }

        function effectsDb() {
            return getEffectsDb?.() || {};
        }

        function isEditingBlocked() {
            return editingBlocked?.() === true;
        }

        function protectedAbilityFields() {
            return abilityState.protectedAbilityFields(protectedNbt());
        }

        function protectedStatFields() {
            return abilityState.protectedStatFields(protectedNbt());
        }

        function setAbilityControlsDisabled(disabled) {
            const models = abilityView.abilityControlModels({
                disabled: disabled || isEditingBlocked(),
                protectedFields: protectedAbilityFields(),
            });
            abilityView.applyAbilityControlModels(doc, models);
            const resetButton = doc.getElementById("btnResetAbilitySpeeds");
            if (resetButton) {
                const fields = protectedAbilityFields();
                resetButton.disabled = Boolean(
                    disabled || isEditingBlocked() || fields.fly_speed || fields.walk_speed,
                );
            }
        }

        function formatAbilitySpeed(value, fallback) {
            return abilityState.formatAbilitySpeed(value, fallback);
        }

        function setStatsProtectionUI() {
            const nbt = protectedNbt();
            const models = abilityView.statProtectionControlModels({
                posOpaque: nbt.pos_opaque === true,
                posMissing: nbt.pos_missing === true,
                dimensionOpaque: nbt.dimension_id_opaque === true,
                dimensionMissing: nbt.dimension_id_missing === true,
                protectedFields: protectedStatFields(),
            }).map(model => ({
                ...model,
                disabled: model.disabled || isEditingBlocked(),
            }));
            abilityView.applyStatProtectionControlModels(statsFormElements?.(), models);
            const locationElements = statsFormElements?.() || {};
            const locationModel = abilityView.locationConversionModel?.({
                sourceDimension: getPlayerStats?.()?.dimension_id,
                targetDimension: locationElements.dimensionId?.value,
                blocked: models.some(model => ["dimensionId", "posX", "posY", "posZ"].includes(model.key) && model.disabled),
            });
            abilityView.applyLocationConversionModel?.(locationElements.convertLocation, locationModel);
            abilityView.applyLocationConversionNote?.(locationElements.convertLocationNote, locationModel);
            const applyButton = doc.getElementById("btnApplyStats");
            if (applyButton && isEditingBlocked()) applyButton.disabled = true;
        }

        function removeProtectedStatsFromPayload(statsPayload) {
            return abilityState.removeProtectedStatsFromPayload(statsPayload, protectedNbt());
        }

        function currentAbilityFormValues() {
            return abilityView.readAbilityFormValues(doc);
        }

        function renderAbilityRiskNote() {
            const note = doc.getElementById("abilityRiskNote");
            const nbt = protectedNbt();
            const abilities = playerAbilities();
            const model = abilityView.abilityRiskNoteModel({
                abilitiesOpaque: nbt.abilities_opaque === true,
                playerAbilitiesOpaque: abilities?._opaque === true,
                warnings: abilityState.abilityRiskWarnings(currentAbilityFormValues()),
            });
            abilityView.applyAbilityRiskNoteModel(note, model);
        }

        function loadAbilitiesUI() {
            let abilities = playerAbilities();
            if (!abilities || typeof abilities !== "object") abilities = {};
            const nbt = protectedNbt();
            const abilitiesOpaque = nbt.abilities_opaque === true || abilities._opaque === true;
            setAbilityControlsDisabled(abilitiesOpaque);
            const model = abilityView.abilityFormModel({
                abilities,
                flySpeedValue: formatAbilitySpeed(abilities.fly_speed, 0.05),
                walkSpeedValue: formatAbilitySpeed(abilities.walk_speed, 0.1),
            });
            abilityView.applyAbilityFormModel(doc, model);
            renderAbilityRiskNote();
        }

        function collectAbilitiesFromUI() {
            return abilityState.collectAbilitiesFromValues(
                playerAbilities(),
                protectedNbt(),
                currentAbilityFormValues(),
                abilityView.readAbilitySpeedValues(doc),
            );
        }

        function syncEffectRow(index, row) {
            const effects = playerEffects();
            if (!Number.isInteger(index) || !effects[index] || !row) return;
            Object.assign(
                effects[index],
                effectsView.effectPatchFromRowValues(effectsView.readEffectRowValues(row), effects[index]),
            );
        }

        function renderEffectPicker() {
            const select = doc.getElementById("effectToAdd");
            const addButton = doc.getElementById("btnAddEffect");
            const details = doc.getElementById("effectPickerDetails");
            const summary = doc.getElementById("effectPickerSummary");
            const list = doc.getElementById("effectPickerList");
            const description = doc.getElementById("effectPickerDescription");
            if (!select || !addButton || !details || !summary || !list || !description) return;
            const options = logic.availableEffectOptions(playerEffects(), effectsDb());
            const previousValue = select.value;
            const selectedOption = options.find(option => String(option.id) === previousValue) || null;
            select.value = selectedOption ? previousValue : "";
            summary.textContent = selectedOption?.label || t("Effekt auswählen …");
            description.textContent = selectedOption?.description
                || t("Bewege den Mauszeiger auf einen Effekt oder fokussiere ihn, um die Beschreibung zu sehen.");
            list.innerHTML = "";
            options.forEach(optionModel => {
                const option = doc.createElement("button");
                option.type = "button";
                option.className = "effect-picker-option";
                option.dataset.effectId = String(optionModel.id);
                option.setAttribute("role", "option");
                option.setAttribute("aria-selected", String(String(optionModel.id) === select.value));
                option.textContent = optionModel.label;
                const previewDescription = () => {
                    description.textContent = optionModel.description;
                };
                option.addEventListener("mouseenter", previewDescription);
                option.addEventListener("focus", previewDescription);
                option.addEventListener("click", () => {
                    if (isEditingBlocked()) return;
                    select.value = String(optionModel.id);
                    list.querySelectorAll("[role='option']").forEach(entry => {
                        entry.setAttribute("aria-selected", String(entry === option));
                    });
                    summary.textContent = optionModel.label;
                    description.textContent = optionModel.description;
                    details.open = false;
                    addButton.disabled = false;
                });
                list.appendChild(option);
            });
            const blocked = isEditingBlocked()
                || protectedNbt().active_effects_opaque === true
                || options.length === 0;
            details.classList.toggle("disabled", blocked);
            details.setAttribute("aria-disabled", String(blocked));
            if (blocked) details.open = false;
            addButton.disabled = blocked || select.value === "";
        }

        function syncEffectsFromUI() {
            doc.querySelectorAll("#effectsContainer .effect-row").forEach(row => {
                syncEffectRow(parseInt(row.dataset.index, 10), row);
            });
        }

        function applyLiveEffectRowChange({ index, row, model, captureLiveEffectUndo }) {
            if (isEditingBlocked() || model.isProtectedEffect) return false;
            captureLiveEffectUndo();
            syncEffectRow(index, row);
            setEffectsTouched?.(true);
            setDirty?.(true);
            return true;
        }

        function renderEffectsList() {
            renderEffectPicker();
            const container = doc.getElementById("effectsContainer");
            if (!container) return;
            container.innerHTML = "";

            const listModel = effectsView.effectsListModel({
                protectedActiveEffects: protectedNbt().active_effects_opaque,
                effects: playerEffects(),
                effectsDb: effectsDb(),
            });
            if (listModel.listStateHtml) {
                container.innerHTML = listModel.listStateHtml;
                return;
            }

            listModel.rowModels.forEach(model => {
                const index = model.index;
                const row = effectsView.effectRowElement(model);
                if (isEditingBlocked()) {
                    row.querySelectorAll("input, select, textarea, button").forEach(control => {
                        control.disabled = true;
                    });
                }
                const captureLiveEffectUndo = () => {
                    if (row.dataset.undoCaptured !== "1") {
                        pushUndo?.();
                        row.dataset.undoCaptured = "1";
                    }
                };
                [
                    [".eff-level", "input"],
                    [".eff-duration", "input"],
                    [".eff-particles", "change"],
                ].forEach(([selector, eventName]) => {
                    const input = row.querySelector(selector);
                    input?.addEventListener(eventName, () => {
                        if (isEditingBlocked()) return;
                        logic.clampInputToDeclaredRange(input);
                        applyLiveEffectRowChange({ index, row, model, captureLiveEffectUndo });
                    });
                });
                row.querySelector(".effect-remove")?.addEventListener("click", () => {
                    if (isEditingBlocked()) return;
                    const decision = logic.removeEffectDecision({
                        protectedEffect: model.isProtectedEffect,
                    });
                    if (!decision.ok) {
                        showToast?.(decision.message, "warning", decision.toastMs);
                        return;
                    }
                    pushUndo?.();
                    playerEffects().splice(index, 1);
                    setEffectsTouched?.(true);
                    renderEffectsList();
                    setDirty?.(true);
                });

                container.appendChild(row);
            });
        }

        function applyLiveAbilityInputChange(captureLiveAbilityUndo) {
            if (isEditingBlocked()) return false;
            const collected = collectAbilitiesFromUI();
            if (collected === null) return false;
            captureLiveAbilityUndo();
            setPlayerAbilities?.(collected);
            setAbilitiesTouched?.(true);
            renderAbilityRiskNote();
            setDirty?.(true);
            return true;
        }

        function wireStatsApply() {
            doc.getElementById("btnApplyStats")?.addEventListener("click", () => {
                if (isEditingBlocked()) return;
                const result = abilityState.applyStatsUpdate({
                    stats: getPlayerStats?.() || {},
                    values: abilityView.readStatsFormValues(statsFormElements?.()),
                    touchedFields: getTouchedStatsFields?.(),
                    protectedNbt: protectedNbt(),
                });

                if (result.error) {
                    logStatus?.(result.error, "error");
                    showToast?.(result.error, "error", 4500);
                    return;
                }
                if (!result.changed) {
                    logStatus?.(t("Keine Statistikänderung erkannt."), "warning");
                    return;
                }

                pushUndo?.();
                setPlayerStats?.(result.nextStats);
                getTouchedStatsFields?.()?.clear?.();

                setDirty?.(true);
                logStatus?.(t("Spieler-Statistiken aktualisiert (Speichern zum Bestätigen)"), "success");

                doc.querySelectorAll("#dashStats input, #dashStats select").forEach(el => {
                    el.classList.add("stat-changed");
                    setTimeout(() => el.classList.remove("stat-changed"), 2000);
                });
            });
        }

        function wireAddEffect() {
            const select = doc.getElementById("effectToAdd");
            const details = doc.getElementById("effectPickerDetails");
            details?.querySelector("summary")?.addEventListener("click", event => {
                if (details.classList.contains("disabled")) event.preventDefault();
            });
            details?.addEventListener("keydown", event => {
                if (event.key === "Escape") {
                    details.open = false;
                    details.querySelector("summary")?.focus();
                }
            });
            doc.getElementById("btnAddEffect")?.addEventListener("click", () => {
                if (isEditingBlocked()) return;
                const decision = logic.addEffectDecision({
                    protectedActiveEffects: protectedNbt().active_effects_opaque,
                    effects: playerEffects(),
                    effectsDb: effectsDb(),
                    selectedEffectId: select?.value,
                });
                if (!decision.ok) {
                    showToast?.(decision.message, "warning", decision.toastMs);
                    return;
                }
                pushUndo?.();
                setEffectsTouched?.(true);
                playerEffects().push(decision.effect);
                renderEffectsList();
                setDirty?.(true);
                showToast?.(decision.toastMessage);
                recordAction?.(decision.recordLabel, "edit");
            });
        }

        function wireAbilitySpeedReset() {
            doc.getElementById("btnResetAbilitySpeeds")?.addEventListener("click", () => {
                if (isEditingBlocked()) return;
                const flyInput = doc.getElementById("abFlySpeed");
                const walkInput = doc.getElementById("abWalkSpeed");
                if (!flyInput || !walkInput || flyInput.disabled || walkInput.disabled) return;
                if (Number(flyInput.value) === 0.05 && Number(walkInput.value) === 0.1) {
                    showToast?.(t("Die Geschwindigkeiten entsprechen bereits den Vanilla-Standardwerten."), "info", 2200);
                    return;
                }
                pushUndo?.();
                flyInput.value = "0.05";
                walkInput.value = "0.1";
                const collected = collectAbilitiesFromUI();
                if (collected === null) return;
                setPlayerAbilities?.(collected);
                setAbilitiesTouched?.(true);
                setDirty?.(true);
                showToast?.(t("Bewegungsgeschwindigkeiten auf Vanilla-Standardwerte zurückgesetzt."));
                recordAction?.(t("Bewegungsgeschwindigkeiten zurückgesetzt"), "edit");
            });
        }

        function wireApplyEffects() {
            doc.getElementById("btnApplyEffects")?.addEventListener("click", () => {
                if (isEditingBlocked()) return;
                const nbt = protectedNbt();
                const plan = logic.effectsAbilitiesApplyPlan({
                    protectedActiveEffects: nbt.active_effects_opaque,
                    hasActiveEffectsTag: nbt.has_active_effects_tag === true,
                    effectsCount: playerEffects().length,
                    effectsTouched: Boolean(getEffectsTouched?.()),
                    shouldSyncAbilities: Boolean(getShouldSyncAbilitiesFromUIForSave?.()),
                });
                const outcome = logic.effectsAbilitiesApplyOutcome({
                    plan,
                    collectedAbilities: plan.syncAbilities ? collectAbilitiesFromUI() : null,
                });
                if (!outcome.hasWork) {
                    logStatus?.(t("Keine Effekt-/Fähigkeitsänderung erkannt."), "warning");
                    showToast?.(t("Keine Änderung erkannt."), "warning", 2500);
                    return;
                }
                pushUndo?.();
                if (outcome.syncEffects) {
                    syncEffectsFromUI();
                    setEffectsTouched?.(true);
                }
                if (outcome.applyAbilities) {
                    setPlayerAbilities?.(outcome.collectedAbilities);
                    setAbilitiesTouched?.(true);
                    renderAbilityRiskNote();
                }
                setDirty?.(true);
                logStatus?.(t("Effekte & Fähigkeiten aktualisiert (Speichern zum Bestätigen)"), "success");
                recordAction?.(t("Effekte & Fähigkeiten aktualisiert"), "edit");
            });
        }

        function wireLiveAbilityInputs() {
            doc.querySelectorAll("#dashEffects .abilities-section input").forEach(input => {
                const captureLiveAbilityUndo = () => {
                    if (input.dataset.undoCaptured !== "1") {
                        pushUndo?.();
                        input.dataset.undoCaptured = "1";
                    }
                };
                input.addEventListener("focus", () => {
                    input.dataset.undoCaptured = "0";
                });
                input.addEventListener("input", () => {
                    logic.clampInputToDeclaredRange(input);
                    applyLiveAbilityInputChange(captureLiveAbilityUndo);
                });
                input.addEventListener("change", () => {
                    logic.clampInputToDeclaredRange(input);
                    applyLiveAbilityInputChange(captureLiveAbilityUndo);
                });
            });
        }

        function wire() {
            wireStatsApply();
            wireAddEffect();
            wireAbilitySpeedReset();
            wireApplyEffects();
            wireLiveAbilityInputs();
        }

        return {
            collectAbilitiesFromUI,
            loadAbilitiesUI,
            protectedAbilityFields,
            protectedStatFields,
            removeProtectedStatsFromPayload,
            renderAbilityRiskNote,
            renderEffectsList,
            setStatsProtectionUI,
            syncEffectsFromUI,
            wire,
        };
    }

    window.MCBEEffectsLogic = {
        ...logic,
        createEffectsAbilitiesController,
        createStatsFormController,
        createConfiguredStatsFormController,
    };
}());
