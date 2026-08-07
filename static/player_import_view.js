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

    function directoryFromPath(path) {
        const value = String(path || "");
        const index = Math.max(value.lastIndexOf("\\"), value.lastIndexOf("/"));
        return index > 0 ? value.slice(0, index) : "";
    }

    function exportFolderControl({ worldPath = "", dockerMode = false } = {}) {
        return {
            disabled: !worldPath || dockerMode,
            title: dockerMode
                ? t("Im Docker-/LAN-Modus kann der Browser keinen Host-Dateimanager öffnen. Nutze den Containerpfad aus der Exportmeldung.")
                : t("Exportordner der geladenen Welt im Dateimanager öffnen"),
        };
    }

    function applyExportFolderControl(element, model = {}) {
        if (!element) return;
        element.disabled = Boolean(model.disabled);
        element.title = model.title || "";
    }

    function importTargetHint({
        importAsExported = false,
        canOverwriteSelected = false,
        playerLabel = "",
        previewRequired = false,
        exportedKeyRequired = false,
    } = {}) {
        if (previewRequired) {
            return t("Warte auf eine passende Import-Vorschau für die ausgewählte Datei. Erst danach kann der Import gestartet werden.");
        }
        if (exportedKeyRequired) {
            return t("Import als exportierter Spieler ist nicht möglich: Die Import-Datei enthält keinen exportierten Spieler-Key. Wähle einen vorhandenen Zielspieler oder nutze einen vollständigen Player-Export.");
        }
        if (importAsExported) {
            return t("Legt den exportierten Spieler-Key direkt in der gewählten Welt an. Existiert der Key dort bereits, wird abgebrochen. Importiert wird der komplette Player-NBT-Datensatz.");
        }
        if (canOverwriteSelected) {
            return t("Zielspieler: {player}. Der vollständige Player-Datensatz wird direkt in der gewählten Welt überschrieben.", { player: playerLabel });
        }
        return t("Wähle einen bearbeitbaren Zielspieler oder aktiviere den Import als exportierter Spieler. Der vollständige Player-Datensatz wird direkt in die gewählte Welt geschrieben.");
    }

    function importControlsModel({
        worldPath = "",
        importPath = "",
        importAsExported = false,
        canOverwriteSelected = false,
        currentImportPreview = null,
        writeBlocked = false,
        playerLabel = "",
    } = {}) {
        const cleanWorldPath = String(worldPath || "").trim();
        const cleanImportPath = String(importPath || "").trim();
        const previewMatches = Boolean(
            currentImportPreview &&
            currentImportPreview.export_path === cleanImportPath &&
            String(currentImportPreview.world_path || "").trim() === cleanWorldPath,
        );
        const previewBlocksImport = previewMatches && currentImportPreview.importable === false;
        const previewHasToken = Boolean(previewMatches && currentImportPreview.import_token && typeof currentImportPreview.import_token === "object");
        const previewAllowsImport = previewMatches && currentImportPreview.importable === true && previewHasToken;
        const exportedPlayerKey = previewMatches && currentImportPreview.player
            ? String(currentImportPreview.player.player_key || "").trim()
            : "";
        const exportedKeyRequired = Boolean(importAsExported && previewAllowsImport && !exportedPlayerKey);
        const previewRequired = Boolean(cleanImportPath) && !previewAllowsImport && !previewBlocksImport;
        const hasTarget = importAsExported ? Boolean(exportedPlayerKey) : Boolean(canOverwriteSelected);
        const canImport = Boolean(cleanWorldPath && cleanImportPath && !writeBlocked && previewAllowsImport && hasTarget);
        return {
            importDisabled: !canImport,
            previewBlocksImport,
            previewMatches,
            previewRequired,
            exportedKeyRequired,
            targetHint: importTargetHint({ importAsExported, canOverwriteSelected, playerLabel, previewRequired, exportedKeyRequired }),
        };
    }

    function applyImportControlsModel(elements = {}, model = {}) {
        const { importButton = null, targetHint = null } = elements;
        if (importButton) importButton.disabled = Boolean(model.importDisabled);
        if (targetHint) targetHint.textContent = model.targetHint || "";
    }

    function importPreviewLoadingModel() {
        return {
            className: "import-preview",
            html: `<strong>${t("Import-Vorschau wird geladen...")}</strong>`,
        };
    }

    function importPreviewHtml(data, errorMessage = "") {
        if (errorMessage) {
            return {
                className: "import-preview error",
                html: `<strong>${t("Import-Vorschau nicht lesbar")}</strong><br><span>${escapeHtml(errorMessage)}</span>`,
            };
        }

        const preview = data?.preview || {};
        const player = data?.player || {};
        const stats = preview.stats || {};
        const pos = Array.isArray(stats.pos) ? stats.pos.map(v => Number(v).toFixed(1)).join(" / ") : t("unbekannt");
        const importableText = data?.importable ? t("importierbar") : t("nicht importierbar");
        const inventoryNote = preview.inventory_will_be_created
            ? " · " + t("leeres Inventar wird beim späteren Speichern angelegt")
            : "";
        const cleanupWarning = data?.cleanup_warning
            ? `<div class="import-preview-note warning">${t("Hinweis: {warning}", { warning: escapeHtml(data.cleanup_warning) })}</div>`
            : "";
        return {
            className: `import-preview ${data?.cleanup_warning ? "warning" : (data?.importable ? "ok" : "error")}`,
            html: `
        <strong>${t("Import-Vorschau: {player}", { player: escapeHtml(player.label || t("Unbekannter Spieler")) })}</strong>
        <div>${t("Quelle: {world} · {date}", { world: escapeHtml(data?.source_world_name || t("unbekannte Welt")), date: escapeHtml(data?.created_at || t("kein Datum")) })}</div>
        <div>${t("Status: {status}{note} · Inventar-Einträge: {count} · Position: {pos}", { status: importableText, note: escapeHtml(inventoryNote), count: escapeHtml(preview.inventory_count ?? 0), pos: escapeHtml(pos) })}</div>
        <div>${escapeHtml(data?.message || "")}</div>
        ${cleanupWarning}
        <div class="import-preview-note">${t("Umfang: kompletter Player-NBT-Datensatz inkl. Inventar, Enderchest, Position/Stats, Effekte und sonstiger erhaltener NBT-Daten.")}</div>
    `,
        };
    }

    function applyImportPreviewModel(element, model = {}) {
        if (!element) return;
        element.style.display = "block";
        element.className = model.className || "import-preview";
        element.innerHTML = model.html || "";
    }

    function clearImportPreviewElement(element) {
        if (!element) return;
        element.style.display = "none";
        element.innerHTML = "";
    }

    window.MCBEPlayerImportView = {
        applyExportFolderControl,
        applyImportControlsModel,
        applyImportPreviewModel,
        clearImportPreviewElement,
        directoryFromPath,
        exportFolderControl,
        importControlsModel,
        importTargetHint,
        importPreviewHtml,
        importPreviewLoadingModel,
    };
}());
