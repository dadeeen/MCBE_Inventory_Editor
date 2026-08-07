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

    function readJson(storage, key, fallback) {
        try {
            return JSON.parse(storage.getItem(key) || JSON.stringify(fallback));
        } catch (_e) {
            return fallback;
        }
    }

    function writeJson(storage, key, value) {
        try {
            storage.setItem(key, JSON.stringify(value));
        } catch (_e) {}
    }

    function migrateBrowserStorage({ localStorage, sessionStorage, keys, currentSchema }) {
        try {
            const previousSchema = localStorage.getItem(keys.storageSchema);
            if (previousSchema !== currentSchema) {
                localStorage.removeItem(keys.recentWorlds);
                try { sessionStorage.removeItem(keys.sessionRecentWorlds); } catch (_e) {}
                localStorage.removeItem(keys.workspace);
                if (!localStorage.getItem(keys.theme) || localStorage.getItem(keys.theme) === "system") {
                    localStorage.setItem(keys.theme, "dark");
                }
                localStorage.setItem(keys.storageSchema, currentSchema);
            }
        } catch (_e) {}
    }

    function loadWorkspace(storage, key) {
        return readJson(storage, key, {});
    }

    function saveWorkspace(storage, key, current, patch = {}) {
        const next = {
            ...current,
            ...patch,
            updated_at: Date.now(),
        };
        writeJson(storage, key, next);
        return next;
    }

    function loadFavoriteWorlds(storage, key) {
        return readJson(storage, key, []);
    }

    function saveFavoriteWorlds(storage, key, worlds) {
        writeJson(storage, key, worlds.slice(0, 20));
    }

    function toggleFavoriteWorld(worlds, path, name) {
        if (!path) {
            return { worlds, changed: false, added: false };
        }
        const next = worlds.slice();
        const idx = next.findIndex(w => w.path === path);
        if (idx >= 0) {
            next.splice(idx, 1);
            return { worlds: next, changed: true, added: false };
        }
        next.unshift({ path, name: name || t("Welt"), date: Date.now() });
        return { worlds: next, changed: true, added: true };
    }

    function workspaceSummaryText({ workspace = {}, favorites = [], version = "dev", mode = "unknown", theme = "dark", showSlotNumbers = false } = {}) {
        const lines = [
            t("Arbeitsbereich"),
            `Version: ${version || "dev"}`,
            t("Modus: {mode}", { mode: mode || "unknown" }),
            t("Darstellung: {theme}", { theme }),
            t("Letzte Welt: {name}", { name: workspace.world_name || "-" }),
            t("Letzter Spieler: {name}", { name: workspace.player_label || "-" }),
            t("Slotnummern: {state}", { state: showSlotNumbers ? t("an") : t("aus") }),
            t("Favoriten: {count}", { count: favorites.length }),
        ];
        favorites.slice(0, 8).forEach((w, i) => lines.push(`${i + 1}. ${w.name || t("Welt")} — ${w.path}`));
        return lines.join("\n");
    }

    function workspacePanelHtml({ workspace = {}, favorites = [], theme = "dark", showSlotNumbers = false } = {}) {
        const hasWorkspace = Boolean(workspace.world_path || workspace.player_key || favorites.length);
        if (!hasWorkspace) {
            return `<div class="no-backups">${t("Noch kein Arbeitsbereich gespeichert.")}</div>`;
        }
        const last = workspace.updated_at ? (window.MCBEI18n?.formatDate?.(workspace.updated_at) || new Date(workspace.updated_at).toLocaleString()) : "-";
        const favoriteRows = favorites.length ? favorites.map(w => `
        <button class="workspace-favorite" type="button" data-world-path="${escapeHtml(w.path)}" data-world-name="${escapeHtml(w.name || t("Favorit"))}">
            <strong>${escapeHtml(w.name || t("Favorit"))}</strong>
            <span>${escapeHtml(w.path)}</span>
        </button>`).join("") : `<div class="no-backups compact">${t("Noch keine Favoriten.")}</div>`;
        return `
        <div class="workspace-current">
            <div><span>${t("Letzte Welt")}</span><strong>${escapeHtml(workspace.world_name || "-")}</strong><small>${escapeHtml(workspace.world_path || "-")}</small></div>
            <div><span>${t("Letzter Spieler")}</span><strong>${escapeHtml(workspace.player_label || "-")}</strong><small>${t("Aktualisiert: {time}", { time: escapeHtml(last) })}</small></div>
            <div><span>${t("Darstellung")}</span><strong>${escapeHtml(theme)}</strong><small>${showSlotNumbers ? t("Slotnummern an") : t("Slotnummern aus")}</small></div>
        </div>
        <div class="workspace-favorites"><h4>${t("Favorisierte Welten")}</h4>${favoriteRows}</div>
    `;
    }



    function createWorkspaceController(deps = {}) {
        const {
            localStorage,
            sessionStorage,
            keys = {},
            currentSchema = "",
            appConfig = {},
            getTheme = () => "dark",
            getShowSlotNumbers = () => false,
            getEnderCollapsed = () => false,
            getWorkspacePanel = () => null,
            onFavoriteSelected = () => {},
            showToast = () => {},
            applyTheme = theme => theme,
            copyTextToClipboard = () => {},
            getSelectedWorld = () => null,
            getWorldPath = () => "",
            renderRecentWorlds = () => {},
            openWorkspaceDashboard = () => {},
        } = deps;

        function migrate() {
            return migrateBrowserStorage({ localStorage, sessionStorage, keys, currentSchema });
        }

        function loadCurrentWorkspace() {
            return loadWorkspace(localStorage, keys.workspace);
        }

        function loadCurrentFavoriteWorlds() {
            return loadFavoriteWorlds(localStorage, keys.favoriteWorlds);
        }

        function saveCurrentFavoriteWorlds(worlds) {
            return saveFavoriteWorlds(localStorage, keys.favoriteWorlds, worlds);
        }

        function saveCurrentWorkspace(patch = {}) {
            const next = saveWorkspace(localStorage, keys.workspace, loadCurrentWorkspace(), {
                ...patch,
                slot_numbers: getShowSlotNumbers(),
                ender_collapsed: getEnderCollapsed(),
                theme: getTheme(),
            });
            renderPanel();
            return next;
        }

        function toggleFavorite(path, name) {
            if (!path) { showToast(t("Keine Welt ausgewählt."), "warning"); return; }
            const result = toggleFavoriteWorld(loadCurrentFavoriteWorlds(), path, name);
            if (!result.changed) return;
            showToast(result.added ? t("Welt als Favorit gespeichert.") : t("Favorit entfernt."), "success");
            saveCurrentFavoriteWorlds(result.worlds);
            renderPanel();
        }

        function summaryText() {
            return workspaceSummaryText({
                workspace: loadCurrentWorkspace(),
                favorites: loadCurrentFavoriteWorlds(),
                version: appConfig?.distribution?.project_version || "dev",
                mode: appConfig?.mode || "unknown",
                theme: getTheme(),
                showSlotNumbers: getShowSlotNumbers(),
            });
        }

        function renderPanel() {
            const workspacePanel = getWorkspacePanel();
            if (!workspacePanel) return;
            workspacePanel.innerHTML = workspacePanelHtml({
                workspace: loadCurrentWorkspace(),
                favorites: loadCurrentFavoriteWorlds(),
                theme: getTheme(),
                showSlotNumbers: getShowSlotNumbers(),
            });
            workspacePanel.querySelectorAll(".workspace-favorite").forEach(btn => {
                btn.addEventListener("click", () => onFavoriteSelected({
                    path: btn.dataset.worldPath,
                    name: btn.dataset.worldName || t("Favorit"),
                    folder: btn.dataset.worldPath,
                    source_label: t("Favorit"),
                }));
            });
        }

        async function clearWorkspaceData(confirm = async () => true) {
            const ok = await confirm(t("Lokalen Arbeitsbereich, Favoriten und letzte Welten zurücksetzen? Weltdaten werden nicht verändert."));
            if (!ok) return false;
            try {
                localStorage.removeItem(keys.workspace);
                localStorage.removeItem(keys.favoriteWorlds);
                localStorage.removeItem(keys.recentWorlds);
                try { sessionStorage.removeItem(keys.sessionRecentWorlds); } catch (_e) {}
            } catch (_e) {}
            renderPanel();
            renderRecentWorlds();
            showToast(t("Arbeitsbereich zurückgesetzt."), "success");
            return true;
        }

        function wireActions({
            doc = document,
            themeSelect = null,
            favoriteButton = null,
            copyButton = null,
            clearButton = null,
            confirmClear = async () => true,
        } = {}) {
            applyTheme(getTheme());
            themeSelect?.addEventListener("change", () => {
                const theme = applyTheme(themeSelect.value);
                saveCurrentWorkspace({ theme });
                showToast(t("Darstellung: {theme}", { theme: themeSelect.options[themeSelect.selectedIndex]?.text || theme }), "success");
            });
            favoriteButton?.addEventListener("click", () => {
                const selectedWorld = getSelectedWorld();
                const path = selectedWorld?.path || getWorldPath();
                const name = selectedWorld?.name || selectedWorld?.folder || getWorldPath() || t("Welt");
                toggleFavorite(path, name);
            });
            copyButton?.addEventListener("click", () => {
                copyTextToClipboard(summaryText(), t("Arbeitsbereich kopiert."));
            });
            clearButton?.addEventListener("click", () => clearWorkspaceData(confirmClear));
            doc.addEventListener("keydown", event => {
                if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "p") {
                    event.preventDefault();
                    openWorkspaceDashboard();
                    showToast(t("Arbeitsbereich geöffnet."), "success", 1800);
                }
            });
        }

        return {
            loadFavoriteWorlds: loadCurrentFavoriteWorlds,
            loadWorkspace: loadCurrentWorkspace,
            migrateBrowserStorage: migrate,
            clearWorkspaceData,
            renderWorkspacePanel: renderPanel,
            saveFavoriteWorlds: saveCurrentFavoriteWorlds,
            saveWorkspace: saveCurrentWorkspace,
            toggleFavoriteWorld: toggleFavorite,
            wireActions,
            workspaceSummaryText: summaryText,
        };
    }


    function createInventoryWorkspaceController({
        doc = document,
        localStorage = window.localStorage,
        sessionStorage = window.sessionStorage,
        keys = {},
        currentSchema = "",
        appConfig = {},
        getTheme = () => "dark",
        getShowSlotNumbers = () => false,
        getEnderCollapsed = () => false,
        onFavoriteSelected = () => {},
        showToast = () => {},
        applyTheme = theme => theme,
        copyTextToClipboard = () => {},
        getSelectedWorld = () => null,
        getWorldPath = () => "",
        renderRecentWorlds = () => {},
        getWorkspacePanel = () => doc.getElementById("workspacePanel"),
        openWorkspaceDashboard = () => doc.querySelector('[data-tab-dash="dashWorkspace"]')?.click(),
    } = {}) {
        return createWorkspaceController({
            localStorage,
            sessionStorage,
            keys,
            currentSchema,
            appConfig,
            getTheme,
            getShowSlotNumbers,
            getEnderCollapsed,
            getWorkspacePanel,
            onFavoriteSelected,
            showToast,
            applyTheme,
            copyTextToClipboard,
            getSelectedWorld,
            getWorldPath,
            renderRecentWorlds,
            openWorkspaceDashboard,
        });
    }

    window.MCBEWorkspaceView = {
        migrateBrowserStorage,
        loadWorkspace,
        saveWorkspace,
        loadFavoriteWorlds,
        saveFavoriteWorlds,
        toggleFavoriteWorld,
        workspaceSummaryText,
        workspacePanelHtml,
        createWorkspaceController,
        createInventoryWorkspaceController,
    };
}());
