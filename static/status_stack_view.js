(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

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

    function normalizeStatusClassName(className) {
        return String(className || "").replace("save-status", "").trim();
    }

    const STATUS_META = Object.freeze({
        info: { label: t("Information"), icon: "i", rank: 0 },
        success: { label: t("Erfolgreich"), icon: "✓", rank: 0 },
        running: { label: t("Läuft"), icon: "↻", rank: 1 },
        warning: { label: t("Warnung"), icon: "!", rank: 2 },
        error: { label: t("Fehler"), icon: "×", rank: 3 },
    });

    function normalizeEntryType(value) {
        const type = String(value || "").trim().toLowerCase();
        return STATUS_META[type] ? type : "info";
    }

    function entryType(entry = {}) {
        const explicitType = String(entry.type || "").trim();
        const message = String(entry.message || "").trim();
        if (message.startsWith("Fehler:") || message.startsWith("Error:")) return "error";
        // Deutsche und englische Backend-Formulierungen erkennen (Server
        // übersetzt Meldungen jetzt pro Request-Locale).
        if (/\b(blockiert|gesperrt|abgebrochen|blocked|locked|aborted|rejected)\b|Server läuft noch|server is still running/i.test(message)) {
            return explicitType ? normalizeEntryType(explicitType) : "warning";
        }
        return normalizeEntryType(explicitType);
    }

    function entryIsActive(entry = {}) {
        if (typeof entry.active === "boolean") return entry.active;
        return entryType(entry) === "running";
    }

    function highestPriorityEntry(entries = []) {
        return entries.reduce((current, entry) => {
            if (!current) return entry;
            return STATUS_META[entryType(entry)].rank > STATUS_META[entryType(current)].rank ? entry : current;
        }, null);
    }

    function fallbackEntries({ statusText = "", statusClassName = "" } = {}) {
        const message = String(statusText || "").trim();
        if (!message) return [];
        return [{
            time: "",
            type: normalizeEntryType(normalizeStatusClassName(statusClassName)),
            message,
            active: false,
        }];
    }

    function statusStackModel({
        visibleNotices = [],
        statusText = "",
        statusClassName = "",
        isDirty = false,
        isTransientDirtyStatusText = null,
    } = {}) {
        const normalizedStatusText = String(statusText || "").trim();
        const hideTransientFallback = !isDirty
            && typeof isTransientDirtyStatusText === "function"
            && isTransientDirtyStatusText(normalizedStatusText);
        const entries = visibleNotices.length
            ? visibleNotices
            : (hideTransientFallback ? [] : fallbackEntries({ statusText: normalizedStatusText, statusClassName }));
        const activeEntries = entries.filter(entryIsActive);
        const latestEntry = entries[0] || null;
        const currentEntry = highestPriorityEntry(activeEntries) || entries[0] || null;
        const severity = currentEntry ? entryType(currentEntry) : "info";
        const latestType = latestEntry ? entryType(latestEntry) : "info";
        const openCount = activeEntries.length;
        const headline = severity === "error"
            ? t("Fehler")
            : severity === "warning"
                ? t("Hinweise")
                : severity === "running" ? t("Aktiv") : "Status";
        // Anzeige-Grenze: Server-Meldungen laufen durch t(); unbekannte Texte
        // bleiben unverändert (deutsche Quelle als Fallback).
        const summary = currentEntry?.message ? t(currentEntry.message) : t("Keine Hinweise");
        const latestStatusLabel = STATUS_META[latestType]?.label || STATUS_META.info.label;
        return {
            countText: openCount ? String(openCount) : STATUS_META[severity].icon,
            entries,
            hasWarning: severity === "warning",
            hasError: severity === "error",
            openCount,
            severity,
            headline,
            summary,
            ariaLabel: t("{headline}: {summary}. {count} offen.", { headline, summary, count: openCount }),
            liveMessage: latestEntry
                ? `${latestStatusLabel}: ${t(latestEntry.message)}`
                : t("Status: Keine offenen Hinweise."),
        };
    }

    function statusStackPanelHtml(entries = []) {
        return entries.length
            ? entries.map(entry => {
                const type = entryType(entry);
                const meta = STATUS_META[type];
                return `
            <div class="status-stack-entry save-status ${escapeAttr(type)}${entryIsActive(entry) ? " active" : ""}">
                <span class="status-stack-meta">
                    <span class="status-stack-kind"><span aria-hidden="true">${meta.icon}</span> ${meta.label}</span>
                    ${entry.time ? `<span class="status-stack-time">${escapeHtml(entry.time)}</span>` : ""}
                </span>
                <span class="status-stack-message">${escapeHtml(t(entry.message))}</span>
            </div>
        `;
            }).join("")
            : `<div class="status-stack-entry save-status">${t("Keine Hinweise")}</div>`;
    }

    function applyStatusStackModel(elements = {}, model = {}) {
        const {
            button = null,
            count = null,
            headline = null,
            summary = null,
            panel = null,
            live = null,
        } = elements;
        if (count) count.textContent = model.countText || "0";
        if (headline) headline.textContent = model.headline || "Status";
        if (summary) summary.textContent = model.summary || t("Keine Hinweise");
        if (button) {
            for (const type of Object.keys(STATUS_META)) {
                button.classList.toggle(type, model.severity === type);
            }
            button.setAttribute?.("aria-label", model.ariaLabel || t("Status anzeigen"));
        }
        if (panel) panel.innerHTML = statusStackPanelHtml(model.entries || []);
        if (live && live.textContent !== model.liveMessage) live.textContent = model.liveMessage || "";
    }

    window.MCBEStatusStackView = {
        applyStatusStackModel,
        entryIsActive,
        entryType,
        fallbackEntries,
        highestPriorityEntry,
        normalizeStatusClassName,
        statusStackModel,
        statusStackPanelHtml,
    };
}());
