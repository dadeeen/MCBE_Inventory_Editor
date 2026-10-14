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
        let previousLayout = root.dataset.layout;

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
            let next = origin.next;
            while (next && next.parentNode !== origin.parent) next = originalPositions.get(next)?.next;
            origin.parent.insertBefore(node, next || null);
        }

        function inventoryIsFocused() {
            return root.dataset.layout === "focus" && body.dataset.workflowView === "inventory"
                && body.classList.contains("app-player-loaded");
        }

        function filterPlayers() {
            const managerFocused = !inventoryIsFocused();
            const query = String(inventoryIsFocused() ? byId("focusPlayerSearch")?.value || "" : byId("playerManagerSearch")?.value || "").trim().toLocaleLowerCase();
            let visiblePlayers = 0;
            let totalPlayers = 0;
            byId("playersList")?.querySelectorAll(".player-row").forEach(row => {
                const name = row.querySelector(".player-name")?.textContent || "";
                totalPlayers++;
                const matches = `${name} ${row.dataset?.playerKey || ""}`.toLocaleLowerCase().includes(query);
                row.style.display = matches ? "" : "none";
                if (matches) visiblePlayers++;
            });
            const empty = byId("focusPlayerSearchEmpty");
            if (empty) empty.hidden = managerFocused || !query || visiblePlayers > 0;
            const managerEmpty = byId("playerManagerSearchEmpty");
            if (managerEmpty) managerEmpty.hidden = !managerFocused || !query || visiblePlayers > 0;
            const count = byId("playerManagerCount");
            if (count) count.textContent = `${visiblePlayers} / ${totalPlayers}`;
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
            server.setAttribute("role", "button");
            server.setAttribute("tabindex", "0");
            server.setAttribute("aria-controls", "focusServerStatusPanel");
            if (!server.hasAttribute?.("aria-expanded")) server.setAttribute("aria-expanded", "false");
            const text = byId("focusServerStatusText");
            const hint = byId("focusServerStatusHint");
            if (text) text.textContent = server.textContent?.trim() || "";
            if (hint) {
                hint.textContent = server.title || "";
                hint.hidden = !server.title;
            }

            const needsAttention = status.classList?.contains?.("error") || status.classList?.contains?.("warning");
            const count = Number(byId("statusStackCount")?.textContent) || 0;
            const statusLabel = local("Meldungen", "Messages") + (needsAttention && count > 0 ? ` (${count})` : "");
            if (status.dataset.focusLabel !== statusLabel) status.dataset.focusLabel = statusLabel;
        }

        function placeHeaderStatus() {
            const host = byId("focusInlineStatus");
            if (root.dataset.layout === "focus" && win.innerWidth >= 1181) {
                move(host, doc.querySelector(".app-header"));
            } else {
                restore(host);
            }
        }

        function sync() {
            const focus = root.dataset.layout === "focus";
            if (previousLayout !== root.dataset.layout) {
                closeSettings({ restoreFocus: true });
                previousLayout = root.dataset.layout;
            }
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
            move(history, byId("focusHistoryMount"));
            move(headerActions, byId("focusSettingsMount"));

            // Dock the *existing* status, history, review action and settings.
            // Neither save semantics nor the undo stack are reimplemented.
            if (focus) {
                move(headerStatus, byId("focusInlineStatus"));
                move(saveArea, byId("focusSaveMount"));
            } else {
                // Settings/history stay shared; restore layout-specific status
                // and save placement without recreating their controls.
                restore(headerStatus);
                restore(saveArea);
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

            placeHeaderStatus();
            filterPlayers();
            updateFacts();
            updateFocusStatusLabels();
            positionStatusDetails();
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

        function fitSettingsPanel() {
            const panel = byId("focusSettingsPanel");
            const toggle = byId("focusSettingsToggle");
            if (!panel || panel.hidden || !toggle?.getBoundingClientRect) return;
            const rect = toggle.getBoundingClientRect();
            const below = Math.max(0, win.innerHeight - rect.bottom - 20);
            const above = Math.max(0, rect.top - 20);
            const openAbove = below < Math.min(260, panel.scrollHeight) && above > below;
            panel.style.top = openAbove ? "auto" : "calc(100% + 8px)";
            panel.style.bottom = openAbove ? "calc(100% + 8px)" : "auto";
            panel.style.maxHeight = `${Math.min(480, openAbove ? above : below)}px`;
        }

        function positionStatusDetails() {
            for (const [triggerId, panelId, preferredWidth] of [
                ["serverStatusBadge", "focusServerStatusPanel", 440],
                ["statusStackButton", "statusStackPanel", 520],
            ]) {
                const trigger = byId(triggerId);
                const panel = byId(panelId);
                if (!panel || panel.hidden || !trigger?.getBoundingClientRect) continue;
                const anchor = trigger.getBoundingClientRect();
                const viewportWidth = doc.documentElement.clientWidth || win.innerWidth;
                const width = Math.min(preferredWidth, viewportWidth - 24);
                panel.style.position = "absolute";
                panel.style.width = `${width}px`;
                panel.style.right = "auto";
                panel.style.bottom = "auto";
                panel.style.margin = "0";
                const parent = panel.offsetParent;
                if (!parent) continue;
                const origin = parent.getBoundingClientRect();
                const below = Math.max(0, win.innerHeight - anchor.bottom - 20);
                const above = Math.max(0, anchor.top - 20);
                const openAbove = below < 120 && above > below;
                panel.style.maxHeight = `${Math.min(320, openAbove ? above : below)}px`;
                const left = Math.max(12, Math.min(anchor.left, viewportWidth - width - 12));
                const top = openAbove ? anchor.top - 8 - panel.getBoundingClientRect().height : anchor.bottom + 8;
                panel.style.left = `${left - origin.left + parent.scrollLeft - parent.clientLeft}px`;
                panel.style.top = `${top - origin.top + parent.scrollTop - parent.clientTop}px`;
            }
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
                if (willOpen) fitSettingsPanel();
            });
            win.addEventListener?.("resize", fitSettingsPanel);
            win.addEventListener?.("resize", () => {
                placeHeaderStatus();
                positionStatusDetails();
            });
            doc.addEventListener("scroll", positionStatusDetails, true);
            for (const id of ["focusServerStatusPanel", "statusStackPanel"]) {
                const panel = byId(id);
                if (panel) observerFactory(positionStatusDetails).observe(panel, {
                    attributes: true, attributeFilter: ["hidden"], childList: true, subtree: true, characterData: true,
                });
            }
            if (win.ResizeObserver) {
                const geometryObserver = new win.ResizeObserver(positionStatusDetails);
                for (const selector of [".app-header", "#serverStatusBadge", "#statusStackButton"]) {
                    const element = doc.querySelector(selector);
                    if (element) geometryObserver.observe(element);
                }
            }
            const serverBadge = byId("serverStatusBadge");
            const serverPanel = byId("focusServerStatusPanel");
            serverBadge?.addEventListener("click", () => {
                if (!serverPanel) return;
                closeSettings();
                const willOpen = serverPanel.hidden;
                serverPanel.hidden = !willOpen;
                serverBadge.setAttribute("aria-expanded", String(willOpen));
                positionStatusDetails();
            });
            serverBadge?.addEventListener("keydown", event => {
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
            for (const id of ["focusPlayerSearch", "playerManagerSearch"]) {
                byId(id)?.addEventListener("input", event => {
                    for (const otherId of ["focusPlayerSearch", "playerManagerSearch"]) {
                        const other = byId(otherId);
                        if (other && other !== event.target) other.value = event.target.value;
                    }
                    filterPlayers();
                });
            }
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
