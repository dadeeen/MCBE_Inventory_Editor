(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function escapeHtml(value) {
        if (window.MCBEHtmlUtils?.escapeHtml) return window.MCBEHtmlUtils.escapeHtml(value ?? "");
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function emptyWorldAnalysisHtml() {
        return `<div class="no-backups">${t("Diagnose wird nach dem Laden einer Welt angezeigt.")}</div>`;
    }

    function compatibilityCardDetail(compatErrors, compatWarnings, compatNotes) {
        if (compatErrors.length) return t("{count} Fehler", { count: compatErrors.length });
        if (compatWarnings.length) return t("{count} Hinweis(e)", { count: compatWarnings.length });
        if (compatNotes.length) return t("Zusatzdaten erhalten");
        return t("Keine Hinweise");
    }

    function worldAnalysisHtml(analysis = {}, { inventorySlotCount = 36, enderChestSlotCount = 27 } = {}) {
        const compatErrors = Array.isArray(analysis.compat_errors) ? analysis.compat_errors : [];
        const compatWarnings = Array.isArray(analysis.compat_warnings) ? analysis.compat_warnings : [];
        const compatNotes = Array.isArray(analysis.compat_notes) ? analysis.compat_notes : [];
        const statusClass = compatErrors.length ? "bad" : compatWarnings.length ? "warn" : "ok";
        const statusText = compatErrors.length ? t("Prüfen nötig") : compatWarnings.length ? t("Mit Hinweisen") : "OK";
        const statusDetail = compatibilityCardDetail(compatErrors, compatWarnings, compatNotes);
        const inventory = analysis.inventory || {};
        const ender = analysis.ender || {};
        const hidden = analysis.hidden || {};
        const hints = [...new Set(compatErrors.concat(compatWarnings))];
        const restrictions = Array.isArray(analysis.restrictions) ? [...new Set(analysis.restrictions)] : [];
        const list = entries => `<ul>${entries.map(entry => `<li>${escapeHtml(entry)}</li>`).join("")}</ul>`;
        return `
        <div class="diagnostic-details-card${hints.length ? " warn" : ""}">
            <h4>${t("Was benötigt Aufmerksamkeit?")}</h4>
            ${hints.length ? list(hints) : `<p>${t("Keine Kompatibilitätsfehler oder -warnungen gemeldet.")}</p>`}
            ${hints.length ? `<p class="hint-text">${t("Prüfe die genannten Bereiche vor dem Speichern. Bei unklaren Meldungen kopiere die Diagnose für die Fehlersuche.")}</p>` : ""}
        </div>
        ${restrictions.length ? `<div class="diagnostic-details-card"><h4>${t("Einschränkungen beim Bearbeiten")}</h4>${list(restrictions)}<p class="hint-text">${t("Geschützte Daten bleiben unverändert. Fehlende Datenbereiche werden nur nach ausdrücklicher Bestätigung angelegt.")}</p></div>` : ""}
        <details class="diagnostic-details-card analysis-overview-details"><summary>${t("Überblick & Kennzahlen")}</summary>
        <div class="analysis-grid">
            <div class="overview-card"><span class="overview-label">${t("Spieler")}</span><strong>${escapeHtml(analysis.players_total ?? 0)}</strong><small>${t("{editable} editierbar · {exportOnly} nur Export", { editable: escapeHtml(analysis.players_editable ?? 0), exportOnly: escapeHtml(analysis.players_export_only ?? 0) })}</small></div>
            <div class="overview-card"><span class="overview-label">${t("Inventar")}</span><strong>${escapeHtml(inventory.used ?? 0)} / ${escapeHtml(inventorySlotCount)}</strong><small>${t("{damaged} beschädigt · {unknown} unbekannt", { damaged: escapeHtml(inventory.damaged ?? 0), unknown: escapeHtml(inventory.unknown ?? 0) })}</small></div>
            <div class="overview-card"><span class="overview-label">${t("Enderchest")}</span><strong>${escapeHtml(ender.used ?? 0)} / ${escapeHtml(enderChestSlotCount)}</strong><small>${analysis.has_ender_chest ? t("Tag vorhanden") : t("noch nicht angelegt")}</small></div>
            <div class="overview-card ${statusClass}"><span class="overview-label">${t("Kompatibilität")}</span><strong>${statusText}</strong><small>${escapeHtml(statusDetail)}</small></div>
        </div>
        <div class="diagnostic-details-card">
            <h4>${t("Aktueller Spieler")}</h4>
            <p>${escapeHtml(analysis.player)}</p>
            <p class="hint-text">${t("Verzauberte Items: {count}", { count: escapeHtml(Number(inventory.enchantments || 0) + Number(ender.enchantments || 0)) })} · ${t("Geschützte/unknown Slots: {count}", { count: escapeHtml(Number(hidden.inventory || 0) + Number(hidden.ender_chest || 0)) })}</p>
        </div>
        </details>
        ${compatNotes.length ? `<div class="diagnostic-details-card"><h4>${t("Erhaltene Zusatzdaten")}</h4><p>${t("Zusätzliche Daten bleiben beim Speichern erhalten. Es ist keine Aktion erforderlich.")}</p><details class="preserved-data-details"><summary>${t("Technische Details anzeigen")}</summary>${compatNotes.map(note => `<p>${escapeHtml(note)}</p>`).join("")}</details></div>` : ""}
    `;
    }


    function createWorldAnalysisController({
        panel = null,
        getWorldPath = () => "",
        getCurrentPlayer = () => null,
        buildAnalysis = () => ({}),
        inventorySlotCount = 36,
        enderChestSlotCount = 27,
    } = {}) {
        function render() {
            if (!panel) return;
            if (!getWorldPath?.() && !getCurrentPlayer?.()) {
                panel.innerHTML = emptyWorldAnalysisHtml();
                return;
            }
            panel.innerHTML = worldAnalysisHtml(buildAnalysis?.() || {}, {
                inventorySlotCount,
                enderChestSlotCount,
            });
        }

        return { render };
    }

    function createInventoryWorldAnalysisController({ doc = document, ...deps } = {}) {
        return createWorldAnalysisController({
            ...deps,
            panel: doc.getElementById("worldAnalysisPanel"),
        });
    }

    window.MCBEWorldAnalysisView = {
        createInventoryWorldAnalysisController,
        createWorldAnalysisController,
        emptyWorldAnalysisHtml,
        worldAnalysisHtml,
    };
}());
