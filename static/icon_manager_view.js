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

    function escapeAttr(value) {
        return escapeHtml(value);
    }

    function formatDe(value) {
        return window.MCBEI18n?.formatNumber?.(value || 0) || Number(value || 0).toLocaleString();
    }

    function iconManagerSummaryText(data = null, { version = "dev" } = {}) {
        const summary = data || {};
        const health = summary.health || {};
        const cache = summary.cache || {};
        const lines = [
            t("Icon-Manager"),
            `Version: ${version || "dev"}`,
            t("Strategie: lokale Extraktion, keine gebündelten Minecraft-Assets"),
            t("Icons erkannt: {count}", { count: summary.count || 0 }),
            t("Geprüfte Dateien: {count}", { count: summary.scanned_files || 0 }),
            `Cache: ${cache.state || t("unbekannt")} · ${cache.path || "-"}`,
            t("Health: {status} · Quellen {existing}/{enabled} · Preview {found}/{total}", { status: health.status || t("unbekannt"), existing: health.existing_sources || 0, enabled: health.enabled_sources || 0, found: health.sample_found || 0, total: health.sample_total || 0 }),
            `Settings: ${summary.settings_path || "-"}`,
        ];
        (health.sample || []).forEach(row => lines.push(`Preview: ${row.found ? "✓" : "-"} ${row.item_id}${row.source ? ` · ${row.source}` : ""}`));
        (summary.sources || []).forEach((src, idx) => {
            lines.push(`${idx + 1}. ${src.enabled ? t("aktiv") : t("aus")} · ${src.manual ? t("manuell") : src.env ? "env" : "auto"} · ${src.exists ? t("vorhanden") : t("fehlt")} · ${src.status || "ok"} · ${t("{count} Icons", { count: src.count || 0 })} · ${src.label || src.path}`);
            lines.push(`   ${src.path}`);
        });
        (summary.warnings || []).slice(0, 20).forEach(w => lines.push(t("Warnung: {text}", { text: w })));
        return lines.join("\n");
    }

    function sourceKind(src = {}) {
        if (src.manual) return t("Manuell");
        if (src.env) return t("Umgebung");
        if (src.world) return t("Welt");
        return t("Automatisch");
    }

    function sourceStatus(src = {}) {
        const sourceIconCount = Number(src.count || 0);
        if (!src.enabled) return t("aus");
        if (!src.exists) return t("Pfad fehlt");
        if (src.status === "warning") return t("{count} Icons · Warnung", { count: sourceIconCount });
        return sourceIconCount ? t("{count} Icons", { count: sourceIconCount }) : t("keine passenden Icons");
    }

    function iconManagerHtml(data = null, { itemEmoji = () => "", itemLabel = value => value } = {}) {
        const summary = data || {};
        const sources = summary.sources || [];
        const warnings = summary.warnings || [];
        const health = summary.health || {};
        const cache = summary.cache || {};
        const cacheLabel = cache.state === "hit" ? t("Cache genutzt") : cache.state === "rebuilt" ? t("Index neu aufgebaut") : t("Cache unbekannt");
        const enabledSourceCount = Number(health.enabled_sources || sources.filter(src => src.enabled !== false).length || 0);
        const healthLabel = Number(summary.count || 0) > 0 ? t("bereit") : (enabledSourceCount ? t("keine Treffer") : t("Fallback aktiv"));
        const sampleRows = (health.sample || []).map(row => `
        <div class="icon-preview-sample ${row.found ? "" : "muted"}" title="${escapeAttr(row.item_id || "")}">
            <div class="icon-preview-thumb">${row.found && row.url ? `<img src="${escapeAttr(row.url)}" alt="">` : `<span>${escapeHtml(itemEmoji(row.item_id) || "□")}</span>`}</div>
            <small>${escapeHtml(itemLabel(row.item_id || ""))}</small>
        </div>`).join("");
        const rows = sources.length ? sources.map(src => `<div class="icon-source-row ${src.enabled ? "" : "muted"}">
            <div class="icon-source-main">
                <strong>${escapeHtml(src.label || src.path || t("Icon-Quelle"))}</strong>
                <span>${escapeHtml(sourceKind(src))} · ${escapeHtml(sourceStatus(src))} · ${src.archive ? t("Archiv") : t("Ordner")}</span>
                <small>${escapeHtml(src.path || "")}</small>
            </div>
            <div class="icon-source-actions">
                ${src.manual ? `<button class="btn-text icon-source-move" type="button" data-path="${escapeAttr(src.path)}" data-direction="up" title="${t("Priorität erhöhen")}">${t("Hoch")}</button>
                <button class="btn-text icon-source-move" type="button" data-path="${escapeAttr(src.path)}" data-direction="down" title="${t("Priorität senken")}">${t("Runter")}</button>
                <button class="btn-text icon-source-toggle" type="button" data-path="${escapeAttr(src.path)}" data-enabled="${src.enabled ? "0" : "1"}">${src.enabled ? t("Deaktivieren") : t("Aktivieren")}</button>
                <button class="btn-text danger icon-source-remove" type="button" data-path="${escapeAttr(src.path)}">${t("Entfernen")}</button>` : `<span class="pill">${src.enabled ? t("aktiv") : t("aus")}</span>`}
            </div>
        </div>`).join("") : `<div class="no-backups">${t("Keine Icon-Quellen gefunden. Fallback-Symbole bleiben aktiv.")}</div>`;
        const warningHtml = warnings.length ? `<div class="diagnostic-warning-list"><strong>${t("Warnungen")}</strong>${warnings.slice(0, 6).map(w => `<div>${escapeHtml(w)}</div>`).join("")}</div>` : "";
        const hasExistingIconSources = sources.some(src => src.enabled !== false && src.exists);
        const setupTitle = hasExistingIconSources
            ? t("Quellen gefunden, aber keine passenden Item-/Block-Texturen.")
            : t("Keine Icon-Quelle eingerichtet.");
        const setupHtml = Number(summary.count || 0) === 0 ? `
        <div class="icon-setup-callout">
            <div>
                <strong>${escapeHtml(setupTitle)}</strong>
                <p>${t("Minecraft-Assets werden bewusst nicht mitgeliefert und es werden keine externen Bilder geladen. Wähle ein Resource Pack (.mcpack/.zip) oder einen Ordner mit textures/items bzw. textures/blocks; bis dahin nutzt die App Platzhalter.")}</p>
            </div>
            <button class="btn btn-secondary btn-sm" type="button" id="btnFocusIconSource">${t("Icon-Pfad eintragen")}</button>
        </div>` : "";
        return `
        ${setupHtml}
        <div class="icon-manager-status">
            <div><span>${t("Aktiver Icon-Index")}</span><strong>${t("{count} Icons", { count: formatDe(summary.count) })}</strong><small>${t("Lokale Quellen · keine externen Downloads")}</small></div>
            <div><span>${t("Asset-Status")}</span><strong>${escapeHtml(healthLabel)}</strong><small>${t("{existing} von {enabled} aktiven Quellen vorhanden", { existing: formatDe(health.existing_sources), enabled: formatDe(health.enabled_sources) })}</small></div>
            <div><span>Performance</span><strong>${escapeHtml(cacheLabel)}</strong><small>${t("{count} geprüfte Dateien", { count: formatDe(summary.scanned_files) })} · ${escapeHtml(cache.path || t("kein Cache"))}</small></div>
            <div><span>${t("Konfiguration")}</span><strong>${escapeHtml(summary.settings_path || t("lokal"))}</strong><small>${t("Gespeichert werden nur Pfade, keine Texturen")}</small></div>
        </div>
        <div class="icon-preview-panel">
            <div><strong>${t("Pack-Vorschau")}</strong><small>${t("{found} von {total} typischen Items gefunden", { found: formatDe(health.sample_found), total: formatDe(health.sample_total) })}</small></div>
            <div class="icon-preview-grid">${sampleRows || `<span class="hint-text">${t("Noch keine Vorschau verfügbar.")}</span>`}</div>
        </div>
        ${rows}
        ${warningHtml}
        <div class="inline-actions icon-manager-footer">
            <button id="btnCopyIconDiagnostics" class="btn btn-secondary btn-sm" type="button">${t("Icon-Diagnose kopieren")}</button>
        </div>
    `;
    }

    window.MCBEIconManagerView = {
        iconManagerSummaryText,
        iconManagerHtml,
    };
}());
