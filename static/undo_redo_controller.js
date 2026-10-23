(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const DEFAULT_LABEL = () => t("Änderung");

    function normalizedLabel(label) {
        return String(label || DEFAULT_LABEL()).slice(0, 400);
    }

    function createUndoRedoController({
        takeSnapshot,
        snapshotHash,
        maxUndo = 50,
    } = {}) {
        if (typeof takeSnapshot !== "function") throw new Error("takeSnapshot dependency is required");
        if (typeof snapshotHash !== "function") throw new Error("snapshotHash dependency is required");

        let undoStack = [];
        let redoStack = [];
        let undoLabels = [];
        let redoLabels = [];
        let lastMergeKey = null;

        function trim(stack, labels) {
            if (stack.length > maxUndo) {
                stack.shift();
                labels.shift();
            }
        }

        function state() {
            return {
                undoLabels: undoLabels.slice(),
                redoLabels: redoLabels.slice(),
                undoCount: undoStack.length,
                redoCount: redoStack.length,
            };
        }

        function reset() {
            lastMergeKey = null;
            undoStack = [];
            redoStack = [];
            undoLabels = [];
            redoLabels = [];
            return state();
        }

        function pushUndo(label = DEFAULT_LABEL(), { mergeKey = null } = {}) {
            const snap = takeSnapshot();
            const hash = snapshotHash(snap);
            const lastHash = undoStack.length ? snapshotHash(undoStack[undoStack.length - 1]) : null;
            if (mergeKey !== null && mergeKey === lastMergeKey && undoStack.length) {
                undoLabels[undoLabels.length - 1] = normalizedLabel(label);
            } else if (hash !== lastHash) {
                undoStack.push(snap);
                undoLabels.push(normalizedLabel(label));
                trim(undoStack, undoLabels);
            }
            redoStack = [];
            redoLabels = [];
            lastMergeKey = mergeKey;
            return state();
        }

        function undo() {
            lastMergeKey = null;
            if (undoStack.length === 0) return null;
            redoStack.push(takeSnapshot());
            redoLabels.push(undoLabels[undoLabels.length - 1] || DEFAULT_LABEL());
            trim(redoStack, redoLabels);
            const snapshot = undoStack.pop();
            const label = undoLabels.pop() || DEFAULT_LABEL();
            return { snapshot, label, state: state() };
        }

        function redo() {
            lastMergeKey = null;
            if (redoStack.length === 0) return null;
            undoStack.push(takeSnapshot());
            undoLabels.push(redoLabels[redoLabels.length - 1] || DEFAULT_LABEL());
            trim(undoStack, undoLabels);
            const snapshot = redoStack.pop();
            const label = redoLabels.pop() || DEFAULT_LABEL();
            return { snapshot, label, state: state() };
        }

        return {
            pushUndo,
            redo,
            reset,
            state,
            undo,
        };
    }



    function createUndoRedoAppController({
        buttons = {},
        panel = null,
        saveState = null,
        hasPlayer = () => false,
        getIsDirty = () => false,
        takeSnapshot,
        snapshotHash,
        cloneJson = value => JSON.parse(JSON.stringify(value)),
        maxUndo = 50,
        getPlayerStats = () => ({}),
        setInventory = () => {},
        setEnderChestInventory = () => {},
        setPlayerStats = () => {},
        setPlayerEffects = () => {},
        setPlayerAbilities = () => {},
        setPendingMounts = () => {},
        touchedStatsFields = null,
        onSnapshotApplied = () => {},
        onCleanMarked = () => {},
        updateGridVisuals = () => {},
        updateSelectionUI = () => {},
        setDirty = () => {},
        recordAction = () => {},
        editingBlocked = () => false,
        getEditingBlockedReason = () => "",
        guardPendingChanges = () => false,
    } = {}) {
        const stack = createUndoRedoController({ takeSnapshot, snapshotHash, maxUndo });
        let cleanSnapshot = null;
        let cleanSnapshotHash = "";

        function currentStateIsClean() {
            return cleanSnapshotHash !== "" && snapshotHash(takeSnapshot()) === cleanSnapshotHash;
        }

        function getCleanSnapshot() {
            return cleanSnapshot;
        }

        function renderUndoRedoPanel() {
            window.MCBEUndoRedoView.applyHistorySaveState?.(saveState, { hasPlayer: hasPlayer(), isDirty: getIsDirty() });
            if (!panel) return;
            panel.innerHTML = window.MCBEUndoRedoView.undoRedoPanelHtml(stack.state());
        }

        function updateUndoButtons() {
            const model = window.MCBEUndoRedoView.undoRedoButtonModels(stack.state());
            if (editingBlocked()) {
                const reason = getEditingBlockedReason() || t("Bearbeitung ist aktuell gesperrt.");
                model.undo.blocked = true;
                model.undo.blockedTitle = reason;
                model.redo.blocked = true;
                model.redo.blockedTitle = reason;
            }
            window.MCBEUndoRedoView.applyUndoRedoButtonModels({
                undoButton: buttons.undo,
                redoButton: buttons.redo,
                historyUndoButton: buttons.historyUndo,
                historyRedoButton: buttons.historyRedo,
            }, model);
            renderUndoRedoPanel();
        }

        function resetForUnloadedPlayer() {
            stack.reset();
            cleanSnapshotHash = snapshotHash(takeSnapshot());
            cleanSnapshot = null;
            updateUndoButtons();
        }

        function markCleanState() {
            cleanSnapshot = takeSnapshot();
            cleanSnapshotHash = snapshotHash(cleanSnapshot);
            stack.reset();
            onCleanMarked();
            setDirty(false);
            updateUndoButtons();
        }

        function pushUndo(label = DEFAULT_LABEL(), options) {
            stack.pushUndo(label, options);
            updateUndoButtons();
        }

        function applySnapshot(snap = {}) {
            setInventory(cloneJson(snap.inv || {}));
            setEnderChestInventory(cloneJson(snap.ec || {}));
            setPlayerStats(cloneJson(snap.stats || getPlayerStats()));
            setPlayerEffects(cloneJson(snap.effects || []));
            setPlayerAbilities(cloneJson(snap.abilities || {}));
            setPendingMounts(cloneJson(snap.mounts || []));
            touchedStatsFields?.clear?.();
            onSnapshotApplied();
        }

        function undo() {
            if (editingBlocked() || guardPendingChanges()) return false;
            const result = stack.undo();
            if (!result) return;
            applySnapshot(result.snapshot);
            updateGridVisuals();
            updateSelectionUI();
            setDirty(!currentStateIsClean());
            updateUndoButtons();
            recordAction(t("Rückgängig: {label}", { label: result.label }), "undo");
        }

        function redo() {
            if (editingBlocked() || guardPendingChanges()) return false;
            const result = stack.redo();
            if (!result) return;
            applySnapshot(result.snapshot);
            updateGridVisuals();
            updateSelectionUI();
            setDirty(!currentStateIsClean());
            updateUndoButtons();
            recordAction(t("Wiederholen: {label}", { label: result.label }), "undo");
        }

        function wire() {
            buttons.undo?.addEventListener("click", undo);
            buttons.redo?.addEventListener("click", redo);
            buttons.historyUndo?.addEventListener("click", undo);
            buttons.historyRedo?.addEventListener("click", redo);
            updateUndoButtons();
        }

        return {
            currentStateIsClean,
            getCleanSnapshot,
            markCleanState,
            pushUndo,
            redo,
            renderUndoRedoPanel,
            resetForUnloadedPlayer,
            undo,
            updateUndoButtons,
            wire,
        };
    }

    function collectUndoRedoElements(doc = document) {
        return {
            buttons: {
                undo: doc.getElementById("btnUndo"),
                redo: doc.getElementById("btnRedo"),
                historyUndo: doc.getElementById("btnHistoryUndo"),
                historyRedo: doc.getElementById("btnHistoryRedo"),
            },
            panel: doc.getElementById("undoRedoPanel"),
            saveState: doc.getElementById("historySaveState"),
        };
    }

    function createInventoryUndoRedoAppController({ doc = document, ...deps } = {}) {
        return createUndoRedoAppController({
            ...deps,
            ...collectUndoRedoElements(doc),
        });
    }

    window.MCBEUndoRedoController = {
        createUndoRedoController,
        createUndoRedoAppController,
        collectUndoRedoElements,
        createInventoryUndoRedoAppController,
    };
}());
