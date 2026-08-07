(function () {
    "use strict";

    function normalizeSelection(selection = {}) {
        return {
            selectedSlots: Array.isArray(selection.selectedSlots) ? selection.selectedSlots.slice() : [],
            selectedEnderSlot: Number.isInteger(selection.selectedEnderSlot) ? selection.selectedEnderSlot : -1,
        };
    }

    function selectInventorySlot(selection, slotId, additive = false) {
        const next = normalizeSelection(selection);
        next.selectedEnderSlot = -1;
        if (additive) {
            const index = next.selectedSlots.indexOf(slotId);
            if (index >= 0) {
                next.selectedSlots.splice(index, 1);
            } else {
                next.selectedSlots.push(slotId);
            }
        } else {
            next.selectedSlots = [slotId];
        }
        return next;
    }

    function selectEnderSlot(_selection, slotId) {
        return {
            selectedSlots: [],
            selectedEnderSlot: slotId,
        };
    }

    function clearSelection() {
        return {
            selectedSlots: [],
            selectedEnderSlot: -1,
        };
    }

    function isSlotSelected(selection, slotId, containerName) {
        const current = normalizeSelection(selection);
        if (containerName === "ender_chest") return current.selectedEnderSlot === slotId;
        return current.selectedSlots.includes(slotId);
    }

    function selectedCount(selection) {
        const current = normalizeSelection(selection);
        return current.selectedSlots.length + (current.selectedEnderSlot >= 0 ? 1 : 0);
    }

    function hasSelection(selection) {
        return selectedCount(selection) > 0;
    }

    function selectedSingleTarget(selection) {
        const current = normalizeSelection(selection);
        if (current.selectedEnderSlot >= 0) {
            return {
                slotId: current.selectedEnderSlot,
                containerName: "ender_chest",
                isEnder: true,
            };
        }
        if (current.selectedSlots.length === 1) {
            return {
                slotId: current.selectedSlots[0],
                containerName: "inventory",
                isEnder: false,
            };
        }
        return null;
    }

    function selectedClipboardSourceTarget(selection) {
        const current = normalizeSelection(selection);
        if (current.selectedEnderSlot >= 0) {
            return {
                slotId: current.selectedEnderSlot,
                containerName: "ender_chest",
                isEnder: true,
            };
        }
        if (current.selectedSlots.length > 0) {
            return {
                slotId: current.selectedSlots[0],
                containerName: "inventory",
                isEnder: false,
            };
        }
        return null;
    }

    function selectedWritableInventorySlots(selection, isProtectedKnownSlot = () => false) {
        const current = normalizeSelection(selection);
        return current.selectedSlots.filter(slotId => !isProtectedKnownSlot(slotId, "inventory"));
    }

    window.MCBESelectionState = {
        clearSelection,
        hasSelection,
        isSlotSelected,
        selectEnderSlot,
        selectInventorySlot,
        selectedClipboardSourceTarget,
        selectedSingleTarget,
        selectedWritableInventorySlots,
        selectedCount,
    };
}());
