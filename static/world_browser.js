(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const WORLD_FOLDER_PICKER_STATUS_KEY = "world-folder-picker";

    function sourceLabelForWorld(world) {
        const systemLabels = {
            "configured-root": t("Konfigurierter Welt-Root"),
            "docker-root": t("Docker-Weltenordner"),
            "minecraft-default": t("Minecraft-Standardordner"),
            "manual-root": t("Manueller Suchbereich"),
        };
        if (systemLabels[world?.source_kind]) return systemLabels[world.source_kind];
        if (world?.source_kind === "user-root" && world?.source_label === "Eigener Suchort") return t("Eigener Suchort");
        return world?.source_label || t("Suchbereich");
    }

    function formatModified(world) {
        const ts = Number(world?.modified_ts || 0);
        if (!Number.isFinite(ts) || ts <= 0) return t("zuletzt geändert unbekannt");
        try {
            return t("zuletzt geändert {when}", { when: window.MCBEI18n?.formatDate?.(ts * 1000) || new Date(ts * 1000).toLocaleString() });
        } catch (_e) {
            return t("zuletzt geändert unbekannt");
        }
    }

    function worldSearchText(world) {
        return [world?.name, world?.folder, world?.path, world?.source_label, world?.source_kind]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
    }

    function compareWorldName(a, b) {
        const left = String(a.name || a.folder || "");
        const right = String(b.name || b.folder || "");
        return window.MCBEI18n?.compare?.(left, right) ?? left.localeCompare(right, undefined, { sensitivity: "base" });
    }

    function filterWorlds(worlds, { query = "", sort = "recent" } = {}) {
        const all = Array.isArray(worlds) ? worlds.slice() : [];
        const normalizedQuery = String(query || "").trim().toLowerCase();
        const filtered = normalizedQuery ? all.filter(world => worldSearchText(world).includes(normalizedQuery)) : all;
        filtered.sort((a, b) => {
            if (sort === "name") return compareWorldName(a, b);
            if (sort === "source") {
                const leftSource = sourceLabelForWorld(a);
                const rightSource = sourceLabelForWorld(b);
                const sourceCompare = window.MCBEI18n?.compare?.(leftSource, rightSource)
                    ?? leftSource.localeCompare(rightSource, undefined, { sensitivity: "base" });
                if (sourceCompare !== 0) return sourceCompare;
                return compareWorldName(a, b);
            }
            return (Number(b.modified_ts || 0) - Number(a.modified_ts || 0))
                || String(a.name || "").localeCompare(String(b.name || ""), undefined, { sensitivity: "base" });
        });
        return filtered;
    }



    function createWorldBrowserController({
        elements = {},
        getLastWorldScan = () => null,
        getLastRenderedWorlds = () => [],
        setLastRenderedWorlds = () => {},
        getSelectedWorld = () => null,
        getWorldPath = () => "",
        getWorldPathInputValue = () => "",
        getIsDirty = () => false,
        getPlayers = () => [],
        getWorldName = () => "-",
        setLastWorldScan = () => {},
        updateSelectedWorld = () => {},
        clearLoadError = () => {},
        updateAutoPathHint = () => {},
        buildErrorMessage = (data, fallback) => data?.error || fallback,
        logStatus = () => {},
        showToast = () => {},
        copyTextToClipboard = () => {},
        parseJsonResponse = response => response.json(),
        withCsrf = () => ({}),
        appConfig = {},
        loadWorldFromInput = () => {},
    } = {}) {
        const {
            worldPathInput = null,
            worldPicker = null,
            worldList = null,
            refreshButton = null,
            searchInput = null,
            sortSelect = null,
            countHint = null,
            diagnosticsPanel = null,
            diagnosticsToggleButton = null,
            copySelectedPathButton = null,
            openSelectedWorldButton = null,
            scanLoading = null,
            scanWarning = null,
            scanEmpty = null,
            loadButton = null,
            browseButton = null,
            manualToggleButton = null,
            manualPanel = null,
            copyDiagnosticsButton = null,
            copyPlayerDiagnosticsButton = null,
        } = elements;

        let scanRequestId = 0;

        function setLoadingState(isLoading) {
            if (scanLoading) scanLoading.style.display = isLoading ? "block" : "none";
            if (isLoading && scanEmpty) {
                scanEmpty.style.display = "none";
                scanEmpty.innerHTML = "";
            }
            if (isLoading && scanWarning) {
                scanWarning.style.display = "none";
                scanWarning.textContent = "";
            }
        }

        function showScanEmpty(title, body) {
            if (!scanEmpty) return;
            scanEmpty.innerHTML = window.MCBEWorldCardsView.worldSearchStatusHtml(title, body);
            scanEmpty.style.display = "flex";
        }

        async function openPathInFileManager(path) {
            if (!path) return;
            try {
                const res = await fetch("/api/open_folder", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ path })
                });
                const data = await parseJsonResponse(res);
                if (data.success) {
                    logStatus(t("Ordner im Dateimanager geöffnet."), "success");
                } else {
                    const msg = buildErrorMessage(data, t("Ordner konnte nicht geöffnet werden."));
                    logStatus(msg, "error");
                    showToast(msg, "error", 5000);
                }
            } catch (e) {
                const msg = t("Ordner konnte nicht geöffnet werden: {error}", { error: e?.message || t("Verbindungsfehler") });
                logStatus(msg, "error");
                showToast(msg, "error", 5000);
            }
        }

        function renderWorldCards(worlds = []) {
            if (!worldList) return;
            const scan = getLastWorldScan();
            const allCount = Array.isArray(scan?.worlds) ? scan.worlds.length : worlds.length;
            const query = (searchInput?.value || "").trim();
            setLastRenderedWorlds(worlds);
            const selectedWorld = getSelectedWorld();
            const rendered = window.MCBEWorldCardsView.applyWorldCardsRender({
                worldList,
                emptyEl: scanEmpty,
                worldCountHint: countHint,
            }, worlds, {
                allCount,
                query,
                selectedPath: selectedWorld?.path || "",
                dirtyWorldPath: getWorldPath(),
                isDirty: Boolean(getIsDirty()),
                sourceLabelForWorld,
                formatModified,
            });
            if (!rendered || !worlds.length) return;
            worldList.querySelectorAll("[data-world-path]").forEach(el => {
                el.addEventListener("click", () => {
                    const selected = getLastRenderedWorlds().find(world => world.path === el.dataset.worldPath);
                    if (!selected) return;
                    clearLoadError();
                    updateSelectedWorld(selected);
                    renderWorldCards(getLastRenderedWorlds());
                    logStatus(t("Welt ausgewählt. Klicke auf Laden, wenn du sie öffnen möchtest."), "success");
                });
            });
        }

        function renderFilteredWorlds() {
            renderWorldCards(filterWorlds(getLastWorldScan()?.worlds, {
                query: searchInput?.value || "",
                sort: sortSelect?.value || "recent",
            }));
        }

        function renderWorldDiagnostics(scanData) {
            window.MCBEWorldCardsView.applyWorldDiagnostics(diagnosticsPanel, scanData, window.MCBEScanPathsView.scanRootKindLabel);
        }

        function buildWorldDiagnosticsText({ appConfig: diagnosticsAppConfig = appConfig } = {}) {
            return window.MCBEPlayerDiagnostics.buildWorldDiagnosticsText({
                appConfig: diagnosticsAppConfig,
                scan: getLastWorldScan() || {},
                selectedWorld: getSelectedWorld(),
                players: getPlayers(),
                worldName: getWorldName() || getSelectedWorld()?.name || "-",
                worldPath: getWorldPath() || getSelectedWorld()?.path || "-",
            });
        }

        function buildPlayersDiagnosticsText() {
            return window.MCBEPlayerDiagnostics.buildPlayersDiagnosticsText({
                players: getPlayers(),
                worldName: getWorldName() || getSelectedWorld()?.name || "-",
                worldPath: getWorldPath() || getSelectedWorld()?.path || "-",
                selectedWorld: getSelectedWorld(),
            });
        }



        async function browseWorldFolder() {
            clearLoadError();
            const pickerStatus = (message, type = "") => logStatus(message, type, {
                key: WORLD_FOLDER_PICKER_STATUS_KEY,
            });
            pickerStatus(t("Öffne Ordnerauswahl..."), "running");
            try {
                const res = await fetch("/api/pick_folder", { method: "POST", headers: withCsrf() });
                const data = await parseJsonResponse(res);
                if (data.success && data.path) {
                    if (worldPathInput) worldPathInput.value = data.path;
                    updateSelectedWorld({ path: data.path, name: t("Manuell gewählte Welt"), folder: data.path, source_label: t("Manueller Pfad") }, { fromManual: true });
                    pickerStatus(t("Welt-Ordner ausgewählt. Bereit zum Laden."), "success");
                } else if (data.error) {
                    pickerStatus(t("Fehler: {error}", { error: data.error }), "error");
                } else {
                    pickerStatus(t("Auswahl abgebrochen."), "");
                }
            } catch (e) {
                console.error("browseWorldFolder:", e);
                pickerStatus(t("Fehler beim Öffnen des Dialogs."), "error");
            }
        }

        function toggleManualWorldPanel() {
            if (!manualPanel) return;
            const show = manualPanel.style.display === "none" || !manualPanel.style.display;
            manualPanel.style.display = show ? "block" : "none";
            if (show) worldPathInput?.focus();
        }

        function handleWorldPathKeydown(event) {
            if (event.key !== "Enter") return;
            event.preventDefault();
            const manual = String(worldPathInput?.value || "").trim();
            if (manual) updateSelectedWorld({ path: manual, name: t("Manueller Pfad"), folder: manual, source_label: t("Manueller Pfad") }, { fromManual: true });
            loadWorldFromInput();
        }

        async function scanWorlds() {
            const requestId = ++scanRequestId;
            setLoadingState(true);
            try {
                const res = await fetch("/api/scan_worlds");
                const data = await parseJsonResponse(res);
                if (requestId !== scanRequestId) return;
                setLastWorldScan(data);
                if (worldList) worldList.innerHTML = "";
                renderWorldDiagnostics(data);
                if (scanWarning && data.warnings && data.warnings.length) {
                    scanWarning.textContent = data.warnings.join(" ");
                    scanWarning.style.display = "block";
                }
                if (!data.success) {
                    if (worldPicker) worldPicker.style.display = "block";
                    showScanEmpty(t("Weltsuche fehlgeschlagen"), buildErrorMessage(data, t("Unbekannter Fehler")));
                    if (countHint) countHint.textContent = t("Suche fehlgeschlagen");
                    updateAutoPathHint(t("Weltsuche fehlgeschlagen"), "error");
                    return;
                }
                const worlds = Array.isArray(data.worlds) ? data.worlds : [];
                if (worldPicker) worldPicker.style.display = "block";
                if (!worlds.length) {
                    updateAutoPathHint(t("Keine Welt gefunden · eigener Ort möglich"), "warning");
                    renderWorldCards([]);
                    return;
                }
                updateAutoPathHint(worlds.length === 1
                    ? t("1 Welt automatisch gefunden")
                    : t("{count} Welten automatisch gefunden", { count: worlds.length }), "success");

                if (!getSelectedWorld() && !String(worldPathInput?.value || "").trim() && worlds.length === 1) {
                    updateSelectedWorld(worlds[0]);
                    logStatus(t("Eine Welt wurde automatisch vorausgewählt. Laden bleibt bewusst manuell."), "info");
                }
                renderFilteredWorlds();
            } catch (e) {
                if (requestId !== scanRequestId) return;
                console.error("scanWorlds:", e);
                if (worldPicker) worldPicker.style.display = "block";
                showScanEmpty(
                    t("Weltsuche nicht erreichbar"),
                    t("Der lokale App-Server konnte die Suche nicht beantworten. Seite neu laden oder Konsole prüfen.")
                );
                const nextScan = { success: false, error: e?.message || t("Weltsuche nicht erreichbar") };
                setLastWorldScan(nextScan);
                renderWorldDiagnostics(nextScan);
                if (countHint) countHint.textContent = t("Suche nicht erreichbar");
                updateAutoPathHint(t("Weltsuche nicht erreichbar"), "error");
            } finally {
                if (requestId === scanRequestId) setLoadingState(false);
            }
        }

        function wire() {
            refreshButton?.addEventListener("click", scanWorlds);
            browseButton?.addEventListener("click", browseWorldFolder);
            manualToggleButton?.addEventListener("click", toggleManualWorldPanel);
            worldPathInput?.addEventListener("keydown", handleWorldPathKeydown);
            loadButton?.addEventListener("click", loadWorldFromInput);
            copyDiagnosticsButton?.addEventListener("click", () => copyTextToClipboard(buildWorldDiagnosticsText(), t("Diagnose in die Zwischenablage kopiert.")));
            copyPlayerDiagnosticsButton?.addEventListener("click", () => copyTextToClipboard(buildPlayersDiagnosticsText(), t("Spieler-Diagnose in die Zwischenablage kopiert.")));
            searchInput?.addEventListener("input", renderFilteredWorlds);
            searchInput?.addEventListener("keydown", (event) => {
                const renderedWorlds = getLastRenderedWorlds();
                if (event.key === "Enter" && renderedWorlds.length === 1) {
                    event.preventDefault();
                    updateSelectedWorld(renderedWorlds[0]);
                    renderWorldCards(renderedWorlds);
                    loadButton?.focus();
                }
            });
            sortSelect?.addEventListener("change", renderFilteredWorlds);
            if (diagnosticsToggleButton && diagnosticsPanel) {
                diagnosticsToggleButton.addEventListener("click", () => {
                    const expand = !diagnosticsPanel.classList.contains("expanded");
                    diagnosticsPanel.classList.toggle("expanded", expand);
                    diagnosticsPanel.classList.toggle("collapsed", !expand);
                    diagnosticsToggleButton.textContent = expand ? t("Suchdetails ausblenden") : t("Suchdetails");
                });
            }
            copySelectedPathButton?.addEventListener("click", () => {
                copyTextToClipboard(getSelectedWorld()?.path || getWorldPathInputValue() || "", t("Weltpfad kopiert."));
            });
            openSelectedWorldButton?.addEventListener("click", () => {
                openPathInFileManager(getSelectedWorld()?.path || getWorldPathInputValue() || "");
            });
        }

        return {
            buildPlayersDiagnosticsText,
            buildWorldDiagnosticsText,
            openPathInFileManager,
            renderFilteredWorlds,
            renderWorldCards,
            renderWorldDiagnostics,
            browseWorldFolder,
            scanWorlds,
            toggleManualWorldPanel,
            wire,
        };
    }

    function collectWorldBrowserElements(doc = document) {
        return {
            worldPathInput: doc.getElementById("worldPath"),
            worldPicker: doc.getElementById("worldPicker"),
            worldList: doc.getElementById("worldList"),
            refreshButton: doc.getElementById("btnRefreshWorlds"),
            searchInput: doc.getElementById("worldSearchInput"),
            sortSelect: doc.getElementById("worldSortSelect"),
            countHint: doc.getElementById("worldCountHint"),
            diagnosticsPanel: doc.getElementById("worldDiagnostics"),
            diagnosticsToggleButton: doc.getElementById("btnToggleDiagnostics"),
            copySelectedPathButton: doc.getElementById("btnCopySelectedWorldPath"),
            openSelectedWorldButton: doc.getElementById("btnOpenSelectedWorld"),
            scanLoading: doc.getElementById("worldScanLoading"),
            scanWarning: doc.getElementById("worldScanWarning"),
            scanEmpty: doc.getElementById("worldScanEmpty"),
            loadButton: doc.getElementById("btnLoad"),
            browseButton: doc.getElementById("btnBrowse"),
            manualToggleButton: doc.getElementById("btnToggleManualWorld"),
            manualPanel: doc.getElementById("manualWorldPanel"),
            copyDiagnosticsButton: doc.getElementById("btnCopyDiagnostics"),
            copyPlayerDiagnosticsButton: doc.getElementById("btnCopyPlayerDiagnostics"),
        };
    }

    function createInventoryWorldBrowserController({ doc = document, ...deps } = {}) {
        return createWorldBrowserController({
            ...deps,
            elements: collectWorldBrowserElements(doc),
        });
    }

    window.MCBEWorldBrowser = {
        collectWorldBrowserElements,
        createInventoryWorldBrowserController,
        createWorldBrowserController,
        filterWorlds,
        formatModified,
        sourceLabelForWorld,
        worldSearchText,
    };
}());
