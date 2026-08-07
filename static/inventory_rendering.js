(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

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

    function itemVisualHtml({ protectedKnown = false, iconUrl = "", fallbackIcon = "□", iconTint = "" } = {}) {
        if (protectedKnown) return "<span>🔒</span>";
        const tintAttr = iconTint ? ` data-icon-tint="${escapeAttr(iconTint)}"` : "";
        return iconUrl
            ? `<img src="${escapeAttr(iconUrl)}" alt="" loading="lazy" data-icon-fallback="${escapeAttr(fallbackIcon || "□")}"${tintAttr}>`
            : `<span>${escapeHtml(fallbackIcon || "□")}</span>`;
    }

    function createInventoryRenderer(deps) {
        const {
            buildSlotTooltipLines,
            currentSelectionState,
            entityVariantDisplayName = () => "",
            entityVariantSearchText = () => "",
            getItemEmoji,
            getItemIconMeta,
            getItemIconTint = () => "",
            getMaxDamage,
            itemDamageLabel = () => "Datenwert",
            itemUsesDurabilityDamage = () => false,
            isKnownItemId,
            itemNamesForId,
            itemRequiresOriginalNbt,
            isProtectedKnownSlot,
            isSlotSelected,
            showSlotNumbers,
            slotAreaLabel,
            variantItemNamesForId = () => null,
        } = deps;

        function removeSlotChildren(slotEl) {
            [".item-visual", ".item-count", ".item-damage-bar", ".item-unknown-badge", ".slot-number-badge", ".empty-slot-action"]
                .forEach(selector => {
                    const child = slotEl.querySelector(selector);
                    if (child) child.remove();
                });
        }

        function renderSlot(slotEl, slotId, item) {
            removeSlotChildren(slotEl);

            slotEl.className = slotEl.className.replace(/\b(enchanted|selected|unknown-item|unknown-enchants|protected-nbt|protected-known-slot|empty-slot|local-icon-item)\b/g, "").trim();
            const isEnderSlot = slotEl.hasAttribute("data-ender-slot");
            const containerName = isEnderSlot ? "ender_chest" : "inventory";
            const protectedKnown = isProtectedKnownSlot(slotId, containerName);
            slotEl.dataset.slotLabel = slotAreaLabel(slotId, containerName);

            if (showSlotNumbers()) {
                const numberEl = document.createElement("div");
                numberEl.className = "slot-number-badge";
                numberEl.textContent = isEnderSlot ? `E${slotId}` : String(slotId);
                slotEl.appendChild(numberEl);
            }

            slotEl.setAttribute("draggable", (!protectedKnown && item && item.name && item.name !== "minecraft:air") ? "true" : "false");

            if (isSlotSelected(currentSelectionState(), slotId, containerName)) {
                slotEl.classList.add("selected");
            }

            const overlay = slotEl.querySelector(".slot-overlay");
            if (overlay) {
                overlay.style.display = ((item && item.name && item.name !== "minecraft:air" && item.count > 0) || protectedKnown) ? "none" : "";
            }

            if (protectedKnown && (!item || !item.name || item.name === "minecraft:air" || item.count <= 0)) {
                renderProtectedKnownSlot(slotEl, slotId, containerName, item);
                return;
            }

            if (item && item.name && item.name !== "minecraft:air" && item.count > 0) {
                renderItemSlot(slotEl, slotId, containerName, item);
            } else {
                renderEmptySlot(slotEl, slotId, containerName, item);
            }
        }

        function applyTooltip(slotEl, slotId, containerName, item, protectedKnown) {
            const tooltipText = buildSlotTooltipLines(slotId, containerName, item, protectedKnown).join("\n");
            slotEl.dataset.tooltip = tooltipText;
            slotEl.setAttribute("aria-label", tooltipText.replace(/\n/g, ". "));
            slotEl.removeAttribute("title");
        }

        function renderProtectedKnownSlot(slotEl, slotId, containerName, item) {
            slotEl.classList.add("protected-known-slot");

            const visualEl = document.createElement("div");
            visualEl.className = "item-visual";
            visualEl.innerHTML = itemVisualHtml({ protectedKnown: true });
            slotEl.appendChild(visualEl);

            const badgeEl = document.createElement("div");
            badgeEl.className = "item-unknown-badge";
            badgeEl.textContent = "NBT";
            badgeEl.setAttribute("aria-label", t("Geschützter nicht darstellbarer NBT-Eintrag; wird erhalten und kann nicht überschrieben werden"));
            slotEl.appendChild(badgeEl);

            applyTooltip(slotEl, slotId, containerName, item, true);
        }

        function renderItemSlot(slotEl, slotId, containerName, item) {
            const unknownItem = !isKnownItemId(item.name);
            const hasUnknownEnchantments = item.has_unknown_enchantments === true;
            const hasProtectedNbt = item.has_protected_nbt === true;

            if (unknownItem) slotEl.classList.add("unknown-item");
            if (hasUnknownEnchantments) slotEl.classList.add("unknown-enchants");
            if (hasProtectedNbt) slotEl.classList.add("protected-nbt");

            const visualEl = document.createElement("div");
            visualEl.className = "item-visual";
            const iconMeta = getItemIconMeta(item);
            const emoji = unknownItem ? "❓" : getItemEmoji(item.name);
            if (iconMeta && iconMeta.url) {
                visualEl.classList.add("has-local-icon");
                visualEl.innerHTML = itemVisualHtml({ iconUrl: iconMeta.url, fallbackIcon: emoji, iconTint: getItemIconTint(item) });
                slotEl.classList.add("local-icon-item");
            } else {
                visualEl.innerHTML = itemVisualHtml({ fallbackIcon: emoji });
            }
            slotEl.appendChild(visualEl);

            if (unknownItem || hasUnknownEnchantments || hasProtectedNbt) {
                const badgeEl = document.createElement("div");
                badgeEl.className = "item-unknown-badge";
                badgeEl.textContent = unknownItem ? "?" : (hasProtectedNbt ? "NBT" : "!");
                const badgeLabel = unknownItem
                    ? t("Item-ID ist nicht in der lokalen Datenbank bekannt")
                    : hasProtectedNbt
                        ? t("Enthält zusätzliche NBT-Daten, die nicht vollständig im Formular angezeigt werden, aber erhalten bleiben")
                        : t("Enthält unbekannte/future Verzauberungen, die beim Speichern erhalten bleiben");
                badgeEl.setAttribute("aria-label", badgeLabel);
                slotEl.appendChild(badgeEl);
            }

            const countEl = document.createElement("div");
            countEl.className = "item-count";
            countEl.innerText = item.count > 1 ? item.count : "";
            slotEl.appendChild(countEl);

            if (item.damage > 0 && itemUsesDurabilityDamage(item.name)) {
                const damageBar = document.createElement("div");
                damageBar.className = "item-damage-bar";
                const fillEl = document.createElement("div");
                fillEl.className = "item-damage-fill";

                const maxDmg = getMaxDamage(item.name);
                const pct = maxDmg > 0 ? Math.min((item.damage / maxDmg) * 100, 100) : 70;
                if (pct >= 80) fillEl.classList.add("low");
                else if (pct >= 50) fillEl.classList.add("med");

                fillEl.style.width = pct + "%";
                damageBar.appendChild(fillEl);
                slotEl.appendChild(damageBar);
            }

            if (item.enchantments && item.enchantments.length > 0) {
                slotEl.classList.add("enchanted");
            }

            applyTooltip(slotEl, slotId, containerName, item, false);
        }

        function renderEmptySlot(slotEl, slotId, containerName, item) {
            slotEl.classList.add("empty-slot");
            const actionEl = document.createElement("div");
            actionEl.className = "empty-slot-action";
            actionEl.textContent = "+ Item";
            slotEl.appendChild(actionEl);
            applyTooltip(slotEl, slotId, containerName, item, false);
        }

        function slotMatchesGridFilter(item, filterLower) {
            if (!filterLower) return true;
            if (!item || !item.name) return false;
            const knownItem = isKnownItemId(item.name);
            const itemNames = itemNamesForId(item.name);
            const variantNames = variantItemNamesForId(item, item.damage) || itemNames;
            const deName = knownItem ? String(itemNames[0] || "").toLowerCase() : "";
            const enName = knownItem ? String(itemNames[1] || "").toLowerCase() : "";
            const variantDeName = String(variantNames[0] || "").toLowerCase();
            const variantEnName = String(variantNames[1] || "").toLowerCase();
            const customName = String(item.display_name || "").toLowerCase();
            const entityVariantName = String(entityVariantDisplayName(item) || "").toLowerCase();
            const entityVariantKey = String(item.entity_variant?.key || "").toLowerCase();
            const entityVariantTerms = String(entityVariantSearchText(item) || "").toLowerCase();
            const unknownTerms = (!knownItem || itemRequiresOriginalNbt(item)) ? "unbekannt unknown future nbt geschützt protected zusatzdaten" : "";
            return item.name.toLowerCase().includes(filterLower)
                || deName.includes(filterLower)
                || enName.includes(filterLower)
                || variantDeName.includes(filterLower)
                || variantEnName.includes(filterLower)
                || customName.includes(filterLower)
                || entityVariantName.includes(filterLower)
                || entityVariantKey.includes(filterLower)
                || entityVariantTerms.includes(filterLower)
                || unknownTerms.includes(filterLower);
        }

        return {
            renderSlot,
            slotMatchesGridFilter,
        };
    }



    function createInventoryGridController(deps = {}) {
        const {
            doc = document,
            elements = {},
            rendererDeps = {},
            getInventory = () => ({}),
            getEnderChestInventory = () => ({}),
            getSelectedSlots = () => [],
            getSelectedEnderSlot = () => -1,
            setSelectedSlots = () => {},
            setSelectedEnderSlot = () => {},
            getGridFilter = () => "",
            setGridFilter = () => {},
            getWorldPath = () => "",
            getInventoryViewPreferences = () => null,
            buildSlotTooltipLines = () => [],
            buildSlotTooltipEntries = null,
            hideSlotInspector = () => {},
            showProtectedSlotMessage = () => {},
            loadSingleSlotEditor = () => {},
            renderEffectsList = () => {},
            loadAbilitiesUI = () => {},
            updateUndoButtons = () => {},
            renderPlayerInventorySummary = () => {},
            isProtectedKnownSlot = () => false,
            itemIsVisiblePresent = item => Boolean(item),
            ensureItemOrigin = item => item,
            pushUndo = () => {},
            recordAction = () => {},
            setDirty = () => {},
            slotDisplayName = (slotId, containerName) => `${containerName}:${slotId}`,
        } = deps;
        const {
            mainInventoryGrid = null,
            hotbarGrid = null,
            enderGrid = null,
            gridSearch = null,
            btnClearSelection = null,
            emptyState = null,
            multiSelectPanel = null,
            detailEditorPanel = null,
            dashboardPanel = null,
            selectedCountEl = null,
        } = elements;
        const inventoryRenderer = createInventoryRenderer({
            ...rendererDeps,
            currentSelectionState,
        });
        let slotHoverCard = null;

        function currentSelectionState() {
            return {
                selectedSlots: getSelectedSlots(),
                selectedEnderSlot: getSelectedEnderSlot(),
            };
        }

        function applySelectionState(selection) {
            setSelectedSlots(selection.selectedSlots || []);
            setSelectedEnderSlot(Number.isInteger(selection.selectedEnderSlot) ? selection.selectedEnderSlot : -1);
        }

        function getContainerMap(containerName) {
            return containerName === "ender_chest" ? getEnderChestInventory() : getInventory();
        }

        function moveOrCopySlot(fromContainerName, fromSlot, toContainerName, toSlot, copyMode = false) {
            const fromMap = getContainerMap(fromContainerName);
            const toMap = getContainerMap(toContainerName);
            const fromItem = fromMap[fromSlot];
            const toItem = toMap[toSlot];
            const plan = window.MCBESlotInteractionLogic.moveOrCopyPlan({
                fromContainerName,
                fromSlot,
                toContainerName,
                toSlot,
                fromProtected: isProtectedKnownSlot(fromSlot, fromContainerName),
                toProtected: isProtectedKnownSlot(toSlot, toContainerName),
                hasFromItem: Boolean(fromItem),
                hasToItem: Boolean(toItem),
                fromItemName: fromItem?.name || "",
                toItemName: toItem?.name || "",
                copyMode,
            });
            if (plan.reason === "protected_slot") {
                showProtectedSlotMessage(plan.protectedSlot, plan.protectedContainer);
                return false;
            }
            if (plan.reason === "not_wearable") {
                window.MCBEUiFeedback?.showToast?.(window.MCBEEquipmentRules.notWearableMessage(plan.slot, plan.itemName), "warning", 4000);
                return false;
            }
            if (!plan.ok) return false;

            pushUndo();
            const result = window.MCBEInventoryState.moveOrCopySlotState({
                fromMap,
                toMap,
                fromSlot,
                toSlot,
                fromContainerName,
                toContainerName,
                copyMode,
                ensureOrigin: ensureItemOrigin,
            });
            if (!result.changed) return false;
            if (result.action === "copy") {
                recordAction(`${slotDisplayName(fromSlot, fromContainerName)} nach ${slotDisplayName(toSlot, toContainerName)} kopiert`, "edit");
            } else {
                recordAction(`${slotDisplayName(fromSlot, fromContainerName)} mit ${slotDisplayName(toSlot, toContainerName)} getauscht/verschoben`, "edit");
            }
            updateGridVisuals();
            setDirty(true);
            return true;
        }

        function makeSlotDraggable(el, slotId, containerName = "inventory") {
            el.addEventListener("dragstart", (e) => {
                const sourceMap = getContainerMap(containerName);
                const plan = window.MCBESlotInteractionLogic.dragStartPlan({
                    slotId,
                    containerName,
                    protectedKnown: isProtectedKnownSlot(slotId, containerName),
                    hasItem: Boolean(sourceMap[slotId]),
                });
                if (!plan.ok) { e.preventDefault(); return; }
                e.dataTransfer.effectAllowed = plan.effectAllowed;
                e.dataTransfer.setData("application/x-mcbe-slot", plan.payload);
                e.dataTransfer.setData("text/plain", plan.payload);
                el.classList.add("dragging");
            });
            el.addEventListener("dragend", () => {
                el.classList.remove("dragging");
                doc.querySelectorAll(".inventory-slot").forEach(s => s.classList.remove("drag-over"));
            });
            el.addEventListener("dragover", (e) => {
                const plan = window.MCBESlotInteractionLogic.dragOverPlan({
                    protectedKnown: isProtectedKnownSlot(slotId, containerName),
                    copyMode: e.ctrlKey || e.metaKey,
                });
                if (!plan.ok) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = plan.dropEffect;
                el.classList.add("drag-over");
            });
            el.addEventListener("dragleave", () => {
                el.classList.remove("drag-over");
            });
            el.addEventListener("drop", (e) => {
                e.preventDefault();
                el.classList.remove("drag-over");
                const rawPayload = e.dataTransfer.getData("application/x-mcbe-slot") || e.dataTransfer.getData("text/plain");
                const plan = window.MCBESlotInteractionLogic.dropPlan({
                    rawPayload,
                    toContainerName: containerName,
                    toSlot: slotId,
                    copyMode: e.ctrlKey || e.metaKey,
                });
                if (!plan.ok) return;
                moveOrCopySlot(plan.fromContainerName, plan.fromSlot, plan.toContainerName, plan.toSlot, plan.copyMode);
            });
        }

        function focusSlotElement(containerName, slotId) {
            const selector = containerName === "ender_chest" ? `[data-ender-slot="${slotId}"]` : `[data-slot="${slotId}"]`;
            const el = doc.querySelector(selector);
            if (el && typeof el.focus === "function") el.focus();
        }

        function handleSlotKeyboard(event, slotId, containerName = "inventory") {
            const map = getContainerMap(containerName);
            const plan = window.MCBESlotInteractionLogic.keyboardSlotPlan({
                key: event.key,
                slotId,
                containerName,
                hasItem: Boolean(map[slotId]),
                protectedKnown: isProtectedKnownSlot(slotId, containerName),
            });
            if (plan.action === "activate" && plan.ok) {
                event.preventDefault();
                if (containerName === "ender_chest") handleEnderSlotClick(event, slotId);
                else handleSlotClick(event, slotId);
                return;
            }
            if (plan.action === "clear") {
                if (plan.ok) {
                    event.preventDefault();
                    pushUndo(`Slot ${slotDisplayName(slotId, containerName)} geleert`);
                    window.MCBEInventoryState.clearTargets([{ map, slotId }]);
                    applySelectionState(containerName === "ender_chest"
                        ? window.MCBESelectionState.selectEnderSlot(currentSelectionState(), slotId)
                        : window.MCBESelectionState.selectInventorySlot(currentSelectionState(), slotId));
                    updateGridVisuals();
                    updateSelectionUI();
                    setDirty(true);
                    recordAction(`${slotDisplayName(slotId, containerName)} per Tastatur geleert`, "edit");
                }
                return;
            }
            if (plan.action === "navigate") {
                event.preventDefault();
                if (plan.ok && plan.target) focusSlotElement(plan.target.container, plan.target.slot);
            }
        }

        function currentSlotItem(slotEl) {
            return window.MCBESlotDisplay.slotItemFromElement(slotEl, {
                inventory: getInventory(),
                enderChestInventory: getEnderChestInventory(),
            });
        }

        function ensureSlotHoverCard() {
            if (slotHoverCard) return slotHoverCard;
            slotHoverCard = window.MCBESlotDisplay.slotHoverCardElement();
            doc.body.appendChild(slotHoverCard);
            return slotHoverCard;
        }

        function moveSlotHoverCard(e) {
            if (!slotHoverCard || slotHoverCard.style.display === "none") return;
            const position = window.MCBESlotDisplay.slotHoverPosition({
                clientX: e.clientX,
                clientY: e.clientY,
                cardWidth: slotHoverCard.offsetWidth,
                cardHeight: slotHoverCard.offsetHeight,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
            });
            slotHoverCard.style.left = `${position.left}px`;
            slotHoverCard.style.top = `${position.top}px`;
        }

        function showSlotHover(e) {
            const slotEl = e.currentTarget;
            const { slotId, containerName, item } = currentSlotItem(slotEl);
            const protectedKnown = isProtectedKnownSlot(slotId, containerName);
            // Getaggte Einträge erlauben hervorgehobene Detailzeilen (Abnutzung
            // fett, Verzauberungen in Lavendel); Fallback auf reine Textzeilen.
            const lines = buildSlotTooltipEntries
                ? buildSlotTooltipEntries(slotId, containerName, item, protectedKnown)
                : buildSlotTooltipLines(slotId, containerName, item, protectedKnown).filter(Boolean);
            const card = ensureSlotHoverCard();
            card.innerHTML = window.MCBESlotDisplay.slotTooltipHtml(lines);
            card.style.display = "block";
            moveSlotHoverCard(e);
        }

        function hideSlotHover() {
            if (slotHoverCard) slotHoverCard.style.display = "none";
        }

        function attachSlotHover(slot) {
            slot.addEventListener("mouseenter", showSlotHover);
            slot.addEventListener("mousemove", moveSlotHoverCard);
            slot.addEventListener("mouseleave", hideSlotHover);
        }

        function createSlotElement(slotId) {
            const slot = window.MCBESlotDisplay.slotButtonElement(slotId, "inventory");
            slot.addEventListener("click", (e) => handleSlotClick(e, slotId));
            slot.addEventListener("keydown", (e) => handleSlotKeyboard(e, slotId, "inventory"));
            makeSlotDraggable(slot, slotId);
            attachSlotHover(slot);
            return slot;
        }

        function createEnderSlotElement(slotId) {
            const slot = window.MCBESlotDisplay.slotButtonElement(slotId, "ender_chest");
            slot.addEventListener("click", (e) => handleEnderSlotClick(e, slotId));
            slot.addEventListener("keydown", (e) => handleSlotKeyboard(e, slotId, "ender_chest"));
            makeSlotDraggable(slot, slotId, "ender_chest");
            attachSlotHover(slot);
            return slot;
        }

        function wireStaticSlots() {
            doc.querySelectorAll(".armor-slot, .offhand-slot").forEach(slotEl => {
                if (slotEl.dataset.mcbeSlotWired === "1") return;
                slotEl.dataset.mcbeSlotWired = "1";
                const slotId = parseInt(slotEl.getAttribute("data-slot"), 10);
                slotEl.setAttribute("role", "button");
                slotEl.setAttribute("tabindex", "0");
                slotEl.setAttribute("aria-label", slotDisplayName(slotId, "inventory"));
                slotEl.removeAttribute("title");
                slotEl.addEventListener("click", (e) => handleSlotClick(e, slotId));
                slotEl.addEventListener("keydown", (e) => handleSlotKeyboard(e, slotId, "inventory"));
                makeSlotDraggable(slotEl, slotId);
                attachSlotHover(slotEl);
            });
        }

        function buildGrids() {
            if (mainInventoryGrid) mainInventoryGrid.innerHTML = "";
            if (hotbarGrid) hotbarGrid.innerHTML = "";
            for (let i = 9; i <= 35; i++) mainInventoryGrid?.appendChild(createSlotElement(i));
            for (let i = 0; i <= 8; i++) hotbarGrid?.appendChild(createSlotElement(i));
            const targetEnderGrid = enderGrid || doc.querySelector(".ender-chest-grid");
            if (targetEnderGrid) {
                targetEnderGrid.innerHTML = "";
                for (let i = 0; i <= 26; i++) targetEnderGrid.appendChild(createEnderSlotElement(i));
            }
        }

        function renderSlots(slotEl, slotId, item) {
            inventoryRenderer.renderSlot(slotEl, slotId, item);
        }

        function slotMatchesGridFilter(item, filterLower) {
            return inventoryRenderer.slotMatchesGridFilter(item, filterLower);
        }

        function updateGridVisuals() {
            updateUndoButtons();
            getInventoryViewPreferences()?.applyInventoryViewPreferences?.();
            getInventoryViewPreferences()?.applyEnderChestVisibility?.();
            const filterLower = String(getGridFilter() || "").toLowerCase();
            doc.querySelectorAll("[data-slot]").forEach(slotEl => {
                const slotId = parseInt(slotEl.getAttribute("data-slot"), 10);
                const item = getInventory()[slotId];
                slotEl.style.opacity = (!filterLower || slotMatchesGridFilter(item, filterLower)) ? "1" : "0.2";
                renderSlots(slotEl, slotId, item);
            });
            doc.querySelectorAll("[data-ender-slot]").forEach(slotEl => {
                const slotId = parseInt(slotEl.getAttribute("data-ender-slot"), 10);
                const item = getEnderChestInventory()[slotId];
                slotEl.style.opacity = (!filterLower || slotMatchesGridFilter(item, filterLower)) ? "1" : "0.2";
                renderSlots(slotEl, slotId, item);
            });
            renderPlayerInventorySummary();
        }

        function handleSlotClick(e, slotId) {
            if (isProtectedKnownSlot(slotId, "inventory")) {
                showProtectedSlotMessage(slotId, "inventory");
                return;
            }
            applySelectionState(window.MCBESelectionState.selectInventorySlot(currentSelectionState(), slotId, Boolean(e && (e.ctrlKey || e.metaKey))));
            updateSelectionUI();
        }

        function handleEnderSlotClick(e, slotId) {
            if (isProtectedKnownSlot(slotId, "ender_chest")) {
                showProtectedSlotMessage(slotId, "ender_chest");
                return;
            }
            applySelectionState(window.MCBESelectionState.selectEnderSlot(currentSelectionState(), slotId));
            updateSelectionUI();
        }

        function clearSelection() {
            applySelectionState(window.MCBESelectionState.clearSelection());
            updateSelectionUI();
        }

        function updateSelectionUI() {
            doc.querySelectorAll(".inventory-slot").forEach(slotEl => {
                const isEnder = slotEl.hasAttribute("data-ender-slot");
                const slotId = parseInt(slotEl.getAttribute(isEnder ? "data-ender-slot" : "data-slot"), 10);
                const isSelected = window.MCBESelectionState.isSlotSelected(currentSelectionState(), slotId, isEnder ? "ender_chest" : "inventory");
                slotEl.classList.toggle("selected", isSelected);
            });
            if (emptyState) emptyState.style.display = "none";
            if (multiSelectPanel) multiSelectPanel.style.display = "none";
            if (detailEditorPanel) detailEditorPanel.style.display = "none";
            if (dashboardPanel) dashboardPanel.style.display = "none";
            hideSlotInspector();

            const { selectedSlots, selectedEnderSlot } = currentSelectionState();
            const totalSelected = window.MCBESelectionState.selectedCount(currentSelectionState());
            if (selectedEnderSlot >= 0 && selectedSlots.length > 0) {
                if (multiSelectPanel) multiSelectPanel.style.display = "flex";
                if (selectedCountEl) selectedCountEl.innerText = totalSelected;
            } else if (selectedEnderSlot >= 0) {
                if (detailEditorPanel) detailEditorPanel.style.display = "flex";
                loadSingleSlotEditor(selectedEnderSlot, true);
            } else if (selectedSlots.length === 0) {
                if (getWorldPath()) {
                    if (dashboardPanel) dashboardPanel.style.display = "flex";
                    renderEffectsList();
                    loadAbilitiesUI();
                } else if (emptyState) {
                    emptyState.style.display = "flex";
                }
            } else if (selectedSlots.length === 1) {
                if (detailEditorPanel) detailEditorPanel.style.display = "flex";
                loadSingleSlotEditor(selectedSlots[0], false);
            } else {
                if (multiSelectPanel) multiSelectPanel.style.display = "flex";
                if (selectedCountEl) selectedCountEl.innerText = selectedSlots.length;
            }
        }

        function wireControls() {
            wireStaticSlots();
            btnClearSelection?.addEventListener("click", clearSelection);
            gridSearch?.addEventListener("input", () => {
                setGridFilter(gridSearch.value.trim());
                updateGridVisuals();
            });
        }

        return {
            applySelectionState,
            attachSlotHover,
            buildGrids,
            clearSelection,
            createEnderSlotElement,
            createSlotElement,
            currentSelectionState,
            currentSlotItem,
            focusSlotElement,
            getContainerMap,
            handleEnderSlotClick,
            handleSlotClick,
            handleSlotKeyboard,
            hideSlotHover,
            makeSlotDraggable,
            moveOrCopySlot,
            renderSlots,
            showSlotHover,
            slotMatchesGridFilter,
            updateGridVisuals,
            updateSelectionUI,
            wireControls,
            wireStaticSlots,
        };
    }

    function collectInventoryGridElements(doc = document) {
        return {
            mainInventoryGrid: doc.querySelector(".main-inventory-grid"),
            hotbarGrid: doc.querySelector(".hotbar-grid"),
            enderGrid: doc.querySelector(".ender-chest-grid"),
            gridSearch: doc.getElementById("gridSearch"),
            btnClearSelection: doc.getElementById("btnClearSelection"),
            emptyState: doc.getElementById("emptyState"),
            multiSelectPanel: doc.getElementById("multiSelectPanel"),
            detailEditorPanel: doc.getElementById("detailEditorPanel"),
            dashboardPanel: doc.getElementById("dashboardPanel"),
            selectedCountEl: doc.getElementById("selectedCount"),
        };
    }

    function createConfiguredInventoryGridController({
        doc = document,
        itemCatalog = {},
        state = {},
        renderer = {},
        helpers = {},
    } = {}) {
        return createInventoryGridController({
            doc,
            elements: collectInventoryGridElements(doc),
            rendererDeps: {
                buildSlotTooltipLines: renderer.buildSlotTooltipLines,
                entityVariantDisplayName: window.MCBESlotDisplay.entityVariantDisplayName,
                entityVariantSearchText: window.MCBESlotDisplay.entityVariantSearchText,
                getItemEmoji: itemCatalog.getItemEmoji,
                getItemIconMeta: itemCatalog.getItemIconMeta,
                getItemIconTint: itemCatalog.getItemIconTint,
                getMaxDamage: itemCatalog.getMaxDamage,
                itemDamageLabel: itemCatalog.itemDamageLabel,
                itemUsesDurabilityDamage: itemCatalog.itemUsesDurabilityDamage,
                isKnownItemId: itemCatalog.isKnownItemId,
                itemNamesForId: itemCatalog.itemNamesForId,
                itemRequiresOriginalNbt: helpers.itemRequiresOriginalNbt,
                isProtectedKnownSlot: helpers.isProtectedKnownSlot,
                isSlotSelected: window.MCBESelectionState.isSlotSelected,
                showSlotNumbers: () => helpers.getInventoryViewPreferences?.()?.getShowSlotNumbers?.(),
                slotAreaLabel: renderer.slotAreaLabel,
                variantItemNamesForId: itemCatalog.variantItemNamesForId,
            },
            getInventory: state.getInventory,
            getEnderChestInventory: state.getEnderChestInventory,
            getSelectedSlots: state.getSelectedSlots,
            getSelectedEnderSlot: state.getSelectedEnderSlot,
            setSelectedSlots: state.setSelectedSlots,
            setSelectedEnderSlot: state.setSelectedEnderSlot,
            getGridFilter: state.getGridFilter,
            setGridFilter: state.setGridFilter,
            getWorldPath: state.getWorldPath,
            getInventoryViewPreferences: helpers.getInventoryViewPreferences,
            buildSlotTooltipLines: renderer.buildSlotTooltipLines,
            buildSlotTooltipEntries: renderer.buildSlotTooltipEntries,
            hideSlotInspector: helpers.hideSlotInspector,
            showProtectedSlotMessage: helpers.showProtectedSlotMessage,
            loadSingleSlotEditor: helpers.loadSingleSlotEditor,
            renderEffectsList: helpers.renderEffectsList,
            loadAbilitiesUI: helpers.loadAbilitiesUI,
            updateUndoButtons: helpers.updateUndoButtons,
            renderPlayerInventorySummary: helpers.renderPlayerInventorySummary,
            isProtectedKnownSlot: helpers.isProtectedKnownSlot,
            itemIsVisiblePresent: helpers.itemIsVisiblePresent,
            ensureItemOrigin: helpers.ensureItemOrigin,
            pushUndo: helpers.pushUndo,
            recordAction: helpers.recordAction,
            setDirty: helpers.setDirty,
            slotDisplayName: renderer.slotDisplayName,
        });
    }

    window.MCBEInventoryRendering = {
        collectInventoryGridElements,
        createConfiguredInventoryGridController,
        createInventoryRenderer,
        createInventoryGridController,
    };
}());
