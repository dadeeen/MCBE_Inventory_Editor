(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function localizedPair(de, en) {
        return window.MCBEI18n?.localizedPair?.(de, en) || { primary: de || en || "", secondary: en && en !== de ? en : "" };
    }

    function itemIsVisiblePresent(item) {
        return !!(item && item.name && item.name !== "minecraft:air" && Number(item.count || 0) > 0);
    }

    function escapeHtml(value) {
        if (window.MCBEHtmlUtils?.escapeHtml) return window.MCBEHtmlUtils.escapeHtml(value);
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;")
            .replace(/`/g, "&#96;");
    }

    function escapeAttr(value) {
        if (window.MCBEHtmlUtils?.escapeAttr) return window.MCBEHtmlUtils.escapeAttr(value);
        return escapeHtml(value);
    }

    function slotAreaLabel(slotId, containerName = "inventory") {
        if (containerName === "ender_chest") return t("Enderchest {n}", { n: slotId + 1 });
        if (slotId === -106) return t("Schildhand");
        if (slotId === 103) return t("Helm");
        if (slotId === 102) return t("Brustplatte");
        if (slotId === 101) return t("Beinschienen");
        if (slotId === 100) return t("Stiefel");
        if (slotId >= 0 && slotId <= 8) return `Hotbar ${slotId + 1}`;
        if (slotId >= 9 && slotId <= 35) return t("Inventar {n}", { n: slotId - 8 });
        return `Slot ${slotId}`;
    }

    function slotDisplayName(slotId, containerName) {
        if (containerName === "ender_chest") return t("Enderchest {n}", { n: slotId + 1 });
        const armor = { "103": t("Kopf"), "102": t("Brust"), "101": t("Beine"), "100": t("Füße"), "-106": t("Schildhand") };
        if (Object.prototype.hasOwnProperty.call(armor, String(slotId))) return armor[String(slotId)];
        if (slotId >= 0 && slotId <= 8) return `Hotbar ${slotId + 1}`;
        if (slotId >= 9 && slotId <= 35) return t("Inventar {n}", { n: slotId - 8 });
        return `Slot ${slotId}`;
    }

    function slotButtonElement(slotId, containerName = "inventory", doc = document) {
        const slot = doc.createElement("div");
        const label = containerName === "ender_chest" ? t("Enderchest Slot {n}", { n: slotId + 1 }) : slotDisplayName(slotId, containerName);
        slot.className = "inventory-slot";
        if (containerName === "ender_chest") {
            slot.setAttribute("data-ender-slot", slotId);
        } else {
            slot.setAttribute("data-slot", slotId);
        }
        slot.dataset.tooltip = label;
        slot.setAttribute("role", "button");
        slot.setAttribute("tabindex", "0");
        slot.setAttribute("aria-label", label);
        return slot;
    }

    function slotItemFromElement(slotEl, { inventory = {}, enderChestInventory = {} } = {}) {
        if (!slotEl) return { slotId: 0, containerName: "inventory", item: null };
        const isEnder = slotEl.hasAttribute("data-ender-slot");
        const slotId = parseInt(slotEl.getAttribute(isEnder ? "data-ender-slot" : "data-slot"), 10);
        const containerName = isEnder ? "ender_chest" : "inventory";
        return {
            slotId,
            containerName,
            item: (isEnder ? enderChestInventory : inventory)[slotId],
        };
    }

    function damageText(
        itemName,
        damage,
        maxDamage,
        itemDamageLabel = () => t("Datenwert"),
        itemUsesDurabilityDamage = () => false,
    ) {
        const value = Math.max(0, Number(damage || 0));
        const label = itemDamageLabel(itemName);
        if (itemUsesDurabilityDamage(itemName)) {
            const maximum = Math.max(0, Number(maxDamage || 0));
            const remaining = Math.max(0, maximum - value);
            return `${t("Haltbarkeit")}: ${remaining} / ${maximum} · ${t("Abnutzung")}: ${value}`;
        }
        return `${label}: ${value}`;
    }

    function entityVariantDisplayName(item) {
        const variant = item?.entity_variant;
        if (!variant || typeof variant !== "object") return "";
        const de = variant.display_name_de || variant.label_de;
        const en = variant.display_name_en || variant.label_en;
        return String(localizedPair(de, en).primary).trim();
    }

    function entityVariantSearchText(item) {
        const variant = item?.entity_variant;
        if (!variant || typeof variant !== "object") return "";
        const parts = [
            variant.key,
            variant.display_name_de,
            variant.display_name_en,
            variant.label_de,
            variant.label_en,
        ];
        if (Array.isArray(variant.fields)) {
            variant.fields.forEach(field => {
                parts.push(field?.raw, field?.display_de, field?.display_en, field?.label_de, field?.label_en);
            });
        }
        return parts.filter(Boolean).join(" ");
    }

    function itemDisplayName(item, detailItemLabel = value => value, itemDamageLabel = () => t("Datenwert"), options = {}) {
        if (!item || !item.name || item.name === "minecraft:air") return t("Leer");
        const base = detailItemLabel(item.name, item.display_name || "", item.damage);
        const variant = entityVariantDisplayName(item);
        const count = Number.isFinite(Number(item.count)) ? Number(item.count) : 1;
        const label = itemDamageLabel(item.name);
        // Die Abnutzung bzw. der Datenwert gehört bewusst nur in die Detailzeilen (z. B.
        // Tooltip), nicht in den Titel. Andere Aufrufer (Änderungsübersichten)
        // behalten ihn über den Standard includeDamage=true.
        const includeDamage = options?.includeDamage !== false;
        const dmg = includeDamage && Number.isFinite(Number(item.damage)) && Number(item.damage) > 0 ? ` · ${label} ${Number(item.damage)}` : "";
        return `${base}${variant ? ` · ${variant}` : ""} x${count}${dmg}`;
    }

    function buildSlotTooltipEntries(slotId, containerName, item, protectedKnown = false, helpers = {}) {
        const slotLabel = slotAreaLabel(slotId, containerName);
        const technicalSlot = containerName === "ender_chest" ? t("Technischer Slot: Enderchest {n}", { n: slotId }) : t("Technischer Slot: {n}", { n: slotId });
        if (protectedKnown) {
            return [
                { text: t("Geschützter Slot"), kind: "title" },
                { text: slotLabel, kind: "tech" },
                { text: t("Geschützter NBT-Eintrag"), kind: "detail" },
                { text: t("Wird erhalten und kann nicht überschrieben werden."), kind: "detail" },
                { text: technicalSlot, kind: "detail" },
            ];
        }
        if (!itemIsVisiblePresent(item)) {
            return [
                { text: t("Leerer Slot"), kind: "title" },
                { text: slotLabel, kind: "tech" },
                { text: t("Klicken zum Bearbeiten oder zum Hinzufügen eines Items."), kind: "detail" },
                { text: technicalSlot, kind: "detail" },
            ];
        }
        const isKnownItemId = helpers.isKnownItemId || (() => true);
        const getMaxDamage = helpers.getMaxDamage || (() => 0);
        const detailItemLabel = helpers.detailItemLabel || (value => value);
        const itemDamageLabel = helpers.itemDamageLabel || (() => t("Datenwert"));
        const itemUsesDurabilityDamage = helpers.itemUsesDurabilityDamage || (() => false);
        const known = isKnownItemId(item.name);
        const count = Number(item.count || 0);
        const entries = [
            { text: itemDisplayName(item, detailItemLabel, itemDamageLabel, { includeDamage: false }), kind: "title" },
            { text: item.name || "", kind: "tech" },
            { text: slotLabel, kind: "detail" },
            { text: technicalSlot, kind: "detail" },
            { text: t("Menge: {count}", { count }), kind: "detail" },
            { text: damageText(item.name, item.damage, getMaxDamage(item.name), itemDamageLabel, itemUsesDurabilityDamage), kind: "damage" },
        ];
        const entityVariant = entityVariantDisplayName(item);
        if (entityVariant) {
            const kindLabel = String(localizedPair(item.entity_variant?.kind_label_de, item.entity_variant?.kind_label_en).primary || t("Entity-Variante")).trim();
            entries.push({ text: `${kindLabel}: ${entityVariant}`, kind: "detail" });
            const valueLabel = String(localizedPair(item.entity_variant?.value_label_de, item.entity_variant?.value_label_en).primary || t("Datenwert")).trim();
            if (Number.isInteger(Number(item.entity_variant?.variant))) entries.push({ text: `${valueLabel}: ${Number(item.entity_variant.variant)}`, kind: "detail" });
            if (Array.isArray(item.entity_variant?.fields)) {
                item.entity_variant.fields.forEach(field => {
                    const label = String(localizedPair(field?.label_de, field?.label_en).primary || field?.key || "").trim();
                    const value = String(localizedPair(field?.display_de, field?.display_en).primary || field?.raw || "").trim();
                    if (label && value) entries.push({ text: `${label}: ${value}`, kind: "detail" });
                });
            }
            if (item.entity_variant?.source) entries.push({ text: t("Variant-Quelle: {source}", { source: item.entity_variant.source }), kind: "detail" });
        }
        if (Array.isArray(item.enchantments) && item.enchantments.length) entries.push({ text: t("Verzauberungen: {count}", { count: item.enchantments.length }), kind: "enchant" });
        if (item.display_name) entries.push({ text: t("Custom-Name: {name}", { name: item.display_name }), kind: "detail" });
        if (Array.isArray(item.lore) && item.lore.length) entries.push({ text: t("Lore: {count} Zeile(n)", { count: item.lore.length }), kind: "detail" });
        if (!known) entries.push({ text: t("Unbekannt/future: wird bestmöglich erhalten."), kind: "detail" });
        if (item.has_unknown_enchantments) entries.push({ text: t("Unbekannte/future Verzauberungen vorhanden."), kind: "enchant" });
        if (item.has_protected_nbt) entries.push({ text: t("Zusätzliche geschützte NBT-Daten vorhanden."), kind: "detail" });
        else if (item.has_preserved_nbt) entries.push({ text: t("Bekannte Zusatz-NBT wird erhalten."), kind: "detail" });
        return entries;
    }

    function buildSlotTooltipLines(slotId, containerName, item, protectedKnown = false, helpers = {}) {
        return buildSlotTooltipEntries(slotId, containerName, item, protectedKnown, helpers).map(entry => entry.text);
    }

    function tooltipEntrySmallClass(kind) {
        if (kind === "damage") return ' class="tt-damage"';
        if (kind === "enchant") return ' class="tt-enchant"';
        return "";
    }

    function slotTooltipHtml(lines = []) {
        // Akzeptiert reine Strings (aria/dataset-Pfad, Tests) oder getaggte
        // { text, kind }-Einträge (Hover-Card) für hervorgehobene Detailzeilen.
        const entries = lines
            .map(line => (typeof line === "string" ? { text: line } : line))
            .filter(entry => entry && entry.text);
        const [title, tech, ...rest] = entries;
        return `
        <strong>${escapeHtml(title ? title.text : "Slot")}</strong>
        <span>${escapeHtml(tech ? tech.text : "")}</span>
        ${rest.map(entry => `<small${tooltipEntrySmallClass(entry.kind)}>${escapeHtml(entry.text)}</small>`).join("")}
    `;
    }

    function slotHoverCardElement(doc = document) {
        const card = doc.createElement("div");
        card.className = "slot-hover-card";
        card.style.display = "none";
        return card;
    }

    function detailPreviewIconHtml({ isEmpty = false, iconUrl = "", fallbackIcon = "□", iconTint = "" } = {}) {
        const tintAttr = iconTint ? ` data-icon-tint="${escapeAttr(iconTint)}"` : "";
        return !isEmpty && iconUrl
            ? `<img src="${escapeAttr(iconUrl)}" alt="" loading="lazy" data-icon-fallback="${escapeAttr(fallbackIcon || "📦")}"${tintAttr}>`
            : `<span>${escapeHtml(isEmpty ? "▫️" : (fallbackIcon || "📦"))}</span>`;
    }

    function detailLoreLinesFromForm(rawLore = "", { maxLoreLines = 8, maxLoreLineLength = 80, maxLines = null, maxLineLength = null } = {}) {
        const lineLimit = Number.isInteger(Number(maxLoreLines)) ? Number(maxLoreLines) : (Number.isInteger(Number(maxLines)) ? Number(maxLines) : 8);
        const charLimit = Number.isInteger(Number(maxLoreLineLength)) ? Number(maxLoreLineLength) : (Number.isInteger(Number(maxLineLength)) ? Number(maxLineLength) : 80);
        const text = String(rawLore ?? "").replace(/\r\n?/g, "\n");
        if (text === "") return [];
        return text
            .split("\n")
            .slice(0, Math.max(0, lineLimit))
            .map(line => line.length > charLimit ? line.slice(0, charLimit) : line);
    }

    function detailPreviewModel({
        itemId = "",
        displayName = "",
        isEmpty = false,
        known = true,
        count = 0,
        damage = 0,
        damageLabel = t("Datenwert"),
        usesDurability = false,
        maxDamage = 0,
        loreLines = [],
        enchantments = [],
        enchantmentTotal = 0,
        iconUrl = "",
        fallbackIcon = "📦",
        iconTint = "",
        enchantmentConflicts = [],
    } = {}) {
        const enchantmentSuffix = enchantmentTotal > enchantments.length ? ` +${enchantmentTotal - enchantments.length}` : "";
        // Nicht-blockierender Hinweis: Per NBT gesetzte Kombinationen
        // funktionieren im Spiel und bleiben speicherbar; Amboss/Zaubertisch
        // würden sie nur nicht zulassen.
        const conflictSuffix = enchantmentConflicts.length
            ? ` · ${t("⚠️ Laut Vanilla-Regeln inkompatibel: {list} (bleibt speicherbar)", { list: enchantmentConflicts.join("; ") })}`
            : "";
        return {
            isEmpty,
            isUnknown: Boolean(itemId) && !known,
            iconHtml: detailPreviewIconHtml({ isEmpty, iconUrl, fallbackIcon, iconTint }),
            nameText: displayName || t("Leerer Slot"),
            metaText: isEmpty
                ? t("Dieser Slot wird beim Anwenden geleert.")
                : `${itemId}${known ? "" : ` · ${t("unbekannt/future")}`} · ${count}x · ${
                    usesDurability
                        ? `${t("Haltbarkeit")} ${Math.max(0, Number(maxDamage || 0) - Number(damage || 0))}/${Math.max(0, Number(maxDamage || 0))} · ${t("Abnutzung")} ${Math.max(0, Number(damage || 0))}`
                        : `${damageLabel} ${damage}`
                }`,
            loreText: loreLines.length ? loreLines.join(" · ") : t("Keine Lore"),
            loreVisible: loreLines.length > 0,
            enchantmentsText: enchantments.length ? `✨ ${enchantments.join(" · ")}${enchantmentSuffix}${conflictSuffix}` : t("Keine Verzauberungen"),
            enchantmentsVisible: enchantments.length > 0,
        };
    }

    function applyDetailPreviewModel(elements = {}, model = {}) {
        const {
            preview = null,
            icon = null,
            name = null,
            meta = null,
            lore = null,
            enchantments = null,
        } = elements;
        if (preview) {
            preview.classList.toggle("empty", Boolean(model.isEmpty));
            preview.classList.toggle("unknown", Boolean(model.isUnknown));
        }
        if (icon) icon.innerHTML = model.iconHtml || "";
        if (name) name.textContent = model.nameText || "";
        if (meta) meta.textContent = model.metaText || "";
        if (lore) {
            lore.textContent = model.loreText || "";
            lore.style.display = model.loreVisible ? "block" : "none";
        }
        if (enchantments) {
            enchantments.textContent = model.enchantmentsText || "";
            enchantments.style.display = model.enchantmentsVisible ? "block" : "none";
        }
    }

    function slotQuickSubtitleHtml({ slotLabel = "", isEmpty = false, maxStack = "" } = {}) {
        const secondLine = isEmpty ? "&nbsp;" : `${t("Max-Stack")} ${escapeHtml(String(maxStack))}`;
        return `<span class="slot-quick-meta-line">${escapeHtml(slotLabel)}</span><span class="slot-quick-meta-line">${secondLine}</span>`;
    }

    function slotQuickActionsModel({
        slotLabel = "",
        isEmpty = false,
        itemLabel = "",
        maxStack = "",
        isValidItem = false,
        damage = 0,
        repairableDamage = null,
        hasInspectableNbt = false,
    } = {}) {
        const canRepairDamage = repairableDamage === null
            ? Number(damage) > 0
            : Boolean(repairableDamage);
        return {
            titleText: isEmpty ? t("Leerer Slot") : itemLabel,
            subtitleHtml: slotQuickSubtitleHtml({ slotLabel, isEmpty, maxStack }),
            inspectDisabled: !hasInspectableNbt,
            inspectTitle: hasInspectableNbt
                ? t("Geschützte Zusatzdaten für diesen Slot anzeigen")
                : t("Keine geschützten Zusatzdaten in diesem Slot erkannt"),
            clearDisabled: isEmpty,
            maxStackDisabled: isEmpty || !isValidItem,
            repairDisabled: isEmpty || !canRepairDamage,
        };
    }

    function applySlotQuickActionsModel(elements = {}, model = {}) {
        const {
            title = null,
            subtitle = null,
            inspectButton = null,
            clearButton = null,
            maxStackButton = null,
            repairButton = null,
        } = elements;
        if (title) title.textContent = model.titleText || "";
        if (subtitle) subtitle.innerHTML = model.subtitleHtml || "";
        if (inspectButton) {
            inspectButton.disabled = Boolean(model.inspectDisabled);
            inspectButton.title = model.inspectTitle || "";
        }
        const applyEditState = (control, disabled) => {
            if (!control) return;
            const gateAwareApply = window.MCBEWriteStatusView?.applyIntrinsicEditControlState;
            if (gateAwareApply) {
                gateAwareApply(control, { disabled, title: "" });
                return;
            }
            control.disabled = Boolean(disabled);
            control.title = "";
        };
        applyEditState(clearButton, model.clearDisabled);
        applyEditState(maxStackButton, model.maxStackDisabled);
        applyEditState(repairButton, model.repairDisabled);
    }

    function slotHoverPosition({ clientX = 0, clientY = 0, cardWidth = 0, cardHeight = 0, viewportWidth = 0, viewportHeight = 0, margin = 14, offset = 16 } = {}) {
        const maxLeft = viewportWidth - cardWidth - margin;
        const maxTop = viewportHeight - cardHeight - margin;
        return {
            left: Math.max(margin, Math.min(clientX + offset, maxLeft)),
            top: Math.max(margin, Math.min(clientY + offset, maxTop)),
        };
    }

    function createSlotDisplayFacade({ itemCatalog = {}, detailItemLabel = value => value } = {}) {
        const damageLabel = itemCatalog.itemDamageLabel || (() => t("Datenwert"));
        const itemUsesDurabilityDamage = itemCatalog.itemUsesDurabilityDamage || (() => false);
        const tooltipHelpers = {
            detailItemLabel,
            getMaxDamage: itemCatalog.getMaxDamage || (() => 0),
            itemDamageLabel: damageLabel,
            itemUsesDurabilityDamage,
            isKnownItemId: itemCatalog.isKnownItemId || (() => true),
        };
        return {
            buildSlotTooltipLines: (slotId, containerName, item, protectedKnown = false) => buildSlotTooltipLines(slotId, containerName, item, protectedKnown, tooltipHelpers),
            buildSlotTooltipEntries: (slotId, containerName, item, protectedKnown = false) => buildSlotTooltipEntries(slotId, containerName, item, protectedKnown, tooltipHelpers),
            itemDisplayName: item => itemDisplayName(item, detailItemLabel, damageLabel),
            itemHasRepairableDamage: item => itemIsVisiblePresent(item)
                && typeof itemCatalog.itemUsesDurabilityDamage === "function"
                && itemCatalog.itemUsesDurabilityDamage(item.name)
                && Number(item.damage || 0) > 0,
            itemIsVisiblePresent,
            slotAreaLabel,
            slotDisplayName,
        };
    }


    function createInventorySlotDisplayFacade({ itemCatalog = {} } = {}) {
        function detailItemLabel(itemName, customName = "", damage = null) {
            const custom = String(customName || "").trim();
            if (custom) return custom;
            const variantNames = itemCatalog.variantItemNamesForId?.(itemName, damage);
            const names = variantNames || itemCatalog.itemNamesForId?.(itemName);
            return localizedPair(names?.[0], names?.[1]).primary || itemName || t("Unbekanntes Item");
        }
        return {
            ...createSlotDisplayFacade({ itemCatalog, detailItemLabel }),
            detailItemLabel,
        };
    }

    window.MCBESlotDisplay = {
        applyDetailPreviewModel,
        applySlotQuickActionsModel,
        entityVariantDisplayName,
        entityVariantSearchText,
        createSlotDisplayFacade,
        createInventorySlotDisplayFacade,
        itemIsVisiblePresent,
        slotAreaLabel,
        slotDisplayName,
        slotButtonElement,
        slotItemFromElement,
        itemDisplayName,
        buildSlotTooltipEntries,
        buildSlotTooltipLines,
        detailPreviewModel,
        detailPreviewIconHtml,
        detailLoreLinesFromForm,
        slotHoverCardElement,
        slotHoverPosition,
        slotQuickActionsModel,
        slotQuickSubtitleHtml,
        slotTooltipHtml,
    };
}());
