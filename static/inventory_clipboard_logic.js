(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function normalizeSelection(selection = {}) {
        return {
            selectedSlots: Array.isArray(selection.selectedSlots) ? selection.selectedSlots.slice() : [],
            selectedEnderSlot: Number.isInteger(selection.selectedEnderSlot) ? selection.selectedEnderSlot : -1,
        };
    }

    function contextMenuButtonModel({ hasClipboard = false, protectedKnown = false } = {}) {
        const editable = !protectedKnown;
        return {
            copyVisible: editable,
            pasteVisible: Boolean(hasClipboard) && editable,
            cutVisible: editable,
            clearVisible: editable,
        };
    }

    function contextSlotActionPlan({
        action = "",
        slotId = null,
        containerName = "inventory",
        protectedKnown = false,
        hasClipboard = false,
        hasSourceItem = false,
        clipboardItemName = "",
    } = {}) {
        if (slotId === null || slotId === undefined || Number.isNaN(Number(slotId))) {
            return { ok: false, reason: "missing_slot" };
        }
        if (protectedKnown) {
            return { ok: false, reason: "protected_slot", showProtected: true };
        }
        if (action === "copy") {
            return hasSourceItem
                ? { ok: true, operation: "copy", selectSlot: true }
                : { ok: false, reason: "empty_source" };
        }
        if (action === "paste") {
            if (!hasClipboard) return { ok: false, reason: "empty_clipboard" };
            const rules = window.MCBEEquipmentRules;
            if (rules && rules.isEquipmentSlot(slotId, containerName) && !rules.itemAllowedInEquipmentSlot(slotId, clipboardItemName)) {
                return { ok: false, reason: "not_wearable", slot: slotId, itemName: clipboardItemName };
            }
            return { ok: true, operation: "paste", requiresUndo: true, selectSlot: true };
        }
        if (action === "cut") {
            return hasSourceItem
                ? { ok: true, operation: "cut", requiresUndo: true }
                : { ok: false, reason: "empty_source" };
        }
        if (action === "clear") {
            // Ein leerer Slot darf keinen Dirty-Status setzen und keinen
            // Redo-Stack verwerfen; es gibt nichts zu leeren.
            return hasSourceItem
                ? { ok: true, operation: "clear", requiresUndo: true }
                : { ok: false, reason: "empty_source" };
        }
        return { ok: false, reason: "unknown_action" };
    }

    function keyboardCopyPlan({ sourceTarget = null, hasSourceItem = false, protectedSource = false } = {}) {
        if (!sourceTarget) return { ok: false, reason: "missing_source_target" };
        // Geschützte Slots (inkl. read-only Root-Ausrüstung) dürfen nicht ins
        // Clipboard: eine eingefügte Kopie ließe sich nicht speichern.
        if (protectedSource) return { ok: false, reason: "protected_slot", showProtected: true, target: sourceTarget };
        return hasSourceItem
            ? { ok: true, operation: "copy", target: sourceTarget }
            : { ok: false, reason: "empty_source" };
    }

    function keyboardPastePlan({
        selection = {},
        singleTarget = null,
        writableSlots = [],
        protectedEnder = false,
        hasClipboard = false,
        clipboardItemName = "",
    } = {}) {
        if (!hasClipboard) return { ok: false, reason: "empty_clipboard" };
        if (singleTarget?.isEnder) {
            if (protectedEnder) return { ok: false, reason: "protected_slot", showProtected: true, target: singleTarget };
            return { ok: true, operation: "paste_ender", target: singleTarget, requiresUndo: true };
        }
        const current = normalizeSelection(selection);
        if (writableSlots.length === 0) return { ok: false, reason: "no_writable_inventory_slots" };
        // Ausrüstungsslots nur befüllen, wenn das Clipboard-Item dort tragbar ist.
        const rules = window.MCBEEquipmentRules;
        const wearableSlots = rules
            ? writableSlots.filter(slotId => !rules.isEquipmentSlot(slotId, "inventory") || rules.itemAllowedInEquipmentSlot(slotId, clipboardItemName))
            : writableSlots.slice();
        if (wearableSlots.length === 0) {
            return { ok: false, reason: "not_wearable", slot: writableSlots[0], itemName: clipboardItemName };
        }
        return {
            ok: true,
            operation: "paste_inventory",
            writableSlots: wearableSlots.slice(),
            skippedProtected: writableSlots.length !== current.selectedSlots.length,
            skippedNotWearable: wearableSlots.length !== writableSlots.length,
            requiresUndo: true,
        };
    }

    function keyboardCutPlan({
        singleTarget = null,
        protectedTarget = false,
        hasSourceItem = false,
    } = {}) {
        // Cut is single-target because the internal clipboard stores one item.
        if (!singleTarget) return { ok: false, reason: "single_selection_required" };
        if (protectedTarget) return { ok: false, reason: "protected_slot", showProtected: true, target: singleTarget };
        return hasSourceItem
            ? {
                ok: true,
                operation: singleTarget.isEnder ? "cut_ender" : "cut_inventory",
                target: singleTarget,
                requiresUndo: true,
            }
            : { ok: false, reason: "empty_source" };
    }

    function isEditableTextTarget(target) {
        if (!target || !(target instanceof Element)) return false;
        const tag = target.tagName ? target.tagName.toLowerCase() : "";
        return target.isContentEditable || ["input", "textarea", "select"].includes(tag);
    }

    function hasActiveTextSelection(win = window) {
        const selection = win.getSelection?.();
        return !!selection && !selection.isCollapsed && String(selection).length > 0;
    }

    function eventStartedInInventorySurface(event) {
        const target = event.target instanceof Element ? event.target : null;
        return !!target?.closest?.(".inventory-grid, .armor-grid, .ender-chest-grid, .slot-editor-card, .slot-quick-copy, #ctxMenu");
    }

    function clipboardShortcutIntent(event) {
        if (!(event?.ctrlKey || event?.metaKey) || event?.altKey) return "";
        const key = String(event.key || "").toLowerCase();
        if (key === "v") return event.shiftKey ? "paste_item" : "";
        if (event.shiftKey) return "";
        if (key === "c") return "copy_item";
        if (key === "x") return "cut_item";
        return "";
    }

    function createInventoryClipboardController({
        doc = document,
        win = window,
        contextMenu = null,
        getInventory = () => ({}),
        getEnderChestInventory = () => ({}),
        getCurrentPlayerKey = () => "",
        getWorldPath = () => "",
        getCurrentSelectionState = () => ({}),
        getActiveWorkflowView = () => "inventory",
        isProtectedKnownSlot = () => false,
        showProtectedSlotMessage = () => {},
        handleSlotClick = () => {},
        handleEnderSlotClick = () => {},
        pushUndo = () => {},
        updateGridVisuals = () => {},
        setDirty = () => {},
        showToast = () => {},
        recordAction = () => {},
        slotDisplayName = (slotId, containerName) => `${containerName}:${slotId}`,
        clearTargets = targets => window.MCBEInventoryState?.clearTargets?.(targets),
        cloneSlotItem = (item, containerName, helpers) => window.MCBEInventoryState?.cloneSlotItemForClipboard?.(item, containerName, helpers),
        pasteClipboard = (clipboard, targets, helpers) => window.MCBEInventoryState?.pasteClipboardToTargets?.(clipboard, targets, helpers),
    } = {}) {
        let slotClipboard = null;
        let ctxSlotId = null;
        let ctxSlotContainer = "inventory";

        function inventoryForContainer(containerName) {
            return containerName === "ender_chest" ? getEnderChestInventory() : getInventory();
        }

        function ensureItemOrigin(item, containerName) {
            if (!item) return item;
            if (!Number.isInteger(item.source_slot) && Number.isInteger(item.slot)) item.source_slot = item.slot;
            if (!item.source_player_key) item.source_player_key = getCurrentPlayerKey();
            if (!item.source_container) item.source_container = containerName;
            if (!item.source_world_path) item.source_world_path = getWorldPath();
            return item;
        }

        function cloneItemForClipboard(item, containerName) {
            return cloneSlotItem(item, containerName, { ensureOrigin: ensureItemOrigin });
        }

        function pasteClipboardToTargets(targets) {
            return pasteClipboard(slotClipboard, targets, { ensureOrigin: ensureItemOrigin });
        }

        function applyContextMenuButtonModel(model = {}) {
            if (!contextMenu) return;
            contextMenu.querySelector('[data-action="paste"]')?.style.setProperty("display", model.pasteVisible ? "" : "none");
            contextMenu.querySelector('[data-action="copy"]')?.style.setProperty("display", model.copyVisible ? "" : "none");
            contextMenu.querySelector('[data-action="cut"]')?.style.setProperty("display", model.cutVisible ? "" : "none");
            contextMenu.querySelector('[data-action="clear"]')?.style.setProperty("display", model.clearVisible ? "" : "none");
        }

        function hideContextMenu() {
            if (contextMenu) contextMenu.style.display = "none";
        }

        function bindContextMenu() {
            if (!contextMenu) return;
            doc.addEventListener("contextmenu", (event) => {
                const slot = event.target.closest(".inventory-slot");
                if (!slot) {
                    hideContextMenu();
                    return;
                }
                event.preventDefault();
                const isEnder = slot.hasAttribute("data-ender-slot");
                ctxSlotContainer = isEnder ? "ender_chest" : "inventory";
                ctxSlotId = parseInt(slot.getAttribute(isEnder ? "data-ender-slot" : "data-slot"), 10);
                const protectedKnown = isProtectedKnownSlot(ctxSlotId, ctxSlotContainer);
                contextMenu.style.display = "flex";
                contextMenu.style.left = `${event.clientX}px`;
                contextMenu.style.top = `${event.clientY}px`;
                applyContextMenuButtonModel(contextMenuButtonModel({
                    hasClipboard: Boolean(slotClipboard),
                    protectedKnown,
                }));
            });

            doc.addEventListener("click", (event) => {
                if (!event.target.closest(".context-menu")) hideContextMenu();
            });

            contextMenu.querySelectorAll(".context-item").forEach(button => {
                button.addEventListener("click", () => handleContextAction(button.dataset.action));
            });
        }

        function handleContextAction(action) {
            const slotId = ctxSlotId;
            hideContextMenu();
            if (slotId === null) return false;

            const source = inventoryForContainer(ctxSlotContainer);
            const isEnder = ctxSlotContainer === "ender_chest";
            const plan = contextSlotActionPlan({
                action,
                slotId,
                containerName: ctxSlotContainer,
                protectedKnown: isProtectedKnownSlot(slotId, ctxSlotContainer),
                hasClipboard: Boolean(slotClipboard),
                hasSourceItem: Boolean(source[slotId]),
                clipboardItemName: slotClipboard?.name || "",
            });
            if (plan.showProtected) {
                showProtectedSlotMessage(slotId, ctxSlotContainer);
                return true;
            }
            if (plan.reason === "not_wearable") {
                showToast(window.MCBEEquipmentRules.notWearableMessage(plan.slot, plan.itemName), "warning", 4000);
                return true;
            }
            if (!plan.ok) return false;

            if (plan.operation === "copy") {
                slotClipboard = cloneItemForClipboard(source[slotId], ctxSlotContainer);
                showToast(t("📋 {name} kopiert", { name: slotClipboard.name }));
                if (plan.selectSlot) isEnder ? handleEnderSlotClick(null, slotId) : handleSlotClick(null, slotId);
                return true;
            }
            if (plan.operation === "paste") {
                pushUndo();
                pasteClipboardToTargets([{ map: source, slotId, container: ctxSlotContainer }]);
                updateGridVisuals();
                setDirty(true);
                showToast(t("📄 {name} eingefügt", { name: slotClipboard.name }));
                recordAction(t("{name} in {slot} eingefügt", { name: slotClipboard.name, slot: slotDisplayName(slotId, ctxSlotContainer) }), "edit");
                if (plan.selectSlot) isEnder ? handleEnderSlotClick(null, slotId) : handleSlotClick(null, slotId);
                return true;
            }
            if (plan.operation === "cut") {
                const clipboardCandidate = cloneItemForClipboard(source[slotId], ctxSlotContainer);
                if (!clipboardCandidate) return false;
                pushUndo();
                slotClipboard = clipboardCandidate;
                clearTargets([{ map: source, slotId }]);
                updateGridVisuals();
                setDirty(true);
                showToast(t("✂️ {name} ausgeschnitten", { name: slotClipboard.name }));
                recordAction(t("{slot} ausgeschnitten", { slot: slotDisplayName(slotId, ctxSlotContainer) }), "edit");
                return true;
            }
            if (plan.operation === "clear") {
                pushUndo();
                clearTargets([{ map: source, slotId }]);
                updateGridVisuals();
                setDirty(true);
                showToast(t("🗑️ Slot geleert"));
                recordAction(t("{slot} geleert", { slot: slotDisplayName(slotId, ctxSlotContainer) }), "edit");
                return true;
            }
            return false;
        }

        function shouldHandleClipboardShortcut(event) {
            const intent = clipboardShortcutIntent(event);
            if (!intent) return false;
            if (doc.querySelector('.modal-overlay[style*="flex"]')) return false;
            if (getActiveWorkflowView() !== "inventory" && !eventStartedInInventorySurface(event)) return false;
            if (!window.MCBESelectionState.hasSelection(getCurrentSelectionState())) return false;
            if (intent === "paste_item") return true;
            if (isEditableTextTarget(event.target)) return false;
            if (hasActiveTextSelection(win)) return false;
            return true;
        }

        function handleCopyShortcut(event) {
            event.preventDefault();
            const sourceTarget = window.MCBESelectionState.selectedClipboardSourceTarget(getCurrentSelectionState());
            const sourceMap = sourceTarget?.isEnder ? getEnderChestInventory() : getInventory();
            const sourceItem = sourceTarget ? sourceMap[sourceTarget.slotId] : null;
            const plan = keyboardCopyPlan({
                sourceTarget,
                hasSourceItem: Boolean(sourceItem),
                protectedSource: Boolean(sourceTarget && isProtectedKnownSlot(sourceTarget.slotId, sourceTarget.containerName)),
            });
            if (plan.showProtected) {
                showProtectedSlotMessage(plan.target.slotId, plan.target.containerName);
                return true;
            }
            if (!plan.ok) return true;
            slotClipboard = cloneItemForClipboard(sourceItem, sourceTarget.containerName);
            showToast(t("📋 {name} kopiert", { name: slotClipboard.name }));
            return true;
        }

        function handlePasteShortcut(event) {
            event.preventDefault();
            if (!slotClipboard) {
                showToast(`${t("📄 Einfügen")}: ${t("keine Daten")}`, "warning", 2600);
                return true;
            }
            const selection = getCurrentSelectionState();
            const singleTarget = window.MCBESelectionState.selectedSingleTarget(selection);
            const writableSlots = window.MCBESelectionState.selectedWritableInventorySlots(selection, isProtectedKnownSlot);
            const plan = keyboardPastePlan({
                selection,
                singleTarget,
                writableSlots,
                protectedEnder: singleTarget?.isEnder && isProtectedKnownSlot(singleTarget.slotId, "ender_chest"),
                hasClipboard: Boolean(slotClipboard),
                clipboardItemName: slotClipboard?.name || "",
            });
            if (plan.showProtected) {
                showProtectedSlotMessage(plan.target.slotId, plan.target.containerName);
                return true;
            }
            if (!plan.ok) {
                if (plan.reason === "no_writable_inventory_slots") {
                    showToast(t("Keine beschreibbaren Slots ausgewählt. Geschützte Slots bleiben unverändert."), "warning", 3000);
                }
                if (plan.reason === "not_wearable") {
                    showToast(window.MCBEEquipmentRules.notWearableMessage(plan.slot, plan.itemName), "warning", 4000);
                }
                return true;
            }
            if (plan.skippedNotWearable) {
                showToast(t("Ausrüstungsslots wurden übersprungen: Item dort nicht tragbar."), "warning", 3000);
            }
            if (plan.operation === "paste_ender") {
                pushUndo();
                pasteClipboardToTargets([{ map: getEnderChestInventory(), slotId: plan.target.slotId, container: "ender_chest" }]);
                showToast(t("📄 {name} in Enderchest-Slot eingefügt", { name: slotClipboard.name }));
                recordAction(t("{name} in Enderchest-Slot {slot} eingefügt", { name: slotClipboard.name, slot: plan.target.slotId }), "edit");
            } else if (plan.operation === "paste_inventory") {
                pushUndo();
                pasteClipboardToTargets(plan.writableSlots.map(slotId => ({ map: getInventory(), slotId, container: "inventory" })));
                if (plan.skippedProtected) showToast(t("Geschützte Slots wurden übersprungen."), "warning", 3000);
                showToast(t("📄 {name} in {count} Slot(s) eingefügt", { name: slotClipboard.name, count: plan.writableSlots.length }));
                recordAction(t("{name} in {count} Slot(s) eingefügt", { name: slotClipboard.name, count: plan.writableSlots.length }), "edit");
            }
            updateGridVisuals();
            setDirty(true);
            return true;
        }

        function handleCutShortcut(event) {
            event.preventDefault();
            const selection = getCurrentSelectionState();
            const singleTarget = window.MCBESelectionState.selectedSingleTarget(selection);
            const sourceMap = singleTarget?.isEnder ? getEnderChestInventory() : getInventory();
            const sourceItem = singleTarget ? sourceMap[singleTarget.slotId] : null;
            const plan = keyboardCutPlan({
                singleTarget,
                protectedTarget: Boolean(singleTarget && isProtectedKnownSlot(singleTarget.slotId, singleTarget.containerName)),
                hasSourceItem: Boolean(sourceItem),
            });
            if (plan.showProtected) {
                showProtectedSlotMessage(plan.target.slotId, plan.target.containerName);
                return true;
            }
            if (plan.reason === "single_selection_required") {
                showToast(`${t("Ausschneiden")}: ${t("Mehrfachauswahl")}`, "warning", 3000);
                return true;
            }
            if (!plan.ok) return true;

            const clipboardCandidate = cloneItemForClipboard(sourceItem, plan.target.containerName);
            if (!clipboardCandidate) return true;

            // Commit the single destructive operation only after the clipboard
            // clone has been produced successfully.
            pushUndo();
            slotClipboard = clipboardCandidate;
            clearTargets([{ map: sourceMap, slotId: plan.target.slotId }]);
            updateGridVisuals();
            setDirty(true);
            showToast(t("✂️ {name} ausgeschnitten", { name: slotClipboard.name }));
            const actionText = plan.target.isEnder
                ? t("Enderchest-Slot {slot} ausgeschnitten", { slot: plan.target.slotId })
                : t("{slot} ausgeschnitten", { slot: slotDisplayName(plan.target.slotId, plan.target.containerName) });
            recordAction(actionText, "edit");
            return true;
        }

        function handleKeydown(event) {
            if (!shouldHandleClipboardShortcut(event)) return false;
            const intent = clipboardShortcutIntent(event);
            if (intent === "copy_item") return handleCopyShortcut(event);
            if (intent === "paste_item") return handlePasteShortcut(event);
            if (intent === "cut_item") return handleCutShortcut(event);
            return false;
        }

        return {
            bindContextMenu,
            eventStartedInInventorySurface,
            handleKeydown,
            isEditableTextTarget,
            state: () => ({ hasClipboard: Boolean(slotClipboard) }),
        };
    }

    function createConfiguredInventoryClipboardController({
        doc = document,
        win = window,
        state = {},
        selection = {},
        slotHandlers = {},
        helpers = {},
        renderer = {},
    } = {}) {
        return createInventoryClipboardController({
            doc,
            win,
            contextMenu: doc.getElementById("slotContextMenu"),
            getInventory: state.getInventory,
            getEnderChestInventory: state.getEnderChestInventory,
            getCurrentPlayerKey: state.getCurrentPlayerKey,
            getWorldPath: state.getWorldPath,
            getActiveWorkflowView: state.getActiveWorkflowView,
            getCurrentSelectionState: selection.currentSelectionState,
            isProtectedKnownSlot: helpers.isProtectedKnownSlot,
            showProtectedSlotMessage: helpers.showProtectedSlotMessage,
            handleSlotClick: slotHandlers.handleSlotClick,
            handleEnderSlotClick: slotHandlers.handleEnderSlotClick,
            pushUndo: helpers.pushUndo,
            updateGridVisuals: helpers.updateGridVisuals,
            setDirty: helpers.setDirty,
            showToast: helpers.showToast,
            recordAction: helpers.recordAction,
            slotDisplayName: renderer.slotDisplayName,
        });
    }

    window.MCBEInventoryClipboardLogic = {
        clipboardShortcutIntent,
        contextMenuButtonModel,
        createInventoryClipboardController,
        createConfiguredInventoryClipboardController,
        eventStartedInInventorySurface,
        isEditableTextTarget,
        contextSlotActionPlan,
        keyboardCopyPlan,
        keyboardCutPlan,
        keyboardPastePlan,
    };
}());
