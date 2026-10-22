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
            currentLevel,
            isActive,
            controlsDisabled,
            levelDisabled: !isActive || controlsDisabled || !Number.isInteger(currentLevel) || currentLevel < 1 || currentLevel > maxLevel,
            compatibilitySuffix: controlsDisabled ? ` · ${t("unpassend, wird erhalten")}` : "",
        };
    }

    function enchantmentRowHtml(model = {}) {
        const levels = Array.from({ length: model.maxLevel }, (_, i) => i + 1);
        if (!levels.includes(model.currentLevel)) levels.unshift(model.currentLevel);
        return `
            <div class="ench-info">
                <span class="ench-name">${escapeHtml(model.primaryName)}</span>
                <span class="ench-name-en">${model.secondaryName ? `${escapeHtml(model.secondaryName)} · ` : ""}Max: ${escapeHtml(model.maxLevel)}${escapeHtml(model.compatibilitySuffix || "")}</span>
            </div>
            <label class="ench-level-field">${escapeHtml(t("Stufe"))}
                <select class="ench-level" aria-label="${escapeHtml(t("Stufe"))}" ${model.levelDisabled ? "disabled" : ""}>
                    ${levels.map(level => `<option value="${escapeHtml(level)}" ${level === model.currentLevel ? "selected" : ""}>${escapeHtml(level)}</option>`).join("")}
                </select>
            </label>
            <button type="button" class="btn btn-secondary btn-sm ench-remove" aria-label="${escapeHtml(t("{name} entfernen", { name: model.primaryName }))}">${escapeHtml(t("Entfernen"))}</button>
        `;
    }

    function enchantmentRowElement(model = {}, doc = document) {
        const row = doc.createElement("div");
        row.className = model.className;
        row.dataset.enchantmentId = String(model.id);
        row.setAttribute("role", "group");
        row.setAttribute("aria-label", model.primaryName);
        row.innerHTML = enchantmentRowHtml(model);
        return row;
    }

    function enchantmentEditorElement({ itemName, enchantments = [], enchantmentsDb = {}, isCompatible,
        canChange = () => true, onChange }, doc = document) {
        const root = doc.createElement("div");
        root.className = "ench-editor";
        let entries = enchantments.map(entry => ({ ...entry }));
        const rows = doc.createElement("div");
        rows.className = "ench-rows";
        const addLabel = doc.createElement("label");
        addLabel.className = "ench-add";
        const caption = doc.createElement("span");
        caption.textContent = t("Verzauberung hinzufügen");
        const add = doc.createElement("select");
        add.setAttribute("aria-label", t("Verzauberung hinzufügen"));
        addLabel.append(caption, add);
        if (itemName === "minecraft:enchanted_book") root.append(enchantedBookInfoElement(doc));
        root.append(rows, addLabel);
        const publish = () => onChange(entries.map(entry => ({ ...entry })));
        function draw() {
            rows.replaceChildren();
            if (!entries.length) {
                const empty = doc.createElement("p");
                empty.className = "ench-empty";
                empty.textContent = t("Keine Verzauberungen.");
                rows.append(empty);
            }
            entries.forEach((entry, index) => {
                const info = enchantmentsDb[entry.id];
                const model = enchantmentRowModel({ id: entry.id, info: info || {}, activeEnchantment: entry,
                    compatible: Boolean(info) && isCompatible(entry.id, itemName) });
                const row = enchantmentRowElement(model, doc);
                const level = row.querySelector(".ench-level");
                level.addEventListener("change", () => {
                    const next = Number(level.value);
                    if (model.levelDisabled || !Number.isInteger(next) || next < 1 || next > model.maxLevel || !canChange()) {
                        level.value = String(entries[index].lvl); return;
                    }
                    entries[index] = { ...entries[index], lvl: next };
                    publish();
                });
                row.querySelector(".ench-remove").addEventListener("click", () => {
                    if (!canChange()) return;
                    entries.splice(index, 1); publish(); draw();
                    const remaining = rows.querySelectorAll(".ench-remove");
                    const next = remaining[Math.min(index, remaining.length - 1)] || (!addLabel.hidden && add);
                    if (next) next.focus();
                    else { root.tabIndex = -1; root.focus(); }
                });
                rows.append(row);
            });
            const available = window.MCBEEnchantmentEditorLogic.enchantmentRowsForItem({
                itemName, enchantmentsDb, activeEnchantments: entries, isCompatible,
            }).filter(row => row.compatible && !row.activeEnchantment);
            add.replaceChildren();
            for (const [value, label] of [["", t("Bitte wählen")], ...available.map(row =>
                [row.id, enchantmentRowModel({ id: row.id, info: row.info }).primaryName])]) {
                const option = doc.createElement("option"); option.value = value; option.textContent = label; add.append(option);
            }
            addLabel.hidden = !available.length;
        }
        add.addEventListener("change", () => {
            const id = Number(add.value);
            if (!add.value || !enchantmentsDb[id] || !isCompatible(id, itemName)
                || entries.some(entry => Number(entry.id) === id) || !canChange()) { add.value = ""; return; }
            entries.push({ id, lvl: 1 }); publish(); draw();
            rows.lastElementChild.querySelector(".ench-level").focus();
        });
        draw();
        return root;
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
        enchantmentEditorElement,
        enchantmentRowElement,
        enchantmentRowHtml,
        enchantmentRowModel,
        unavailableEnchantmentsElement,
        unavailableEnchantmentsHtml,
        unavailableEnchantmentsText,
    };
}());
