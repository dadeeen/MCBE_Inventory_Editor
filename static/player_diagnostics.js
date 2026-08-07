(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function scanRootKindLabel(kind) {
        if (kind === "docker-root") return t("Docker-Mount (immer aktiv)");
        if (kind === "minecraft-default") return t("Minecraft-Standard (immer aktiv)");
        if (kind === "configured-root") return t("Konfigurierter Root (immer aktiv)");
        return t("Suchbereich");
    }

    function buildPlayersDiagnosticsText({ players = [], worldName = "-", worldPath = "-", selectedWorld = null } = {}) {
        const lines = [];
        lines.push(t("Spieler-Diagnose:"));
        lines.push(t("Geladene Welt: {world}", { world: worldName || selectedWorld?.name || "-" }));
        lines.push(t("Weltpfad: {path}", { path: worldPath || selectedWorld?.path || "-" }));
        lines.push(t("Spieler-Datensätze: {count}", { count: Array.isArray(players) ? players.length : 0 }));
        (players || []).forEach((player, idx) => {
            const dbg = player.debug || {};
            lines.push(`${idx + 1}. ${player.label || t("Unbekannt")}`);
            lines.push(`   kind=${player.kind || "?"} confidence=${player.confidence || "?"} editable=${player.editable === true} exportable=${player.exportable === true}`);
            lines.push(`   reason_code=${player.reason_code || "-"}`);
            lines.push(`   reason=${player.reason || "-"}`);
            lines.push(`   inventory: has_tag=${player.has_inventory_tag === true} list=${player.has_inventory === true} opaque=${player.inventory_opaque === true} create_requires_confirmation=${player.inventory_create_requires_confirmation === true}`);
            lines.push(`   ender_chest: has_tag=${player.has_ender_chest_tag === true} list=${player.has_ender_chest === true} opaque=${player.ender_chest_opaque === true}`);
            if (dbg.key_b64 || dbg.key_hex || dbg.raw_length != null) {
                lines.push(`   key_b64=${dbg.key_b64 || player.player_key || "-"}`);
                lines.push(`   key_hex=${dbg.key_hex || "-"}`);
                lines.push(`   raw_length=${dbg.raw_length ?? "?"} first_bytes=${dbg.first_bytes_hex || "-"} starts_like_named_compound=${dbg.starts_like_named_compound === true}`);
            }
            if (dbg.parse_error) lines.push(`   parse_error=${dbg.parse_error}`);
            if (Array.isArray(dbg.tag_names)) lines.push(`   tags=${dbg.tag_names.join(", ") || "-"}`);
            if (dbg.tag_types && typeof dbg.tag_types === "object") {
                const types = Object.entries(dbg.tag_types).map(([k, v]) => `${k}:${v}`).join(", ");
                if (types) lines.push(`   tag_types=${types}`);
            }
        });
        return lines.join("\n");
    }

    function buildWorldDiagnosticsText({ appConfig = {}, scan = {}, selectedWorld = null, players = [], worldName = "-", worldPath = "-" } = {}) {
        const lines = [];
        lines.push(t("MCBE Inventory Editor Diagnose"));
        lines.push(`Version: ${appConfig?.distribution?.project_version || "dev"}`);
        lines.push(t("Modus: {mode}", { mode: appConfig?.mode || t("unbekannt") }));
        lines.push(t("Gefundene Welten: {count}", { count: Array.isArray(scan.worlds) ? scan.worlds.length : 0 }));
        lines.push(t("Geprüfte Ordner: {count}", { count: scan.checked_dirs || 0 }));
        if (scan.truncated) lines.push(t("Hinweis: Suche wurde begrenzt/abgebrochen."));
        if (Array.isArray(scan.warnings) && scan.warnings.length) {
            lines.push(t("Warnungen:"));
            scan.warnings.forEach(w => lines.push(`- ${w}`));
        }
        if (Array.isArray(scan.scan_roots)) {
            lines.push(t("Suchbereiche:"));
            scan.scan_roots.forEach(root => {
                const label = root.kind === "user-root" && root.label && root.label !== "Eigener Suchort"
                    ? root.label
                    : scanRootKindLabel(root.kind);
                lines.push(`- ${label} | ${root.status} | ${t("{count} Welten", { count: root.world_count || 0 })} | ${root.path}`);
            });
        }
        if (selectedWorld?.path) lines.push(t("Ausgewählte Welt: {name} | {path}", { name: selectedWorld.name || "", path: selectedWorld.path }));
        if (Array.isArray(players) && players.length) {
            lines.push("");
            lines.push(buildPlayersDiagnosticsText({ players, worldName, worldPath, selectedWorld }));
        }
        return lines.join("\n");
    }

    window.MCBEPlayerDiagnostics = {
        buildPlayersDiagnosticsText,
        buildWorldDiagnosticsText,
        scanRootKindLabel,
    };
}());
