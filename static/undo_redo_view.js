(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function undoRedoButtonModels({ undoLabels = [], redoLabels = [], undoCount = 0, redoCount = 0 } = {}) {
        return {
            undo: {
                disabled: undoCount === 0,
                text: "↩",
                count: undoCount,
                title: undoCount ? t("Rückgängig: {label}", { label: undoLabels[undoLabels.length - 1] || t("letzte Änderung") }) : t("Rückgängig (Ctrl+Z)"),
            },
            redo: {
                disabled: redoCount === 0,
                text: "↪",
                count: redoCount,
                title: redoCount ? t("Wiederholen: {label}", { label: redoLabels[redoLabels.length - 1] || t("letzte Änderung") }) : t("Wiederholen (Ctrl+Y)"),
            },
        };
    }

    function applyUndoRedoButtonModels(elements = {}, model = {}) {
        const pairs = [
            [elements.undoButton, model.undo],
            [elements.redoButton, model.redo],
            [elements.historyUndoButton, model.undo],
            [elements.historyRedoButton, model.redo],
        ];
        for (const [button, state] of pairs) {
            if (!button || !state) continue;
            const count = Math.max(0, Math.trunc(Number(state.count) || 0));
            const countLabel = t("Verfügbare Schritte: {count}", { count });
            const title = count ? `${state.title} · ${countLabel}` : state.title;
            button.dataset.historyCount = count ? (count > 99 ? "99+" : String(count)) : "";
            const apply = window.MCBEWriteStatusView?.applyIntrinsicEditControlState;
            if (apply) {
                apply(button, { ...state, title });
            } else {
                button.disabled = Boolean(state.disabled || state.blocked);
                button.title = state.blockedTitle || title || "";
            }
            button.setAttribute("aria-label", button.title || title || "");
            const historyButton = button === elements.historyUndoButton || button === elements.historyRedoButton;
            const label = button === elements.historyUndoButton ? t("Rückgängig") : t("Wiederholen");
            button.textContent = historyButton ? `${state.text} ${label}${count ? ` (${count})` : ""}` : state.text || "";
        }
    }

    function undoRedoPanelHtml({ undoLabels = [], redoLabels = [], undoCount = 0, redoCount = 0 } = {}) {
        const rows = [];
        if (undoCount) rows.push([t("Als Nächstes rückgängig:"), undoLabels.at(-1)]);
        if (redoCount) rows.push([t("Als Nächstes wiederholen:"), redoLabels.at(-1)]);
        return rows.length
            ? rows.map(([label, action]) => `<p class="history-next"><span>${escapeHtml(label)}</span> <strong>${escapeHtml(action)}</strong></p>`).join("")
            : `<p class="hint-text">${t("Noch keine Bearbeitung zum Rückgängigmachen.")}</p>`;
    }

    function applyHistorySaveState(element, { hasPlayer = false, isDirty = false } = {}) {
        if (!element) return;
        const text = !hasPlayer ? t("Lade einen Spieler, um Änderungen zu bearbeiten.")
            : isDirty ? t("Ungespeicherte Änderungen") : t("Keine ungespeicherten Änderungen");
        if (element.textContent !== text) element.textContent = text;
        element.dataset.state = !hasPlayer ? "empty" : isDirty ? "dirty" : "clean";
    }

    window.MCBEUndoRedoView = {
        applyUndoRedoButtonModels,
        undoRedoButtonModels,
        undoRedoPanelHtml,
        applyHistorySaveState,
    };
}());
