(function () {
    "use strict";
    const t = (value, args) => window.MCBEI18n?.t(value, args) || value;
    const clone = value => window.MCBESpecialItemLogic.clone(value);
    const COLOR_NAMES = ["Schwarz", "Rot", "Grün", "Braun", "Blau", "Violett", "Türkis", "Hellgrau", "Grau", "Rosa", "Hellgrün", "Gelb", "Hellblau", "Magenta", "Orange", "Weiß"];
    const PATTERN_NAMES = {
        bo: "Bordüre", bri: "Mauer", mc: "Kreis", cre: "Creeper", cr: "Andreaskreuz", cbo: "Gezackte Bordüre",
        lud: "Linke untere Hälfte", rd: "Rechte untere Hälfte", ld: "Linke obere Hälfte", rud: "Rechte obere Hälfte",
        flo: "Blume", flw: "Fluss", glb: "Globus", gra: "Farbverlauf", gru: "Farbverlauf von unten", gus: "Windstoßer",
        hh: "Obere Hälfte", hhb: "Untere Hälfte", vh: "Linke Hälfte", vhr: "Rechte Hälfte", moj: "Mojang-Logo",
        pig: "Schnauze", mr: "Raute", sku: "Schädel", ss: "Kleine Streifen", bl: "Linkes unteres Eck", br: "Rechtes unteres Eck",
        tl: "Linkes oberes Eck", tr: "Rechtes oberes Eck", sc: "Kreuz", bs: "Unterer Streifen", cs: "Mittlerer Längsstreifen",
        dls: "Linker Schrägstreifen", drs: "Rechter Schrägstreifen", ls: "Linker Streifen", ms: "Mittlerer Querstreifen",
        rs: "Rechter Streifen", ts: "Oberer Streifen", bt: "Dreieck unten", tt: "Dreieck oben", bts: "Zacken unten", tts: "Zacken oben",
    };
    const SHAPES = ["Kleine Kugel", "Große Kugel", "Stern", "Creeper", "Explosion"];

    function createEditor({ dialog, model, catalog, textLimits, getItemBrowser, isCurrentContext, getEnchantments, itemLabel, commit, canEdit,
        getBannerPatterns, loadBannerPatterns, canLoadBannerPatterns }) {
        const COLOR_HEX = model.schema.color_hex;
        const doc = dialog.ownerDocument;
        const body = dialog.querySelector(".special-body");
        const title = dialog.querySelector("h2");
        const path = dialog.querySelector(".special-path");
        const error = dialog.querySelector(".special-error");
        const accept = dialog.querySelector('[data-special="accept"]');
        let frames = [];
        let context = null;
        let returnFocus = null;
        let nativeReturnFocus = null;
        let saveFrame = () => {};
        let controlId = 0;
        let disposeAutocomplete = null;
        let refreshPreview = () => {};
        let inheritedDraft = false;
        let hasInputChanges = () => false;
        const bannerRenderer = window.MCBEBannerPreview.createRenderer(doc);
        function el(tag, text = "", className = "") {
            const node = doc.createElement(tag);
            if (text) node.textContent = text;
            if (className) node.className = className;
            return node;
        }
        function message(text) { error.textContent = text || ""; }
        function button(text, handler, secondary = true) {
            const node = el("button", t(text), `btn ${secondary ? "btn-secondary" : "btn-primary"} btn-sm`);
            node.type = "button";
            node.addEventListener("click", handler);
            return node;
        }
        function field(parent, text, value, options = {}) {
            const label = el("label", t(text), options.wide ? "special-wide" : "");
            const input = el(options.multiline ? "textarea" : "input");
            if (!options.multiline) input.type = options.type || "text";
            input.value = value ?? "";
            for (const key of ["min", "max", "maxLength", "list"]) if (options[key] !== undefined) input.setAttribute(key, options[key]);
            if (options.className) input.className = options.className;
            label.append(input);
            parent.append(label);
            return input;
        }
        function select(parent, text, value, values) {
            const wrapper = el("div", "", "special-field");
            const label = el("label", t(text));
            const input = el("select");
            input.id = `special-control-${++controlId}`;
            label.htmlFor = input.id;
            values.forEach(([id, name]) => { const option = el("option", name); option.value = id; input.append(option); });
            input.value = String(value);
            wrapper.append(label, input); parent.append(wrapper);
            return input;
        }
        function rowActions(parent, rows, index, rerender) {
            const actions = el("div", "", "special-actions");
            const move = direction => {
                [rows[index], rows[index + direction]] = [rows[index + direction], rows[index]];
                rerender();
            };
            const up = button("Nach oben", () => move(-1)); up.disabled = index === 0;
            const down = button("Nach unten", () => move(1)); down.disabled = index === rows.length - 1;
            actions.append(up, down, button("Entfernen", () => { rows.splice(index, 1); rerender(); }));
            parent.append(actions);
        }
        function finish(item) {
            const frame = frames.pop();
            if (frames.length) {
                frame.done(item);
                render();
                return;
            }
            const result = commit(context, item);
            if (result.ok) close();
            else { frames.push(frame); message(result.error); }
        }
        function close() {
            disposeAutocomplete?.(); disposeAutocomplete = null;
            frames = []; refreshPreview = () => {}; dialog.close();
            returnFocus?.focus?.();
        }
        function cancel() {
            if (frames.length > 1) { frames.pop(); render(); }
            else close();
        }
        function specialDepth() { return frames.filter(frame => frame.type === "special").length - 1; }
        function specialFrame(item, done, renderNow = true) {
            if (specialDepth() + 1 >= model.schema.limits.depth) { message(t("Die maximale Verschachtelungstiefe ist erreicht.")); return null; }
            const frame = { type: "special", item: clone(item), data: model.data(item), done };
            frame.initialItemState = JSON.stringify(frame.item);
            frame.initialDataState = JSON.stringify(frame.data);
            frames.push(frame);
            if (renderNow) render();
            return frame;
        }
        function childFrame(container, slot, renderNow = true) {
            const original = container.data.items.find(item => item.slot === slot);
            const frame = { type: "item", originSlot: slot, item: clone(original || { slot, name: "", count: 1, damage: 0, enchantments: [], lore: [] }), container,
                done: item => { container.data = model.withChild(container.data, slot, item); } };
            frame.initialItemState = JSON.stringify(frame.item);
            frames.push(frame);
            if (renderNow) render();
            return frame;
        }
        function openPath(slots) {
            // Use the ordinary editor frames, including their isolated drafts
            // and accept/cancel callbacks, for a direct search-result jump.
            for (let index = 0; index < slots.length; index++) {
                const parent = frames.at(-1);
                if (!model.editable(parent.item) || !["shulker", "bundle"].includes(model.kind(parent.item))
                    || !parent.data.items.some(item => item.slot === slots[index])) return false;
                const child = childFrame(parent, slots[index], false);
                if (index < slots.length - 1 && !specialFrame(child.item, item => { child.item = item; }, false)) return false;
            }
            return true;
        }
        function focusInitialControl() {
            const target = body.querySelector(".special-item-name") || body.querySelector("input, textarea, select, button");
            target?.focus();
        }
        function render() {
            const frame = frames.at(-1);
            refreshPreview = () => {};
            hasInputChanges = () => false;
            disposeAutocomplete?.(); disposeAutocomplete = null;
            body.replaceChildren(); message("");
            title.textContent = frame.type === "item" ? t(frame.item.name ? "Item bearbeiten" : "Item hinzufügen") : model.label(frame.item);
            path.textContent = frames.map(entry => entry.item.name ? itemLabel(entry.item) : t("Leerer Slot")).join(" › ");
            path.title = path.textContent;
            accept.textContent = frames.length > 1 ? t("Übernehmen und zurück") : t("Übernehmen");
            accept.disabled = false;
            if (frame.type === "item") renderItem(frame);
            else if (!model.editable(frame.item)) {
                body.append(el("p", frame.item.special_item?.reason || t("Diese Spezialdaten sind geschützt und bleiben unverändert erhalten.")));
                accept.disabled = true;
            } else {
                const kind = model.kind(frame.item);
                if (["bundle", "shulker"].includes(kind)) renderContainer(frame);
                if (kind === "book") renderBook(frame);
                if (["fireworks", "firework_star"].includes(kind)) renderFireworks(frame);
                if (kind === "banner") renderBanner(frame);
                saveFrame = () => {
                    const validation = model.validate(frame.item, frame.data, specialDepth());
                    if (validation) { message(validation); return; }
                    finish(model.apply(frame.item, frame.data));
                };
            }
            focusInitialControl();
        }
        function renderContainer(frame) {
            const isBundle = model.kind(frame.item) === "bundle";
            const capacity = isBundle ? 64 : 27;
            const used = isBundle ? model.contentWeight(frame.data.items, specialDepth() + 1) : frame.data.items.length;
            const summary = el("div", "", "special-summary");
            summary.append(el("strong", isBundle
                ? (used === null ? t("Gewicht ungeprüft") : t("{used} / 64 Gewichtseinheiten", { used }))
                : t("{used} / 27 Slots belegt", { used })), el("span", isBundle ? t("Ein unteilbares Item belegt das ganze Bundle. Innere Bundles wiegen zusätzlich 4 Einheiten.") : t("Wähle einen Slot, um das Item zu bearbeiten oder hinzuzufügen."), "special-note"));
            body.append(summary);
            const progress = el("progress"); progress.max = isBundle ? 64 : 27; progress.value = used || 0; progress.setAttribute("aria-label", t("Füllstand")); body.append(progress);
            // Bundles expose occupied entries plus one insertion slot; shulkers retain their 27-slot layout.
            const slots = isBundle ? frame.data.items.map(item => item.slot) : Array.from({ length: capacity }, (_, i) => i);
            const empty = Array.from({ length: capacity }, (_, i) => i).find(slot => !frame.data.items.some(item => item.slot === slot));
            if (isBundle && empty !== undefined) slots.push(empty);
            const grid = el("div", "", "special-grid");
            slots.forEach(slot => {
                const original = frame.data.items.find(item => item.slot === slot);
                const label = original ? `${itemLabel(original)} × ${original.count}` : t("Leerer Slot");
                const slotButton = button(label, () => childFrame(frame, slot));
                slotButton.className = "special-slot";
                slotButton.setAttribute("aria-label", t("Slot {slot}: {item}", { slot: slot + 1, item: label }));
                slotButton.replaceChildren(el("span", original ? catalog.getItemEmoji(original.name) : "+"), el("small", label));
                const icon = original && catalog.getItemIconMeta(original);
                if (icon?.url) {
                    const img = el("img"); img.alt = ""; img.src = icon.url; img.width = img.height = 32;
                    img.addEventListener("error", () => img.replaceWith(el("span", catalog.getItemEmoji(original.name))), { once: true });
                    slotButton.firstChild.replaceWith(img);
                }
                if (original) slotButton.append(el("b", String(original.count), "special-slot-count"));
                slotButton.append(el("small", String(slot + 1), "special-slot-number"));
                grid.append(slotButton);
            });
            body.append(grid);
        }
        function renderItem(frame) {
            const item = frame.item;
            const logic = window.MCBESlotDetailLogic;
            const browser = getItemBrowser();
            const fields = el("div", "", "special-fields special-item-primary"); body.append(fields);
            const searchField = el("div", "", "special-item-search"); fields.append(searchField);
            const heading = el("div", "", "item-picker-header");
            const label = el("label", t("Item-ID"));
            const name = el("input", "", "special-item-name");
            name.type = "text"; name.id = `special-control-${++controlId}`; name.value = item.name;
            label.htmlFor = name.id;
            name.placeholder = t("Name oder Item-ID eingeben");
            name.autocomplete = "off";
            const suggestions = el("div", "", "autocomplete-list special-item-suggestions");
            const choose = button("📖 Item-Browser", () => browser.openPicker({
                onSelect: selectItem, selectionReason, isCurrent: current, focusTarget: choose,
            }));
            heading.append(label, choose); searchField.append(heading, name, suggestions);
            const count = field(fields, "Menge", item.count, { type: "number", min: 1 });
            const countHint = el("p", "", "special-note special-count-hint");
            countHint.id = `special-control-${++controlId}`; count.setAttribute("aria-describedby", countHint.id); body.append(countHint);
            const properties = el("details", "", "special-properties");
            properties.open = Boolean(frame.propertiesOpen);
            properties.append(el("summary", t("Weitere Eigenschaften")));
            properties.addEventListener("toggle", () => { frame.propertiesOpen = properties.open; });
            const extraFields = el("div", "", "special-fields"); properties.append(extraFields); body.append(properties);
            const damage = field(extraFields, "Abnutzung / Datenwert", item.damage, { type: "number", min: 0, max: 32767 });
            const variant = select(extraFields, "Variante", item.damage, []);
            const capacity = model.kind(frame.container.item) === "bundle" ? 64 : 27;
            const destination = select(extraFields, "Zielslot", item.slot, Array.from({ length: capacity }, (_, slot) => slot)
                .filter(slot => slot === frame.originSlot || !frame.container.data.items.some(child => child.slot === slot))
                .map(slot => [slot, String(slot + 1)]));
            const custom = field(extraFields, "Anzeigename", item.display_name || "", { maxLength: textLimits.maxDisplayName });
            const lore = field(extraFields, "Beschreibung (eine Zeile je Eintrag)", (item.lore || []).join("\n"), { multiline: true });
            const enchantments = clone(item.enchantments || []);
            const enchBox = el("div", "", "special-card"); properties.append(enchBox);
            enchBox.append(el("h3", t("Verzauberungen")));
            const enchRows = el("div"); enchBox.append(enchRows);
            const enchSelect = select(enchBox, "Verzauberung hinzufügen", "", []);
            const normalizedName = () => logic.normalizedItemName(name.value);
            let formItemName = logic.normalizedItemName(item.name);
            const current = () => dialog.open && frames.at(-1) === frame && isCurrentContext(context);
            const limitFor = id => model.childCountLimit(frame.container.item, frame.container.data, frame.originSlot,
                id === item.name ? item : { name: id, count: 1 }, specialDepth());
            function selectionReason(id) {
                const limit = limitFor(id);
                return limit.error || (limit.maximum < 1 ? t("Für dieses Item ist im Bundle nicht genügend Platz.") : "");
            }
            function resetItemFields(nextName) {
                const plan = window.MCBEEnchantmentEditorLogic.manualItemResetPlan({
                    previousName: formItemName, nextName, isValidItemId: catalog.isAddableItemId,
                });
                if (plan.shouldReset) {
                    formItemName = plan.nextName;
                    count.value = 1; damage.value = 0; custom.value = ""; lore.value = ""; enchantments.length = 0;
                }
            }
            function selectItem(selected) {
                if (!current() || !canEdit()) return;
                resetItemFields(selected.id);
                name.value = selected.id;
                if (selected.damage !== null && selected.damage !== undefined && Number.isInteger(Number(selected.damage))) damage.value = Number(selected.damage);
                syncFields();
            }
            function drawEnchantments() {
                const id = normalizedName();
                const db = getEnchantments();
                const rows = window.MCBEEnchantmentEditorLogic.enchantmentRowsForItem({
                    itemName: id, enchantmentsDb: db, activeEnchantments: enchantments,
                    isCompatible: catalog.isEnchantmentCompatibleWithItem,
                });
                const available = rows.filter(row => row.compatible && !row.activeEnchantment);
                enchBox.hidden = !catalog.isEnchantableItemForEditor(id) && !enchantments.length;
                enchRows.replaceChildren();
                enchantments.forEach((entry, index) => {
                    const compatible = catalog.isEnchantmentCompatibleWithItem(entry.id, id);
                    const data = db[entry.id];
                    const row = el("div", "", "special-actions");
                    row.append(el("span", logic.localizedEnchantmentName(data, entry.id)
                        + (!compatible ? ` · ${t("unpassend, wird erhalten")}` : "")));
                    const level = field(row, "Stufe", entry.lvl, { type: "number", min: 1, max: data?.max_lvl ?? 1 });
                    level.readOnly = !compatible || !data;
                    level.addEventListener("input", () => { entry.lvl = level.valueAsNumber; });
                    row.append(button("Entfernen", () => { enchantments.splice(index, 1); drawEnchantments(); })); enchRows.append(row);
                });
                enchSelect.replaceChildren();
                for (const [id, label] of [["", t("Bitte wählen")], ...available.map(row => [row.id, logic.localizedEnchantmentName(row.info, row.id)])]) {
                    const option = el("option", label); option.value = id; enchSelect.append(option);
                }
                enchSelect.parentElement.hidden = !available.length;
            }
            enchSelect.addEventListener("change", () => {
                const id = Number(enchSelect.value);
                if (enchSelect.value && catalog.isEnchantmentCompatibleWithItem(id, normalizedName())
                    && !enchantments.some(entry => Number(entry.id) === id)) enchantments.push({ id, lvl: 1 });
                drawEnchantments();
            });
            function build() {
                resetItemFields(normalizedName());
                const result = logic.buildItemForm({ catalog, enchantmentsDb: getEnchantments(), countLimit: limitFor(normalizedName()),
                    slotId: item.slot, previousItem: item.name ? item : null, rawName: name.value, rawCount: count.value,
                    rawDamage: damage.value, rawCustomName: custom.value, rawLore: lore.value, enchantments,
                    maxDisplayName: textLimits.maxDisplayName, maxLoreLines: textLimits.maxLoreLines, maxLoreLineLength: textLimits.maxLoreLineLength,
                    enchantmentLabel: id => logic.localizedEnchantmentName(getEnchantments()[id], id),
                    detailItemLabel: id => itemLabel({ name: id }), specialItemNbtRequirement: catalog.specialItemNbtRequirement,
                });
                if (!result.ok || !result.item) { message(result.error || t("Wähle ein Item.")); return null; }
                const built = model.cleanChild(result.item);
                built.slot = Number(destination.value);
                if (normalizedName() === item.name && item.source_index !== undefined) built.source_index = item.source_index;
                if (window.MCBESpecialItemLogic.sameUserFields(item, built)) return model.cleanChild(item);
                return built;
            }
            const special = button(model.label(item), () => {
                const built = build();
                if (built) {
                    frame.item = built;
                    specialFrame(built, updated => { frame.item = updated; });
                }
            });
            function syncQuantity() {
                const id = normalizedName();
                const limit = limitFor(id);
                const state = logic.itemFormModel({ catalog, rawName: id, rawCount: count.value, rawDamage: damage.value,
                    previousItem: item, countLimit: limit });
                const validId = id === item.name && Boolean(id) || catalog.isAddableItemId(id);
                logic.applyItemFormConstraints(state, { count, damage });
                countHint.textContent = !validId ? t("Wähle ein Item.") : state.preserved && (limit.error || Number(count.value) > limit.maximum)
                    ? t("Vorhandene Menge {count} bleibt unverändert erhalten.", { count: count.value })
                    : limit.error || t("Maximal {max} in diesem Behälter.", { max: limit.maximum });
                accept.disabled = !validId || Boolean(state.countError);
                special.disabled = accept.disabled;
                special.hidden = !model.kind({ name: id }); special.textContent = model.label({ name: id });
                message(validId ? state.countError : "");
            }
            function syncFields() {
                const id = normalizedName();
                const variants = catalog.dataValueVariantsForId(id);
                damage.parentElement.hidden = variants.length > 0;
                variant.parentElement.hidden = !variants.length;
                variant.replaceChildren();
                const options = variants.map(value => [value.damage, itemLabel({ name: id, damage: value.damage })]);
                if (variants.length && !variants.some(value => value.damage === Number(damage.value))) options.unshift([damage.value, t("Datenwert {value}", { value: damage.value })]);
                options.forEach(([value, label]) => { const option = el("option", label); option.value = value; variant.append(option); });
                variant.value = damage.value;
                drawEnchantments(); syncQuantity();
            }
            name.addEventListener("input", syncFields);
            count.addEventListener("input", syncQuantity);
            variant.addEventListener("change", () => { damage.value = variant.value; syncQuantity(); });
            damage.addEventListener("input", syncQuantity);
            disposeAutocomplete = browser.setupAutocomplete(name, suggestions, {
                includeVariants: true, onSelect: selectItem, selectionReason, browserButton: choose,
                onCommit: () => { resetItemFields(normalizedName()); syncFields(); },
            });
            syncFields();
            const actions = el("div", "", "special-actions"); actions.append(special);
            if (item.name) actions.append(button("Item entfernen", () => finish(null)));
            body.append(actions);
            saveFrame = () => {
                const built = build();
                if (!built) return;
                const candidate = model.withChild(frame.container.data, frame.originSlot, built);
                const validation = model.validate(frame.container.item, candidate, specialDepth());
                if (validation) { message(validation); return; }
                finish(built);
            };
            const formState = () => JSON.stringify({
                controls: [name, count, damage, destination, custom, lore].map(input => input.value),
                enchantments: enchantments.map(({ id, lvl }) => [id, lvl]).sort(([a], [b]) => a - b),
            });
            const initialFormState = formState();
            hasInputChanges = () => formState() !== initialFormState;
        }
        function renderBook(frame) {
            const data = frame.data;
            const limits = model.schema.limits;
            const fields = el("div", "", "special-fields"); body.append(fields);
            if ("title" in data) {
                const titleInput = field(fields, "Titel", data.title, { maxLength: limits.title_length });
                const author = field(fields, "Autor", data.author, { maxLength: limits.author_length });
                titleInput.addEventListener("input", () => { data.title = titleInput.value; });
                author.addEventListener("input", () => { data.author = author.value; });
            }
            body.append(el("p", t("{count} / {maximum} Seiten", { count: data.pages.length, maximum: limits.pages }), "special-note"));
            data.pages.forEach((page, index) => {
                const card = el("section", "", "special-card");
                const text = field(card, t("Seite {page}", { page: index + 1 }), page.text, { multiline: true, maxLength: limits.page_length, className: "special-book-page" });
                const count = el("small", `${page.text.length} / ${limits.page_length}`, "special-note");
                text.addEventListener("input", () => { page.text = text.value; count.textContent = `${page.text.length} / ${limits.page_length}`; });
                card.append(count); rowActions(card, data.pages, index, render); body.append(card);
            });
            const add = button("Seite hinzufügen", () => { data.pages.push({ text: "" }); render(); body.querySelectorAll("textarea").item(data.pages.length - 1)?.focus(); });
            add.disabled = data.pages.length >= limits.pages; body.append(add);
        }
        function colors(parent, label, values, onChange) {
            const fieldset = el("fieldset", "", "special-card"); fieldset.append(el("legend", t(label)));
            const list = el("div", "", "special-colors"); fieldset.append(list);
            COLOR_NAMES.forEach((color, index) => {
                const label = el("label", "", "special-color");
                const checkbox = el("input"); checkbox.type = "checkbox"; checkbox.checked = values.includes(index);
                const swatch = el("i"); swatch.style.backgroundColor = COLOR_HEX[index];
                label.append(checkbox, swatch, doc.createTextNode(t(color))); list.append(label);
                checkbox.addEventListener("change", () => {
                    // Preserve repeated and ordered original colors until the user changes this palette.
                    onChange(Array.from(list.querySelectorAll("input")).flatMap((input, id) => input.checked ? [id] : []));
                });
            }); parent.append(fieldset);
        }
        function renderFireworks(frame) {
            const isStar = model.kind(frame.item) === "firework_star";
            const data = frame.data;
            if (!isStar) {
                const flight = select(body, "Flugdauer", data.flight, [1, 2, 3].map(value => [value, String(value)]));
                flight.addEventListener("change", () => { data.flight = Number(flight.value); });
                body.append(el("p", t("Ohne Effekte eignet sich die Rakete für Elytra-Flüge."), "special-note"));
            }
            data.explosions.forEach((effect, index) => {
                const card = el("section", "", "special-card"); card.append(el("h3", t("Effekt {number}", { number: index + 1 })));
                const shape = select(card, "Form", effect.shape, SHAPES.map((name, id) => [id, t(name)]));
                shape.addEventListener("change", () => { effect.shape = Number(shape.value); });
                colors(card, "Farben", effect.colors, value => { effect.colors = value; });
                colors(card, "Verblassfarben (optional)", effect.fade, value => { effect.fade = value; });
                for (const [key, text] of [["trail", "Schweif"], ["flicker", "Funkeln"]]) {
                    const label = el("label", "", "special-check"); const check = el("input"); check.type = "checkbox"; check.checked = effect[key];
                    check.addEventListener("change", () => { effect[key] = check.checked; }); label.append(check, doc.createTextNode(t(text))); card.append(label);
                }
                rowActions(card, data.explosions, index, render); body.append(card);
            });
            const add = button("Effekt hinzufügen", () => { data.explosions.push({ shape: 0, colors: [15], fade: [], trail: false, flicker: false }); render(); });
            add.disabled = data.explosions.length >= (isStar ? 1 : model.schema.limits.explosions); body.append(add);
        }
        function renderBanner(frame) {
            const data = frame.data;
            body.append(el("p", t("Ebene 1 liegt ganz unten. Jede weitere Ebene überlagert die vorherigen Muster."), "special-note"));
            const layout = el("div", "", "special-banner-layout");
            const preview = el("figure", "", "special-banner-preview");
            const stage = el("div", "", "special-banner-stage");
            const canvas = el("canvas", "", "special-preview"); canvas.width = 20; canvas.height = 40; canvas.hidden = true;
            canvas.setAttribute("role", "img"); stage.append(canvas);
            const caption = el("figcaption");
            caption.append(el("strong", t("Vanilla-Vorschau")));
            const baseColor = Number(frame.item.damage ?? 15);
            caption.append(el("p", t("Grundfarbe: {color} · {count} / {max} Ebenen", {
                color: t(COLOR_NAMES[baseColor]), count: data.patterns.length, max: model.schema.limits.patterns,
            }), "special-note"));
            const status = el("p", "", "special-note"); status.setAttribute("role", "status");
            const downloadHint = el("p", t("Lädt das offizielle Minecraft-Texturpaket über die Vanilla-Icons. Danach ist die Vorschau auch offline verfügbar."), "special-note");
            const reload = button("Bannermuster laden", async () => {
                reload.disabled = true; retry.hidden = true;
                status.textContent = t("Bannermuster werden geladen …");
                try {
                    const result = await loadBannerPatterns();
                    if (!preview.isConnected || frames.at(-1) !== frame) return;
                    if (!result?.success) throw new Error(result?.error || t("Bannermuster konnten nicht geladen werden."));
                    await draw();
                } catch (error) {
                    if (preview.isConnected && frames.at(-1) === frame) status.textContent = error.message;
                } finally { reload.disabled = !canLoadBannerPatterns(); }
            });
            const retry = button("Erneut versuchen", () => draw());
            reload.hidden = true; retry.hidden = true; downloadHint.hidden = true;
            caption.append(status, downloadHint, reload, retry); preview.append(stage, caption);
            const layers = el("div", "", "special-banner-layers");
            layout.append(preview, layers); body.append(layout);
            let generation = 0;
            async function draw() {
                const current = ++generation;
                const active = () => current === generation && preview.isConnected && frames.at(-1) === frame;
                canvas.hidden = true; reload.hidden = true; retry.hidden = true; downloadHint.hidden = true;
                preview.dataset.state = "loading";
                status.textContent = t("Bannervorschau wird geladen …");
                try {
                    const rendered = await bannerRenderer.render(baseColor, data.patterns, getBannerPatterns(), COLOR_HEX);
                    if (!active()) return;
                    if (!rendered) {
                        preview.dataset.state = "missing";
                        status.textContent = t("Für diese Vorschau fehlen Bannermuster im lokalen Icon-Cache.");
                        reload.hidden = false; reload.disabled = !canLoadBannerPatterns(); downloadHint.hidden = false;
                        return;
                    }
                    canvas.width = rendered.width; canvas.height = rendered.height;
                    canvas.getContext("2d").drawImage(rendered, 0, 0);
                    const description = data.patterns.map((entry, index) => t("Ebene {number}: {pattern}, {color}", {
                        number: index + 1, pattern: t(PATTERN_NAMES[entry.pattern]), color: t(COLOR_NAMES[entry.color]),
                    })).join("; ");
                    canvas.setAttribute("aria-label", t("Bannervorschau, Grundfarbe {color}", { color: t(COLOR_NAMES[baseColor]) }) + (description ? "; " + description : ""));
                    canvas.hidden = false; status.textContent = ""; preview.dataset.state = "ready";
                } catch (_error) {
                    if (!active()) return;
                    preview.dataset.state = "error";
                    status.textContent = t("Die Bannervorschau konnte nicht geladen werden. Deine Änderungen bleiben erhalten.");
                    retry.hidden = false;
                }
            }
            refreshPreview = draw;
            data.patterns.forEach((pattern, index) => {
                const card = el("section", "", "special-card"); card.append(el("h3", t("Ebene {number}", { number: index + 1 })));
                const fields = el("div", "", "special-fields"); card.append(fields);
                const type = select(fields, "Muster", pattern.pattern, model.schema.patterns.map(code => [code, t(PATTERN_NAMES[code] || code)]));
                const color = select(fields, "Farbe", pattern.color, COLOR_NAMES.map((name, id) => [id, t(name)]));
                type.addEventListener("change", () => { pattern.pattern = type.value; draw(); });
                color.addEventListener("change", () => { pattern.color = Number(color.value); draw(); });
                rowActions(card, data.patterns, index, render); layers.append(card);
            });
            const add = button("Muster hinzufügen", () => { data.patterns.push({ pattern: "bo", color: 0 }); render(); });
            add.disabled = data.patterns.length >= model.schema.limits.patterns; layers.append(add); draw();
        }
        accept.addEventListener("click", () => {
            if (canEdit()) saveFrame();
            else message(t("Bearbeitung ist aktuell gesperrt."));
        });
        dialog.querySelectorAll('[data-special="cancel"]').forEach(node => node.addEventListener("click", cancel));
        dialog.addEventListener("cancel", event => { event.preventDefault(); cancel(); });
        dialog.addEventListener("close", () => {
            // Native cancellation may restore its own opener after close().
            // Only correct that fallback; never steal a newer user selection.
            if (!dialog.open && (doc.activeElement === nativeReturnFocus || doc.activeElement === doc.body)) returnFocus?.focus?.();
        });
        dialog.addEventListener("keydown", event => {
            event.stopPropagation();
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") event.preventDefault();
        });
        return {
            refreshPreview() { refreshPreview(); },
            hasPendingChanges() {
                if (!dialog.open) return false;
                return inheritedDraft || hasInputChanges() || frames.some(frame =>
                    JSON.stringify(frame.item) !== frame.initialItemState
                    || frame.type === "special" && JSON.stringify(frame.data) !== frame.initialDataState);
            },
            open(item, nextContext, slots = [], focusAfterClose = null, originalItem = item) {
                if (!item || !model.kind(item) || !canEdit()) return;
                context = nextContext; frames = []; nativeReturnFocus = doc.activeElement;
                returnFocus = focusAfterClose || nativeReturnFocus;
                inheritedDraft = !window.MCBESpecialItemLogic.sameUserFields(item, originalItem)
                    || Boolean(item.replace_original_nbt) !== Boolean(originalItem?.replace_original_nbt);
                specialFrame(item, null, false);
                const found = openPath(slots);
                if (!found) frames = frames.slice(0, 1);
                render();
                if (!found) message(t("Der gesuchte Inhalt wurde inzwischen geändert. Suche erneut."));
                if (!dialog.open) dialog.showModal();
                focusInitialControl();
            },
        };
    }
    window.MCBESpecialItemEditor = { createEditor };
}());
