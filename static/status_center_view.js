(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function escapeHtml(value) {
        if (window.MCBEHtmlUtils?.escapeHtml) return window.MCBEHtmlUtils.escapeHtml(value);
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function dataSourceView() {
        return window.MCBEDataSourceView;
    }

    function compatibilityNotesFor(report) {
        return Array.isArray(report?.notes) ? report.notes.filter(Boolean) : [];
    }

    function statusCenterModel({
        runtimeDiagnostics = {},
        appConfig = {},
        currentCompatibility = {},
        iconSummary = {},
        itemDbStatus = null,
        lastWorldScan = {},
        isDirty = false,
        worldPath = "",
        selectedWorldPath = "",
        currentPlayerLabel = t("Kein Spieler"),
        hasCurrentPlayer = false,
        compatibilitySummary = "",
    } = {}) {
        const view = dataSourceView();
        const gate = runtimeDiagnostics.write_gate || {};
        const gateSetup = runtimeDiagnostics.write_gate_setup || {};
        const server = gate.server_status || {};
        const localWorldAccessWarning = appConfig?.mode === "local" && gateSetup.local_world_access_warning === true;
        const worldCompat = currentCompatibility?.world || {};
        const playerCompat = currentCompatibility?.player || {};
        const worldWarnings = Array.isArray(worldCompat.warnings) ? worldCompat.warnings.length : 0;
        const playerWarnings = Array.isArray(playerCompat.warnings) ? playerCompat.warnings.length : 0;
        const compatibilityNotes = compatibilityNotesFor(playerCompat).length + compatibilityNotesFor(worldCompat).length;
        const iconWarnings = Array.isArray(iconSummary?.warnings) ? iconSummary.warnings.length : 0;
        const iconState = view.iconStateSummary(iconSummary);
        const dbRank = view.itemDbStatusRank(itemDbStatus);
        const scanIssues = (lastWorldScan?.roots || []).filter(root => !["ok", "missing", "disabled"].includes(root.status)).length;
        const runtimeRank = Math.max(
            localWorldAccessWarning ? 1 : 0,
            view.statusSeverityRank(server.status === "online" && !gate.allowed ? "blocked" : (server.status || "ok"))
        );
        const compatRank = Math.max(
            view.statusSeverityRank(worldCompat.status || "ok"),
            view.statusSeverityRank(playerCompat.status || "ok")
        );
        const iconRank = Math.max(iconWarnings ? 1 : 0, iconState.rank);
        const worldRank = scanIssues ? 1 : 0;
        const saveRank = isDirty ? 1 : 0;
        const overall = Math.max(runtimeRank, compatRank, iconRank, dbRank, worldRank, saveRank);
        const modeLabel = appConfig?.mode === "docker" ? "Docker" : t("Lokal");
        const serverDetail = localWorldAccessWarning
            ? t("Keine Serverprüfung: Welt nur öffnen, wenn Minecraft/Server geschlossen ist.")
            : appConfig?.mode === "docker"
            ? (gate.allowed ? t("Schreiben erlaubt") : t("Schreibsperre aktiv"))
            : t("Serverprüfung nicht aktiv");
        const compatDetail = playerWarnings + worldWarnings
            ? `${compatibilitySummary || t("{count} Hinweis(e)", { count: playerWarnings + worldWarnings })} · ${t("Daten werden erhalten")}`
            : (compatibilityNotes ? t("Zusatzdaten werden erhalten") : (hasCurrentPlayer ? t("kompatibel wirkend") : t("noch kein Spieler geladen")));
        const worldDetail = selectedWorldPath || worldPath || t("noch keine Welt geladen");
        return {
            heroClass: view.statusSeverityClass(overall),
            headline: view.statusSeverityLabel(overall),
            subtitle: t("{mode}modus · {player}", { mode: modeLabel, player: currentPlayerLabel }),
            detail: overall ? t("Details sind unten gesammelt verfügbar.") : t("Keine akuten Probleme erkannt."),
            tiles: [
                { label: t("Welt"), value: worldPath ? t("geladen") : t("offen"), detail: worldDetail, rank: worldRank },
                { label: t("Schreiben"), value: gate.allowed === false ? t("gesperrt") : t("bereit"), detail: serverDetail, rank: runtimeRank },
                { label: t("Kompatibilität"), value: compatRank ? t("Hinweise") : "OK", detail: compatDetail, rank: compatRank },
                { label: t("Icons"), value: iconState.value, detail: iconState.detail, rank: iconRank },
                {
                    label: t("Item-DB"),
                    value: view.itemDbStatusValue(itemDbStatus),
                    detail: `${view.itemDbCountsText(itemDbStatus)} · ${view.itemDbSourceText(itemDbStatus)}`,
                    rank: dbRank,
                },
                {
                    label: t("Änderungen"),
                    value: isDirty ? t("ungespeichert") : t("sauber"),
                    detail: isDirty ? t("Save-Prüfung vor dem Speichern") : t("keine lokalen Änderungen"),
                    rank: saveRank,
                },
            ],
        };
    }

    function statusCenterHtml(options = {}) {
        const model = options.tiles ? options : statusCenterModel(options);
        const view = dataSourceView();
        return `
        <div class="status-hero ${escapeHtml(model.heroClass)}">
            <div><strong>${escapeHtml(model.headline)}</strong><span>${escapeHtml(model.subtitle)}</span></div>
            <small>${escapeHtml(model.detail)}</small>
        </div>
        <div class="status-tile-grid">
            ${model.tiles.map(tile => view.statusTile(tile.label, tile.value, tile.detail, tile.rank)).join("")}
        </div>
    `;
    }

    function statusCenterText({
        runtimeDiagnostics = {},
        appConfig = {},
        currentCompatibility = {},
        iconSummary = {},
        isDirty = false,
        worldPath = "",
        currentPlayerLabel = t("Kein Spieler"),
    } = {}) {
        const view = dataSourceView();
        const gate = runtimeDiagnostics.write_gate || {};
        const gateSetup = runtimeDiagnostics.write_gate_setup || {};
        const server = gate.server_status || {};
        const playerCompat = currentCompatibility?.player || {};
        const worldCompat = currentCompatibility?.world || {};
        const playerWarnings = playerCompat.warnings || [];
        const worldWarnings = worldCompat.warnings || [];
        const compatibilityNotes = compatibilityNotesFor(playerCompat).concat(compatibilityNotesFor(worldCompat));
        const playerStatus = playerCompat.status || "ok";
        const worldStatus = worldCompat.status || "ok";
        const compatibilityStatus = view.statusSeverityRank(playerStatus) >= view.statusSeverityRank(worldStatus) ? playerStatus : worldStatus;
        return [
            t("MCBE Inventory Editor - Statuscenter"),
            `Version: ${appConfig?.distribution?.project_version || "dev"}`,
            t("Modus: {mode}", { mode: appConfig?.mode || "local" }),
            t("Welt: {world}", { world: worldPath || "-" }),
            t("Spieler: {player}", { player: currentPlayerLabel }),
            t("Schreiben: {status}", { status: gate.allowed === false ? t("gesperrt") : t("bereit") }),
            t("Lokalmodus-Hinweis: {hint}", { hint: gateSetup.local_world_access_warning ? t("keine Serverprüfung; Welt nur ohne paralleles Minecraft/Server öffnen") : "-" }),
            t("Serverstatus: {status}", { status: server.status || t("nicht aktiv") }),
            t("Kompatibilität: {status}", { status: compatibilityStatus }),
            t("Kompatibilitätshinweise: {list}", { list: playerWarnings.concat(worldWarnings).join(" | ") || "-" }),
            t("Erhaltene Zusatzdaten: {list}", { list: compatibilityNotes.join(" | ") || "-" }),
            t("Icons: {count} indexiert", { count: iconSummary?.count || 0 }),
            t("Ungespeicherte Änderungen: {value}", { value: isDirty ? t("ja") : t("nein") }),
        ].join("\n");
    }


    function createStatusCenterController({
        panel = null,
        getRuntimeDiagnostics = () => ({}),
        getAppConfig = () => ({}),
        getCurrentCompatibility = () => ({}),
        getIconSummary = () => ({}),
        getItemDbStatus = () => null,
        getLastWorldScan = () => ({}),
        getIsDirty = () => false,
        getWorldPath = () => "",
        getSelectedWorldPath = () => "",
        getCurrentPlayerLabel = () => t("Kein Spieler"),
        hasCurrentPlayer = () => false,
        getCompatibilitySummary = () => "",
    } = {}) {
        function snapshot() {
            return {
                runtimeDiagnostics: getRuntimeDiagnostics() || {},
                appConfig: getAppConfig() || {},
                currentCompatibility: getCurrentCompatibility() || {},
                iconSummary: getIconSummary() || {},
                itemDbStatus: getItemDbStatus(),
                lastWorldScan: getLastWorldScan() || {},
                isDirty: Boolean(getIsDirty()),
                worldPath: getWorldPath() || "",
                selectedWorldPath: getSelectedWorldPath() || "",
                currentPlayerLabel: getCurrentPlayerLabel(),
                hasCurrentPlayer: Boolean(hasCurrentPlayer()),
                compatibilitySummary: getCompatibilitySummary(),
            };
        }

        function render() {
            if (!panel) return;
            panel.innerHTML = statusCenterHtml(snapshot());
        }

        function text() {
            return statusCenterText(snapshot());
        }

        return { render, snapshot, text };
    }

    function createInventoryStatusCenterController({ doc = document, ...deps } = {}) {
        return createStatusCenterController({
            ...deps,
            panel: doc.getElementById("statusCenterPanel"),
        });
    }

    window.MCBEStatusCenterView = {
        statusCenterHtml,
        createInventoryStatusCenterController,
        statusCenterModel,
        statusCenterText,
        createStatusCenterController,
    };
}());
