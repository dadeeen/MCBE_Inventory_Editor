(function () {
    "use strict";
    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function itemProtectedNbtDetails(item, { visible = true } = {}) {
        if (!visible) return [];
        const details = [];
        if (Array.isArray(item?.protected_nbt_summary) && item.protected_nbt_summary.length) details.push(...item.protected_nbt_summary.map(String));
        else if (item?.has_protected_nbt) details.push(t("Zusatz-NBT vorhanden, Kategorien in diesem Datensatz nicht genauer aufgeschlüsselt."));
        if (Array.isArray(item?.preserved_nbt_summary) && item.preserved_nbt_summary.length) details.push(...item.preserved_nbt_summary.map(String));
        else if (item?.has_preserved_nbt && !item?.has_protected_nbt) details.push(t("Bekannte Zusatz-NBT vorhanden, wird bei gleicher Item-ID erhalten."));
        if (item?.has_unknown_enchantments) details.push(t("Unbekannte/future Verzauberungen werden erhalten."));
        if (item?.protected_nbt_dropped) details.push(t("Beim Itemtyp-Wechsel wird Zusatz-NBT vom vorherigen Item nicht übernommen."));
        return details;
    }
    function itemNbtViewText(item) {
        if (!item?.nbt_view) return "";
        try { return JSON.stringify(item.nbt_view, null, 2); } catch (_error) { return ""; }
    }
    function itemHasInspectableNbt(item, { visible = true } = {}) {
        return visible && Boolean(item?.name && item.name !== "minecraft:air" && Number(item.count) > 0);
    }
    function nodeExplanation(node, item, catalog) {
        if (node.id === "$.Name") return t("Technische Kennung des geladenen Gegenstands.");
        if (node.id === "$.Count") return t("Gespeicherte Anzahl im Stapel.");
        if (node.id === "$.Slot") return t("Slot in den Originaldaten; nach Verschieben kann der aktuelle Zielslot abweichen.");
        if (node.id === "$.tag.display.Name") return t("Eigener Anzeigename des Gegenstands.");
        if (node.id === "$.tag.display.Lore") return t("Eigene Beschreibung, zeilenweise gespeichert.");
        if (node.id === "$.tag.Damage" && /^(Byte|Short|Int|Long)Tag$/.test(node.type) && catalog?.itemUsesDurabilityDamage?.(item?.name)) return t("Verbrauchte Haltbarkeitspunkte des geladenen Gegenstands.");
        if (node.id === "$.Damage") return t("Datenwert des geladenen Gegenstands; die Bedeutung hängt vom Itemtyp ab.");
        return t("Originaler NBT-Wert. Nicht jeder Tag hat eine bekannte fachliche Bedeutung.");
    }
    function createSlotInspectorController(deps = {}) {
        const {
            elements = {}, getInventory = () => ({}), getEnderChestInventory = () => ({}),
            getCleanSnapshot = () => null, getCurrentPlayerKey = () => "", getWorldPath = () => "",
            currentPlayerLabel = () => t("Spieler"), slotDisplayName = (slot, container) => `${container}:${slot}`,
            isProtectedKnownSlot = () => false, itemIsVisiblePresent = item => Boolean(item),
            itemLabel = item => item?.display_name || item?.name || "", catalog = {},
            getSpecialItemModel = () => null, getEnchantments = () => ({}),
            showToast = () => {}, copyTextToClipboard = () => {},
        } = deps;
        const { panel, title, closeButton, copyButton } = elements;
        const doc = panel?.ownerDocument;
        const model = window.MCBENbtInspectorModel;
        const byId = id => doc.getElementById(id);
        let session = null, returnFocus = null, wired = false, copyRequest = 0;
        let nodes = [], nodeMap = new Map(), expanded = new Set(), matches = [], matchIndex = -1;
        let selectedId = "$", query = "";
        const bannerRenderer = doc && window.MCBEBannerPreview?.createRenderer(doc);
        function el(tag, text = "", className = "") {
            const node = doc.createElement(tag);
            if (text !== "") node.textContent = String(text);
            if (className) node.className = className;
            return node;
        }
        function sourceFor(container) { return container === "ender_chest" ? getEnderChestInventory() : getInventory(); }
        function hide() {
            if (panel?.open) panel.close();
            session = null; nodes = []; nodeMap.clear(); matches = []; expanded.clear();
            // Restore focus synchronously; the queued close event must not
            // steal it from the user's next selection or another dialog.
            if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
            returnFocus = null;
        }
        function isCurrent() {
            if (!session) return false;
            const valid = session.player === getCurrentPlayerKey() && session.world === getWorldPath()
                && session.snapshot === getCleanSnapshot()
                && session.item === (sourceFor(session.container)?.[session.slot] || null);
            if (!valid) hide();
            return valid;
        }
        function copy(value, message) {
            if (!isCurrent()) return;
            const owner = session, request = ++copyRequest;
            byId("itemInspectorCopyFallback").hidden = true;
            byId("itemInspectorCopyText").value = "";
            byId("itemInspectorCopyStatus").textContent = "";
            Promise.resolve(copyTextToClipboard(value, message, { allowEmpty: true, onFailure: text => {
                if (session !== owner || request !== copyRequest || !isCurrent()) return;
                byId("itemInspectorCopyFallback").hidden = false;
                const field = byId("itemInspectorCopyText"); field.value = text;
                field.focus(); field.select();
            } })).then(success => {
                if (success && session === owner && request === copyRequest && isCurrent()) byId("itemInspectorCopyStatus").textContent = message;
            });
        }
        function row(list, name, value, path = null) {
            list.append(el("dt", name));
            const cell = el("dd", value);
            if (path && nodeMap.has(path)) {
                const link = el("button", t("Im NBT anzeigen"), "btn-text inspector-jump"); link.type = "button";
                link.addEventListener("click", () => { selectTab("tree"); reveal(path); selectNode(path); renderTree(true); });
                cell.append(link);
            }
            list.append(cell);
        }
        function renderOverview() {
            const target = byId("inspectorOverview"); target.replaceChildren();
            if (session.protectedKnown) {
                target.append(el("h3", t("Slot bleibt geschützt")), el("p", t("Dieser NBT-Eintrag kann nicht verlustfrei als normales Item dargestellt werden. Der Editor überschreibt ihn nicht."))); return;
            }
            const item = session.item;
            target.append(el("p", t("Aktueller Entwurf · Zuletzt im Editor übernommene Werte. Offene Formulareingaben sind nicht enthalten."), "inspector-source"));
            const list = el("dl", "", "inspector-properties"); target.append(list);
            row(list, t("Item-ID"), item.name, "$.Name");
            row(list, t("Anzahl"), catalog.hasVerifiedStackLimit?.(item.name)
                ? t("{count} / {max} pro Stapel", { count: item.count, max: catalog.getMaxStack(item.name) }) : String(item.count));
            if (catalog.itemUsesDurabilityDamage?.(item.name)) {
                row(list, t("Haltbarkeit"), t("{remaining} / {max} · {used} verbraucht", {
                    remaining: Math.max(0, catalog.getMaxDamage(item.name) - item.damage), max: catalog.getMaxDamage(item.name), used: item.damage,
                }));
            } else if (item.damage) row(list, catalog.itemDamageLabel?.(item.name) || t("Datenwert"), item.damage);
            if (item.display_name) row(list, t("Anzeigename"), item.display_name);
            if (item.lore?.length) row(list, t("Beschreibung"), item.lore.join("\n"));
            if (item.enchantments?.length) {
                const db = getEnchantments();
                row(list, t("Verzauberungen"), item.enchantments.map(entry => {
                    const name = (doc.documentElement.lang === "en" ? db[entry.id]?.name_en : db[entry.id]?.name_de) || String(entry.id);
                    return `${name} ${entry.lvl ?? entry.level}`;
                }).join("\n"));
            }
            renderSpecial(target, list, item);
            const details = itemProtectedNbtDetails(item);
            if (details.length) {
                target.append(el("h3", t("Erhaltene Zusatzdaten")));
                const ul = el("ul", "", "inspector-notes"); details.forEach(detail => ul.append(el("li", detail))); target.append(ul);
            }
            target.append(el("p", session.original
                ? t("NBT-Baum und JSON zeigen den geladenen Originalstand. Bearbeitungen des Entwurfs sind dort nicht abgebildet.")
                : t("Keine geladenen Originaldaten sicher zuordenbar. Für neue oder ersetzte Items ist die NBT-Ansicht erst nach dem Speichern verfügbar."), "inspector-source"));
        }
        function renderSpecial(target, list, item) {
            const special = getSpecialItemModel(), kind = special?.kind(item);
            if (!kind) return;
            if (!special.editable(item)) { row(list, t("Spezialdaten"), t("Geschützter Aufbau; technische Einzelheiten stehen im NBT-Baum.")); return; }
            const data = special.data(item);
            if (["bundle", "shulker"].includes(kind)) {
                row(list, t("Belegte Plätze"), data.items.length);
                if (kind === "bundle") {
                    const weight = special.contentWeight(data.items);
                    row(list, t("Bundle-Auslastung"), weight === null ? t("Nicht sicher bestimmbar") : t("{used} / 64 Gewichtseinheiten", { used: weight }));
                }
                if (data.items.length) {
                    const contents = el("ul", "", "inspector-contents");
                    data.items.forEach(child => contents.append(el("li", t(kind === "bundle" ? "{count} × {item}" : "Platz {slot}: {count} × {item}", { slot: child.slot + 1, count: child.count, item: itemLabel(child) }))));
                    target.append(el("h3", t("Behälterinhalt")), contents);
                }
            } else if (kind === "book") {
                row(list, t("Seiten"), data.pages.length);
                if (data.title) row(list, t("Buchtitel"), data.title);
                if (data.author) row(list, t("Autor"), data.author);
            } else if (kind === "banner") {
                row(list, t("Bannerart"), t(data.type === 1 ? "Ominöses Banner" : "Normales Banner"));
                if (data.type !== 1) row(list, t("Bannermuster"), data.patterns.length);
                const preview = el("div", "", "inspector-banner"); target.append(preview);
                const owner = session, baseColor = Number.isInteger(data.base_color) ? data.base_color : item.damage;
                bannerRenderer.render(baseColor, data.patterns, deps.getBannerPatterns?.() || {}, special.schema.color_hex, data.type || 0)
                    .then(canvas => {
                        if (session !== owner) return;
                        if (canvas) { canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", t("Bannervorschau")); preview.append(canvas); }
                        else preview.append(el("p", t("Bannervorschau ohne geladene Mustertexturen nicht verfügbar."), "inspector-source"));
                    }).catch(() => { if (session === owner) preview.append(el("p", t("Bannervorschau nicht verfügbar."), "inspector-source")); });
            } else {
                if (kind === "fireworks") row(list, t("Flugdauer"), data.flight);
                row(list, t("Feuerwerkseffekte"), data.explosions.length);
            }
        }
        function selectTab(name) {
            if (!isCurrent()) return;
            panel.querySelectorAll("[data-inspector-tab]").forEach(button => {
                const active = button.dataset.inspectorTab === name;
                button.setAttribute("aria-selected", String(active)); button.tabIndex = active ? 0 : -1;
                byId(button.getAttribute("aria-controls")).hidden = !active;
            });
            byId("slotInspectorBody").scrollTop = 0;
            fitTree();
        }
        function fitTree() {
            if (!panel.open || byId("inspectorTree").hidden) return;
            const body = byId("slotInspectorBody"), tree = byId("itemInspectorTree");
            const contentTop = tree.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
            // Keep search results inside the viewport, including short screens.
            // The selected node's details remain reachable in the body below.
            tree.style.setProperty("--inspector-tree-space", `${Math.max(96, Math.floor(body.clientHeight - contentTop - 16))}px`);
            updateValueVisibility();
        }
        function updateValueVisibility() {
            if (!panel.open || byId("inspectorTree").hidden) return;
            const node = nodeMap.get(selectedId);
            const preview = byId("itemInspectorTree").querySelector('[aria-selected="true"] .inspector-value');
            const multiline = typeof node?.value === "string" && /[\r\n\u2028\u2029]/.test(node.value);
            const structuredValue = typeof node?.count !== "number" && node?.value !== null && typeof node?.value === "object";
            byId("itemInspectorValue").hidden = !node || node.children || !preview
                || !(node.partial || multiline || structuredValue || preview.scrollWidth > preview.clientWidth);
        }
        function reveal(id) {
            let node = nodeMap.get(id);
            while (node?.parentId) { expanded.add(node.parentId); node = nodeMap.get(node.parentId); }
        }
        function visibleNodes() {
            const visible = new Set();
            return nodes.filter(node => {
                if (node.parentId === null || (visible.has(node.parentId) && expanded.has(node.parentId))) { visible.add(node.id); return true; }
                return false;
            });
        }
        function selectNode(id) {
            const node = nodeMap.get(id); selectedId = id; byId("itemInspectorNode").hidden = !node;
            if (!node) return;
            byId("itemInspectorPath").textContent = node.id;
            byId("itemInspectorExplanation").textContent = nodeExplanation(node, session.original?.item, catalog) + (node.partial ? " " + t("Auszug: Dieser Wert ist gekürzt.") : "");
            if (Number.isInteger(node.listTypeId)) byId("itemInspectorExplanation").textContent += " " + t("Deklarierter Listen-Elementtyp (NBT-ID): {id}.", { id: node.listTypeId });
            byId("itemInspectorValue").textContent = (node.children ? model.nodeValueText(node) : typeof node.value === "string" ? node.value : JSON.stringify(node.value)) ?? "";
            byId("itemInspectorValue").hidden = true;
            byId("itemInspectorCopyValue").disabled = node.children || node.partial;
            byId("itemInspectorCopyValue").title = node.partial ? t("Gekürzte Werte können über die als Auszug gekennzeichnete JSON-Ansicht kopiert werden.") : "";
        }
        function renderTree(focus = false) {
            const tree = byId("itemInspectorTree"), visible = visibleNodes(); tree.replaceChildren();
            if (!visible.some(node => node.id === selectedId)) selectNode(visible[0]?.id || "");
            const fragment = doc.createDocumentFragment();
            const siblings = new Map();
            nodes.forEach(node => { if (!siblings.has(node.parentId)) siblings.set(node.parentId, []); siblings.get(node.parentId).push(node.id); });
            visible.forEach(node => {
                const entry = el("div", "", "inspector-tree-row");
                entry.setAttribute("role", "treeitem"); entry.setAttribute("aria-level", String(node.depth + 1));
                entry.setAttribute("aria-selected", String(node.id === selectedId)); entry.tabIndex = node.id === selectedId ? 0 : -1;
                entry.setAttribute("aria-posinset", String(siblings.get(node.parentId).indexOf(node.id) + 1));
                entry.setAttribute("aria-setsize", String(nodeMap.get(node.parentId)?.partial ? -1 : siblings.get(node.parentId).length));
                entry.dataset.path = node.id; entry.style.setProperty("--nbt-depth", String(Math.min(node.depth, 8)));
                if (node.children) entry.setAttribute("aria-expanded", String(expanded.has(node.id)));
                if (matches.includes(node.id)) entry.classList.add("inspector-match");
                const key = el("span", node.key, "inspector-key");
                const arrow = el("span", node.children ? expanded.has(node.id) ? "▾" : "▸" : "", "inspector-arrow"); arrow.setAttribute("aria-hidden", "true"); key.prepend(arrow);
                const type = el("span", node.type.replace(/Tag$/, ""), "inspector-type");
                type.dataset.family = node.type === "StringTag" ? "string" : /^(Compound|List|ByteArray|IntArray|LongArray)Tag$/.test(node.type) ? "structure" : /^(Byte|Short|Int|Long|Float|Double)Tag$/.test(node.type) ? "number" : "unknown";
                entry.append(key, type, el("span", model.nodeValueText(node), "inspector-value"));
                entry.addEventListener("click", () => {
                    if (!isCurrent()) return;
                    selectNode(node.id);
                    if (node.children) expanded.has(node.id) ? expanded.delete(node.id) : expanded.add(node.id);
                    renderTree(true);
                });
                fragment.append(entry);
            });
            tree.append(fragment);
            updateValueVisibility();
            if (focus) {
                Array.from(tree.children).find(node => node.dataset.path === selectedId)?.focus({ preventScroll: true });
                scrollSelected();
            }
        }
        function scrollSelected() {
            const tree = byId("itemInspectorTree");
            const selected = Array.from(tree.children).find(node => node.dataset.path === selectedId);
            if (!selected) return;
            const bounds = tree.getBoundingClientRect(), rowBounds = selected.getBoundingClientRect();
            if (rowBounds.top < bounds.top) tree.scrollTop -= bounds.top - rowBounds.top;
            else if (rowBounds.bottom > bounds.bottom) tree.scrollTop += rowBounds.bottom - bounds.bottom;
        }
        function updateSearchStatus() {
            byId("itemInspectorSearchStatus").textContent = query
                ? matches.length ? t("Treffer {current} von {count}", { current: matchIndex + 1, count: matches.length }) : t("Keine Treffer in den angezeigten Daten.")
                : t("{count} NBT-Knoten", { count: nodes.length });
            byId("itemInspectorPrevious").disabled = byId("itemInspectorNext").disabled = !matches.length;
        }
        function search() {
            query = byId("itemInspectorSearch").value.trim().toLocaleLowerCase();
            matches = query ? nodes.filter(node => [node.key, node.id, model.nodeValueText(node), typeof node.value === "string" ? node.value : ""]
                .some(value => String(value).toLocaleLowerCase().includes(query))).map(node => node.id) : [];
            matchIndex = matches.length ? 0 : -1;
            if (matches.length) { reveal(matches[0]); selectNode(matches[0]); }
            renderTree(); updateSearchStatus(); scrollSelected();
        }
        function nextMatch(offset) {
            if (!matches.length) return;
            matchIndex = (matchIndex + offset + matches.length) % matches.length;
            reveal(matches[matchIndex]); selectNode(matches[matchIndex]); renderTree(); updateSearchStatus(); scrollSelected();
        }
        function treeKey(event) {
            const current = nodeMap.get(event.target.dataset.path);
            if (!current) return;
            const visible = visibleNodes(), index = visible.indexOf(current); let next = current;
            if (event.key === "ArrowDown") next = visible[Math.min(index + 1, visible.length - 1)];
            else if (event.key === "ArrowUp") next = visible[Math.max(0, index - 1)];
            else if (event.key === "Home") next = visible[0];
            else if (event.key === "End") next = visible[visible.length - 1];
            else if (event.key === "ArrowRight") {
                if (current.children && !expanded.has(current.id)) expanded.add(current.id);
                else if (current.children) next = visible[index + 1] || current;
            } else if (event.key === "ArrowLeft") {
                if (expanded.has(current.id)) expanded.delete(current.id);
                else next = nodeMap.get(current.parentId) || current;
            } else if (["Enter", " "].includes(event.key) && current.children) {
                expanded.has(current.id) ? expanded.delete(current.id) : expanded.add(current.id);
            } else return;
            event.preventDefault(); selectNode(next.id); renderTree(true);
        }
        function show(slotId, containerName, reason = "item_nbt") {
            if (!panel || doc.querySelector("dialog[open]:not(#slotInspectorPanel)")) return;
            const item = sourceFor(containerName)?.[slotId] || null;
            const protectedKnown = reason === "protected_known_slot" || isProtectedKnownSlot(slotId, containerName);
            if (!protectedKnown && !itemHasInspectableNbt(item, { visible: itemIsVisiblePresent(item) })) return;
            returnFocus = doc.activeElement;
            const snapshot = getCleanSnapshot();
            const original = protectedKnown ? null : model.resolveOriginal({ item, containerName, cleanSnapshot: snapshot, worldPath: getWorldPath(), playerKey: getCurrentPlayerKey() });
            session = { slot: Number(slotId), container: containerName, item, original, protectedKnown, snapshot, world: getWorldPath(), player: getCurrentPlayerKey() };
            byId("itemInspectorCopyFallback").hidden = true; byId("itemInspectorCopyText").value = "";
            byId("itemInspectorCopyStatus").textContent = "";
            nodes = original ? model.flattenTree(original.item.nbt_view) : [];
            nodeMap = new Map(nodes.map(node => [node.id, node])); expanded = new Set(["$"]); matches = []; matchIndex = -1; query = "";
            title.textContent = protectedKnown ? t("Slot geschützt") : itemLabel(item);
            byId("itemInspectorLocation").textContent = slotDisplayName(Number(slotId), containerName);
            const partial = original && model.hasPartial(original.item.nbt_view);
            const sourceText = original
                ? t("Geladener Originalstand · {slot}. Änderungen des Entwurfs sind hier nicht enthalten.", { slot: slotDisplayName(original.slotId, original.containerName) })
                    + (partial ? " " + t("Auszug: Große oder tiefe Inhalte sind gekürzt. Suche und Kopieren beziehen sich auf die verfügbaren Auszüge.") : "")
                : t("Keine geladenen Originaldaten verfügbar.");
            panel.querySelectorAll(".inspector-source").forEach(node => { node.textContent = sourceText; });
            byId("itemInspectorJson").textContent = itemNbtViewText(original?.item);
            byId("itemInspectorCopyJson").disabled = !original;
            byId("itemInspectorCopyJson").textContent = partial ? t("JSON-Auszug kopieren") : t("JSON-Ansicht kopieren");
            byId("itemInspectorSearch").value = ""; byId("itemInspectorSearch").disabled = !nodes.length;
            byId("itemInspectorCollapse").disabled = !nodes.length;
            selectNode(nodes[0]?.id || ""); renderTree(); updateSearchStatus(); renderOverview(); selectTab("overview");
            if (!panel.open) panel.showModal(); closeButton.focus();
        }
        function wire() {
            if (!panel || wired) return; wired = true;
            if (doc.defaultView?.ResizeObserver) {
                const resize = new doc.defaultView.ResizeObserver(fitTree);
                resize.observe(byId("slotInspectorBody"));
                resize.observe(byId("itemInspectorTree"));
            }
            closeButton.addEventListener("click", hide);
            panel.addEventListener("cancel", event => { event.preventDefault(); hide(); });
            panel.addEventListener("keydown", event => {
                if (!isCurrent()) return;
                event.stopPropagation();
                if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") event.preventDefault();
            });
            ["click", "keydown", "input"].forEach(name => panel.addEventListener(name, event => {
                if (!isCurrent()) { event.preventDefault(); event.stopImmediatePropagation(); }
            }, true));
            panel.querySelectorAll("[data-inspector-tab]").forEach(button => {
                button.addEventListener("click", () => selectTab(button.dataset.inspectorTab));
                button.addEventListener("keydown", event => {
                    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault();
                    const tabs = Array.from(panel.querySelectorAll("[data-inspector-tab]")), index = tabs.indexOf(button);
                    const target = tabs[event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
                    selectTab(target.dataset.inspectorTab); target.focus();
                });
            });
            byId("itemInspectorTree").addEventListener("keydown", treeKey);
            byId("itemInspectorSearch").addEventListener("input", search);
            byId("itemInspectorSearch").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); nextMatch(event.shiftKey ? -1 : 1); } });
            byId("itemInspectorPrevious").addEventListener("click", () => nextMatch(-1));
            byId("itemInspectorNext").addEventListener("click", () => nextMatch(1));
            byId("itemInspectorCollapse").addEventListener("click", () => { expanded.clear(); selectNode("$"); renderTree(); });
            byId("itemInspectorCopyPath").addEventListener("click", () => copy(selectedId, t("NBT-Pfad kopiert.")));
            byId("itemInspectorCopyValue").addEventListener("click", () => {
                const node = nodeMap.get(selectedId);
                if (node && !node.children && !node.partial) copy(typeof node.value === "string" ? node.value : JSON.stringify(node.value), t("NBT-Wert kopiert."));
            });
            byId("itemInspectorCopyJson").addEventListener("click", () => { if (session?.original) copy(itemNbtViewText(session.original.item), t("NBT-JSON kopiert.")); });
            byId("itemInspectorCopyDismiss").addEventListener("click", () => { byId("itemInspectorCopyFallback").hidden = true; byId("itemInspectorCopyText").value = ""; closeButton.focus(); });
            copyButton.addEventListener("click", () => {
                if (!isCurrent()) return;
                const lines = [t("Item-Inspektor · Nur lesen"), title.textContent, byId("itemInspectorLocation").textContent,
                    t("Spieler: {label}", { label: currentPlayerLabel() }), t("Weltpfad: {path}", { path: getWorldPath() }),
                    ...itemProtectedNbtDetails(session.item),
                    session.protectedKnown ? t("Dieser NBT-Eintrag kann nicht verlustfrei als normales Item dargestellt werden. Der Editor überschreibt ihn nicht.") : "",
                    t("Geladener Originalstand"), itemNbtViewText(session.original?.item) || t("Keine geladenen Originaldaten verfügbar.")];
                copy(lines.join("\n"), t("Diagnose kopiert."));
            });
        }
        function showProtectedMessage(slotId, containerName) {
            showToast(t("Dieser Slot ist geschützt. Die Analyse erklärt den Grund."), "warning", 4500); show(slotId, containerName, "protected_known_slot");
        }
        return { show, hide, wire, showProtectedMessage, itemHasInspectableNbt: item => itemHasInspectableNbt(item, { visible: itemIsVisiblePresent(item) }) };
    }
    function collectSlotInspectorElements(doc = document) {
        return { panel: doc.getElementById("slotInspectorPanel"), title: doc.getElementById("slotInspectorTitle"), closeButton: doc.getElementById("btnCloseSlotInspector"), copyButton: doc.getElementById("btnCopySlotInspector") };
    }
    function createInventorySlotInspectorController({ doc = document, ...deps } = {}) {
        return createSlotInspectorController({ ...deps, elements: collectSlotInspectorElements(doc) });
    }
    window.MCBENbtInspector = { itemHasInspectableNbt, itemProtectedNbtDetails, itemNbtViewText, nodeExplanation, createSlotInspectorController, collectSlotInspectorElements, createInventorySlotInspectorController };
}());
