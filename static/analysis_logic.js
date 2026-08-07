(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function createAnalysisLogic(deps) {
        const {
            appConfig,
            currentPlayerLabel,
            firstEmptyWritableSlot,
            getCurrentCompatibility,
            getEnderChestInventory,
            getHasEnderChest,
            getHiddenUnknownSlots,
            getInventory,
            getPlayers,
            getProtectedNbt,
            getProtectedKnownSlots,
            getSelectedWorld,
            getWorldName,
            getWorldPath,
            inventorySlotCount,
            enderChestSlotCount,
            isKnownItemId,
            itemIsVisiblePresent,
            itemHasRepairableDamage = null,
            maxDamage,
            protectedAbilityFields,
            protectedStatFields,
            getCreateRequiresConfirmation,
        } = deps;

        function hasRepairableDamage(item) {
            if (typeof itemHasRepairableDamage === "function") return itemHasRepairableDamage(item);
            return itemIsVisiblePresent(item) && Number(item.damage || 0) > 0 && maxDamage()[item.name] !== undefined;
        }

        function getInventoryStatsForMap(map) {
            const values = Object.values(map || {}).filter(itemIsVisiblePresent);
            let damaged = 0;
            let unknown = 0;
            let enchantments = 0;
            values.forEach(item => {
                if (hasRepairableDamage(item)) damaged += 1;
                if (item.name && !isKnownItemId(item.name)) unknown += 1;
                if (Array.isArray(item.enchantments) && item.enchantments.length) enchantments += 1;
            });
            return { used: values.length, damaged, unknown, enchantments };
        }

        function currentCompatibilityWarnings() {
            const currentCompatibility = getCurrentCompatibility();
            const playerWarnings = Array.isArray(currentCompatibility?.player?.warnings) ? currentCompatibility.player.warnings : [];
            const worldWarnings = Array.isArray(currentCompatibility?.world?.warnings) ? currentCompatibility.world.warnings : [];
            return playerWarnings.concat(worldWarnings).filter(Boolean);
        }

        function currentCompatibilityNotes() {
            const currentCompatibility = getCurrentCompatibility();
            const playerNotes = Array.isArray(currentCompatibility?.player?.notes) ? currentCompatibility.player.notes : [];
            const worldNotes = Array.isArray(currentCompatibility?.world?.notes) ? currentCompatibility.world.notes : [];
            return playerNotes.concat(worldNotes).filter(Boolean);
        }

        function currentUnknownItemCount() {
            const playerCompat = getCurrentCompatibility()?.player || {};
            return Number(playerCompat.unknown_item_ids?.inventory || 0) + Number(playerCompat.unknown_item_ids?.ender_chest || 0);
        }

        function currentProtectedSlotCount() {
            const hiddenUnknownSlots = getHiddenUnknownSlots();
            return Number(hiddenUnknownSlots?.inventory || 0)
                + Number(hiddenUnknownSlots?.ender_chest || 0)
                + Number(hiddenUnknownSlots?.inventory_protected_known || 0)
                + Number(hiddenUnknownSlots?.ender_chest_protected_known || 0);
        }

        function currentLoadProtectionMessages() {
            const hiddenUnknownSlots = getHiddenUnknownSlots();
            const protectedNbt = getProtectedNbt();
            const createFlags = getCreateRequiresConfirmation();
            const messages = currentCompatibilityWarnings().slice();
            if (hiddenUnknownSlots.inventory) messages.push(t("{count} unbekannte Inventar-Slot(s)", { count: hiddenUnknownSlots.inventory }));
            if (hiddenUnknownSlots.ender_chest) messages.push(t("{count} unbekannte Enderchest-Slot(s)", { count: hiddenUnknownSlots.ender_chest }));
            if (hiddenUnknownSlots.inventory_protected_known) messages.push(t("{count} nicht darstellbare Inventar-Einträge in bekannten Slots", { count: hiddenUnknownSlots.inventory_protected_known }));
            if (hiddenUnknownSlots.ender_chest_protected_known) messages.push(t("{count} nicht darstellbare Enderchest-Einträge in bekannten Slots", { count: hiddenUnknownSlots.ender_chest_protected_known }));
            if (hiddenUnknownSlots.inventory_opaque || protectedNbt.inventory_opaque) messages.push(t("Inventar-Tag mit unbekanntem Typ"));
            if (createFlags.inventory) messages.push(t("kein Inventory-Tag vorhanden; neues Inventar nur mit expliziter Bestätigung"));
            if (hiddenUnknownSlots.ender_chest_opaque || protectedNbt.ender_chest_opaque) messages.push(t("Enderchest-Tag mit unbekanntem Typ"));
            if (protectedNbt.active_effects_opaque) messages.push(t("Effektliste mit unbekanntem Typ"));
            if (protectedNbt.active_effect_entries_opaque) messages.push(t("{count} Effekt-Eintrag/Einträge mit geschützten Feldtypen", { count: protectedNbt.active_effect_entries_opaque }));
            if (protectedNbt.abilities_opaque) messages.push(t("Fähigkeiten-Tag mit unbekanntem Typ"));
            const abilityOpaqueFields = Object.values(protectedAbilityFields());
            if (abilityOpaqueFields.length) messages.push(t("geschützte Fähigkeiten-Tags ({fields})", { fields: abilityOpaqueFields.join(", ") }));
            if (protectedNbt.pos_opaque) messages.push(t("Positions-Tag mit unbekanntem Typ"));
            const statOpaqueFields = Object.values(protectedStatFields());
            if (statOpaqueFields.length) messages.push(t("geschützte Statistik-Tags ({fields})", { fields: statOpaqueFields.join(", ") }));
            const rootListLabels = {
                Armor: "Armor",
                Offhand: "Offhand",
                Mainhand: "Mainhand",
                PlayerUIItems: "PlayerUIItems",
            };
            const rootListsPresent = protectedNbt.root_item_lists_present && typeof protectedNbt.root_item_lists_present === "object"
                ? protectedNbt.root_item_lists_present
                : {};
            Object.entries(rootListsPresent).forEach(([tagName, count]) => {
                const safeCount = Number(count || 0);
                if (safeCount > 0) messages.push(t("{count} Eintrag/Einträge in separater {tag}-Root-Liste werden geschützt erhalten", { count: safeCount, tag: rootListLabels[tagName] || tagName }));
            });
            const rootListsOpaque = protectedNbt.root_item_lists_opaque && typeof protectedNbt.root_item_lists_opaque === "object"
                ? Object.keys(protectedNbt.root_item_lists_opaque)
                : [];
            if (rootListsOpaque.length) messages.push(t("geschützte Root-Item-Listen ({fields})", { fields: rootListsOpaque.join(", ") }));
            return messages.filter(Boolean);
        }

        function compatibilitySummaryText() {
            const messages = currentLoadProtectionMessages();
            if (!messages.length) return "";
            const createFlags = getCreateRequiresConfirmation();
            const parts = [];
            const unknownItems = currentUnknownItemCount();
            const protectedSlots = currentProtectedSlotCount();
            if (unknownItems) parts.push(t("{count} unbekannte Item-ID(s)", { count: unknownItems }));
            if (protectedSlots) parts.push(t("{count} geschützte Slot(s)", { count: protectedSlots }));
            if (createFlags.inventory) parts.push(t("Inventar-Anlage braucht Bestätigung"));
            if (createFlags.enderChest) parts.push(t("Enderchest-Anlage braucht Bestätigung"));
            if (!parts.length) parts.push(t("{count} Kompatibilitätshinweis(e)", { count: messages.length }));
            else if (messages.length > parts.length && parts.length < 3) parts.push(t("{count} Hinweise gesamt", { count: messages.length }));
            return parts.slice(0, 3).join(" · ");
        }

        function playerLoadStatusMessage() {
            const summary = compatibilitySummaryText();
            if (!summary) return t("{player} geladen", { player: currentPlayerLabel() });
            return t("{player} geladen. {summary}. Details unter Spieler > Analyse.", { player: currentPlayerLabel(), summary });
        }

        function buildInventorySummary() {
            const inventory = getInventory();
            const enderChestInventory = getEnderChestInventory();
            const inventoryRange = Array.from({ length: inventorySlotCount }, (_, i) => i);
            const enderRange = Array.from({ length: enderChestSlotCount }, (_, i) => i);
            const inventoryItems = inventoryRange.map(slot => inventory[slot]).filter(itemIsVisiblePresent);
            const enderItems = enderRange.map(slot => enderChestInventory[slot]).filter(itemIsVisiblePresent);
            const equipmentSlots = [103, 102, 101, 100, -106];
            const equipmentUsed = equipmentSlots.map(slot => inventory[slot]).filter(itemIsVisiblePresent).length;
            const protectedKnownSlots = getProtectedKnownSlots();
            const hiddenUnknownSlots = getHiddenUnknownSlots();
            const protectedInventory = Array.isArray(protectedKnownSlots?.inventory) ? protectedKnownSlots.inventory.length : 0;
            const protectedEnder = Array.isArray(protectedKnownSlots?.ender_chest) ? protectedKnownSlots.ender_chest.length : 0;
            const hiddenInventory = Number(hiddenUnknownSlots?.inventory || 0) + Number(hiddenUnknownSlots?.inventory_protected_known || 0);
            const hiddenEnder = Number(hiddenUnknownSlots?.ender_chest || 0) + Number(hiddenUnknownSlots?.ender_chest_protected_known || 0);
            const allVisibleItems = Object.values(inventory || {}).concat(Object.values(enderChestInventory || {})).filter(itemIsVisiblePresent);
            const damaged = allVisibleItems.filter(hasRepairableDamage).length;
            return {
                inventoryUsed: inventoryItems.length,
                inventoryTotal: inventorySlotCount,
                enderUsed: enderItems.length,
                enderTotal: enderChestSlotCount,
                equipmentUsed,
                equipmentTotal: equipmentSlots.length,
                protectedCount: protectedInventory + protectedEnder + hiddenInventory + hiddenEnder,
                damaged,
                firstFreeInventorySlot: firstEmptyWritableSlot("inventory"),
                firstFreeEnderSlot: firstEmptyWritableSlot("ender_chest"),
            };
        }

        function buildWorldAnalysis() {
            const players = getPlayers();
            const currentCompatibility = getCurrentCompatibility();
            const editablePlayers = players.filter(p => p.editable).length;
            const exportOnlyPlayers = players.filter(p => p.exportable && !p.editable).length;
            const compatWarnings = (currentCompatibility?.player?.warnings || []).concat(currentCompatibility?.world?.warnings || []);
            const compatErrors = (currentCompatibility?.player?.errors || []).concat(currentCompatibility?.world?.errors || []);
            return {
                world: getWorldName() || getSelectedWorld()?.name || getWorldPath() || t("Keine Welt geladen"),
                player: currentPlayerLabel ? currentPlayerLabel() : t("Kein Spieler geladen"),
                players_total: players.length,
                players_editable: editablePlayers,
                players_export_only: exportOnlyPlayers,
                inventory: getInventoryStatsForMap(getInventory()),
                ender: getInventoryStatsForMap(getEnderChestInventory()),
                hidden: getHiddenUnknownSlots() || {},
                compat_warnings: compatWarnings,
                compat_notes: currentCompatibilityNotes(),
                compat_errors: compatErrors,
                has_ender_chest: getHasEnderChest(),
            };
        }

        function worldAnalysisText() {
            const a = buildWorldAnalysis();
            const lines = [
                t("MCBE Inventory Editor - Weltanalyse"),
                `Version: ${appConfig?.distribution?.project_version || "dev"}`,
                t("Modus: {mode}", { mode: appConfig?.mode || t("unbekannt") }),
                t("Welt: {world}", { world: a.world }),
                t("Spieler: {total} gesamt, {editable} editierbar, {exportOnly} nur Export", { total: a.players_total, editable: a.players_editable, exportOnly: a.players_export_only }),
                t("Aktueller Spieler: {player}", { player: a.player }),
                t("Inventar: {used}/{total} belegt, {damaged} beschädigt, {unknown} unbekannt", { used: a.inventory.used, total: inventorySlotCount, damaged: a.inventory.damaged, unknown: a.inventory.unknown }),
                t("Enderchest: {used}/{total} belegt, {tag}", { used: a.ender.used, total: enderChestSlotCount, tag: a.has_ender_chest ? t("Tag vorhanden") : t("Tag noch nicht angelegt") }),
                t("Verzauberte Items: {count}", { count: a.inventory.enchantments + a.ender.enchantments }),
                t("Geschützte/unknown Einträge: Inventar {inv}, Enderchest {ec}", { inv: a.hidden.inventory || 0, ec: a.hidden.ender_chest || 0 }),
            ];
            if (a.compat_errors.length) lines.push(t("Blockierende Kompatibilitätsfehler: {list}", { list: a.compat_errors.join(" | ") }));
            if (a.compat_warnings.length) lines.push(t("Kompatibilitätswarnungen: {list}", { list: a.compat_warnings.join(" | ") }));
            if (a.compat_notes.length) lines.push(t("Erhaltene Zusatzdaten: {list}", { list: a.compat_notes.join(" | ") }));
            return lines.join("\n");
        }

        return {
            buildInventorySummary,
            buildWorldAnalysis,
            compatibilitySummaryText,
            currentCompatibilityNotes,
            currentCompatibilityWarnings,
            currentLoadProtectionMessages,
            currentProtectedSlotCount,
            currentUnknownItemCount,
            getInventoryStatsForMap,
            playerLoadStatusMessage,
            worldAnalysisText,
        };
    }

    window.MCBEAnalysisLogic = {
        createAnalysisLogic,
    };
}());
