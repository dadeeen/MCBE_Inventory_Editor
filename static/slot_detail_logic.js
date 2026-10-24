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

    function restoreEquivalentItem(item, baseline) {
        if (!item || !baseline) return item;
        const originFields = ["name", "source_slot", "source_container", "source_player_key", "source_world_path",
            "source_item_digest", "root_equipment_source_tag", "root_equipment_source_index",
            "replace_original_nbt", "protected_nbt_dropped", "origin_world_mismatch"];
        if (originFields.some(key => item[key] !== baseline[key])) return item;
        const displayText = value => String(value ?? "").replace(/[\r\n]/g, "");
        const loreText = value => (value || []).join("\n").replace(/\r\n?/g, "\n");
        let restored = item;
        for (const [key, rendered] of [["display_name", displayText], ["lore", loreText]]) {
            if (rendered(restored[key]) !== rendered(baseline[key])) continue;
            if (!Object.prototype.hasOwnProperty.call(baseline, key)
                || JSON.stringify(restored[key]) === JSON.stringify(baseline[key])) continue;
            if (restored === item) restored = cloneJson(item);
            restored[key] = cloneJson(baseline[key]);
        }
        // Compare text as rendered by HTML controls and ignore derived caches.
        // Origins, replacement intent and other NBT edits must still match.
        const comparable = value => {
            const result = cloneJson(value);
            delete result.nbt_view;
            delete result.stack_key;
            result.display_name = displayText(result.display_name);
            result.lore = loreText(result.lore);
            result.enchantments ??= [];
            return result;
        };
        const candidate = comparable(restored);
        const original = comparable(baseline);
        const editor = window.MCBEEntityVariantEditor;
        if (candidate.entity_variant_edit && !original.entity_variant_edit && editor) {
            const originalEdit = editor.sourceEditFromModel(editor.editorModel({ item: baseline, itemName: baseline.name }));
            if (editor.editsEqual(candidate.entity_variant_edit, originalEdit)) {
                delete candidate.entity_variant_edit;
                candidate.entity_variant = original.entity_variant;
            }
        }
        const ordered = value => Array.isArray(value) ? value.map(ordered)
            : value && typeof value === "object"
                ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])]))
                : value;
        return JSON.stringify(ordered(candidate)) === JSON.stringify(ordered(original)) ? cloneJson(baseline) : restored;
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
        const damage = String(damageValue ?? "").trim() === "" ? NaN : Number(damageValue);
        const knownDamage = Number.isInteger(damage)
            && variants.some(variant => Number(variant?.damage) === damage);
        const sourceDamage = Number(sourceItem?.damage);
        const preservesExisting = Number.isInteger(damage)
            && normalizedItemName(sourceItem?.name) === normalizedItemName(itemName)
            && Number.isInteger(sourceDamage)
            && sourceDamage === damage;
        return {
            selectedDamage: knownDamage || preservesExisting
                ? damage
                : Number(variants[0]?.damage) || 0,
            preserveUnknown: !knownDamage && preservesExisting,
        };
    }

    // The source item is the current slot's original, including container
    // children. Their provenance is source_index, not source_item_digest.
    // This model never rewrites a value just because its meaning is unknown.
    function itemDamageEditorModel({ catalog, itemName = "", damageValue = 0, sourceItem = null }) {
        const name = normalizedItemName(itemName);
        const value = String(damageValue ?? "").trim() === "" ? NaN : Number(damageValue);
        const variants = catalog.dataValueVariantsForId?.(name) || [];
        const mode = variants.length ? "variant" : catalog.itemUsesDurabilityDamage?.(name) ? "durability" : "none";
        const maxDamage = mode === "durability" ? catalog.getMaxDamage(name)
            : Math.max(0, ...variants.map(variant => Number(variant.damage)));
        const supported = Number.isInteger(value) && (mode === "durability"
            ? value >= 0 && value <= maxDamage
            : mode === "variant" ? variants.some(variant => Number(variant.damage) === value) : value === 0);
        const preserved = normalizedItemName(sourceItem?.name) === name
            && Number.isInteger(value) && value === Number(sourceItem?.damage);
        const preserveUnknown = preserved && !supported;
        const error = supported || preserved ? "" : mode === "none"
            ? t("Für dieses Item ist kein bearbeitbarer Datenwert belegt. Der vorhandene Wert muss unverändert bleiben.")
            : t("Der Abnutzungs- oder Datenwert liegt außerhalb des erlaubten Bereichs.");
        const remaining = mode === "durability" && supported ? maxDamage - value : null;
        let note = "";
        if (mode === "durability") {
            note = preserveUnknown
                ? t("Gespeicherte Abnutzung {value}: unverändert beibehalten oder auf einen Wert von 0 bis {max} ändern.", { value, max: maxDamage })
                : t("0 = neuwertig. Erlaubte Abnutzung: 0 bis {max}.", { max: maxDamage });
            if (remaining !== null) note += " " + t("Verbleibende Haltbarkeit: {remaining} von {max}.", { remaining, max: maxDamage });
        } else if (mode === "variant") {
            note = preserveUnknown
                ? t("Unbekannter Datenwert {value} bleibt erhalten, solange keine andere Variante gewählt wird.", { value })
                : t("Minecraft speichert diese Variante als Bedrock-Datenwert.");
        } else if (preserveUnknown) {
            note = t("Gespeicherter Datenwert: {value}. Für dieses Item ist keine Bedeutung belegt; der Wert bleibt unverändert erhalten.", { value });
        }
        return { mode, value, maxDamage, variants, preserveUnknown, note, remaining, error };
    }

    function entityVariantMetadataForItem(previousItem, itemName) {
        if (!previousItem || normalizedItemName(previousItem.name) !== normalizedItemName(itemName)) return null;
        return previousItem.entity_variant || null;
    }

    function stackCountFromForm({
        rawCount = 1,
        maxStack = 64,
        stackLimitVerified = true,
        previousItem = null,
        itemName = "",
    } = {}) {
        const legalCount = clampInteger(rawCount, 1, 1, maxStack);
        const requestedCount = clampInteger(rawCount, 1, 1, MAX_BEDROCK_STACK_COUNT);
        if (!stackLimitVerified) return requestedCount;
        const previousCount = Number(previousItem?.count);
        const preservesExistingOverstack = normalizedItemName(previousItem?.name) === normalizedItemName(itemName)
            && Number.isInteger(previousCount)
            && previousCount > maxStack
            && requestedCount === previousCount;
        return preservesExistingOverstack ? previousCount : legalCount;
    }

    // Both item forms use the same input rules. Container capacity is supplied
    // by its model; inventory slots use only the catalog's stack limit.
    function itemFormModel({ catalog, rawName, rawCount, rawDamage, previousItem = null, countLimit = null }) {
        const name = normalizedItemName(rawName);
        const sameItem = Boolean(previousItem) && normalizedItemName(previousItem.name) === name;
        const count = String(rawCount ?? "").trim() === "" ? NaN : Number(rawCount);
        const stack = Math.min(MAX_BEDROCK_STACK_COUNT, catalog.getMaxStack(name));
        const maximum = countLimit?.maximum ?? stack;
        const preserved = sameItem && count === Number(previousItem.count);
        const damage = itemDamageEditorModel({ catalog, itemName: name, damageValue: rawDamage, sourceItem: previousItem });
        const countError = !Number.isInteger(count) || count < 1 || count > MAX_BEDROCK_STACK_COUNT || !preserved && count > stack
            ? t("Die Menge liegt außerhalb des erlaubten Stacklimits.")
            : !preserved && (countLimit?.error || count > maximum)
                ? countLimit?.error || t("Für dieses Item ist im Bundle nicht genügend Platz.") : "";
        return { maximum, maxDamage: damage.maxDamage, countError, damageError: damage.error, preserved, variants: damage.variants,
            damageMode: damage.mode, damageNote: damage.note, damageRemaining: damage.remaining,
            readOnlyCount: maximum === 1 && count === 1 && !countLimit?.error };
    }

    function applyItemFormConstraints(model, { count, damage }) {
        if (count) {
            count.max = String(model.maximum);
            count.readOnly = model.readOnlyCount;
            count.classList?.toggle("item-count-fixed", model.readOnlyCount);
            count.setAttribute?.("aria-invalid", String(Boolean(model.countError)));
        }
        if (damage) {
            damage.max = String(model.maxDamage);
            damage.readOnly = model.damageMode === "none";
            damage.setAttribute?.("aria-invalid", String(Boolean(model.damageError)));
        }
    }

    function buildItemForm({ catalog, enchantmentsDb = {}, countLimit = null, ...fields }) {
        const name = normalizedItemName(fields.rawName);
        if (name && name !== "minecraft:air") {
            const model = itemFormModel({ catalog, countLimit, ...fields });
            if (model.countError || model.damageError) return { ok: false, error: model.countError || model.damageError };
            const unchanged = normalizedItemName(fields.previousItem?.name) === name
                && JSON.stringify(fields.previousItem?.enchantments || []) === JSON.stringify(fields.enchantments || []);
            if (!unchanged && (fields.enchantments || []).some(entry => !Number.isInteger(entry.lvl) || entry.lvl < 1
                || !enchantmentsDb[entry.id] || entry.lvl > enchantmentsDb[entry.id].max_lvl)) {
                return { ok: false, error: t("Die Verzauberungsstufe liegt außerhalb des erlaubten Bereichs.") };
            }
        }
        return buildDetailItemFromForm({
            ...fields, rawCount: Number(fields.rawCount), rawDamage: Number(fields.rawDamage),
            maxStack: catalog.getMaxStack(name), maxDamage: catalog.getMaxDamage(name),
            stackLimitVerified: catalog.hasVerifiedStackLimit(name), isValidItemId: catalog.isValidItemId,
            isAddableItemId: catalog.isAddableItemId, isEnchantableItem: catalog.isEnchantableItemForEditor,
            isEnchantmentCompatible: catalog.isEnchantmentCompatibleWithItem,
        });
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
        stackLimitVerified = true,
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

        if (!stackLimitVerified && Number(rawCount) > maxStack
            && !(sameItem && Number(rawCount) === Number(previousItem.count))) {
            return {
                ok: false,
                error: t("Stacklimit ungeprüft. Neue Stapel sind nur mit Menge 1 erlaubt; vorhandene Mengen bleiben unverändert erhalten."),
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
        if (!name || name === "minecraft:air" || count <= 0) {
            return { ok: true, item: null };
        }
        // Kein trim(): Führende/abschließende Leerzeichen sind gültige Bedrock-
        // Namensformatierung, genau wie in der Lore darunter. Ein Trim hier würde
        // den Namen jedes unberührten Items beim Speichern still verändern.
        const requestedCustomName = String(rawCustomName ?? "");
        const previousCustomName = sameItem ? String(previousItem?.display_name ?? "") : null;
        // Text inputs strip line breaks; textareas normalize CR/CRLF to LF.
        // An unchanged browser representation must retain the original NBT text.
        const preserveCustomName = previousCustomName !== null
            && (requestedCustomName === previousCustomName || requestedCustomName === previousCustomName.replace(/[\r\n]/g, ""));
        if (!preserveCustomName && requestedCustomName.length > maxDisplayName) {
            return { ok: false, error: t("Der Anzeigename darf höchstens {max} Zeichen enthalten.", { max: maxDisplayName }) };
        }
        const customName = preserveCustomName ? previousCustomName : requestedCustomName;
        const rawLoreText = String(rawLore ?? "").replace(/\r\n?/g, "\n");
        const previousLore = sameItem && Array.isArray(previousItem.lore)
            ? previousItem.lore.map(line => String(line))
            : null;
        const preserveLore = previousLore && rawLoreText === previousLore.join("\n").replace(/\r\n?/g, "\n");
        const requestedLore = rawLoreText === "" ? [] : rawLoreText.split("\n");
        if (!preserveLore && (requestedLore.length > maxLoreLines || requestedLore.some(line => line.length > maxLoreLineLength))) {
            return { ok: false, error: t("Die Beschreibung darf höchstens {lines} Zeilen mit jeweils {length} Zeichen enthalten.", { lines: maxLoreLines, length: maxLoreLineLength }) };
        }
        const lore = preserveLore ? cloneJson(previousLore) : requestedLore;
        const currentEnchantments = cloneJson(enchantments || []);

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
        const protectedNbtDropped = Boolean(previousItem && !sameItem && (previousItem.protected_nbt_dropped || itemRequiresOriginalNbt(previousItem)));
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

        // A new/replacement item must not resolve NBT from the disk's old slot
        // when the user clears it or changes away from and back to its old ID.
        if (!sameItem) builtItem.replace_original_nbt = true;
        if (protectedNbtDropped) {
            builtItem.protected_nbt_dropped = true;
            builtItem.previous_name = previousItem.protected_nbt_dropped ? previousItem.previous_name || previousItem.name : previousItem.name || "";
        }
        if (sameItem && previousItem) {
            const visibleUnchanged = ["slot", "name", "count", "damage"].every(key => previousItem[key] === builtItem[key])
                && (previousItem.display_name || "") === builtItem.display_name
                && JSON.stringify(previousItem.lore || []) === JSON.stringify(builtItem.lore || [])
                && JSON.stringify(previousItem.enchantments || []) === JSON.stringify(builtItem.enchantments || [])
                && !entityVariantEdit;
            if (visibleUnchanged) return { ok: true, item: cloneJson(previousItem) };
            [
                "has_protected_nbt",
                "has_preserved_nbt",
                "has_unknown_enchantments",
                "item_tag_opaque",
                "entity_variant",
                "entity_variant_edit",
                "entity_variant_state",
                "special_item",
                "special_edit",
                "protected_nbt_summary",
                "preserved_nbt_summary",
                "source_item_digest",
                "root_equipment_source_tag",
                "root_equipment_source_index",
                "root_equipment_read_only",
                "origin_world_mismatch",
                "replace_original_nbt",
                "protected_nbt_dropped",
                "previous_name",
                "special_nbt_defaulted",
                "special_nbt_requirement",
            ].forEach(key => {
                if (Object.prototype.hasOwnProperty.call(previousItem, key)) builtItem[key] = previousItem[key];
            });
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
        stackLimitVerified = true,
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
        if (!stackLimitVerified) return { ok: false, reason: "unverified_stack_limit" };
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
        buildItemForm,
        itemFormModel,
        applyItemFormConstraints,
        dataVariantSelectionPlan,
        entityVariantMetadataForItem,
        loreLinesFromText,
        normalizedItemName,
        restoreEquivalentItem,
        quickClearSlotPlan,
        quickMaxStackPlan,
        quickRepairSlotPlan,
        stackCountFromForm,
        itemDamageEditorModel,
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
        getCleanSnapshot = () => null,
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
        openSpecialEditor,
        specialItemModel,
        switchTab,
        slotDisplayName,
        detailItemLabel,
        pushUndo,
        finishUndoGroup = () => true,
        updateGridVisuals,
        setDirty,
        editingBlocked = () => false,
        getEditingBlockedReason = () => "",
        syncEditControls = () => {},
        onFormStateChanged = () => {},
        logStatus,
        recordAction,
        showToast,
        showConfirmDialog = async () => false,
    } = {}) {
        let currentEditingEnchantments = [];
        let currentEditingIsEnder = false;
        let lastDetailItemResetName = "";
        let currentEntityVariantModel = { visible: false, editable: false, kind: "" };
        let detailFormBaseline = null;
        let selectedItemVariant = null;
        let inputSession = null;
        let inputSessionTarget = null;
        const composingInputs = new Set();

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

        function detailFormState() {
            const entityControls = !currentEntityVariantModel.visible || !currentEntityVariantModel.editable ? []
                : currentEntityVariantModel.kind === "axolotl" ? [elements.detailAxolotlColor, elements.detailAxolotlAge]
                    : currentEntityVariantModel.kind === "tropical_fish"
                        ? [elements.detailTropicalFishPattern, elements.detailTropicalFishColor, elements.detailTropicalFishColor2]
                        : [];
            return JSON.stringify({
                selectedItemVariant,
                controls: [
                    elements.detailItemSearch, elements.detailCount, elements.detailDamage,
                    elements.detailCustomName, elements.detailLore, ...entityControls,
                ].map((control, index) => {
                    const value = control?.value ?? "";
                    if (index === 0) {
                        const name = logic.normalizedItemName(value);
                        return name === "minecraft:air" ? "" : name;
                    }
                    return [1, 2].includes(index) && String(value).trim() !== "" && Number.isFinite(Number(value))
                        ? Number(value) : value;
                }),
                enchantments: currentEditingEnchantments.map(({ id, lvl }) => [id, lvl]).sort(([a], [b]) => a - b),
            });
        }

        function detailContextKey(slotId, containerName) {
            return JSON.stringify([getWorldPath?.(), getCurrentPlayerKey?.(), containerName, slotId]);
        }

        function captureDetailFormBaseline(slotId, containerName) {
            detailFormBaseline = {
                context: detailContextKey(slotId, containerName), state: detailFormState(),
                item: slotSnapshot(slotId, containerName),
            };
            refreshDetailFormState();
        }

        function slotSnapshot(slotId, containerName) {
            const source = containerName === "ender_chest" ? enderChestInventory() : inventory();
            return JSON.stringify(source[slotId] || null);
        }

        function formSourceIsCurrent(slotId, containerName) {
            return detailFormBaseline?.context === detailContextKey(slotId, containerName)
                && detailFormBaseline.item === slotSnapshot(slotId, containerName);
        }

        function detailDraftState() {
            const target = currentDetailTarget();
            const changed = Boolean(detailFormBaseline && target
                && window.MCBESelectionState.selectedCount(getCurrentSelectionState?.()) === 1
                && detailFormBaseline.context === detailContextKey(target.slotId, target.containerName)
                && detailFormBaseline.state !== detailFormState());
            if (!changed) return { pending: false, canApply: false, error: "" };
            const name = logic.normalizedItemName(elements.detailItemSearch?.value);
            if (!name || name === "minecraft:air") {
                return { pending: true, canApply: false, error: t("Wähle einen Gegenstand oder verwende „Slot leeren“.") };
            }
            // Validate a projected draft without resetting fields or changing
            // the accepted inventory. Compare with what the form loaded, so
            // equivalent input cannot become a stale draft after an undo.
            const previousItem = JSON.parse(detailFormBaseline.item);
            const plan = logic.applySingleSlotPlan({
                buildResult: buildDetailItemFromForm(target.slotId, target.containerName, { preview: true }),
                previousItem,
                containerName: target.containerName,
            });
            // An empty slot can contain a partial draft (for example a name
            // entered before choosing an item). Keep that input guarded too.
            const pending = plan.reason !== "unchanged" || !previousItem;
            if (pending && !formSourceIsCurrent(target.slotId, target.containerName)) {
                return { pending: true, canApply: false, error: staleDetailFormError() };
            }
            return { pending, canApply: plan.ok && !isProtectedKnownSlot?.(target.slotId, target.containerName),
                error: plan.toast?.message || "" };
        }

        function hasPendingChanges() {
            return detailDraftState().pending;
        }

        function refreshDetailFormState() {
            const draft = detailDraftState();
            if (elements.detailFormError) {
                elements.detailFormError.textContent = draft.error;
                elements.detailFormError.hidden = !draft.error;
            }
            onFormStateChanged(draft);
        }

        function guardSlotChanges(targets = null) {
            applyCurrentSingleSlot();
            if (!hasPendingChanges()) return false;
            const current = currentDetailTarget();
            if (targets && !targets.some(target => target.slotId === current.slotId && target.containerName === current.containerName)) return false;
            showToast?.(t("Bitte korrigiere oder verwirf zuerst die offenen Eingaben im Slot-Editor. Die Aktion wurde nicht ausgeführt."), "warning", 4500);
            return true;
        }

        async function confirmDiscardChanges() {
            applyCurrentSingleSlot();
            if (!hasPendingChanges()) return true;
            const baseline = detailFormBaseline;
            const discard = await showConfirmDialog(
                t("Die Eingaben im Slot-Editor wurden noch nicht übernommen. Eingaben verwerfen?"),
                { okLabel: t("Eingaben verwerfen"), cancelLabel: t("Weiter bearbeiten") },
            );
            const target = currentDetailTarget();
            return discard && detailFormBaseline === baseline && target
                && baseline.context === detailContextKey(target.slotId, target.containerName);
        }

        function reconcileCurrentSlot() {
            const target = currentDetailTarget();
            if (!target || detailFormBaseline?.context !== detailContextKey(target.slotId, target.containerName)
                || formSourceIsCurrent(target.slotId, target.containerName)) return;
            if (hasPendingChanges()) {
                refreshDetailFormState();
                return;
            }
            // Visual refreshes must not reset an unrelated, unaccepted draft.
            loadSingleSlotEditor(target.slotId, target.isEnder, { preserveView: true });
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

        function applyDamageEditorModel(model) {
            if (elements.detailDamageGroup) elements.detailDamageGroup.style.display = model.mode === "durability" ? "" : "none";
            if (elements.detailDataVariantGroup) elements.detailDataVariantGroup.style.display = model.mode === "variant" ? "" : "none";
            if (elements.detailDamageLabel) elements.detailDamageLabel.textContent = t("Abnutzung");
            if (elements.detailDamage) elements.detailDamage.title = model.note;
            if (elements.detailDamageNote) {
                elements.detailDamageNote.textContent = model.note;
                elements.detailDamageNote.hidden = !model.note;
            }
            elements.detailDataVariant?.setAttribute?.("aria-invalid", String(Boolean(model.error)));
        }

        function damageEditorModel(itemName, damageValue, sourceItem) {
            const model = logic.itemDamageEditorModel({ catalog: itemCatalog, itemName, damageValue, sourceItem });
            const banner = itemCatalog.applyItemVariant?.({ ...sourceItem, name: itemName }, selectedItemVariant);
            if (itemName === "minecraft:banner" && itemCatalog.bannerType?.(banner) === 1) {
                model.mode = "none";
                model.note = t("Das ominöse Banner verwendet ein festes Motiv.");
            }
            return model;
        }

        function updateDataVariantEditor(itemName, damageValue = elements.detailDamage?.value, sourceItem = null) {
            const model = damageEditorModel(itemName, damageValue, sourceItem);
            applyDamageEditorModel(model);
            const variants = model.variants;
            if (model.mode !== "variant" || !elements.detailDataVariant) return;

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
            const original = logic.dataVariantSelectionPlan({ itemName, damageValue: sourceItem?.damage, variants, sourceItem });
            if (original.preserveUnknown) {
                options.push({
                    value: original.selectedDamage,
                    label: t("Unbekannter Datenwert {value} (wird beibehalten)", { value: original.selectedDamage }),
                });
            }
            replaceSelectOptions(elements.detailDataVariant, options);
            elements.detailDataVariant.value = String(selection.selectedDamage);
            if (elements.detailDamage) elements.detailDamage.value = selection.selectedDamage;
            if (elements.detailDataVariantLabel) {
                elements.detailDataVariantLabel.textContent = t("Variante");
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
            const damageModel = damageEditorModel(itemId, elements.detailDamage?.value, sourceItem);
            applyDamageEditorModel(damageModel);
            const formModel = logic.itemFormModel({ catalog: itemCatalog, rawName: itemId,
                rawCount: elements.detailCount?.value, rawDamage: elements.detailDamage?.value, previousItem: sourceItem });
            logic.applyItemFormConstraints(formModel, { count: elements.detailCount, damage: elements.detailDamage });
            const count = isEmpty
                ? 0
                : logic.stackCountFromForm({
                    rawCount: Number(elements.detailCount?.value),
                    maxStack,
                    stackLimitVerified: itemCatalog.hasVerifiedStackLimit(itemId),
                    previousItem: sourceItem,
                    itemName: itemId,
                });
            const damage = isEmpty ? 0 : damageModel.value;
            const usesDurability = !isEmpty && damageModel.mode === "durability";
            const damageLabel = isEmpty ? t("Abnutzung") : itemCatalog.itemDamageLabel(itemId);
            const loreLines = detailLoreLinesFromForm();
            const enchants = currentEditingEnchantments
                .map(e => {
                    const info = enchDb()[e.id];
                    const name = localizedEnchantmentName(info, e.id);
                    return `${name} ${e.lvl}`;
                })
                .slice(0, 4);
            const previewSource = sourceItem?.name === itemId ? sourceItem : {};
            const previewItem = itemCatalog.applyItemVariant?.({ ...previewSource, name: itemId, damage }, selectedItemVariant)
                || { ...previewSource, name: itemId, damage };
            const iconMeta = itemCatalog.getItemIconMeta(previewItem);
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
                    : entityDisplayName || detailItemLabel(itemId, "", damage, previewItem),
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
            refreshDetailFormState();
        }

        function loadSingleSlotEditor(slotId, isEnderChest = false, { preserveView = false } = {}) {
            finishInputSession();
            composingInputs.clear();
            selectedItemVariant = null;
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

            if (!preserveView) {
                switchTab?.("tabGeneral");
                if (!item.name) elements.detailItemSearch?.focus();
            }
            captureDetailFormBaseline(slotId, isEnderChest ? "ender_chest" : "inventory");
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

        function staleDetailFormError() {
            return t("Der Inhalt dieses Slots wurde inzwischen geändert. Deine Eingaben bleiben erhalten. Öffne den Slot erneut, bevor du Änderungen übernimmst.");
        }

        function buildDetailItemFromForm(slotId, containerName, { preview = false } = {}) {
            if (!preview && !formSourceIsCurrent(slotId, containerName)) {
                return { ok: false, error: staleDetailFormError() };
            }
            if (!preview) resetDetailFormForNewItem(elements.detailItemSearch?.value);
            const source = containerName === "ender_chest" ? enderChestInventory() : inventory();
            const name = logic.normalizedItemName(elements.detailItemSearch?.value);
            const previousItem = preview ? JSON.parse(detailFormBaseline.item) : source[slotId];
            const reset = preview && window.MCBEEnchantmentEditorLogic.manualItemResetPlan({
                previousName: previousItem?.name || "", nextName: name,
                lastResetName: lastDetailItemResetName, isValidItemId: itemCatalog.isAddableItemId,
            }).shouldReset;
            const entityState = reset ? { edit: null, metadata: null } : selectedEntityVariantState(previousItem, name);
            const result = logic.buildItemForm({
                catalog: itemCatalog, enchantmentsDb: enchDb(),
                slotId,
                containerName,
                previousItem,
                rawName: name,
                rawCount: reset ? 1 : elements.detailCount?.value,
                rawDamage: reset ? 0 : elements.detailDamage?.value,
                rawCustomName: reset ? "" : elements.detailCustomName?.value,
                rawLore: reset ? "" : elements.detailLore?.value,
                enchantments: reset ? [] : currentEditingEnchantments,
                currentPlayerKey: getCurrentPlayerKey?.(),
                worldPath: getWorldPath?.(),
                maxDisplayName,
                maxLoreLines,
                maxLoreLineLength,
                enchantmentLabel: id => localizedEnchantmentName(enchDb()[id], id),
                detailItemLabel,
                itemRequiresOriginalNbt,
                specialItemNbtRequirement: itemCatalog.specialItemNbtRequirement,
                entityVariantEdit: entityState.edit,
                entityVariantMetadata: entityState.metadata,
            });
            if (result.ok && result.item) {
                result.item = itemCatalog.applyItemVariant?.(result.item, reset ? null : selectedItemVariant) || result.item;
                result.item = logic.restoreEquivalentItem(result.item, inputSession?.initialItem);
                const clean = getCleanSnapshot();
                result.item = logic.restoreEquivalentItem(result.item, (containerName === "ender_chest" ? clean?.ec : clean?.inv)?.[slotId]);
            }
            return result;
        }

        function updateDetailQuickActions() {
            const target = currentDetailTarget();
            if (!elements.slotQuickActions || !target) return;
            const sourceItem = target.source?.[target.slotId] || null;
            const name = String(elements.detailItemSearch?.value || "").trim().toLowerCase();
            const isEmpty = !name || name === "minecraft:air";
            const maxStack = itemCatalog.getMaxStack(name);
            const damage = Number(elements.detailDamage?.value);
            const slotLabel = slotDisplayName(target.slotId, target.containerName);
            const previewSource = sourceItem?.name === name ? sourceItem : {};
            const previewItem = itemCatalog.applyItemVariant?.({ ...previewSource, name, damage }, selectedItemVariant)
                || { ...previewSource, name, damage };
            const model = window.MCBESlotDisplay.slotQuickActionsModel({
                slotLabel,
                isEmpty,
                itemLabel: detailItemLabel(name, elements.detailCustomName?.value || "", damage, previewItem),
                maxStack,
                stackLimitVerified: itemCatalog.hasVerifiedStackLimit(name),
                isValidItem: itemCatalog.isValidItemId(name),
                damage,
                repairableDamage: itemCatalog.itemUsesDurabilityDamage(name) && damage > 0,
                hasInspectableNbt: itemHasInspectableNbt(sourceItem),
            });
            model.clearDisabled = !sourceItem && isEmpty;
            window.MCBESlotDisplay.applySlotQuickActionsModel({
                title: elements.slotQuickTitle,
                subtitle: elements.slotQuickSubtitle,
                inspectButton: elements.btnInspectSlotNbt,
                clearButton: elements.btnQuickClearSlot,
                maxStackButton: elements.btnQuickMaxStack,
                repairButton: elements.btnQuickRepairSlot,
            }, model);
            if (elements.btnSpecialItem) {
                elements.btnSpecialItem.hidden = !specialItemModel?.kind({ name });
                elements.btnSpecialItem.textContent = specialItemModel?.label({ name }) || "";
                window.MCBEWriteStatusView.applyIntrinsicEditControlState(elements.btnSpecialItem, {
                    disabled: isProtectedKnownSlot(target.slotId, target.containerName),
                    blocked: editingBlocked(),
                    blockedTitle: getEditingBlockedReason(),
                });
            }
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

            container.appendChild(window.MCBEEnchantmentsView.enchantmentEditorElement({
                enchantmentsDb: enchDb(),
                itemName,
                enchantments: currentEditingEnchantments,
                isCompatible: itemCatalog.isEnchantmentCompatibleWithItem,
                canChange: () => !guardEditingAction(),
                onChange: entries => {
                    currentEditingEnchantments = entries;
                    updateEnchantmentActionButtons(itemName);
                    updateDetailPreview();
                    applyCurrentSingleSlot();
                },
            }));
        }

        function resetDetailFormForNewItem(itemName) {
            const target = currentDetailTarget();
            if (!target) return;
            const plan = window.MCBEEnchantmentEditorLogic.manualItemResetPlan({
                previousName: target.source?.[target.slotId]?.name || "",
                nextName: itemName,
                lastResetName: lastDetailItemResetName,
                isValidItemId: itemCatalog.isAddableItemId,
            });
            if (!plan.shouldReset) return;
            lastDetailItemResetName = plan.nextName;
            selectedItemVariant = null;
            const maxStack = itemCatalog.getMaxStack(itemName);
            if (elements.detailCount) elements.detailCount.value = Math.min(1, maxStack);
            if (elements.detailDamage) elements.detailDamage.value = 0;
            if (elements.detailCustomName) elements.detailCustomName.value = "";
            if (elements.detailLore) elements.detailLore.value = "";
            currentEditingEnchantments = [];
            updateDataVariantEditor(itemName, 0);
            const sourceItem = target.source?.[target.slotId] || null;
            updateEntityVariantEditor(itemName, logic.normalizedItemName(sourceItem?.name) === plan.nextName ? sourceItem : null);
            buildEnchantmentsList();
            updateDetailPreview();
        }

        function selectDetailItemVariant(item) {
            const damage = Number(item?.damage);
            if (!Number.isInteger(damage) || damage < 0 || !elements.detailDamage) return;
            elements.detailDamage.value = damage;
            selectedItemVariant = [0, 1].includes(item?.banner_type) ? { banner_type: item.banner_type } : null;
            const target = currentDetailTarget();
            updateDataVariantEditor(elements.detailItemSearch?.value, damage, target?.source?.[target.slotId] || null);
            updateDetailPreview();
        }

        function updateVariantEditorsForCurrentForm() {
            const target = currentDetailTarget();
            const itemName = logic.normalizedItemName(elements.detailItemSearch?.value);
            const sourceItem = target?.source?.[target.slotId] || null;
            const matchingSource = sourceItem && logic.normalizedItemName(sourceItem.name) === itemName
                ? sourceItem
                : null;
            const formItemName = logic.normalizedItemName(lastDetailItemResetName || sourceItem?.name);
            if (itemName === formItemName) {
                updateDataVariantEditor(itemName, elements.detailDamage?.value, matchingSource);
            } else {
                if (elements.detailDataVariantGroup) elements.detailDataVariantGroup.style.display = "none";
                if (elements.detailDamageGroup) elements.detailDamageGroup.style.display = "none";
            }
            // Search text can temporarily hide the controls, but must not
            // reload them from the original and discard an unaccepted edit.
            // Loading a slot or changing its item identity initializes them.
            if (elements.detailEntityVariantPanel) {
                elements.detailEntityVariantPanel.style.display = currentEntityVariantModel.visible && itemName === formItemName ? "" : "none";
            }
            updateDetailPreview();
        }

        function finishInputSession() {
            const completed = inputSession;
            inputSession = inputSessionTarget = null;
            if (!completed?.actionMessage) return;
            if (finishUndoGroup(completed) === false) return;
            logStatus?.(completed.statusMessage, "info");
            recordAction?.(completed.actionMessage, "edit");
        }

        function applyCurrentSingleSlot(options = {}) {
            if (!options.mergeKey) finishInputSession();
            if (composingInputs.size || editingBlocked() || !detailDraftState().canApply) return false;
            const target = window.MCBESelectionState.selectedSingleTarget(getCurrentSelectionState?.());
            return target ? applySingleChanges(target.slotId, options) : false;
        }

        function applySingleChanges(slotId, { mergeKey = null, quiet = false } = {}) {
            if (!quiet) finishInputSession();
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
                if (plan.reason === "unchanged") captureDetailFormBaseline(slotId, containerName);
                return;
            }

            const slotLabel = slotDisplayName(slotId, containerName);
            const actionMessage = plan.operation === "clear"
                ? t("{slot} geleert", { slot: slotLabel })
                : t("{slot}: {count}× {item} aktualisiert", {
                    slot: slotLabel, count: plan.item.count,
                    item: detailItemLabel(plan.item.name, plan.item.display_name, plan.item.damage, plan.item),
                });
            pushUndo?.(actionMessage, { mergeKey });
            if (plan.operation === "clear") {
                window.MCBEInventoryState.clearTargets([{ map: source, slotId }]);
            } else {
                source[slotId] = plan.item;
            }

            const nextItem = source[slotId] || null;
            updateDataVariantEditor(nextItem?.name || "", nextItem?.damage || 0, nextItem);
            updateEntityVariantEditor(nextItem?.name || "", nextItem);
            updateDetailPreview();
            captureDetailFormBaseline(slotId, containerName);
            updateGridVisuals?.();
            setDirty?.(true);
            const statusMessage = currentEditingIsEnder ? t("Enderchest-Slot {slot} aktualisiert – noch nicht gespeichert", { slot: slotId }) : t("Slot {slot} aktualisiert – noch nicht gespeichert", { slot: slotId });
            if (quiet && mergeKey === inputSession) {
                Object.assign(inputSession, { actionMessage, statusMessage });
            } else {
                logStatus?.(statusMessage, "info");
                recordAction?.(actionMessage, "edit");
            }
            return true;
        }

        function applyQuickClearSlot() {
            finishInputSession();
            if (guardEditingAction()) return;
            const target = currentDetailTarget();
            const plan = logic.quickClearSlotPlan({
                hasTarget: Boolean(target),
                protectedKnown: Boolean(target && isProtectedKnownSlot(target.slotId, target.containerName)),
                rawName: target?.source?.[target.slotId]?.name || elements.detailItemSearch?.value,
            });
            if (plan.showProtected) {
                showProtectedSlotMessage(target.slotId, target.containerName);
                return;
            }
            if (!plan.ok) {
                if (plan.refreshQuickActions) updateDetailQuickActions();
                return;
            }
            const actionMessage = t("{slot} geleert", { slot: slotDisplayName(target.slotId, target.containerName) });
            pushUndo?.(actionMessage);
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
            captureDetailFormBaseline(target.slotId, target.containerName);
            setDirty?.(true);
            logStatus?.(t("{label} geleert – noch nicht gespeichert", { label: slotDisplayName(target.slotId, target.containerName) }), "info");
            recordAction?.(actionMessage, "edit");
        }

        function applyQuickMaxStack() {
            if (guardEditingAction()) return;
            const target = currentDetailTarget();
            const name = logic.normalizedItemName(elements.detailItemSearch?.value);
            const plan = logic.quickMaxStackPlan({
                hasTarget: Boolean(target),
                rawName: name,
                maxStack: target ? itemCatalog.getMaxStack(name) : 64,
                stackLimitVerified: itemCatalog.hasVerifiedStackLimit(name),
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
            const damage = target ? Number(elements.detailDamage?.value) : 0;
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
                applyCurrentSingleSlot();
            });

            elements.btnClearAllEnch?.addEventListener("click", () => {
                if (guardEditingAction()) return;
                currentEditingEnchantments = [];
                buildEnchantmentsList();
                updateDetailPreview();
                applyCurrentSingleSlot();
            });
        }

        function wireFormPreview() {
            const fields = [elements.detailItemSearch, elements.detailCount, elements.detailDamage, elements.detailCustomName, elements.detailLore].filter(Boolean);
            const updateInput = event => {
                updateDetailPreview();
                // An ID may be a valid prefix of the item still being searched
                // for. Picker selection or leaving that field commits its ID.
                if (event.currentTarget === elements.detailItemSearch || event.isComposing) return;
                if (inputSessionTarget !== event.currentTarget) {
                    finishInputSession();
                    inputSessionTarget = event.currentTarget;
                    const target = currentDetailTarget();
                    inputSession = { initialItem: target?.source?.[target.slotId] || null };
                }
                applyCurrentSingleSlot({ mergeKey: inputSession, quiet: true });
            };
            fields.forEach(input => {
                input.addEventListener("input", updateInput);
                input.addEventListener("compositionstart", () => composingInputs.add(input));
                input.addEventListener("compositionend", event => { composingInputs.delete(input); updateInput(event); });
                input.addEventListener("blur", finishInputSession);
            });
            elements.detailItemSearch?.addEventListener("input", buildEnchantmentsList);
            elements.detailItemSearch?.addEventListener("input", updateVariantEditorsForCurrentForm);
            elements.detailDataVariant?.addEventListener("change", () => {
                const damage = Number.parseInt(elements.detailDataVariant.value, 10);
                if (Number.isInteger(damage) && elements.detailDamage) {
                    elements.detailDamage.value = damage;
                }
                updateDetailPreview();
                applyCurrentSingleSlot();
            });
            [
                elements.detailAxolotlColor,
                elements.detailAxolotlAge,
                elements.detailTropicalFishPattern,
                elements.detailTropicalFishColor,
                elements.detailTropicalFishColor2,
            ].filter(Boolean).forEach(select => select.addEventListener("change", () => {
                updateDetailPreview();
                applyCurrentSingleSlot();
            }));
        }

        function wireQuickActions() {
            elements.btnSpecialItem?.addEventListener("click", () => {
                const target = currentDetailTarget();
                if (!target || guardEditingAction()) return;
                const built = buildDetailItemFromForm(target.slotId, target.containerName);
                if (!built.ok) { showToast?.(built.error, "warning", 4000); return; }
                openSpecialEditor?.(target.slotId, target.containerName, built.item);
            });
            elements.btnQuickClearSlot?.addEventListener("click", applyQuickClearSlot);
            elements.btnInspectSlotNbt?.addEventListener("click", () => {
                const target = currentDetailTarget();
                const sourceItem = target?.source?.[target.slotId] || null;
                if (!target || !itemHasInspectableNbt(sourceItem)) {
                    showToast?.(t("Kein Gegenstand in diesem Slot."), "warning", 2500);
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
            wireQuickActions();
        }

        return {
            applyCurrentSingleSlot,
            buildEnchantmentsList,
            currentDetailTarget,
            firstEmptyWritableSlot,
            guardSlotChanges,
            hasPendingChanges,
            confirmDiscardChanges,
            loadSingleSlotEditor,
            reconcileCurrentSlot,
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
            detailDamageNote: doc.getElementById("detailDamageNote"),
            detailFormError: doc.getElementById("detailFormError"),
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
            btnSpecialItem: doc.getElementById("btnSpecialItem"),
            btnQuickMaxStack: doc.getElementById("btnQuickMaxStack"),
            btnQuickRepairSlot: doc.getElementById("btnQuickRepairSlot"),
            enchantsContainer: doc.getElementById("enchantsContainer"),
            btnMaxAllEnch: doc.getElementById("btnMaxAllEnch"),
            btnClearAllEnch: doc.getElementById("btnClearAllEnch"),
            diagCountEl: doc.getElementById("enchCount"),
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
            getCleanSnapshot: state.getCleanSnapshot,
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
            openSpecialEditor: helpers.openSpecialEditor,
            specialItemModel: helpers.specialItemModel,
            switchTab: helpers.switchTab,
            slotDisplayName: helpers.slotDisplayName,
            detailItemLabel: helpers.detailItemLabel,
            pushUndo: helpers.pushUndo,
            finishUndoGroup: helpers.finishUndoGroup,
            updateGridVisuals: helpers.updateGridVisuals,
            setDirty: helpers.setDirty,
            editingBlocked: helpers.editingBlocked,
            getEditingBlockedReason: helpers.getEditingBlockedReason,
            syncEditControls: helpers.syncEditControls,
            onFormStateChanged: helpers.onFormStateChanged,
            logStatus: helpers.logStatus,
            recordAction: helpers.recordAction,
            showToast: helpers.showToast,
            showConfirmDialog: helpers.showConfirmDialog,
        });
    }

    window.MCBESlotDetailLogic = {
        ...logic,
        applyItemAvailabilityBadge,
        localizedEnchantmentName,
        collectSlotDetailElements,
        createInventorySlotDetailController,
        createSlotDetailController,
    };
}());
