(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const MAX_BEDROCK_STACK_COUNT = 127;

    function cloneJson(value) {
        return JSON.parse(JSON.stringify(value));
    }

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

    function loreLinesFromText(rawLore, { maxLines = 8, maxLineLength = 80 } = {}) {
        const text = String(rawLore ?? "").replace(/\r\n?/g, "\n");
        if (text === "") return [];
        return text
            .split("\n")
            .slice(0, maxLines)
            .map(line => line.length > maxLineLength ? line.slice(0, maxLineLength) : line);
    }

    function dataVariantSelectionPlan({
        itemName = "",
        damageValue = 0,
        variants = [],
        sourceItem = null,
    } = {}) {
        if (!Array.isArray(variants) || variants.length === 0) {
            return { selectedDamage: 0, preserveUnknown: false };
        }
        const damage = Number.parseInt(damageValue, 10);
        const knownDamage = Number.isInteger(damage)
            && variants.some(variant => Number(variant?.damage) === damage);
        const sourceDamage = Number(sourceItem?.damage);
        const preservesExisting = Number.isInteger(damage)
            && normalizedItemName(sourceItem?.name) === normalizedItemName(itemName)
            && Number.isInteger(sourceDamage)
            && sourceDamage === damage
            && typeof sourceItem?.source_item_digest === "string"
            && sourceItem.source_item_digest.length > 0;
        return {
            selectedDamage: knownDamage || preservesExisting
                ? damage
                : Number(variants[0]?.damage) || 0,
            preserveUnknown: !knownDamage && preservesExisting,
        };
    }

    function entityVariantMetadataForItem(previousItem, itemName) {
        if (!previousItem || normalizedItemName(previousItem.name) !== normalizedItemName(itemName)) return null;
        return previousItem.entity_variant || null;
    }

    function stackCountFromForm({
        rawCount = 1,
        maxStack = 64,
        previousItem = null,
        itemName = "",
    } = {}) {
        const legalCount = clampInteger(rawCount, 1, 1, maxStack);
        const requestedCount = clampInteger(rawCount, 1, 1, MAX_BEDROCK_STACK_COUNT);
        const previousCount = Number(previousItem?.count);
        const preservesExistingOverstack = normalizedItemName(previousItem?.name) === normalizedItemName(itemName)
            && Number.isInteger(previousCount)
            && previousCount > maxStack
            && requestedCount === previousCount;
        return preservesExistingOverstack ? previousCount : legalCount;
    }

    function buildDetailItemFromForm({
        slotId,
        containerName = "inventory",
        previousItem = null,
        rawName = "",
        rawCount = 1,
        rawDamage = 0,
        rawCustomName = "",
        rawLore = "",
        enchantments = [],
        currentPlayerKey = "",
        worldPath = "",
        maxStack = 64,
        maxDamage = 0,
        maxDisplayName = 64,
        maxLoreLines = 8,
        maxLoreLineLength = 80,
        isValidItemId = () => true,
        isAddableItemId = () => true,
        isEnchantableItem = () => true,
        isEnchantmentCompatible = () => true,
        enchantmentLabel = id => `ID ${id}`,
        detailItemLabel = value => value,
        itemRequiresOriginalNbt = () => false,
        specialItemNbtRequirement = () => null,
        entityVariantEdit = null,
        entityVariantMetadata = null,
    } = {}) {
        const name = normalizedItemName(rawName);
        const sameItem = Boolean(previousItem && normalizedItemName(previousItem.name) === name);
        if (name && name !== "minecraft:air" && !isValidItemId(name)) {
            return { ok: false, error: t("Ungültige Item-ID. Erwartet wird z. B. minecraft:stone.") };
        }
        if (name && name !== "minecraft:air" && !sameItem && !isAddableItemId(name)) {
            return {
                ok: false,
                error: t("Dieses Item ist kein registriertes Vanilla-Inventaritem und kann nicht neu hinzugefügt werden."),
            };
        }

        const count = stackCountFromForm({
            rawCount,
            maxStack,
            previousItem,
            itemName: name,
        });
        const requestedDamage = Number.parseInt(rawDamage, 10);
        const previousDamage = Number(previousItem?.damage);
        const preservesExistingDamage = sameItem
            && Number.isInteger(requestedDamage)
            && Number.isInteger(previousDamage)
            && requestedDamage === previousDamage;
        const damage = preservesExistingDamage
            ? previousDamage
            : clampInteger(rawDamage, 0, 0, maxDamage);
        // Kein trim(): Führende/abschließende Leerzeichen sind gültige Bedrock-
        // Namensformatierung, genau wie in der Lore darunter. Ein Trim hier würde
        // den Namen jedes unberührten Items beim Speichern still verändern.
        const requestedCustomName = String(rawCustomName ?? "");
        const previousCustomName = sameItem ? String(previousItem?.display_name ?? "") : null;
        const customName = previousCustomName !== null && requestedCustomName === previousCustomName
            ? previousCustomName
            : requestedCustomName.slice(0, maxDisplayName);
        const rawLoreText = String(rawLore ?? "").replace(/\r\n?/g, "\n");
        const previousLore = sameItem && Array.isArray(previousItem.lore)
            ? previousItem.lore.map(line => String(line))
            : null;
        const lore = previousLore && rawLoreText === previousLore.join("\n")
            ? cloneJson(previousLore)
            : loreLinesFromText(rawLoreText, { maxLines: maxLoreLines, maxLineLength: maxLoreLineLength });
        const currentEnchantments = cloneJson(enchantments || []);

        if (!name || name === "minecraft:air" || count <= 0) {
            return { ok: true, item: null };
        }

        const previousEnchantments = previousItem ? (previousItem.enchantments || []) : [];
        const preservesExistingUnusualEnchantments = sameItem
            && JSON.stringify(previousEnchantments) === JSON.stringify(currentEnchantments || []);
        const incompatibleEnchantments = currentEnchantments.filter(e => !isEnchantmentCompatible(e.id, name));
        if (currentEnchantments.length && !isEnchantableItem(name) && !preservesExistingUnusualEnchantments) {
            return {
                ok: false,
                error: t("{item} ist nach Vanilla-Regeln nicht verzauberbar. Entferne die Verzauberungen oder wähle ein verzauberbares Item.", { item: detailItemLabel(name, "", damage) }),
            };
        }
        if (incompatibleEnchantments.length && !preservesExistingUnusualEnchantments) {
            const labels = incompatibleEnchantments
                .map(e => enchantmentLabel(e.id))
                .join(", ");
            return {
                ok: false,
                error: t("Diese Verzauberungen passen nicht zu {item}: {labels}.", { item: detailItemLabel(name, "", damage), labels }),
            };
        }

        const sourceSlot = sameItem
            ? (Number.isInteger(previousItem.source_slot) ? previousItem.source_slot : slotId)
            : slotId;
        const sourcePlayerKey = sameItem && previousItem.source_player_key ? previousItem.source_player_key : currentPlayerKey;
        const sourceContainer = sameItem && previousItem.source_container ? previousItem.source_container : containerName;
        const sourceWorldPath = sameItem && previousItem.source_world_path ? previousItem.source_world_path : worldPath;
        const protectedNbtDropped = Boolean(previousItem && !sameItem && itemRequiresOriginalNbt(previousItem));
        const specialNbtRequirement = specialItemNbtRequirement(name);
        const specialNbtDefaulted = Boolean(specialNbtRequirement && !sameItem);
        const builtItem = {
            slot: slotId,
            source_slot: sourceSlot,
            source_player_key: sourcePlayerKey,
            source_container: sourceContainer,
            source_world_path: sourceWorldPath,
            name,
            count,
            damage,
            display_name: customName,
            lore,
            enchantments: currentEnchantments,
        };

        if (protectedNbtDropped) {
            builtItem.protected_nbt_dropped = true;
            builtItem.previous_name = previousItem.name || "";
        }
        if (sameItem && previousItem) {
            const visibleUnchanged = ["slot", "name", "count", "damage", "display_name"].every(key => previousItem[key] === builtItem[key])
                && JSON.stringify(previousItem.lore || []) === JSON.stringify(builtItem.lore || [])
                && JSON.stringify(previousItem.enchantments || []) === JSON.stringify(builtItem.enchantments || [])
                && !entityVariantEdit;
            [
                "has_protected_nbt",
                "has_preserved_nbt",
                "has_unknown_enchantments",
                "item_tag_opaque",
                "entity_variant",
                "entity_variant_state",
                "protected_nbt_summary",
                "preserved_nbt_summary",
                "source_item_digest",
                "origin_world_mismatch",
                "replace_original_nbt",
            ].forEach(key => {
                if (Object.prototype.hasOwnProperty.call(previousItem, key)) builtItem[key] = previousItem[key];
            });
            if (visibleUnchanged && Object.prototype.hasOwnProperty.call(previousItem, "nbt_view")) builtItem.nbt_view = previousItem.nbt_view;
        }
        if (sameItem && entityVariantEdit) {
            builtItem.entity_variant_edit = cloneJson(entityVariantEdit);
            if (entityVariantMetadata) builtItem.entity_variant = cloneJson(entityVariantMetadata);
        }
        if (specialNbtDefaulted) {
            builtItem.special_nbt_defaulted = true;
            builtItem.special_nbt_requirement = specialNbtRequirement;
        }

        return {
            ok: true,
            item: builtItem,
        };
    }

    function applySingleSlotPlan({
        protectedKnown = false,
        buildResult = { ok: false },
        previousItem = null,
        containerName = "inventory",
    } = {}) {
        if (protectedKnown) return { ok: false, reason: "protected_slot", showProtected: true };
        if (!buildResult.ok) {
            return {
                ok: false,
                reason: "invalid_item",
                toast: {
                    message: buildResult.error || t("Slot konnte nicht übernommen werden."),
                    type: "warning",
                    ms: 4000,
                },
            };
        }
        const nextItem = buildResult.item || null;
        const rules = window.MCBEEquipmentRules;
        if (nextItem && rules && rules.isEquipmentSlot(nextItem.slot, containerName) && !rules.itemAllowedInEquipmentSlot(nextItem.slot, nextItem.name)) {
            return {
                ok: false,
                reason: "not_wearable",
                toast: {
                    message: rules.notWearableMessage(nextItem.slot, nextItem.name),
                    type: "warning",
                    ms: 4000,
                },
            };
        }
        if (JSON.stringify(previousItem || null) === JSON.stringify(nextItem)) {
            return { ok: false, reason: "unchanged", refreshQuickActions: true };
        }
        return {
            ok: true,
            operation: nextItem ? "set" : "clear",
            item: nextItem,
            requiresUndo: true,
        };
    }

    function quickClearSlotPlan({
        hasTarget = false,
        protectedKnown = false,
        rawName = "",
    } = {}) {
        if (!hasTarget) return { ok: false, reason: "no_target" };
        if (protectedKnown) return { ok: false, reason: "protected_slot", showProtected: true };
        const name = normalizedItemName(rawName);
        if (!name || name === "minecraft:air") return { ok: false, reason: "empty_slot", refreshQuickActions: true };
        return { ok: true, requiresUndo: true };
    }

    function quickMaxStackPlan({
        hasTarget = false,
        rawName = "",
        maxStack = 64,
    } = {}) {
        if (!hasTarget) return { ok: false, reason: "no_target" };
        const name = normalizedItemName(rawName);
        if (!name || name === "minecraft:air") {
            return {
                ok: false,
                reason: "empty_item",
                toast: {
                    message: t("Wähle zuerst ein Item aus."),
                    type: "warning",
                    ms: 3000,
                },
            };
        }
        return { ok: true, count: maxStack };
    }

    function quickRepairSlotPlan({
        hasTarget = false,
        repairableDamage = false,
    } = {}) {
        if (!hasTarget) return { ok: false, reason: "no_target" };
        if (!repairableDamage) {
            return {
                ok: false,
                reason: "not_repairable",
                refreshQuickActions: true,
                toast: {
                    message: t("Dieses Item hat keine reparierbare Abnutzung."),
                    type: "warning",
                    ms: 3000,
                },
            };
        }
        return { ok: true, damage: 0 };
    }

    window.MCBESlotDetailLogic = {
        applySingleSlotPlan,
        buildDetailItemFromForm,
        dataVariantSelectionPlan,
        entityVariantMetadataForItem,
        loreLinesFromText,
        normalizedItemName,
        quickClearSlotPlan,
        quickMaxStackPlan,
        quickRepairSlotPlan,
        stackCountFromForm,
    };
}());

(function () {
    "use strict";

    const logic = window.MCBESlotDetailLogic || {};

    function localizedEnchantmentName(info, id) {
        if (!info) return `ID ${id}`;
        const localized = window.MCBEI18n?.localizedPair?.(info.name_de, info.name_en);
        return localized ? localized.primary || `ID ${id}` : info.name_de || info.name_en || `ID ${id}`;
    }

    function applyItemAvailabilityBadge(element, model = null) {
        if (!element) return;
        const visible = Boolean(model?.key && model?.label);
        element.hidden = !visible;
        element.textContent = visible ? String(model.label) : "";
        element.title = visible ? String(model.description || "") : "";
        if (visible) {
            if (element.dataset) element.dataset.itemAvailability = String(model.key);
            element.setAttribute?.("aria-label", String(model.ariaLabel || model.label));
            return;
        }
        if (element.dataset) delete element.dataset.itemAvailability;
        element.removeAttribute?.("aria-label");
    }

    function createSlotDetailController({
        elements = {},
        itemCatalog,
        constants = {},
        getInventory,
        getEnderChestInventory,
        getCurrentSelectionState,
        getCurrentPlayerKey,
        getWorldPath,
        getEnchantmentsDb,
        getItemAvailability,
        isProtectedKnownSlot,
        itemRequiresOriginalNbt,
        itemHasInspectableNbt,
        itemHasRepairableDamage,
        showProtectedSlotMessage,
        showSlotInspector,
        switchTab,
        slotDisplayName,
        detailItemLabel,
        pushUndo,
        updateGridVisuals,
        setDirty,
        editingBlocked = () => false,
        getEditingBlockedReason = () => "",
        syncEditControls = () => {},
        logStatus,
        recordAction,
        showToast,
    } = {}) {
        let currentEditingEnchantments = [];
        let currentEditingIsEnder = false;
        let lastDetailItemResetName = "";
        let currentEntityVariantModel = { visible: false, editable: false, kind: "" };

        const maxDisplayName = constants.maxDisplayName ?? 64;
        const maxLoreLines = constants.maxLoreLines ?? 10;
        const maxLoreLineLength = constants.maxLoreLineLength ?? 128;
        const inventorySlotCount = constants.inventorySlotCount ?? 36;
        const enderChestSlotCount = constants.enderChestSlotCount ?? 27;

        function inventory() {
            return getInventory?.() || {};
        }

        function enderChestInventory() {
            return getEnderChestInventory?.() || {};
        }

        function enchDb() {
            return getEnchantmentsDb?.() || {};
        }

        function guardEditingAction() {
            if (editingBlocked?.() !== true) return false;
            const reason = getEditingBlockedReason?.() || t("Bearbeitung ist aktuell gesperrt.");
            showToast?.(reason, "warning", 4500);
            return true;
        }

        function detailLoreLinesFromForm() {
            return window.MCBESlotDisplay.detailLoreLinesFromForm(elements.detailLore?.value, {
                maxLoreLines,
                maxLoreLineLength,
            });
        }

        function localizedPrimary(de, en) {
            const localized = window.MCBEI18n?.localizedPair?.(de, en);
            return localized?.primary || de || en || "";
        }

        function localizedOptionLabel(de, en) {
            const localized = window.MCBEI18n?.localizedPair?.(de, en);
            const primary = localized?.primary || de || en || "";
            return localized?.secondary ? `${primary} (${localized.secondary})` : primary;
        }

        function replaceSelectOptions(select, options) {
            if (!select) return;
            const doc = select.ownerDocument || window.document;
            select.innerHTML = "";
            for (const optionData of options) {
                const option = doc.createElement("option");
                option.value = String(optionData.value);
                option.textContent = optionData.label;
                select.appendChild(option);
            }
        }

        function updateDataVariantEditor(itemName, damageValue = elements.detailDamage?.value, sourceItem = null) {
            const variants = itemCatalog.dataValueVariantsForId?.(itemName) || [];
            const visible = variants.length > 0;
            if (elements.detailDamageGroup) elements.detailDamageGroup.style.display = visible ? "none" : "";
            if (elements.detailDataVariantGroup) elements.detailDataVariantGroup.style.display = visible ? "" : "none";
            if (!visible || !elements.detailDataVariant) return;

            const selection = logic.dataVariantSelectionPlan({
                itemName,
                damageValue,
                variants,
                sourceItem,
            });
            const options = variants.map(variant => ({
                value: variant.damage,
                label: localizedOptionLabel(variant.names?.[0], variant.names?.[1]),
            }));
            if (selection.preserveUnknown) {
                options.push({
                    value: selection.selectedDamage,
                    label: t("Unbekannter Datenwert {value} (wird beibehalten)", { value: selection.selectedDamage }),
                });
            }
            replaceSelectOptions(elements.detailDataVariant, options);
            elements.detailDataVariant.value = String(selection.selectedDamage);
            if (elements.detailDamage) elements.detailDamage.value = selection.selectedDamage;
            if (elements.detailDataVariantLabel) {
                elements.detailDataVariantLabel.textContent = itemCatalog.itemDamageLabel(itemName);
            }
        }

        function setEntityVariantControlsDisabled(disabled) {
            [
                elements.detailAxolotlColor,
                elements.detailAxolotlAge,
                elements.detailTropicalFishPattern,
                elements.detailTropicalFishColor,
                elements.detailTropicalFishColor2,
            ].filter(Boolean).forEach(control => {
                control.disabled = disabled;
            });
        }

        function updateEntityVariantEditor(itemName, item = null) {
            const editor = window.MCBEEntityVariantEditor;
            currentEntityVariantModel = editor?.editorModel?.({ item, itemName })
                || { visible: false, editable: false, kind: "" };
            if (elements.detailEntityVariantPanel) {
                elements.detailEntityVariantPanel.style.display = currentEntityVariantModel.visible ? "" : "none";
                elements.detailEntityVariantPanel.classList?.toggle("is-readonly", !currentEntityVariantModel.editable);
            }
            if (!currentEntityVariantModel.visible) return;
            if (elements.detailEntityVariantTitle) {
                elements.detailEntityVariantTitle.textContent = currentEntityVariantModel.title || t("Gespeicherte Entityvariante");
            }
            if (elements.detailEntityVariantNote) {
                elements.detailEntityVariantNote.textContent = currentEntityVariantModel.note || "";
            }
            if (elements.detailAxolotlVariantFields) {
                elements.detailAxolotlVariantFields.style.display = currentEntityVariantModel.kind === "axolotl"
                    && currentEntityVariantModel.state !== "unresolved"
                    ? ""
                    : "none";
            }
            if (elements.detailTropicalFishVariantFields) {
                elements.detailTropicalFishVariantFields.style.display = currentEntityVariantModel.kind === "tropical_fish" ? "" : "none";
            }
            if (currentEntityVariantModel.kind === "axolotl") {
                const generic = currentEntityVariantModel.state === "generic";
                replaceSelectOptions(
                    elements.detailAxolotlColor,
                    generic ? editor.genericAxolotlColorOptions() : editor.axolotlColorOptions(),
                );
                replaceSelectOptions(
                    elements.detailAxolotlAge,
                    generic ? editor.genericAxolotlAgeOptions() : editor.axolotlAgeOptions(),
                );
                if (elements.detailAxolotlColor) {
                    elements.detailAxolotlColor.value = generic
                        ? "generic"
                        : String(currentEntityVariantModel.variant);
                }
                if (elements.detailAxolotlAge) {
                    elements.detailAxolotlAge.value = currentEntityVariantModel.isBaby ? "baby" : "adult";
                }
            } else if (currentEntityVariantModel.kind === "tropical_fish") {
                replaceSelectOptions(elements.detailTropicalFishPattern, editor.tropicalFishPatternOptions());
                replaceSelectOptions(elements.detailTropicalFishColor, editor.tropicalFishColorOptions());
                replaceSelectOptions(elements.detailTropicalFishColor2, editor.tropicalFishColorOptions());
                if (elements.detailTropicalFishPattern) {
                    elements.detailTropicalFishPattern.value = `${currentEntityVariantModel.variant}:${currentEntityVariantModel.markVariant}`;
                }
                if (elements.detailTropicalFishColor) {
                    elements.detailTropicalFishColor.value = String(currentEntityVariantModel.color);
                }
                if (elements.detailTropicalFishColor2) {
                    elements.detailTropicalFishColor2.value = String(currentEntityVariantModel.color2);
                }
            }
            setEntityVariantControlsDisabled(!currentEntityVariantModel.editable);
        }

        function selectedEntityVariantState(previousItem, itemName) {
            const editor = window.MCBEEntityVariantEditor;
            const sameItem = previousItem
                && logic.normalizedItemName(previousItem.name) === logic.normalizedItemName(itemName);
            const sourceItem = sameItem ? previousItem : null;
            const sourceMetadata = logic.entityVariantMetadataForItem(sourceItem, itemName);
            if (!editor || !currentEntityVariantModel.editable) return { edit: null, metadata: sourceMetadata };
            if (editor.kindForItemName(itemName) !== currentEntityVariantModel.kind) return { edit: null, metadata: null };
            const edit = editor.editFromValues({
                kind: currentEntityVariantModel.kind,
                axolotlVariant: elements.detailAxolotlColor?.value,
                axolotlAge: elements.detailAxolotlAge?.value,
                tropicalPattern: elements.detailTropicalFishPattern?.value,
                tropicalColor: elements.detailTropicalFishColor?.value,
                tropicalColor2: elements.detailTropicalFishColor2?.value,
            });
            if (!edit) return { edit: null, metadata: sourceMetadata };
            const sourceModel = editor.editorModel({ item: sourceItem, itemName });
            const sourceEdit = editor.sourceEditFromModel(sourceModel);
            const hasPendingEdit = Boolean(sourceItem?.entity_variant_edit);
            const shouldPersistEdit = hasPendingEdit || !editor.editsEqual(edit, sourceEdit);
            return {
                edit: shouldPersistEdit ? edit : null,
                metadata: shouldPersistEdit
                    ? editor.updatedEntityVariantMetadata(sourceMetadata, edit)
                    : sourceMetadata,
            };
        }

        function updateDetailPreview() {
            const itemId = String(elements.detailItemSearch?.value || "").trim().toLowerCase();
            const isEmpty = !itemId || itemId === "minecraft:air";
            const known = isEmpty || itemCatalog.isKnownItemId(itemId);
            const maxStack = itemCatalog.getMaxStack(itemId);
            const maxDmg = itemCatalog.getMaxDamage(itemId);
            const target = currentDetailTarget();
            const sourceItem = target?.source?.[target.slotId] || null;
            const count = isEmpty
                ? 0
                : logic.stackCountFromForm({
                    rawCount: elements.detailCount?.value,
                    maxStack,
                    previousItem: sourceItem,
                    itemName: itemId,
                });
            const damage = isEmpty ? 0 : itemCatalog.clampNumber(elements.detailDamage?.value, 0, 0, maxDmg);
            const usesDurability = !isEmpty && itemCatalog.itemUsesDurabilityDamage(itemId);
            const damageLabel = isEmpty ? t("Abnutzung") : itemCatalog.itemDamageLabel(itemId);
            if (elements.detailDamageLabel) {
                elements.detailDamageLabel.textContent = damageLabel;
            }
            if (elements.detailDamage) {
                elements.detailDamage.title = usesDurability
                    ? t("0 = neuwertig; höherer Wert = mehr Abnutzung. Verbleibende Haltbarkeit: Maximalwert minus Abnutzung.")
                    : t("Bedrock-Datenwert für Varianten wie Potions, Farben oder Legacy-Subtypen");
            }
            const loreLines = detailLoreLinesFromForm();
            const enchants = currentEditingEnchantments
                .map(e => {
                    const info = enchDb()[e.id];
                    const name = localizedEnchantmentName(info, e.id);
                    return `${name} ${e.lvl}`;
                })
                .slice(0, 4);
            const iconMeta = itemCatalog.getItemIconMeta(itemId, damage);
            const enchantmentConflicts = (itemCatalog.vanillaExclusiveEnchantmentConflicts?.(currentEditingEnchantments, itemId) || [])
                .map(ids => ids.map(id => localizedEnchantmentName(enchDb()[id], id)).join(" ↔ "));
            const variantSource = sourceItem && logic.normalizedItemName(sourceItem.name) === itemId
                ? sourceItem
                : null;
            const entityState = selectedEntityVariantState(variantSource, itemId);
            const entityDisplayName = entityState.metadata
                ? localizedPrimary(entityState.metadata.display_name_de, entityState.metadata.display_name_en)
                : "";
            const customName = String(elements.detailCustomName?.value || "").trim();
            const previewModel = window.MCBESlotDisplay.detailPreviewModel({
                itemId,
                displayName: customName
                    ? detailItemLabel(itemId, customName, damage)
                    : entityDisplayName || detailItemLabel(itemId, "", damage),
                isEmpty,
                known,
                count,
                damage,
                damageLabel,
                usesDurability,
                maxDamage: maxDmg,
                loreLines,
                enchantments: enchants,
                enchantmentTotal: currentEditingEnchantments.length,
                enchantmentConflicts,
                iconUrl: iconMeta?.url || "",
                fallbackIcon: itemCatalog.getItemEmoji(itemId) || "📦",
                iconTint: itemCatalog.getItemIconTint?.(itemId) || "",
            });
            window.MCBESlotDisplay.applyDetailPreviewModel({
                preview: elements.detailPreview,
                icon: elements.detailPreviewIcon,
                name: elements.detailPreviewName,
                meta: elements.detailPreviewMeta,
                lore: elements.detailPreviewLore,
                enchantments: elements.detailPreviewEnchantments,
            }, previewModel);
            applyItemAvailabilityBadge(
                elements.detailPreviewAvailability,
                isEmpty ? null : getItemAvailability?.(itemId, damage),
            );
            updateDetailQuickActions();
        }

        function loadSingleSlotEditor(slotId, isEnderChest = false) {
            currentEditingIsEnder = isEnderChest;
            const source = isEnderChest ? enderChestInventory() : inventory();
            if (elements.detailSlotNum) elements.detailSlotNum.innerText = slotId + (isEnderChest ? " (Enderchest)" : "");
            const item = source[slotId] || { name: "", count: 1, damage: 0, display_name: "", lore: [], enchantments: [] };

            if (elements.detailItemSearch) elements.detailItemSearch.value = item.name;
            if (elements.detailCount) elements.detailCount.value = item.count;
            if (elements.detailDamage) elements.detailDamage.value = item.damage;
            if (elements.detailCustomName) elements.detailCustomName.value = item.display_name || "";
            if (elements.detailLore) elements.detailLore.value = (item.lore || []).join("\n");

            currentEditingEnchantments = JSON.parse(JSON.stringify(item.enchantments || []));
            lastDetailItemResetName = "";
            updateDataVariantEditor(item.name, item.damage, item);
            updateEntityVariantEditor(item.name, item);
            buildEnchantmentsList();
            updateDetailPreview();
            updateDetailQuickActions();
            syncEditControls?.();

            switchTab?.("tabGeneral");
            if (!item.name) elements.detailItemSearch?.focus();
        }

        function currentDetailTarget() {
            const target = window.MCBESelectionState.selectedSingleTarget(getCurrentSelectionState?.());
            if (!target) return null;
            return {
                ...target,
                source: target.isEnder ? enderChestInventory() : inventory(),
            };
        }

        function firstEmptyWritableSlot(containerName) {
            const source = containerName === "ender_chest" ? enderChestInventory() : inventory();
            return window.MCBEInventoryState.firstEmptyWritableSlot({
                containerName,
                source,
                slotCount: containerName === "ender_chest" ? enderChestSlotCount : inventorySlotCount,
                isProtectedKnownSlot,
            });
        }

        function buildDetailItemFromForm(slotId, containerName) {
            const source = containerName === "ender_chest" ? enderChestInventory() : inventory();
            const name = logic.normalizedItemName(elements.detailItemSearch?.value);
            const previousItem = source[slotId];
            const validDetailItemId = !name || name === "minecraft:air" || itemCatalog.isValidItemId(name);
            const maxStack = validDetailItemId ? itemCatalog.getMaxStack(name) : 64;
            const maxDmg = validDetailItemId ? itemCatalog.getMaxDamage(name) : 0;
            const entityState = selectedEntityVariantState(previousItem, name);
            return logic.buildDetailItemFromForm({
                slotId,
                containerName,
                previousItem,
                rawName: name,
                rawCount: elements.detailCount?.value,
                rawDamage: elements.detailDamage?.value,
                rawCustomName: elements.detailCustomName?.value,
                rawLore: elements.detailLore?.value,
                enchantments: currentEditingEnchantments,
                currentPlayerKey: getCurrentPlayerKey?.(),
                worldPath: getWorldPath?.(),
                maxStack,
                maxDamage: maxDmg,
                maxDisplayName,
                maxLoreLines,
                maxLoreLineLength,
                isValidItemId: itemCatalog.isValidItemId,
                isAddableItemId: itemCatalog.isAddableItemId,
                isEnchantableItem: itemCatalog.isEnchantableItemForEditor,
                isEnchantmentCompatible: itemCatalog.isEnchantmentCompatibleWithItem,
                enchantmentLabel: id => localizedEnchantmentName(enchDb()[id], id),
                detailItemLabel,
                itemRequiresOriginalNbt,
                specialItemNbtRequirement: itemCatalog.specialItemNbtRequirement,
                entityVariantEdit: entityState.edit,
                entityVariantMetadata: entityState.metadata,
            });
        }

        function updateDetailQuickActions() {
            const target = currentDetailTarget();
            if (!elements.slotQuickActions || !target) return;
            const sourceItem = target.source?.[target.slotId] || null;
            const name = String(elements.detailItemSearch?.value || "").trim().toLowerCase();
            const isEmpty = !name || name === "minecraft:air";
            const maxStack = itemCatalog.getMaxStack(name);
            const damage = itemCatalog.clampNumber(elements.detailDamage?.value, 0, 0, itemCatalog.getMaxDamage(name));
            const slotLabel = slotDisplayName(target.slotId, target.containerName);
            const model = window.MCBESlotDisplay.slotQuickActionsModel({
                slotLabel,
                isEmpty,
                itemLabel: detailItemLabel(name, elements.detailCustomName?.value || "", damage),
                maxStack,
                isValidItem: itemCatalog.isValidItemId(name),
                damage,
                repairableDamage: itemCatalog.itemUsesDurabilityDamage(name) && damage > 0,
                hasInspectableNbt: itemHasInspectableNbt(sourceItem),
            });
            window.MCBESlotDisplay.applySlotQuickActionsModel({
                title: elements.slotQuickTitle,
                subtitle: elements.slotQuickSubtitle,
                inspectButton: elements.btnInspectSlotNbt,
                clearButton: elements.btnQuickClearSlot,
                maxStackButton: elements.btnQuickMaxStack,
                repairButton: elements.btnQuickRepairSlot,
            }, model);
        }

        function countMaxableExistingEnchantments(itemName) {
            return window.MCBEEnchantmentEditorLogic.countMaxableEnchantments({
                enchantments: currentEditingEnchantments,
                itemName,
                enchantmentsDb: enchDb(),
                isCompatible: itemCatalog.isEnchantmentCompatibleWithItem,
            });
        }

        function updateEnchantmentActionButtons(itemName = String(elements.detailItemSearch?.value || "").trim().toLowerCase()) {
            const enchantable = itemCatalog.isEnchantableItemForEditor(itemName);
            const model = window.MCBEEnchantmentsView.enchantmentActionButtonsModel({
                enchantmentCount: currentEditingEnchantments.length,
                enchantable,
                maxableCount: countMaxableExistingEnchantments(itemName),
            });
            window.MCBEEnchantmentsView.applyEnchantmentActionButtonsModel({
                count: elements.diagCountEl,
                maxAllButton: elements.btnMaxAllEnch,
                clearAllButton: elements.btnClearAllEnch,
            }, model);
        }

        function buildEnchantmentsList() {
            const container = elements.enchantsContainer;
            if (!container) return;
            container.innerHTML = "";
            const itemName = window.MCBEEnchantmentEditorLogic.normalizedItemName(elements.detailItemSearch?.value);
            const enchantable = itemCatalog.isEnchantableItemForEditor(itemName);
            updateEnchantmentActionButtons(itemName);

            if (!enchantable) {
                container.appendChild(window.MCBEEnchantmentsView.unavailableEnchantmentsElement({
                    hasExistingEnchantments: currentEditingEnchantments.length > 0,
                    itemName,
                }));
                if (currentEditingEnchantments.length === 0) return;
            }

            if (itemName === "minecraft:enchanted_book") {
                container.appendChild(window.MCBEEnchantmentsView.enchantedBookInfoElement());
            }

            const sortedEnchs = window.MCBEEnchantmentEditorLogic.enchantmentRowsForItem({
                enchantmentsDb: enchDb(),
                itemName,
                activeEnchantments: currentEditingEnchantments,
                isCompatible: itemCatalog.isEnchantmentCompatibleWithItem,
            });

            for (const { id, info, activeEnchantment, compatible } of sortedEnchs) {
                const controlsDisabled = !compatible;
                const model = window.MCBEEnchantmentsView.enchantmentRowModel({
                    id,
                    info,
                    activeEnchantment,
                    compatible,
                });

                const row = window.MCBEEnchantmentsView.enchantmentRowElement(model);
                const slider = row.querySelector(".ench-slider");
                const valSpan = row.querySelector(".ench-value");
                const checkbox = row.querySelector(".ench-checkbox");

                slider.addEventListener("input", (e) => {
                    if (controlsDisabled || guardEditingAction()) return;
                    const val = parseInt(e.target.value, 10);
                    valSpan.innerText = val;
                    currentEditingEnchantments = window.MCBEEnchantmentEditorLogic.updateEnchantmentLevel(currentEditingEnchantments, id, val);
                    updateEnchantmentActionButtons(itemName);
                    updateDetailPreview();
                });

                checkbox.addEventListener("change", (e) => {
                    if (controlsDisabled || guardEditingAction()) return;
                    if (e.target.checked) {
                        slider.removeAttribute("disabled");
                        const val = parseInt(slider.value, 10);
                        currentEditingEnchantments = window.MCBEEnchantmentEditorLogic.toggleEnchantment(currentEditingEnchantments, { id, checked: true, level: val });
                    } else {
                        slider.setAttribute("disabled", "true");
                        currentEditingEnchantments = window.MCBEEnchantmentEditorLogic.toggleEnchantment(currentEditingEnchantments, { id, checked: false });
                    }
                    updateEnchantmentActionButtons(itemName);
                    updateDetailPreview();
                });

                container.appendChild(row);
            }
        }

        function resetDetailFormForNewItem(itemName) {
            lastDetailItemResetName = String(itemName || "").trim().toLowerCase();
            const maxStack = itemCatalog.getMaxStack(itemName);
            if (elements.detailCount) elements.detailCount.value = Math.min(1, maxStack);
            if (elements.detailDamage) elements.detailDamage.value = 0;
            if (elements.detailCustomName) elements.detailCustomName.value = "";
            if (elements.detailLore) elements.detailLore.value = "";
            currentEditingEnchantments = [];
            updateDataVariantEditor(itemName, 0);
            updateEntityVariantEditor(itemName, null);
            buildEnchantmentsList();
            updateDetailPreview();
        }

        function selectDetailItemVariant(item) {
            const damage = Number(item?.damage);
            if (!Number.isInteger(damage) || damage < 0 || !elements.detailDamage) return;
            elements.detailDamage.value = damage;
            updateDataVariantEditor(elements.detailItemSearch?.value, damage);
            updateDetailPreview();
        }

        function maybeResetDetailFormForManualItemChange() {
            const target = currentDetailTarget();
            if (!target) return;
            const previousItem = target.source?.[target.slotId] || null;
            const plan = window.MCBEEnchantmentEditorLogic.manualItemResetPlan({
                previousName: previousItem?.name || "",
                nextName: elements.detailItemSearch?.value || "",
                lastResetName: lastDetailItemResetName,
                isValidItemId: itemCatalog.isValidItemId,
            });
            if (!plan.shouldReset) return;
            lastDetailItemResetName = plan.nextName;
            resetDetailFormForNewItem(plan.nextName);
        }

        function updateVariantEditorsForCurrentForm() {
            const target = currentDetailTarget();
            const itemName = logic.normalizedItemName(elements.detailItemSearch?.value);
            const sourceItem = target?.source?.[target.slotId] || null;
            const matchingSource = sourceItem && logic.normalizedItemName(sourceItem.name) === itemName
                ? sourceItem
                : null;
            updateDataVariantEditor(itemName, elements.detailDamage?.value, matchingSource);
            updateEntityVariantEditor(itemName, matchingSource);
            updateDetailPreview();
        }

        function applyCurrentSingleSlot() {
            const target = window.MCBESelectionState.selectedSingleTarget(getCurrentSelectionState?.());
            if (target) applySingleChanges(target.slotId);
        }

        function applySingleChanges(slotId) {
            if (guardEditingAction()) return;
            const containerName = currentEditingIsEnder ? "ender_chest" : "inventory";
            const protectedKnown = isProtectedKnownSlot(slotId, containerName);
            const source = currentEditingIsEnder ? enderChestInventory() : inventory();
            const built = buildDetailItemFromForm(slotId, containerName);
            const previousItem = source[slotId] || null;
            const plan = logic.applySingleSlotPlan({
                protectedKnown,
                buildResult: built,
                previousItem,
                containerName,
            });
            if (plan.showProtected) {
                showProtectedSlotMessage(slotId, containerName);
                return;
            }
            if (!plan.ok) {
                if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                if (plan.refreshQuickActions) updateDetailQuickActions();
                return;
            }

            pushUndo?.();
            if (plan.operation === "clear") {
                window.MCBEInventoryState.clearTargets([{ map: source, slotId }]);
            } else {
                source[slotId] = plan.item;
            }

            const nextItem = source[slotId] || null;
            updateDataVariantEditor(nextItem?.name || "", nextItem?.damage || 0, nextItem);
            updateEntityVariantEditor(nextItem?.name || "", nextItem);
            updateGridVisuals?.();
            updateDetailPreview();
            setDirty?.(true);
            logStatus?.(currentEditingIsEnder ? t("Enderchest-Slot {slot} aktualisiert", { slot: slotId }) : t("Slot {slot} aktualisiert", { slot: slotId }), "success");
            recordAction?.(t("{slot} aktualisiert", { slot: slotDisplayName(slotId, containerName) }), "edit");
        }

        function applyQuickClearSlot() {
            if (guardEditingAction()) return;
            const target = currentDetailTarget();
            const plan = logic.quickClearSlotPlan({
                hasTarget: Boolean(target),
                protectedKnown: Boolean(target && isProtectedKnownSlot(target.slotId, target.containerName)),
                rawName: elements.detailItemSearch?.value,
            });
            if (plan.showProtected) {
                showProtectedSlotMessage(target.slotId, target.containerName);
                return;
            }
            if (!plan.ok) {
                if (plan.refreshQuickActions) updateDetailQuickActions();
                return;
            }
            pushUndo?.();
            window.MCBEInventoryState.clearTargets([{ map: target.source, slotId: target.slotId }]);
            if (elements.detailItemSearch) elements.detailItemSearch.value = "";
            if (elements.detailCount) elements.detailCount.value = 1;
            if (elements.detailDamage) elements.detailDamage.value = 0;
            if (elements.detailCustomName) elements.detailCustomName.value = "";
            if (elements.detailLore) elements.detailLore.value = "";
            currentEditingEnchantments = [];
            updateDataVariantEditor("", 0);
            updateEntityVariantEditor("", null);
            buildEnchantmentsList();
            updateDetailPreview();
            updateGridVisuals?.();
            setDirty?.(true);
            logStatus?.(`${slotDisplayName(target.slotId, target.containerName)} geleert`, "success");
            recordAction?.(`${slotDisplayName(target.slotId, target.containerName)} geleert`, "edit");
        }

        function applyQuickMaxStack() {
            if (guardEditingAction()) return;
            const target = currentDetailTarget();
            const name = logic.normalizedItemName(elements.detailItemSearch?.value);
            const plan = logic.quickMaxStackPlan({
                hasTarget: Boolean(target),
                rawName: name,
                maxStack: target ? itemCatalog.getMaxStack(name) : 64,
            });
            if (!plan.ok) {
                if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                return;
            }
            if (elements.detailCount) elements.detailCount.value = plan.count;
            applySingleChanges(target.slotId);
        }

        function applyQuickRepairSlot() {
            if (guardEditingAction()) return;
            const target = currentDetailTarget();
            const name = logic.normalizedItemName(elements.detailItemSearch?.value);
            const damage = target ? itemCatalog.clampNumber(elements.detailDamage?.value, 0, 0, itemCatalog.getMaxDamage(name)) : 0;
            const plan = logic.quickRepairSlotPlan({
                hasTarget: Boolean(target),
                repairableDamage: itemHasRepairableDamage({ name, count: 1, damage }),
            });
            if (!plan.ok) {
                if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                if (plan.refreshQuickActions) updateDetailQuickActions();
                return;
            }
            if (elements.detailDamage) elements.detailDamage.value = plan.damage;
            applySingleChanges(target.slotId);
        }

        function wireEnchantments() {
            elements.btnMaxAllEnch?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                const itemName = window.MCBEEnchantmentEditorLogic.normalizedItemName(elements.detailItemSearch?.value);
                const plan = window.MCBEEnchantmentEditorLogic.maxAllEnchantmentsPlan({
                    itemName,
                    enchantments: currentEditingEnchantments,
                    enchantmentsDb: enchDb(),
                    isEnchantableItem: itemCatalog.isEnchantableItemForEditor,
                    isCompatible: itemCatalog.isEnchantmentCompatibleWithItem,
                });
                if (!plan.ok) {
                    if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                    buildEnchantmentsList();
                    return;
                }
                currentEditingEnchantments = plan.enchantments;
                if (plan.toast) showToast?.(plan.toast.message, plan.toast.type, plan.toast.ms);
                buildEnchantmentsList();
                updateDetailPreview();
            });

            elements.btnClearAllEnch?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                currentEditingEnchantments = [];
                buildEnchantmentsList();
                updateDetailPreview();
            });
        }

        function wireFormPreview() {
            [elements.detailItemSearch, elements.detailCount, elements.detailDamage, elements.detailCustomName, elements.detailLore]
                .filter(Boolean)
                .forEach(input => input.addEventListener("input", updateDetailPreview));
            elements.detailItemSearch?.addEventListener("input", maybeResetDetailFormForManualItemChange);
            elements.detailItemSearch?.addEventListener("input", buildEnchantmentsList);
            elements.detailItemSearch?.addEventListener("input", updateVariantEditorsForCurrentForm);
            elements.detailDataVariant?.addEventListener("change", () => {
                const damage = Number.parseInt(elements.detailDataVariant.value, 10);
                if (Number.isInteger(damage) && elements.detailDamage) {
                    elements.detailDamage.value = damage;
                }
                updateDetailPreview();
            });
            [
                elements.detailAxolotlColor,
                elements.detailAxolotlAge,
                elements.detailTropicalFishPattern,
                elements.detailTropicalFishColor,
                elements.detailTropicalFishColor2,
            ].filter(Boolean).forEach(select => select.addEventListener("change", updateDetailPreview));
        }

        function wireApplyButtons() {
            elements.btnApplySingle?.addEventListener("click", applyCurrentSingleSlot);
            elements.btnApplySingleEnch?.addEventListener("click", applyCurrentSingleSlot);
        }

        function wireQuickActions() {
            elements.btnQuickClearSlot?.addEventListener("click", applyQuickClearSlot);
            elements.btnInspectSlotNbt?.addEventListener("click", () => {
                const target = currentDetailTarget();
                const sourceItem = target?.source?.[target.slotId] || null;
                if (!target || !itemHasInspectableNbt(sourceItem)) {
                    showToast?.(t("Keine geschützten Zusatzdaten in diesem Slot erkannt."), "warning", 2500);
                    return;
                }
                showSlotInspector?.(target.slotId, target.containerName, "item_protected_nbt");
            });
            elements.btnQuickMaxStack?.addEventListener("click", applyQuickMaxStack);
            elements.btnQuickRepairSlot?.addEventListener("click", applyQuickRepairSlot);
        }

        function wire() {
            wireEnchantments();
            wireFormPreview();
            wireApplyButtons();
            wireQuickActions();
        }

        return {
            applyCurrentSingleSlot,
            buildEnchantmentsList,
            currentDetailTarget,
            firstEmptyWritableSlot,
            loadSingleSlotEditor,
            resetDetailFormForNewItem,
            selectDetailItemVariant,
            updateDetailPreview,
            updateDetailQuickActions,
            wire,
        };
    }

    function collectSlotDetailElements(doc = document) {
        return {
            detailItemSearch: doc.getElementById("detailItemSearch"),
            detailCount: doc.getElementById("detailCount"),
            detailDamage: doc.getElementById("detailDamage"),
            detailDamageLabel: doc.querySelector('label[for="detailDamage"]'),
            detailDamageGroup: doc.getElementById("detailDamageGroup"),
            detailDataVariantGroup: doc.getElementById("detailDataVariantGroup"),
            detailDataVariantLabel: doc.getElementById("detailDataVariantLabel"),
            detailDataVariant: doc.getElementById("detailDataVariant"),
            detailEntityVariantPanel: doc.getElementById("detailEntityVariantPanel"),
            detailEntityVariantTitle: doc.getElementById("detailEntityVariantTitle"),
            detailEntityVariantNote: doc.getElementById("detailEntityVariantNote"),
            detailAxolotlVariantFields: doc.getElementById("detailAxolotlVariantFields"),
            detailAxolotlColor: doc.getElementById("detailAxolotlColor"),
            detailAxolotlAge: doc.getElementById("detailAxolotlAge"),
            detailTropicalFishVariantFields: doc.getElementById("detailTropicalFishVariantFields"),
            detailTropicalFishPattern: doc.getElementById("detailTropicalFishPattern"),
            detailTropicalFishColor: doc.getElementById("detailTropicalFishColor"),
            detailTropicalFishColor2: doc.getElementById("detailTropicalFishColor2"),
            detailCustomName: doc.getElementById("detailCustomName"),
            detailLore: doc.getElementById("detailLore"),
            detailSlotNum: doc.getElementById("detailSlotNum"),
            detailPreview: doc.getElementById("detailPreview"),
            detailPreviewIcon: doc.getElementById("detailPreviewIcon"),
            detailPreviewName: doc.getElementById("detailPreviewName"),
            detailPreviewAvailability: doc.getElementById("detailPreviewAvailability"),
            detailPreviewMeta: doc.getElementById("detailPreviewMeta"),
            detailPreviewLore: doc.getElementById("detailPreviewLore"),
            detailPreviewEnchantments: doc.getElementById("detailPreviewEnchantments"),
            slotQuickActions: doc.getElementById("slotQuickActions"),
            slotQuickTitle: doc.getElementById("slotQuickTitle"),
            slotQuickSubtitle: doc.getElementById("slotQuickSubtitle"),
            btnInspectSlotNbt: doc.getElementById("btnInspectSlotNbt"),
            btnQuickClearSlot: doc.getElementById("btnQuickClearSlot"),
            btnQuickMaxStack: doc.getElementById("btnQuickMaxStack"),
            btnQuickRepairSlot: doc.getElementById("btnQuickRepairSlot"),
            enchantsContainer: doc.getElementById("enchantsContainer"),
            btnMaxAllEnch: doc.getElementById("btnMaxAllEnch"),
            btnClearAllEnch: doc.getElementById("btnClearAllEnch"),
            diagCountEl: doc.getElementById("enchCount"),
            btnApplySingle: doc.getElementById("btnApplySingle"),
            btnApplySingleEnch: doc.getElementById("btnApplySingleEnch"),
        };
    }

    function createInventorySlotDetailController({
        doc = document,
        itemCatalog,
        constants = {},
        state = {},
        helpers = {},
    } = {}) {
        return createSlotDetailController({
            elements: collectSlotDetailElements(doc),
            itemCatalog,
            constants,
            getInventory: state.getInventory,
            getEnderChestInventory: state.getEnderChestInventory,
            getCurrentSelectionState: state.getCurrentSelectionState,
            getCurrentPlayerKey: state.getCurrentPlayerKey,
            getWorldPath: state.getWorldPath,
            getEnchantmentsDb: state.getEnchantmentsDb,
            getItemAvailability: helpers.getItemAvailability,
            isProtectedKnownSlot: helpers.isProtectedKnownSlot,
            itemRequiresOriginalNbt: helpers.itemRequiresOriginalNbt,
            itemHasInspectableNbt: helpers.itemHasInspectableNbt,
            itemHasRepairableDamage: helpers.itemHasRepairableDamage,
            showProtectedSlotMessage: helpers.showProtectedSlotMessage,
            showSlotInspector: helpers.showSlotInspector,
            switchTab: helpers.switchTab,
            slotDisplayName: helpers.slotDisplayName,
            detailItemLabel: helpers.detailItemLabel,
            pushUndo: helpers.pushUndo,
            updateGridVisuals: helpers.updateGridVisuals,
            setDirty: helpers.setDirty,
            editingBlocked: helpers.editingBlocked,
            getEditingBlockedReason: helpers.getEditingBlockedReason,
            syncEditControls: helpers.syncEditControls,
            logStatus: helpers.logStatus,
            recordAction: helpers.recordAction,
            showToast: helpers.showToast,
        });
    }

    window.MCBESlotDetailLogic = {
        ...logic,
        applyItemAvailabilityBadge,
        collectSlotDetailElements,
        createInventorySlotDetailController,
        createSlotDetailController,
    };
}());
