(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function escapeHtml(value) {
        if (window.MCBEHtmlUtils?.escapeHtml) return window.MCBEHtmlUtils.escapeHtml(value);
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function unavailableEnchantmentsText({ hasExistingEnchantments = false, itemName = "" } = {}) {
        if (String(itemName || "").trim().toLowerCase() === "minecraft:book") {
            return t("Ein normales Buch speichert keine Verzauberungen. Wähle „Verzaubertes Buch“, um Verzauberungen zu bearbeiten.");
        }
        return hasExistingEnchantments
            ? t("Dieses Item ist nach Vanilla-Regeln nicht verzauberbar. Vorhandene ungewöhnliche Enchantment-NBT wird nur unverändert erhalten oder gezielt entfernt.")
            : t("Dieses Item ist nach Vanilla-Regeln nicht verzauberbar. Der Editor legt dafür keine neue Enchantment-NBT an.");
    }

    function unavailableEnchantmentsHtml(model = {}) {
        const text = unavailableEnchantmentsText(model);
        return `<div class="no-backups compact">${escapeHtml(text)}</div>`;
    }

    function unavailableEnchantmentsElement(model = {}, doc = document) {
        const note = doc.createElement("div");
        note.className = "no-backups compact";
        note.textContent = unavailableEnchantmentsText(model);
        return note;
    }

    function enchantedBookInfoText() {
        return t("Ein verzaubertes Buch kann mehrere Verzauberungen gemeinsam speichern. Ob sie auf ein Zielitem passen, entscheidet Minecraft erst beim Übertragen.");
    }

    function enchantedBookInfoElement(doc = document) {
        const note = doc.createElement("div");
        note.className = "no-backups compact";
        note.textContent = enchantedBookInfoText();
        return note;
    }

    function enchantmentRowModel({ id = 0, info = {}, activeEnchantment = null, compatible = true } = {}) {
        const isActive = Boolean(activeEnchantment);
        const currentLevel = isActive ? activeEnchantment.lvl : 1;
        const maxLevel = Math.max(1, Number(info.max_lvl) || 1);
        const controlsDisabled = !compatible;
        const localizedNames = window.MCBEI18n?.localizedPair?.(info.name_de, info.name_en);
        const primaryName = localizedNames
            ? localizedNames.primary || String(id)
            : info.name_de || info.name_en || String(id);
        const secondaryCandidate = localizedNames ? localizedNames.secondary : info.name_en || "";
        return {
            id,
            className: controlsDisabled ? "ench-row readonly" : "ench-row",
            primaryName,
            secondaryName: secondaryCandidate === primaryName ? "" : secondaryCandidate,
            maxLevel,
            sliderMax: maxLevel,
            currentLevel,
            isActive,
            controlsDisabled,
            levelDisabled: !isActive || controlsDisabled,
            compatibilitySuffix: controlsDisabled ? ` · ${t("unpassend, wird erhalten")}` : "",
        };
    }

    function enchantmentRowHtml(model = {}) {
        return `
            <div class="ench-info">
                <span class="ench-name">${escapeHtml(model.primaryName)}</span>
                <span class="ench-name-en">${model.secondaryName ? `${escapeHtml(model.secondaryName)} · ` : ""}Max: ${escapeHtml(model.maxLevel)}${escapeHtml(model.compatibilitySuffix || "")}</span>
            </div>
            <div class="ench-controls">
                <input type="range" class="ench-slider" min="1" max="${escapeHtml(model.sliderMax)}" value="${escapeHtml(model.currentLevel)}" ${model.levelDisabled ? "disabled" : ""} />
                <span class="ench-value">${escapeHtml(model.currentLevel)}</span>
                <input type="checkbox" class="ench-checkbox" ${model.isActive ? "checked" : ""} ${model.controlsDisabled ? "disabled" : ""} />
            </div>
        `;
    }

    function enchantmentRowElement(model = {}, doc = document) {
        const row = doc.createElement("div");
        row.className = model.className;
        row.innerHTML = enchantmentRowHtml(model);
        return row;
    }

    function enchantmentActionButtonsModel({
        enchantmentCount = 0,
        enchantable = false,
        maxableCount = 0,
    } = {}) {
        return {
            countText: String(enchantmentCount),
            maxAllDisabled: !enchantable || maxableCount === 0,
            maxAllTitle: enchantable
                ? t("Hebt vorhandene passende Verzauberungen auf ihr Vanilla-Maximallevel an")
                : t("Dieses Item ist nach Vanilla-Regeln nicht verzauberbar"),
            clearAllDisabled: enchantmentCount === 0,
        };
    }

    function applyEnchantmentActionButtonsModel(elements = {}, model = {}) {
        const {
            count = null,
            maxAllButton = null,
            clearAllButton = null,
        } = elements;
        if (count) count.innerText = model.countText || "0";
        if (maxAllButton) {
            maxAllButton.disabled = Boolean(model.maxAllDisabled);
            maxAllButton.title = model.maxAllTitle || "";
        }
        if (clearAllButton) clearAllButton.disabled = Boolean(model.clearAllDisabled);
    }

    window.MCBEEnchantmentsView = {
        applyEnchantmentActionButtonsModel,
        enchantedBookInfoElement,
        enchantedBookInfoText,
        enchantmentActionButtonsModel,
        enchantmentRowElement,
        enchantmentRowHtml,
        enchantmentRowModel,
        unavailableEnchantmentsElement,
        unavailableEnchantmentsHtml,
        unavailableEnchantmentsText,
    };
}());
