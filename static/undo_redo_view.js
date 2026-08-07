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

    function renderItems(items, empty) {
        return items.length
            ? `<ol>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`
            : `<div class="hint-text">${escapeHtml(empty)}</div>`;
    }

    function undoRedoButtonModels({ undoLabels = [], redoLabels = [], undoCount = 0, redoCount = 0 } = {}) {
        return {
            undo: {
                disabled: undoCount === 0,
                text: undoCount ? `↩ ${undoCount}` : "↩",
                title: undoCount ? t("Rückgängig: {label}", { label: undoLabels[undoLabels.length - 1] || t("letzte Änderung") }) : t("Rückgängig (Ctrl+Z)"),
            },
            redo: {
                disabled: redoCount === 0,
                text: redoCount ? `↪ ${redoCount}` : "↪",
                title: redoCount ? t("Wiederholen: {label}", { label: redoLabels[redoLabels.length - 1] || t("letzte Änderung") }) : t("Wiederholen (Ctrl+Y)"),
            },
        };
    }

    function applyUndoRedoButtonModels(elements = {}, model = {}) {
        const pairs = [
            [elements.undoButton, model.undo],
            [elements.redoButton, model.redo],
        ];
        for (const [button, state] of pairs) {
            if (!button || !state) continue;
            button.disabled = Boolean(state.disabled);
            button.textContent = state.text || "";
            button.title = state.title || "";
        }
    }

    function undoRedoPanelHtml({ undoLabels = [], redoLabels = [], undoCount = 0, redoCount = 0 } = {}) {
        const undoItems = undoLabels.slice(-8).reverse();
        const redoItems = redoLabels.slice(-5).reverse();
        if (!undoItems.length && !redoItems.length) {
            return `<div class="no-backups">${t("Noch kein Undo/Redo-Stapel vorhanden.")}</div>`;
        }
        return `
        <div class="undo-stack-grid">
            <section class="diagnostic-details-card">
                <h4>${t("Rückgängig möglich ({count})", { count: undoCount })}</h4>
                ${renderItems(undoItems, t("Keine Rückgängig-Schritte."))}
            </section>
            <section class="diagnostic-details-card">
                <h4>${t("Wiederholen möglich ({count})", { count: redoCount })}</h4>
                ${renderItems(redoItems, t("Keine Wiederholen-Schritte."))}
            </section>
        </div>`;
    }

    window.MCBEUndoRedoView = {
        applyUndoRedoButtonModels,
        undoRedoButtonModels,
        undoRedoPanelHtml,
    };
}());
