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

    function scanRootKindLabel(kind) {
        return {
            configured: t("Konfiguriert"),
            "configured-root": t("Konfigurierter Welt-Root"),
            "docker-root": t("Docker-Weltenordner"),
            "minecraft-default": t("Minecraft-Standardordner"),
            "user-root": t("Eigener Suchort"),
            "manual-root": t("Manueller Suchbereich"),
            manual_world: t("Manuell geladene Welt"),
            default_candidate: t("Standardordner"),
            minecraft_worlds: "MinecraftWorlds",
            worlds: t("Worlds-Ordner"),
        }[kind] || t("Suchbereich");
    }

    function scanPathRowHtml(root = {}) {
        const path = root.path || "";
        const enabled = root.enabled !== false;
        const removable = root.removable === true;
        const kind = scanRootKindLabel(root.kind);
        const customLabel = root.kind === "user-root" && root.label && root.label !== "Eigener Suchort" ? root.label : "";
        const detail = customLabel ? `${kind} · ${customLabel}` : kind;
        return `<div class="scan-path-row" style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:5px 0;opacity:${enabled ? "1" : "0.55"};">
            <label style="display:flex;gap:7px;align-items:flex-start;min-width:0;flex:1;font-size:0.85rem;">
                <input type="checkbox" data-scan-path-toggle data-path="${escapeHtml(path)}" ${enabled ? "checked" : ""} ${removable ? "" : "disabled"} title="${removable ? t("Suchbereich aktivieren/deaktivieren") : t("Dieser Suchbereich ist immer aktiv")}">
                <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;">📁 ${escapeHtml(path)}<br><span style="font-size:0.72rem;color:var(--text-secondary);">${escapeHtml(detail)}</span></span>
            </label>
            ${removable ? `<button class="btn-text remove-scan-path" type="button" data-scan-path-remove data-path="${escapeHtml(path)}" title="${t("Entfernen")}">✕</button>` : ""}
        </div>`;
    }

    function scanPathsHtml(data = {}) {
        const roots = Array.isArray(data.scan_roots) ? data.scan_roots : [];
        const body = roots.length
            ? roots.map(scanPathRowHtml).join("")
            : `<div style="font-size:0.85rem;color:var(--text-secondary);padding:8px 0;">${t("Keine Suchbereiche konfiguriert. Füge einen direkten Weltordner oder einen Sammelordner hinzu, oder lade eine Welt manuell.")}</div>`;
        const settings = data.settings_path
            ? `<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:6px;line-height:1.35;">${t("Gespeichert in: {path}", { path: escapeHtml(data.settings_path) })}</div>`
            : "";
        return body + settings;
    }

    window.MCBEScanPathsView = {
        scanRootKindLabel,
        scanPathsHtml,
    };
}());
