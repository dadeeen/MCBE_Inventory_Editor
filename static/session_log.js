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

    function formatSessionTime(date = new Date()) {
        try {
            return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        } catch (_e) {
            return date.toISOString().slice(11, 19);
        }
    }

    function sessionTypeLabel(type) {
        return {
            edit: t("Bearbeitung"),
            load: t("Laden"),
            save: t("Speichern"),
            backup: t("Backup"),
            export: t("Export"),
            undo: t("Undo/Redo"),
            warning: t("Hinweis"),
        }[type] || "Info";
    }

    function sessionLogHtml(entries = []) {
        if (!entries.length) {
            return `<div class="no-backups">${t("Noch keine lokalen Bearbeitungsschritte.")}</div>`;
        }
        return entries.map(entry => `
        <div class="session-log-row ${escapeHtml(entry.type || "info")}">
            <span class="session-log-time">${escapeHtml(entry.time)}</span>
            <div>
                <strong>${escapeHtml(sessionTypeLabel(entry.type))}</strong>
                <small>${escapeHtml(entry.message)}</small>
            </div>
        </div>
    `).join("");
    }

    function buildSessionLogText(entries = [], context = {}) {
        const lines = [];
        lines.push(t("MCBE Inventory Editor - Sitzungs-Verlauf"));
        lines.push(`Version: ${context.version || "dev"}`);
        lines.push(t("Modus: {mode}", { mode: context.mode || t("unbekannt") }));
        if (context.worldPath) lines.push(t("Welt: {name} | {path}", { name: context.worldName || "", path: context.worldPath }));
        if (context.playerLabel) lines.push(t("Spieler: {player}", { player: context.playerLabel }));
        lines.push("");
        if (!entries.length) {
            lines.push(t("Keine lokalen Bearbeitungsschritte aufgezeichnet."));
        } else {
            entries.slice().reverse().forEach(entry => {
                lines.push(`[${entry.time}] ${sessionTypeLabel(entry.type)}: ${entry.message}`);
            });
        }
        return lines.join("\n");
    }



    function createStatusSessionController({
        elements = {},
        appConfig = {},
        statusNoticeStore = null,
        maxSessionLog = 80,
        getIsDirty = () => false,
        getWorldPath = () => "",
        getWorldName = () => "",
        getCurrentPlayer = () => null,
        getCurrentPlayerLabel = () => "",
        renderUndoRedoPanel = () => {},
        renderWorldAnalysis = () => {},
        copyTextToClipboard = () => {},
        showToast = () => {},
    } = {}) {
        const {
            statusMsg = null,
            statusStackButton = null,
            statusStackPanel = null,
            statusStackCount = null,
            statusStackHeadline = null,
            statusStackSummary = null,
            statusStackLive = null,
            sessionLogContainer = null,
            copyWorldAnalysisButton = null,
            copySessionLogButton = null,
            clearSessionLogButton = null,
        } = elements;
        let entries = [];
        let currentStatusKey = "";

        function updateHeaderStatusStack({ announce = true } = {}) {
            if (!statusStackButton || !statusStackSummary || !statusStackCount || !statusStackHeadline || !statusStackPanel) return;
            const statusText = String(statusMsg?.textContent || "").trim();
            const model = window.MCBEStatusStackView.statusStackModel({
                visibleNotices: statusNoticeStore?.visibleNotices({ isDirty: getIsDirty() }) || [],
                statusText,
                statusClassName: statusMsg?.className || "",
                isDirty: getIsDirty(),
                isTransientDirtyStatusText: window.MCBEStatusStore.isTransientDirtyStatusText,
            });
            window.MCBEStatusStackView.applyStatusStackModel({
                button: statusStackButton,
                count: statusStackCount,
                headline: statusStackHeadline,
                summary: statusStackSummary,
                panel: statusStackPanel,
                live: announce ? statusStackLive : null,
            }, model);
        }

        function logStatus(msg, type = "", options = {}) {
            if (!statusMsg) return;
            const text = String(msg || "").trim();
            if (!text) return;
            const normalizedType = String(type || "").trim();
            const category = String(options.category || "").trim();
            const key = String(options.key || "").trim();
            currentStatusKey = key;
            statusMsg.innerText = text;
            statusMsg.className = "save-status " + normalizedType;
            statusNoticeStore?.addNotice({
                time: formatSessionTime(),
                type: normalizedType,
                message: text,
                category,
                key,
                active: typeof options.active === "boolean" ? options.active : undefined,
            });
            updateHeaderStatusStack();
        }

        function clearStatus(key) {
            const removed = statusNoticeStore?.removeNotice(key) === true;
            if (removed) {
                if (currentStatusKey && currentStatusKey === String(key || "").trim()) {
                    statusMsg.innerText = "";
                    statusMsg.className = "save-status";
                    currentStatusKey = "";
                }
                if (statusStackLive) statusStackLive.textContent = "";
                updateHeaderStatusStack({ announce: false });
            }
            return removed;
        }

        function renderSessionLog() {
            if (!sessionLogContainer) return;
            sessionLogContainer.innerHTML = sessionLogHtml(entries);
        }

        function buildSessionLogTextForCopy() {
            return buildSessionLogText(entries, {
                version: appConfig?.distribution?.project_version || "dev",
                mode: appConfig?.mode || t("unbekannt"),
                worldName: getWorldName(),
                worldPath: getWorldPath(),
                playerLabel: getCurrentPlayer() ? getCurrentPlayerLabel() : "",
            });
        }

        function recordAction(message, type = "edit") {
            if (!message) return;
            entries.unshift({
                time: formatSessionTime(),
                type,
                message: String(message).slice(0, 400),
                player: getCurrentPlayerLabel ? getCurrentPlayerLabel() : "",
                world: getWorldName(),
            });
            if (entries.length > maxSessionLog) entries.length = maxSessionLog;
            renderSessionLog();
            renderUndoRedoPanel();
            renderWorldAnalysis();
        }

        function clearSessionLog() {
            entries = [];
            renderSessionLog();
            showToast(t("Sitzungs-Verlauf geleert."), "success", 2000);
        }

        function wire({ getWorldAnalysisText = () => "" } = {}) {
            statusStackButton?.addEventListener("click", () => {
                const open = statusStackPanel?.hidden === false;
                if (!statusStackPanel) return;
                statusStackPanel.hidden = open;
                statusStackButton.setAttribute("aria-expanded", String(!open));
            });
            document.addEventListener("click", (event) => {
                if (!statusStackPanel || statusStackPanel.hidden) return;
                if (statusStackPanel.contains(event.target) || statusStackButton?.contains(event.target)) return;
                statusStackPanel.hidden = true;
                statusStackButton?.setAttribute("aria-expanded", "false");
            });
            copyWorldAnalysisButton?.addEventListener("click", () => copyTextToClipboard(getWorldAnalysisText(), t("Weltanalyse kopiert.")));
            copySessionLogButton?.addEventListener("click", () => copyTextToClipboard(buildSessionLogTextForCopy(), t("Sitzungs-Verlauf kopiert.")));
            clearSessionLogButton?.addEventListener("click", clearSessionLog);
            updateHeaderStatusStack({ announce: false });
        }

        return {
            buildSessionLogText: buildSessionLogTextForCopy,
            clearStatus,
            clearSessionLog,
            logStatus,
            recordAction,
            renderSessionLog,
            updateHeaderStatusStack,
            wire,
        };
    }

    function collectStatusSessionElements(doc = document) {
        return {
            statusMsg: doc.getElementById("statusMsg"),
            statusStackButton: doc.getElementById("statusStackButton"),
            statusStackPanel: doc.getElementById("statusStackPanel"),
            statusStackCount: doc.getElementById("statusStackCount"),
            statusStackHeadline: doc.getElementById("statusStackHeadline"),
            statusStackSummary: doc.getElementById("statusStackSummary"),
            statusStackLive: doc.getElementById("statusStackLive"),
            sessionLogContainer: doc.getElementById("sessionLogContainer"),
            copyWorldAnalysisButton: doc.getElementById("btnCopyWorldAnalysis"),
            copySessionLogButton: doc.getElementById("btnCopySessionLog"),
            clearSessionLogButton: doc.getElementById("btnClearSessionLog"),
        };
    }

    function createInventoryStatusSessionController({ doc = document, ...deps } = {}) {
        return createStatusSessionController({
            ...deps,
            elements: collectStatusSessionElements(doc),
        });
    }

    window.MCBESessionLog = {
        collectStatusSessionElements,
        createInventoryStatusSessionController,
        createStatusSessionController,
        formatSessionTime,
        sessionTypeLabel,
        sessionLogHtml,
        buildSessionLogText,
    };
}());
