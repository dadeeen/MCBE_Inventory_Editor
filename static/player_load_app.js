(function () {
    "use strict";

    const FACADE_METHODS = Object.freeze([
        "loadPlayer",
        "loadPlayersList",
        "loadWorldFromInput",
        "renderPlayersList",
        "renderRecentWorlds",
        "resetLoadedPlayerState",
    ]);

    function requiredFunction(value, name) {
        if (typeof value !== "function") {
            throw new Error(`${name} must be provided.`);
        }
        return value;
    }

    function callController(controller, method, args) {
        const fn = controller?.[method];
        if (typeof fn !== "function") {
            throw new Error(`Player-load controller method missing: ${method}`);
        }
        return fn.apply(controller, args);
    }

    function createInventoryPlayerLoadApp({
        doc = document,
        controllerFactory = window.MCBEPlayerLoadController?.createInventoryPlayerLoadController,
        state = {},
        api = {},
        feedback = {},
        actions = {},
        ui = {},
        constants = {},
    } = {}) {
        const controller = requiredFunction(
            controllerFactory,
            "MCBEPlayerLoadController.createInventoryPlayerLoadController",
        )({
            doc,
            getState: state.getPlayerLoadState,
            setState: state.assignAppState,
            withCsrf: api.withCsrf,
            parseJsonResponse: api.parseJsonResponse,
            buildErrorMessage: api.buildErrorMessage,
            showConfirmDialog: feedback.showConfirmDialog,
            showToast: feedback.showToast,
            showLoading: feedback.showLoading,
            hideLoading: feedback.hideLoading,
            logStatus: actions.logStatus,
            copyTextToClipboard: actions.copyTextToClipboard,
            buildPlayersDiagnosticsText: actions.buildPlayersDiagnosticsText,
            renderLoadError: actions.renderLoadError,
            saveWorkspace: actions.saveWorkspace,
            annotateItemOrigins: actions.annotateItemOrigins,
            updateProtectedKnownSlotsFromMeta: actions.updateProtectedKnownSlotsFromMeta,
            normalizeServerGuardEpoch: actions.normalizeServerGuardEpoch,
            beginServerStatusRequest: actions.beginServerStatusRequest,
            clearLoadedPlayerStaleState: actions.clearLoadedPlayerStaleState,
            markLoadedPlayerStale: actions.markLoadedPlayerStale,
            renderServerStatus: actions.renderServerStatus,
            updatePlayerExportFolderControl: actions.updatePlayerExportFolderControl,
            updateImportControls: actions.updateImportControls,
            updateWriteControls: actions.updateWriteControls,
            scheduleWorldPresenceUpdate: actions.scheduleWorldPresenceUpdate,
            renderPlayerToolOptions: actions.renderPlayerToolOptions,
            renderStatusCenter: actions.renderStatusCenter,
            updateAppMode: actions.updateAppMode,
            updateWorldPresence: actions.updateWorldPresence,
            renderWorldAnalysis: actions.renderWorldAnalysis,
            setWorkflowView: actions.setWorkflowView,
            getActiveWorkflowView: actions.getActiveWorkflowView,
            loadLocalIconIndex: actions.loadLocalIconIndex,
            renderStatsForm: actions.renderStatsForm,
            clearTouchedStatsFields: ui.clearTouchedStatsFields,
            setStatsProtectionUI: actions.setStatsProtectionUI,
            buildGrids: actions.buildGrids,
            getInventoryViewPreferences: actions.getInventoryViewPreferences,
            updateGridVisuals: actions.updateGridVisuals,
            clearSelection: actions.clearSelection,
            markCleanState: actions.markCleanState,
            renderPlayerInventorySummary: actions.renderPlayerInventorySummary,
            recordAction: actions.recordAction,
            getCurrentPlayerLabel: actions.getCurrentPlayerLabel,
            getAnalysisLogic: actions.getAnalysisLogic,
            resetUndoRedoForUnloadedPlayer: ui.resetUndoRedoForUnloadedPlayer,
            clearGridSearch: ui.clearGridSearch,
            clearLoadError: actions.clearLoadError,
            confirmLocalWorldAccessBeforeOpen: actions.confirmLocalWorldAccessBeforeOpen,
            loadBackupsList: actions.loadBackupsList,
            clearRecentWorldSession: ui.clearRecentWorldSession,
            defaultMaxDamage: constants.defaultMaxDamage,
            appConfig: constants.appConfig || {},
            exportBlocked: actions.exportBlocked,
        });

        const app = { controller };
        FACADE_METHODS.forEach(method => {
            app[method] = (...args) => callController(controller, method, args);
        });
        app.wire = (...args) => callController(controller, "wire", args);
        return app;
    }

    window.MCBEPlayerLoadApp = {
        createInventoryPlayerLoadApp,
        facadeMethods: () => FACADE_METHODS.slice(),
    };
}());
