(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function statusChipModel(label, value, goodValues = ["ok", "offline", "disabled", true]) {
        const ok = goodValues.includes(value);
        const cls = ok ? "ok" : (value === "unknown" || value === "empty" || value === "not-configured" ? "warn" : "bad");
        return { label, value: String(value ?? t("unbekannt")), className: cls };
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

    function statusChipHtml(label, value, goodValues = ["ok", "offline", "disabled", true]) {
        const chip = statusChipModel(label, value, goodValues);
        return `<div class="diagnostic-chip ${escapeAttr(chip.className)}"><span>${escapeHtml(chip.label)}</span><strong>${escapeHtml(chip.value)}</strong></div>`;
    }

    function statusMessageHtml(message, { level = "" } = {}) {
        const cls = level ? ` ${escapeAttr(level)}` : "";
        return `<div class="no-backups${cls}">${escapeHtml(message)}</div>`;
    }

    function formatLogTimestamp(raw) {
        const text = String(raw || "").trim();
        if (!text) return "";
        const iso = text.replace(/([+-]\d{2})(\d{2})$/, "$1:$2");
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return text;
        return window.MCBEI18n?.formatDate?.(date, {
            day: "2-digit",
            month: "2-digit",
            year: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        }) || date.toLocaleString();
    }

    function logCategory(entry) {
        const logger = String(entry?.logger || "");
        const message = String(entry?.message || "");
        if (logger === "werkzeug") {
            if (/\/api\/heartbeat|\/api\/server_status|\/api\/diagnostics\/status|\/api\/world\/presence/.test(message)) {
                return { key: "http-noise", label: t("HTTP automatisch") };
            }
            if (/\/api\//.test(message)) return { key: "http-api", label: "HTTP API" };
            return { key: "http", label: "HTTP" };
        }
        if (logger.includes("audit")) return { key: "audit", label: "Audit" };
        if (logger.includes("mcbe_editor")) return { key: "app", label: "App" };
        if (String(entry?.level || "").toUpperCase() === "ERROR") return { key: "error", label: t("Fehler") };
        return { key: "system", label: logger || "System" };
    }

    function runtimeDiagnosticsText(data) {
        if (!data) return t("Keine Diagnose geladen.");
        const root = data.worlds_root || {};
        const gateSetup = data.write_gate_setup || {};
        const gate = data.write_gate || {};
        const server = gate.server_status || {};
        return [
            t("MCBE Inventory Editor Diagnose"),
            `Version: ${data.distribution?.project_version || "dev"}`,
            t("Modus: {mode}", { mode: data.mode }),
            t("Welt-Root: {value}", { value: root.root || "auto" }),
            t("Welt-Root Status: {value}", { value: root.status || t("unbekannt") }),
            t("Welt-Root Meldung: {value}", { value: root.message || "" }),
            `Contains World Hint: ${root.contains_world_hint ?? t("unbekannt")}`,
            `Write Gate Setup: ${gateSetup.status || t("unbekannt")}`,
            `Write Gate Reason: ${gate.reason || gateSetup.message || ""}`,
            `Local World Access Warning: ${gateSetup.local_world_access_warning === true ? t("ja") : t("nein")}`,
            t("Serverstatus: {value}", { value: server.status || "unknown" }),
            `Server: ${server.server_host || data.config?.server_host || t("nicht gesetzt")}:${server.server_port || data.config?.server_port || ""}`,
            `Data Root: ${data.data_root?.path || t("unbekannt")}`,
            `Backup Root: ${data.config?.backup_root || t("unbekannt")}`,
            `Scan: depth=${data.config?.world_scan_depth} max_dirs=${data.config?.world_scan_max_dirs}`,
        ].join("\n");
    }

    function runtimeDiagnosticsHtml(data, options = {}) {
        if (!data || !data.success) {
            return `<div class="no-backups error">${t("Diagnose konnte nicht geladen werden.")}</div>`;
        }
        const root = data.worlds_root || {};
        const gateSetup = data.write_gate_setup || {};
        const gate = data.write_gate || {};
        const server = gate.server_status || {};
        const dataRoot = data.data_root || {};
        const dist = data.distribution || {};
        const worldsRoot = root.root || options.worldsRoot || t("automatisch");
        const worldHint = root.contains_world_hint === true
            ? t("gefunden")
            : (root.contains_world_hint === false ? t("nicht gefunden") : t("unbekannt"));
        return `
        <div class="diagnostic-grid">
            ${statusChipHtml(t("Modus"), data.mode || "local", ["local", "docker"])}
            ${statusChipHtml(t("Welt-Root"), root.status || "auto", ["ok", "not-configured"])}
            ${statusChipHtml(t("Welthinweis"), worldHint, [t("gefunden"), t("unbekannt")])}
            ${statusChipHtml(t("Schreibsperre"), gateSetup.status || t("unbekannt"), ["configured", "disabled"])}
            ${statusChipHtml(t("Serverstatus"), server.status || "unknown", ["offline", "unknown"])}
            ${statusChipHtml(t("Datenordner"), dataRoot.writable === true ? t("beschreibbar") : t("prüfen"), [t("beschreibbar")])}
        </div>
        <div class="diagnostic-details-card">
            <strong>Details</strong>
            <div>${t("Welt-Root")}: <code>${escapeHtml(worldsRoot)}</code></div>
            <div>${t("Welt-Root Meldung: {value}", { value: escapeHtml(root.message || t("keine")) })}</div>
            <div>${t("Schreibschutz: {value}", { value: escapeHtml(gate.reason || gateSetup.message || t("keine Meldung")) })}</div>
            ${gateSetup.local_world_access_warning ? `<div class="diagnostic-warning">${t("Lokalmodus: Die App kann ohne konfigurierte Serveradresse nicht zuverlässig erkennen, ob Minecraft oder ein Bedrock-Server diese Welt gerade geöffnet hat.")}</div>` : ""}
            <div>${t("Daten")}: <code>${escapeHtml(dataRoot.path || t("unbekannt"))}</code></div>
            <div>Distribution: ${escapeHtml(dist.kind || "dev")} · Version ${escapeHtml(dist.project_version || "dev")}</div>
        </div>
    `;
    }

    function recentLogsText(logs = []) {
        if (!Array.isArray(logs) || !logs.length) return t("Keine Logs geladen.");
        return logs.map(entry => {
            const category = logCategory(entry);
            return `[${formatLogTimestamp(entry.ts)}] ${entry.level || "INFO"} ${category.label}: ${entry.message || ""}${entry.traceback ? `\n${entry.traceback}` : ""}`;
        }).join("\n");
    }

    function recentLogsHtml(logs = []) {
        if (!Array.isArray(logs) || logs.length === 0) {
            return `<div class="no-backups">${t("Keine Logs im aktuellen Serverprozess.")}</div>`;
        }
        const visibleLogs = logs.slice(-80).reverse();
        const noisyHttp = visibleLogs.filter(entry => logCategory(entry).key === "http-noise").length;
        const rows = visibleLogs.map(entry => {
            const level = String(entry.level || "INFO").toLowerCase();
            const category = logCategory(entry);
            const trace = entry.traceback ? `<pre class="log-trace">${escapeHtml(entry.traceback)}</pre>` : "";
            return `
            <div class="log-row ${escapeAttr(level)} ${escapeAttr(category.key)}">
                <span class="log-level">${escapeHtml(entry.level || "INFO")}</span>
                <span class="log-time">${escapeHtml(formatLogTimestamp(entry.ts))}</span>
                <span class="log-category">${escapeHtml(category.label)}</span>
                <code class="log-message">${escapeHtml(entry.message || "")}</code>
                ${trace}
            </div>`;
        }).join("");
        const hint = noisyHttp > 0
            ? `<div class="log-hint">${t("{count} automatische HTTP-Status-/Heartbeat-Zeile(n) enthalten.", { count: noisyHttp })}</div>`
            : "";
        return `<div class="log-list">${hint}${rows}</div>`;
    }

    function auditEventSummary(event) {
        const parts = [];
        if (event.username) parts.push(t("Benutzer {name}", { name: event.username }));
        if (event.remote) parts.push(`Remote ${event.remote}`);
        if (event.world && event.world.name) parts.push(t("Welt {name}", { name: event.world.name }));
        if (event.player && event.player.preview) parts.push(t("Spieler {name}", { name: event.player.preview }));
        if (event.error) parts.push(t("Fehler {error}", { error: event.error }));
        return parts.join(" · ");
    }

    function auditEventsHtml(events = [], auditLog = null) {
        const healthWarning = auditLog && auditLog.healthy === false
            ? `<div class="status-message error">${escapeHtml(t("Audit-Log kann derzeit nicht geschrieben werden. Details stehen in den Anwendungslogs."))}</div>`
            : "";
        if (!Array.isArray(events) || !events.length) {
            const storage = auditLog && auditLog.enabled === false
                ? t("Audit-Log ist deaktiviert.")
                : t("Noch keine Audit-Ereignisse vorhanden.");
            return `${healthWarning}<div class="no-backups">${escapeHtml(storage)}</div>`;
        }
        const rows = events.slice().reverse().map(event => {
            const outcome = String(event.outcome || "unknown").toLowerCase();
            const summary = auditEventSummary(event);
            const details = event.details && typeof event.details === "object"
                ? `<code>${escapeHtml(JSON.stringify(event.details))}</code>`
                : "";
            return `
            <div class="audit-row ${escapeAttr(outcome)}">
                <div class="audit-main"><strong>${escapeHtml(event.action || "Audit")}</strong><span class="audit-outcome">${escapeHtml(event.outcome || "")}</span></div>
                <small>${escapeHtml(formatLogTimestamp(event.ts))}</small>
                ${summary ? `<p>${escapeHtml(summary)}</p>` : ""}
                ${details}
            </div>`;
        }).join("");
        return healthWarning + rows;
    }



    function createDiagnosticsController({
        elements = {},
        appConfig = {},
        parseJsonResponse = response => response.json(),
        copyTextToClipboard = () => {},
        getCurrentCompatibility = () => ({}),
        getIconSourceSummary = () => ({}),
        getIsDirty = () => false,
        getWorldPath = () => "",
        getCurrentPlayerLabel = () => "",
        onRuntimeDiagnostics = () => {},
    } = {}) {
        const {
            runtimeDiagnostics = null,
            recentLogsPanel = null,
            refreshRuntimeButton = null,
            copyRuntimeButton = null,
            refreshLogsButton = null,
            copyLogsButton = null,
        } = elements;
        let lastRuntimeDiagnostics = null;
        let lastRecentLogs = [];

        function renderRuntimeDiagnostics(data) {
            if (!runtimeDiagnostics) return;
            runtimeDiagnostics.innerHTML = runtimeDiagnosticsHtml(data, { worldsRoot: appConfig.worlds_root });
        }

        function statusCenterText() {
            return window.MCBEStatusCenterView.statusCenterText({
                runtimeDiagnostics: lastRuntimeDiagnostics || {},
                appConfig,
                currentCompatibility: getCurrentCompatibility(),
                iconSummary: getIconSourceSummary(),
                isDirty: getIsDirty(),
                worldPath: getWorldPath(),
                currentPlayerLabel: getCurrentPlayerLabel(),
            });
        }

        async function loadRuntimeDiagnostics() {
            if (!runtimeDiagnostics) return;
            runtimeDiagnostics.innerHTML = statusMessageHtml(t("Diagnose wird geladen..."));
            try {
                const res = await fetch("/api/diagnostics/status");
                const data = await parseJsonResponse(res);
                lastRuntimeDiagnostics = data;
                onRuntimeDiagnostics(data);
                renderRuntimeDiagnostics(data);
            } catch (_e) {
                runtimeDiagnostics.innerHTML = statusMessageHtml(t("Diagnose konnte nicht geladen werden."), { level: "error" });
            }
        }

        function renderRecentLogs(logs) {
            if (!recentLogsPanel) return;
            recentLogsPanel.innerHTML = recentLogsHtml(logs);
        }

        function recentLogsTextForCopy(logs = lastRecentLogs) {
            return recentLogsText(logs);
        }

        async function loadRecentLogs() {
            if (!recentLogsPanel) return;
            recentLogsPanel.innerHTML = statusMessageHtml(t("Logs werden geladen..."));
            try {
                const res = await fetch("/api/logs/recent?level=INFO&limit=80");
                const data = await parseJsonResponse(res);
                lastRecentLogs = Array.isArray(data.logs) ? data.logs : [];
                renderRecentLogs(lastRecentLogs);
            } catch (e) {
                recentLogsPanel.innerHTML = statusMessageHtml(
                    t("Logs konnten nicht geladen werden: {error}", { error: e.message || t("unbekannter Fehler") }),
                    { level: "error" }
                );
            }
        }

        function wire() {
            refreshRuntimeButton?.addEventListener("click", loadRuntimeDiagnostics);
            copyRuntimeButton?.addEventListener("click", () => copyTextToClipboard(statusCenterText(), t("Status kopiert.")));
            refreshLogsButton?.addEventListener("click", loadRecentLogs);
            copyLogsButton?.addEventListener("click", () => copyTextToClipboard(recentLogsTextForCopy(), t("Logs kopiert.")));
        }

        return {
            loadRecentLogs,
            loadRuntimeDiagnostics,
            recentLogsText: recentLogsTextForCopy,
            renderRecentLogs,
            renderRuntimeDiagnostics,
            statusCenterText,
            wire,
        };
    }

    function collectDiagnosticsElements(doc = document) {
        return {
            runtimeDiagnostics: doc.getElementById("runtimeDiagnostics"),
            recentLogsPanel: doc.getElementById("recentLogsPanel"),
            refreshRuntimeButton: doc.getElementById("btnRefreshRuntimeDiagnostics"),
            copyRuntimeButton: doc.getElementById("btnCopyRuntimeDiagnostics"),
            refreshLogsButton: doc.getElementById("btnRefreshRecentLogs"),
            copyLogsButton: doc.getElementById("btnCopyRecentLogs"),
        };
    }

    function createInventoryDiagnosticsController({
        doc = document,
        appConfig = {},
        api = {},
        copyTextToClipboard = () => {},
        getCurrentCompatibility = () => ({}),
        getIconSourceSummary = () => ({}),
        getIsDirty = () => false,
        getWorldPath = () => "",
        getCurrentPlayerLabel = () => "",
        onRuntimeDiagnostics = () => {},
    } = {}) {
        return createDiagnosticsController({
            elements: collectDiagnosticsElements(doc),
            appConfig,
            parseJsonResponse: api.parseJsonResponse,
            copyTextToClipboard,
            getCurrentCompatibility,
            getIconSourceSummary,
            getIsDirty,
            getWorldPath,
            getCurrentPlayerLabel,
            onRuntimeDiagnostics,
        });
    }


    window.MCBEDiagnosticsView = {
        auditEventSummary,
        collectDiagnosticsElements,
        createInventoryDiagnosticsController,
        createDiagnosticsController,
        auditEventsHtml,
        formatLogTimestamp,
        logCategory,
        recentLogsHtml,
        recentLogsText,
        runtimeDiagnosticsHtml,
        runtimeDiagnosticsText,
        statusMessageHtml,
        statusChipHtml,
        statusChipModel,
    };
}());

(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const view = window.MCBEDiagnosticsView || {};

    function createAuditEventsController({
        elements = {},
        parseJsonResponse = response => response.json(),
        buildErrorMessage = (data, fallback) => data?.error || fallback,
        exportUrl = "/api/audit/export?limit=1000",
    } = {}) {
        const { container = null, refreshButton = null, exportButton = null } = elements;

        function render(events, auditLog = null) {
            if (!container) return;
            container.innerHTML = view.auditEventsHtml(events, auditLog);
        }

        async function load() {
            if (!container) return;
            container.innerHTML = view.statusMessageHtml(t("Lade Audit-Ereignisse..."));
            try {
                const res = await fetch("/api/audit/events?limit=120");
                const data = await parseJsonResponse(res);
                if (!data.success) {
                    container.innerHTML = view.statusMessageHtml(
                        buildErrorMessage(data, t("Audit-Ereignisse konnten nicht geladen werden.")),
                        { level: "error" },
                    );
                    return;
                }
                render(data.events || [], data.audit_log || null);
            } catch (err) {
                console.error("loadAuditEvents:", err);
                container.innerHTML = view.statusMessageHtml(t("Verbindungsfehler beim Laden des Audit-Trails."), { level: "error" });
            }
        }

        function wire() {
            refreshButton?.addEventListener("click", load);
            exportButton?.addEventListener("click", () => {
                window.location.href = exportUrl;
            });
        }

        return { load, render, wire };
    }

    function collectAuditEventsElements(doc = document) {
        return {
            container: doc.getElementById("auditEventsContainer"),
            refreshButton: doc.getElementById("btnRefreshAudit"),
            exportButton: doc.getElementById("btnExportAudit"),
        };
    }

    function createInventoryAuditEventsController({ doc = document, ...deps } = {}) {
        return createAuditEventsController({
            ...deps,
            elements: collectAuditEventsElements(doc),
        });
    }

    window.MCBEDiagnosticsView = {
        ...view,
        collectAuditEventsElements,
        createInventoryAuditEventsController,
        createAuditEventsController,
    };
}());
