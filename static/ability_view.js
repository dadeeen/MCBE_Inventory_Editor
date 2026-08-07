(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    // ability_state.js wird vor dieser Datei geladen und besitzt die
    // Rundungsregel, weil applyStatsUpdate sie beim Zurückgewinnen exakter
    // Achsen spiegeln muss. Eine zweite Definition hier würde auseinanderlaufen.
    function formatPositionForDisplay(value) {
        return window.MCBEAbilityState.formatPositionForDisplay(value);
    }

    const ABILITY_CONTROLS = [
        ["abMayfly", "mayfly", "mayfly"],
        ["abFlying", "flying", "flying"],
        ["abInvulnerable", "invulnerable", "invulnerable"],
        ["abMaybuild", "maybuild", "mayBuild"],
        ["abInstabuild", "instabuild", "instabuild"],
        ["abFlySpeed", "fly_speed", "flySpeed"],
        ["abWalkSpeed", "walk_speed", "walkSpeed"],
    ];

    const STAT_CONTROLS = [
        ["health", "health", "Health"],
        ["gamemode", "gamemode", "PlayerGameType"],
        ["xpLevel", "xp_level", "XPLevel"],
        ["xpProgress", "xp_progress", "XPProgress"],
        ["foodLevel", "food_level", "foodLevel"],
        ["foodSaturation", "food_saturation", "foodSaturationLevel"],
    ];

    function abilityControlModels({
        disabled = false,
        protectedFields = {},
    } = {}) {
        return ABILITY_CONTROLS.map(([id, fieldName, tagName]) => {
            const fieldProtected = Object.prototype.hasOwnProperty.call(protectedFields || {}, fieldName);
            let title = "";
            if (disabled) {
                title = t("abilities-Tag hat einen unbekannten NBT-Typ und wird geschützt erhalten.");
            } else if (fieldProtected) {
                title = t("{tag}-Tag hat einen unerwarteten NBT-Typ und wird geschützt erhalten.", { tag: protectedFields[fieldName] || tagName });
            }
            return {
                id,
                disabled: disabled || fieldProtected,
                title,
            };
        });
    }

    function abilityFormModel({
        abilities = {},
        flySpeedValue = "",
        walkSpeedValue = "",
    } = {}) {
        return {
            checks: {
                abMayfly: abilities?.mayfly === true,
                abFlying: abilities?.flying === true,
                abInvulnerable: abilities?.invulnerable === true,
                abMaybuild: abilities?.maybuild !== false,
                abInstabuild: abilities?.instabuild === true,
            },
            values: {
                abFlySpeed: String(flySpeedValue),
                abWalkSpeed: String(walkSpeedValue),
            },
        };
    }

    function statProtectionControlModels({
        posOpaque = false,
        posMissing = false,
        dimensionOpaque = false,
        dimensionMissing = false,
        protectedFields = {},
    } = {}) {
        const positionUnavailable = posOpaque === true || posMissing === true;
        const positionTitle = posMissing
            ? t("Pos-Tag fehlt; der Standort wird sicherheitshalber nicht neu erzeugt.")
            : posOpaque
                ? t("Pos-Tag hat einen unbekannten NBT-Typ und wird geschützt erhalten.")
                : "";
        const models = ["posX", "posY", "posZ"].map(key => ({
            key,
            disabled: positionUnavailable,
            title: positionTitle,
        }));
        const dimensionUnavailable = positionUnavailable || dimensionOpaque === true || dimensionMissing === true;
        let dimensionTitle = "";
        if (positionUnavailable) {
            dimensionTitle = t("Ein Dimensionswechsel benötigt eine sicher editierbare Spielerposition.");
        } else if (dimensionMissing) {
            dimensionTitle = t("DimensionId fehlt; die Spielerdimension wird sicherheitshalber nicht neu erzeugt.");
        } else if (dimensionOpaque) {
            dimensionTitle = t("DimensionId hat einen unbekannten Wert oder NBT-Typ und wird geschützt erhalten.");
        }
        models.unshift({
            key: "dimensionId",
            disabled: dimensionUnavailable,
            title: dimensionTitle,
        });
        STAT_CONTROLS.forEach(([key, fieldName, tagName]) => {
            const fieldProtected = Object.prototype.hasOwnProperty.call(protectedFields || {}, fieldName);
            models.push({
                key,
                disabled: fieldProtected,
                title: fieldProtected
                    ? t("{tag}-Tag hat einen unerwarteten NBT-Typ und wird geschützt erhalten.", { tag: protectedFields[fieldName] || tagName })
                    : "",
            });
        });
        return models;
    }

    function gamemodeDisplayModel(value) {
        const normalized = Number.isFinite(Number(value)) ? Number(value) : null;
        const labels = {
            0: t("Überleben (Survival)"),
            1: t("Kreativ (Creative)"),
            2: t("Abenteuer (Adventure)"),
            3: t("Zuschauer (Spectator)"),
            5: t("Standard/Weltmodus (Default)"),
        };
        return {
            value: Object.prototype.hasOwnProperty.call(labels, normalized)
                ? t("{label} · NBT-Wert {value}", { label: labels[normalized], value: normalized })
                : t("Unbekannter oder serverspezifischer Wert · NBT-Wert {value}", { value: normalized ?? "?" }),
            readOnly: true,
            title: t("Read-only: Dieser Player-Gamemode wird nur angezeigt. Der Editor schreibt ihn nicht; Welt-/Servermodus kann abweichen."),
        };
    }

    function statsFormModel(stats = {}) {
        const rawXpPercent = Number(stats.xp_progress) * 100;
        const displayXpPercent = Number(stats.xp_progress) >= 0 && Number(stats.xp_progress) < 1
            ? Math.min(rawXpPercent, 99.99)
            : rawXpPercent;
        const dimensionId = stats.dimension_id === null
            || stats.dimension_id === undefined
            || stats.dimension_id === ""
            ? null
            : Number(stats.dimension_id);
        return {
            values: {
                dimensionId: [0, 1, 2].includes(dimensionId) ? String(dimensionId) : "",
                // Gerundete Anzeige, exakter Speicherwert: applyStatsUpdate
                // stellt für jede unveränderte Achse den vollen Ausgangswert
                // wieder her, damit ein reiner Dimensionswechsel die Position
                // nicht auf die Anzeigegenauigkeit zusammenstaucht.
                posX: formatPositionForDisplay(stats.pos?.[0] ?? 0),
                posY: formatPositionForDisplay(stats.pos?.[1] ?? 70),
                posZ: formatPositionForDisplay(stats.pos?.[2] ?? 0),
                health: stats.health.toFixed(1),
                xpLevel: stats.xp_level,
                xpProgress: Number(displayXpPercent.toFixed(2)).toString(),
                foodLevel: stats.food_level,
                foodSaturation: stats.food_saturation.toFixed(1),
            },
            gamemode: gamemodeDisplayModel(stats.gamemode),
        };
    }

    function applyAbilityControlModels(doc = document, models = []) {
        models.forEach(model => {
            const element = doc.getElementById?.(model.id);
            if (!element) return;
            element.disabled = Boolean(model.disabled);
            element.title = model.title || "";
        });
    }

    function applyAbilityFormModel(doc = document, model = {}) {
        Object.entries(model.checks || {}).forEach(([id, checked]) => {
            const element = doc.getElementById?.(id);
            if (!element) return;
            element.checked = Boolean(checked);
        });
        Object.entries(model.values || {}).forEach(([id, value]) => {
            const element = doc.getElementById?.(id);
            if (!element) return;
            element.value = value;
        });
    }

    function readAbilityFormValues(doc = document) {
        return {
            mayfly: doc.getElementById?.("abMayfly")?.checked === true,
            flying: doc.getElementById?.("abFlying")?.checked === true,
            invulnerable: doc.getElementById?.("abInvulnerable")?.checked === true,
            maybuild: doc.getElementById?.("abMaybuild")?.checked !== false,
            instabuild: doc.getElementById?.("abInstabuild")?.checked === true,
        };
    }

    function readAbilitySpeedValues(doc = document) {
        return {
            fly_speed: doc.getElementById?.("abFlySpeed")?.value,
            walk_speed: doc.getElementById?.("abWalkSpeed")?.value,
        };
    }

    function readStatsFormValues(elements = {}) {
        return {
            dimensionId: elements.dimensionId?.value,
            posX: elements.posX?.value,
            posY: elements.posY?.value,
            posZ: elements.posZ?.value,
            health: elements.health?.value,
            xpLevel: elements.xpLevel?.value,
            xpProgress: elements.xpProgress?.value,
            foodLevel: elements.foodLevel?.value,
            foodSaturation: elements.foodSaturation?.value,
        };
    }

    function applyStatProtectionControlModels(elements = {}, models = []) {
        models.forEach(model => {
            const element = elements[model.key];
            if (!element) return;
            element.disabled = Boolean(model.disabled);
            element.title = model.title || "";
        });
    }

    function applyStatsFormModel(elements = {}, model = {}) {
        Object.entries(model.values || {}).forEach(([key, value]) => {
            const element = elements[key];
            if (!element) return;
            element.value = value;
        });
        if (elements.gamemode && model.gamemode) {
            elements.gamemode.value = model.gamemode.value || "";
            elements.gamemode.readOnly = Boolean(model.gamemode.readOnly);
            elements.gamemode.title = model.gamemode.title || "";
        }
    }

    function locationConversionModel({
        sourceDimension,
        targetDimension,
        blocked = false,
        converted = false,
        positionInvalid = false,
    } = {}) {
        const source = sourceDimension === null || sourceDimension === undefined || sourceDimension === ""
            ? null
            : Number(sourceDimension);
        const target = targetDimension === null || targetDimension === undefined || targetDimension === ""
            ? null
            : Number(targetDimension);
        let label = t("Oberwelt ↔ Nether umrechnen");
        let title = t("Wähle als Ziel Oberwelt oder Nether. Die Umrechnung verändert nur X und Z; Y bleibt unverändert.");
        let available = false;
        if (source === 0 && target === 1) {
            label = t("Für Nether umrechnen (X/Z ÷ 8)");
            title = t("Rechnet die aktuell eingetragenen X-/Z-Koordinaten ausdrücklich für den Nether um.");
            available = true;
        } else if (source === 1 && target === 0) {
            label = t("Für Oberwelt umrechnen (X/Z × 8)");
            title = t("Rechnet die aktuell eingetragenen X-/Z-Koordinaten ausdrücklich für die Oberwelt um.");
            available = true;
        }
        if (converted) {
            label = t("Koordinaten umgerechnet");
            title = t("Die Umrechnung wurde einmal angewendet. Prüfe die Zielposition vor dem Übernehmen.");
        } else if (available && positionInvalid) {
            title = t("X, Y und Z müssen vollständig ausgefüllte, endliche Zahlen sein.");
        }
        // Browsers do not show a title tooltip on a disabled button, so the reason
        // has to be rendered as visible text next to it.
        let note = "";
        if (blocked) {
            note = t("Dimension oder Position sind für diese Welt gesperrt.");
        } else if (converted) {
            note = title;
        } else if (source === null) {
            note = t("Die Ausgangsdimension der Welt ist nicht bekannt. Eine Umrechnung ist deshalb nicht möglich.");
        } else if (source === 2) {
            note = t("Aus dem Ende gibt es keine Koordinatenumrechnung. Nur Oberwelt und Nether stehen im Verhältnis 1:8.");
        } else if (!available) {
            note = t("Nur zwischen Oberwelt und Nether möglich. Wähle oben die jeweils andere Dimension.");
        } else if (positionInvalid) {
            note = title;
        }
        return {
            disabled: blocked || !available || converted || positionInvalid,
            label,
            title,
            note,
        };
    }

    function applyLocationConversionNote(element, model = {}) {
        if (!element) return;
        element.hidden = !model.note;
        element.textContent = model.note || "";
    }

    function applyLocationConversionModel(element, model = {}) {
        if (!element) return;
        element.disabled = Boolean(model.disabled);
        element.textContent = model.label || "";
        element.title = model.title || "";
    }

    function abilityRiskNoteModel({
        abilitiesOpaque = false,
        playerAbilitiesOpaque = false,
        warnings = [],
    } = {}) {
        const visibleWarnings = (Array.isArray(warnings) ? warnings : []).filter(Boolean);
        const hidden = abilitiesOpaque || playerAbilitiesOpaque || visibleWarnings.length === 0;
        return {
            hidden,
            text: hidden ? "" : visibleWarnings.join(" "),
        };
    }

    function applyAbilityRiskNoteModel(element, model = {}) {
        if (!element) return;
        element.hidden = Boolean(model.hidden);
        element.textContent = model.text || "";
    }

    window.MCBEAbilityView = {
        abilityControlModels,
        abilityFormModel,
        abilityRiskNoteModel,
        applyAbilityControlModels,
        applyAbilityFormModel,
        applyAbilityRiskNoteModel,
        applyLocationConversionModel,
        applyLocationConversionNote,
        applyStatProtectionControlModels,
        applyStatsFormModel,
        gamemodeDisplayModel,
        locationConversionModel,
        readAbilityFormValues,
        readAbilitySpeedValues,
        readStatsFormValues,
        statsFormModel,
        statProtectionControlModels,
    };
}());
