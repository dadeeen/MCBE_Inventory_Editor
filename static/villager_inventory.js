(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => params && k in params ? String(params[k]) : m));
    const esc = value => window.MCBEHtmlUtils.escapeHtml(value);
    const itemName = (inventory, item) => (inventory.allowed_items || []).find(option => option.name === item?.name)?.label || item?.name || t("Unbekannt");
    const itemText = (inventory, item) => item ? `${item.count ?? "?"} × ${itemName(inventory, item)}` : t("Leer");

    function slotDiffers(slot, draft) {
        if (!slot.editable || !draft) return false;
        return draft.invalid || draft.name !== (slot.item?.name || "")
            || (!!draft.name && Number(draft.count) !== slot.item?.count);
    }

    function changes(inventory, drafts) {
        if (!inventory?.editable) throw new Error(inventory?.reason || t("Dieses Vorratsinventar kann nur gelesen werden."));
        const result = [];
        for (const slot of inventory.slots || []) {
            const draft = drafts[slot.slot];
            if (!slotDiffers(slot, draft)) continue;
            if (!draft.name) { result.push({ slot: slot.slot, item: null }); continue; }
            const allowed = (inventory.allowed_items || []).find(item => item.name === draft.name);
            const count = Number(draft.count), max = allowed?.max_count || 64;
            if (!allowed || draft.invalid || !String(draft.count).trim() || !Number.isInteger(count) || count < 1 || count > max) {
                throw new Error(t("Platz {slot}: Wähle einen Vorrat und eine ganze Anzahl zwischen 1 und {max}.", { slot: slot.slot + 1, max }));
            }
            result.push({ slot: slot.slot, item: { name: draft.name, count } });
        }
        if (!result.length) throw new Error(t("Es wurde keine Vorratsänderung angegeben."));
        return result;
    }

    function editorHtml(inventory = {}) {
        const slots = inventory.slots || [], occupied = slots.filter(slot => slot.item).length;
        const reason = inventory.reason || (!inventory.present ? t("Kein unterstütztes Vorratsinventar gespeichert.") : "");
        return `<details id="villagerInventoryDetails" class="villager-disclosure"><summary>${esc(t("Vorräte ({count}/{capacity})", { count: occupied, capacity: inventory.capacity || 8 }))}<span id="villagerInventoryDraftMark" class="villager-draft-dot" hidden>•</span></summary>
            ${reason ? `<p class="villager-field-note">${esc(reason)}</p>` : ""}
            ${inventory.present ? `<form id="villagerInventoryForm"><fieldset id="villagerInventoryFields" class="villager-stock-fields"${!inventory.editable ? " disabled" : ""}>
                <legend class="visually-hidden">${esc(t("Vorräte bearbeiten"))}</legend>
                ${slots.map(slot => {
                    const title = t("Platz {slot}", { slot: slot.slot + 1 });
                    if (!slot.editable) return `<div class="villager-stock-protected"><strong>${esc(title)} · ${esc(itemText(inventory, slot.item))}</strong><small>${esc(slot.reason || t("Geschützter Inhalt bleibt unverändert."))}</small></div>`;
                    return `<div class="villager-stock-row"><span aria-hidden="true">${slot.slot + 1}</span>
                        <label class="visually-hidden" for="villagerStockItem${slot.slot}">${esc(t("{slot}: Gegenstand", { slot: title }))}</label>
                        <select id="villagerStockItem${slot.slot}" data-stock-slot="${slot.slot}"><option value="">${esc(t("Leer"))}</option>${(inventory.allowed_items || []).map(item => `<option value="${esc(item.name)}"${slot.item?.name === item.name ? " selected" : ""}>${esc(item.label || item.name)}</option>`).join("")}</select>
                        <label class="visually-hidden" for="villagerStockCount${slot.slot}">${esc(t("{slot}: Anzahl", { slot: title }))}</label>
                        <input id="villagerStockCount${slot.slot}" data-stock-slot="${slot.slot}" type="number" min="1" max="64" step="1" value="${esc(slot.item?.count || 0)}"${slot.item ? "" : " disabled"}>
                    </div>`;
                }).join("")}</fieldset>
                ${inventory.editable ? `<div class="villager-detail-form-actions"><button type="submit" id="villagerInventoryPreview" class="btn btn-primary btn-sm">${esc(t("Vorräte prüfen"))}</button><button type="button" id="villagerInventoryReset" class="btn-text" hidden>${esc(t("Verwerfen"))}</button></div><span id="villagerInventoryDirty" class="villager-draft-status" hidden>${esc(t("Ungespeichert"))}</span>` : ""}
            </form>` : ""}</details>`;
    }

    function snapshotHtml(snapshot, inventory = {}) {
        return `<ul class="villager-stock-preview">${(snapshot?.slots || []).map(slot => `<li>${esc(t("Platz {slot}", { slot: slot.slot + 1 }))}: ${esc(itemText(inventory, slot.item))}</li>`).join("")}</ul>`;
    }

    window.MCBEVillagerInventory = { changes, slotDiffers, editorHtml, snapshotHtml };
}());
