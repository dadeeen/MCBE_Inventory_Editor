(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function slotTechLabel(slotId, containerName) {
        return containerName === "ender_chest" ? `EnderChestInventory[${slotId}]` : `Inventory Slot ${slotId}`;
    }

    function slotAreaLabel(slotId, containerName) {
        const target = Number(slotId);
        return containerName === "ender_chest" ? t("Enderchest {slot}", { slot: target }) : `Inventory Slot ${target}`;
    }

    function slotOriginLabel(slotId, containerName) {
        return t("Zielslot: {label}", { label: slotAreaLabel(slotId, containerName) });
    }

    function escapeHtml(value) {
        if (window.MCBEHtmlUtils?.escapeHtml) return window.MCBEHtmlUtils.escapeHtml(value);
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function protectedSlotInspectorText(slotId, containerName, context = {}) {
        const label = context.slotLabel || slotAreaLabel(slotId, containerName);
        const tech = slotTechLabel(slotId, containerName);
        const lines = [
            t("Slot-Schutzdetails"),
            t("Bereich: {label}", { label }),
            t("Technisch: {tech}", { tech }),
            t("Grund: Der Datensatz enthält einen nicht darstellbaren oder future/opaque NBT-Eintrag in einem bekannten Slot."),
            t("Entscheidung: Der Editor zeigt den Slot read-only und überschreibt ihn nicht."),
            t("Auswirkung: Beim Speichern bleiben diese Rohdaten im Original-NBT erhalten; sichtbare andere Slots können trotzdem bearbeitet werden."),
            t("Was du tun kannst: Slot unverändert lassen, Item ingame entfernen oder Diagnose kopieren, falls du erwartest, dass der Slot normal editierbar sein sollte."),
        ];
        if (context.hasPlayer) lines.push(t("Spieler: {label}", { label: context.playerLabel || "" }));
        if (context.worldPath) lines.push(t("Weltpfad: {path}", { path: context.worldPath }));
        return lines.join("\n");
    }

    function itemProtectedNbtDetails(item, { visible = true } = {}) {
        if (!visible) return [];
        const details = [];
        if (Array.isArray(item?.protected_nbt_summary) && item.protected_nbt_summary.length) {
            item.protected_nbt_summary.forEach(entry => details.push(String(entry)));
        } else if (item?.has_protected_nbt === true) {
            details.push(t("Zusatz-NBT vorhanden, Kategorien in diesem Datensatz nicht genauer aufgeschlüsselt."));
        }
        if (Array.isArray(item?.preserved_nbt_summary) && item.preserved_nbt_summary.length) {
            item.preserved_nbt_summary.forEach(entry => details.push(String(entry)));
        } else if (item?.has_preserved_nbt === true && item.has_protected_nbt !== true) {
            details.push(t("Bekannte Zusatz-NBT vorhanden, wird bei gleicher Item-ID erhalten."));
        }
        if (item?.has_unknown_enchantments === true) details.push(t("Unbekannte/future Verzauberungen werden erhalten."));
        if (item?.protected_nbt_dropped === true) details.push(t("Beim Itemtyp-Wechsel wird Zusatz-NBT vom vorherigen Item nicht übernommen."));
        return details;
    }

    function itemNbtViewText(item) {
        if (!item || !item.nbt_view) return "";
        try {
            return JSON.stringify(item.nbt_view, null, 2);
        } catch (_e) {
            return "";
        }
    }

    function rawNbtSlotValue(item) {
        const rawSlot = item?.nbt_view?.value?.Slot?.value;
        const numericSlot = Number(rawSlot);
        return Number.isInteger(numericSlot) ? numericSlot : null;
    }

    function itemSlotOriginLines(slotId, containerName, item) {
        const target = Number(slotId);
        const lines = [slotOriginLabel(slotId, containerName)];
        if (Number.isInteger(item?.source_slot) && item.source_slot !== target) {
            lines.push(t("Originalquelle: {container} Slot {slot}", { container: containerName === "ender_chest" ? "EnderChestInventory" : "Inventory", slot: item.source_slot }));
        }
        const rawSlot = rawNbtSlotValue(item);
        if (rawSlot !== null && rawSlot !== target) {
            lines.push(t("Roh-NBT Slot-Feld: {slot}", { slot: rawSlot }));
        }
        return lines;
    }

    function itemHasInspectableNbt(item, { visible = true } = {}) {
        return itemProtectedNbtDetails(item, { visible }).length > 0 || Boolean(itemNbtViewText(item));
    }

    function itemSlotInspectorText(slotId, containerName, item, context = {}) {
        const label = context.slotLabel || slotAreaLabel(slotId, containerName);
        const tech = slotTechLabel(slotId, containerName);
        const details = itemProtectedNbtDetails(item, { visible: context.visible !== false });
        const lines = [
            t("Slot-Zusatzdaten"),
            t("Bereich: {label}", { label }),
            t("Technisch: {tech}", { tech }),
            ...itemSlotOriginLines(slotId, containerName, item),
            `Item: ${item?.name || "minecraft:air"}`,
            `Status: ${context.itemRequiresOriginalNbt ? t("Zusatz-NBT wird bei gleicher Item-ID erhalten") : t("Keine Zusatz-NBT gemeldet")}`,
        ];
        if (details.length) {
            lines.push(t("Kategorien:"));
            details.forEach(detail => lines.push(`- ${detail}`));
        }
        const rawNbt = itemNbtViewText(item);
        if (rawNbt) lines.push("", t("Experten-NBT:"), rawNbt);
        lines.push(t("Entscheidung: Der Editor bearbeitet nur sichtbare Felder; Zusatzdaten werden nicht frei editiert."));
        lines.push(t("Auswirkung: Beim Speichern bleiben diese Daten erhalten, solange die Item-ID zur sicheren Originalquelle passt."));
        if (context.hasPlayer) lines.push(t("Spieler: {label}", { label: context.playerLabel || "" }));
        if (context.worldPath) lines.push(t("Weltpfad: {path}", { path: context.worldPath }));
        return lines.join("\n");
    }

    function slotInspectorBodyHtml({
        label = "Slot",
        protectedKnown = false,
        slotId = 0,
        containerName = "inventory",
        item = null,
        inspectableDetails = [],
        nbtViewText = "",
        inspectorText = "",
    } = {}) {
        const rows = protectedKnown
            ? [
                ["Status", "Read-only"],
                [t("Grund"), t("Nicht darstellbarer/future NBT-Eintrag in bekanntem Slot")],
                [t("Entscheidung"), t("Nicht überschreiben, Rohdaten beim Speichern erhalten")],
                [t("Nächster sinnvoller Schritt"), t("Unverändert lassen oder Diagnose kopieren")],
            ]
            : [
                ["Status", t("Editierbar mit geschützten Zusatzdaten")],
                ["Item", item?.name || "minecraft:air"],
                [t("Technischer Zielslot"), slotTechLabel(slotId, containerName)],
                [t("NBT-Ursprung"), itemSlotOriginLines(slotId, containerName, item).join(" · ")],
                [t("Kategorien"), inspectableDetails.length ? t("{count} erkannt", { count: inspectableDetails.length }) : t("Keine Zusatzdaten gemeldet")],
                [t("Entscheidung"), t("Sichtbare Felder editieren, Zusatzdaten bei gleicher Item-ID erhalten")],
            ];
        const detailList = !protectedKnown && inspectableDetails.length
            ? `<ul class="slot-inspector-list">${inspectableDetails.map(detail => `<li>${escapeHtml(detail)}</li>`).join("")}</ul>`
            : "";
        const nbtViewHtml = !protectedKnown && nbtViewText
            ? `<details class="diagnostic-details slot-inspector-json" open>
                <summary>${t("Experten-NBT anzeigen")}</summary>
                <pre>${escapeHtml(nbtViewText)}</pre>
            </details>`
            : "";
        return `
            <div class="slot-inspector-callout ${protectedKnown ? "warning" : "info"}">
                <strong>${escapeHtml(protectedKnown ? t("{label} bleibt geschützt.", { label }) : t("{label} enthält Zusatzdaten.", { label }))}</strong>
                <p>${escapeHtml(protectedKnown ? t("Das ist kein UI-Fehler: Der Editor kann diesen Roh-NBT-Eintrag nicht verlustfrei als normales Item-Formular darstellen.") : t("Diese Daten werden lesbar angezeigt, aber nicht frei editiert. Der Zielslot und der Roh-NBT-Ursprung können nach Verschieben/Kopieren verschieden sein."))}</p>
            </div>
            ${detailList}
            ${nbtViewHtml}
            <div class="slot-inspector-table">
                ${rows.map(([k, v]) => `<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join("")}
            </div>
            <details class="diagnostic-details slot-inspector-raw">
                <summary>${t("Detail-Log anzeigen")}</summary>
                <pre>${escapeHtml(inspectorText)}</pre>
            </details>
        `;
    }

    function slotInspectorPanelModel({
        label = "Slot",
        protectedKnown = false,
        slotId = 0,
        containerName = "inventory",
        item = null,
        inspectableDetails = [],
        nbtViewText = "",
        inspectorText = "",
    } = {}) {
        return {
            visible: true,
            titleText: protectedKnown ? t("{label} ist read-only", { label }) : t("{label}: NBT-Details", { label }),
            bodyHtml: slotInspectorBodyHtml({
                label,
                protectedKnown,
                slotId,
                containerName,
                item,
                inspectableDetails,
                nbtViewText,
                inspectorText,
            }),
        };
    }

    function applySlotInspectorPanelModel(elements = {}, model = {}) {
        const {
            panel = null,
            title = null,
            body = null,
        } = elements;
        if (title) title.textContent = model.titleText || "";
        if (body) body.innerHTML = model.bodyHtml || "";
        if (panel) panel.style.display = model.visible === false ? "none" : "flex";
    }



    function createSlotInspectorController(deps = {}) {
        const {
            elements = {},
            getInventory = () => ({}),
            getEnderChestInventory = () => ({}),
            isProtectedKnownSlot = () => false,
            itemIsVisiblePresent = item => Boolean(item),
            itemRequiresOriginalNbt = () => false,
            slotDisplayName = (slotId, containerName) => `${containerName}:${slotId}`,
            currentPlayerLabel = () => t("Spieler"),
            getCurrentPlayerKey = () => "",
            getWorldPath = () => "",
            getActiveWorkflowView = () => "inventory",
            setWorkflowView = () => {},
            showToast = () => {},
            copyTextToClipboard = () => {},
        } = deps;
        const {
            panel,
            title,
            body,
            closeButton,
            copyButton,
        } = elements;
        let lastText = "";

        function sourceFor(containerName) {
            return containerName === "ender_chest" ? getEnderChestInventory() : getInventory();
        }

        function context(slotId, containerName) {
            return {
                slotLabel: slotDisplayName(Number(slotId), containerName),
                visible: true,
                itemRequiresOriginalNbt: false,
                hasPlayer: Boolean(getCurrentPlayerKey()),
                playerLabel: currentPlayerLabel(),
                worldPath: getWorldPath(),
            };
        }

        function protectedText(slotId, containerName) {
            return protectedSlotInspectorText(slotId, containerName, context(slotId, containerName));
        }

        function itemText(slotId, containerName, item) {
            return itemSlotInspectorText(slotId, containerName, item, {
                ...context(slotId, containerName),
                visible: itemIsVisiblePresent(item),
                itemRequiresOriginalNbt: itemRequiresOriginalNbt(item),
            });
        }

        function show(slotId, containerName, reason = "protected_known_slot") {
            const label = slotDisplayName(Number(slotId), containerName);
            const item = sourceFor(containerName)?.[slotId] || null;
            const protectedKnown = reason === "protected_known_slot" || isProtectedKnownSlot(slotId, containerName);
            const inspectableDetails = itemProtectedNbtDetails(item, { visible: itemIsVisiblePresent(item) });
            lastText = protectedKnown ? protectedText(slotId, containerName) : itemText(slotId, containerName, item);
            const model = slotInspectorPanelModel({
                label,
                protectedKnown,
                slotId,
                containerName,
                item,
                inspectableDetails,
                nbtViewText: !protectedKnown ? itemNbtViewText(item) : "",
                inspectorText: lastText,
            });
            applySlotInspectorPanelModel({ panel, title, body }, model);
            if (panel) {
                if (getActiveWorkflowView() !== "inventory") setWorkflowView("inventory", { scroll: false });
                setTimeout(() => panel?.scrollIntoView?.({ behavior: "smooth", block: "center" }), 0);
            }
        }

        function hide() {
            applySlotInspectorPanelModel({ panel }, { visible: false });
        }

        function showProtectedMessage(slotId, containerName) {
            showToast(containerName === "ender_chest"
                ? t("Enderchest-Slot {slot} ist read-only. Öffne die Slot-Details für weitere Informationen.", { slot: slotId })
                : t("Inventar-Slot {slot} ist read-only. Öffne die Slot-Details für weitere Informationen.", { slot: slotId }), "warning", 4500);
            show(slotId, containerName, "protected_known_slot");
        }

        function wire() {
            closeButton?.addEventListener("click", hide);
            copyButton?.addEventListener("click", () => {
                if (!lastText) {
                    showToast(t("Noch keine Slot-Details vorhanden."), "warning", 2500);
                    return;
                }
                copyTextToClipboard(lastText, t("Slot-Schutzdetails kopiert."));
            });
        }

        return {
            hide,
            itemHasInspectableNbt: item => itemHasInspectableNbt(item, { visible: itemIsVisiblePresent(item) }),
            itemNbtViewText,
            itemProtectedNbtDetails: item => itemProtectedNbtDetails(item, { visible: itemIsVisiblePresent(item) }),
            itemSlotInspectorText: itemText,
            itemSlotOriginLines,
            protectedSlotInspectorText: protectedText,
            rawNbtSlotValue,
            show,
            showProtectedMessage,
            wire,
        };
    }

    function collectSlotInspectorElements(doc = document) {
        return {
            panel: doc.getElementById("slotInspectorPanel"),
            title: doc.getElementById("slotInspectorTitle"),
            body: doc.getElementById("slotInspectorBody"),
            closeButton: doc.getElementById("btnCloseSlotInspector"),
            copyButton: doc.getElementById("btnCopySlotInspector"),
        };
    }

    function createInventorySlotInspectorController({ doc = document, ...deps } = {}) {
        return createSlotInspectorController({
            ...deps,
            elements: collectSlotInspectorElements(doc),
        });
    }

    window.MCBENbtInspector = {
        applySlotInspectorPanelModel,
        collectSlotInspectorElements,
        createInventorySlotInspectorController,
        protectedSlotInspectorText,
        itemProtectedNbtDetails,
        itemNbtViewText,
        rawNbtSlotValue,
        itemSlotOriginLines,
        itemHasInspectableNbt,
        itemSlotInspectorText,
        slotInspectorBodyHtml,
        slotInspectorPanelModel,
        createSlotInspectorController,
    };
}());
