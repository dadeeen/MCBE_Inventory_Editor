(function () {
    "use strict";

    function createItemBrowserController({
        elements = {},
        itemBrowserLogic = window.MCBEItemBrowserLogic,
        getItemsDb = () => ({}),
        getAddableItems = () => null,
        getBlockOnlyItems = () => null,
        getBlockItems = () => null,
        getItemEmoji = () => "□",
        getItemIconMeta = () => null,
        getItemIconTint = () => "",
        getItemVariantsForId = () => [],
        getItemAvailability = () => null,
        getEquipmentTargets = () => [],
        equipmentRules = window.MCBEEquipmentRules,
        onDetailItemChanged = () => {},
        onDetailItemVariantSelected = () => {},
        onApplyDetailItem = () => {},
        documentObj = document,
    } = {}) {
        const {
            detailInput,
            detailAutocomplete,
            bulkInput,
            bulkAutocomplete,
            overlay,
            grid,
            searchInput,
            categorySelect,
            sortSelect,
            count,
            closeButton,
            detailBrowserButton,
            bulkBrowserButton,
            title,
        } = elements;
        let browserActiveInput = null;
        let picker = null;
        const autocompleteOptions = new WeakMap();
        const autocompletes = new Map();
        const pendingInputs = new WeakSet();
        const deferredAutocompleteHides = new Set();
        let returnFocusElement = null;
        let selectingAutocompleteItem = false;
        let pageScrollLocked = false;
        let pageScrollPosition = 0;

        function isDetailInput(inputEl) {
            return inputEl && inputEl === detailInput;
        }

        function equipmentTargets(inputEl) {
            if (inputEl !== detailInput && inputEl !== bulkInput) return [];
            return getEquipmentTargets(isDetailInput(inputEl))
                .filter(target => equipmentRules?.isEquipmentSlot(target.slotId, target.container));
        }

        function allowedForInput(id, inputEl) {
            return equipmentTargets(inputEl).every(target => equipmentRules.itemAllowedInEquipmentSlot(target.slotId, id));
        }

        function browserTitle(inputEl) {
            const slots = [...new Set(equipmentTargets(inputEl).map(target => Number(target.slotId)))];
            const titles = { 103: "Helm auswählen", 102: "Brustausrüstung auswählen", 101: "Beinausrüstung auswählen", 100: "Stiefel auswählen", [-106]: "Nebenhand auswählen" };
            const text = slots.length === 1 ? titles[slots[0]] : "📖 Item-Browser";
            return window.t ? window.t(text) : text;
        }

        function autocompleteMatches(query, inputEl = detailInput, limit = 10) {
            return itemBrowserLogic.autocompleteMatches(
                getItemsDb(),
                query,
                Infinity,
                getBlockOnlyItems(),
                getAddableItems(),
                isDetailInput(inputEl) || autocompleteOptions.get(inputEl)?.includeVariants ? getItemVariantsForId : null,
            ).filter(item => allowedForInput(item.id, inputEl)).slice(0, limit);
        }

        function itemIconTarget(id, damage, metadata = null) {
            const item = Number.isInteger(Number(damage)) && damage !== null && damage !== undefined && damage !== ""
                ? { name: id, damage: Number(damage) }
                : id;
            if (id === "minecraft:banner" && metadata?.banner_type === 1) return { name: id, damage: 15, special_edit: { kind: "banner", data: { type: 1, patterns: [] } } };
            return item;
        }

        function dispatchInput(inputEl, options = {}) {
            inputEl.dispatchEvent(new Event("input", options));
        }

        function selectAutocompleteItem(inputEl, listEl, item, options = {}) {
            if (!inputEl || !listEl || !item || !item.id) return;
            if (!allowedForInput(item.id, inputEl)) return;
            if (options.selectionReason?.(item.id, item)) return;
            pendingInputs.delete(inputEl);
            deferredAutocompleteHides.delete(listEl);
            listEl.style.display = "none";
            listEl.innerHTML = "";
            if (options.onSelect) {
                options.onSelect(item);
                inputEl.focus?.({ preventScroll: true });
                return;
            }
            inputEl.value = item.id;

            if (isDetailInput(inputEl)) {
                const nextName = String(item.id || "").trim().toLowerCase();
                if (nextName) {
                    onDetailItemChanged(nextName);
                }
                if (Number.isInteger(Number(item.damage))) {
                    onDetailItemVariantSelected(item);
                }
            }

            // Das gesendete "input"-Event darf die eben getroffene Auswahl nicht
            // erneut als Vorschlagsliste öffnen.
            selectingAutocompleteItem = true;
            try {
                dispatchInput(inputEl, { bubbles: true });
            } finally {
                selectingAutocompleteItem = false;
            }
            inputEl.focus?.({ preventScroll: true });
            if (options.applyOnSelect && isDetailInput(inputEl)) {
                onApplyDetailItem();
            }
        }

        function setupAutocomplete(inputEl, listEl, options = {}) {
            if (!inputEl || !listEl) return;
            autocompleteOptions.set(inputEl, options);
            autocompletes.set(inputEl, listEl);
            function dismissAutocomplete(event) {
                if (event.key !== "Escape" || listEl.style.display !== "block") return false;
                event.preventDefault();
                event.stopPropagation();
                listEl.style.display = "none";
                listEl.innerHTML = "";
                inputEl.focus?.({ preventScroll: true });
                return true;
            }
            listEl.addEventListener?.("keydown", dismissAutocomplete);
            inputEl.addEventListener("input", event => {
                deferredAutocompleteHides.delete(listEl);
                if (!selectingAutocompleteItem) pendingInputs.add(inputEl);
                const query = event.target.value.toLowerCase().trim();
                listEl.innerHTML = "";

                if (!query || selectingAutocompleteItem) {
                    listEl.style.display = "none";
                    return;
                }

                // Limit only the rendered page, never the searchable result set.
                // Otherwise broad queries silently lose every match after ten.
                const matches = autocompleteMatches(query, inputEl, Infinity);

                if (matches.length > 0) {
                    const appendMatches = (start, end) => {
                        let firstRow = null;
                        matches.slice(start, end).forEach(item => {
                            const fallbackIcon = getItemEmoji(item.id) || "□";
                            const iconMeta = getItemIconMeta(itemIconTarget(item.id, item.damage, item));
                            const row = itemBrowserLogic.autocompleteItemElement(
                                item,
                                {
                                    iconUrl: iconMeta?.url || "",
                                    fallbackIcon,
                                    iconTint: getItemIconTint(item.id) || "",
                                },
                                getItemAvailability(item.id, item.damage),
                            );

                            row.addEventListener("click", () => {
                                selectAutocompleteItem(inputEl, listEl, item, options);
                            });
                            markUnavailable(row, options.selectionReason?.(item.id, item));

                            listEl.appendChild(row);
                            firstRow ||= row;
                        });
                        return firstRow;
                    };
                    const chunkPlanFor = typeof itemBrowserLogic.browserRenderChunkPlan === "function"
                        ? renderedCount => itemBrowserLogic.browserRenderChunkPlan({
                            totalCount: matches.length, renderedCount, chunkSize: 10,
                        })
                        : renderedCount => ({ start: renderedCount, end: matches.length, hasMore: false });
                    let plan = chunkPlanFor(0);
                    appendMatches(plan.start, plan.end);
                    if (plan.hasMore) {
                        const moreButton = documentObj.createElement("button");
                        moreButton.type = "button";
                        moreButton.className = "autocomplete-load-more";
                        moreButton.textContent = plan.buttonLabel;
                        moreButton.addEventListener("click", event => {
                            // Removing the final button must not make the document
                            // click handler treat this as a click outside the list.
                            event.stopPropagation();
                            const hadFocus = documentObj.activeElement === moreButton;
                            moreButton.remove();
                            plan = chunkPlanFor(plan.end);
                            const firstRow = appendMatches(plan.start, plan.end);
                            if (plan.hasMore) {
                                moreButton.textContent = plan.buttonLabel;
                                listEl.appendChild(moreButton);
                            }
                            if (hadFocus) {
                                firstRow?.focus({ preventScroll: true });
                                firstRow?.scrollIntoView({ block: "nearest" });
                            }
                        });
                        listEl.appendChild(moreButton);
                    }
                    listEl.style.display = "block";
                    // A hidden list ignores scrollTop; reset after showing it.
                    listEl.scrollTop = 0;
                } else {
                    listEl.style.display = "none";
                }
            });

            inputEl.addEventListener("keydown", event => {
                if (dismissAutocomplete(event)) return;
                if (event.key !== "Enter") return;
                const query = String(inputEl.value || "").toLowerCase().trim();
                if (!query) return;
                // Mehrdeutige Namen auch jenseits der sichtbaren Vorschläge erkennen.
                const matches = autocompleteMatches(query, inputEl, Infinity);
                const selected = itemBrowserLogic.autocompleteSelection(matches, query);
                if (!selected) return;
                event.preventDefault();
                selectAutocompleteItem(inputEl, listEl, selected, options);
            });
            return () => { autocompletes.delete(inputEl); autocompleteOptions.delete(inputEl); pendingInputs.delete(inputEl); deferredAutocompleteHides.delete(listEl); };
        }

        function hideAutocompleteLists(event) {
            autocompletes.forEach((list, input) => {
                if (!input || !list) return;
                if (event.target !== input && !list.contains(event.target)) {
                    const options = autocompleteOptions.get(input);
                    // Keep inline results in the layout until the pointer click
                    // completes, so hiding them cannot move its target button.
                    if (options?.inline && (event.type === "pointerdown" || event.type === "focusin" && deferredAutocompleteHides.has(list))) {
                        deferredAutocompleteHides.add(list);
                    } else {
                        list.style.display = "none";
                        deferredAutocompleteHides.delete(list);
                    }
                    // A valid ID can still be a prefix of the item being
                    // searched for. Commit only when leaving the picker;
                    // suggestion and browser selections commit their own ID.
                    if (pendingInputs.has(input) && event.target !== options?.browserButton
                        && !options?.browserButton?.contains?.(event.target) && !overlay?.open) {
                        pendingInputs.delete(input);
                        options?.onCommit?.(input.value);
                    }
                }
            });
        }

        function finishAutocompletePointer() {
            if (!deferredAutocompleteHides.size) return;
            // A released/cancelled pointer need not produce a click (e.g. a drag).
            setTimeout(() => {
                deferredAutocompleteHides.forEach(list => { list.style.display = "none"; });
                deferredAutocompleteHides.clear();
            }, 0);
        }

        function categoryLabel() {
            if (!categorySelect) return "Alle Kategorien";
            return categorySelect.options[categorySelect.selectedIndex]?.text || "Alle Kategorien";
        }

        function setPageScrollLocked(locked) {
            if (locked === pageScrollLocked) return;
            const root = documentObj.documentElement;
            const body = documentObj.body;
            const win = documentObj.defaultView;

            if (locked) {
                pageScrollPosition = Number(win?.scrollY ?? root?.scrollTop ?? 0);
                root?.classList?.add("item-browser-open");
                body?.classList?.add("item-browser-open");
                if (body?.style) body.style.top = `-${pageScrollPosition}px`;
                pageScrollLocked = true;
                return;
            }

            root?.classList?.remove("item-browser-open");
            body?.classList?.remove("item-browser-open");
            if (body?.style) body.style.top = "";
            pageScrollLocked = false;
            win?.scrollTo?.(0, pageScrollPosition);
        }

        function closeBrowser() {
            if (overlay?.open) overlay.close();
            if (overlay) overlay.style.display = "none";
            overlay?.setAttribute?.("aria-hidden", "true");
            setPageScrollLocked(false);
            const focusTarget = returnFocusElement;
            returnFocusElement = null;
            picker = null;
            focusTarget?.focus?.({ preventScroll: true });
        }

        function markUnavailable(card, reason) {
            if (!reason) return;
            card.setAttribute("aria-disabled", "true");
            const note = documentObj.createElement("span");
            note.className = "browser-unavailable";
            note.textContent = reason;
            card.appendChild(note);
        }

        function selectBrowserItem(id, metadata = null) {
            if (picker) {
                const target = picker;
                if (!target.isCurrent()) { closeBrowser(); return; }
                if (target.selectionReason?.(id, metadata)) return;
                closeBrowser();
                target.onSelect({ ...metadata, id });
                return;
            }
            if (!allowedForInput(id, browserActiveInput)) return;
            if (browserActiveInput) {
                pendingInputs.delete(browserActiveInput);
                browserActiveInput.value = id;
            }
            closeBrowser();
            if (browserActiveInput) {
                if (isDetailInput(browserActiveInput)) {
                    onDetailItemChanged(id);
                }
                if (isDetailInput(browserActiveInput) && Number.isInteger(Number(metadata?.damage))) {
                    onDetailItemVariantSelected({ ...metadata, id, damage: Number(metadata.damage) });
                }
                dispatchInput(browserActiveInput);
                if (isDetailInput(browserActiveInput)) {
                    onApplyDetailItem();
                }
            }
        }

        function renderBrowserItems(query) {
            if (!grid || !count) return;
            grid.innerHTML = "";
            const q = String(query || "").toLowerCase().trim();
            const category = categorySelect ? categorySelect.value : "all";
            const sortMode = sortSelect ? sortSelect.value : "type";
            const browserOptions = {
                query: q,
                category,
                sortMode,
                blockOnlyIds: getBlockOnlyItems(),
                addableIds: getAddableItems(),
                blockItemIds: getBlockItems(),
            };
            if (picker || isDetailInput(browserActiveInput)) browserOptions.itemVariantsForId = getItemVariantsForId;
            const items = itemBrowserLogic.browserItems(getItemsDb(), browserOptions)
                .filter(([id]) => allowedForInput(id, browserActiveInput));

            if (items.length === 0) {
                grid.innerHTML = itemBrowserLogic.browserEmptyHtml();
                count.textContent = itemBrowserLogic.browserCountText({
                    count: 0,
                    categoryLabel: categoryLabel(),
                    sortMode,
                });
                return;
            }

            count.textContent = itemBrowserLogic.browserCountText({
                count: items.length,
                categoryLabel: categoryLabel(),
                sortMode,
            });

            function appendCards(start, end) {
                let firstCard = null;
                items.slice(start, end).forEach(([id, names, metadata]) => {
                    const iconMeta = getItemIconMeta(itemIconTarget(id, metadata?.damage, metadata));
                    const card = itemBrowserLogic.browserItemCardElement({
                        id,
                        names,
                        damage: metadata?.damage,
                        iconUrl: iconMeta?.url || "",
                        fallbackIcon: getItemEmoji(id) || "□",
                        iconTint: getItemIconTint(id) || "",
                        availability: getItemAvailability(id, metadata?.damage),
                    });
                    card.addEventListener("click", () => selectBrowserItem(id, metadata));
                    markUnavailable(card, picker?.selectionReason?.(id, metadata));
                    grid.appendChild(card);
                    firstCard ||= card;
                });
                return firstCard;
            }

            // Chunk-Rendering: nur die erste Portion sofort ins DOM; der Rest
            // wird über den "Weitere anzeigen"-Button nachgelegt. Ohne das
            // Plan-Helper-Modul (z. B. in isolierten Tests) wird alles gerendert.
            const chunkPlanFor = typeof itemBrowserLogic.browserRenderChunkPlan === "function"
                ? renderedCount => itemBrowserLogic.browserRenderChunkPlan({ totalCount: items.length, renderedCount })
                : renderedCount => ({ start: renderedCount, end: items.length, remaining: 0, hasMore: false, buttonLabel: "" });

            let plan = chunkPlanFor(0);
            appendCards(plan.start, plan.end);
            if (!plan.hasMore) return;

            const moreButton = documentObj.createElement("button");
            moreButton.type = "button";
            moreButton.className = "browser-load-more";
            moreButton.textContent = plan.buttonLabel;
            moreButton.addEventListener("click", () => {
                const hadFocus = documentObj.activeElement === moreButton;
                moreButton.remove();
                plan = chunkPlanFor(plan.end);
                const firstCard = appendCards(plan.start, plan.end);
                if (plan.hasMore) {
                    moreButton.textContent = plan.buttonLabel;
                    grid.appendChild(moreButton);
                }
                if (hadFocus) {
                    firstCard?.focus({ preventScroll: true });
                    firstCard?.scrollIntoView({ block: "nearest" });
                }
            });
            grid.appendChild(moreButton);
        }

        function showBrowser(focusTarget) {
            if (!overlay || !searchInput) return;
            returnFocusElement = focusTarget || documentObj.activeElement;
            overlay.style.display = "flex";
            overlay.setAttribute?.("aria-hidden", "false");
            setPageScrollLocked(true);
            overlay.showModal();
            searchInput.value = "";
            searchInput.focus();

            if (categorySelect) categorySelect.value = "all";
            if (sortSelect) sortSelect.value = "type";
            renderBrowserItems("");
        }

        function openItemBrowser(inputEl, focusTarget = null) {
            picker = null;
            browserActiveInput = inputEl;
            if (title) title.textContent = browserTitle(inputEl);
            showBrowser(focusTarget || inputEl);
        }

        function openPicker({ onSelect, selectionReason, isCurrent, focusTarget }) {
            browserActiveInput = null;
            picker = { onSelect, selectionReason, isCurrent };
            if (title) title.textContent = window.t ? window.t("📖 Item-Browser") : "📖 Item-Browser";
            showBrowser(focusTarget);
        }

        function handleEscape(event) {
            event.stopPropagation();
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") event.preventDefault();
            if (event.key === "Escape" && overlay?.open) {
                event.preventDefault();
                closeBrowser();
            }
        }

        function wire() {
            setupAutocomplete(detailInput, detailAutocomplete, {
                applyOnSelect: true, onCommit: onDetailItemChanged, browserButton: detailBrowserButton,
            });
            setupAutocomplete(bulkInput, bulkAutocomplete);
            documentObj.addEventListener("pointerdown", hideAutocompleteLists, true);
            documentObj.addEventListener("pointerup", finishAutocompletePointer, true);
            documentObj.addEventListener("pointercancel", finishAutocompletePointer, true);
            documentObj.addEventListener("click", hideAutocompleteLists);
            documentObj.addEventListener("focusin", hideAutocompleteLists);
            detailBrowserButton?.addEventListener("click", () => openItemBrowser(detailInput, detailBrowserButton));
            bulkBrowserButton?.addEventListener("click", () => openItemBrowser(bulkInput, bulkBrowserButton));
            overlay?.addEventListener("click", event => {
                if (event.target === event.currentTarget) closeBrowser();
            });
            closeButton?.addEventListener("click", closeBrowser);
            searchInput?.addEventListener("input", () => renderBrowserItems(searchInput.value));
            categorySelect?.addEventListener("change", () => renderBrowserItems(searchInput?.value || ""));
            sortSelect?.addEventListener("change", () => renderBrowserItems(searchInput?.value || ""));
            overlay?.addEventListener("keydown", handleEscape);
            overlay?.addEventListener("cancel", event => { event.preventDefault(); closeBrowser(); });
        }

        return {
            autocompleteMatches,
            closeBrowser,
            openItemBrowser,
            openPicker,
            renderBrowserItems,
            selectAutocompleteItem,
            setupAutocomplete,
            wire,
        };
    }

    function collectInventoryItemBrowserElements(doc = document) {
        return {
            detailInput: doc.getElementById("detailItemSearch"),
            detailAutocomplete: doc.getElementById("detailItemAutocomplete"),
            bulkInput: doc.getElementById("bulkItemSearch"),
            bulkAutocomplete: doc.getElementById("bulkItemAutocomplete"),
            overlay: doc.getElementById("itemBrowserOverlay"),
            grid: doc.getElementById("browserGrid"),
            searchInput: doc.getElementById("browserSearchInput"),
            categorySelect: doc.getElementById("browserCategorySelect"),
            sortSelect: doc.getElementById("browserSortSelect"),
            count: doc.getElementById("browserCount"),
            closeButton: doc.getElementById("btnBrowserClose"),
            detailBrowserButton: doc.getElementById("btnBrowserDetail"),
            bulkBrowserButton: doc.getElementById("btnBrowserBulk"),
            title: doc.getElementById("itemBrowserTitle"),
        };
    }

    function createInventoryItemBrowserController({
        doc = document,
        itemCatalog = {},
        getItemsDb = () => ({}),
        getAddableItems = () => null,
        getBlockOnlyItems = () => null,
        getBlockItems = () => null,
        getItemAvailability = () => null,
        getEquipmentTargets = () => [],
        onDetailItemChanged = () => {},
        onDetailItemVariantSelected = () => {},
        onApplyDetailItem = () => {},
    } = {}) {
        return createItemBrowserController({
            documentObj: doc,
            elements: collectInventoryItemBrowserElements(doc),
            getItemsDb,
            getAddableItems,
            getBlockOnlyItems,
            getBlockItems,
            getItemEmoji: itemCatalog.getItemEmoji,
            getItemIconMeta: itemCatalog.getItemIconMeta,
            getItemIconTint: itemCatalog.getItemIconTint,
            getItemVariantsForId: itemCatalog.addableItemVariantsForId,
            getItemAvailability,
            getEquipmentTargets,
            onDetailItemChanged,
            onDetailItemVariantSelected,
            onApplyDetailItem,
        });
    }


    window.MCBEItemBrowserController = {
        collectInventoryItemBrowserElements,
        createInventoryItemBrowserController,
        createItemBrowserController,
    };
}());
