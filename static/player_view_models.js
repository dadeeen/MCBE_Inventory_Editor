(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function playerByKey(players = [], key) {
        return players.find(player => player.player_key === key) || null;
    }

    function editablePlayers(players = []) {
        return players.filter(player => player.editable);
    }

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

    function playerToolOptionModels(players = [], { currentPlayerKey = "", previousValue = "" } = {}) {
        const editable = editablePlayers(players);
        const firstOther = editable.find(player => player.player_key !== currentPlayerKey) || editable[0] || null;
        const selectedValue = previousValue && editable.some(player => player.player_key === previousValue)
            ? previousValue
            : (firstOther?.player_key || "");
        return {
            disabled: editable.length === 0,
            selectedValue,
            options: editable.map(player => ({
                value: player.player_key,
                label: player.player_key === currentPlayerKey ? t("{label} (aktuell)", { label: player.label }) : player.label,
                isCurrent: player.player_key === currentPlayerKey,
            })),
        };
    }

    function playerToolOptionsHtml(model = {}, { disableCurrent = false } = {}) {
        if (model.disabled) return `<option value="">${t("Keine bearbeitbaren Spieler")}</option>`;
        return (model.options || []).map(option => {
            const disabled = disableCurrent && option.isCurrent ? " disabled" : "";
            return `<option value="${escapeAttr(option.value || "")}"${disabled}>${escapeHtml(option.label || "")}</option>`;
        }).join("");
    }

    function copyFromPlayerRequestModel({
        currentPlayerKey = "",
        sourcePlayerKey = "",
        useInventory = false,
        useEnder = false,
        useStats = false,
        sourceLabel = "",
        targetLabel = "",
    } = {}) {
        if (!currentPlayerKey) {
            return { valid: false, message: t("Lade zuerst den Zielspieler."), confirmationText: "" };
        }
        if (!sourcePlayerKey || sourcePlayerKey === currentPlayerKey) {
            return { valid: false, message: t("Wähle einen anderen Quellspieler."), confirmationText: "" };
        }
        if (!useInventory && !useEnder && !useStats) {
            return { valid: false, message: t("Wähle mindestens einen Bereich."), confirmationText: "" };
        }
        const source = sourceLabel || t("Quellspieler");
        return {
            valid: true,
            message: "",
            confirmationText: t("Daten von {source} in {target} übernehmen? Die Änderung bleibt bis zum Speichern nur lokal und kann per Undo rückgängig gemacht werden.", { source, target: targetLabel }),
        };
    }

    function snapshotSummaryForComparison(data = {}, itemIsVisiblePresent, itemHasRepairableDamage = null) {
        const inv = data.inventory || {};
        const ec = data.ender_chest || {};
        const stats = data.stats || {};
        const invItems = Object.values(inv).filter(itemIsVisiblePresent);
        const ecItems = Object.values(ec).filter(itemIsVisiblePresent);
        const repairableDamage = typeof itemHasRepairableDamage === "function"
            ? itemHasRepairableDamage
            : item => Number(item.damage || 0) > 0;
        const damaged = invItems.concat(ecItems).filter(repairableDamage).length;
        return {
            inv: invItems.length,
            ec: ecItems.length,
            damaged,
            xp: stats.xp_level ?? "?",
            health: stats.health ?? "?",
            food: stats.food_level ?? "?",
        };
    }

    function playerRowModel(player = {}, currentPlayerKey = "") {
        const canSelect = player.editable || player.exportable || player.reason;
        const kindLabel = player.kind === "local"
            ? t("Lokal")
            : player.kind === "remote"
                ? t("Multiplayer")
                : t("Unbekannt");
        let badgeText;
        let badgeTitle;
        if (player.editable) {
            badgeText = player.inventory_create_requires_confirmation ? t("Ohne Inventory") : t("Bearbeitbar");
            badgeTitle = player.inventory_create_requires_confirmation ? player.reason : "";
        } else if (player.reason && player.reason.toLowerCase().includes("corrupt")) {
            badgeText = t("Fehlerhaft");
            badgeTitle = t("{kind} · Konfidenz: {confidence} · Grund: {reason}", { kind: player.kind, confidence: player.confidence, reason: player.reason });
        } else if (player.exportable) {
            badgeText = t("Nur Export");
            badgeTitle = t("{kind} · Konfidenz: {confidence} · Grund: {reason}", { kind: player.kind, confidence: player.confidence, reason: player.reason });
        } else {
            badgeText = t("Schreibgeschützt");
            badgeTitle = t("{kind} · Konfidenz: {confidence} · Grund: {reason}", { kind: player.kind, confidence: player.confidence, reason: player.reason });
        }
        const actionMeta = player.editable
            ? (player.inventory_create_requires_confirmation ? t("Bearbeitbar · kein Inventory-Tag, Erzeugung nur nach Bestätigung") : t("Klick zum Bearbeiten"))
            : player.exportable
                ? t("Nur Export · {reason}", { reason: player.reason || t("nicht bearbeitbar") })
                : t("Nicht bearbeitbar · {reason}", { reason: player.reason || t("unbekannter Grund") });
        return {
            active: player.player_key === currentPlayerKey,
            badgeClass: player.editable ? "player-badge" : "player-badge readonly",
            badgeText,
            badgeTitle,
            canSelect,
            meta: `${kindLabel} · ${actionMeta}`,
            name: player.label || "",
        };
    }

    function playerRowHtml(model = {}) {
        const title = model.badgeTitle ? ` title="${escapeAttr(model.badgeTitle)}"` : "";
        return `
            <span class="player-name">${escapeHtml(model.name || "")}</span>
            <span class="${escapeAttr(model.badgeClass || "player-badge")}"${title}>${escapeHtml(model.badgeText || "")}</span>
            <span class="player-meta">${escapeHtml(model.meta || "")}</span>
        `;
    }

    function playerRowElement(model = {}, doc = document) {
        const row = doc.createElement("button");
        row.type = "button";
        row.className = "player-row";
        if (model.active) row.classList.add("active");
        if (!model.canSelect) row.disabled = true;
        row.innerHTML = playerRowHtml(model);
        return row;
    }

    const PLAYER_LIST_STATUS_TEXT = {
        empty: () => t("Keine Spieler-Datensätze erkannt."),
        loading: () => t("Suche Spieler..."),
        loadError: () => t("Spieler konnten nicht geladen werden."),
        connectionError: () => t("Verbindungsfehler beim Laden der Spieler."),
    };

    function playerListStatusHtml(status = "empty") {
        const level = status === "loadError" || status === "connectionError" ? " error" : "";
        const text = (PLAYER_LIST_STATUS_TEXT[status] || PLAYER_LIST_STATUS_TEXT.empty)();
        return `<div class="no-backups${level}">${escapeHtml(text)}</div>`;
    }

    window.MCBEPlayerViewModels = {
        copyFromPlayerRequestModel,
        editablePlayers,
        playerByKey,
        playerListStatusHtml,
        playerRowElement,
        playerRowHtml,
        playerRowModel,
        playerToolOptionModels,
        playerToolOptionsHtml,
        snapshotSummaryForComparison,
    };
}());
