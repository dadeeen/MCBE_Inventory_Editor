(function () {
    "use strict";

    const MAX_TREE_NODES = 2048;
    const MAX_TREE_DEPTH = 32;
    const ARRAY_ELEMENT_TYPES = {
        ByteArrayTag: "ByteTag",
        IntArrayTag: "IntTag",
        LongArrayTag: "LongTag",
    };
    const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
    const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);

    function normalizedWorldPath(value) {
        return typeof value === "string" ? value.trim().replace(/\\/g, "/").replace(/\/+$/, "") : "";
    }

    function contextMatches(item, worldPath, playerKey) {
        return normalizedWorldPath(item.source_world_path) === worldPath
            && item.source_player_key === playerKey
            && item.origin_world_mismatch !== true
            && item.replace_original_nbt !== true;
    }

    function equalNbtViews(left, right) {
        if (!isObject(left) || !isObject(right)) return false;
        try {
            return JSON.stringify(left) === JSON.stringify(right);
        } catch (_error) {
            return false;
        }
    }

    // The clean snapshot is authoritative. A matching item name alone cannot
    // distinguish a newly created item from the former occupant of a slot.
    function resolveOriginal({ item, containerName = "inventory", cleanSnapshot, worldPath, playerKey } = {}) {
        const currentWorld = normalizedWorldPath(worldPath);
        if (!isObject(item) || !isObject(cleanSnapshot) || !currentWorld || typeof playerKey !== "string" || !playerKey) return null;
        if (typeof item.name !== "string" || !item.name) return null;
        if (!["inventory", "ender_chest"].includes(containerName)) return null;
        if (!contextMatches(item, currentWorld, playerKey)) return null;
        const sourceContainer = item.source_container;
        const sourceSlot = item.source_slot;
        if (!Number.isInteger(sourceSlot)) return null;
        const rootEquipment = sourceContainer === "armor" || sourceContainer === "offhand";
        if (rootEquipment) {
            const validSlot = sourceContainer === "armor" ? [100, 101, 102, 103].includes(sourceSlot) : sourceSlot === -106;
            if (!validSlot || containerName !== "inventory" || item.slot !== sourceSlot || item.root_equipment_read_only !== true) return null;
        } else if (!["inventory", "ender_chest"].includes(sourceContainer)) {
            return null;
        }
        const sourceMap = sourceContainer === "ender_chest" ? cleanSnapshot.ec : cleanSnapshot.inv;
        if (!isObject(sourceMap) || !hasOwn(sourceMap, sourceSlot)) return null;
        const candidate = sourceMap[sourceSlot];
        if (!isObject(candidate) || !isObject(candidate.nbt_view) || candidate.name !== item.name || candidate.slot !== sourceSlot) return null;
        if (!contextMatches(candidate, currentWorld, playerKey)
            || candidate.source_container !== sourceContainer || candidate.source_slot !== sourceSlot) return null;
        if (rootEquipment && candidate.root_equipment_read_only !== true) return null;

        const itemDigest = typeof item.source_item_digest === "string" ? item.source_item_digest.trim().toLowerCase() : "";
        const candidateDigest = typeof candidate.source_item_digest === "string" ? candidate.source_item_digest.trim().toLowerCase() : "";
        if (itemDigest || candidateDigest) {
            if (!/^[0-9a-f]{64}$/.test(itemDigest) || itemDigest !== candidateDigest) return null;
        } else if (!equalNbtViews(item.nbt_view, candidate.nbt_view)) {
            return null;
        }
        return { item: candidate, containerName: sourceContainer, slotId: sourceSlot };
    }

    function childPath(parent, key, array = false) {
        if (array) return `${parent}[${key}]`;
        return /^[A-Za-z_$][\w$]*$/.test(key) ? `${parent}.${key}` : `${parent}[${JSON.stringify(key)}]`;
    }

    function hasTruncation(tag) {
        return Boolean(tag?.truncation || tag?.truncated || tag?.partial === true);
    }

    function flattenTree(nbtView) {
        if (!isObject(nbtView)) return [];
        const nodes = [];
        const ancestors = new Set();

        function visit(tag, key, id, parent, depth, elementType = "") {
            if (nodes.length >= MAX_TREE_NODES) {
                if (parent) parent.partial = true;
                return false;
            }
            const typed = isObject(tag) && typeof tag.type === "string" && hasOwn(tag, "value");
            const type = typed ? tag.type : elementType || "UnknownTag";
            const value = typed ? tag.value : tag;
            const compound = type === "CompoundTag" && isObject(value);
            const sequence = (type === "ListTag" || hasOwn(ARRAY_ELEMENT_TYPES, type)) && Array.isArray(value);
            const container = compound || sequence;
            const malformed = (!typed && !elementType) || (elementType && (isObject(tag) || Array.isArray(tag))) || (type === "CompoundTag" && !compound)
                || ((type === "ListTag" || hasOwn(ARRAY_ELEMENT_TYPES, type)) && !sequence);
            const node = {
                id, parentId: parent?.id ?? null, depth, key: String(key), type, value,
                children: false,
                partial: hasTruncation(tag) || malformed,
            };
            if (typed && type === "ListTag" && Number.isInteger(tag.list_type_id)) node.listTypeId = tag.list_type_id;
            nodes.push(node);
            if (!container) return true;

            const entries = compound ? Object.keys(value) : null;
            node.count = compound ? entries.length : value.length;
            const reportedTotal = typed ? tag.truncation?.total : undefined;
            if (Number.isSafeInteger(reportedTotal) && reportedTotal >= node.count) node.totalCount = reportedTotal;
            if (depth >= MAX_TREE_DEPTH || ancestors.has(value)) {
                node.partial = node.count > 0 || node.partial;
                return true;
            }
            ancestors.add(value);
            for (let index = 0; index < node.count; index += 1) {
                const childKey = compound ? entries[index] : index;
                if (!visit(value[childKey], compound ? childKey : `[${childKey}]`, childPath(id, childKey, sequence), node, depth + 1, ARRAY_ELEMENT_TYPES[type] || "")) break;
                node.children = true;
            }
            ancestors.delete(value);
            return true;
        }

        visit(nbtView, "$", "$", null, 0);
        return nodes;
    }

    function hasPartial(nbtView) {
        return flattenTree(nbtView).some(node => node.partial);
    }

    function nodeValueText(node) {
        if (!node) return "";
        let text;
        if (typeof node.count === "number") {
            text = node.type === "CompoundTag" ? `{${node.count}}` : `[${node.count}]`;
        } else if (node.type === "StringTag" && typeof node.value === "string") {
            text = JSON.stringify(node.value);
        } else if (node.value === null) {
            text = "null";
        } else if (node.value === undefined) {
            text = "—";
        } else if (typeof node.value === "object") {
            text = Array.isArray(node.value) ? "[…]" : "{…}";
        } else {
            text = String(node.value);
        }
        return `${text}${node.partial ? " …" : ""}`;
    }

    window.MCBENbtInspectorModel = {
        flattenTree,
        hasPartial,
        nodeValueText,
        resolveOriginal,
    };
}());
