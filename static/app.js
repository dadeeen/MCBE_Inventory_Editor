const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
const appRuntime = window.MCBEAppBootstrap.createRuntimeContext({ doc: document, win: window });
const withCsrf = appRuntime.withCsrf;
const parseJsonResponse = appRuntime.parseJsonResponse;
const buildErrorMessage = appRuntime.buildErrorMessage;
const appConfig = appRuntime.appConfig;
const browserStorageKeys = appRuntime.storageKeys;
const {
    recentWorlds: RECENT_WORLDS_KEY,
    sessionRecentWorlds: SESSION_RECENT_WORLDS_KEY,
    workspace: WORKSPACE_KEY,
    favoriteWorlds: FAVORITE_WORLDS_KEY,
    theme: THEME_KEY,
    storageSchema: STORAGE_SCHEMA_KEY,
    slotNumbers: SLOT_NUMBERS_KEY,
    enderCollapsed: ENDER_COLLAPSED_KEY,
} = browserStorageKeys;
const CURRENT_STORAGE_SCHEMA = appRuntime.currentStorageSchema;
const {
    maxSessionLog: MAX_SESSION_LOG,
    maxHeaderNotices: MAX_HEADER_NOTICES,
    inventorySlotCount: INVENTORY_SLOT_COUNT,
    enderChestSlotCount: ENDER_CHEST_SLOT_COUNT,
    maxUndo: MAX_UNDO,
    defaultMaxDamage: DEFAULT_MAX_DAMAGE,
    maxBedrockStackCount: MAX_BEDROCK_STACK_COUNT,
    maxDisplayName: MAX_DISPLAY_NAME,
    maxLoreLines: MAX_LORE_LINES,
    maxLoreLineLength: MAX_LORE_LINE_LEN,
    itemIdPattern: ITEM_ID_PATTERN,
} = appRuntime.constants;
const ITEM_ID_RE = new RegExp(ITEM_ID_PATTERN);

// State variables
let worldPath = "";
let inventory = {};      // Local copy of inventory (Slot -> Item Object)
let enderChestInventory = {};  // Local copy of ender chest (Slot -> Item Object)
let hasEnderChest = false;    // Whether the player originally had an EnderChestInventory tag
let inventoryCreateRequiresConfirmation = false; // Player has no Inventory tag; creating one must be explicit
let enderChestCreateRequiresConfirmation = false; // Player has no EnderChestInventory tag; creating one must be explicit
let effectsCreateRequiresConfirmation = false; // Player has no ActiveEffects tag; creating one must be explicit
let abilitiesCreateRequiresConfirmation = false; // Player has no abilities tag; creating one must be explicit
let effectsTouched = false;
let abilitiesTouched = false;
let selectedSlots = [];  // Array of currently selected slots (integers)
let selectedEnderSlot = -1; // Currently selected ender chest slot (-1 = none)
let itemsDb = {};        // From backend: ID -> [de_name, en_name]
let compatItemAliases = {}; // Runtime/legacy IDs known to Minecraft, mapped to browser-visible canonical IDs
let addableItems = new Set(); // Positive Mojang-Item-Registry: nur diese IDs dürfen neu erzeugt werden
let blockOnlyItems = new Set(); // IDs, die Mojang nur als Block registriert; nicht als Item vorschlagbar
let blockItems = new Set(); // Registry-abgeleitete Blockitems; zusätzliche Browser-Kategorie „Blöcke“
let itemIconIndex = {};   // Local user-owned Minecraft/resource-pack icons, indexed by item ID
let iconSourceSummary = { status: "loading", count: 0, roots: [], warnings: [] };
let itemDbStatus = null;
let enchDb = {};         // From backend: ID -> {name_de, name_en, max_lvl}
let enchantmentCompatibility = {}; // From backend: vanilla enchantment slot compatibility data
let itemComponents = {}; // From Mojang behavior items: enchantable/repairable/wearable/dyeable
let stackLimits = {};    // From backend: item_name -> max_stack (or __default__ = 64)
let maxDamage = {};      // From backend: item_name -> max_damage (or __default__ = 32767)
let isDirty = false;
let players = [];
let currentPlayerKey = "";
let currentPlayer = null;
let currentPlayerRevision = "";
let selectedWorld = null;
let lastWorldScan = null;
let lastRenderedWorlds = [];
const TRANSIENT_DIRTY_NOTICE_CATEGORY = window.MCBEStatusStore.TRANSIENT_DIRTY_NOTICE_CATEGORY;
const statusNoticeStore = window.MCBEStatusStore.createStatusStore({ maxNotices: MAX_HEADER_NOTICES });
let lastInventorySummary = null;
let inventoryViewPreferences = null;
let activeWorkflowView = "world";

window.MCBEWorkspaceView.migrateBrowserStorage({
    localStorage,
    sessionStorage,
    keys: browserStorageKeys,
    currentSchema: CURRENT_STORAGE_SCHEMA,
});

let themeController = null;
let workspaceController = null;
let mountController = null;

// Appearance and workspace helpers
function getThemeController() {
    if (!themeController) {
        themeController = window.MCBEThemeController.createConfiguredThemeController({
            doc: document,
            storage: localStorage,
            storageKey: THEME_KEY,
        });
    }
    return themeController;
}
function getAppTheme() { return getThemeController().getTheme(); }
function applyTheme(theme) { return getThemeController().applyTheme(theme); }

function getWorkspaceController() {
    if (!workspaceController) {
        workspaceController = window.MCBEWorkspaceView.createInventoryWorkspaceController({
            doc: document,
            localStorage,
            sessionStorage,
            keys: browserStorageKeys,
            currentSchema: CURRENT_STORAGE_SCHEMA,
            appConfig,
            getTheme: getAppTheme,
            getShowSlotNumbers: () => getInventoryViewPreferences().getShowSlotNumbers(),
            getEnderCollapsed: () => getInventoryViewPreferences().getEnderChestCollapsed(),
            onFavoriteSelected: world => {
                updateSelectedWorld(world);
                showToast(t("Favorit ausgewählt. Zum Öffnen: Ausgewählte Welt laden."), "success");
            },
            showToast,
            applyTheme,
            copyTextToClipboard,
            getSelectedWorld: () => selectedWorld,
            getWorldPath: () => worldPath,
            renderRecentWorlds,
        });
    }
    return workspaceController;
}
function saveWorkspace(patch = {}) {
    return getWorkspaceController().saveWorkspace(patch);
}
function renderWorkspacePanel() {
    return getWorkspaceController().renderWorkspacePanel();
}
function getMountController() {
    if (!mountController) {
        const mountApiClient = window.MCBEMountApi.createMountApiClient({
            fetchFn: fetch,
            withCsrf,
            parseJsonResponse,
            buildErrorMessage,
        });
        mountController = window.MCBEMountController.createMountController({
            doc: document,
            apiClient: mountApiClient,
            getWorldPath: () => worldPath,
            getCurrentPlayerKey: () => currentPlayerKey,
            getCurrentPlayer: () => currentPlayer,
            showToast,
            logStatus,
            onPendingChanged: () => setDirty(buildChangeSummary({ limit: 1, includeSections: true }).total > 0),
            onReviewRequested: () => setWorkflowView("save", { user: true }),
            pushUndo,
            guardEditingAction,
            syncEditControls: () => updateWriteControls(),
        });
    }
    return mountController;
}

function renderMountsPanel() {
    return getMountController().refresh();
}
function buildFallbackWriteGate(message = t("Serverstatus noch nicht geprüft.")) {
    return window.MCBEWriteStatusView.fallbackWriteGate(appConfig, message);
}

let currentWriteGate = buildFallbackWriteGate();
let currentServerGuardEpoch = 0;
let currentServerGuardToken = "";
let currentServerStatusRevision = 0;
let currentPlayerServerGuardEpoch = 0;
let currentPlayerServerGuardToken = "";
let currentPlayerStaleReason = "";
const PLAYER_STALE_SERVER_REASON = t("Nur ansehen: Der Bedrock-Server wurde seit dem Laden dieses Spielers online gesehen. Stoppe den Server und lade den Spieler neu, um ihn zu bearbeiten.");

// New State for Player Stats
let playerStats = {
    pos: [0.0, 70.0, 0.0],
    dimension_id: null,
    health: 20.0,
    gamemode: 0,
    xp_level: 0,
    xp_progress: 0.0,
    food_level: 20,
    food_saturation: 20.0
};

// Effects & Abilities state
let playerEffects = [];
let playerAbilities = {};
const stateSnapshot = window.MCBEStateSnapshot.createStateSnapshot(() => ({
    inventory,
    enderChestInventory,
    playerStats,
    playerEffects,
    playerAbilities,
    pendingMounts: getMountController().getPendingMounts(),
}));
const takeSnapshot = stateSnapshot.takeSnapshot;
const snapshotHash = window.MCBEStateSnapshot.snapshotHash;
let effectsDb = {};
let hiddenUnknownSlots = { inventory: 0, ender_chest: 0 };
let protectedKnownSlots = { inventory: [], ender_chest: [] };
let protectedNbt = {};
let currentCompatibility = {};
let currentImportPreview = null;
let lastPlayerExportDir = "";
const WORLD_PRESENCE_SESSION_KEY = "mcbe-inventory-editor:presenceSession";
const WORLD_PRESENCE_INTERVAL_MS = 8000;
const itemCatalog = window.MCBEItemCatalog.createItemCatalog({
    getItemsDb: () => itemsDb,
    getCompatItemAliases: () => compatItemAliases,
    getAddableItems: () => addableItems,
    getItemIconIndex: () => itemIconIndex,
    getStackLimits: () => stackLimits,
    getMaxDamageMap: () => maxDamage,
    getEnchantmentCompatibility: () => enchantmentCompatibility,
    getItemComponents: () => itemComponents,
    itemIdRe: ITEM_ID_RE,
    defaultMaxDamage: DEFAULT_MAX_DAMAGE,
    maxBedrockStackCount: MAX_BEDROCK_STACK_COUNT,
});
const itemAvailabilityCatalog = window.MCBEItemAvailability.createItemAvailabilityCatalog();

const {
    buildSlotTooltipLines,
    buildSlotTooltipEntries,
    detailItemLabel,
    itemDisplayName,
    itemHasRepairableDamage,
    itemIsVisiblePresent,
    slotAreaLabel,
    slotDisplayName,
} = window.MCBESlotDisplay.createInventorySlotDisplayFacade({ itemCatalog });

const showConfirmDialog = window.MCBEUiFeedback.showConfirmDialog;
const showLoading = window.MCBEUiFeedback.showLoading;
const hideLoading = window.MCBEUiFeedback.hideLoading;
const showToast = window.MCBEUiFeedback.showToast;

// DOM Elements
const {
    worldPathEl, btnSave, btnSaveReviewConfirm,
    worldNameEl, inventoryContainer, gridSearch,
} = window.MCBEAppDomRefs.collectAppDomRefs(document);

const workflowShell = window.MCBEWorkflowState.createConfiguredInventoryEditorWorkflowShell({
    win: window,
    doc: document,
    state: {
        getActiveView: () => activeWorkflowView,
        setActiveView: value => { activeWorkflowView = value; },
        getCurrentPlayer: () => currentPlayer,
        getCurrentPlayerKey: () => currentPlayerKey,
        getIsDirty: () => isDirty,
        getWorldPath: () => worldPath,
    },
    helpers: { showToast },
    actions: {
        onPlayerView: () => {
            switchDashTab("dashStats");
            renderEffectsList();
            loadAbilitiesUI();
        },
        onMountsView: renderMountsPanel,
        onSaveView: renderSaveWorkflowPanel,
        onToolsView: () => {
            switchDashTab("dashDiagnostics");
            renderStatusCenter();
            renderIconManager();
            renderDataSourcePanels();
        },
    },
});
const responsivePanelController = workflowShell.responsivePanelController;
function setWorkflowView(view, options = {}) { return workflowShell.setWorkflowView(view, options); }
function updateAppMode() { return workflowShell.updateAppMode(); }

const statsFormController = window.MCBEEffectsLogic.createConfiguredStatsFormController({
    doc: document,
    getPlayerStats: () => playerStats,
});
const touchedStatsFields = statsFormController.touchedFields;
function statsFormElements() { return statsFormController.elements(); }
function renderStatsForm() { return statsFormController.render(); }
statsFormController.wireTouchedTracking();

// Dashboard state
let lastRuntimeDiagnostics = null;

let inventoryGridController = null;

function itemRequiresOriginalNbt(item) {
    return window.MCBEInventoryState.itemRequiresOriginalNbt(item);
}
const inventoryOriginController = window.MCBEInventoryState.createInventoryOriginController({
    getWorldPath: () => worldPath,
    getCurrentPlayerKey: () => currentPlayerKey,
    getInventory: () => inventory,
    getEnderChestInventory: () => enderChestInventory,
    getProtectedKnownSlots: () => protectedKnownSlots,
    setProtectedKnownSlots: value => { protectedKnownSlots = value; },
});
function ensureItemOrigin(item, containerName = "inventory") { return inventoryOriginController.ensureItemOrigin(item, containerName); }
function annotateItemOrigins(items, playerKey, containerName) { return inventoryOriginController.annotateItemOrigins(items, playerKey, containerName); }
function updateProtectedKnownSlotsFromMeta(meta) { return inventoryOriginController.updateProtectedKnownSlotsFromMeta(meta); }
function isProtectedKnownSlot(slotId, containerName) { return inventoryOriginController.isProtectedKnownSlot(slotId, containerName); }
function normalizeOriginsToCurrentSavedState(itemSourceDigests = null) {
    return inventoryOriginController.normalizeOriginsToCurrentSavedState(itemSourceDigests);
}
function getInventoryGridController() {
    if (!inventoryGridController) {
        inventoryGridController = window.MCBEInventoryRendering.createConfiguredInventoryGridController({
            doc: document,
            itemCatalog,
            state: {
                getInventory: () => inventory,
                getEnderChestInventory: () => enderChestInventory,
                getSelectedSlots: () => selectedSlots,
                getSelectedEnderSlot: () => selectedEnderSlot,
                setSelectedSlots: value => { selectedSlots = value; },
                setSelectedEnderSlot: value => { selectedEnderSlot = value; },
                getGridFilter: () => gridFilter,
                setGridFilter: value => { gridFilter = value; },
                getWorldPath: () => worldPath,
            },
            renderer: {
                buildSlotTooltipLines,
                buildSlotTooltipEntries,
                slotAreaLabel,
                slotDisplayName,
            },
            helpers: {
                getInventoryViewPreferences,
                itemRequiresOriginalNbt,
                isProtectedKnownSlot,
                hideSlotInspector,
                showProtectedSlotMessage,
                loadSingleSlotEditor,
                renderEffectsList,
                loadAbilitiesUI,
                updateUndoButtons,
                renderPlayerInventorySummary,
                itemIsVisiblePresent,
                ensureItemOrigin,
                pushUndo,
                recordAction,
                setDirty,
                guardEditingAction,
            },
        });
    }
    return inventoryGridController;
}
function buildGrids() { return getInventoryGridController().buildGrids(); }
function updateGridVisuals() { return getInventoryGridController().updateGridVisuals(); }
function handleSlotClick(e, slotId) { return getInventoryGridController().handleSlotClick(e, slotId); }
function handleEnderSlotClick(e, slotId) { return getInventoryGridController().handleEnderSlotClick(e, slotId); }
function clearSelection() { return getInventoryGridController().clearSelection(); }
function currentSelectionState() { return getInventoryGridController().currentSelectionState(); }
function updateSelectionUI() { return getInventoryGridController().updateSelectionUI(); }

const statusSessionController = window.MCBESessionLog.createInventoryStatusSessionController({
    doc: document,
    appConfig,
    statusNoticeStore,
    maxSessionLog: MAX_SESSION_LOG,
    getIsDirty: () => isDirty,
    getWorldPath: () => worldPath,
    getWorldName: () => worldNameEl?.textContent || "",
    getCurrentPlayer: () => currentPlayer,
    getCurrentPlayerLabel: currentPlayerLabel,
    renderUndoRedoPanel,
    renderWorldAnalysis,
    copyTextToClipboard,
    showToast,
});
function logStatus(msg, type = "", options = {}) {
    return statusSessionController.logStatus(msg, type, options);
}
function clearStatus(key) {
    return statusSessionController.clearStatus(key);
}
function updateHeaderStatusStack() {
    return statusSessionController.updateHeaderStatusStack();
}
function recordAction(message, type = "edit") {
    return statusSessionController.recordAction(message, type);
}
statusSessionController.wire({ getWorldAnalysisText: () => getAnalysisLogic().worldAnalysisText() });

let analysisLogic = null;

function getAnalysisLogic() {
    if (!analysisLogic) {
        analysisLogic = window.MCBEAnalysisLogic.createAnalysisLogic({
            appConfig,
            currentPlayerLabel,
            firstEmptyWritableSlot,
            getCurrentCompatibility: () => currentCompatibility,
            getEnderChestInventory: () => enderChestInventory,
            getHasEnderChest: () => hasEnderChest,
            getHiddenUnknownSlots: () => hiddenUnknownSlots,
            getInventory: () => inventory,
            getPlayers: () => players,
            getProtectedKnownSlots: () => protectedKnownSlots,
            getProtectedNbt: () => protectedNbt,
            getSelectedWorld: () => selectedWorld,
            getWorldName: () => worldNameEl?.textContent || "",
            getWorldPath: () => worldPath,
            inventorySlotCount: INVENTORY_SLOT_COUNT,
            enderChestSlotCount: ENDER_CHEST_SLOT_COUNT,
            isKnownItemId: itemCatalog.isKnownItemId,
            itemHasRepairableDamage,
            itemIsVisiblePresent,
            maxDamage: () => maxDamage,
            protectedAbilityFields,
            protectedStatFields,
            getCreateRequiresConfirmation: () => ({
                inventory: inventoryCreateRequiresConfirmation,
                enderChest: enderChestCreateRequiresConfirmation,
            }),
        });
    }
    return analysisLogic;
}
const worldAnalysisController = window.MCBEWorldAnalysisView.createInventoryWorldAnalysisController({
    doc: document,
    getWorldPath: () => worldPath,
    getCurrentPlayer: () => currentPlayer,
    buildAnalysis: () => getAnalysisLogic().buildWorldAnalysis(),
    inventorySlotCount: INVENTORY_SLOT_COUNT,
    enderChestSlotCount: ENDER_CHEST_SLOT_COUNT,
});
function renderWorldAnalysis() { return worldAnalysisController.render(); }
function getInventoryViewPreferences() {
    if (!inventoryViewPreferences) {
        inventoryViewPreferences = window.MCBEInventoryViewPreferences.createConfiguredInventoryViewPreferences({
            doc: document,
            storage: localStorage,
            slotNumbersKey: SLOT_NUMBERS_KEY,
            enderCollapsedKey: ENDER_COLLAPSED_KEY,
        });
    }
    return inventoryViewPreferences;
}
const playerInventorySummaryController = window.MCBEPlayerInventorySummaryView.createInventoryPlayerInventorySummaryController({
    doc: document,
    getWorldPath: () => worldPath,
    getCurrentPlayer: () => currentPlayer,
    getPlayerLabel: currentPlayerLabel,
    buildSummary: () => getAnalysisLogic().buildInventorySummary(),
    setLastSummary: value => { lastInventorySummary = value; },
});
function renderPlayerInventorySummary() { return playerInventorySummaryController.render(); }

// The controller is assigned after all update dependencies exist. Status
// callbacks may safely render it once application startup begins.
let firstRunSetupController = null;

const dataSourceController = window.MCBEDataSourceView.createInventoryDataSourceController({
    doc: document,
    appConfig,
    parseJsonResponse,
    getItemDbStatus: () => itemDbStatus,
    setItemDbStatus: value => { itemDbStatus = value; },
    getIconSourceSummary: () => iconSourceSummary,
    getUnknownItemCount: () => getAnalysisLogic().currentUnknownItemCount(),
    hasCurrentPlayer: () => Boolean(currentPlayer),
    // Also open the tools workspace: the first-run banner sits on the landing
    // screen, where switching the dashboard tab alone would change nothing visible.
    openItemDbStatus: () => {
        setWorkflowView("tools", { user: true });
        switchDashTab("dashUpdate");
    },
    renderStatusCenter,
    onItemDbStatusApplied: () => firstRunSetupController?.render(),
    logStatus,
});

function renderDataSourcePanels() {
    const rendered = dataSourceController.render();
    // Icon-state changes use this shared renderer. Item-DB mutations use the
    // controller callback above, so every status consumer is invalidated once.
    firstRunSetupController?.render();
    return rendered;
}

async function loadItemDbStatus() {
    return dataSourceController.loadItemDbStatus();
}

const statusCenterController = window.MCBEStatusCenterView.createInventoryStatusCenterController({
    doc: document,
    getRuntimeDiagnostics: () => lastRuntimeDiagnostics || {},
    getAppConfig: () => appConfig,
    getCurrentCompatibility: () => currentCompatibility,
    getIconSummary: () => iconSourceSummary,
    getItemDbStatus: () => itemDbStatus,
    getLastWorldScan: () => lastWorldScan,
    getIsDirty: () => isDirty,
    getWorldPath: () => worldPath,
    getSelectedWorldPath: () => selectedWorld?.path,
    getCurrentPlayerLabel: () => currentPlayerLabel(),
    hasCurrentPlayer: () => Boolean(currentPlayer),
    getCompatibilitySummary: () => getAnalysisLogic().compatibilitySummaryText(),
});

function renderStatusCenter() {
    return statusCenterController.render();
}

let playerToolsController = null;

function getPlayerToolsController() {
    if (!playerToolsController) {
        playerToolsController = window.MCBEPlayerTools.createInventoryPlayerToolsController({
            doc: document,
            getPlayers: () => players,
            getCurrentPlayerKey: () => currentPlayerKey,
            getWorldPath: () => worldPath,
            getInventory: () => inventory,
            getEnderChestInventory: () => enderChestInventory,
            getPlayerStats: () => playerStats,
            setInventory: next => { inventory = next; },
            setEnderChestState: next => {
                enderChestInventory = next.inventory || {};
                hasEnderChest = Boolean(next.hasEnderChest);
                enderChestCreateRequiresConfirmation = Boolean(next.createRequiresConfirmation);
            },
            setPlayerStats: next => { playerStats = next; },
            currentPlayerLabel,
            withCsrf: () => withCsrf(),
            parseJsonResponse,
            buildErrorMessage,
            itemIsVisiblePresent,
            itemHasRepairableDamage,
            annotateItemOrigins,
            pushUndo,
            renderStatsForm,
            clearSelection,
            buildGrids,
            getInventoryViewPreferences,
            updateGridVisuals,
            renderPlayerInventorySummary,
            getIsDirty: () => isDirty,
            writeBlocked: () => writeBlocked(),
            guardEditingAction,
            getServerGuardEpoch: () => currentServerGuardEpoch,
            getServerGuardToken: () => currentServerGuardToken,
            getWorldPresenceSessionId,
            confirmPresenceConflict,
            beginServerStatusRequest: () => beginServerStatusRequest(),
            renderWriteGate: (writeGate, options) => renderServerStatus(
                { server_status: writeGate.server_status, write_gate: writeGate },
                { ...options, authoritativeBlock: true },
            ),
            refreshAfterStateTransfer: async () => {
                const playerToReload = currentPlayerKey;
                const refreshed = await loadPlayersList(false);
                if (refreshed && playerToReload) {
                    await loadPlayer(playerToReload, true, { showLoadingOverlay: false });
                }
            },
            setDirty,
            recordAction,
            showToast,
            showConfirmDialog,
            showLoading,
            hideLoading,
        });
    }
    return playerToolsController;
}
function renderPlayerToolOptions() { return getPlayerToolsController().renderOptions(); }

getPlayerToolsController().wire();

const worldStatusController = window.MCBEWorldStatusView.createInventoryWorldStatusController({
    doc: document,
    appConfig,
    buildErrorMessage,
    getSelectedWorld: () => selectedWorld,
    setSelectedWorld: value => { selectedWorld = value; },
    getWorldPath: () => worldPath,
    getIsDirty: () => isDirty,
    getCurrentPlayerKey: () => currentPlayerKey,
    getLastRenderedWorlds: () => lastRenderedWorlds,
    buildChangeSummary,
    effectiveWriteGate: () => effectiveWriteGate(),
    writeBlocked: () => writeBlocked(),
    currentPlayerLabel,
    renderWorldCards,
    showConfirmDialog,
});
const {
    clearLoadError,
    confirmLocalWorldAccessBeforeOpen,
    renderLoadError,
    updateAutoPathHint,
    updateDirtyBanner,
    updateSelectedWorld,
} = worldStatusController;

function workflowStateContext() {
    return {
        activeWorkflowView,
        currentPlayer,
        currentPlayerKey,
        inventoryVisible: Boolean(inventoryContainer && inventoryContainer.style.display !== "none"),
        isDirty,
        worldPath,
    };
}

const sectionChanged = window.MCBEStateSnapshot.sectionChanged;

const saveWorkflowController = window.MCBESaveWorkflowView.createInventorySaveWorkflowController({
    doc: document,
    getCleanSnapshot: () => undoRedoAppController.getCleanSnapshot(),
    getPendingMounts: () => getMountController().getPendingMounts(),
    takeSnapshot,
    sectionChanged,
    workflowStateContext,
    buildChangeSummary,
    buildChangeSummaryText,
    validateInventoryState,
    currentPlayerLabel,
    changeKindLabel,
    collectEditorDecisionDetails,
    getIsDirty: () => isDirty,
    writeBlocked: () => writeBlocked(),
    copyTextToClipboard,
    saveCurrentPlayer,
});
function renderSaveWorkflowPanel() { return saveWorkflowController.render(); }
let saveAppController = null;

function getSaveAppController() {
    if (!saveAppController) saveAppController = createConfiguredSaveAppController();
    return saveAppController;
}
function buildChangeSummary(options = {}) { return getSaveAppController().buildChangeSummary(options); }
function changeKindLabel(kind) { return getSaveAppController().changeKindLabel(kind); }
function collectEditorDecisionDetails(summary = buildChangeSummary({ limit: 100, includeSections: true }), validation = validateInventoryState({ limit: 100 })) {
    return getSaveAppController().collectEditorDecisionDetails(summary, validation);
}
function decisionLogText(summary = buildChangeSummary({ limit: 100, includeSections: true }), validation = validateInventoryState({ limit: 100 })) {
    return getSaveAppController().decisionLogText(summary, validation);
}
function buildChangeSummaryText(summary = buildChangeSummary({ limit: 100, includeSections: true }), validation = validateInventoryState({ limit: 100 })) {
    return getSaveAppController().buildChangeSummaryText(summary, validation);
}
function validateInventoryState(options = {}) { return getSaveAppController().validateInventoryState(options); }
const saveReviewController = window.MCBESaveReviewView.createInventorySaveReviewController({
    doc: document,
    getPlayerLabel: currentPlayerLabel,
    getWorldLabel: () => worldNameEl?.textContent || selectedWorld?.name || t("Geladene Welt"),
    changeKindLabel,
    collectEditorDecisionDetails,
    buildChangeSummaryText,
    decisionLogText,
    copyTextToClipboard,
    showToast,
});
function openSaveReview(summary, validation = validateInventoryState({ limit: 12 })) {
    return saveReviewController.open(summary, validation);
}

const clipboardFeedbackController = window.MCBEUiFeedback.createInventoryClipboardFeedbackController({
    doc: document,
    clipboard: navigator.clipboard,
    logStatus,
    clearStatus,
    showToastFn: showToast,
});
function copyTextToClipboard(text, successMessage = t("In die Zwischenablage kopiert.")) {
    return clipboardFeedbackController.copyTextToClipboard(text, successMessage);
}
clipboardFeedbackController.wire();

function renderWorldCards(worlds) {
    return worldBrowserController.renderWorldCards(worlds);
}
function buildPlayersDiagnosticsText() {
    return worldBrowserController.buildPlayersDiagnosticsText();
}

const writeGateController = window.MCBEWriteStatusView.createInventoryWriteGateController({
    doc: document,
    appConfig,
    parseJsonResponse,
    getCurrentWriteGate: () => currentWriteGate,
    setCurrentWriteGate: value => { currentWriteGate = value; },
    getCurrentServerGuardEpoch: () => currentServerGuardEpoch,
    setCurrentServerGuardEpoch: value => { currentServerGuardEpoch = value; },
    getCurrentServerGuardToken: () => currentServerGuardToken,
    setCurrentServerGuardToken: value => { currentServerGuardToken = value; },
    getCurrentServerStatusRevision: () => currentServerStatusRevision,
    setCurrentServerStatusRevision: value => { currentServerStatusRevision = value; },
    getCurrentPlayerServerGuardEpoch: () => currentPlayerServerGuardEpoch,
    getCurrentPlayerServerGuardToken: () => currentPlayerServerGuardToken,
    getCurrentPlayerStaleReason: () => currentPlayerStaleReason,
    setCurrentPlayerStaleReason: value => { currentPlayerStaleReason = value; },
    getCurrentPlayerKey: () => currentPlayerKey,
    getIsDirty: () => isDirty,
    buildChangeSummary,
    updateImportControls: () => updateImportControls(),
    updatePlayerTransferControls: () => getPlayerToolsController().updateStateTransferWriteControl(),
    renderSaveWorkflowPanel,
    updateDirtyBanner,
    updateHeaderStatusStack,
    renderStatusCenter,
    logStatus,
    clearStatus,
    showToast,
    staleReason: PLAYER_STALE_SERVER_REASON,
});
const normalizeServerGuardEpoch = window.MCBEWriteStatusView.normalizeServerGuardEpoch;
const {
    beginServerStatusRequest,
    clearLoadedPlayerStaleState,
    effectiveWriteGate,
    permissions,
    writeBlocked,
} = writeGateController;
function guardEditingAction() { return writeGateController.guardEditingAction(); }
function guardWorldWriteAction() { return writeGateController.guardWorldWriteAction(); }

const playerImportPreviewController = window.MCBEPlayerTransferLogic.createInventoryPlayerImportPreviewController({
    doc: document,
    withCsrf,
    parseJsonResponse,
    getWorldPath: () => worldPath,
    getCurrentPlayer: () => currentPlayer,
    getCurrentPlayerLabel: currentPlayerLabel,
    getCurrentImportPreview: () => currentImportPreview,
    setCurrentImportPreview: value => { currentImportPreview = value; },
    writeBlocked,
    appConfig,
});
const {
    refreshPlayerImportPreview,
    schedulePlayerImportPreview,
    updateImportControls,
    updatePlayerExportFolderControl,
} = playerImportPreviewController;
const {
    refreshServerStatus,
    renderServerStatus,
    updateWriteControls,
} = writeGateController;

// Check/Uncheck dirty state
const dirtyStateController = window.MCBEWorkflowState.createDirtyStateController({
    getIsDirty: () => isDirty,
    setIsDirty: value => { isDirty = value; },
    getWorldPath: () => worldPath,
    effectiveWriteGate,
    logStatus,
    clearStatus,
    transientDirtyNoticeCategory: TRANSIENT_DIRTY_NOTICE_CATEGORY,
    scheduleWorldPresenceUpdate,
    updateWriteControls,
    renderPlayerInventorySummary,
    renderStatusCenter,
    renderSaveWorkflowPanel,
    updateAppMode,
});
function setDirty(dirty) { return dirtyStateController.setDirty(dirty); }

function currentPlayerLabel() {
    return currentPlayer ? currentPlayer.label : t("Spieler");
}

const worldPresenceController = window.MCBEPresenceView.createConfiguredWorldPresenceController({
    win: window,
    doc: document,
    sessionKey: WORLD_PRESENCE_SESSION_KEY,
    intervalMs: WORLD_PRESENCE_INTERVAL_MS,
    api: apiClient,
    state: {
        getWorldPath: () => worldPath,
        getCurrentPlayerKey: () => currentPlayerKey,
        getCurrentPlayerLabel: currentPlayerLabel,
        getIsDirty: () => isDirty,
    },
    helpers: { logStatus, showToast, showConfirmDialog },
});
function getWorldPresenceController() { return worldPresenceController; }
function getWorldPresenceSessionId() { return worldPresenceController.sessionId(); }
function updateWorldPresence(options = {}) { return worldPresenceController.update(options); }
function confirmPresenceConflict(data) { return worldPresenceController.confirmConflict(data); }
function scheduleWorldPresenceUpdate() { return worldPresenceController.scheduleUpdate(); }
const slotInspectorController = window.MCBENbtInspector.createInventorySlotInspectorController({
    doc: document,
    getInventory: () => inventory,
    getEnderChestInventory: () => enderChestInventory,
    isProtectedKnownSlot,
    itemIsVisiblePresent,
    itemRequiresOriginalNbt,
    slotDisplayName,
    currentPlayerLabel,
    getCurrentPlayerKey: () => currentPlayerKey,
    getWorldPath: () => worldPath,
    getActiveWorkflowView: () => activeWorkflowView,
    setWorkflowView,
    showToast,
    copyTextToClipboard,
});
const {
    hide: hideSlotInspector,
    itemHasInspectableNbt,
    show: showSlotInspector,
    showProtectedMessage: showProtectedSlotMessage,
} = slotInspectorController;
slotInspectorController.wire();

let playerLoadApp = null;
const appStateBridge = window.MCBEAppStateBridge;
const PLAYER_LOAD_STATE_KEYS = [
    "worldPath",
    "selectedWorld",
    "isDirty",
    "players",
    "currentPlayerKey",
    "currentPlayer",
    "currentServerGuardEpoch",
    "currentServerGuardToken",
    "currentServerStatusRevision",
    "currentPlayerServerGuardEpoch",
    "currentPlayerServerGuardToken",
];

const assignAppStatePatch = appStateBridge.createPatchAssigner({
    worldPath: value => { worldPath = value; },
    inventory: value => { inventory = value; },
    enderChestInventory: value => { enderChestInventory = value; },
    hasEnderChest: value => { hasEnderChest = value; },
    inventoryCreateRequiresConfirmation: value => { inventoryCreateRequiresConfirmation = value; },
    enderChestCreateRequiresConfirmation: value => { enderChestCreateRequiresConfirmation = value; },
    effectsCreateRequiresConfirmation: value => { effectsCreateRequiresConfirmation = value; },
    abilitiesCreateRequiresConfirmation: value => { abilitiesCreateRequiresConfirmation = value; },
    effectsTouched: value => { effectsTouched = value; },
    abilitiesTouched: value => { abilitiesTouched = value; },
    selectedSlots: value => { selectedSlots = value; },
    selectedEnderSlot: value => { selectedEnderSlot = value; },
    itemsDb: value => { itemsDb = value; },
    compatItemAliases: value => { compatItemAliases = value || {}; },
    addableItems: value => { addableItems = value instanceof Set ? value : new Set(value || []); },
    blockOnlyItems: value => { blockOnlyItems = value instanceof Set ? value : new Set(value || []); },
    blockItems: value => { blockItems = value instanceof Set ? value : new Set(value || []); },
    itemAvailability: value => { itemAvailabilityCatalog.replace(value || {}); },
    enchDb: value => { enchDb = value; },
    enchantmentCompatibility: value => { enchantmentCompatibility = value; },
    itemComponents: value => {
        itemComponents = value && typeof value === "object" ? value : {};
        window.MCBEEquipmentRules?.setItemComponents?.(itemComponents);
    },
    stackLimits: value => { stackLimits = value; },
    maxDamage: value => { maxDamage = value; },
    isDirty: value => { isDirty = value; },
    players: value => { players = value; },
    currentPlayerKey: value => { currentPlayerKey = value; },
    currentPlayer: value => { currentPlayer = value; },
    currentPlayerRevision: value => { currentPlayerRevision = value; },
    currentServerGuardEpoch: value => { currentServerGuardEpoch = value; },
    currentServerGuardToken: value => { currentServerGuardToken = value; },
    currentServerStatusRevision: value => { currentServerStatusRevision = value; },
    currentPlayerServerGuardEpoch: value => { currentPlayerServerGuardEpoch = value; },
    currentPlayerServerGuardToken: value => { currentPlayerServerGuardToken = value; },
    playerStats: value => { playerStats = value; },
    playerEffects: value => { playerEffects = value; },
    playerAbilities: value => { playerAbilities = value; },
    effectsDb: value => { effectsDb = value; },
    hiddenUnknownSlots: value => { hiddenUnknownSlots = value; },
    protectedKnownSlots: value => { protectedKnownSlots = value; },
    protectedNbt: value => { protectedNbt = value; },
    currentCompatibility: value => { currentCompatibility = value; },
    lastPlayerExportDir: value => { lastPlayerExportDir = value; },
    gridFilter: value => { gridFilter = value; },
}, {
    onUnknownKey: appStateBridge.unknownPatchKeyLogger(console, "Unbekanntes App-State-Patch-Feld"),
});

function assignAppState(patch = {}) { return assignAppStatePatch(patch); }
function playerLoadState() {
    return appStateBridge.pickState({
        worldPath,
        selectedWorld,
        isDirty,
        players,
        currentPlayerKey,
        currentPlayer,
        currentServerGuardEpoch,
        currentServerGuardToken,
        currentServerStatusRevision,
        currentPlayerServerGuardEpoch,
        currentPlayerServerGuardToken,
    }, PLAYER_LOAD_STATE_KEYS);
}
function getPlayerLoadApp() {
    if (!playerLoadApp) {
        playerLoadApp = window.MCBEPlayerLoadApp.createInventoryPlayerLoadApp({
            doc: document,
            state: {
                getPlayerLoadState: playerLoadState,
                assignAppState,
            },
            api: { withCsrf, parseJsonResponse, buildErrorMessage },
            feedback: { showConfirmDialog, showToast, showLoading, hideLoading },
            actions: {
                logStatus,
                copyTextToClipboard,
                buildPlayersDiagnosticsText,
                renderLoadError,
                saveWorkspace,
                annotateItemOrigins,
                updateProtectedKnownSlotsFromMeta,
                normalizeServerGuardEpoch,
                beginServerStatusRequest,
                clearLoadedPlayerStaleState,
                markLoadedPlayerStale: writeGateController.markLoadedPlayerStale,
                renderServerStatus,
                updatePlayerExportFolderControl,
                updateImportControls,
                updateWriteControls,
                // Exporte lesen den geladenen Stand und bleiben bei einer
                // reinen Server-Schreibsperre verfügbar.
                exportBlocked: () => !permissions().canExport,
                scheduleWorldPresenceUpdate,
                renderPlayerToolOptions,
                renderStatusCenter,
                updateAppMode,
                updateWorldPresence,
                renderWorldAnalysis,
                setWorkflowView,
                getActiveWorkflowView: () => activeWorkflowView,
                loadLocalIconIndex,
                renderStatsForm,
                setStatsProtectionUI,
                buildGrids,
                getInventoryViewPreferences,
                updateGridVisuals,
                clearSelection,
                markCleanState,
                clearPendingMounts: () => getMountController().clearPendingMounts({ renderPanel: false }),
                renderPlayerInventorySummary,
                recordAction,
                getCurrentPlayerLabel: currentPlayerLabel,
                getAnalysisLogic,
                clearLoadError,
                confirmLocalWorldAccessBeforeOpen,
                loadBackupsList: (...args) => loadBackupsList(...args),
            },
            ui: {
                clearTouchedStatsFields: () => touchedStatsFields.clear(),
                resetUndoRedoForUnloadedPlayer: () => {
                    undoRedoAppController.resetForUnloadedPlayer();
                },
                clearGridSearch: () => { gridFilter = ""; if (gridSearch) gridSearch.value = ""; },
                clearRecentWorldSession: () => { try { sessionStorage.removeItem(SESSION_RECENT_WORLDS_KEY); } catch (_e) {} },
            },
            constants: { defaultMaxDamage: DEFAULT_MAX_DAMAGE, appConfig },
        });
    }
    return playerLoadApp;
}
function resetLoadedPlayerState(options = {}) { return getPlayerLoadApp().resetLoadedPlayerState(options); }
function renderPlayersList() { return getPlayerLoadApp().renderPlayersList(); }
function loadPlayersList(selectFirst = true) { return getPlayerLoadApp().loadPlayersList(selectFirst); }
function loadPlayer(playerKey, skipDirtyCheck = false, options = {}) { return getPlayerLoadApp().loadPlayer(playerKey, skipDirtyCheck, options); }
function loadWorldFromInput() { return getPlayerLoadApp().loadWorldFromInput(); }
function renderRecentWorlds() { return getPlayerLoadApp().renderRecentWorlds(); }
getPlayerLoadApp().wire();

const iconSourcesController = window.MCBEIconSourcesController.createInventoryIconSourcesController({
    doc: document,
    api: apiClient,
    appConfig,
    permissions,
    itemCatalog,
    itemLabel: detailItemLabel,
    getWorldPath: () => worldPath,
    getSelectedWorldPath: () => selectedWorld?.path || "",
    loadWorkspace: () => getWorkspaceController().loadWorkspace(),
    saveWorkspace,
    isInventoryOpen: () => Boolean(currentPlayerKey),
    copyTextToClipboard,
    showToast,
    showConfirmDialog,
    showLoading,
    hideLoading,
    logStatus,
    appendUpdateOutput,
    onIconData({ icons, summary }) {
        itemIconIndex = icons || {};
        iconSourceSummary = summary || { count: 0, roots: [], warnings: [] };
    },
    onIconStatusUnavailable() {
        iconSourceSummary = { status: "unavailable", count: 0, roots: [], warnings: [] };
        renderDataSourcePanels();
        renderStatusCenter();
    },
    onIconDataApplied() {
        renderDataSourcePanels();
        renderStatusCenter();
        updateGridVisuals();
        updateDetailPreview();
    },
});

function loadLocalIconIndex(options) {
    return iconSourcesController.loadLocalIconIndex(options);
}
function renderIconManager(data = null) {
    return iconSourcesController.renderIconManager(data);
}

// Undo/Redo system
const undoRedoAppController = window.MCBEUndoRedoController.createInventoryUndoRedoAppController({
    doc: document,
    takeSnapshot: stateSnapshot.takeSnapshot,
    snapshotHash: window.MCBEStateSnapshot.snapshotHash,
    cloneJson: window.MCBEStateSnapshot.cloneJson,
    maxUndo: MAX_UNDO,
    getPlayerStats: () => playerStats,
    setInventory: value => { inventory = value; },
    setEnderChestInventory: value => { enderChestInventory = value; },
    setPlayerStats: value => { playerStats = value; },
    setPlayerEffects: value => { playerEffects = value; },
    setPlayerAbilities: value => { playerAbilities = value; },
    setPendingMounts: value => getMountController().setPendingMounts(value, { notify: false }),
    touchedStatsFields,
    onSnapshotApplied: () => {
        renderStatsForm();
        renderEffectsList();
        loadAbilitiesUI();
        setStatsProtectionUI();
        renderPlayerInventorySummary();
        renderWorldAnalysis();
    },
    onCleanMarked: () => {
        effectsTouched = false;
        abilitiesTouched = false;
    },
    updateGridVisuals,
    updateSelectionUI,
    setDirty,
    recordAction,
    editingBlocked: () => writeGateController.editingBlocked(),
    getEditingBlockedReason: () => writeGateController.effectiveWriteGate()?.reason || "",
});
function markCleanState() { return undoRedoAppController.markCleanState(); }
function pushUndo(label = t("Änderung")) { return undoRedoAppController.pushUndo(label); }
function undo() { return undoRedoAppController.undo(); }
function redo() { return undoRedoAppController.redo(); }
function updateUndoButtons() { return undoRedoAppController.updateUndoButtons(); }
function renderUndoRedoPanel() { return undoRedoAppController.renderUndoRedoPanel(); }
undoRedoAppController.wire();

const inventoryClipboardController = window.MCBEInventoryClipboardLogic.createConfiguredInventoryClipboardController({
    doc: document,
    win: window,
    state: {
        getInventory: () => inventory,
        getEnderChestInventory: () => enderChestInventory,
        getCurrentPlayerKey: () => currentPlayerKey,
        getWorldPath: () => worldPath,
        getActiveWorkflowView: () => activeWorkflowView,
    },
    selection: { currentSelectionState },
    slotHandlers: { handleSlotClick, handleEnderSlotClick },
    helpers: { isProtectedKnownSlot, showProtectedSlotMessage, pushUndo, updateGridVisuals, setDirty, showToast, recordAction, guardEditingAction },
    renderer: { slotDisplayName },
});
inventoryClipboardController.bindContextMenu();

// Keyboard shortcuts
window.MCBEWorkflowState.createConfiguredAppKeyboardController({
    doc: document,
    inventoryClipboardController,
    actions: { undo, redo },
    state: { getActiveWorkflowView: () => activeWorkflowView },
    selection: {
        currentSelectionState,
        hasSelection: window.MCBESelectionState.hasSelection,
        clearSelection,
    },
    helpers: {
        isEditableTextTarget: window.MCBEInventoryClipboardLogic.isEditableTextTarget,
        showToast,
    },
}).wire();

const worldBrowserController = window.MCBEWorldBrowser.createInventoryWorldBrowserController({
    doc: document,
    parseJsonResponse,
    withCsrf,
    appConfig,
    loadWorldFromInput,
    getLastWorldScan: () => lastWorldScan,
    getLastRenderedWorlds: () => lastRenderedWorlds,
    setLastRenderedWorlds: value => { lastRenderedWorlds = Array.isArray(value) ? value : []; },
    getSelectedWorld: () => selectedWorld,
    getWorldPath: () => worldPath,
    getWorldPathInputValue: () => worldPathEl?.value || "",
    getIsDirty: () => isDirty,
    getPlayers: () => players,
    getWorldName: () => worldNameEl?.innerText || "",
    setLastWorldScan: data => { lastWorldScan = data; },
    updateSelectedWorld,
    clearLoadError,
    updateAutoPathHint,
    buildErrorMessage,
    logStatus,
    showToast,
    copyTextToClipboard,
});
const scanWorlds = worldBrowserController.scanWorlds;
worldBrowserController.wire();

window.MCBESaveWorkflowView.createInventoryDirtyActionsController({
    doc: document,
    getCurrentPlayerKey: () => currentPlayerKey,
    saveCurrentPlayer,
    setWorkflowView,
    loadPlayer,
    showConfirmDialog,
    showToast,
}).wire();

// Scan path settings
const scanPathsController = window.MCBEScanPathsController.createInventoryScanPathsController({
    doc: document,
    api: apiClient,
    updateAutoPathHint,
    scanWorlds,
});
scanPathsController.wire();

// Save World
function createConfiguredSaveAppController() {
    return window.MCBESaveController.createConfiguredSaveAppController({
        api: { fetchFn: fetch, parseJsonResponse, withCsrf },
        constants: { maxBedrockStackCount: MAX_BEDROCK_STACK_COUNT },
        itemCatalog,
        state: {
            getAbilitiesCreateRequiresConfirmation: () => abilitiesCreateRequiresConfirmation,
            getAbilitiesTouched: () => abilitiesTouched,
            getCleanSnapshot: () => undoRedoAppController.getCleanSnapshot(),
            getCurrentPlayer: () => currentPlayer,
            getCurrentPlayerKey: () => currentPlayerKey,
            getCurrentPlayerRevision: () => currentPlayerRevision,
            getCurrentPlayerServerGuardEpoch: () => currentPlayerServerGuardEpoch,
            getCurrentPlayerServerGuardToken: () => currentPlayerServerGuardToken,
            getCurrentWriteGate: () => effectiveWriteGate(),
            getEnchantmentsDb: () => enchDb,
            getEffectsCreateRequiresConfirmation: () => effectsCreateRequiresConfirmation,
            getEffectsTouched: () => effectsTouched,
            getEnderChestCreateRequiresConfirmation: () => enderChestCreateRequiresConfirmation,
            getEnderChestInventory: () => enderChestInventory,
            getHasEnderChest: () => hasEnderChest,
            getHiddenUnknownSlots: () => hiddenUnknownSlots,
            getInventory: () => inventory,
            getPendingMounts: () => getMountController().getPendingMounts(),
            getInventoryCreateRequiresConfirmation: () => inventoryCreateRequiresConfirmation,
            getIsDirty: () => isDirty,
            getPlayerAbilities: () => playerAbilities,
            getPlayerEffects: () => playerEffects,
            getPlayerStats: () => playerStats,
            getProtectedKnownSlots: () => protectedKnownSlots,
            getProtectedNbt: () => protectedNbt,
            getWorldPath: () => worldPath,
            getWorldPresenceSessionId,
            setCurrentPlayerRevision: value => { currentPlayerRevision = value || currentPlayerRevision; },
            setPlayerAbilities: value => { playerAbilities = value; },
        },
        ui: {
            saveButton: btnSave,
            saveReviewConfirmButton: btnSaveReviewConfirm,
            getWorldLabel: () => worldNameEl?.textContent || selectedWorld?.name || t("Geladene Welt"),
        },
        helpers: {
            assignAppState,
            beginServerStatusRequest,
            buildChangeSummary,
            collectAbilitiesFromUI,
            confirmPresenceConflict,
            currentPlayerLabel,
            hideLoading,
            itemDisplayName,
            itemIsVisiblePresent,
            itemRequiresOriginalNbt,
            loadBackupsList: () => loadBackupsList(),
            logStatus,
            markReloadRequired: reason => { currentPlayerStaleReason = reason; },
            markCleanState,
            normalizeOriginsToCurrentSavedState,
            openSaveReview,
            recordAction,
            removeProtectedStatsFromPayload,
            renderServerStatus,
            sectionChanged,
            showConfirmDialog,
            showLoading,
            showToast,
            slotDisplayName,
            syncEffectsFromUI,
            takeSnapshot: () => takeSnapshot(),
            updateWorldPresence,
            updateWriteControls,
            validateInventoryState,
            writeBlocked,
            guardWorldWriteAction,
            finalizePendingMounts: (results, options) => getMountController().finalizePendingMounts(results, options),
        },
    });
}

async function saveCurrentPlayer(options = {}) {
    return getSaveAppController().saveCurrentPlayer(options);
}
if (btnSave) btnSave.addEventListener("click", () => saveCurrentPlayer({ skipReview: false }));
saveWorkflowController.wire();

let gridFilter = "";
getInventoryGridController().wireControls();

// Single Slot Editor logic
const slotDetailController = window.MCBESlotDetailLogic.createInventorySlotDetailController({
    doc: document,
    itemCatalog,
    constants: {
        maxDisplayName: MAX_DISPLAY_NAME,
        maxLoreLines: MAX_LORE_LINES,
        maxLoreLineLength: MAX_LORE_LINE_LEN,
        inventorySlotCount: INVENTORY_SLOT_COUNT,
        enderChestSlotCount: ENDER_CHEST_SLOT_COUNT,
    },
    state: {
        getInventory: () => inventory,
        getEnderChestInventory: () => enderChestInventory,
        getCurrentSelectionState: currentSelectionState,
        getCurrentPlayerKey: () => currentPlayerKey,
        getWorldPath: () => worldPath,
        getEnchantmentsDb: () => enchDb,
    },
    helpers: {
        isProtectedKnownSlot,
        itemRequiresOriginalNbt,
        itemHasInspectableNbt,
        itemHasRepairableDamage,
        showProtectedSlotMessage,
        showSlotInspector,
        switchTab,
        slotDisplayName,
        detailItemLabel,
        getItemAvailability: itemAvailabilityCatalog.badgeFor,
        pushUndo,
        updateGridVisuals,
        setDirty,
        editingBlocked: () => writeGateController.editingBlocked(),
        getEditingBlockedReason: () => writeGateController.effectiveWriteGate()?.reason || "",
        syncEditControls: updateWriteControls,
        logStatus,
        recordAction,
        showToast,
    },
});
slotDetailController.wire();

function updateDetailPreview() {
    return slotDetailController.updateDetailPreview();
}
function loadSingleSlotEditor(slotId, isEnderChest = false) {
    return slotDetailController.loadSingleSlotEditor(slotId, isEnderChest);
}
function firstEmptyWritableSlot(containerName) {
    return slotDetailController.firstEmptyWritableSlot(containerName);
}
function applyCurrentSingleSlot() {
    return slotDetailController.applyCurrentSingleSlot();
}
function resetDetailFormForNewItem(itemName) {
    return slotDetailController.resetDetailFormForNewItem(itemName);
}
function selectDetailItemVariant(item) {
    return slotDetailController.selectDetailItemVariant(item);
}

const bulkEditController = window.MCBEBulkEditLogic.createInventoryBulkEditController({
    doc: document,
    itemCatalog,
    maxBedrockStackCount: MAX_BEDROCK_STACK_COUNT,
    state: {
        getSelectedSlots: () => selectedSlots,
        getSelectedEnderSlot: () => selectedEnderSlot,
        getInventory: () => inventory,
        getEnderChestInventory: () => enderChestInventory,
        getCurrentSelectionState: currentSelectionState,
        getMaxDamage: () => maxDamage,
    },
    helpers: {
        isProtectedKnownSlot,
        itemIsVisiblePresent,
        pushUndo,
        updateGridVisuals,
        setDirty,
        renderWorldAnalysis,
        logStatus,
        recordAction,
        showToast,
        clearSelection,
        guardEditingAction,
    },
});
bulkEditController.wire();

// Tab switcher (Slot-Editor)
const slotTabController = window.MCBEWorkflowState.createConfiguredSlotTabController({ doc: document });
function switchTab(tabId) { return slotTabController.switchTo(tabId); }
slotTabController.wire();

// --- Dashboard Specific Scripting ---

const auditEventsController = window.MCBEDiagnosticsView.createInventoryAuditEventsController({
    doc: document,
    parseJsonResponse,
    buildErrorMessage,
});
const loadAuditEvents = auditEventsController.load;
auditEventsController.wire();

// Tab switcher (Dashboard)
const dashboardTabController = window.MCBEWorkflowState.createConfiguredDashboardTabController({
    doc: document,
    loadAuditEvents,
    loadRuntimeDiagnostics: (...args) => loadRuntimeDiagnostics(...args),
    loadBackupsList: (...args) => loadBackupsList(...args),
});
function switchDashTab(tabId) { return dashboardTabController.switchTo(tabId); }
dashboardTabController.wire();

// Player stats, effects and abilities controller
const effectsAbilitiesController = window.MCBEEffectsLogic.createEffectsAbilitiesController({
    doc: document,
    statsFormElements,
    getTouchedStatsFields: () => touchedStatsFields,
    getProtectedNbt: () => protectedNbt,
    getPlayerStats: () => playerStats,
    setPlayerStats: value => { playerStats = value; },
    getPlayerEffects: () => playerEffects,
    getPlayerAbilities: () => playerAbilities,
    setPlayerAbilities: value => { playerAbilities = value; },
    getEffectsDb: () => effectsDb,
    getEffectsTouched: () => effectsTouched,
    setEffectsTouched: value => { effectsTouched = value; },
    setAbilitiesTouched: value => { abilitiesTouched = value; },
    getShouldSyncAbilitiesFromUIForSave: () => getSaveAppController().shouldSyncAbilitiesFromUIForSave(),
    editingBlocked: () => writeGateController.editingBlocked(),
    pushUndo,
    setDirty,
    logStatus,
    showToast,
    recordAction,
});
effectsAbilitiesController.wire();

function renderEffectsList() {
    return effectsAbilitiesController.renderEffectsList();
}
function protectedAbilityFields() {
    return effectsAbilitiesController.protectedAbilityFields();
}
function protectedStatFields() {
    return effectsAbilitiesController.protectedStatFields();
}
function setStatsProtectionUI() {
    return effectsAbilitiesController.setStatsProtectionUI();
}
function removeProtectedStatsFromPayload(statsPayload) {
    return effectsAbilitiesController.removeProtectedStatsFromPayload(statsPayload);
}
function loadAbilitiesUI() {
    return effectsAbilitiesController.loadAbilitiesUI();
}
function collectAbilitiesFromUI() {
    return effectsAbilitiesController.collectAbilitiesFromUI();
}
function syncEffectsFromUI() {
    return effectsAbilitiesController.syncEffectsFromUI();
}

// --- End Effects & Abilities ---

const diagnosticsController = window.MCBEDiagnosticsView.createInventoryDiagnosticsController({
    doc: document,
    appConfig,
    api: apiClient,
    copyTextToClipboard,
    getCurrentCompatibility: () => currentCompatibility,
    getIconSourceSummary: () => iconSourceSummary,
    getIsDirty: () => isDirty,
    getWorldPath: () => worldPath,
    getCurrentPlayerLabel: currentPlayerLabel,
    onRuntimeDiagnostics: data => { lastRuntimeDiagnostics = data; },
});
const loadRuntimeDiagnostics = diagnosticsController.loadRuntimeDiagnostics;
const loadRecentLogs = diagnosticsController.loadRecentLogs;
diagnosticsController.wire();

const backupsController = window.MCBEBackupsView.createInventoryBackupsController({
    doc: document,
    appConfig,
    api: apiClient,
    getWorldPath: () => worldPath,
    copyTextToClipboard,
    logStatus,
    showToast,
    showLoading,
    hideLoading,
    onRestoreBackup: filename => restoreBackup(filename),
    guardWorldWriteAction,
    beginServerStatusRequest,
    renderWriteGate: (writeGate, options) => renderServerStatus(
        { server_status: writeGate.server_status, write_gate: writeGate },
        { ...options, authoritativeBlock: true },
    ),
    syncWriteControls: () => updateWriteControls(),
});
const loadBackupsList = backupsController.loadBackupsList;
backupsController.wire();

// --- DB Update Management ---

const updateDbController = window.MCBEUpdateDbView.createInventoryUpdateDbController({
    doc: document,
    api: apiClient,
    showLoading,
    hideLoading,
    logStatus,
    showToast,
    showConfirmDialog,
    async onReloaded(data) {
        if (data.item_db) dataSourceController.applyItemDbStatus(data.item_db);
        else await loadItemDbStatus();
        return window.MCBEUpdateDbView.refreshLoadedPlayerAfterDbUpdate({
            currentPlayerKey,
            isDirty,
            loadPlayer,
        });
    },
});

function appendUpdateOutput(text) {
    updateDbController.appendOutput(text);
}

firstRunSetupController = window.MCBEFirstRunSetupView.createInventoryFirstRunSetupController({
    doc: document,
    // Readiness is bound to the server-side database artifact and survives
    // browser changes without surviving a /data reset incorrectly.
    isItemDbPending: () => {
        if (!itemDbStatus || itemDbStatus.status === "unavailable") return null;
        return itemDbStatus.verification?.verified !== true;
    },
    isIconsPending: () => {
        if (["loading", "unavailable"].includes(iconSourceSummary?.status)) return null;
        return Number(iconSourceSummary?.count || 0) === 0;
    },
    // The setup row confirms the forced update, so no second dialog is needed.
    runItemDbUpdate: () => updateDbController.run(false, true, { only: null }),
    runIconsUpdate: () => iconSourcesController.updateVanillaIcons(),
    refreshItemDbStatus: () => loadItemDbStatus(),
    refreshIconSources: () => loadLocalIconIndex({ rescan: false, throwOnError: true }),
    canWriteAppState: () => iconSourcesController.canWriteAppState(),
    loadWorkspace: () => getWorkspaceController().loadWorkspace(),
    saveWorkspace,
    readOnlyMessage: t("Nur ansehen: Diese Instanz darf keine App-Daten schreiben."),
});

// --- End DB Update Management ---

const playerTransferController = window.MCBEPlayerTransferLogic.createInventoryPlayerTransferController({
    doc: document,
    withCsrf,
    parseJsonResponse,
    state: {
        getWorldPath: () => worldPath,
        getCurrentPlayerKey: () => currentPlayerKey,
        getCurrentPlayer: () => currentPlayer,
        getCurrentPlayerRevision: () => currentPlayerRevision,
        getIsDirty: () => isDirty,
        getCurrentImportPreview: () => currentImportPreview,
        getCurrentPlayerLabel: currentPlayerLabel,
        getWorldPresenceSessionId,
        getLastPlayerExportDir: () => lastPlayerExportDir,
        setLastPlayerExportDir: value => { lastPlayerExportDir = value; },
    },
    helpers: {
        updatePlayerExportFolderControl,
        updateImportControls,
        // Export ist app_write: nur der Read-Only-Modus sperrt ihn, nicht das
        // Server-Online-Gate (siehe Backend-Policy-Tabelle).
        writeBlocked: () => !permissions().canExport,
        schedulePlayerImportPreview,
        refreshPlayerImportPreview,
        renderServerStatus,
        beginServerStatusRequest,
        confirmPresenceConflict,
        showConfirmDialog,
        showLoading,
        hideLoading,
        logStatus,
        showToast,
        recordAction,
        guardWorldWriteAction,
        refreshImportedPlayer: async playerKey => {
            await loadPlayersList(false);
            await loadPlayer(playerKey, true, { showLoadingOverlay: false });
        },
    },
});
playerTransferController.wire();

const backupRestoreController = window.MCBEBackupRestoreLogic.createConfiguredBackupRestoreController({
    doc: document,
    api: { withCsrf, parseJsonResponse },
    state: {
        getWorldPath: () => worldPath,
        getWorldName: () => worldNameEl?.textContent || t("Geladene Welt"),
        getCurrentPlayerKey: () => currentPlayerKey,
        getPlayers: () => players,
        setPlayers: value => { players = value; },
        getWorldPresenceSessionId,
    },
    flow: {
        confirmPresenceConflict,
        clearLoadError,
        resetLoadedPlayerState,
        loadPlayersList,
        loadBackupsList,
        beginServerStatusRequest,
        renderWriteGate: (writeGate, options) => renderServerStatus(
            { server_status: writeGate.server_status, write_gate: writeGate },
            { ...options, authoritativeBlock: true },
        ),
        guardWorldWriteAction,
        renderPlayersList,
        renderPlayerToolOptions,
        renderWorldAnalysis,
        updateWorldPresence,
        setWorkflowView,
        loadPlayer,
    },
    helpers: { showLoading, hideLoading, logStatus, showToast },
});
const restoreBackup = backupRestoreController.restoreBackup;

const itemBrowserController = window.MCBEItemBrowserController.createInventoryItemBrowserController({
    doc: document,
    itemCatalog,
    getItemsDb: () => itemsDb,
    getAddableItems: () => addableItems,
    getBlockOnlyItems: () => blockOnlyItems,
    getBlockItems: () => blockItems,
    getItemAvailability: itemAvailabilityCatalog.badgeFor,
    onDetailItemChanged: resetDetailFormForNewItem,
    onDetailItemVariantSelected: selectDetailItemVariant,
    onApplyDetailItem: applyCurrentSingleSlot,
});

itemBrowserController.wire();

window.MCBEWorkflowState.createInventoryEditorBootController({
    doc: document,
    inventoryViewPreferences: getInventoryViewPreferences(),
    clearSelection,
    responsivePanelController,
    lifecycleController: window.MCBEWorkflowState.createAppLifecycleController({
        win: window,
        appConfig,
        withCsrf,
        getIsDirty: () => isDirty,
        refreshServerStatus,
        getWorldPresenceController,
        scanPathsController,
        scanWorlds,
        renderRecentWorlds,
    }),
    workspaceController: getWorkspaceController(),
    workspaceActions: { confirmClear: showConfirmDialog },
    renderWorkspacePanel,
    iconSourcesController,
    loadLocalIconIndex,
    loadItemDbStatus,
    onInitialDataLoaded: () => firstRunSetupController.maybeOpenOnStart(),
    setInitialWorkflowView: setWorkflowView,
    updateGridVisuals,
}).start();
