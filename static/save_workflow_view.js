(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function escapeHtml(value) {
        if (window.MCBEHtmlUtils?.escapeHtml) return window.MCBEHtmlUtils.escapeHtml(value ?? "");
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function uniqueElements(elements = []) {
        const seen = new Set();
        const result = [];
        for (const element of elements) {
            if (!element || seen.has(element)) continue;
            seen.add(element);
            result.push(element);
        }
        return result;
    }

    function changeRows(summary, changeKindLabel = kind => kind) {
        if (!summary || summary.total === 0) return `<div class="save-workflow-empty">${t("Keine ungespeicherten Änderungen.")}</div>`;
        return summary.shown.map(change => {
            const cls = change.kind === "added" ? "added" : change.kind === "removed" ? "removed" : "changed";
            return `<div class="save-workflow-change ${cls}"><span>${escapeHtml(changeKindLabel(change.kind))}</span><p>${escapeHtml(change.label)}</p></div>`;
        }).join("") + (summary.hidden > 0 ? `<div class="save-change-more">+ ${summary.hidden === 1 ? t("1 weitere Änderung") : t("{count} weitere Änderungen", { count: summary.hidden })}</div>` : "");
    }

    function sectionPills(labels = []) {
        const items = labels.length ? labels : [t("Nichts zu schreiben")];
        return items.map(label => `<span>${escapeHtml(label)}</span>`).join("");
    }

    function validationLabel(validation = {}) {
        if (validation.errors > 0) return t("{count} Fehler blockieren das Speichern", { count: validation.errors });
        if (validation.warnings > 0) return validation.warnings === 1 ? t("1 Warnung") : t("{count} Warnungen", { count: validation.warnings });
        return t("Keine blockierenden Probleme");
    }

    function validationRows(validation = {}) {
        return (validation.shown || []).map(issue => {
            const level = issue.level === "error" ? t("Fehler") : issue.level === "warning" ? t("Warnung") : t("Hinweis");
            return `<div class="save-validation-row ${escapeHtml(issue.level)}"><span>${escapeHtml(level)}</span><p>${escapeHtml(issue.label)}</p></div>`;
        }).join("");
    }

    function workflowSummaryHtml({ summary = {}, validation = {}, isDirty = false, playerLabel = "", sectionLabels = [], changeKindLabel = kind => kind } = {}) {
        const validationClass = validation.errors > 0 ? "error" : validation.warnings > 0 ? "warning" : "ok";
        const rows = validationRows(validation);
        const cleanText = isDirty ? t("Ungespeicherte Änderungen vorhanden") : t("Keine ungespeicherten Änderungen");
        return `
        <div class="save-workflow-status-grid">
            <div><span>Status</span><strong>${escapeHtml(cleanText)}</strong><small>${escapeHtml(playerLabel)}</small></div>
            <div><span>${t("Schreibbereiche")}</span><strong>${escapeHtml(summary.total ?? 0)}</strong><small>${t("Nur geänderte Sektionen werden gesendet")}</small></div>
            <div><span>${t("Prüfung")}</span><strong class="${validationClass}">${escapeHtml(validationLabel(validation))}</strong><small>${t("Backup vor jedem Save")}</small></div>
        </div>
        <div class="save-workflow-pills">${sectionPills(sectionLabels)}</div>
        <div class="save-review-section">
            <h4>${t("Änderungen")}</h4>
            ${changeRows(summary, changeKindLabel)}
        </div>
        <div class="save-review-section">
            <h4>${t("Speicherprüfung")}</h4>
            ${rows || `<div class="save-validation-status ok">${t("Keine Probleme erkannt.")}</div>`}
            ${validation.hidden > 0 ? `<div class="save-change-more">+ ${validation.hidden === 1 ? t("1 weitere Prüfmeldung") : t("{count} weitere Prüfmeldungen", { count: validation.hidden })}</div>` : ""}
        </div>
    `;
    }

    function emptyWorkflowHtml() {
        return `<div class="no-backups">${t("Lade zuerst einen bearbeitbaren Spieler. Danach zeigt dieser Schritt exakt, welche Bereiche geschrieben werden.")}</div>`;
    }

    function emptyDecisionLogHtml() {
        return `<div class="no-backups">${t("Noch kein Spieler geladen. Es gibt deshalb keinen Schreibplan.")}</div>`;
    }

    function decisionLogHtml(rows = []) {
        if (!rows || !rows.length) return `<div class="no-backups">${t("Keine Entscheidungsdetails verfügbar.")}</div>`;
        return rows.map(row => `
        <div class="decision-log-row ${escapeHtml(row.severity || "ok")}">
            <span>${escapeHtml(row.title || "Detail")}</span>
            <p>${escapeHtml(row.text || "")}</p>
        </div>
    `).join("");
    }

    function applyWorkflowPanelModel(elements = {}, model = {}) {
        const {
            summary = null,
            decisionLog = null,
            copyButton = null,
            runButton = null,
        } = elements;
        if (summary) summary.innerHTML = model.summaryHtml || "";
        if (decisionLog) decisionLog.innerHTML = model.decisionLogHtml || "";
        if (copyButton) copyButton.disabled = Boolean(model.copyDisabled);
        if (runButton) runButton.disabled = Boolean(model.runDisabled);
    }



    function createSaveWorkflowController({
        elements = {},
        getCleanSnapshot = () => null,
        getPendingMounts = () => [],
        takeSnapshot = () => ({}),
        sectionChanged = () => false,
        workflowStateContext = () => ({}),
        buildChangeSummary = () => ({ total: 0, shown: [], hidden: 0 }),
        buildChangeSummaryText = () => "",
        validateInventoryState = () => ({ errors: 0, warnings: 0, shown: [], hidden: 0 }),
        currentPlayerLabel = () => t("Spieler"),
        changeKindLabel = kind => kind,
        collectEditorDecisionDetails = () => [],
        getIsDirty = () => false,
        writeBlocked = () => false,
        copyTextToClipboard = () => {},
        saveCurrentPlayer = () => {},
    } = {}) {
        const {
            panel = null,
            summary = null,
            decisionLog = null,
            refreshButton = null,
            copyButton = null,
            runButton = null,
        } = elements;

        function sectionLabels() {
            const cleanSnapshot = getCleanSnapshot();
            if (!cleanSnapshot) return [t("Spieler neu geladen")];
            const current = takeSnapshot();
            const labels = [];
            if (sectionChanged(cleanSnapshot.inv, current.inv)) labels.push(t("Inventar"));
            if (sectionChanged(cleanSnapshot.ec, current.ec)) labels.push(t("Enderchest"));
            if (sectionChanged(cleanSnapshot.stats, current.stats)) labels.push(t("Stats/Position"));
            if (sectionChanged(cleanSnapshot.effects, current.effects)) labels.push(t("Effekte"));
            if (sectionChanged(cleanSnapshot.abilities, current.abilities)) labels.push(t("Fähigkeiten"));
            if (getPendingMounts().length) labels.push("Mounts");
            return labels;
        }

        function render() {
            if (!panel || !summary) return;
            const hasPlayer = window.MCBEWorkflowState.hasLoadedEditablePlayer(workflowStateContext());
            if (!hasPlayer) {
                applyWorkflowPanelModel({
                    summary,
                    decisionLog,
                    copyButton,
                    runButton,
                }, {
                    summaryHtml: emptyWorkflowHtml(),
                    decisionLogHtml: emptyDecisionLogHtml(),
                    copyDisabled: true,
                    runDisabled: true,
                });
                return;
            }
            const changeSummary = buildChangeSummary({ limit: 30, includeSections: true });
            const validation = validateInventoryState({ limit: 16 });
            applyWorkflowPanelModel({
                summary,
                decisionLog,
                copyButton,
                runButton,
            }, {
                summaryHtml: workflowSummaryHtml({
                    summary: changeSummary,
                    validation,
                    isDirty: getIsDirty(),
                    playerLabel: currentPlayerLabel(),
                    sectionLabels: sectionLabels(),
                    changeKindLabel,
                }),
                decisionLogHtml: decisionLogHtml(collectEditorDecisionDetails(changeSummary, validation)),
                copyDisabled: !hasPlayer,
                runDisabled: !getIsDirty() || writeBlocked() || validation.errors > 0,
            });
        }

        function copySummary() {
            copyTextToClipboard(
                buildChangeSummaryText(
                    buildChangeSummary({ limit: 100, includeSections: true }),
                    validateInventoryState({ limit: 100 }),
                ),
                t("Änderungsübersicht kopiert."),
            );
        }

        function wire() {
            refreshButton?.addEventListener("click", render);
            copyButton?.addEventListener("click", copySummary);
            runButton?.addEventListener("click", () => saveCurrentPlayer({ skipReview: true }));
        }

        return {
            copySummary,
            render,
            sectionLabels,
            wire,
        };
    }



    function collectSaveWorkflowElements(doc = document) {
        return {
            panel: doc.getElementById("saveWorkflowPanel"),
            summary: doc.getElementById("saveWorkflowSummary"),
            decisionLog: doc.getElementById("saveDecisionLog"),
            refreshButton: doc.getElementById("btnSaveWorkflowRefresh"),
            copyButton: doc.getElementById("btnSaveWorkflowCopy"),
            runButton: doc.getElementById("btnSaveWorkflowRun"),
        };
    }

    function createInventorySaveWorkflowController({ doc = document, ...deps } = {}) {
        return createSaveWorkflowController({
            ...deps,
            elements: collectSaveWorkflowElements(doc),
        });
    }



    function createDirtyActionsController({
        elements = {},
        getCurrentPlayerKey = () => "",
        saveCurrentPlayer = () => {},
        setWorkflowView = () => {},
        loadPlayer = async () => {},
        showConfirmDialog = async () => false,
        showToast = () => {},
    } = {}) {
        const {
            saveButton = null,
            reviewButton = null,
            showPreviewButton = null,
            discardButton = null,
            discardButtons = [],
        } = elements;
        const allDiscardButtons = discardButtons.length ? uniqueElements(discardButtons) : [discardButton].filter(Boolean);

        function openReview() {
            setWorkflowView("save", { user: true });
        }

        async function discardChanges() {
            const playerKey = getCurrentPlayerKey();
            if (!playerKey) return false;
            const ok = await showConfirmDialog(t("Ungespeicherte Änderungen verwerfen und den zuletzt gespeicherten Spielerstand neu laden?"));
            if (!ok) return false;
            const reloaded = await loadPlayer(playerKey, true);
            if (reloaded !== true) {
                showToast(
                    t("Änderungen konnten nicht verworfen werden. Der gespeicherte Spielerstand wurde nicht neu geladen."),
                    "error",
                    5200,
                );
                return false;
            }
            showToast(t("Änderungen verworfen. Zuletzt gespeicherter Stand wurde neu geladen."), "success", 3500);
            return true;
        }

        function wire() {
            saveButton?.addEventListener("click", () => saveCurrentPlayer({ skipReview: false }));
            reviewButton?.addEventListener("click", openReview);
            showPreviewButton?.addEventListener("click", openReview);
            allDiscardButtons.forEach(button => button?.addEventListener("click", discardChanges));
        }

        return { discardChanges, openReview, wire };
    }

    function markDiscardActionButton(button, id) {
        if (!button) return null;
        if (button.setAttribute) button.setAttribute("data-discard-changes", "true");
        if (button.id === "btnDiscardChanges") button.id = id;
        return button;
    }

    function normalizeDiscardActionButtons(doc = document) {
        const explicitButtons = Array.from(doc.querySelectorAll?.("[data-discard-changes]") || []);
        const legacyButtons = Array.from(doc.querySelectorAll?.("#btnDiscardChanges") || []);
        const namedButtons = [doc.getElementById?.("btnDirtyDiscardChanges"), doc.getElementById?.("btnSafeEditDiscardChanges")];
        const legacyOrNamedButtons = uniqueElements([...legacyButtons, ...namedButtons]);
        legacyOrNamedButtons.forEach((button, index) => {
            markDiscardActionButton(button, index === 0 ? "btnDirtyDiscardChanges" : "btnSafeEditDiscardChanges");
        });
        explicitButtons.forEach(button => markDiscardActionButton(button, button.id));
        return uniqueElements([...explicitButtons, ...legacyOrNamedButtons]);
    }

    function collectDirtyActionElements(doc = document) {
        const discardButtons = normalizeDiscardActionButtons(doc);
        return {
            saveButton: doc.getElementById("btnDirtySave"),
            reviewButton: doc.getElementById("btnDirtyReview"),
            showPreviewButton: doc.getElementById("btnShowSavePreview"),
            discardButton: discardButtons[0] || null,
            discardButtons,
        };
    }

    function createInventoryDirtyActionsController({
        doc = document,
        getCurrentPlayerKey = () => "",
        saveCurrentPlayer = () => {},
        setWorkflowView = () => {},
        loadPlayer = async () => {},
        showConfirmDialog = async () => false,
        showToast = () => {},
    } = {}) {
        return createDirtyActionsController({
            elements: collectDirtyActionElements(doc),
            getCurrentPlayerKey,
            saveCurrentPlayer,
            setWorkflowView,
            loadPlayer,
            showConfirmDialog,
            showToast,
        });
    }


    window.MCBESaveWorkflowView = {
        applyWorkflowPanelModel,
        createSaveWorkflowController,
        collectSaveWorkflowElements,
        createInventorySaveWorkflowController,
        collectDirtyActionElements,
        createInventoryDirtyActionsController,
        createDirtyActionsController,
        changeRows,
        decisionLogHtml,
        emptyDecisionLogHtml,
        emptyWorkflowHtml,
        normalizeDiscardActionButtons,
        sectionPills,
        workflowSummaryHtml,
    };
}());
