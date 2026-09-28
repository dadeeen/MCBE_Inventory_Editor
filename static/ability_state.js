(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function protectedAbilityFields(protectedNbt = {}) {
        return (protectedNbt && protectedNbt.ability_fields_opaque && typeof protectedNbt.ability_fields_opaque === "object")
            ? protectedNbt.ability_fields_opaque
            : {};
    }

    function protectedStatFields(protectedNbt = {}) {
        return (protectedNbt && protectedNbt.stat_fields_opaque && typeof protectedNbt.stat_fields_opaque === "object")
            ? protectedNbt.stat_fields_opaque
            : {};
    }

    function isFieldProtected(fields, fieldName) {
        return Object.prototype.hasOwnProperty.call(fields || {}, fieldName);
    }

    function formatAbilitySpeed(value, fallback) {
        const numericValue = Number(value);
        const safeValue = Number.isFinite(numericValue) ? numericValue : fallback;
        return Number(safeValue.toFixed(4)).toString();
    }

    // Das Eingabefeld zeigt nur vier Nachkommastellen. Die Änderung eines Feldes
    // sammelt den gesamten Fähigkeitssatz ein, also auch die übrigen Felder; ohne den
    // Rückgriff auf den exakten Ausgangswert würde sie deren ungerundete Werte kürzen.
    function abilitySpeedFromFormValue(inputValue, currentValue, fallback) {
        const parsed = parseFloat(inputValue);
        const value = Number.isFinite(parsed) ? parsed : fallback;
        const exact = Number(currentValue);
        if (Number.isFinite(exact) && formatAbilitySpeed(exact, fallback) === formatAbilitySpeed(value, fallback)) {
            return exact;
        }
        return value;
    }

    function removeProtectedStatsFromPayload(statsPayload, protectedNbt = {}) {
        if (!statsPayload || typeof statsPayload !== "object") return statsPayload;
        if (protectedNbt.pos_opaque || protectedNbt.pos_missing) {
            delete statsPayload.pos;
            delete statsPayload.dimension_id;
        }
        if (protectedNbt.dimension_id_opaque || protectedNbt.dimension_id_missing) {
            delete statsPayload.dimension_id;
        }
        for (const fieldName of Object.keys(protectedStatFields(protectedNbt))) {
            delete statsPayload[fieldName];
        }
        return statsPayload;
    }

    function cloneJson(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function valuesEqual(a, b) {
        return JSON.stringify(a) === JSON.stringify(b);
    }

    function finiteNumber(value, fallback) {
        const parsed = parseFloat(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function clampNumber(value, fallback, min, max) {
        const parsed = parseInt(value, 10);
        if (!Number.isFinite(parsed)) return fallback;
        if (min > max) [min, max] = [max, min];
        return Math.min(Math.max(parsed, min), max);
    }

    function clampFiniteNumber(value, fallback, min, max) {
        const parsed = finiteNumber(value, fallback);
        if (min > max) [min, max] = [max, min];
        return Math.min(Math.max(parsed, min), max);
    }

    function strictFiniteNumber(value) {
        if (value === null || value === undefined || typeof value === "boolean") return null;
        if (typeof value === "string" && value.trim() === "") return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function strictVanillaDimensionId(value) {
        if (value === null || value === undefined || typeof value === "boolean") return null;
        if (typeof value === "string" && value.trim() === "") return null;
        const parsed = Number(value);
        return Number.isInteger(parsed) && [0, 1, 2].includes(parsed) ? parsed : null;
    }

    // Bedrock-Positionen tragen mehr Nachkommastellen, als ein Formular sinnvoll
    // anzeigen kann. Die Anzeige rundet deshalb, und positionFromFormValues
    // stellt für jede unveränderte Achse den exakten Ausgangswert wieder her.
    function formatPositionForDisplay(value) {
        const parsed = strictFiniteNumber(value);
        return parsed === null ? "" : parsed.toFixed(2);
    }

    function positionFromFormValues(values = {}, currentPosition = null) {
        const position = [
            strictFiniteNumber(values.posX),
            strictFiniteNumber(values.posY),
            strictFiniteNumber(values.posZ),
        ];
        if (position.some(value => value === null)) return null;
        if (!Array.isArray(currentPosition)) return position;
        // Eine Achse, deren angezeigter Wert unverändert ist, darf nicht auf die
        // Anzeigegenauigkeit zurückfallen: ein reiner Dimensionswechsel schreibt
        // die Position mit und würde den Spieler sonst um bis zu 5 mm versetzen.
        return position.map((value, index) => {
            const exact = strictFiniteNumber(currentPosition[index]);
            return exact !== null && formatPositionForDisplay(exact) === formatPositionForDisplay(value) ? exact : value;
        });
    }

    function convertPositionBetweenDimensions(position, fromDimension, toDimension) {
        const source = strictVanillaDimensionId(fromDimension);
        const target = strictVanillaDimensionId(toDimension);
        if (!Array.isArray(position) || position.length !== 3) return null;
        const normalizedPosition = position.map(strictFiniteNumber);
        if (normalizedPosition.some(value => value === null)) return null;
        let factor = null;
        if (source === 0 && target === 1) factor = 1 / 8;
        if (source === 1 && target === 0) factor = 8;
        if (factor === null) return null;
        const converted = [
            normalizedPosition[0] * factor,
            normalizedPosition[1],
            normalizedPosition[2] * factor,
        ];
        return converted.every(Number.isFinite) ? converted : null;
    }

    function touchedFieldSet(touchedFields = []) {
        if (typeof touchedFields?.has === "function") return touchedFields;
        if (typeof touchedFields?.[Symbol.iterator] === "function") return new Set(Array.from(touchedFields));
        return new Set(Array.isArray(touchedFields) ? touchedFields : []);
    }

    function inputValueDiffersFromStat(inputValue, currentValue, parser) {
        if (inputValue === undefined || inputValue === null) return false;
        return !valuesEqual(parser(inputValue), currentValue);
    }

    function applyStatsUpdate({
        stats = {},
        values = {},
        touchedFields = [],
        protectedNbt = {},
    } = {}) {
        const nextStats = cloneJson(stats || {});
        const touched = touchedFieldSet(touchedFields);
        const statFields = protectedStatFields(protectedNbt);
        let changed = false;

        const positionEditable = !protectedNbt.pos_opaque && !protectedNbt.pos_missing;
        const dimensionEditable = positionEditable
            && !protectedNbt.dimension_id_opaque
            && !protectedNbt.dimension_id_missing;
        const positionTouched = touched.has("pos");
        const dimensionTouched = touched.has("dimension_id");
        let nextPosition = null;
        let nextDimensionId = null;

        if (positionEditable && (positionTouched || dimensionTouched && dimensionEditable)) {
            nextPosition = positionFromFormValues(values, nextStats.pos);
            if (!nextPosition) {
                return {
                    changed: false,
                    nextStats,
                    error: t("X, Y und Z müssen vollständig ausgefüllte, endliche Zahlen sein."),
                };
            }
        }
        if (dimensionEditable && dimensionTouched) {
            nextDimensionId = strictVanillaDimensionId(values.dimensionId);
            if (nextDimensionId === null) {
                return {
                    changed: false,
                    nextStats,
                    error: t("Bitte eine unterstützte Spielerdimension auswählen."),
                };
            }
        }
        if (nextPosition && !valuesEqual(nextPosition, nextStats.pos)) {
            nextStats.pos = nextPosition;
            changed = true;
        }
        if (nextDimensionId !== null) {
            if (!valuesEqual(nextDimensionId, nextStats.dimension_id)) {
                nextStats.dimension_id = nextDimensionId;
                changed = true;
            }
        }

        [
            ["health", "health", value => clampFiniteNumber(value, 20.0, 0, 1024)],
            ["xp_level", "xpLevel", value => clampNumber(value, 0, 0, 24791)],
            ["xp_progress", "xpProgress", value => clampFiniteNumber(value, 0.0, 0, 99.99) / 100],
            ["food_level", "foodLevel", value => clampNumber(value, 20, 0, 20)],
            ["food_saturation", "foodSaturation", value => clampFiniteNumber(value, 20.0, 0.0, 20.0)],
        ].forEach(([fieldName, valueKey, parser]) => {
            if (!touched.has(fieldName) || isFieldProtected(statFields, fieldName)) return;
            if (!inputValueDiffersFromStat(values[valueKey], nextStats[fieldName], parser)) return;
            nextStats[fieldName] = parser(values[valueKey]);
            changed = true;
        });

        return { changed, nextStats };
    }

    // Vanilla-Standardwerte der editierbaren Geschwindigkeiten. movement_speed ist
    // das Attribut minecraft:movement, die übrigen liegen im abilities-Compound.
    const ABILITY_SPEED_DEFAULTS = Object.freeze({
        movement_speed: 0.1,
        walk_speed: 0.1,
        fly_speed: 0.05,
        vertical_fly_speed: 1.0,
    });

    // Grund, aus dem das Backend minecraft:movement schützt ("missing",
    // "modifiers" oder "value"), sonst ein leerer Text.
    function movementSpeedLock(protectedNbt = {}) {
        const reason = protectedNbt?.movement_speed_locked;
        return typeof reason === "string" ? reason : "";
    }

    function isAbilitySpeedLocked(fieldName, protectedNbt = {}) {
        return fieldName === "movement_speed"
            ? movementSpeedLock(protectedNbt) !== ""
            : isFieldProtected(protectedAbilityFields(protectedNbt), fieldName);
    }

    function collectAbilitiesFromValues(playerAbilities = {}, protectedNbt = {}, speeds = {}) {
        if (protectedNbt.abilities_opaque === true || playerAbilities?._opaque === true) return null;
        const next = { ...(playerAbilities || {}) };
        delete next._opaque;
        Object.keys(protectedAbilityFields(protectedNbt)).forEach(fieldName => { delete next[fieldName]; });
        Object.entries(ABILITY_SPEED_DEFAULTS).forEach(([fieldName, fallback]) => {
            if (isAbilitySpeedLocked(fieldName, protectedNbt)) {
                delete next[fieldName];
                return;
            }
            next[fieldName] = abilitySpeedFromFormValue(speeds[fieldName], playerAbilities?.[fieldName], fallback);
        });
        return next;
    }

    window.MCBEAbilityState = {
        ABILITY_SPEED_DEFAULTS,
        applyStatsUpdate,
        collectAbilitiesFromValues,
        convertPositionBetweenDimensions,
        formatAbilitySpeed,
        formatPositionForDisplay,
        isAbilitySpeedLocked,
        isFieldProtected,
        movementSpeedLock,
        protectedAbilityFields,
        protectedStatFields,
        removeProtectedStatsFromPayload,
    };
}());
