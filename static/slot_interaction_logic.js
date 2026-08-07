(function () {
    "use strict";

    const ARROW_DELTAS = {
        ArrowRight: 1,
        ArrowDown: 9,
        ArrowLeft: -1,
        ArrowUp: -9,
    };

    function slotOrderForKeyboard(containerName) {
        if (containerName === "ender_chest") {
            return Array.from({ length: 27 }, (_, i) => ({ container: "ender_chest", slot: i }));
        }
        return [
            { container: "inventory", slot: 103 },
            { container: "inventory", slot: 102 },
            { container: "inventory", slot: 101 },
            { container: "inventory", slot: 100 },
            { container: "inventory", slot: -106 },
            ...Array.from({ length: 27 }, (_, i) => ({ container: "inventory", slot: i + 9 })),
            ...Array.from({ length: 9 }, (_, i) => ({ container: "inventory", slot: i })),
        ];
    }

    function parseDragPayloadRaw(raw) {
        const text = String(raw || "");
        try {
            const parsed = JSON.parse(text);
            if (parsed && Number.isInteger(parsed.slot)) {
                return {
                    slot: parsed.slot,
                    container: parsed.container || "inventory",
                };
            }
        } catch (_e) {
            const slot = parseInt(text, 10);
            if (Number.isInteger(slot)) return { slot, container: "inventory" };
        }
        return null;
    }

    function moveOrCopyPlan({
        fromContainerName = "inventory",
        fromSlot = null,
        toContainerName = "inventory",
        toSlot = null,
        fromProtected = false,
        toProtected = false,
        hasFromItem = false,
        hasToItem = false,
        fromItemName = "",
        toItemName = "",
        copyMode = false,
    } = {}) {
        if (fromProtected || toProtected) {
            return {
                ok: false,
                reason: "protected_slot",
                protectedSlot: toProtected ? toSlot : fromSlot,
                protectedContainer: toProtected ? toContainerName : fromContainerName,
            };
        }
        if (fromContainerName === toContainerName && fromSlot === toSlot) return { ok: false, reason: "same_slot" };
        if (!hasFromItem && !hasToItem) return { ok: false, reason: "empty_pair" };
        // Ausrüstungsslots akzeptieren nur tatsächlich tragbare Items.
        const rules = window.MCBEEquipmentRules;
        if (rules) {
            if (hasFromItem && rules.isEquipmentSlot(toSlot, toContainerName) && !rules.itemAllowedInEquipmentSlot(toSlot, fromItemName)) {
                return { ok: false, reason: "not_wearable", slot: toSlot, itemName: fromItemName };
            }
            // Beim Verschieben/Tauschen wandert das Ziel-Item zurück in den Quellslot.
            if (!copyMode && hasToItem && rules.isEquipmentSlot(fromSlot, fromContainerName) && !rules.itemAllowedInEquipmentSlot(fromSlot, toItemName)) {
                return { ok: false, reason: "not_wearable", slot: fromSlot, itemName: toItemName };
            }
        }
        return { ok: true };
    }

    function dragStartPlan({ slotId, containerName = "inventory", protectedKnown = false, hasItem = false } = {}) {
        if (protectedKnown || !hasItem) return { ok: false };
        return {
            ok: true,
            effectAllowed: "copyMove",
            payload: JSON.stringify({ slot: slotId, container: containerName }),
        };
    }

    function dragOverPlan({ protectedKnown = false, copyMode = false } = {}) {
        if (protectedKnown) return { ok: false };
        return {
            ok: true,
            dropEffect: copyMode ? "copy" : "move",
        };
    }

    function dropPlan({ rawPayload = "", toContainerName = "inventory", toSlot = null, copyMode = false } = {}) {
        const payload = parseDragPayloadRaw(rawPayload);
        if (!payload) return { ok: false, reason: "invalid_payload" };
        return {
            ok: true,
            fromContainerName: payload.container || "inventory",
            fromSlot: Number(payload.slot),
            toContainerName,
            toSlot,
            copyMode: Boolean(copyMode),
        };
    }

    function keyboardSlotPlan({
        key = "",
        slotId = null,
        containerName = "inventory",
        hasItem = false,
        protectedKnown = false,
    } = {}) {
        if (key === "Enter" || key === " ") {
            return { ok: true, action: "activate" };
        }
        if (key === "Delete" || key === "Backspace") {
            return hasItem && !protectedKnown
                ? { ok: true, action: "clear" }
                : { ok: false, action: "clear", reason: protectedKnown ? "protected_slot" : "empty_slot" };
        }
        if (!Object.prototype.hasOwnProperty.call(ARROW_DELTAS, key)) return { ok: false, action: "noop" };

        const order = slotOrderForKeyboard(containerName);
        const idx = order.findIndex(entry => entry.container === containerName && entry.slot === slotId);
        if (idx < 0) return { ok: false, action: "navigate", reason: "missing_slot" };

        let next = idx + ARROW_DELTAS[key];
        if (next < 0) next = 0;
        if (next >= order.length) next = order.length - 1;
        return { ok: true, action: "navigate", target: order[next] };
    }

    window.MCBESlotInteractionLogic = {
        dragOverPlan,
        dragStartPlan,
        dropPlan,
        keyboardSlotPlan,
        moveOrCopyPlan,
        parseDragPayloadRaw,
        slotOrderForKeyboard,
    };
}());
