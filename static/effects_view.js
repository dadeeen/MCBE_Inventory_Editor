(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function effectRowModel(effect = {}, index = 0, effectsDb = {}) {
        const info = effectsDb[effect.id];
        const isKnownEffect = !!info;
        const isProtectedEffect = effect.opaque === true || !isKnownEffect;
        const localizedNames = info ? window.MCBEI18n?.localizedPair?.(info[0], info[1]) : null;
        const unknownNames = window.MCBEI18n?.localizedPair?.("Unbekannter/future Effekt", "Unknown/future effect")
            || { primary: "Unbekannter/future Effekt", secondary: "Unknown/future effect" };
        const dbPrimary = localizedNames ? localizedNames.primary || String(effect.id) : info ? info[0] || info[1] : "";
        const dbSecondary = localizedNames ? localizedNames.secondary : info ? info[1] : "";
        const nameDe = info ? dbPrimary : t("Unbekannter Effekt ({id})", { id: effect.id });
        const nameEn = info ? dbSecondary : unknownNames.secondary || unknownNames.primary;
        const localizedDescriptions = info ? window.MCBEI18n?.localizedPair?.(info[2], info[3]) : null;
        const desc = effect.opaque_reason
            || (info
                ? localizedDescriptions
                    ? localizedDescriptions.primary
                    : info[3] || info[2] || ""
                : t("Nicht in der lokalen Effektdatenbank. Wird unverändert erhalten, solange er nicht entfernt wird."));
        return {
            index,
            isProtectedEffect,
            className: isProtectedEffect ? "effect-row unknown-effect" : "effect-row",
            nameDe,
            nameEn,
            desc,
            level: Math.max(1, Math.min(256, (Number(effect.amplifier) || 0) + 1)),
            durationSeconds: Math.floor(Number(effect.duration || 0) / 20),
            showParticles: effect.show_particles !== false,
        };
    }

    function effectRowHtml(model) {
        const disabledAttrs = model.isProtectedEffect ? `disabled title="${t("Effekt ist read-only und wird unverändert erhalten")}"` : "";
        const removeLabel = model.isProtectedEffect ? t("Geschützter Effekt wird vom Editor nicht gelöscht") : t("Effekt entfernen");
        const removeDisabledAttrs = `${model.isProtectedEffect ? "disabled " : ""}title="${removeLabel}" aria-label="${removeLabel}"`;
        return `
            <div class="effect-name" title="${escapeHtml(model.nameEn)}${model.desc ? " - " + escapeHtml(model.desc) : ""}">${escapeHtml(model.nameDe)}</div>
            ${model.desc ? `<div class="effect-desc">${escapeHtml(model.desc)}</div>` : ""}
            <div class="effect-controls">
                <div class="effect-field">
                    <label>${t("Stufe")}</label>
                    <input type="number" class="eff-level" min="1" max="256" value="${escapeHtml(model.level)}" data-index="${model.index}" ${disabledAttrs} />
                </div>
                <div class="effect-field">
                    <label>${t("Dauer (s)")}</label>
                    <input type="number" class="eff-duration" min="0" max="107374182" value="${escapeHtml(model.durationSeconds)}" data-index="${model.index}" ${disabledAttrs} />
                </div>
                <label class="effect-field" style="cursor:pointer;">
                    <span style="font-size:0.65rem;color:var(--text-secondary);text-transform:uppercase;">${t("Partikel")}</span>
                    <input type="checkbox" class="eff-particles" aria-label="${t("Partikel anzeigen")}" ${model.showParticles ? "checked" : ""} data-index="${model.index}" ${disabledAttrs} />
                </label>
                <button class="effect-remove" data-index="${model.index}" ${removeDisabledAttrs}>✕</button>
            </div>
        `;
    }

    function effectRowElement(model, doc = document) {
        const row = doc.createElement("div");
        row.className = model.className;
        row.dataset.index = String(model.index);
        row.innerHTML = effectRowHtml(model);
        return row;
    }

    function readEffectRowValues(row) {
        const levelEl = row?.querySelector?.(".eff-level");
        const durationEl = row?.querySelector?.(".eff-duration");
        const particlesEl = row?.querySelector?.(".eff-particles");
        return {
            levelValue: levelEl?.value,
            durationSecondsValue: durationEl?.value,
            showParticles: particlesEl ? particlesEl.checked : true,
        };
    }

    function effectPatchFromRowValues(values = {}, currentEffect = null) {
        const level = Math.max(1, Math.min(256, parseInt(values.levelValue, 10) || 1));
        const seconds = Math.max(0, parseInt(values.durationSecondsValue, 10) || 0);
        let duration = Math.min(seconds * 20, 2147483647);
        // Die Anzeige rundet Ticks auf ganze Sekunden ab. Solange das Sekundenfeld
        // unverändert aussieht, muss der exakte Tickwert erhalten bleiben -- der
        // Save-Aufbau synchronisiert die Effektzeilen auch ohne Effektänderung und
        // würde sonst bis zu 19 Ticks verlieren. Gleiches Muster wie bei den
        // Positionskoordinaten in ability_state.js.
        const exactDuration = Number(currentEffect?.duration);
        if (Number.isFinite(exactDuration) && exactDuration >= 0 && Math.floor(exactDuration / 20) === seconds) {
            duration = exactDuration;
        }
        return {
            amplifier: level - 1,
            duration,
            show_particles: values.showParticles !== false,
        };
    }

    function effectsListStateHtml({ protectedActiveEffects = false, hasEffects = false } = {}) {
        if (protectedActiveEffects) {
            return `<div class="no-backups warning">${t("ActiveEffects hat einen unbekannten NBT-Typ und wird geschützt erhalten.")}</div>`;
        }
        if (!hasEffects) {
            return `<div class="no-backups">${t("Keine aktiven Effekte.")}</div>`;
        }
        return "";
    }

    function effectsListModel({
        protectedActiveEffects = false,
        effects = [],
        effectsDb = {},
    } = {}) {
        const listStateHtml = effectsListStateHtml({
            protectedActiveEffects,
            hasEffects: Boolean(effects.length),
        });
        return {
            listStateHtml,
            rowModels: listStateHtml ? [] : effects.map((effect, index) => effectRowModel(effect, index, effectsDb)),
        };
    }

    window.MCBEEffectsView = {
        effectPatchFromRowValues,
        effectsListStateHtml,
        effectsListModel,
        effectRowElement,
        effectRowModel,
        effectRowHtml,
        readEffectRowValues,
    };
}());
