(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function cloneJson(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function normalizedWorldPath(value) {
        return String(value || "").trim().replace(/\\/g, "/").replace(/\/+$/, "");
    }

    function itemRequiresOriginalNbt(item) {
        return Boolean(item && (
            item.has_preserved_nbt === true
            || item.has_protected_nbt === true
            || item.has_unknown_enchantments === true
        ));
    }

    function cloneItemForSlot(item, slotId, containerName, sourceContainerName = containerName, options = {}) {
        if (!item) return null;
        const cloned = cloneJson(item);
        const originalWorldPath = normalizedWorldPath(cloned.source_world_path);
        let currentWorldPath = "";
        // Keep source provenance atomic. Mixing it with the target slot could
        // make the backend load unrelated NBT.
        if (typeof options.ensureOrigin === "function") {
            const probe = { slot: Number.isInteger(cloned.source_slot) ? cloned.source_slot : cloned.slot };
            options.ensureOrigin(probe, sourceContainerName);
            currentWorldPath = normalizedWorldPath(probe.source_world_path);
            options.ensureOrigin(cloned, sourceContainerName);
        }
        cloned.slot = slotId;
        if (originalWorldPath && currentWorldPath && originalWorldPath !== currentWorldPath) {
            // Clipboard provenance is world-local. Invalidate cross-world
            // entries so addable items are rebuilt and protected items fail closed.
            cloned.origin_world_mismatch = true;
            cloned.source_player_key = "";
            cloned.source_container = "__cross_world__";
            cloned.source_slot = slotId === 0 ? 1 : 0;
        }
        return cloned;
    }

    function cloneSlotItemForClipboard(item, containerName, options = {}) {
        if (!item) return null;
        const cloned = cloneJson(item);
        if (typeof options.ensureOrigin === "function") {
            return options.ensureOrigin(cloned, containerName);
        }
        return cloned;
    }

    function cloneClipboardForTarget(clipboard, slotId, targetContainer, options = {}) {
        if (!clipboard) return null;
        const sourceContainer = clipboard.source_container || targetContainer;
        return cloneItemForSlot(clipboard, slotId, targetContainer, sourceContainer, options);
    }

    function pasteClipboardToTargets(clipboard, targets, options = {}) {
        let changed = 0;
        targets.forEach(({ map, slotId, container }) => {
            map[slotId] = cloneClipboardForTarget(clipboard, slotId, container, options);
            changed += 1;
        });
        return changed;
    }

    function clearTargets(targets) {
        targets.forEach(({ map, slotId }) => {
            delete map[slotId];
        });
        return targets.length;
    }

    function fillTargets(targets, { name, count, damage }) {
        targets.forEach(({ map, slotId }) => {
            map[slotId] = {
                slot: slotId,
                name,
                count,
                damage,
                display_name: "",
                lore: [],
                enchantments: [],
                // Bulk fill means "replace with a newly built base item", even
                // when the occupied slot already contains the same item ID.
                replace_original_nbt: true,
            };
        });
        return targets.length;
    }

    function repairTargets(targets) {
        targets.forEach(({ map, slotId }) => {
            map[slotId].damage = 0;
        });
        return targets.length;
    }

    function selectedBulkTargets({
        selectedSlots = [],
        selectedEnderSlot = -1,
        inventory = {},
        enderChestInventory = {},
        isProtectedKnownSlot = () => false,
    } = {}) {
        const targets = selectedSlots
            .map(slotId => ({ container: "inventory", slotId, map: inventory }))
            .filter(target => !isProtectedKnownSlot(target.slotId, target.container));
        if (selectedEnderSlot >= 0 && !isProtectedKnownSlot(selectedEnderSlot, "ender_chest")) {
            targets.push({ container: "ender_chest", slotId: selectedEnderSlot, map: enderChestInventory });
        }
        return targets;
    }

    function bulkSelectionLabel(count, { selectedEnderSlot = -1 } = {}) {
        const ender = selectedEnderSlot >= 0 ? " inkl. Enderchest" : "";
        return `${t("{count} markierte Slot(s)", { count })}${ender}`;
    }

    function itemHasRepairableDamage(item, maxDamage = {}, isPresent = null) {
        const present = typeof isPresent === "function"
            ? isPresent(item)
            : Boolean(item && item.name && item.name !== "minecraft:air");
        return present && maxDamage[item.name] !== undefined && Number(item.damage || 0) > 0;
    }

    function visibleItemTargets(targets = [], isItemVisiblePresent = () => false) {
        return targets.filter(({ map, slotId }) => isItemVisiblePresent(map?.[slotId]));
    }

    function firstEmptyWritableSlot({
        containerName = "inventory",
        source = {},
        slotCount = 36,
        isProtectedKnownSlot = () => false,
    } = {}) {
        for (let slotId = 0; slotId < slotCount; slotId += 1) {
            if (isProtectedKnownSlot(slotId, containerName)) continue;
            const item = source?.[slotId];
            if (!item || !item.name || item.name === "minecraft:air" || Number(item.count || 0) <= 0) return slotId;
        }
        return null;
    }

    function damagedItemTargets(targets = [], { maxDamage = {}, isItemVisiblePresent = null } = {}) {
        return targets.filter(({ map, slotId }) => itemHasRepairableDamage(map?.[slotId], maxDamage, isItemVisiblePresent));
    }

    function damagedInventoryTargets({ sources = [], maxDamage = {}, isItemVisiblePresent = null } = {}) {
        const targets = [];
        sources.forEach(({ map }) => {
            Object.entries(map || {}).forEach(([slotId, item]) => {
                if (itemHasRepairableDamage(item, maxDamage, isItemVisiblePresent)) targets.push({ map, slotId });
            });
        });
        return targets;
    }

    function setTargetCounts(targets, { desired, getMaxStack = () => 64, maxBedrockStackCount = 127 } = {}) {
        let changed = 0;
        targets.forEach(({ map, slotId }) => {
            const item = map?.[slotId];
            if (!item) return;
            const maxStack = getMaxStack(item.name);
            const upperBound = Math.min(maxStack, maxBedrockStackCount);
            item.count = Math.min(Math.max(desired, 1), upperBound);
            changed += 1;
        });
        return changed;
    }

    function moveOrCopySlotState({
        fromMap,
        toMap,
        fromSlot,
        toSlot,
        fromContainerName,
        toContainerName,
        copyMode = false,
        ensureOrigin,
    }) {
        const fromItem = fromMap?.[fromSlot];
        const toItem = toMap?.[toSlot];
        if (!fromItem && !toItem) return { changed: false };

        const cloneOptions = { ensureOrigin };
        if (copyMode && fromItem) {
            toMap[toSlot] = cloneItemForSlot(fromItem, toSlot, toContainerName, fromContainerName, cloneOptions);
            return { changed: true, action: "copy" };
        }

        if (fromItem) {
            toMap[toSlot] = cloneItemForSlot(fromItem, toSlot, toContainerName, fromContainerName, cloneOptions);
        } else {
            delete toMap[toSlot];
        }

        if (toItem) {
            fromMap[fromSlot] = cloneItemForSlot(toItem, fromSlot, fromContainerName, toContainerName, cloneOptions);
        } else {
            delete fromMap[fromSlot];
        }

        return { changed: true, action: "move_or_swap" };
    }


    function createInventoryOriginController({
        getWorldPath = () => "",
        getCurrentPlayerKey = () => "",
        getInventory = () => ({}),
        getEnderChestInventory = () => ({}),
        getProtectedKnownSlots = () => ({ inventory: [], ender_chest: [] }),
        setProtectedKnownSlots = () => {},
    } = {}) {
        function ensureItemOrigin(item, containerName = "inventory") {
            if (!item) return item;
            if (!Number.isInteger(item.source_slot) && Number.isInteger(item.slot)) item.source_slot = item.slot;
            if (!item.source_player_key) item.source_player_key = getCurrentPlayerKey();
            if (!item.source_container) item.source_container = containerName;
            if (!item.source_world_path) item.source_world_path = getWorldPath();
            return item;
        }

        function annotateItemOrigins(items, playerKey, containerName) {
            Object.values(items || {}).forEach(item => {
                if (!item) return;
                if (!Number.isInteger(item.source_slot) && Number.isInteger(item.slot)) item.source_slot = item.slot;
                if (!item.source_player_key) item.source_player_key = playerKey;
                if (!item.source_container) item.source_container = containerName;
                if (!item.source_world_path) item.source_world_path = getWorldPath();
            });
        }

        function protectedSlotList(containerName) {
            const slots = getProtectedKnownSlots?.() || {};
            return containerName === "ender_chest" ? slots.ender_chest : slots.inventory;
        }

        function isProtectedKnownSlot(slotId, containerName) {
            const list = protectedSlotList(containerName);
            return Array.isArray(list) && list.includes(slotId);
        }

        function updateProtectedKnownSlotsFromMeta(meta) {
            const invSlots = Array.isArray(meta?.inventory_protected_known_slots) ? meta.inventory_protected_known_slots : [];
            const ecSlots = Array.isArray(meta?.ender_chest_protected_known_slots) ? meta.ender_chest_protected_known_slots : [];
            setProtectedKnownSlots({
                inventory: invSlots.map(Number).filter(Number.isInteger),
                ender_chest: ecSlots.map(Number).filter(Number.isInteger),
            });
        }

        function normalizeOriginsToCurrentSavedState(itemSourceDigests = null) {
            const hasDigestMaps = Boolean(
                itemSourceDigests
                && typeof itemSourceDigests === "object"
                && (itemSourceDigests.inventory || itemSourceDigests.ender_chest),
            );
            [
                [getInventory?.() || {}, "inventory"],
                [getEnderChestInventory?.() || {}, "ender_chest"],
            ].forEach(([items, containerName]) => {
                const digestMap = itemSourceDigests?.[containerName] || {};
                Object.entries(items || {}).forEach(([slotKey, item]) => {
                    if (!item) return;
                    const slotId = Number.isInteger(item.slot) ? item.slot : parseInt(slotKey, 10);
                    if (!Number.isInteger(slotId)) return;
                    const readOnlyRootEquipment = item.root_equipment_read_only === true
                        || ["armor", "offhand"].includes(String(item.source_container || ""));
                    if (!readOnlyRootEquipment) {
                        item.slot = slotId;
                        item.source_slot = slotId;
                        item.source_player_key = getCurrentPlayerKey();
                        item.source_container = containerName;
                        item.source_world_path = getWorldPath();
                        delete item.origin_world_mismatch;
                        delete item.replace_original_nbt;
                    }
                    if (hasDigestMaps) {
                        const digest = String(digestMap[String(slotId)] || "").trim().toLowerCase();
                        if (/^[0-9a-f]{64}$/.test(digest)) {
                            item.source_item_digest = digest;
                        } else {
                            delete item.source_item_digest;
                        }
                    }
                });
            });
        }

        return {
            annotateItemOrigins,
            ensureItemOrigin,
            isProtectedKnownSlot,
            normalizeOriginsToCurrentSavedState,
            updateProtectedKnownSlotsFromMeta,
        };
    }

    window.MCBEInventoryState = {
        bulkSelectionLabel,
        clearTargets,
        cloneClipboardForTarget,
        createInventoryOriginController,
        cloneItemForSlot,
        cloneSlotItemForClipboard,
        damagedInventoryTargets,
        damagedItemTargets,
        fillTargets,
        firstEmptyWritableSlot,
        itemRequiresOriginalNbt,
        moveOrCopySlotState,
        pasteClipboardToTargets,
        repairTargets,
        selectedBulkTargets,
        setTargetCounts,
        visibleItemTargets,
    };
}());
