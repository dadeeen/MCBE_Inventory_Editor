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

    function changeRows(summary = {}, changeKindLabel = kind => kind) {
        const shown = Array.isArray(summary.shown) ? summary.shown : [];
        const rows = shown.map(change => {
            const cls = change.kind === "added" ? "added" : change.kind === "removed" ? "removed" : "changed";
            const label = changeKindLabel(change.kind);
            return `<div class="save-change-row ${cls}"><span>${escapeHtml(label)}</span><p>${escapeHtml(change.label)}</p></div>`;
        }).join("");
        const hidden = summary.hidden > 0 ? `<div class="save-change-more">+ ${summary.hidden === 1 ? t("1 weitere Änderung") : t("{count} weitere Änderungen", { count: summary.hidden })}</div>` : "";
        const empty = summary.total === 0
            ? `<div class="save-change-empty">${t("Keine sichtbaren Slot-Änderungen erkannt. Es können technische/metadatenbezogene Änderungen im Spielerstand enthalten sein.")}</div>`
            : "";
        return empty || rows + hidden;
    }

    function validationRows(validation = {}) {
        const shown = Array.isArray(validation.shown) ? validation.shown : [];
        return shown.map(issue => {
            const label = issue.level === "error" ? t("Fehler") : issue.level === "warning" ? t("Warnung") : t("Hinweis");
            return `<div class="save-validation-row ${escapeHtml(issue.level)}"><span>${escapeHtml(label)}</span><p>${escapeHtml(issue.label)}</p></div>`;
        }).join("");
    }

    function validationStatus(validation = {}) {
        if (validation.errors > 0) {
            return `<div class="save-validation-status error">${t("{count} Fehler blockieren das Speichern. Bitte korrigieren oder verwerfen.", { count: validation.errors })}</div>`;
        }
        if (validation.warnings > 0) {
            return `<div class="save-validation-status warning">${validation.warnings === 1 ? t("1 Warnung") : t("{count} Warnungen", { count: validation.warnings })}. ${t("Speichern ist möglich, prüfe die Hinweise bewusst.")}</div>`;
        }
        return `<div class="save-validation-status ok">${t("Keine blockierenden Probleme erkannt.")}</div>`;
    }

    function saveReviewHtml({ summary = {}, validation = {}, playerLabel = "", worldLabel = "", changeKindLabel = kind => kind } = {}) {
        const validationHidden = validation.hidden > 0 ? `<div class="save-change-more">+ ${validation.hidden === 1 ? t("1 weitere Prüfmeldung") : t("{count} weitere Prüfmeldungen", { count: validation.hidden })}</div>` : "";
        return `
        <div class="save-review-target">
            <strong>${escapeHtml(playerLabel)}</strong>
            <span>${escapeHtml(worldLabel || t("Geladene Welt"))}</span>
        </div>
        <div class="save-review-section">
            <h4>${t("Änderungen")}</h4>
            ${changeRows(summary, changeKindLabel)}
        </div>
        <div class="save-review-section">
            <h4>${t("Speicherprüfung")}</h4>
            ${validationStatus(validation)}
            ${validationRows(validation) || ""}${validationHidden}
        </div>
    `;
    }

    window.MCBESaveReviewView = {
        saveReviewHtml,
    };
}());

(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const view = window.MCBESaveReviewView || {};

    function createSaveReviewController({
        doc = document,
        elements = {},
        getPlayerLabel,
        getWorldLabel,
        changeKindLabel,
        collectEditorDecisionDetails,
        buildChangeSummaryText,
        decisionLogText,
        copyTextToClipboard,
        showToast,
    } = {}) {
        function render(summary, validation = {}) {
            if (!elements.summary) return;
            elements.summary.innerHTML = view.saveReviewHtml({
                summary,
                validation,
                playerLabel: getPlayerLabel?.() || t("Spieler"),
                worldLabel: getWorldLabel?.() || t("Geladene Welt"),
                changeKindLabel,
            });
            if (elements.confirmButton) elements.confirmButton.disabled = validation.errors > 0;
            if (elements.decisionLog) {
                elements.decisionLog.innerHTML = window.MCBESaveWorkflowView.decisionLogHtml(
                    collectEditorDecisionDetails?.(summary, validation) || [],
                );
            }
            if (elements.copyButton) {
                elements.copyButton.onclick = () => copyTextToClipboard?.(
                    buildChangeSummaryText?.(summary, validation) || "",
                    t("Änderungsübersicht kopiert."),
                );
            }
            if (elements.copyDetailsButton) {
                elements.copyDetailsButton.onclick = () => copyTextToClipboard?.(
                    `${buildChangeSummaryText?.(summary, validation) || ""}\n\n${decisionLogText?.(summary, validation) || ""}`,
                    t("Änderungsdetails kopiert."),
                );
            }
        }

        function open(summary, validation = {}) {
            render(summary, validation);
            return new Promise(resolve => {
                if (!elements.overlay) {
                    resolve(true);
                    return;
                }
                const cleanup = (value) => {
                    elements.overlay.style.display = "none";
                    elements.confirmButton?.removeEventListener("click", onConfirm);
                    elements.cancelButton?.removeEventListener("click", onCancel);
                    elements.closeButton?.removeEventListener("click", onCancel);
                    elements.overlay.removeEventListener("click", onOverlayClick);
                    doc.removeEventListener("keydown", onKeyDown);
                    resolve(value);
                };
                const onConfirm = () => {
                    if (validation.errors > 0) {
                        showToast?.(t("Speichern ist wegen Validierungsfehlern blockiert."), "error", 4000);
                        return;
                    }
                    cleanup(true);
                };
                const onCancel = () => cleanup(false);
                const onOverlayClick = (event) => { if (event.target === elements.overlay) cleanup(false); };
                const onKeyDown = (event) => { if (event.key === "Escape") cleanup(false); };
                elements.confirmButton?.addEventListener("click", onConfirm);
                elements.cancelButton?.addEventListener("click", onCancel);
                elements.closeButton?.addEventListener("click", onCancel);
                elements.overlay.addEventListener("click", onOverlayClick);
                doc.addEventListener("keydown", onKeyDown);
                elements.overlay.style.display = "flex";
                elements.confirmButton?.focus();
            });
        }

        return { open, render };
    }

    function collectSaveReviewElements(doc = document) {
        return {
            overlay: doc.getElementById("saveReviewOverlay"),
            summary: doc.getElementById("saveReviewSummary"),
            decisionLog: doc.getElementById("saveReviewDecisionLog"),
            confirmButton: doc.getElementById("btnSaveReviewConfirm"),
            cancelButton: doc.getElementById("btnSaveReviewCancel"),
            closeButton: doc.getElementById("btnSaveReviewClose"),
            copyButton: doc.getElementById("btnSaveReviewCopy"),
            copyDetailsButton: doc.getElementById("btnSaveReviewCopyDetails"),
        };
    }

    function createInventorySaveReviewController({ doc = document, ...deps } = {}) {
        return createSaveReviewController({
            ...deps,
            doc,
            elements: collectSaveReviewElements(doc),
        });
    }

    window.MCBESaveReviewView = {
        ...view,
        collectSaveReviewElements,
        createInventorySaveReviewController,
        createSaveReviewController,
    };
}());
