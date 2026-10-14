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
        let conversionOriginalPosition = null;
        let conversionSourceDimension = null;

        function formElements() {
            return elements;
        }

        function conversionPosition(values) {
            // Preserve stored precision when a displayed coordinate is unchanged.
            return abilityState?.positionFromFormValues
                ? abilityState.positionFromFormValues(values, getPlayerStats?.()?.pos)
                : [values.posX, values.posY, values.posZ];
        }

        function markTouched(field) {
            if (field) touchedFields.add(field);
        }

        function resetConversion() {
            conversionApplied = false;
            conversionOriginalPosition = null;
            refreshLocationConversion();
        }

        function render() {
            const model = abilityView.statsFormModel(getPlayerStats?.() || {});
            abilityView.applyStatsFormModel(formElements(), model);
            conversionApplied = false;
            conversionOriginalPosition = null;
            refreshLocationConversion();
        }

        function refreshLocationConversion() {
            if (!abilityView?.locationConversionModel || !abilityView?.applyLocationConversionModel) return;
            const values = abilityView.readStatsFormValues(formElements());
            const sourceDimension = getPlayerStats?.()?.dimension_id;
            // Applying the form starts a new conversion from the accepted dimension.
            if (sourceDimension !== conversionSourceDimension) {
                conversionApplied = false;
                conversionOriginalPosition = null;
                conversionSourceDimension = sourceDimension;
            }
            const targetDimension = Number(sourceDimension) === 0 ? 1 : 0;
            const source = Number(sourceDimension);
            const target = Number(targetDimension);
            const supportedPair = (source === 0 && target === 1) || (source === 1 && target === 0);
            const convertedPosition = supportedPair
                ? abilityState?.convertPositionBetweenDimensions?.(
                    conversionPosition(values),
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
                targetDimension: values.dimensionId,
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
                if (elements.convertLocation.disabled) return;
                if (conversionApplied && conversionOriginalPosition) {
                    elements.dimensionId.value = conversionOriginalPosition[2];
                    elements.posX.value = conversionOriginalPosition[0];
                    elements.posZ.value = conversionOriginalPosition[1];
                    conversionApplied = false;
                    conversionOriginalPosition = null;
                    markTouched("pos");
                    refreshLocationConversion();
                    return;
                }
                const values = abilityView.readStatsFormValues(formElements());
                const position = conversionPosition(values);
                const converted = abilityState?.convertPositionBetweenDimensions?.(
                    position,
                    getPlayerStats?.()?.dimension_id,
                    Number(getPlayerStats?.()?.dimension_id) === 0 ? 1 : 0,
                );
                if (!converted) return;
                conversionOriginalPosition = [elements.posX.value, elements.posZ.value, elements.dimensionId.value];
                elements.dimensionId.value = String(Number(getPlayerStats?.()?.dimension_id) === 0 ? 1 : 0);
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
            resetConversion,
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

    const ABILITY_SPEED_INPUT_IDS = Object.freeze({
        movement_speed: "abMovementSpeed",
        walk_speed: "abWalkSpeed",
        fly_speed: "abFlySpeed",
        vertical_fly_speed: "abVerticalFlySpeed",
    });

    function createEffectsAbilitiesController({
        doc = document,
        statsFormElements,
        getTouchedStatsFields,
        getProtectedNbt,
        getPlayerStats,
        setPlayerStats,
        onStatsApplied = () => {},
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
                disabled,
                protectedFields: protectedAbilityFields(),
                movementLock: abilityState.movementSpeedLock(protectedNbt()),
            }).map(model => ({ ...model, blocked: isEditingBlocked() }));
            abilityView.applyAbilityControlModels(doc, models);
            const resetButton = doc.getElementById("btnResetAbilitySpeeds");
            if (resetButton) {
                // Der Reset betrifft nur die editierbaren Felder; ein gesperrtes
                // Feld allein deaktiviert ihn nicht.
                abilityView.applyControlState(resetButton, {
                    disabled: models.every(model => model.disabled),
                    blocked: isEditingBlocked(),
                });
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
                blocked: isEditingBlocked(),
            }));
            abilityView.applyStatProtectionControlModels(statsFormElements?.(), models);
            const locationElements = statsFormElements?.() || {};
            const locationModel = abilityView.locationConversionModel?.({
                sourceDimension: getPlayerStats?.()?.dimension_id,
                targetDimension: locationElements.dimensionId?.value,
                blocked: models.some(model => ["dimensionId", "posX", "posY", "posZ"].includes(model.key) && model.disabled),
            });
            abilityView.applyLocationConversionModel?.(locationElements.convertLocation, { ...locationModel, blocked: isEditingBlocked() });
            abilityView.applyLocationConversionNote?.(locationElements.convertLocationNote, locationModel);
            const applyButton = doc.getElementById("btnApplyStats");
            abilityView.applyControlState(applyButton, { disabled: false, blocked: isEditingBlocked() });
        }

        function removeProtectedStatsFromPayload(statsPayload) {
            return abilityState.removeProtectedStatsFromPayload(statsPayload, protectedNbt());
        }

        function loadAbilitiesUI() {
            let abilities = playerAbilities();
            if (!abilities || typeof abilities !== "object") abilities = {};
            const nbt = protectedNbt();
            const abilitiesOpaque = nbt.abilities_opaque === true || abilities._opaque === true;
            setAbilityControlsDisabled(abilitiesOpaque);
            const defaults = abilityState.ABILITY_SPEED_DEFAULTS;
            const model = abilityView.abilityFormModel({
                movementSpeedValue: formatAbilitySpeed(abilities.movement_speed, defaults.movement_speed),
                walkSpeedValue: formatAbilitySpeed(abilities.walk_speed, defaults.walk_speed),
                flySpeedValue: formatAbilitySpeed(abilities.fly_speed, defaults.fly_speed),
                verticalFlySpeedValue: formatAbilitySpeed(abilities.vertical_fly_speed, defaults.vertical_fly_speed),
            });
            abilityView.applyAbilityFormModel(doc, model);
            abilityView.applyMovementLockNoteModel(doc.getElementById("abilityMovementLockNote"), abilityView.movementLockNoteModel({
                abilitiesOpaque,
                reason: abilityState.movementSpeedLock(nbt),
            }));
        }

        function collectAbilitiesFromUI() {
            return abilityState.collectAbilitiesFromValues(
                playerAbilities(),
                protectedNbt(),
                abilityView.readAbilitySpeedValues(doc),
            );
        }

        function syncEffectRow(index, row) {
            const effects = playerEffects();
            if (!Number.isInteger(index) || !effects[index] || !row) return;
            if (effects[index].opaque === true || !effectsDb()[effects[index].id]) return;
            Object.assign(
                effects[index],
                effectsView.effectPatchFromRowValues(effectsView.readEffectRowValues(row), effects[index]),
            );
        }

        function renderEffectPicker() {
            const select = doc.getElementById("effectToAdd");
            const addButton = doc.getElementById("btnAddEffect");
            const list = doc.getElementById("effectPickerList");
            if (!select || !addButton || !list) return;
            const used = new Set(playerEffects().map(effect => Number(effect.id)));
            const options = logic.availableEffectOptions([], effectsDb());
            const query = (doc.getElementById("effectCatalogSearch")?.value || "").trim().toLocaleLowerCase();
            const selected = options.find(option => String(option.id) === select.value && !used.has(option.id));
            if (!selected) select.value = "";
            doc.getElementById("effectPickerSummary").textContent = selected?.label || t("Effekt auswählen …");
            doc.getElementById("effectPickerDescription").textContent = selected?.description || t("Wähle einen Effekt aus, um Beschreibung und Werte anzuzeigen.");
            list.innerHTML = "";
            for (const optionModel of options) {
                if (query && ![optionModel.label, ...effectsDb()[optionModel.id].slice(0, 2), String(optionModel.id)].join(" ").toLocaleLowerCase().includes(query)) continue;
                const option = doc.createElement("button");
                option.type = "button";
                option.className = "effect-picker-option";
                option.dataset.effectId = String(optionModel.id);
                option.setAttribute("aria-pressed", String(String(optionModel.id) === select.value));
                option.disabled = used.has(optionModel.id);
                option.textContent = optionModel.label + (option.disabled ? " · " + t("Bereits aktiv") : "");
                option.addEventListener("click", () => {
                    if (isEditingBlocked()) return;
                    select.value = String(optionModel.id);
                    renderEffectPicker();
                    list.querySelector(`[data-effect-id="${optionModel.id}"]`)?.focus();
                });
                list.appendChild(option);
            }
            if (!list.children.length) list.textContent = t("Keine passenden Effekte gefunden.");
            const blocked = protectedNbt().active_effects_opaque === true || options.length === 0;
            abilityView.applyControlState(doc.getElementById("btnOpenEffectPicker"), { disabled: blocked, blocked: isEditingBlocked() });
            abilityView.applyControlState(addButton, { disabled: blocked || !selected, blocked: isEditingBlocked() });
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

            let liveUndoInput = null;
            listModel.rowModels.forEach(model => {
                const index = model.index;
                const row = effectsView.effectRowElement(model);
                if (isEditingBlocked()) {
                    row.querySelectorAll("input, select, textarea, button").forEach(control => {
                        abilityView.applyControlState(control, { disabled: control.disabled, title: control.title, blocked: true });
                    });
                }
                [
                    [".eff-level", "input"],
                    [".eff-duration", "input"],
                    [".eff-particles", "change"],
                ].forEach(([selector, eventName]) => {
                    const input = row.querySelector(selector);
                    const captureLiveEffectUndo = () => {
                        // Group typing only within this focused control. Checkbox
                        // changes are discrete actions, including repeated clicks.
                        if (liveUndoInput !== input || eventName === "change") {
                            pushUndo?.();
                            liveUndoInput = input;
                        }
                    };
                    input?.addEventListener("blur", () => {
                        if (liveUndoInput === input) liveUndoInput = null;
                    });
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
                onStatsApplied();

                setDirty?.(true);
                logStatus?.(t("Spieler-Statistiken aktualisiert (Speichern zum Bestätigen)"), "info");

                doc.querySelectorAll("#dashStats input, #dashStats select").forEach(el => {
                    el.classList.add("stat-changed");
                    setTimeout(() => el.classList.remove("stat-changed"), 2000);
                });
            });
        }

        function wireAddEffect() {
            const select = doc.getElementById("effectToAdd");
            const dialog = doc.getElementById("effectPickerDialog");
            const trigger = doc.getElementById("btnOpenEffectPicker");
            trigger?.addEventListener("click", () => {
                if (isEditingBlocked() || protectedNbt().active_effects_opaque === true) return;
                select.value = "";
                doc.getElementById("effectCatalogSearch").value = "";
                doc.getElementById("effectCatalogLevel").value = "1";
                doc.getElementById("effectCatalogDuration").value = "30";
                renderEffectPicker();
                dialog.showModal();
                doc.getElementById("effectCatalogSearch").focus();
            });
            doc.getElementById("btnCloseEffectPicker")?.addEventListener("click", () => dialog.close());
            dialog?.addEventListener("close", () => trigger?.focus());
            dialog?.addEventListener("keydown", event => {
                // Keep application shortcuts out of the modal while retaining
                // native text editing, Tab navigation and Escape-to-close.
                event.stopPropagation();
                if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") event.preventDefault();
            });
            doc.getElementById("effectCatalogSearch")?.addEventListener("input", renderEffectPicker);
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
                const level = doc.getElementById("effectCatalogLevel");
                const duration = doc.getElementById("effectCatalogDuration");
                if (!level.reportValidity() || !duration.reportValidity()) return;
                Object.assign(decision.effect, effectsView.effectPatchFromRowValues({
                    levelValue: level.value, durationSecondsValue: duration.value, showParticles: true,
                }));
                pushUndo?.();
                setEffectsTouched?.(true);
                playerEffects().push(decision.effect);
                dialog?.close();
                renderEffectsList();
                setDirty?.(true);
                showToast?.(decision.toastMessage);
                recordAction?.(decision.recordLabel, "edit");
            });
        }

        function wireAbilitySpeedReset() {
            doc.getElementById("btnResetAbilitySpeeds")?.addEventListener("click", () => {
                if (isEditingBlocked()) return;
                const defaults = abilityState.ABILITY_SPEED_DEFAULTS;
                const inputs = Object.entries(ABILITY_SPEED_INPUT_IDS)
                    .map(([fieldName, id]) => [doc.getElementById(id), defaults[fieldName]])
                    .filter(([input]) => input && !input.disabled);
                if (!inputs.length) return;
                if (inputs.every(([input, value]) => Number(input.value) === value)) {
                    showToast?.(t("Die Geschwindigkeiten entsprechen bereits den Vanilla-Standardwerten."), "info", 2200);
                    return;
                }
                pushUndo?.();
                inputs.forEach(([input, value]) => { input.value = String(value); });
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
                }
                setDirty?.(true);
                logStatus?.(t("Effekte & Fähigkeiten aktualisiert (Speichern zum Bestätigen)"), "info");
                recordAction?.(t("Effekte & Fähigkeiten aktualisiert"), "edit");
            });
        }

        // Bedrock nutzt walkSpeed nur als Bezug für das Sichtfeld. Stimmt es mit
        // minecraft:movement überein, bleibt das Sichtfeld beim Laufen normal;
        // deshalb zieht eine Änderung der Laufgeschwindigkeit das Feld mit.
        function syncWalkSpeedWithMovement(input) {
            if (input.id !== ABILITY_SPEED_INPUT_IDS.movement_speed) return;
            const walkInput = doc.getElementById(ABILITY_SPEED_INPUT_IDS.walk_speed);
            if (walkInput && !walkInput.disabled) walkInput.value = input.value;
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
                    syncWalkSpeedWithMovement(input);
                    applyLiveAbilityInputChange(captureLiveAbilityUndo);
                });
                input.addEventListener("change", () => {
                    logic.clampInputToDeclaredRange(input);
                    syncWalkSpeedWithMovement(input);
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
