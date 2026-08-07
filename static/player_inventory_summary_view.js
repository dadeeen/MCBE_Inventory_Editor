(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function playerInventorySummaryModel({ worldPath = "", currentPlayer = null, playerLabel = "", summary = null } = {}) {
        if (!worldPath || !currentPlayer || !summary) {
            return {
                visible: false,
                summary: null,
                playerName: "",
                inventoryText: "",
                enderText: "",
                damagedText: "",
                enderMetaText: "",
            };
        }
        return {
            visible: true,
            summary,
            playerName: playerLabel,
            inventoryText: t("Inventar {used}/{total}", { used: summary.inventoryUsed, total: summary.inventoryTotal }),
            enderText: t("Enderchest {used}/{total}", { used: summary.enderUsed, total: summary.enderTotal }),
            damagedText: t("{count} beschädigt", { count: summary.damaged }),
            enderMetaText: t("{used} / {total} belegt", { used: summary.enderUsed, total: summary.enderTotal }),
        };
    }

    function applyPlayerInventorySummaryModel(elements = {}, model = {}) {
        const {
            container = null,
            playerName = null,
            inventoryBadge = null,
            enderBadge = null,
            damagedBadge = null,
            enderMeta = null,
        } = elements;
        if (container) container.style.display = model.visible ? "flex" : "none";
        if (!model.visible) return false;
        if (playerName) playerName.textContent = model.playerName || "";
        if (inventoryBadge) inventoryBadge.textContent = model.inventoryText || "";
        if (enderBadge) enderBadge.textContent = model.enderText || "";
        if (damagedBadge) damagedBadge.textContent = model.damagedText || "";
        if (enderMeta) enderMeta.textContent = model.enderMetaText || "";
        return true;
    }


    function createPlayerInventorySummaryController({
        elements = {},
        getWorldPath = () => "",
        getCurrentPlayer = () => null,
        getPlayerLabel = () => "",
        buildSummary = () => null,
        setLastSummary = () => {},
    } = {}) {
        function render() {
            const worldPath = getWorldPath?.() || "";
            const currentPlayer = getCurrentPlayer?.() || null;
            const summary = worldPath && currentPlayer ? buildSummary?.() : null;
            const model = playerInventorySummaryModel({
                worldPath,
                currentPlayer,
                playerLabel: summary ? getPlayerLabel?.() : "",
                summary,
            });
            applyPlayerInventorySummaryModel(elements, model);
            setLastSummary(model.visible ? model.summary : null);
            return model;
        }

        return { render };
    }

    function collectPlayerInventorySummaryElements(doc = document) {
        return {
            container: doc.getElementById("playerInventorySummary"),
            playerName: doc.getElementById("playerSummaryName"),
            inventoryBadge: doc.getElementById("summaryBadgeInventory"),
            enderBadge: doc.getElementById("summaryBadgeEnder"),
            damagedBadge: doc.getElementById("summaryBadgeDamaged"),
            enderMeta: doc.getElementById("enderChestMeta"),
        };
    }

    function createInventoryPlayerInventorySummaryController({ doc = document, ...deps } = {}) {
        return createPlayerInventorySummaryController({
            ...deps,
            elements: collectPlayerInventorySummaryElements(doc),
        });
    }

    window.MCBEPlayerInventorySummaryView = {
        applyPlayerInventorySummaryModel,
        collectPlayerInventorySummaryElements,
        createInventoryPlayerInventorySummaryController,
        createPlayerInventorySummaryController,
        playerInventorySummaryModel,
    };
}());
