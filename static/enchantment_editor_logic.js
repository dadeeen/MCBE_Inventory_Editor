(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function cloneJson(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function normalizedItemName(rawName) {
        return String(rawName || "").trim().toLowerCase();
    }

    function localizedEnchantmentName(info = {}) {
        const localized = window.MCBEI18n?.localizedPair?.(info.name_de, info.name_en);
        return localized ? localized.primary : info.name_de || info.name_en || "";
    }

    function countMaxableEnchantments({
        enchantments = [],
        itemName = "",
        enchantmentsDb = {},
        isCompatible = () => false,
    } = {}) {
        return enchantments.filter(enchantment => {
            const id = Number(enchantment.id);
            const info = enchantmentsDb[id];
            return info && isCompatible(id, itemName) && Number(enchantment.lvl || 0) < Number(info.max_lvl || 1);
        }).length;
    }

    function enchantmentRowsForItem({
        enchantmentsDb = {},
        itemName = "",
        activeEnchantments = [],
        isCompatible = () => false,
    } = {}) {
        const activeIds = new Set(activeEnchantments.map(enchantment => Number(enchantment.id)));
        return Object.entries(enchantmentsDb)
            .filter(([idStr]) => isCompatible(parseInt(idStr, 10), itemName) || activeIds.has(parseInt(idStr, 10)))
            .sort((a, b) => window.MCBEI18n?.compare?.(localizedEnchantmentName(a[1]), localizedEnchantmentName(b[1]))
                ?? localizedEnchantmentName(a[1]).localeCompare(localizedEnchantmentName(b[1]), undefined, { sensitivity: "base" }))
            .map(([idStr, info]) => {
                const id = parseInt(idStr, 10);
                return {
                    id,
                    info,
                    activeEnchantment: activeEnchantments.find(enchantment => Number(enchantment.id) === id) || null,
                    compatible: isCompatible(id, itemName),
                };
            });
    }

    function updateEnchantmentLevel(enchantments = [], id, level) {
        const numericId = Number(id);
        const numericLevel = parseInt(level, 10);
        return enchantments.map(enchantment => (
            Number(enchantment.id) === numericId
                ? { ...enchantment, lvl: numericLevel }
                : enchantment
        ));
    }

    function toggleEnchantment(enchantments = [], { id, checked = false, level = 1 } = {}) {
        const numericId = Number(id);
        if (checked) {
            if (enchantments.some(enchantment => Number(enchantment.id) === numericId)) return cloneJson(enchantments);
            return [...cloneJson(enchantments), { id: numericId, lvl: parseInt(level, 10) }];
        }
        return cloneJson(enchantments).filter(enchantment => Number(enchantment.id) !== numericId);
    }

    function manualItemResetPlan({
        previousName = "",
        nextName = "",
        lastResetName = "",
        isValidItemId = () => false,
    } = {}) {
        const previous = normalizedItemName(previousName);
        const next = normalizedItemName(nextName);
        if (!previous || !next || next === previous || next === "minecraft:air") return { shouldReset: false };
        if (!isValidItemId(next) || next === normalizedItemName(lastResetName)) return { shouldReset: false };
        return { shouldReset: true, nextName: next };
    }

    function maxAllEnchantmentsPlan({
        itemName = "",
        enchantments = [],
        enchantmentsDb = {},
        isEnchantableItem = () => false,
        isCompatible = () => false,
    } = {}) {
        const normalizedName = normalizedItemName(itemName);
        if (!isEnchantableItem(normalizedName)) {
            return {
                ok: false,
                toast: {
                    message: t("Dieses Item ist nach Vanilla-Regeln nicht verzauberbar."),
                    type: "warning",
                    ms: 3000,
                },
            };
        }
        let changed = 0;
        const nextEnchantments = enchantments.map(enchantment => {
            const id = Number(enchantment.id);
            const info = enchantmentsDb[id];
            if (!info || !isCompatible(id, normalizedName)) return { ...enchantment };
            const maxLevel = Number(info.max_lvl || 1);
            const currentLevel = Number(enchantment.lvl || 1);
            if (currentLevel >= maxLevel) return { ...enchantment };
            changed += 1;
            return { ...enchantment, lvl: maxLevel };
        });
        return {
            ok: true,
            enchantments: nextEnchantments,
            changed,
            toast: changed ? null : {
                message: t("Keine vorhandene passende Verzauberung muss erhöht werden."),
                type: "warning",
                ms: 2500,
            },
        };
    }

    window.MCBEEnchantmentEditorLogic = {
        countMaxableEnchantments,
        enchantmentRowsForItem,
        manualItemResetPlan,
        maxAllEnchantmentsPlan,
        normalizedItemName,
        toggleEnchantment,
        updateEnchantmentLevel,
    };
}());
