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
        } = elements;
        let browserActiveInput = null;
        let returnFocusElement = null;
        let selectingAutocompleteItem = false;
        let pageScrollLocked = false;
        let pageScrollPosition = 0;

        function isDetailInput(inputEl) {
            return inputEl && inputEl === detailInput;
        }

        function autocompleteMatches(query, inputEl = detailInput, limit = 10) {
            return itemBrowserLogic.autocompleteMatches(
                getItemsDb(),
                query,
                limit,
                getBlockOnlyItems(),
                getAddableItems(),
                isDetailInput(inputEl) ? getItemVariantsForId : null,
            );
        }

        function itemIconTarget(id, damage) {
            return Number.isInteger(Number(damage)) && damage !== null && damage !== undefined && damage !== ""
                ? { name: id, damage: Number(damage) }
                : id;
        }

        function dispatchInput(inputEl, options = {}) {
            inputEl.dispatchEvent(new Event("input", options));
        }

        function selectAutocompleteItem(inputEl, listEl, item, options = {}) {
            if (!inputEl || !listEl || !item || !item.id) return;
            const previousName = String(inputEl.value || "").trim().toLowerCase();
            inputEl.value = item.id;
            listEl.style.display = "none";
            listEl.innerHTML = "";

            if (isDetailInput(inputEl)) {
                const nextName = String(item.id || "").trim().toLowerCase();
                if (nextName && nextName !== previousName) {
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
                            const iconMeta = getItemIconMeta(itemIconTarget(item.id, item.damage));
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
        }

        function hideAutocompleteLists(event) {
            [
                { input: detailInput, list: detailAutocomplete },
                { input: bulkInput, list: bulkAutocomplete },
            ].forEach(({ input, list }) => {
                if (!input || !list) return;
                if (event.target !== input && !list.contains(event.target)) {
                    list.style.display = "none";
                }
            });
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
            if (overlay) overlay.style.display = "none";
            overlay?.setAttribute?.("aria-hidden", "true");
            setPageScrollLocked(false);
            const focusTarget = returnFocusElement;
            returnFocusElement = null;
            focusTarget?.focus?.({ preventScroll: true });
        }

        function selectBrowserItem(id, metadata = null) {
            const previousName = String(browserActiveInput?.value || "").trim().toLowerCase();
            if (browserActiveInput) {
                browserActiveInput.value = id;
            }
            closeBrowser();
            if (browserActiveInput) {
                if (isDetailInput(browserActiveInput) && id !== previousName) {
                    onDetailItemChanged(id);
                }
                if (isDetailInput(browserActiveInput) && Number.isInteger(Number(metadata?.damage))) {
                    onDetailItemVariantSelected({ id, damage: Number(metadata.damage) });
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
            if (isDetailInput(browserActiveInput)) browserOptions.itemVariantsForId = getItemVariantsForId;
            const items = itemBrowserLogic.browserItems(getItemsDb(), browserOptions);

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
                items.slice(start, end).forEach(([id, names, metadata]) => {
                    const iconMeta = getItemIconMeta(itemIconTarget(id, metadata?.damage));
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
                    grid.appendChild(card);
                });
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
                moreButton.remove();
                plan = chunkPlanFor(plan.end);
                appendCards(plan.start, plan.end);
                if (plan.hasMore) {
                    moreButton.textContent = plan.buttonLabel;
                    grid.appendChild(moreButton);
                }
            });
            grid.appendChild(moreButton);
        }

        function openItemBrowser(inputEl, focusTarget = null) {
            if (!overlay || !searchInput) return;
            browserActiveInput = inputEl;
            returnFocusElement = focusTarget || documentObj.activeElement || inputEl || null;
            overlay.style.display = "flex";
            overlay.setAttribute?.("aria-hidden", "false");
            setPageScrollLocked(true);
            searchInput.value = "";
            searchInput.focus();

            if (categorySelect) categorySelect.value = "all";
            if (sortSelect) sortSelect.value = "type";
            renderBrowserItems("");
        }

        function handleEscape(event) {
            if (event.key === "Escape" && overlay && overlay.style.display === "flex") {
                closeBrowser();
            }
        }

        function wire() {
            setupAutocomplete(detailInput, detailAutocomplete, { applyOnSelect: true });
            setupAutocomplete(bulkInput, bulkAutocomplete);
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
            documentObj.addEventListener("keydown", handleEscape);
        }

        return {
            autocompleteMatches,
            closeBrowser,
            openItemBrowser,
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
