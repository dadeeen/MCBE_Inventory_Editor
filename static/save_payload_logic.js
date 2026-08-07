(function () {
    "use strict";

    const STATS_PAYLOAD_KEYS = ["pos", "dimension_id", "health", "xp_level", "xp_progress", "food_level", "food_saturation"];
    const STRIPPED_ITEM_FIELDS = new Set([
        "protected_nbt_summary",
        "preserved_nbt_summary",
        "nbt_view",
        "protected_nbt_dropped",
        "previous_name",
        "special_nbt_defaulted",
        "special_nbt_requirement",
        "item_tag_opaque",
        // root_equipment_read_only wird bewusst NICHT gestrippt: Echo-Items in
        // Root-Slots sind vor dem Strippen bereits gefiltert; erreicht das Flag
        // das Backend, ist es eine verirrte Kopie, die dort abgelehnt wird.
        "root_equipment_source_tag",
        "root_equipment_source_index",
    ]);
    const READ_ONLY_ROOT_EQUIPMENT_CONTAINERS = new Set(["armor", "offhand"]);
    const ROOT_EQUIPMENT_SLOTS = new Set([100, 101, 102, 103, -106]);

    function cloneJson(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function hasMeaningfulObjectKeys(obj) {
        return Boolean(obj && typeof obj === "object" && Object.keys(obj).some(key => key !== "_opaque"));
    }

    function valuesEqualForSave(a, b) {
        if (Array.isArray(a) || Array.isArray(b)) {
            if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
            return a.every((value, idx) => Number(value) === Number(b[idx]));
        }
        return Number.isFinite(Number(a)) || Number.isFinite(Number(b))
            ? Number(a) === Number(b)
            : JSON.stringify(a) === JSON.stringify(b);
    }

    function vanillaDimensionId(value) {
        if (value === null || value === undefined || typeof value === "boolean") return null;
        if (typeof value === "string" && value.trim() === "") return null;
        const parsed = Number(value);
        return Number.isInteger(parsed) && [0, 1, 2].includes(parsed) ? parsed : null;
    }

    function payloadContainsUserChanges(payload) {
        if (!payload || typeof payload !== "object") return false;
        if (Object.prototype.hasOwnProperty.call(payload, "inventory")) return true;
        if (Object.prototype.hasOwnProperty.call(payload, "ender_chest")) return true;
        if (Object.prototype.hasOwnProperty.call(payload, "effects")) return true;
        if (Object.prototype.hasOwnProperty.call(payload, "abilities")) return true;
        return Boolean(payload.stats && typeof payload.stats === "object" && Object.keys(payload.stats).length > 0);
    }

    function isReadOnlyRootEquipmentItem(item) {
        if (!item || typeof item !== "object") return false;
        if (item.root_equipment_read_only === true) return true;
        return READ_ONLY_ROOT_EQUIPMENT_CONTAINERS.has(String(item.source_container || ""));
    }

    // Nur das normale Echo der read-only Fallbacks in ihren Root-Slots wird
    // still aus dem Payload gefiltert. Eine verirrte Kopie in einem anderen
    // Slot wird mitgesendet, damit das Backend sie mit klarem Fehler ablehnt
    // statt sie stumm verschwinden zu lassen.
    function isEchoedRootEquipmentItem(item) {
        return isReadOnlyRootEquipmentItem(item) && ROOT_EQUIPMENT_SLOTS.has(Number(item.slot));
    }

    function createSavePayloadLogic(deps) {
        const {
            collectAbilitiesFromUI,
            getAbilitiesTouched,
            getCleanSnapshot,
            getCurrentPlayerKey,
            getCurrentPlayerRevision,
            getEnderChestInventory,
            getEffectsTouched,
            getInventory,
            getPlayerAbilities,
            getPlayerEffects,
            getPlayerStats,
            getProtectedNbt,
            getServerGuardEpoch,
            getServerGuardToken = () => "",
            getWorldPath,
            getWorldPresenceSessionId,
            itemIsVisiblePresent,
            itemRequiresOriginalNbt,
            removeProtectedStatsFromPayload,
            sectionChanged,
            setPlayerAbilities,
            syncEffectsFromUI,
        } = deps;

        function shouldSyncAbilitiesFromUIForSave() {
            const protectedNbt = getProtectedNbt() || {};
            const playerAbilities = getPlayerAbilities() || {};
            if (protectedNbt.abilities_opaque === true || playerAbilities?._opaque === true) return false;
            return Boolean(getAbilitiesTouched());
        }

        function syncPendingEditorStateForSave() {
            const protectedNbt = getProtectedNbt() || {};
            const playerEffects = getPlayerEffects();
            if (!protectedNbt.active_effects_opaque && (getEffectsTouched() || protectedNbt.has_active_effects_tag === true || Array.isArray(playerEffects) && playerEffects.length > 0)) {
                syncEffectsFromUI();
            }
            let collectedAbilities = null;
            if (shouldSyncAbilitiesFromUIForSave()) {
                collectedAbilities = collectAbilitiesFromUI();
                if (collectedAbilities !== null) {
                    setPlayerAbilities(collectedAbilities);
                }
            }
            return collectedAbilities;
        }

        function buildChangedStatsPayload() {
            const before = getCleanSnapshot()?.stats || {};
            const current = getPlayerStats() || {};
            const statsPayload = {};
            const positionChanged = Object.prototype.hasOwnProperty.call(current, "pos")
                && !valuesEqualForSave(current.pos, before.pos);
            const currentDimensionId = vanillaDimensionId(current.dimension_id);
            const beforeDimensionId = vanillaDimensionId(before.dimension_id);
            const dimensionChanged = Object.prototype.hasOwnProperty.call(current, "dimension_id")
                && currentDimensionId !== null
                && currentDimensionId !== beforeDimensionId;
            STATS_PAYLOAD_KEYS.forEach(key => {
                if (key === "dimension_id") {
                    if (dimensionChanged) statsPayload.dimension_id = currentDimensionId;
                    return;
                }
                if (Object.prototype.hasOwnProperty.call(current, key) && !valuesEqualForSave(current[key], before[key])) {
                    statsPayload[key] = cloneJson(current[key]);
                }
            });
            if (positionChanged || dimensionChanged) {
                // A player location is DimensionId + Pos. Include both known
                // components so a dimension switch cannot be written with an
                // implicit/default position and a position edit keeps its
                // authoritative dimension context.
                if (Array.isArray(current.pos) && current.pos.length === 3) {
                    statsPayload.pos = cloneJson(current.pos);
                }
                if (currentDimensionId !== null) {
                    statsPayload.dimension_id = currentDimensionId;
                }
            }
            return removeProtectedStatsFromPayload(statsPayload);
        }

        function cleanSnapshotMapForContainer(containerName) {
            const cleanSnapshot = getCleanSnapshot();
            if (!cleanSnapshot) return {};
            return containerName === "ender_chest" ? (cleanSnapshot.ec || {}) : (cleanSnapshot.inv || {});
        }

        function itemMatchesProtectedSource(item, candidate) {
            if (!itemIsVisiblePresent(item) || !itemIsVisiblePresent(candidate)) return false;
            if (item.name !== candidate.name) return false;
            const itemDigest = String(item.source_item_digest || "").trim().toLowerCase();
            const candidateDigest = String(candidate.source_item_digest || "").trim().toLowerCase();
            if (itemDigest || candidateDigest) {
                return Boolean(itemDigest && candidateDigest && itemDigest === candidateDigest);
            }
            const itemNbt = item.nbt_view ? JSON.stringify(item.nbt_view) : "";
            const candidateNbt = candidate.nbt_view ? JSON.stringify(candidate.nbt_view) : "";
            if (itemNbt && candidateNbt) return itemNbt === candidateNbt;
            return itemRequiresOriginalNbt(candidate);
        }

        function findCleanProtectedSource(item) {
            const cleanSnapshot = getCleanSnapshot();
            if (!cleanSnapshot || !itemRequiresOriginalNbt(item)) return null;
            const containers = [
                ["inventory", cleanSnapshot.inv || {}],
                ["ender_chest", cleanSnapshot.ec || {}],
            ];
            const matches = [];
            containers.forEach(([containerName, sourceMap]) => {
                Object.entries(sourceMap || {}).forEach(([slotKey, candidate]) => {
                    if (itemMatchesProtectedSource(item, candidate)) matches.push({ containerName, slotId: Number(slotKey), candidate });
                });
            });
            if (!matches.length) return null;
            const strongMatches = matches.filter(match => item.nbt_view && match.candidate?.nbt_view && JSON.stringify(item.nbt_view) === JSON.stringify(match.candidate.nbt_view));
            const usableMatches = strongMatches.length ? strongMatches : matches;
            if (usableMatches.length !== 1) return null;
            return usableMatches[0];
        }

        function repairProtectedItemSourceForPayload(item, containerName) {
            if (!item || typeof item !== "object" || !itemRequiresOriginalNbt(item)) return item;
            const repaired = { ...item };
            const currentPlayerKey = getCurrentPlayerKey();
            const worldPath = getWorldPath();
            if (repaired.source_player_key && repaired.source_player_key !== currentPlayerKey) return repaired;
            if (repaired.source_world_path && worldPath && repaired.source_world_path !== worldPath) return repaired;
            const sourceContainer = repaired.source_container || containerName;
            const sourceSlot = Number(repaired.source_slot);
            const sourceMap = cleanSnapshotMapForContainer(sourceContainer);
            const currentSource = Number.isInteger(sourceSlot) ? sourceMap[sourceSlot] : null;
            if (itemMatchesProtectedSource(repaired, currentSource)) return repaired;

            const found = findCleanProtectedSource(repaired);
            if (!found) return repaired;
            repaired.source_container = found.containerName;
            repaired.source_slot = found.slotId;
            repaired.source_player_key = currentPlayerKey;
            repaired.source_world_path = worldPath;
            return repaired;
        }

        function itemForSavePayload(item, containerName) {
            if (!item || typeof item !== "object") return item;
            const repaired = repairProtectedItemSourceForPayload(item, containerName);
            return Object.fromEntries(Object.entries(repaired).filter(([key]) => !STRIPPED_ITEM_FIELDS.has(key)));
        }

        function buildSavePayload() {
            const collectedAbilities = syncPendingEditorStateForSave();
            const inventory = getInventory();
            const enderChestInventory = getEnderChestInventory();
            const playerEffects = getPlayerEffects();
            const playerAbilities = getPlayerAbilities();
            const invList = Object.values(inventory)
                .filter(item => !isEchoedRootEquipmentItem(item))
                .map(item => itemForSavePayload(item, "inventory"));
            const ecList = Object.values(enderChestInventory).map(item => itemForSavePayload(item, "ender_chest"));
            const statsPayload = buildChangedStatsPayload();
            const before = getCleanSnapshot() || null;
            const inventoryChanged = !before || sectionChanged(before.inv, inventory);
            const enderChestChanged = !before || sectionChanged(before.ec, enderChestInventory);
            const effectsChanged = !before || sectionChanged(before.effects, playerEffects);
            const abilitiesChanged = !before || sectionChanged(before.abilities, playerAbilities);
            const payload = {
                world_path: getWorldPath(),
                player_key: getCurrentPlayerKey(),
                session_id: getWorldPresenceSessionId(),
                base_revision: getCurrentPlayerRevision(),
                server_guard_epoch: getServerGuardEpoch(),
                server_guard_token: getServerGuardToken(),
                stats: statsPayload
            };

            if (inventoryChanged) {
                payload.inventory = invList;
                // Signalisiert dem Backend, dass dieser Client editierbare
                // Root-Ausrüstungslisten kennt und Items in den Slots
                // 100-103/-106 mitsendet. Nur dann darf ein fehlendes
                // Ausrüstungs-Item als bewusstes Leeren interpretiert werden.
                payload.root_equipment_editable = true;
            }
            if (enderChestChanged) {
                payload.ender_chest = ecList;
            }
            if (effectsChanged && !(getProtectedNbt() || {}).active_effects_opaque) {
                payload.effects = playerEffects;
            }
            if (abilitiesChanged && collectedAbilities !== null) {
                payload.abilities = playerAbilities;
            }
            return payload;
        }

        return {
            buildChangedStatsPayload,
            buildSavePayload,
            cleanSnapshotMapForContainer,
            findCleanProtectedSource,
            hasMeaningfulObjectKeys,
            itemMatchesProtectedSource,
            payloadContainsUserChanges,
            repairProtectedItemSourceForPayload,
            shouldSyncAbilitiesFromUIForSave,
            syncPendingEditorStateForSave,
            valuesEqualForSave,
        };
    }

    window.MCBESavePayloadLogic = {
        createSavePayloadLogic,
        hasMeaningfulObjectKeys,
        isEchoedRootEquipmentItem,
        isReadOnlyRootEquipmentItem,
        payloadContainsUserChanges,
        valuesEqualForSave,
    };
}());
