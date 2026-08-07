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

    function worldCountText({ visibleCount = 0, allCount = 0, query = "" } = {}) {
        if (query) return t("{visible} von {all} Welten sichtbar", { visible: visibleCount, all: allCount });
        return allCount === 1 ? t("1 Welt gefunden") : t("{count} Welten gefunden", { count: allCount });
    }

    function emptyWorldsHtml(query = "") {
        return query
            ? `<strong>${t("Keine Treffer für „{query}“", { query: escapeHtml(query) })}</strong><span>${t("Suche nach Weltname, Ordner, Quelle oder Pfad. Entferne den Filter, um alle Welten zu sehen.")}</span>`
            : `<strong>${t("Keine Welten automatisch gefunden")}</strong>`
                + `<span>${t("Liegt deine Welt an einem eigenen Ort (verschoben, NAS, OneDrive, Serverkopie)? Dann füge den Ordner als Suchbereich hinzu.")}</span>`
                + `<button type="button" class="btn btn-primary btn-sm" data-open-scan-paths>${t("Eigenen Ort hinzufügen")}</button>`;
    }

    function worldSearchStatusHtml(title, message) {
        return `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
    }

    function worldCardsHtml(worlds = [], {
        selectedPath = "",
        dirtyWorldPath = "",
        isDirty = false,
        sourceLabelForWorld = () => t("Suchergebnis"),
        formatModified = () => t("unbekannt"),
    } = {}) {
        const groups = new Map();
        worlds.forEach(world => {
            const key = sourceLabelForWorld(world);
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(world);
        });

        return Array.from(groups.entries()).map(([source, groupWorlds]) => {
            const cards = groupWorlds.map(world => {
                const isSelected = selectedPath === world.path;
                const hasUnsavedChanges = Boolean(isDirty && dirtyWorldPath && world.path === dirtyWorldPath);
                return `<button class="world-card${isSelected ? " selected" : ""}" type="button" data-world-path="${escapeHtml(world.path || "")}" title="${escapeHtml(world.path || "")}">
                <span class="world-card-main">
                    <strong>${escapeHtml(world.name || t("Unbenannte Welt"))}</strong>
                    <small>${escapeHtml(sourceLabelForWorld(world))} · ${escapeHtml(formatModified(world))}</small>
                    <code>${escapeHtml(world.folder || world.path || "")}</code>
                </span>
                <span class="world-card-badges">
                    <span class="world-card-action">${isSelected ? t("Ausgewählt") : t("Auswählen")}</span>
                    ${hasUnsavedChanges ? `<span class="world-card-dirty">${t("Ungespeichert")}</span>` : ""}
                </span>
            </button>`;
            }).join("");
            return `<section class="world-source-group">
                <div class="world-source-title">${escapeHtml(source)} · ${groupWorlds.length === 1 ? t("1 Welt") : t("{count} Welten", { count: groupWorlds.length })}</div>
                ${cards}
            </section>`;
        }).join("");
    }

    function worldDiagnosticsHtml(scanData = {}, scanRootKindLabel = () => t("Suchbereich")) {
        const roots = Array.isArray(scanData.scan_roots) ? scanData.scan_roots : [];
        if (!roots.length) return "";
        const total = Array.isArray(scanData.worlds) ? scanData.worlds.length : 0;
        const issues = roots.filter(root => !["ok", "missing", "disabled"].includes(root.status)).length;
        const rows = roots.map(root => {
            const ok = root.status === "ok" && root.world_count > 0;
            const muted = root.status === "disabled" || root.status === "missing" || (root.status === "ok" && !root.world_count);
            const icon = ok ? "✓" : (muted ? "·" : "!");
            const cls = ok ? "ok" : (muted ? "muted" : "warn");
            const label = root.kind === "user-root" && root.label && root.label !== "Eigener Suchort"
                ? root.label
                : scanRootKindLabel(root.kind);
            const rootCount = root.world_count || 0;
            const rootCountText = rootCount === 1 ? t("1 Welt") : t("{count} Welten", { count: rootCount });
            const detail = `${rootCountText} · ${root.message || root.status || t("geprüft")}`;
            return `<div class="diagnostic-row ${cls}"><span>${icon}</span><div><strong>${escapeHtml(label)}</strong><small>${escapeHtml(detail)}</small><code>${escapeHtml(root.path || "")}</code></div></div>`;
        }).join("");
        const issueText = issues ? ` · ${issues === 1 ? t("1 Hinweis") : t("{count} Hinweise", { count: issues })}` : "";
        const totalText = total === 1 ? t("1 Welt") : t("{count} Welten", { count: total });
        return `<div class="diagnostic-title">${t("Automatische Suche: {worlds} gefunden · {dirs} Ordner geprüft{issues}", { worlds: totalText, dirs: scanData.checked_dirs || 0, issues: issueText })}</div>${rows}`;
    }

    function applyWorldCardsRender({ worldList, emptyEl, worldCountHint } = {}, worlds = [], {
        allCount = worlds.length,
        query = "",
        selectedPath = "",
        dirtyWorldPath = "",
        isDirty = false,
        sourceLabelForWorld = () => t("Suchergebnis"),
        formatModified = () => t("unbekannt"),
    } = {}) {
        if (!worldList) return false;
        worldList.innerHTML = "";
        if (worldCountHint) worldCountHint.textContent = worldCountText({ visibleCount: worlds.length, allCount, query });
        if (!worlds.length) {
            if (emptyEl) {
                emptyEl.innerHTML = emptyWorldsHtml(query);
                emptyEl.style.display = "flex";
                emptyEl.querySelector?.("[data-open-scan-paths]")?.addEventListener("click", () => {
                    const doc = emptyEl.ownerDocument || document;
                    doc.getElementById("btnScanPaths")?.click();
                });
            }
            return true;
        }
        if (emptyEl) emptyEl.style.display = "none";
        worldList.innerHTML = worldCardsHtml(worlds, {
            selectedPath,
            dirtyWorldPath,
            isDirty,
            sourceLabelForWorld,
            formatModified,
        });
        return true;
    }

    function applyWorldDiagnostics(worldDiagnostics, scanData = {}, scanRootKindLabel = () => t("Suchbereich")) {
        if (!worldDiagnostics) return false;
        const roots = Array.isArray(scanData?.scan_roots) ? scanData.scan_roots : [];
        if (!roots.length) {
            worldDiagnostics.style.display = "none";
            worldDiagnostics.innerHTML = "";
            return true;
        }
        const wasExpanded = worldDiagnostics.classList.contains("expanded");
        worldDiagnostics.innerHTML = worldDiagnosticsHtml(scanData, scanRootKindLabel);
        worldDiagnostics.classList.toggle("expanded", wasExpanded);
        worldDiagnostics.classList.toggle("collapsed", !wasExpanded);
        worldDiagnostics.style.display = "block";
        return true;
    }

    window.MCBEWorldCardsView = {
        applyWorldCardsRender,
        applyWorldDiagnostics,
        worldCountText,
        emptyWorldsHtml,
        worldSearchStatusHtml,
        worldCardsHtml,
        worldDiagnosticsHtml,
    };
}());
