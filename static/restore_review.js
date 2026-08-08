(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function topLevelText(backup = {}) {
        return Array.isArray(backup.top_level_entries) && backup.top_level_entries.length
            ? backup.top_level_entries.join(", ")
            : t("unbekannt");
    }

    function restoreReviewModel(data, filename, { worldName = t("Geladene Welt"), worldPath = "" } = {}) {
        const backup = data?.backup || {};
        const target = data?.target_world || {};
        return {
            backup,
            checks: [
                { ok: backup.has_db === true, label: t("Backup enthält db/") },
                { ok: Number(backup.file_count || 0) > 0, label: t("ZIP enthält Dateien") },
                { ok: Number(backup.uncompressed_mb || 0) < 2048, label: t("Entpackte Größe wirkt plausibel") },
            ],
            targetName: target.name || target.folder || worldName || t("Geladene Welt"),
            topLevel: topLevelText(backup),
            worldPath,
            filename,
        };
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

    function backupTimestamp(isoValue, fallback) {
        if (window.MCBEHtmlUtils?.formatTimestamp) return window.MCBEHtmlUtils.formatTimestamp(isoValue, fallback);
        return String(fallback ?? "");
    }

    function backupIsoTimestamp(backup = {}) {
        return backup.created_at || backup.modified_at || "";
    }

    function backupTimestampTitle(backup = {}) {
        if (backup.created_at) return t("UTC-Zeitstempel: {value}", { value: backup.created_at });
        if (backup.modified_at) return t("UTC-Änderungszeit: {value}", { value: backup.modified_at });
        return "";
    }

    function restoreReviewHtml(model = {}) {
        const backup = model.backup || {};
        const filename = model.filename || "";
        const checks = Array.isArray(model.checks) ? model.checks : [];
        const timestampTitle = backupTimestampTitle(backup);
        return `
        <div class="restore-target-card">
            <strong>${escapeHtml(model.targetName)}</strong>
            <span>${escapeHtml(model.worldPath || "")}</span>
        </div>
        <div class="restore-meta-grid">
            <div><span>Backup</span><strong>${escapeHtml(backup.filename || filename)}</strong></div>
            <div><span>${t("Geändert")}</span><strong${timestampTitle ? ` title="${escapeHtml(timestampTitle)}"` : ""}>${escapeHtml(backupTimestamp(backupIsoTimestamp(backup), backup.modified) || t("unbekannt"))}</strong></div>
            <div><span>ZIP</span><strong>${escapeHtml(String(backup.size_mb ?? "?"))} MB</strong></div>
            <div><span>${t("Entpackt")}</span><strong>${escapeHtml(String(backup.uncompressed_mb ?? "?"))} MB</strong></div>
        </div>
        <div class="restore-checklist">
            ${checks.map(item => `<div class="restore-check ${item.ok ? "ok" : "warn"}"><span>${item.ok ? "✓" : "!"}</span>${escapeHtml(item.label)}</div>`).join("")}
        </div>
        <div class="restore-details">
            <div>${t("Einträge: {files} Dateien / {dirs} Ordner", { files: escapeHtml(String(backup.file_count ?? "?")), dirs: escapeHtml(String(backup.dir_count ?? "?")) })}</div>
            <div>${backup.levelname ? `levelname.txt: ${escapeHtml(backup.levelname)}` : `Top-Level: ${escapeHtml(model.topLevel)}`}</div>
            <div class="restore-warning-line">${t("Ungespeicherte UI-Änderungen werden verworfen. Vor dem Restore wird ein Sicherheitsbackup der aktuellen Welt erstellt.")}</div>
        </div>
    `;
    }

    window.MCBERestoreReview = {
        restoreReviewHtml,
        restoreReviewModel,
    };
}());
