(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const playerViewModels = window.MCBEPlayerViewModels;
    if (!playerViewModels) throw new Error("MCBEPlayerViewModels must be loaded before MCBEPlayerLoadController.");
    const {
        playerListStatusHtml,
        playerRowElement,
        playerRowModel,
    } = playerViewModels;

    const PLAYER_WORKFLOW_VIEWS = new Set(["player", "inventory", "mounts", "save", "tools"]);
    const PLAYER_LOAD_STATUS_KEY = "player-load";

    function workflowViewAfterPlayerLoad(activeView) {
        const normalized = String(activeView || "");
        return PLAYER_WORKFLOW_VIEWS.has(normalized) ? normalized : "inventory";
    }

    function createPlayerLoadController(deps = {}) {
        const {
            elements = {},
            getState = () => ({}),
            setState = () => {},
            withCsrf = () => ({}),
            parseJsonResponse = async response => response.json(),
            buildErrorMessage = (data, fallback = t("Fehler")) => data?.error || fallback,
            showConfirmDialog = async () => false,
            showToast = () => {},
            logStatus = () => {},
            copyTextToClipboard = () => {},
            buildPlayersDiagnosticsText = () => "",
            renderLoadError = () => {},
            saveWorkspace = () => {},
            annotateItemOrigins = () => {},
            updateProtectedKnownSlotsFromMeta = () => {},
            normalizeServerGuardEpoch = value => Number(value) || 0,
            beginServerStatusRequest = () => null,
            clearLoadedPlayerStaleState = () => {},
            markLoadedPlayerStale = () => {},
            renderServerStatus = () => {},
            updatePlayerExportFolderControl = () => {},
            updateImportControls = () => {},
            scheduleWorldPresenceUpdate = () => {},
            renderPlayerToolOptions = () => {},
            renderStatusCenter = () => {},
            updateAppMode = () => {},
            updateWorldPresence = async () => {},
            renderWorldAnalysis = () => {},
            setWorkflowView = () => {},
            getActiveWorkflowView = () => "world",
            loadLocalIconIndex = () => {},
            renderStatsForm = () => {},
            clearTouchedStatsFields = () => {},
            setStatsProtectionUI = () => {},
            buildGrids = () => {},
            getInventoryViewPreferences = () => null,
            updateGridVisuals = () => {},
            clearSelection = () => {},
            markCleanState = () => {},
            clearPendingMounts = () => {},
            renderPlayerInventorySummary = () => {},
            recordAction = () => {},
            getCurrentPlayerLabel = () => t("Spieler"),
            getAnalysisLogic = () => null,
            resetUndoRedoForUnloadedPlayer = () => {},
            clearGridSearch = () => {},
            clearLoadError = () => {},
            confirmLocalWorldAccessBeforeOpen = async () => true,
            loadBackupsList = () => {},
            showLoading = () => {},
            hideLoading = () => {},
            defaultMaxDamage = 32767,
            appConfig = {},
            exportBlocked = () => false,
            api = null,
        } = deps;
        const {
            playersList,
            playerManager,
            inventoryContainer,
            btnExportPlayer,
            btnImportPlayer,
            btnSave,
            btnUndo,
            btnRedo,
            btnRefreshPlayers,
            playerInventorySummary,
            emptyState,
            detailEditorPanel,
            multiSelectPanel,
            dashboardPanel,
            recentWorldsEl,
            recentWorldsList,
            loadButton,
            worldPathInput,
            worldSearchInput,
            worldNameElement,
            worldBanner,
        } = elements;
        let playerApi = api;
        let playerLoadRequestId = 0;
        let playerListRequestId = 0;
        let worldLoadRequestId = 0;

        function logLoadStatus(message, type = "") {
            logStatus(message, type, { key: PLAYER_LOAD_STATUS_KEY });
        }

        function getPlayerApi() {
            if (!playerApi) {
                if (!window.MCBEPlayerApi?.createPlayerApiClient) {
                    throw new Error("MCBEPlayerApi must be loaded before player-load API calls.");
                }
                playerApi = window.MCBEPlayerApi.createPlayerApiClient({
                    withCsrf,
                    parseJsonResponse,
                    buildErrorMessage,
                });
            }
            return playerApi;
        }

        function resetLoadedPlayerState({ showEmptyState = true } = {}) {
            const state = getState();
            setState({
                inventory: {},
                enderChestInventory: {},
                hasEnderChest: false,
                enderChestCreateRequiresConfirmation: false,
                inventoryCreateRequiresConfirmation: false,
                currentPlayerKey: "",
                currentPlayer: null,
                currentPlayerRevision: "",
                currentPlayerServerGuardEpoch: state.currentServerGuardEpoch || 0,
                currentPlayerServerGuardToken: state.currentServerGuardToken || "",
                playerStats: {
                    pos: [0.0, 70.0, 0.0],
                    dimension_id: null,
                    health: 20.0,
                    gamemode: 0,
                    xp_level: 0,
                    xp_progress: 0.0,
                    food_level: 20,
                    food_saturation: 20.0,
                },
                playerEffects: [],
                playerAbilities: {},
                effectsDb: {},
                hiddenUnknownSlots: { inventory: 0, ender_chest: 0 },
                protectedKnownSlots: { inventory: [], ender_chest: [] },
                protectedNbt: {},
                currentCompatibility: {},
                lastPlayerExportDir: "",
                isDirty: false,
            });
            clearLoadedPlayerStaleState();
            clearPendingMounts();
            clearSelection();
            resetUndoRedoForUnloadedPlayer();
            if (btnExportPlayer) btnExportPlayer.disabled = true;
            updatePlayerExportFolderControl();
            if (btnImportPlayer) btnImportPlayer.disabled = true;
            if (btnSave) btnSave.disabled = true;
            if (btnUndo) btnUndo.disabled = true;
            if (btnRedo) btnRedo.disabled = true;
            if (inventoryContainer) inventoryContainer.style.display = "none";
            if (playerInventorySummary) playerInventorySummary.style.display = "none";
            if (emptyState) emptyState.style.display = showEmptyState ? "flex" : "none";
            if (detailEditorPanel) detailEditorPanel.style.display = "none";
            if (multiSelectPanel) multiSelectPanel.style.display = "none";
            if (dashboardPanel) dashboardPanel.style.display = "none";
            getInventoryViewPreferences()?.applyEnderChestVisibility?.();
            updateImportControls();
            scheduleWorldPresenceUpdate();
            renderPlayerToolOptions();
            renderStatusCenter();
            updateAppMode();
        }

        async function selectExportOnlyPlayer(player) {
            if (getState().isDirty) {
                const ok = await showConfirmDialog(t("Es gibt ungespeicherte Änderungen. Fortfahren?"));
                if (!ok) return;
            }
            resetLoadedPlayerState({ showEmptyState: false });
            setState({ currentPlayerKey: player.player_key, currentPlayer: player });
            if (btnExportPlayer) btnExportPlayer.disabled = !player.exportable || exportBlocked();
            updateImportControls();
            renderPlayersList();
            await updateWorldPresence();
            setWorkflowView("player", { scroll: false });
            logLoadStatus(t("{player} ausgewählt – nur Export möglich.", { player: getCurrentPlayerLabel() }), "warning");
            updateWriteControlsSafe();
        }

        function updateWriteControlsSafe() {
            deps.updateWriteControls?.();
        }

        function playerLoadLabel(playerKey) {
            const player = (getState().players || []).find(candidate => candidate.player_key === playerKey);
            return player?.label || playerKey || t("Spieler");
        }

        function renderPlayersList() {
            const state = getState();
            if (!playersList) return;
            playersList.innerHTML = "";
            if (!state.players?.length) {
                playersList.innerHTML = playerListStatusHtml("empty");
                return;
            }
            state.players.forEach(player => {
                const model = playerRowModel(player, state.currentPlayerKey);
                const row = playerRowElement(model);
                if (player.editable) {
                    row.addEventListener("click", () => loadPlayer(player.player_key));
                } else if (player.exportable) {
                    row.addEventListener("click", () => selectExportOnlyPlayer(player));
                } else if (player.reason) {
                    row.addEventListener("click", () => {
                        setState({ currentPlayer: player, currentPlayerKey: player.player_key || "" });
                        renderPlayersList();
                        copyTextToClipboard(buildPlayersDiagnosticsText(), t("Spieler-Diagnose kopiert."));
                        logLoadStatus(player.reason, "warning");
                    });
                }
                playersList.appendChild(row);
            });
        }

        async function loadPlayersList(selectFirst = true) {
            const requestId = ++playerListRequestId;
            const requestedWorldPath = getState().worldPath;
            if (!requestedWorldPath) return false;
            const state = getState();
            if (state.isDirty) {
                const ok = await showConfirmDialog(t("Es gibt ungespeicherte Änderungen. Fortfahren?"));
                if (!ok) {
                    logLoadStatus(t("Aktualisierung der Spielerliste abgebrochen."), "warning");
                    return false;
                }
                if (requestId !== playerListRequestId || requestedWorldPath !== getState().worldPath) return false;
            }
            logLoadStatus(t("Suche Spieler in der Welt..."), "running");
            resetLoadedPlayerState({ showEmptyState: false });
            if (playerManager) playerManager.style.display = "flex";
            if (playersList) playersList.innerHTML = playerListStatusHtml("loading");
            try {
                const data = await getPlayerApi().listPlayers(requestedWorldPath);
                if (requestId !== playerListRequestId || requestedWorldPath !== getState().worldPath) return false;
                if (!data.success) {
                    if (playersList) playersList.innerHTML = playerListStatusHtml("loadError");
                    const msg = buildErrorMessage(data, t("Spieler konnten nicht geladen werden."));
                    logLoadStatus(t("Fehler: {error}", { error: msg }), "error");
                    renderLoadError(data, t("Spieler konnten nicht geladen werden."));
                    return false;
                }
                setState({ players: data.players || [] });
                renderPlayersList();
                renderPlayerToolOptions();
                renderWorldAnalysis();
                await updateWorldPresence();
                if (requestId !== playerListRequestId || requestedWorldPath !== getState().worldPath) return false;
                const firstEditable = (getState().players || []).find(p => p.editable);
                if (selectFirst && firstEditable) {
                    await loadPlayer(firstEditable.player_key);
                    if (requestId !== playerListRequestId || requestedWorldPath !== getState().worldPath) return false;
                } else if (!firstEditable) {
                    setWorkflowView("player", { scroll: false });
                    logLoadStatus(t("Keine editierbaren Spieler erkannt. Read-only Datensätze können nur exportiert werden."), "warning");
                } else {
                    logLoadStatus(t("Spielerliste aktualisiert: {count} Datensätze.", {
                        count: getState().players.length,
                    }), "success");
                }
                return true;
            } catch (e) {
                if (requestId !== playerListRequestId || requestedWorldPath !== getState().worldPath) return false;
                console.error("loadPlayersList:", e);
                if (playersList) playersList.innerHTML = playerListStatusHtml("connectionError");
                const data = { error: t("Verbindungsfehler beim Laden der Spieler."), details: e?.message || "" };
                logLoadStatus(buildErrorMessage(data), "error");
                renderLoadError(data, t("Verbindungsfehler beim Laden der Spieler."));
                return false;
            }
        }

        async function loadPlayer(playerKey, skipDirtyCheck = false, options = {}) {
            const requestId = ++playerLoadRequestId;
            const requestedWorldPath = getState().worldPath;
            const { showLoadingOverlay = true } = options || {};
            if (!skipDirtyCheck && getState().isDirty) {
                const ok = await showConfirmDialog(t("Es gibt ungespeicherte Änderungen. Spieler trotzdem wechseln?"));
                if (!ok) {
                    logLoadStatus(t("Spielerwechsel abgebrochen."), "warning");
                    return false;
                }
                if (requestId !== playerLoadRequestId) return false;
            }
            logLoadStatus(t("Lade Spieler..."), "running");
            let loadingShown = false;
            if (showLoadingOverlay) {
                showLoading(t("{player} wird geladen...", { player: playerLoadLabel(playerKey) }));
                loadingShown = true;
            }
            try {
                const statusRequestOrder = beginServerStatusRequest();
                const data = await getPlayerApi().loadPlayer(requestedWorldPath, playerKey);
                if (requestId !== playerLoadRequestId || requestedWorldPath !== getState().worldPath) return false;
                if (!data.success) {
                    const msg = buildErrorMessage(data, t("Spieler konnte nicht geladen werden."));
                    logLoadStatus(t("Fehler: {error}", { error: msg }), "error");
                    renderLoadError(data, t("Spieler konnte nicht geladen werden."));
                    return false;
                }

                // Ein erfolgreicher Reload ersetzt den gesamten lokalen Spielerzustand.
                // Vorgemerkte Mounts gehören zu dem zuvor geladenen Spieler und dürfen
                // weder als sauberer Zustand des neuen Spielers übernommen noch später
                // relativ zu dessen Position geschrieben werden.
                clearPendingMounts();
                const state = getState();
                const responseServerEpoch = normalizeServerGuardEpoch(data.server_guard_epoch);
                const nextServerEpoch = Math.max(state.currentServerGuardEpoch || 0, responseServerEpoch);
                const nextPlayerServerEpoch = normalizeServerGuardEpoch(
                    data.player_server_guard_epoch ?? data.server_guard_epoch,
                );
                const responseServerGuardToken = typeof data.server_guard_token === "string"
                    ? data.server_guard_token
                    : "";
                const nextPlayerServerGuardToken = typeof data.player_server_guard_token === "string"
                    ? data.player_server_guard_token
                    : responseServerGuardToken;
                const nextInventory = data.inventory || {};
                const nextEnder = data.ender_chest || {};
                annotateItemOrigins(nextInventory, playerKey, "inventory");
                annotateItemOrigins(nextEnder, playerKey, "ender_chest");
                const nextProtectedNbt = data.protected_nbt || {};
                const nextHiddenUnknownSlots = data.hidden_unknown_slots || { inventory: 0, ender_chest: 0 };

                setState({
                    currentPlayerKey: playerKey,
                    currentPlayer: data.player,
                    currentPlayerRevision: data.player_revision || "",
                    currentServerGuardEpoch: nextServerEpoch,
                    currentPlayerServerGuardEpoch: nextPlayerServerEpoch,
                    currentPlayerServerGuardToken: nextPlayerServerGuardToken,
                    inventory: nextInventory,
                    enderChestInventory: nextEnder,
                    hasEnderChest: data.has_ender_chest === true,
                    enderChestCreateRequiresConfirmation: !Boolean(data.player?.has_ender_chest_tag),
                    protectedNbt: nextProtectedNbt,
                    inventoryCreateRequiresConfirmation: data.player?.inventory_create_requires_confirmation === true || (data.player?.has_inventory_tag === false && !nextProtectedNbt.inventory_opaque),
                    effectsCreateRequiresConfirmation: nextProtectedNbt.has_active_effects_tag === false && !nextProtectedNbt.active_effects_opaque,
                    abilitiesCreateRequiresConfirmation: nextProtectedNbt.has_abilities_tag === false && !nextProtectedNbt.abilities_opaque,
                    effectsTouched: false,
                    abilitiesTouched: false,
                    itemsDb: data.items_db,
                    compatItemAliases: data.compat_item_aliases || {},
                    addableItems: new Set(data.addable_items || []),
                    blockOnlyItems: new Set(data.block_only_items || []),
                    blockItems: new Set(data.block_items || []),
                    itemAvailability: data.item_availability || {},
                    enchDb: data.ench_db,
                    enchantmentCompatibility: data.enchantment_compatibility || {},
                    itemComponents: data.item_components || {},
                    effectsDb: data.effects_db || {},
                    stackLimits: data.stack_limits || { "__default__": 64 },
                    maxDamage: data.max_damage || { "__default__": defaultMaxDamage },
                    playerStats: data.stats,
                    playerEffects: data.effects || [],
                    playerAbilities: data.abilities || {},
                    hiddenUnknownSlots: nextHiddenUnknownSlots,
                    currentCompatibility: data.compatibility || {},
                    gridFilter: "",
                });
                clearLoadedPlayerStaleState();
                if (data.write_gate) {
                    renderServerStatus(data, { requestOrder: statusRequestOrder });
                }
                const latestState = getState();
                const staleAtLoad = data.server_guard_stale === true
                    || (
                        responseServerGuardToken
                        && nextPlayerServerGuardToken
                        && (latestState.currentServerGuardToken || responseServerGuardToken) !== nextPlayerServerGuardToken
                    )
                    || (
                        !responseServerGuardToken
                        && appConfig?.require_server_offline === true
                        && nextServerEpoch > nextPlayerServerEpoch
                    );
                if (staleAtLoad) {
                    const staleReason = t(
                        data.server_guard_stale_reason_key
                            || data.server_guard_stale_reason
                            || "Nur ansehen: Der Bedrock-Server wurde seit dem Laden dieses Spielers online gesehen. Stoppe den Server und lade den Spieler neu, um ihn zu bearbeiten.",
                    );
                    markLoadedPlayerStale(staleReason);
                }
                saveWorkspace({ player_key: playerKey, player_label: data.player?.label || playerKey, world_path: state.worldPath, world_name: state.selectedWorld?.name || state.worldPath });
                updateProtectedKnownSlotsFromMeta(nextHiddenUnknownSlots);
                loadLocalIconIndex({ rescan: appConfig?.read_only !== true });
                if (inventoryContainer) inventoryContainer.style.display = "flex";
                if (btnExportPlayer) btnExportPlayer.disabled = !data.player?.exportable || exportBlocked();
                updateImportControls();
                renderStatsForm();
                clearTouchedStatsFields();
                setStatsProtectionUI();
                buildGrids();
                getInventoryViewPreferences()?.applyInventoryViewPreferences?.();
                getInventoryViewPreferences()?.applyEnderChestVisibility?.();
                clearGridSearch();
                updateGridVisuals();
                clearSelection();
                markCleanState();
                renderPlayerInventorySummary();
                recordAction(t("{player} geladen", { player: getCurrentPlayerLabel() }), "load");
                updateAppMode();
                renderPlayersList();
                renderPlayerToolOptions();
                renderStatusCenter();
                renderWorldAnalysis();
                await updateWorldPresence();
                setWorkflowView(workflowViewAfterPlayerLoad(getActiveWorkflowView()), { scroll: false });
                const analysis = getAnalysisLogic();
                const loadProtectionMessages = analysis?.currentLoadProtectionMessages?.() || [];
                if (loadProtectionMessages.length > 0) {
                    const warning = analysis.playerLoadStatusMessage();
                    logLoadStatus(warning, "warning");
                    showToast(warning, "warning", 5200);
                } else {
                    logLoadStatus(t("{player} geladen", { player: getCurrentPlayerLabel() }), "success");
                }
                return true;
            } catch (e) {
                if (requestId !== playerLoadRequestId) return false;
                console.error("loadPlayer:", e);
                const data = { error: t("Verbindungsfehler beim Laden des Spielers."), details: e?.message || "" };
                logLoadStatus(buildErrorMessage(data), "error");
                renderLoadError(data, t("Verbindungsfehler beim Laden des Spielers."));
                return false;
            } finally {
                if (loadingShown && requestId === playerLoadRequestId) hideLoading();
            }
        }



        async function loadWorldFromInput() {
            const requestId = ++worldLoadRequestId;
            // A world change invalidates every player response started for the
            // previously selected world, even before the new world request has
            // completed.
            playerLoadRequestId += 1;
            playerListRequestId += 1;
            clearLoadError();
            const state = getState();
            if (state.isDirty) {
                const ok = await showConfirmDialog(t("Es gibt ungespeicherte Änderungen. Welt trotzdem wechseln?"));
                if (!ok) {
                    logLoadStatus(t("Weltwechsel abgebrochen."), "warning");
                    return false;
                }
                if (requestId !== worldLoadRequestId) return false;
            }

            const nextWorldPath = String(worldPathInput?.value || state.worldPath || "").trim();
            if (!nextWorldPath) {
                logLoadStatus(t("Bitte erst eine Welt auswählen oder einen direkten Weltordner angeben."), "error");
                worldSearchInput?.focus?.();
                return false;
            }

            const localAccessOk = await confirmLocalWorldAccessBeforeOpen(nextWorldPath);
            if (requestId !== worldLoadRequestId) return false;
            if (!localAccessOk) {
                logLoadStatus(t("Laden abgebrochen. Schließe Minecraft/Server, bevor du die Welt öffnest."), "warning");
                return false;
            }

            if (loadButton) loadButton.disabled = true;
            showLoading(t("1/2 Welt prüfen und Spieler erkennen..."));
            logLoadStatus(t("Lade Welt und Spieler..."), "running");
            try {
                const data = await getPlayerApi().listPlayers(nextWorldPath);
                if (requestId !== worldLoadRequestId) return false;

                if (!data.success) {
                    const msg = buildErrorMessage(data, t("Welt konnte nicht geladen werden."));
                    logLoadStatus(t("Fehler: {error}", { error: msg }), "error");
                    renderLoadError(data, t("Welt konnte nicht geladen werden."));
                    showToast(t("Welt konnte nicht geladen werden – Details stehen unter dem Pfadfeld."), "error", 6000);
                    return false;
                }

                showLoading(t("2/2 Spieler vorbereiten..."));
                const nextPlayers = data.players || [];
                setState({ worldPath: nextWorldPath, players: nextPlayers });
                if (worldNameElement) worldNameElement.innerText = data.world_name;
                if (worldBanner) worldBanner.style.display = "flex";
                if (playerManager) playerManager.style.display = "flex";
                renderPlayersList();
                loadBackupsList();
                recordAction(t("Welt geladen: {world}", { world: data.world_name || nextWorldPath }), "load");
                saveRecentWorld(nextWorldPath, data.world_name);
                renderRecentWorlds();
                renderWorldAnalysis();

                const firstEditable = nextPlayers.find(player => player.editable);
                if (firstEditable) {
                    await loadPlayer(firstEditable.player_key, true, { showLoadingOverlay: false });
                    if (requestId !== worldLoadRequestId) return false;
                } else {
                    resetLoadedPlayerState({ showEmptyState: false });
                    if (playerManager) playerManager.style.display = "flex";
                    renderPlayersList();
                    renderPlayerToolOptions();
                    renderWorldAnalysis();
                    await updateWorldPresence();
                    setWorkflowView("player", { scroll: false });
                    logLoadStatus(t("Welt geladen, aber keine editierbaren Spieler erkannt. Details stehen in der Spieler-Liste und in der Spieler-Diagnose."), "warning");
                }
                return true;
            } catch (e) {
                if (requestId !== worldLoadRequestId) return false;
                console.error("loadWorldFromInput:", e);
                const data = { error: t("Verbindungsfehler beim Laden der Welt."), details: e?.message || "" };
                logLoadStatus(buildErrorMessage(data), "error");
                renderLoadError(data, t("Verbindungsfehler beim Laden der Welt."));
                return false;
            } finally {
                if (requestId === worldLoadRequestId) {
                    hideLoading();
                    if (loadButton) loadButton.disabled = false;
                }
            }
        }

        function saveRecentWorld(path, name) {
            saveWorkspace({ world_path: path, world_name: name || path });
            deps.clearRecentWorldSession?.();
        }

        function renderRecentWorlds() {
            if (recentWorldsEl) recentWorldsEl.style.display = "none";
            if (recentWorldsList) recentWorldsList.innerHTML = "";
        }

        function wire() {
            btnRefreshPlayers?.addEventListener?.("click", () => loadPlayersList(false));
        }

        return {
            loadPlayer,
            loadPlayersList,
            loadWorldFromInput,
            renderPlayersList,
            renderRecentWorlds,
            resetLoadedPlayerState,
            saveRecentWorld,
            selectExportOnlyPlayer,
            wire,
        };
    }

    function collectPlayerLoadElements(doc = document) {
        return {
            playersList: doc.getElementById("playersList"),
            playerManager: doc.getElementById("playerManager"),
            inventoryContainer: doc.getElementById("inventoryContainer"),
            btnExportPlayer: doc.getElementById("btnExportPlayer"),
            btnImportPlayer: doc.getElementById("btnImportPlayer"),
            btnSave: doc.getElementById("btnSave"),
            btnUndo: doc.getElementById("btnUndo"),
            btnRedo: doc.getElementById("btnRedo"),
            btnRefreshPlayers: doc.getElementById("btnRefreshPlayers"),
            playerInventorySummary: doc.getElementById("playerInventorySummary"),
            emptyState: doc.getElementById("emptyState"),
            detailEditorPanel: doc.getElementById("detailEditorPanel"),
            multiSelectPanel: doc.getElementById("multiSelectPanel"),
            dashboardPanel: doc.getElementById("dashboardPanel"),
            recentWorldsEl: doc.getElementById("recentWorlds"),
            recentWorldsList: doc.getElementById("recentWorldsList"),
            loadButton: doc.getElementById("btnLoad"),
            worldPathInput: doc.getElementById("worldPath"),
            worldSearchInput: doc.getElementById("worldSearchInput"),
            worldNameElement: doc.getElementById("worldName"),
            worldBanner: doc.getElementById("worldBanner"),
        };
    }

    function createInventoryPlayerLoadController({ doc = document, ...deps } = {}) {
        return createPlayerLoadController({
            ...deps,
            elements: collectPlayerLoadElements(doc),
        });
    }

    window.MCBEPlayerLoadController = {
        collectPlayerLoadElements,
        createInventoryPlayerLoadController,
        createPlayerLoadController,
        workflowViewAfterPlayerLoad,
    };
}());
