(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function hasLoadedEditablePlayer(context = {}) {
        return Boolean(context.currentPlayerKey && context.currentPlayer && context.inventoryVisible);
    }

    function hasLoadedMountReferencePlayer(context = {}) {
        return Boolean(context.worldPath && context.currentPlayerKey && context.currentPlayer);
    }

    function viewAllowed(view, context = {}) {
        if (view === "world" || view === "tools") return true;
        if (view === "player") return Boolean(context.worldPath);
        if (view === "inventory" || view === "save") return hasLoadedEditablePlayer(context);
        if (view === "mounts") return hasLoadedMountReferencePlayer(context);
        return false;
    }

    function fallbackView(context = {}) {
        if (hasLoadedEditablePlayer(context)) return context.activeWorkflowView === "save" ? "save" : "inventory";
        if (context.worldPath) return "player";
        return "world";
    }

    function viewTitle(view) {
        return {
            world: t("Welt auswählen"),
            player: t("Spieler wählen"),
            inventory: t("Inventar bearbeiten"),
            mounts: t("Mounts erzeugen"),
            save: t("Änderungen prüfen & speichern"),
            tools: t("Tools & Diagnose"),
        }[view] || t("Arbeitsbereich");
    }

    function disabledReason(view, context = {}) {
        if (view === "world") return t("Welt suchen oder wechseln.");
        if (view === "player" && !context.worldPath) return t("Lade zuerst eine Welt.");
        if (view === "tools") return t("Diagnose, Icons, Backups und technische Details öffnen.");
        if ((view === "inventory" || view === "save") && !hasLoadedEditablePlayer(context)) return t("Lade zuerst einen bearbeitbaren Spieler.");
        if (view === "mounts" && !hasLoadedMountReferencePlayer(context)) return t("Lade zuerst einen Spieler.");
        if (view === "save" && !context.isDirty) return t("Keine ungespeicherten Änderungen.");
        return viewTitle(view);
    }

    function unavailableMessage(view) {
        if (view === "inventory" || view === "save") return t("Lade zuerst einen bearbeitbaren Spieler.");
        if (view === "mounts") return t("Lade zuerst einen Spieler.");
        if (view === "player") return t("Lade zuerst eine Welt.");
        return t("Dieser Arbeitsbereich ist aktuell nicht verfügbar.");
    }

    function resolvedView(requestedView, context = {}) {
        const requested = String(requestedView || "world");
        return viewAllowed(requested, context) ? requested : fallbackView(context);
    }

    function navButtonModel(view, activeView, context = {}) {
        const active = view === activeView;
        return {
            active,
            ariaCurrent: active ? "page" : "false",
            disabled: !viewAllowed(view, context),
            title: disabledReason(view, context),
        };
    }

    function appBodyClassModel(context = {}) {
        return {
            "app-world-loaded": Boolean(context.worldPath),
            "app-player-loaded": hasLoadedEditablePlayer(context),
            "app-dirty": Boolean(context.isDirty),
        };
    }


    function createResponsivePanelController({
        win = window,
        doc = document,
        breakpoint = 1024,
        leftPanel = null,
        rightPanel = null,
        panelToggles = [],
    } = {}) {
        const toggles = Array.from(panelToggles || []);

        function isNarrowViewport() {
            return win.innerWidth <= breakpoint;
        }

        function activatePanel(panel) {
            toggles.forEach(btn => btn.classList.toggle("active", btn.dataset.panel === panel));
            if (leftPanel) leftPanel.classList.toggle("visible", panel === "left");
            if (rightPanel) rightPanel.classList.toggle("visible", panel === "right");
        }

        function activateForWorkflow(view) {
            if (!isNarrowViewport()) return;
            activatePanel(view === "world" ? "left" : "right");
        }

        function sync() {
            if (isNarrowViewport()) {
                toggles.forEach(btn => { btn.style.display = ""; });
                const activeToggle = doc.querySelector(".btn-toggle.active");
                activatePanel(activeToggle?.dataset.panel || "left");
            } else {
                toggles.forEach(btn => { btn.style.display = "none"; });
                if (leftPanel) leftPanel.classList.remove("visible");
                if (rightPanel) rightPanel.classList.remove("visible");
            }
        }

        function wire() {
            toggles.forEach(btn => {
                btn.addEventListener("click", () => activatePanel(btn.dataset.panel));
            });
            if (isNarrowViewport()) activatePanel("left");
            else sync();
            win.addEventListener("resize", sync);
        }

        return { activateForWorkflow, activatePanel, isNarrowViewport, sync, wire };
    }

    function createWorkflowShellController({
        doc = document,
        body = document.body,
        navButtons = [],
        getActiveView = () => "world",
        setActiveView = () => {},
        getContext = () => ({}),
        getScrollTarget = () => doc.body,
        responsivePanels = null,
        showToast = () => {},
        switchToPlayerDashboard = () => {},
        renderSaveWorkflowPanel = () => {},
        renderToolsDashboard = () => {},
        renderMountsPanel = () => {},
    } = {}) {
        const buttons = Array.from(navButtons || []);

        function currentContext() {
            return getContext() || {};
        }

        function applyShellState() {
            const activeView = getActiveView();
            body.dataset.workflowView = activeView;
            // In der dedizierten Tools-Ansicht sollen die Werkzeug-Tabs sofort
            // sichtbar sein; im kombinierten Dashboard bleiben sie eingeklappt,
            // bis der Nutzer sie braucht.
            const toolsDetails = doc.getElementById("toolsSettingsDetails");
            if (toolsDetails && activeView === "tools") toolsDetails.open = true;
            responsivePanels?.activateForWorkflow?.(activeView);
            buttons.forEach(btn => {
                const model = navButtonModel(btn.dataset.workflowView, activeView, currentContext());
                btn.classList.toggle("active", model.active);
                btn.disabled = model.disabled;
                btn.title = model.title;
                btn.setAttribute("aria-current", model.ariaCurrent);
            });
        }

        function updateAppMode() {
            const classModel = appBodyClassModel(currentContext());
            Object.entries(classModel).forEach(([className, enabled]) => {
                body.classList.toggle(className, enabled);
            });
            setActiveView(resolvedView(getActiveView(), currentContext()));
            applyShellState();
            renderSaveWorkflowPanel();
        }

        function setWorkflowView(view, { scroll = true, user = false } = {}) {
            const requested = String(view || "world");
            if (user && !viewAllowed(requested, currentContext())) showToast(unavailableMessage(requested), "warning", 2600);
            const activeView = resolvedView(requested, currentContext());
            setActiveView(activeView);
            applyShellState();

            if (activeView === "player") switchToPlayerDashboard();
            if (activeView === "save") renderSaveWorkflowPanel();
            if (activeView === "tools") renderToolsDashboard();
            if (activeView === "mounts") renderMountsPanel();

            if (scroll) {
                const target = getScrollTarget(activeView) || doc.body;
                setTimeout(() => target?.scrollIntoView?.({ behavior: "smooth", block: "start" }), 0);
            }
        }

        function wireNav() {
            buttons.forEach(btn => {
                // Main navigation behaves like tabs: switching the visible work
                // area must not unexpectedly move the page. Callers that open a
                // specific workflow action can still request scrolling explicitly.
                btn.addEventListener("click", () => setWorkflowView(btn.dataset.workflowView, { scroll: false, user: true }));
            });
        }

        return { applyShellState, setWorkflowView, updateAppMode, wireNav };
    }




    function createInventoryEditorWorkflowShell({
        win = window,
        doc = document,
        body = document.body,
        navButtons = [],
        getActiveView = () => "world",
        setActiveView = () => {},
        getContext = () => ({}),
        targets = {},
        showToast = () => {},
        onPlayerView = () => {},
        onSaveView = () => {},
        onToolsView = () => {},
        onMountsView = () => {},
    } = {}) {
        const responsivePanelController = createResponsivePanelController({
            win,
            doc,
            leftPanel: doc.querySelector(".left-panel"),
            rightPanel: doc.querySelector(".right-panel"),
            panelToggles: doc.querySelectorAll(".btn-toggle"),
        });
        const workflowShellController = createWorkflowShellController({
            doc,
            body,
            navButtons,
            getActiveView,
            setActiveView,
            getContext,
            responsivePanels: responsivePanelController,
            showToast,
            getScrollTarget: view => view === "world" ? (targets.world || doc.body)
                : view === "player" ? targets.player
                : view === "mounts" ? targets.mounts
                : view === "save" ? targets.save
                : view === "tools" ? targets.tools
                : targets.inventory,
            switchToPlayerDashboard: onPlayerView,
            renderSaveWorkflowPanel: onSaveView,
            renderToolsDashboard: onToolsView,
            renderMountsPanel: onMountsView,
        });
        workflowShellController.wireNav();
        return {
            responsivePanelController,
            workflowShellController,
            setWorkflowView: (view, options = {}) => workflowShellController.setWorkflowView(view, options),
            updateAppMode: () => workflowShellController.updateAppMode(),
        };
    }


    function createConfiguredInventoryEditorWorkflowShell({
        win = window,
        doc = document,
        state = {},
        actions = {},
        helpers = {},
    } = {}) {
        const inventoryContainer = doc.getElementById("inventoryContainer");
        return createInventoryEditorWorkflowShell({
            win,
            doc,
            body: doc.body,
            navButtons: Array.from(doc.querySelectorAll('[data-workflow-view]')),
            getActiveView: state.getActiveView || (() => "world"),
            setActiveView: state.setActiveView || (() => {}),
            getContext: () => ({
                activeWorkflowView: state.getActiveView?.() || "world",
                currentPlayer: state.getCurrentPlayer?.() || null,
                currentPlayerKey: state.getCurrentPlayerKey?.() || "",
                inventoryVisible: Boolean(inventoryContainer && inventoryContainer.style.display !== "none"),
                isDirty: Boolean(state.getIsDirty?.()),
                worldPath: state.getWorldPath?.() || "",
            }),
            targets: {
                world: doc.getElementById("worldPicker"),
                player: doc.getElementById("playerManager"),
                inventory: inventoryContainer,
                mounts: doc.getElementById("mountsPanel"),
                save: doc.getElementById("saveWorkflowPanel"),
                tools: doc.getElementById("dashboardPanel"),
            },
            showToast: helpers.showToast,
            onPlayerView: actions.onPlayerView,
            onSaveView: actions.onSaveView,
            onToolsView: actions.onToolsView,
            onMountsView: actions.onMountsView,
        });
    }


    function createTabController({
        doc = document,
        buttonSelector = ".tab-btn",
        contentSelector = ".tab-content",
        buttonAttribute = "data-tab",
        activeClass = "active",
        onSwitch = () => {},
    } = {}) {
        function switchTo(tabId) {
            const target = String(tabId || "");
            doc.querySelectorAll(buttonSelector).forEach(btn => {
                btn.classList.toggle(activeClass, btn.getAttribute(buttonAttribute) === target);
            });
            doc.querySelectorAll(contentSelector).forEach(content => {
                content.classList.toggle(activeClass, content.id === target);
            });
            onSwitch(target);
        }

        function wire() {
            doc.querySelectorAll(buttonSelector).forEach(btn => {
                btn.addEventListener("click", event => {
                    const targetTab = event.currentTarget.getAttribute(buttonAttribute);
                    if (targetTab) switchTo(targetTab);
                });
            });
        }

        return { switchTo, wire };
    }

    function createAppKeyboardController({
        doc = document,
        inventoryClipboardController = null,
        isEditableTextTarget = target => target?.matches?.("input, textarea, select, [contenteditable='true']"),
        undo = () => {},
        redo = () => {},
        saveButton = null,
        getActiveWorkflowView = () => "world",
        inventoryContainer = null,
        gridSearch = null,
        currentSelectionState = () => ({}),
        hasSelection = selection => Boolean(selection),
        clearSelection = () => {},
        showToast = () => {},
    } = {}) {
        function handleKeydown(event) {
            const isEditableTarget = isEditableTextTarget(event.target);
            if ((event.ctrlKey || event.metaKey) && event.key === "z" && !event.shiftKey && !isEditableTarget) {
                event.preventDefault();
                undo();
                return;
            }
            if ((event.ctrlKey || event.metaKey) && (event.key === "y" || (event.key === "z" && event.shiftKey)) && !isEditableTarget) {
                event.preventDefault();
                redo();
                return;
            }
            if (inventoryClipboardController?.handleKeydown?.(event)) return;
            if ((event.ctrlKey || event.metaKey) && event.key === "s") {
                event.preventDefault();
                saveButton?.click();
                return;
            }
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f" && !isEditableTarget) {
                if (getActiveWorkflowView() === "inventory" && inventoryContainer && inventoryContainer.style.display !== "none" && gridSearch) {
                    event.preventDefault();
                    gridSearch.focus();
                    gridSearch.select();
                }
            }
            if (event.key === "Escape" && !doc.querySelector('.modal-overlay[style*="flex"]')) {
                if (hasSelection(currentSelectionState())) {
                    event.preventDefault();
                    clearSelection();
                    showToast(t("Auswahl aufgehoben"), "success", 1800);
                }
            }
        }

        function wire() {
            doc.addEventListener("keydown", handleKeydown);
        }

        return { handleKeydown, wire };
    }


    function createConfiguredAppKeyboardController({
        doc = document,
        inventoryClipboardController = null,
        actions = {},
        state = {},
        selection = {},
        helpers = {},
    } = {}) {
        return createAppKeyboardController({
            doc,
            inventoryClipboardController,
            isEditableTextTarget: helpers.isEditableTextTarget,
            undo: actions.undo,
            redo: actions.redo,
            saveButton: doc.getElementById("btnSave"),
            getActiveWorkflowView: state.getActiveWorkflowView,
            inventoryContainer: doc.getElementById("inventoryContainer"),
            gridSearch: doc.getElementById("gridSearch"),
            currentSelectionState: selection.currentSelectionState,
            hasSelection: selection.hasSelection,
            clearSelection: selection.clearSelection,
            showToast: helpers.showToast,
        });
    }

    function createConfiguredSlotTabController({ doc = document } = {}) {
        return createTabController({
            doc,
            buttonSelector: ".tab-btn",
            contentSelector: ".tab-content",
            buttonAttribute: "data-tab",
        });
    }

    function createConfiguredDashboardTabController({
        doc = document,
        loadAuditEvents = () => {},
        loadRuntimeDiagnostics = () => {},
        loadBackupsList = () => {},
    } = {}) {
        const controller = createTabController({
            doc,
            buttonSelector: ".tab-btn-dash",
            contentSelector: ".tab-content-dash",
            buttonAttribute: "data-tab-dash",
            onSwitch(tabId) {
                if (tabId === "dashAudit") loadAuditEvents();
                if (tabId === "dashDiagnostics") loadRuntimeDiagnostics();
                if (tabId === "dashBackups") loadBackupsList();
            },
        });
        // When the collapsible tools section is closed while one of its tabs
        // is active, fall back to the player stats tab so no orphaned tool
        // panel stays visible below the collapsed section.
        const toolsDetails = doc.getElementById("toolsSettingsDetails");
        toolsDetails?.addEventListener("toggle", () => {
            if (toolsDetails.open) return;
            const activeButton = doc.querySelector(".tab-btn-dash.active");
            if (activeButton && toolsDetails.contains(activeButton)) {
                doc.querySelector('.tab-btn-dash[data-tab-dash="dashStats"]')?.click();
            }
        });
        return controller;
    }




    function createDirtyStateController({
        getIsDirty = () => false,
        setIsDirty = () => {},
        getWorldPath = () => "",
        effectiveWriteGate = () => null,
        logStatus = () => {},
        clearStatus = () => false,
        transientDirtyNoticeCategory = "dirty",
        scheduleWorldPresenceUpdate = () => {},
        updateWriteControls = () => {},
        renderPlayerInventorySummary = () => {},
        renderStatusCenter = () => {},
        renderSaveWorkflowPanel = () => {},
        updateAppMode = () => {},
    } = {}) {
        function setDirty(dirty) {
            const changed = getIsDirty() !== dirty;
            setIsDirty(Boolean(dirty));
            updateWriteControls();
            renderPlayerInventorySummary();
            if (changed && getWorldPath()) scheduleWorldPresenceUpdate();
            if (dirty) {
                const gate = effectiveWriteGate();
                if (
                    gate?.allowed !== false
                    || gate?.requires_unknown_server_confirmation === true
                ) {
                    logStatus(t("Ungespeicherte Änderungen vorhanden"), "warning", {
                        category: transientDirtyNoticeCategory,
                        key: transientDirtyNoticeCategory,
                        active: true,
                    });
                }
            } else {
                clearStatus(transientDirtyNoticeCategory);
            }
            renderStatusCenter();
            renderSaveWorkflowPanel();
            updateAppMode();
        }

        return { setDirty };
    }

    function createAppLifecycleController({
        win = window,
        appConfig = {},
        withCsrf = () => ({}),
        getIsDirty = () => false,
        refreshServerStatus = async () => {},
        getWorldPresenceController = () => null,
        scanPathsController = null,
        scanWorlds = () => {},
        renderRecentWorlds = () => {},
    } = {}) {
        function wireDirtyUnload() {
            win.addEventListener("beforeunload", event => {
                if (!getIsDirty()) return;
                event.preventDefault();
                event.returnValue = "";
            });
        }

        function startHeartbeat() {
            if (appConfig?.mode !== "local") return;
            win.setInterval(async () => {
                try {
                    await fetch("/api/heartbeat", { method: "POST", headers: withCsrf() });
                } catch (_e) {}
            }, 2000);
        }

        function startServerStatusPolling() {
            refreshServerStatus();
            win.setInterval(refreshServerStatus, 10000);
        }

        function startWorldPresence() {
            const controller = getWorldPresenceController();
            controller?.startPolling?.();
            controller?.wireBeforeUnload?.();
        }

        function startInitialWorldScan() {
            scanPathsController?.loadScanPaths?.().finally(scanWorlds);
            renderRecentWorlds();
        }

        function start() {
            wireDirtyUnload();
            startHeartbeat();
            startServerStatusPolling();
            startWorldPresence();
            startInitialWorldScan();
        }

        return {
            start,
            startHeartbeat,
            startInitialWorldScan,
            startServerStatusPolling,
            startWorldPresence,
            wireDirtyUnload,
        };
    }

    function createInventoryEditorBootController({
        doc = document,
        helpOverlayController = null,
        inventoryViewPreferences = null,
        closeDetailButton = null,
        clearSelection = () => {},
        responsivePanelController = null,
        lifecycleController = null,
        workspaceController = null,
        workspaceActions = {},
        renderWorkspacePanel = () => {},
        iconSourcesController = null,
        loadLocalIconIndex = () => {},
        loadItemDbStatus = () => {},
        onInitialDataLoaded = () => {},
        setInitialWorkflowView = () => {},
        updateGridVisuals = () => {},
    } = {}) {
        function wireInventoryViewControls() {
            const detailClose = closeDetailButton || doc.getElementById("btnCloseDetail");
            inventoryViewPreferences?.wireControls?.({ onSlotNumbersChanged: updateGridVisuals });
            detailClose?.addEventListener?.("click", clearSelection);
            responsivePanelController?.wire?.();
        }

        function wireWorkspace() {
            const configuredWorkspaceActions = {
                doc,
                themeSelect: doc.getElementById("themeSelect"),
                favoriteButton: doc.getElementById("btnFavoriteCurrentWorld"),
                copyButton: doc.getElementById("btnCopyWorkspace"),
                clearButton: doc.getElementById("btnClearWorkspace"),
                ...workspaceActions,
            };
            workspaceController?.wireActions?.(configuredWorkspaceActions);
            renderWorkspacePanel();
        }

        async function startInitialDataLoads() {
            iconSourcesController?.wire?.();
            // The first-run overlay decides from both statuses, so it may only run
            // once each load settled. allSettled keeps a failing status from
            // suppressing the other one's todo.
            await Promise.allSettled([loadLocalIconIndex({ rescan: false }), loadItemDbStatus()]);
            onInitialDataLoaded();
        }

        function start() {
            const configuredHelpOverlayController = helpOverlayController || window.MCBEUiFeedback?.createHelpOverlayController?.({
                doc,
                openButton: doc.getElementById("btnHelp"),
                closeButton: doc.getElementById("btnHelpClose"),
                overlay: doc.getElementById("helpOverlay"),
            });
            configuredHelpOverlayController?.wire?.();
            wireInventoryViewControls();
            lifecycleController?.start?.();
            wireWorkspace();
            startInitialDataLoads();
            setInitialWorkflowView("world", { scroll: false });
        }

        return {
            start,
            startInitialDataLoads,
            wireInventoryViewControls,
            wireWorkspace,
        };
    }

    window.MCBEWorkflowState = {
        appBodyClassModel,
        hasLoadedEditablePlayer,
        hasLoadedMountReferencePlayer,
        navButtonModel,
        resolvedView,
        unavailableMessage,
        viewAllowed,
        fallbackView,
        viewTitle,
        disabledReason,
        createResponsivePanelController,
        createWorkflowShellController,
        createInventoryEditorWorkflowShell,
        createConfiguredInventoryEditorWorkflowShell,
        createInventoryEditorBootController,
        createAppKeyboardController,
        createConfiguredAppKeyboardController,
        createConfiguredSlotTabController,
        createConfiguredDashboardTabController,
        createDirtyStateController,
        createAppLifecycleController,
        createTabController,
    };
}());
