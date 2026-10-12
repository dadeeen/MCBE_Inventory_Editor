(function () {
    "use strict";

    // Only layout and DOM placement are changed. The moved player list keeps
    // its original handlers; equipment always stays beside the inventory.
    function createFocusWorkspaceController({ doc = document, win = window, observerFactory = callback => new MutationObserver(callback) } = {}) {
        const byId = id => doc.getElementById(id);
        const root = doc.documentElement;
        const body = doc.body;
        const originalPositions = new Map();
        let wired = false;

        function remember(node) {
            if (node && !originalPositions.has(node)) {
                originalPositions.set(node, { parent: node.parentNode, next: node.nextSibling });
            }
        }

        function move(node, target, before = null) {
            if (!node || !target || node.parentNode === target) return;
            remember(node);
            target.insertBefore(node, before);
        }

        function restore(node) {
            const origin = originalPositions.get(node);
            if (!origin || !node || node.parentNode === origin.parent) return;
            origin.parent.insertBefore(node, origin.next?.parentNode === origin.parent ? origin.next : null);
        }

        function inventoryIsFocused() {
            return root.dataset.layout === "focus" && body.dataset.workflowView === "inventory"
                && body.classList.contains("app-player-loaded");
        }

        function filterPlayers() {
            const query = inventoryIsFocused() ? String(byId("focusPlayerSearch")?.value || "").trim().toLocaleLowerCase() : "";
            let visiblePlayers = 0;
            byId("playersList")?.querySelectorAll(".player-row").forEach(row => {
                const name = row.querySelector(".player-name")?.textContent || "";
                const matches = name.toLocaleLowerCase().includes(query);
                row.style.display = matches ? "" : "none";
                if (matches) visiblePlayers++;
            });
            const empty = byId("focusPlayerSearchEmpty");
            if (empty) empty.hidden = !query || visiblePlayers > 0;
        }

        function fieldValue(id) {
            return byId(id)?.value?.trim?.() || "";
        }

        function readableNumber(id) {
            const raw = fieldValue(id);
            return raw && Number.isFinite(Number(raw)) ? raw : "—";
        }

        function updateFacts() {
            const hasPlayer = body.classList.contains("app-player-loaded");
            const display = (id, value) => {
                const el = byId(id);
                if (el) el.textContent = hasPlayer && value ? value : "—";
            };
            const position = ["statPosX", "statPosY", "statPosZ"].map(readableNumber);
            const dimension = byId("statDimensionId");
            const dim = dimension?.selectedOptions?.[0];
            const dimLabel = dim && !dim.disabled ? dim.textContent.trim() : "—";
            const name = byId("playerSummaryName")?.textContent?.trim();
            display("focusSummaryPlayerName", name);
            const gamemode = byId("statGamemode");
            display("focusFactMode", gamemode?.dataset?.summaryLabel || fieldValue("statGamemode"));
            const modeFact = byId("focusFactMode");
            if (modeFact) modeFact.title = hasPlayer ? gamemode?.dataset?.summaryTitle || fieldValue("statGamemode") : "";
            display("focusFactPosition", position.every(value => value !== "—") ? position.join(", ") : "—");
            display("focusFactDimension", dimLabel);
            display("focusVitalXp", readableNumber("statXpLevel"));
            display("focusVitalHealth", readableNumber("statHealth"));
            display("focusVitalFood", readableNumber("statFoodLevel"));
        }

        function updateFocusStatusLabels() {
            // Never replace the underlying status text/ARIA information: this
            // is a short, visual label; clicking reveals the full live log.
            const server = byId("serverStatusBadge");
            const status = byId("statusStackButton");
            if (!server?.dataset || !status?.dataset) return;
            const english = byId("languageSelect")?.value === "en";
            const local = (de, en) => english ? en : de;
            const is = name => Boolean(server.classList?.contains?.(name));
            const serverText = String(server.textContent || "").toLowerCase();
            let serverLabel;
            if (is("status-check-failed")) serverLabel = local("Prüfung fehlgeschlagen", "Check failed");
            else if (is("blocked")) serverLabel = local("Schreiben gesperrt", "Writes blocked");
            else if (/wird geprüft|checking/.test(serverText)) serverLabel = local("Serverstatus wird geprüft", "Checking server");
            else if (is("online")) serverLabel = local("Server online", "Server online");
            else if (is("offline")) serverLabel = local("Server offline", "Server offline");
            else serverLabel = local("Server ungeprüft", "Server unverified");
            if (server.dataset.focusLabel !== serverLabel) server.dataset.focusLabel = serverLabel;
            const isFocus = root.dataset.layout === "focus";
            if (isFocus) {
                server.setAttribute("role", "button");
                server.setAttribute("tabindex", "0");
                server.setAttribute("aria-controls", "focusServerStatusPanel");
                if (!server.hasAttribute?.("aria-expanded")) server.setAttribute("aria-expanded", "false");
            } else {
                for (const name of ["role", "tabindex", "aria-controls", "aria-expanded"]) server.removeAttribute?.(name);
            }
            const text = byId("focusServerStatusText");
            const hint = byId("focusServerStatusHint");
            if (text) text.textContent = server.textContent?.trim() || "";
            if (hint) {
                hint.textContent = server.title || "";
                hint.hidden = !server.title;
            }

            const severity = ["error", "warning", "running", "success"].find(name => status.classList?.contains?.(name)) || "info";
            const summary = String(byId("statusStackSummary")?.textContent || "").toLowerCase();
            let statusLabel;
            if (severity === "error") statusLabel = local("Fehler", "Error");
            else if (severity === "warning") statusLabel = local("Hinweise", "Notices");
            else if (severity === "running") statusLabel = local("Vorgang läuft", "In progress");
            else if (severity === "success") statusLabel = local("Erfolgreich", "Success");
            else if (/(weltsuche|world scan|world search)/.test(summary) && /(läuft|running|searching)/.test(summary)) {
                statusLabel = local("Weltsuche läuft", "Searching worlds");
            } else if (/(bereit|ready|keine hinweise|no notices)/.test(summary)) statusLabel = local("Bereit", "Ready");
            else statusLabel = local("Status", "Status");
            if (status.dataset.focusLabel !== statusLabel) status.dataset.focusLabel = statusLabel;
        }

        function sync() {
            const focus = root.dataset.layout === "focus";
            const focusedInventory = inventoryIsFocused();
            // Capture all original positions BEFORE moving anything, including
            // adjacent nodes. Otherwise restoring could silently reorder them.
            const saveArea = byId("layoutSaveAction")?.closest(".layout-context-action");
            const playerList = byId("playersList");
            // Preserve live world-state warnings even though the redundant
            // loaded-world card is hidden. Dirty edits are already reported by
            // the existing safe-edit banner and the header save-status control.
            const warnings = [byId("loadErrorPanel"), byId("worldPresenceBanner")];
            // All original header positions must be remembered before moving
            // ANY sibling, otherwise a round-trip could reorder Studio/Classic.
            const headerStatus = doc.querySelector(".app-header .header-status-area");
            const headerActions = doc.querySelector(".app-header .header-actions");
            const history = doc.querySelector(".app-header .undo-redo-btns");
            [headerStatus, headerActions, history, saveArea, playerList, ...warnings].forEach(remember);

            // Dock the *existing* status, history, review action and settings.
            // Neither save semantics nor the undo stack are reimplemented.
            if (focus) {
                move(headerStatus, byId("focusInlineStatus"));
                move(history, byId("focusHistoryMount"));
                move(saveArea, byId("focusSaveMount"));
                move(headerActions, byId("focusSettingsMount"));
            } else {
                // Restore siblings in reverse original order, maintaining the
                // old header layout and tab order exactly on every switch.
                restore(history);
                restore(headerActions);
                restore(headerStatus);
                restore(saveArea);
                closeSettings();
                closeServerDetails();
            }
            if (focusedInventory) {
                move(playerList, byId("focusPlayerListMount"));
            } else {
                restore(playerList);
            }
            // Player data hides the world column too. Keep the original live
            // notices before the active editor, including across view switches.
            const warningHost = focusedInventory ? byId("inventoryContainer")
                : focus && body.dataset.workflowView === "player-edit" ? byId("dashboardPanel") : null;
            if (warningHost) {
                const firstContent = warningHost.querySelector(focusedInventory ? ".inventory-section" : ".dashboard-section");
                for (const warning of warnings) move(warning, warningHost, firstContent);
            } else {
                // Restore in reverse sibling order: each original nextSibling
                // is then back in place before its preceding warning moves.
                for (const warning of [...warnings].reverse()) restore(warning);
            }

            filterPlayers();
            updateFacts();
            updateFocusStatusLabels();
        }

        function closeServerDetails({ restoreFocus = false } = {}) {
            const panel = byId("focusServerStatusPanel");
            const badge = byId("serverStatusBadge");
            if (!panel || panel.hidden) return;
            panel.hidden = true;
            badge?.setAttribute("aria-expanded", "false");
            if (restoreFocus) badge?.focus?.();
        }

        function closeSettings({ restoreFocus = false } = {}) {
            const panel = byId("focusSettingsPanel");
            const toggle = byId("focusSettingsToggle");
            if (!panel || panel.hidden) return;
            panel.hidden = true;
            toggle?.setAttribute("aria-expanded", "false");
            if (restoreFocus) toggle?.focus?.();
        }

        function wire() {
            if (wired) return;
            wired = true;
            const settingsToggle = byId("focusSettingsToggle");
            const settingsPanel = byId("focusSettingsPanel");
            settingsToggle?.addEventListener("click", () => {
                if (!settingsPanel) return;
                closeServerDetails();
                const willOpen = settingsPanel.hidden;
                settingsPanel.hidden = !willOpen;
                settingsToggle.setAttribute("aria-expanded", String(willOpen));
            });
            const serverBadge = byId("serverStatusBadge");
            const serverPanel = byId("focusServerStatusPanel");
            serverBadge?.addEventListener("click", () => {
                if (root.dataset.layout !== "focus" || !serverPanel) return;
                closeSettings();
                const willOpen = serverPanel.hidden;
                serverPanel.hidden = !willOpen;
                serverBadge.setAttribute("aria-expanded", String(willOpen));
            });
            serverBadge?.addEventListener("keydown", event => {
                if (root.dataset.layout !== "focus") return;
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    serverBadge.click();
                }
            });
            doc.addEventListener("click", event => {
                if (settingsPanel && !settingsPanel.hidden && !byId("focusSettingsMenu")?.contains?.(event.target)) closeSettings();
                if (serverPanel && !serverPanel.hidden && !serverBadge?.contains?.(event.target) && !serverPanel.contains?.(event.target)) closeServerDetails();
            });
            doc.addEventListener("keydown", event => {
                if (event.key !== "Escape") return;
                if (!settingsPanel?.hidden) closeSettings({ restoreFocus: true });
                if (!serverPanel?.hidden) closeServerDetails({ restoreFocus: true });
            });
            const input = byId("focusPlayerSearch");
            input?.addEventListener("input", filterPlayers);
            byId("focusRefreshPlayers")?.addEventListener("click", () => byId("btnRefreshPlayers")?.click());
            const trackedInputs = new Set(["statDimensionId", "statPosX", "statPosY", "statPosZ", "statHealth", "statFoodLevel", "statXpLevel", "statGamemode"]);
            const onFormChange = event => {
                if (trackedInputs.has(event.target?.id)) updateFacts();
                if (event.target?.id === "languageSelect") updateFocusStatusLabels();
            };
            doc.addEventListener("input", onFormChange);
            doc.addEventListener("change", onFormChange);
            const shellObserver = observerFactory(sync);
            shellObserver.observe(root, { attributes: true, attributeFilter: ["data-layout"] });
            shellObserver.observe(body, { attributes: true, attributeFilter: ["class", "data-workflow-view"] });
            const name = byId("playerSummaryName");
            if (name) observerFactory(updateFacts).observe(name, { childList: true, subtree: true, characterData: true });
            const gamemode = byId("statGamemode");
            if (gamemode) observerFactory(updateFacts).observe(gamemode, {
                attributes: true, attributeFilter: ["data-summary-label", "data-summary-title"],
            });
            const list = byId("playersList");
            if (list) observerFactory(filterPlayers).observe(list, { childList: true });
            // Backend status and progress update asynchronously; keep the
            // compact labels in sync without observing our own data attributes.
            const server = byId("serverStatusBadge");
            if (server) observerFactory(updateFocusStatusLabels).observe(server, {
                attributes: true, attributeFilter: ["class", "title"], childList: true, characterData: true, subtree: true,
            });
            const status = byId("statusStackButton");
            if (status) observerFactory(updateFocusStatusLabels).observe(status, {
                attributes: true, attributeFilter: ["class", "aria-label"], childList: true, characterData: true, subtree: true,
            });
            sync();
        }

        return { sync, wire, updateFacts, updateFocusStatusLabels, filterPlayers, inventoryIsFocused, restore };
    }

    function init() {
        const controller = createFocusWorkspaceController();
        window.MCBEFocusWorkspace = controller;
        controller.wire();
    }
    window.MCBEFocusWorkspaceFactory = { createFocusWorkspaceController };
    if (typeof document !== "undefined") {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
        else init();
    }
}());
