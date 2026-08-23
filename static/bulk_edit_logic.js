(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function normalizedItemName(rawName) {
        return String(rawName || "").trim().toLowerCase();
    }

    function clampInteger(value, fallback, min, max) {
        const parsed = parseInt(value, 10);
        if (!Number.isFinite(parsed)) return fallback;
        let lower = min;
        let upper = max;
        if (lower > upper) [lower, upper] = [upper, lower];
        return Math.min(Math.max(parsed, lower), upper);
    }

    function noWritableTargets() {
        return {
            ok: false,
            toast: {
                message: t("Keine beschreibbaren Slots ausgewählt. Geschützte Slots bleiben unverändert."),
                type: "warning",
                ms: 3000,
            },
        };
    }

    function skippedProtected(writableCount, selectedCount) {
        return writableCount !== selectedCount;
    }

    function bulkFillPlan({
        rawName = "",
        isValidItemId = true,
        maxStack = 64,
        maxDamage = 0,
        rawCount = 1,
        rawDamage = 0,
        writableCount = 0,
        selectedCount = 0,
        selectionLabel = "",
    } = {}) {
        const name = normalizedItemName(rawName);
        if (name && name !== "minecraft:air" && !isValidItemId) {
            return {
                ok: false,
                toast: {
                    message: t("Ungültige Item-ID. Erwartet wird z. B. minecraft:stone."),
                    type: "warning",
                    ms: 4000,
                },
            };
        }

        const count = clampInteger(rawCount, maxStack, 1, maxStack);
        const damage = clampInteger(rawDamage, 0, 0, maxDamage);
        if (!name || name === "minecraft:air" || count <= 0) {
            return {
                ok: false,
                toast: {
                    message: t("Bitte wähle ein gültiges Item aus."),
                    type: "warning",
                    ms: 3000,
                },
            };
        }
        if (writableCount === 0) return noWritableTargets();

        const label = selectionLabel || t("{count} markierte Slot(s)", { count: writableCount });
        return {
            ok: true,
            item: { name, count, damage },
            undoLabel: t("Markierte Slots mit {name} gefüllt", { name }),
            skippedProtected: skippedProtected(writableCount, selectedCount),
            statusMessage: t("{label} gefüllt mit {name}", { label, name }),
            actionMessage: t("{label} gefüllt mit {name}", { label, name }),
        };
    }

    function bulkClearPlan({ writableCount = 0, selectedCount = 0, selectionLabel = "" } = {}) {
        if (writableCount === 0) return noWritableTargets();
        const label = selectionLabel || t("{count} markierte Slot(s)", { count: writableCount });
        return {
            ok: true,
            undoLabel: t("Markierte Slots geleert"),
            skippedProtected: skippedProtected(writableCount, selectedCount),
            statusMessage: t("{label} geleert", { label }),
            actionMessage: t("{label} geleert", { label }),
        };
    }

    function bulkSetCountPlan({ targetCount = 0, rawDesired = "" } = {}) {
        if (targetCount === 0) {
            return {
                ok: false,
                toast: {
                    message: t("Keine belegten markierten Slots gefunden."),
                    type: "warning",
                    ms: 3000,
                },
            };
        }
        const desired = Number.parseInt(rawDesired, 10);
        if (!Number.isFinite(desired) || desired < 1) {
            return {
                ok: false,
                toast: {
                    message: t("Bitte eine gültige Menge eingeben."),
                    type: "warning",
                    ms: 3000,
                },
            };
        }
        return {
            ok: true,
            desired,
            undoLabel: t("Menge für markierte Slots gesetzt"),
        };
    }

    function bulkSetCountOutcome(changed = 0) {
        return {
            recordMessage: t("Menge für {count} markierte Slot(s) gesetzt", { count: changed }),
            toast: {
                message: t("Menge für {count} Slot(s) gesetzt.", { count: changed }),
                type: "success",
                ms: 2500,
            },
        };
    }

    function bulkRepairSelectedPlan({ targetCount = 0 } = {}) {
        if (targetCount === 0) {
            return {
                ok: false,
                toast: {
                    message: t("Keine beschädigten markierten Items gefunden."),
                    type: "warning",
                    ms: 3000,
                },
            };
        }
        return {
            ok: true,
            undoLabel: t("Markierte Items repariert"),
            recordMessage: t("{count} markierte Item(s) repariert", { count: targetCount }),
            toast: {
                message: t("{count} markierte Item(s) repariert.", { count: targetCount }),
                type: "success",
                ms: 2500,
            },
        };
    }

    function repairAllPlan({ targetCount = 0 } = {}) {
        if (targetCount === 0) {
            return {
                ok: false,
                statusMessage: t("Keine haltbaren Items mit Abnutzung gefunden."),
                statusType: "warning",
            };
        }
        return {
            ok: true,
            undoLabel: t("Alle reparierbaren Items repariert"),
            statusMessage: t("Reparierte haltbare Items: {count} (inkl. Enderchest).", { count: targetCount }),
            statusType: "success",
            actionMessage: t("Haltbare Items repariert: {count}", { count: targetCount }),
        };
    }

    window.MCBEBulkEditLogic = {
        bulkClearPlan,
        bulkFillPlan,
        bulkRepairSelectedPlan,
        bulkSetCountOutcome,
        bulkSetCountPlan,
        normalizedItemName,
        repairAllPlan,
    };
}());

(function () {
    "use strict";

    const logic = window.MCBEBulkEditLogic || {};

    function createBulkEditController({
        elements = {},
        itemCatalog,
        maxBedrockStackCount = 64,
        getSelectedSlots,
        getSelectedEnderSlot,
        getInventory,
        getEnderChestInventory,
        getCurrentSelectionState,
        getMaxDamage,
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
        guardEditingAction = () => false,
    } = {}) {
        function selectedBulkTargets() {
            return window.MCBEInventoryState.selectedBulkTargets({
                selectedSlots: getSelectedSlots?.() || [],
                selectedEnderSlot: getSelectedEnderSlot?.(),
                inventory: getInventory?.() || {},
                enderChestInventory: getEnderChestInventory?.() || {},
                isProtectedKnownSlot,
            });
        }

        function selectedBulkLabel(count) {
            return window.MCBEInventoryState.bulkSelectionLabel(count, {
                selectedEnderSlot: getSelectedEnderSlot?.(),
            });
        }

        function selectedCount() {
            return window.MCBESelectionState.selectedCount(getCurrentSelectionState?.());
        }

        function finishBulkEdit({ dirty = true, refreshAnalysis = true, clear = true } = {}) {
            updateGridVisuals?.();
            if (dirty) setDirty?.(true);
            if (refreshAnalysis) renderWorldAnalysis?.();
            if (clear) clearSelection?.();
        }

        function wireBulkFill() {
            elements.fillButton?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                const name = logic.normalizedItemName(elements.bulkItemSearch?.value);
                const validBulkItemId = !name || name === "minecraft:air"
                    || (itemCatalog.isValidItemId(name) && itemCatalog.isAddableItemId(name));
                const maxStack = validBulkItemId ? itemCatalog.getMaxStack(name) : 64;
                const maxDmg = validBulkItemId ? itemCatalog.getMaxDamage(name) : 0;
                const writableTargets = selectedBulkTargets();
                const plan = logic.bulkFillPlan({
                    rawName: name,
                    isValidItemId: validBulkItemId,
                    maxStack,
                    maxDamage: maxDmg,
                    rawCount: elements.bulkCount?.value,
                    rawDamage: elements.bulkDamage?.value,
                    writableCount: writableTargets.length,
                    selectedCount: selectedCount(),
                    selectionLabel: selectedBulkLabel(writableTargets.length),
                });
                if (!plan.ok) {
                    if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                    return;
                }
                const rules = window.MCBEEquipmentRules;
                const wearableTargets = rules
                    ? writableTargets.filter(target => !rules.isEquipmentSlot(target.slotId, target.container) || rules.itemAllowedInEquipmentSlot(target.slotId, plan.item.name))
                    : writableTargets;
                if (wearableTargets.length === 0) {
                    showToast?.(rules.notWearableMessage(writableTargets[0].slotId, plan.item.name), "warning", 4000);
                    return;
                }
                pushUndo?.(plan.undoLabel);
                if (plan.skippedProtected) showToast?.(t("Geschützte Slots wurden übersprungen."), "warning", 3000);
                if (wearableTargets.length !== writableTargets.length) {
                    showToast?.(t("Ausrüstungsslots wurden übersprungen: Item dort nicht tragbar."), "warning", 3000);
                }
                window.MCBEInventoryState.fillTargets(wearableTargets, plan.item);
                finishBulkEdit();
                logStatus?.(plan.statusMessage, "success");
                recordAction?.(plan.actionMessage, "edit");
            });
        }

        function wireBulkClear() {
            elements.clearButton?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                const writableTargets = selectedBulkTargets();
                const plan = logic.bulkClearPlan({
                    writableCount: writableTargets.length,
                    selectedCount: selectedCount(),
                    selectionLabel: selectedBulkLabel(writableTargets.length),
                });
                if (!plan.ok) {
                    if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                    return;
                }
                pushUndo?.(plan.undoLabel);
                window.MCBEInventoryState.clearTargets(writableTargets);
                finishBulkEdit();
                if (plan.skippedProtected) showToast?.(t("Geschützte Slots wurden übersprungen."), "warning", 3000);
                logStatus?.(plan.statusMessage, "success");
                recordAction?.(plan.actionMessage, "edit");
            });
        }

        function wireBulkSetCount() {
            elements.setCountButton?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                const targets = window.MCBEInventoryState.visibleItemTargets(selectedBulkTargets(), itemIsVisiblePresent);
                const plan = logic.bulkSetCountPlan({
                    targetCount: targets.length,
                    rawDesired: elements.bulkCount?.value,
                });
                if (!plan.ok) {
                    if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                    return;
                }
                pushUndo?.(plan.undoLabel);
                const changed = window.MCBEInventoryState.setTargetCounts(targets, {
                    desired: plan.desired,
                    getMaxStack: itemCatalog.getMaxStack,
                    maxBedrockStackCount,
                });
                finishBulkEdit({ clear: false });
                const outcome = logic.bulkSetCountOutcome(changed);
                recordAction?.(outcome.recordMessage, "edit");
                showToast?.(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
            });
        }

        function wireBulkRepairSelected() {
            elements.repairSelectedButton?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                const targets = window.MCBEInventoryState.damagedItemTargets(selectedBulkTargets(), {
                    maxDamage: getMaxDamage?.() || {},
                    isItemVisiblePresent: itemIsVisiblePresent,
                });
                const plan = logic.bulkRepairSelectedPlan({ targetCount: targets.length });
                if (!plan.ok) {
                    if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                    return;
                }
                pushUndo?.(plan.undoLabel);
                window.MCBEInventoryState.repairTargets(targets);
                finishBulkEdit({ clear: false });
                recordAction?.(plan.recordMessage, "edit");
                showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
            });
        }

        function wireRepairAll() {
            elements.repairAllButton?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                const repairTargets = window.MCBEInventoryState.damagedInventoryTargets({
                    sources: [{ map: getInventory?.() || {} }, { map: getEnderChestInventory?.() || {} }],
                    maxDamage: getMaxDamage?.() || {},
                    isItemVisiblePresent: itemIsVisiblePresent,
                });
                const plan = logic.repairAllPlan({ targetCount: repairTargets.length });
                if (!plan.ok) {
                    logStatus?.(plan.statusMessage, plan.statusType);
                    return;
                }
                pushUndo?.(plan.undoLabel);
                window.MCBEInventoryState.repairTargets(repairTargets);
                finishBulkEdit({ clear: false });
                logStatus?.(plan.statusMessage, plan.statusType);
                recordAction?.(plan.actionMessage, "edit");
            });
        }

        function wire() {
            wireBulkFill();
            wireBulkClear();
            wireBulkSetCount();
            wireBulkRepairSelected();
            wireRepairAll();
        }

        return {
            selectedBulkTargets,
            selectedBulkLabel,
            wire,
        };
    }

    function collectBulkEditElements(doc = document) {
        return {
            bulkItemSearch: doc.getElementById("bulkItemSearch"),
            bulkCount: doc.getElementById("bulkCount"),
            bulkDamage: doc.getElementById("bulkDamage"),
            fillButton: doc.getElementById("btnBulkFill"),
            clearButton: doc.getElementById("btnBulkClear"),
            setCountButton: doc.getElementById("btnBulkSetCount"),
            repairSelectedButton: doc.getElementById("btnBulkRepairSelected"),
            repairAllButton: doc.getElementById("btnRepairAll"),
        };
    }

    function createInventoryBulkEditController({
        doc = document,
        itemCatalog,
        maxBedrockStackCount,
        state = {},
        helpers = {},
    } = {}) {
        return createBulkEditController({
            elements: collectBulkEditElements(doc),
            itemCatalog,
            maxBedrockStackCount,
            getSelectedSlots: state.getSelectedSlots,
            getSelectedEnderSlot: state.getSelectedEnderSlot,
            getInventory: state.getInventory,
            getEnderChestInventory: state.getEnderChestInventory,
            getCurrentSelectionState: state.getCurrentSelectionState,
            getMaxDamage: state.getMaxDamage,
            isProtectedKnownSlot: helpers.isProtectedKnownSlot,
            itemIsVisiblePresent: helpers.itemIsVisiblePresent,
            pushUndo: helpers.pushUndo,
            updateGridVisuals: helpers.updateGridVisuals,
            setDirty: helpers.setDirty,
            renderWorldAnalysis: helpers.renderWorldAnalysis,
            logStatus: helpers.logStatus,
            recordAction: helpers.recordAction,
            showToast: helpers.showToast,
            clearSelection: helpers.clearSelection,
            guardEditingAction: helpers.guardEditingAction,
        });
    }

    window.MCBEBulkEditLogic = {
        ...logic,
        collectBulkEditElements,
        createBulkEditController,
        createInventoryBulkEditController,
    };
}());
