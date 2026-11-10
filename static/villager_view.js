(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const model = window.MCBEVillagerModel;
    const esc = window.MCBEHtmlUtils.escapeHtml;

    function nbtTree(node, name = "NBT", budget = { left: 2000 }, depth = 0) {
        if (budget.left-- <= 0 || depth > 32) return `<div>${esc(t("Weitere Rohdaten sind ausgeblendet."))}</div>`;
        if (node === null || typeof node !== "object") {
            return `<div class="villager-nbt-leaf"><strong>${esc(name)}</strong>: ${esc(typeof node === "string" ? JSON.stringify(node) : String(node))}</div>`;
        }
        const type = String(node.type || "?");
        const title = `<strong>${esc(name)}</strong> <span class="villager-nbt-type">${esc(type)}</span>`;
        const truncation = node.truncated ? `<p>${esc(typeof node.truncated === "string" ? node.truncated : t("Anzeige begrenzt"))}</p>` : "";
        if (node.value && typeof node.value === "object") {
            const entries = Object.entries(node.value);
            const children = [];
            for (const [key, value] of entries) {
                if (budget.left <= 0) break;
                children.push(nbtTree(value, key, budget, depth + 1));
            }
            const omitted = children.length < entries.length ? `<p>${esc(t("Weitere Rohdaten sind ausgeblendet."))}</p>` : "";
            return `<details${depth === 0 ? " open" : ""}><summary>${title} · ${entries.length}</summary>${children.join("")}${truncation}${omitted}</details>`;
        }
        const value = typeof node.value === "string" ? JSON.stringify(node.value) : String(node.value ?? "—");
        return `<div class="villager-nbt-leaf">${title}: ${esc(value)}${truncation}</div>`;
    }

    function itemText(item) {
        if (!item || typeof item !== "object") return "—";
        return `${typeof item.count === "number" ? `${item.count} × ` : ""}${String(item.name || t("Unbekannt"))}`;
    }

    const chunkAssignmentMissing = row => row.issues?.some(issue => issue.code === "orphan_actor");

    function equipmentHtml(equipment = {}) {
        const slots = (equipment.slots || []).map(slot => {
            const saved = /^(Armor|Mainhand|Offhand)\[(\d+)\]$/.exec(slot.slot || "");
            return { ...slot, container: slot.container || saved?.[1], index: slot.index ?? Number(saved?.[2]) };
        });
        const occupied = equipment.occupied_count ?? slots.filter(slot => slot.state === "occupied").length;
        const uncertain = equipment.unknown_count > 0 || equipment.unknown_containers?.length > 0 || slots.some(slot => slot.state === "unknown");
        const title = uncertain ? t("Ausrüstung ({count} belegt, weitere unklar)", { count: occupied }) : t("Ausrüstung ({count} belegt)", { count: occupied });
        const slotValue = slot => {
            if (slot.state === "empty") return `<span class="villager-equipment-empty">${esc(t("Leer"))}</span>`;
            const value = slot.item ? esc(itemText(slot.item)) : "";
            return slot.state === "occupied" ? value : `${value}<small class="villager-equipment-unknown">${esc(t("Nicht eindeutig lesbar"))}</small>`;
        };
        const group = container => {
            const entries = slots.filter(slot => slot.container === container);
            const metadata = equipment.containers?.find(entry => entry.container === container);
            const opaque = equipment.unknown_containers?.includes(container) || metadata?.total === null;
            // Bedrock Armor indices follow Head/Torso/Legs/Feet/Body. Body's
            // presence in saved villagers does not establish an in-game effect.
            const labels = [t("Kopf"), t("Brust"), t("Beine"), t("Füße"), t("Zusatzslot (Body)")];
            const hand = container === "Mainhand" ? t("Haupthand") : t("Nebenhand");
            let content = entries.map(slot => {
                const label = container === "Armor" ? labels[slot.index] || t("Zusätzlicher Rüstungsplatz {slot}", { slot: slot.index + 1 })
                    : slot.index === 0 ? hand : t("Zusätzlicher Handplatz {slot}", { slot: slot.index + 1 });
                return `<div class="villager-equipment-slot"><dt title="${esc(slot.slot)}">${esc(label)}</dt><dd>${slotValue(slot)}</dd></div>`;
            }).join("");
            if (!entries.length) {
                const message = opaque ? t("Nicht eindeutig lesbar") : metadata?.present ? t("Keine Plätze gespeichert.") : t("Nicht gespeichert");
                content = `<div class="villager-equipment-slot"><dt>${esc(container === "Armor" ? t("Plätze") : hand)}</dt><dd${opaque ? ' class="villager-equipment-unknown"' : ""}>${esc(message)}</dd></div>`;
            }
            if (metadata?.truncated) content += `<div class="villager-equipment-truncated">${esc(t("Weitere gespeicherte Plätze sind ausgeblendet."))}</div>`;
            return content;
        };
        return `<details id="villagerEquipmentDetails" class="villager-disclosure"><summary>${esc(title)}</summary>
            <section class="villager-equipment-group" data-equipment-group="Armor"><h4>${esc(t("Rüstung (Armor)"))}</h4><dl class="villager-equipment-slots">${group("Armor")}</dl></section>
            <section class="villager-equipment-group"><h4>${esc(t("Haupt- und Nebenhand"))}</h4><dl class="villager-equipment-slots"><div data-equipment-group="Mainhand">${group("Mainhand")}</div><div data-equipment-group="Offhand">${group("Offhand")}</div></dl></section>
            ${uncertain ? `<p class="hint-text">${esc(t("Unklare Ausrüstungsdaten bleiben unverändert. Die gespeicherten Werte stehen in den Rohdaten."))}</p>` : ""}
            </details>`;
    }

    function createVillagerView({ doc = document } = {}) {
        const el = id => doc.getElementById(id);
        const text = (id, value) => {
            const node = el(id), next = String(value ?? "");
            if (node && node.textContent !== next) node.textContent = next;
        };
        const show = (id, value) => { const node = el(id); if (node && node.hidden === Boolean(value)) node.hidden = !value; };
        const disable = (id, value) => { const node = el(id); if (node && node.disabled !== Boolean(value)) node.disabled = Boolean(value); };
        const option = (value, label) => `<option value="${esc(value)}">${esc(label)}</option>`;
        const optionKeys = new Map(), htmlKeys = new Map();
        let data = null, generation = 0, renderedPageKey = "", rowNodes = new Map(), mapView = null;
        let diagnosticState = null;
        function html(id, value) {
            const node = el(id);
            if (node && htmlKeys.get(id) !== value) { node.innerHTML = value; htmlKeys.set(id, value); }
        }
        function options(id, values, current) {
            const node = el(id);
            if (!node) return;
            const key = JSON.stringify(values);
            if (optionKeys.get(id) !== key) { node.innerHTML = values.map(([value, label]) => option(value, label)).join(""); optionKeys.set(id, key); }
            const next = String(current ?? "");
            if (node.value !== next) node.value = next;
        }
        function notice(id, message, kind = "") {
            const node = el(id);
            if (!node) return;
            text(id, message || "");
            show(id, !!message);
            const classes = `villager-notice ${kind}`.trim();
            if (node.className !== classes) node.className = classes;
        }
        function collection(state) {
            const locale = doc.documentElement?.lang || "";
            if (!data || data.rows !== state.rows || data.preferences !== state.preferences || data.locale !== locale) {
                const labels = values => [...values].sort((a, b) => model.compareText(a[1], b[1]));
                data = {
                    rows: state.rows, preferences: state.preferences, locale, generation: ++generation,
                    byId: new Map(state.rows.map(row => [row.id, row])),
                    injured: state.rows.filter(model.isInjured).length,
                    professions: labels(new Map(state.rows.map(row => [String(row.profession?.id ?? "unknown"), t(row.profession?.label || "Unbekannt")]))),
                    tiers: [...new Map(state.rows.map(row => [String(row.trade_tier ?? "unknown"), t(row.trade_tier_label || "Unbekannt")]))].sort((a, b) => Number(a[0]) - Number(b[0])),
                    dimensions: labels(new Map(state.rows.map(row => [String(row.dimension ?? "unknown"), model.dimensionLabel(row.dimension)]))),
                    mapPlayers: null, knownDimensions: null,
                    filterKey: "", filtered: [], filteredIds: new Set(), regionCounts: null,
                };
            }
            if (!data.knownDimensions || data.mapPlayers !== state.mapPlayers) {
                data.mapPlayers = state.mapPlayers;
                data.knownDimensions = [...new Set([0, 1, 2, ...state.rows.map(row => row.dimension).filter(Number.isInteger),
                    ...state.preferences.regions.map(region => region.dimension).filter(Number.isInteger),
                    ...(state.mapPlayers || []).map(player => player.dimension).filter(Number.isInteger)])].sort((a, b) => a - b);
            }
            const key = JSON.stringify([state.filters, state.sort, state.direction]);
            if (data.filterKey !== key) {
                data.filtered = model.sortedRows(model.filterRows(state.rows, state.filters, state.preferences), state.sort, state.direction, state.preferences);
                data.filteredIds = new Set(data.filtered.map(row => row.id));
                data.filterKey = key;
            }
            return data;
        }
        function renderFilters(state, info) {
            options("villagerProfession", [["", t("Alle Berufe")], ...info.professions], state.filters.profession);
            options("villagerTier", [["", t("Alle Handelsstufen")], ...info.tiers], state.filters.tier);
            options("villagerDimension", [["", t("Alle Dimensionen")], ...info.dimensions], state.filters.dimension);
            options("villagerRegion", [["", t("Alle Regionen")], ["none", t("Ohne Region")], ...state.preferences.regions.map(region => [region.id, region.name])], state.filters.region);
            options("villagerMapDimension", info.knownDimensions.map(d => [String(d), model.dimensionLabel(d)]), state.mapDimension);
            const regionDimension = el("villagerRegionDimension")?.value || "0";
            // Deleting another region must not remove the selected dimension
            // from a still-open draft when it was the last saved reference.
            const regionDimensions = [...new Set([...info.knownDimensions, ...(state.regionDirty ? [Number(regionDimension)] : [])])].filter(Number.isInteger).sort((a, b) => a - b);
            options("villagerRegionDimension", regionDimensions.map(d => [String(d), model.dimensionLabel(d)]), regionDimensions.includes(Number(regionDimension)) ? regionDimension : "0");
            if (el("villagerSort")) el("villagerSort").value = state.sort;
            const sortLabels = { name: t("Name"), profession: t("Beruf"), tier: t("Handelsstufe"), health: t("Gesundheit"), region: t("Region"), dimension: t("Dimension") };
            const headings = el("villagerTableHead");
            for (const header of headings?.querySelectorAll("th[data-sort-columns]") || []) {
                if (header.dataset.sortColumns.split(" ").includes(state.sort)) header.setAttribute("aria-sort", state.direction === "desc" ? "descending" : "ascending");
                else header.removeAttribute("aria-sort");
            }
            for (const button of headings?.querySelectorAll("button[data-sort]") || []) {
                const active = button.dataset.sort === state.sort;
                const field = sortLabels[button.dataset.sort];
                const label = active && state.direction === "asc" ? t("Nach {field} absteigend sortieren", { field }) : t("Nach {field} aufsteigend sortieren", { field });
                button.setAttribute("aria-pressed", String(active));
                button.setAttribute("aria-label", label);
                button.title = label;
                button.querySelector(".villager-sort-arrow").textContent = active ? state.direction === "desc" ? "↓" : "↑" : "↕";
            }
            const chips = [];
            const selectedLabel = (values, value) => values.find(entry => entry[0] === value)?.[1] || value;
            if (state.filters.query.trim()) chips.push(["query", t("Suche: {query}", { query: state.filters.query.trim() })]);
            if (state.filters.profession) chips.push(["profession", selectedLabel(info.professions, state.filters.profession)]);
            if (state.filters.region) chips.push(["region", state.filters.region === "none" ? t("Ohne Region") : state.preferences.regions.find(r => r.id === state.filters.region)?.name || state.filters.region]);
            if (state.filters.tier) chips.push(["tier", selectedLabel(info.tiers, state.filters.tier)]);
            if (state.filters.dimension) chips.push(["dimension", selectedLabel(info.dimensions, state.filters.dimension)]);
            if (state.filters.injured) chips.push(["injured", t("Nur Verletzte")]);
            if (state.filters.editable) chips.push(["editable", t("Nur bearbeitbare")]);
            html("villagerActiveFilters", chips.map(([key, label]) => `<button type="button" class="villager-filter-chip" data-action="remove-filter" data-filter="${key}" aria-label="${esc(t("Filter entfernen: {filter}", { filter: label }))}">${esc(label)}<span aria-hidden="true">×</span></button>`).join(""));
            show("villagerActiveFilters", chips.length > 0);
            show("villagerResetFilters", chips.length > 0);
            const extra = Number(!!state.filters.tier) + Number(!!state.filters.dimension) + Number(state.filters.editable);
            text("villagerMoreFilterCount", extra);
            show("villagerMoreFilterCount", extra > 0);
        }
        function renderRows(state, page, info) {
            const body = el("villagerRows");
            if (!body) return;
            const key = `${info.generation}/${page.rows.map(row => row.id).join("\0")}`;
            if (key !== renderedPageKey) {
                const active = doc.activeElement;
                const focusedId = body.contains(active) ? active?.dataset?.id : null;
                const focusedAction = focusedId ? active.dataset.action : null;
                body.innerHTML = page.rows.map(row => {
                    const name = model.displayName(row, state.preferences.aliases);
                    const alias = state.preferences.aliases[model.aliasKey(row)];
                    const regions = model.matchingRegions(row, state.preferences.regions).map(region => region.name).join(", ");
                    const profession = `${t(row.profession?.label || "Unbekannt")} · ${t(row.trade_tier_label || "—")}`;
                    const notes = [!row.editable && !row.inventory_editable && !row.name_editable ? t("Nur lesen") : "", row.is_baby === true ? t("Kind") : ""].filter(Boolean).join(" · ");
                    return `<tr data-villager-id="${esc(row.id)}">
                        <td><label class="villager-row-check"><input type="checkbox" data-action="select" data-id="${esc(row.id)}" aria-label="${esc(t("{name} markieren", { name }))}"></label></td>
                        <td><button type="button" class="villager-name" data-action="detail" data-id="${esc(row.id)}" aria-controls="villagerDetail" aria-expanded="false">${esc(name)}</button>
                            ${alias && alias !== name ? `<small>${esc(t("Editor-Alias"))}: ${esc(alias)}</small>` : ""}
                            <small class="villager-mobile-profession">${esc(profession)}</small>
                            <small class="villager-mobile-location">${esc(regions ? `${regions} · ` : "")}<code>${esc(model.positionText(row))}</code> · ${esc(model.dimensionLabel(row.dimension))}</small>
                            ${notes ? `<span class="villager-row-note">${esc(notes)}</span>` : ""}
                            ${chunkAssignmentMissing(row) ? `<span class="villager-orphan-badge">${esc(t("Chunk-Zuordnung fehlt"))}</span>` : ""}</td>
                        <td>${esc(t(row.profession?.label || "Unbekannt"))}<small>${esc(t(row.trade_tier_label || "—"))}</small></td>
                        <td class="villager-health${model.isInjured(row) ? " injured" : ""}">${esc(model.healthText(row.health))}</td>
                        <td>${regions ? esc(regions) : `<code>${esc(model.positionText(row))}</code>`}<small>${regions ? `<code>${esc(model.positionText(row))}</code> · ` : ""}${esc(model.dimensionLabel(row.dimension))}</small></td>
                    </tr>`;
                }).join("") || `<tr><td colspan="5" class="villager-no-results"><strong>${esc(state.rows.length ? t("Keine Dorfbewohner entsprechen diesen Filtern.") : t("Keine gespeicherten Dorfbewohner gefunden."))}</strong>${state.rows.length ? `<button type="button" class="btn-text" data-action="reset-filters">${esc(t("Filter zurücksetzen"))}</button>` : esc(t("Prüfe die gewählte Welt oder starte den Scan erneut."))}</td></tr>`;
                renderedPageKey = key;
                rowNodes = new Map([...body.querySelectorAll("tr[data-villager-id]")].map(node => [node.dataset.villagerId, node]));
                if (focusedId) [...body.querySelectorAll("[data-id]")].find(node => node.dataset.id === focusedId && node.dataset.action === focusedAction)?.focus({ preventScroll: true });
            }
            for (const [id, node] of rowNodes) {
                const active = id === state.activeId, selected = state.selected.has(id);
                node.classList.toggle("is-active", active);
                node.classList.toggle("is-selected", selected);
                const checkbox = node.querySelector('input[data-action="select"]');
                if (checkbox) { checkbox.checked = selected; checkbox.disabled = state.busy || state.scanning; }
                const button = node.querySelector(".villager-name");
                if (button) { button.setAttribute("aria-expanded", String(active)); button.disabled = state.busy || state.scanning; }
            }
            const all = el("villagerSelectPage");
            if (all) {
                const selectedOnPage = page.rows.filter(row => state.selected.has(row.id)).length;
                all.checked = page.rows.length > 0 && selectedOnPage === page.rows.length;
                all.indeterminate = selectedOnPage > 0 && selectedOnPage < page.rows.length;
                all.disabled = state.busy || state.scanning || !page.rows.length;
            }
            text("villagerPageInfo", t("Seite {page} von {pages}", { page: page.page, pages: page.pages }));
            disable("villagerPreviousPage", page.page <= 1 || state.busy || state.scanning);
            disable("villagerNextPage", page.page >= page.pages || state.busy || state.scanning);
            text("villagerSortDirection", state.direction === "desc" ? "↓" : "↑");
            el("villagerSortDirection")?.setAttribute("aria-label", state.direction === "desc" ? t("Aufsteigend sortieren") : t("Absteigend sortieren"));
        }
        function renderMap(state, info) {
            if (!state.mapOpen) return;
            if (!el("villagerMap")) return;
            mapView ||= window.MCBEVillagerMap.createVillagerMap({ doc });
            mapView.render(state, info);
            const playerStatus = state.mapPlayersLoading ? t("Spielerpositionen werden geladen …") : state.mapPlayersError;
            show("villagerMapPlayerHint", !playerStatus && !!el("villagerMapPlayerHint")?.textContent);
            text("villagerMapPlayerStatus", playerStatus || "");
            show("villagerMapPlayerStatus", !!playerStatus && state.mapPlayerMode !== "none");
            show("villagerMapPlayersRetry", !!state.mapPlayersError && !state.mapPlayersLoading && state.mapPlayerMode !== "none");
        }
        function renderRegions(state, info) {
            for (const node of el("villagerRegionForm")?.querySelectorAll("input, select, button") || []) node.disabled = state.readOnly || state.preferencesBusy || state.busy || state.scanning;
            text("villagerRegionError", state.regionError || "");
            show("villagerRegionError", !!state.regionError);
            if (!state.regionsOpen) return;
            if (!info.regionCounts) {
                info.regionCounts = new Map(state.preferences.regions.map(region => [region.id, 0]));
                for (const row of state.rows) for (const region of model.matchingRegions(row, state.preferences.regions)) info.regionCounts.set(region.id, info.regionCounts.get(region.id) + 1);
            }
            html("villagerRegionList", state.preferences.regions.map(region => `<li><div><strong>${esc(region.name)}</strong><small>${esc(model.dimensionLabel(region.dimension))} · X ${esc(region.min_x)} … ${esc(region.max_x)} · Z ${esc(region.min_z)} … ${esc(region.max_z)}${region.min_y !== undefined ? ` · Y ${esc(region.min_y)} … ${esc(region.max_y)}` : ""} · ${esc(t("{count} Bewohner", { count: info.regionCounts.get(region.id) }))}</small></div><div class="villager-actions"><button type="button" class="btn-text" data-action="edit-region" data-id="${esc(region.id)}">${esc(t("Bearbeiten"))}</button><button type="button" class="btn-text" data-action="delete-region" data-id="${esc(region.id)}">${esc(t("Löschen"))}</button></div></li>`).join("") || `<li>${esc(t("Noch keine Regionen angelegt."))}</li>`);
            for (const node of el("villagerRegionList")?.querySelectorAll("button") || []) node.disabled = state.preferencesBusy || state.busy || state.scanning || state.readOnly;
        }
        function renderDiagnostics() {
            if (!el("villagerDiagnostics")?.open || !diagnosticState) return;
            const state = diagnosticState, byId = collection(state).byId, groups = new Map();
            for (const item of state.diagnostics || []) {
                const key = JSON.stringify([item.code, item.message]);
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(item);
            }
            const content = [...groups].map(([key, items]) => {
                const first = items[0];
                const title = first.code === "orphan_actor" ? t("Chunk-Zuordnung fehlt")
                    : first.code === "missing_actor" ? t("Fehlender Kreaturdatensatz") : first.message || first.code || String(first);
                const explanation = first.code === "orphan_actor" ? t("Die Bewohnerdaten sind lesbar, aber keinem gespeicherten Chunk zugeordnet. Name, Gesundheit und Vorräte bleiben schreibgeschützt.")
                    : first.code === "missing_actor" ? t("Ein gespeicherter Verweis hat keine zugehörigen Kreaturdaten. Ob es ein Dorfbewohner war, ist nicht feststellbar.") : "";
                const references = items.map(item => {
                    const row = byId.get(item.id);
                    if (row) {
                        const location = model.hasPosition(row) ? model.positionText(row) : "";
                        const identity = row.unique_id ? `ID ${row.unique_id}` : row.id;
                        const context = [location, Number.isInteger(row.dimension) ? model.dimensionLabel(row.dimension) : "", identity].filter(Boolean).join(" · ");
                        return `<li><button type="button" class="btn-text villager-diagnostic-link" data-action="diagnostic-detail" data-id="${esc(row.id)}"><span>${esc(model.displayName(row, state.preferences.aliases))}</span><small>${esc(context)}</small></button></li>`;
                    }
                    const reference = item.actor ? t("Actor-Referenz: {id}", { id: item.actor })
                        : item.record ? t("Datenbankschlüssel: {id}", { id: item.record })
                        : item.id ? t("Datensatz: {id}", { id: item.id }) : "";
                    return reference ? `<li><code>${esc(reference)}</code></li>` : "";
                }).filter(Boolean).join("");
                const heading = `${esc(title)} <span class="villager-diagnostic-count">(${items.length})</span>`;
                return explanation || references ? `<li><details class="villager-diagnostic-group" data-diagnostic-key="${esc(key)}" data-diagnostic-code="${esc(first.code || "")}"><summary>${heading}</summary>${explanation ? `<p class="hint-text">${esc(explanation)}</p>` : ""}${references ? `<ul class="villager-diagnostic-records">${references}</ul>` : ""}</details></li>`
                    : `<li>${heading}</li>`;
            }).join("");
            const list = el("villagerDiagnosticList");
            if (htmlKeys.get("villagerDiagnosticList") !== content) {
                const opened = new Set([...(list?.querySelectorAll("details[open]") || [])].map(node => node.dataset.diagnosticKey));
                html("villagerDiagnosticList", content);
                for (const group of list?.querySelectorAll("details") || []) group.open = opened.has(group.dataset.diagnosticKey);
            }
            for (const button of list?.querySelectorAll("button") || []) button.disabled = state.busy || state.scanning || state.saving;
        }
        el("villagerDiagnostics")?.addEventListener("toggle", renderDiagnostics);
        function render(state) {
            show("villagerPending", !!state.pending?.length);
            html("villagerPendingRows", (state.pending || []).map((entry, index) => `<div class="villager-pending-row"><span>${esc(t("{count} Änderungen vorgemerkt", { count: entry.rows.length }))}: ${esc(entry.rows.map(row => row.label || row.name || row.id).join(", "))}</span><button type="button" class="btn btn-secondary btn-sm" data-remove-pending="${index}">${esc(t("Vormerkung entfernen"))}</button></div>`).join(""));
            text("villagerWorldLabel", state.worldLabel || state.worldPath);
            show("villagerEmpty", !state.loaded && !state.scanning);
            show("villagerResults", state.loaded);
            show("villagerScanProgress", state.scanning);
            show("villagerCancelScan", state.scanning);
            disable("villagerScan", !state.worldPath || state.scanning || state.busy || state.preferencesBusy);
            text("villagerScan", state.loaded ? t("Neu scannen") : t("Dorfbewohner suchen"));
            text("villagerProgressText", state.progress || t("Gespeicherte Kreaturen werden gelesen …"));
            notice("villagerStatus", state.message, state.messageKind);
            notice("villagerStale", state.staleReason ? state.serverOnline
                ? t("Letzter Scanstand · schreibgeschützt. Zum Bearbeiten Server stoppen und neu scannen.")
                : t("Veralteter Scanstand · schreibgeschützt. Zum Bearbeiten neu scannen.") : "", "warning");
            notice("villagerWriteGate", state.staleReason ? "" : state.blockedReason, "warning");
            const info = collection(state), page = model.pageRows(info.filtered, state.page, state.pageSize);
            text("villagerInjured", `(${info.injured})`);
            renderFilters(state, info);
            const total = `<span id="villagerTotal">${esc(model.healthNumber(state.rows.length))}</span>`;
            html("villagerResultInfo", info.filtered.length === state.rows.length ? `<strong>${total} ${esc(t("Bewohner"))}</strong>` : `<strong>${esc(model.healthNumber(info.filtered.length))}</strong> ${esc(t("von"))} ${total} ${esc(t("Bewohner"))}`);
            renderRows(state, page, info);
            const hiddenCount = [...state.selected].filter(id => !info.filteredIds.has(id)).length;
            text("villagerSelectionInfo", state.selected.size ? t("{count} markiert", { count: state.selected.size }) + (hiddenCount ? ` · ${t("{count} davon ausgeblendet", { count: hiddenCount })}` : "") : t("Entwurf ohne Auswahl"));
            show("villagerBatchForm", state.selected.size > 0 || state.batchDirty);
            show("villagerClearSelection", state.selected.size > 0);
            disable("villagerClearSelection", !state.selected.size || state.busy || state.scanning);
            disable("villagerSelectFiltered", !info.filtered.length || state.busy || state.scanning);
            const healthBlocked = state.busy || state.scanning || !!state.staleReason || !!state.blockedReason;
            disable("villagerBatchFields", healthBlocked);
            disable("villagerBatchCurrent", el("villagerBatchHeal")?.checked === true);
            disable("villagerBatchPreview", healthBlocked || !state.selected.size || !state.batchDirty);
            text("villagerBatchHint", state.selected.size ? t("Leere Werte bleiben unverändert.") : t("Wähle Bewohner aus, um diesen Entwurf zu prüfen."));
            disable("villagerDetailFields", healthBlocked || !state.detail?.editable);
            disable("villagerDetailMax", state.detail?.health?.max_editable === false);
            disable("villagerDetailCurrent", el("villagerDetailHeal")?.checked === true);
            disable("villagerDetailPreview", healthBlocked || !state.detail?.editable || !state.detailDirty);
            const canHeal = !!state.detail?.editable && model.isInjured(state.detail);
            show("villagerDetailHealAction", canHeal);
            disable("villagerDetailHealAction", healthBlocked || !canHeal);
            const nameBlocked = healthBlocked || state.preferencesBusy || !state.detail?.name_editable;
            disable("villagerName", nameBlocked);
            disable("villagerNamePreview", nameBlocked || !state.nameDirty);
            disable("villagerNameRemove", nameBlocked || !el("villagerName")?.value);
            disable("villagerNameReset", nameBlocked);
            for (const id of ["villagerNameDirty", "villagerNameReset"]) show(id, state.nameDirty);
            const inventoryBlocked = state.readOnly || !!state.blockedReason || !!state.staleReason || state.busy || state.scanning || state.preferencesBusy || !state.detail?.inventory?.editable;
            disable("villagerInventoryFields", inventoryBlocked);
            disable("villagerInventoryPreview", inventoryBlocked || !state.inventoryDirty);
            disable("villagerInventoryReset", state.saving || state.scanning);
            for (const slot of state.detail?.inventory?.slots || []) {
                disable(`villagerStockCount${slot.slot}`, !el(`villagerStockItem${slot.slot}`)?.value);
            }
            const aliasEditable = !!model.aliasKey(state.detail);
            disable("villagerAliasSave", !aliasEditable || state.preferencesBusy || state.readOnly || state.busy || state.scanning || !state.aliasDirty);
            disable("villagerAlias", !aliasEditable || state.preferencesBusy || state.readOnly || state.saving || state.scanning);
            disable("villagerRegionSave", state.preferencesBusy || state.readOnly || state.busy || state.scanning || !state.regionDirty);
            for (const [id, dirty] of [["villagerDetailDirty", state.detailDirty], ["villagerBatchDirty", state.batchDirty], ["villagerAliasDirty", state.aliasDirty], ["villagerAliasDraftMark", state.aliasDirty], ["villagerRegionDirty", state.regionDirty], ["villagerRegionDraftMark", state.regionDirty], ["villagerDetailReset", state.detailDirty], ["villagerBatchReset", state.batchDirty]]) show(id, dirty);
            disable("villagerDetailReset", state.saving || state.scanning);
            disable("villagerBatchReset", state.saving || state.scanning);
            for (const id of ["villagerInventoryDirty", "villagerInventoryDraftMark", "villagerInventoryReset"]) show(id, state.inventoryDirty);
            const draft = state.detailDirty || state.nameDirty || state.inventoryDirty || state.batchDirty || state.aliasDirty || state.regionDirty || state.preview?.change_count > 0;
            show("villagerDraftStatus", draft);
            text("villagerDraftStatus", t("Ungespeicherte Eingaben"));
            el("villagerWorkspace")?.classList.toggle("has-detail", !!state.activeId);
            show("villagerDetail", !!state.activeId);
            if (state.detail) {
                text("villagerDetailTitle", model.displayName(state.detail, state.preferences.aliases));
                const names = model.matchingRegions(state.detail, state.preferences.regions).map(region => region.name).join(", ");
                text("villagerDetailRegion", names);
                show("villagerDetailRegion", !!names);
            }
            show("villagerMapPanel", state.mapOpen);
            show("villagerRegionsPanel", state.regionsOpen);
            el("villagerMapToggle")?.setAttribute("aria-expanded", String(!!state.mapOpen));
            el("villagerRegionsToggle")?.setAttribute("aria-expanded", String(!!state.regionsOpen));
            renderMap(state, info);
            renderRegions(state, info);
            // The previous call disables all form controls; the save button also needs a real draft.
            disable("villagerRegionSave", state.preferencesBusy || state.readOnly || state.busy || state.scanning || !state.regionDirty);
            diagnosticState = state;
            const diagnosticRows = state.diagnostics || [];
            show("villagerDiagnostics", diagnosticRows.length > 0);
            text("villagerDiagnosticsSummary", t("Scan-Diagnose ({count})", { count: state.diagnosticCount || diagnosticRows.length }));
            show("villagerDiagnosticsTruncated", state.diagnosticsTruncated);
            renderDiagnostics();
            if (state.preview) {
                disable("villagerSave", state.busy || !state.preview.change_count || !!state.staleReason || !!state.blockedReason);
                text("villagerSave", t("{count} Änderungen vormerken", { count: state.preview.change_count || 0 }));
                notice("villagerPreviewNotice", state.staleReason || state.blockedReason || state.previewNotice || "", state.previewNoticeKind || "warning");
                disable("villagerPreviewClose", state.saving);
                disable("villagerPreviewCancel", state.saving);
            }
            return page;
        }
        function renderDetail(row, state, { loading = false, error = "" } = {}) {
            const box = el("villagerDetail");
            if (!box) return;
            if (!row) { box.innerHTML = ""; delete box.dataset.villagerId; return; }
            const same = box.dataset.villagerId === row.id;
            const opened = same ? [...box.querySelectorAll("details[id][open]")].map(node => node.id) : [];
            const scroll = same ? box.scrollTop : 0;
            box.dataset.villagerId = row.id;
            const name = model.displayName(row, state.preferences.aliases);
            const aliasKey = model.aliasKey(row);
            let content = `<div class="villager-detail-header"><div><h3 id="villagerDetailTitle" tabindex="-1">${esc(name)}</h3><p class="villager-detail-subtitle">${esc(t(row.profession?.label || "Unbekannt"))} · ${esc(t(row.trade_tier_label || "—"))}${row.is_baby === true ? ` · ${esc(t("Kind"))}` : ""}</p></div><button type="button" class="btn-text" data-action="close-detail" aria-label="${esc(t("Details schließen"))}">✕</button></div>`;
            if (loading || error) {
                box.innerHTML = content + `<p role="status" class="hint-text">${esc(error || t("Details werden geladen …"))}</p>`;
                return;
            }
            const region = model.matchingRegions(row, state.preferences.regions).map(item => item.name).join(", ");
            content += `<div class="villager-detail-location"><span id="villagerDetailRegion"${region ? "" : " hidden"}>${esc(region)}</span><span id="villagerDetailPosition">${esc(model.dimensionLabel(row.dimension))} · ${esc(model.positionText(row))}</span><button type="button" class="btn-text" data-action="copy-position"${!model.hasPosition(row) ? " disabled" : ""}>${esc(t("Koordinaten kopieren"))}</button></div>`;
            if (chunkAssignmentMissing(row)) content += `<p id="villagerIntegrityNotice" class="villager-notice warning"><strong>${esc(t("Chunk-Zuordnung fehlt"))}</strong><br>${esc(t("Die Bewohnerdaten sind lesbar, aber keinem gespeicherten Chunk zugeordnet. Name, Gesundheit und Vorräte bleiben schreibgeschützt."))}</p>`;
            content += `<form id="villagerNameForm" class="villager-name-form">
                <div class="villager-detail-section-heading"><label for="villagerName">${esc(t("Name in Minecraft"))}</label><span id="villagerNameDirty" class="villager-draft-status" hidden>${esc(t("Ungespeichert"))}</span></div>
                <input id="villagerName" value="${esc(row.name || "")}" placeholder="${esc(t("Ohne Namen"))}" autocomplete="off"${!row.name_editable ? " disabled" : ""}>
                ${!row.name_editable && !chunkAssignmentMissing(row) ? `<p class="villager-field-note">${esc(row.name_reason || t("Dieser Datensatz kann nur gelesen werden."))}</p>` : ""}
                <div class="villager-detail-form-actions"><button type="submit" id="villagerNamePreview" class="btn btn-primary btn-sm">${esc(t("Namen prüfen"))}</button><button type="button" id="villagerNameRemove" class="btn-text">${esc(t("Name entfernen"))}</button><button type="button" id="villagerNameReset" class="btn-text" hidden>${esc(t("Verwerfen"))}</button></div>
                </form>`;
            content += `<div class="villager-detail-section-heading"><h4>${esc(t("Gesundheit"))} · ${esc(model.healthText(row.health))}</h4><span id="villagerDetailDirty" class="villager-draft-status" hidden>${esc(t("Ungespeichert"))}</span></div>`;
            if (!row.editable && !chunkAssignmentMissing(row)) content += `<p class="villager-field-note">${esc(row.health?.reason || row.issues?.[0]?.message || t("Dieser Datensatz kann nur gelesen werden."))}</p>`;
            else if (row.editable && row.health?.max_editable === false) content += `<p class="villager-field-note">${esc(row.health.max_reason || t("Das Maximum dieses Datensatzes bleibt geschützt; aktuelle Gesundheit kann bearbeitet werden."))}</p>`;
            // Keep an existing sub-one health value valid for native form
            // submission. Unchanged fields are omitted from the patch, while
            // the shared validator still requires at least 1 for new values.
            const minimum = value => Number.isFinite(value) && value > 0 && value < 1 ? value : 1;
            content += `<form id="villagerDetailHealthForm"><fieldset id="villagerDetailFields" class="villager-health-fields"${!row.editable || state.staleReason || state.blockedReason ? " disabled" : ""}>
                <legend class="visually-hidden">${esc(t("Gesundheit bearbeiten"))}</legend>
                <label>${esc(t("Aktuelle Lebenspunkte"))}<input id="villagerDetailCurrent" type="number" min="${minimum(row.health?.current)}" max="2048" step="any" value="${esc(row.health?.current ?? "")}"></label>
                <label>${esc(t("Maximale Lebenspunkte"))}<input id="villagerDetailMax" type="number" min="${minimum(row.health?.max)}" max="2048" step="any" value="${esc(row.health?.max ?? "")}"></label>
                <label class="villager-check"><input id="villagerDetailHeal" type="checkbox">${esc(t("Vollständig heilen"))}</label>
                </fieldset>
                <div class="villager-detail-form-actions"><button type="submit" id="villagerDetailPreview" class="btn btn-primary btn-sm">${esc(t("Änderung prüfen"))}</button><button type="button" id="villagerDetailReset" class="btn-text" hidden>${esc(t("Verwerfen"))}</button></div>
                </form>
                <button type="button" id="villagerDetailHealAction" class="btn-text"${!row.editable || !model.isInjured(row) ? " disabled" : ""}>${esc(t("Heilen und prüfen"))}</button>
                <details id="villagerAliasDetails" class="villager-disclosure"><summary><span id="villagerDetailAliasSummary">${esc(t("Weitere Einstellungen"))}</span><span id="villagerAliasDraftMark" class="villager-draft-dot" hidden>•</span></summary>
                <p class="hint-text">${esc(t("Nur im Editor sichtbar. Der Minecraft-Name bleibt erhalten."))}</p>
                ${aliasKey ? "" : `<p class="villager-field-note">${esc(t("Für diesen Dorfbewohner ist keine eindeutige, dauerhafte Kennung verfügbar. Ein Editor-Alias kann deshalb nicht sicher gespeichert werden."))}</p>`}
                <form id="villagerAliasForm" class="villager-alias-form"><label for="villagerAlias">${esc(t("Editor-Alias"))}</label><input id="villagerAlias" maxlength="80" value="${esc(aliasKey ? state.preferences.aliases[aliasKey] || "" : "")}" placeholder="${esc(t("Optionaler Editor-Alias"))}"${state.readOnly || !aliasKey ? " disabled" : ""}><button type="submit" id="villagerAliasSave" class="btn btn-secondary btn-sm">${esc(t("Speichern"))}</button><span id="villagerAliasDirty" class="villager-draft-status" hidden>${esc(t("Ungespeichert"))}</span></form></details>`;
            const trades = row.trades || {};
            content += window.MCBEVillagerInventory.editorHtml(row.inventory);
            content += `<details id="villagerTradesDetails" class="villager-disclosure"><summary>${esc(t("Handelsangebote ({count})", { count: trades.total ?? row.trade_count ?? 0 }))}</summary><ol class="villager-trades">${(trades.offers || []).map(offer => `<li><strong>${esc(itemText(offer.buy_a))}${offer.buy_b ? ` + ${esc(itemText(offer.buy_b))}` : ""} → ${esc(itemText(offer.sell))}</strong><small>${esc(t("Nutzungen: {used} / {max}", { used: offer.uses ?? "—", max: offer.max_uses ?? "—" }))}${offer.tier !== null && offer.tier !== undefined ? ` · ${esc(t("Stufe {tier}", { tier: offer.tier + 1 }))}` : ""}</small></li>`).join("") || `<li>${esc(t("Keine lesbaren Handelsangebote gespeichert."))}</li>`}</ol>${trades.truncated ? `<p class="hint-text">${esc(t("Anzeige begrenzt; alle Originaldaten bleiben erhalten."))}</p>` : ""}</details>`;
            const equipment = row.equipment || {};
            content += equipmentHtml(equipment);
            const facts = [
                [t("Eindeutige ID"), row.unique_id || t("Unbekannt")],
                [t("Kennung"), row.identifier || "—"], [t("Handelserfahrung"), row.trade_experience ?? "—"],
                [t("Alter"), row.is_baby === true ? t("Kind") : row.is_baby === false ? t("Erwachsen") : t("Unbekannt")],
                [t("Minecraft-Dorf"), row.village?.label || row.village?.name || row.village?.id || t("Nicht eindeutig zugeordnet")],
                [t("Speicherformat"), row.storage === "legacy" ? t("Älteres Chunk-Format") : t("Actor-Datensatz")],
            ];
            content += `<details id="villagerTechnicalDetails" class="villager-disclosure"><summary>${esc(t("Technische Details"))}</summary><dl>${facts.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`).join("")}</dl>${row.village_reason ? `<p class="hint-text">${esc(row.village_reason)}</p>` : ""}
                <details id="villagerNbtDetails" class="villager-disclosure"><summary>${esc(t("Rohdaten (NBT)"))}</summary><div id="villagerNbtData" class="villager-nbt"></div></details>
                ${row.issues?.length ? `<ul class="villager-diagnostics">${row.issues.map(issue => `<li>${esc(issue.message || issue.code)}</li>`).join("")}</ul>` : ""}</details>`;
            box.innerHTML = content;
            const nbtDetails = el("villagerNbtDetails");
            let nbtRendered = false;
            nbtDetails?.addEventListener("toggle", () => {
                if (nbtDetails.open && !nbtRendered) {
                    el("villagerNbtData").innerHTML = row.nbt ? nbtTree(row.nbt) : esc(t("Keine Rohdaten verfügbar."));
                    nbtRendered = true;
                }
            });
            for (const id of opened) if (el(id)) el(id).open = true;
            box.scrollTop = scroll;
        }
        function renderPreview(preview, state) {
            text("villagerPreviewWorld", state.worldLabel || state.worldPath);
            text("villagerPreviewSummary", t("{changed} Änderungen · {unchanged} unverändert · {skipped} übersprungen", { changed: preview.change_count || 0, unchanged: preview.unchanged_count || 0, skipped: preview.skipped_count || 0 }));
            const labels = { changed: t("Wird geändert"), unchanged: t("Unverändert"), skipped: t("Übersprungen") };
            const rows = collection(state).byId;
            html("villagerPreviewRows", (preview.rows || []).map(row => {
                const inventory = row.kind === "inventory";
                const before = row.kind === "name" ? esc(row.before?.name || t("Ohne Namen")) : inventory ? window.MCBEVillagerInventory.snapshotHtml(row.before, state.detail?.inventory) : esc(model.healthText(row.before));
                const after = row.kind === "name" ? esc(row.after?.name || t("Ohne Namen")) : inventory ? window.MCBEVillagerInventory.snapshotHtml(row.after, state.detail?.inventory) : esc(model.healthText(row.after));
                return `<tr><td>${esc(rows.has(row.id) ? model.displayName(rows.get(row.id), state.preferences.aliases) : row.label || row.name || row.id)}${row.kind === "name" ? `<small>${esc(t("Name in Minecraft"))}</small>` : inventory ? `<small>${esc(t("Vorräte"))}</small>` : ""}</td><td${inventory || row.kind === "name" ? "" : ' class="villager-health"'}>${before}</td><td${inventory || row.kind === "name" ? "" : ' class="villager-health"'}>${after}</td><td class="villager-outcome-${esc(row.status)}">${esc(labels[row.status] || row.status)}${row.reason ? `<small>${esc(row.reason)}</small>` : ""}</td></tr>`;
            }).join(""));
            notice("villagerPreviewNotice", state.previewNotice || "");
        }
        return { render, renderDetail, renderPreview, notice, element: el, focusMapPlayer: () => mapView?.focusPlayer() };
    }

    window.MCBEVillagerView = { createVillagerView, nbtTree, itemText };
}());
