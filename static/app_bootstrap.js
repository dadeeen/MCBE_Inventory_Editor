(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const STORAGE_KEYS = Object.freeze({
        recentWorlds: "mcbe-inventory-editor:recentWorlds",
        sessionRecentWorlds: "mcbe-inventory-editor:recentWorlds:session",
        workspace: "mcbe-inventory-editor:workspace",
        favoriteWorlds: "mcbe-inventory-editor:favoriteWorlds",
        theme: "mcbe-inventory-editor:theme",
        storageSchema: "mcbe-inventory-editor:storageSchema",
        slotNumbers: "mcbe-inventory-editor:slotNumbers",
        enderCollapsed: "mcbe-inventory-editor:enderCollapsed",
    });

    const CONSTANTS = Object.freeze({
        maxSessionLog: 80,
        maxHeaderNotices: 8,
        inventorySlotCount: 36,
        enderChestSlotCount: 27,
        maxUndo: 50,
        defaultMaxDamage: 32767,
        maxBedrockStackCount: 127,
        maxDisplayName: 512,
        maxLoreLines: 50,
        maxLoreLineLength: 512,
        itemIdPattern: "^[a-z0-9_.-]+:[a-z0-9_.-]+$",
    });

    const CURRENT_STORAGE_SCHEMA = "v3-dark-session-history";

    function appConfigFromDocument(doc = document) {
        try {
            return JSON.parse(doc.getElementById("appConfigJson")?.textContent || "{}");
        } catch (_e) {
            return {};
        }
    }

    function csrfTokenFromDocument(doc = document) {
        return doc.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
    }

    function markViewerMode(doc, appConfig) {
        if (appConfig?.read_only !== true) return;
        const subtitle = doc.querySelector(".app-subtitle");
        if (!subtitle || subtitle.querySelector("[data-readonly-viewer-badge]")) return;
        const badge = doc.createElement("span");
        badge.dataset.readonlyViewerBadge = "true";
        badge.textContent = "• READONLY / VIEWER";
        badge.title = t("MCBE_READ_ONLY=true: Welten ansehen, Schreibaktionen blockiert.");
        badge.style.color = "var(--warning)";
        badge.style.fontWeight = "800";
        badge.style.letterSpacing = "0.04em";
        subtitle.appendChild(badge);
    }

    function installIconErrorFallback(doc = document) {
        if (!doc || typeof doc.addEventListener !== "function" || typeof doc.createElement !== "function") return false;
        if (doc.__mcbeIconErrorFallbackInstalled) return false;
        doc.__mcbeIconErrorFallbackInstalled = true;
        // CSP (script-src 'self') verbietet Inline-onerror-Handler; error-Events
        // bubbeln nicht, daher ein delegierter Capture-Listener. Fehlgeschlagene
        // Icon-Bilder (z. B. 429/404) werden durch das Emoji-Fallback ersetzt,
        // statt als leere Iconfläche zu erscheinen.
        doc.addEventListener("error", (event) => {
            const img = event.target;
            if (!img || String(img.tagName || "").toLowerCase() !== "img") return;
            const fallback = img.getAttribute?.("data-icon-fallback");
            if (fallback === null || fallback === undefined) return;
            const span = doc.createElement("span");
            span.textContent = fallback || "□";
            if (typeof img.replaceWith === "function") img.replaceWith(span);
        }, true);
        return true;
    }

    function installIconTintHandler(doc = document) {
        if (!doc || typeof doc.addEventListener !== "function" || typeof doc.createElement !== "function") return false;
        if (doc.__mcbeIconTintHandlerInstalled) return false;
        doc.__mcbeIconTintHandlerInstalled = true;
        // Graustufen-Basistexturen (Leder-Rüstung) werden wie im Spiel mit der
        // Item-Farbe multipliziert. Delegierter Capture-Listener, weil
        // load-Events nicht bubbeln und CSP Inline-Handler verbietet.
        doc.addEventListener("load", (event) => {
            const img = event.target;
            if (!img || String(img.tagName || "").toLowerCase() !== "img") return;
            const tint = img.getAttribute?.("data-icon-tint");
            if (!tint || img.__mcbeIconTintApplied) return;
            try {
                const canvas = doc.createElement("canvas");
                canvas.width = img.naturalWidth || 0;
                canvas.height = img.naturalHeight || 0;
                if (!canvas.width || !canvas.height || typeof canvas.getContext !== "function") return;
                const ctx = canvas.getContext("2d");
                if (!ctx) return;
                ctx.drawImage(img, 0, 0);
                ctx.globalCompositeOperation = "multiply";
                ctx.fillStyle = tint;
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                // Multiply füllt auch transparente Pixel; Alphakanal des
                // Originals wiederherstellen.
                ctx.globalCompositeOperation = "destination-in";
                ctx.drawImage(img, 0, 0);
                img.__mcbeIconTintApplied = true;
                img.src = canvas.toDataURL("image/png");
            } catch (_e) {
                // Canvas nicht verfügbar oder Bild tainted: Original bleibt sichtbar.
            }
        }, true);
        return true;
    }

    function inventoryClipboardHelpModel() {
        const controlKey = t("Strg");
        return {
            existingKeyLabels: new Map([
                ["Strg+Z", `${controlKey}+Z`],
                ["Strg+Y", `${controlKey}+Y`],
                ["Strg+S", `${controlKey}+S`],
                ["Strg+F", `${controlKey}+F`],
                ["Strg", controlKey],
                ["Rechtsklick", t("Rechtsklick")],
            ]),
            rows: [
                { id: "copy-item", shortcut: `${controlKey}+C`, description: `${t("📋 Kopieren")} (${t("Inventar")})` },
                { id: "paste-item", shortcut: `${controlKey}+Shift+V`, description: `${t("📄 Einfügen")} (${t("Inventar")})` },
                { id: "paste-system", shortcut: `${controlKey}+V`, description: `${t("📄 Einfügen")} (System)` },
                { id: "copy-drag", shortcut: `${controlKey} + ${t("Slot ziehen & ablegen")}`, description: `${t("Kopieren")} (${t("Inventar")})` },
            ],
        };
    }

    function createInventoryClipboardHelpRow(doc, rowModel) {
        const row = doc.createElement("tr");
        row.dataset.inventoryClipboardHelp = "true";
        row.dataset.inventoryClipboardHelpId = rowModel.id;

        const shortcutCell = doc.createElement("td");
        const shortcut = doc.createElement("kbd");
        shortcut.textContent = rowModel.shortcut;
        shortcutCell.appendChild(shortcut);

        const descriptionCell = doc.createElement("td");
        descriptionCell.textContent = rowModel.description;
        row.append(shortcutCell, descriptionCell);
        return row;
    }

    function installInventoryClipboardHelp(doc = document) {
        if (!doc || typeof doc.querySelector !== "function" || typeof doc.createElement !== "function") return false;
        const table = doc.querySelector("#helpOverlay .help-table");
        if (!table) return false;

        const model = inventoryClipboardHelpModel();
        const existingRows = Array.from(table.querySelectorAll?.("tr") || []);
        const focusSearchRow = existingRows.find(row => String(row.querySelector?.("kbd")?.textContent || "").trim() === "Strg+F");

        existingRows.forEach(row => {
            const key = row.querySelector?.("kbd");
            const source = String(key?.textContent || "").trim();
            if (key && model.existingKeyLabels.has(source)) key.textContent = model.existingKeyLabels.get(source);
        });

        if (table.dataset?.inventoryClipboardHelpInstalled === "true" || table.querySelector?.('[data-inventory-clipboard-help="true"]')) {
            return false;
        }
        if (table.dataset) table.dataset.inventoryClipboardHelpInstalled = "true";

        let anchor = focusSearchRow;
        for (const rowModel of model.rows) {
            const row = createInventoryClipboardHelpRow(doc, rowModel);
            if (anchor && typeof anchor.insertAdjacentElement === "function") {
                anchor.insertAdjacentElement("afterend", row);
                anchor = row;
            } else {
                const target = table.tBodies?.[0] || table;
                target.appendChild(row);
            }
        }
        return true;
    }

    function createRuntimeContext({ doc = document, win = window, consoleObj = console } = {}) {
        const csrfToken = csrfTokenFromDocument(doc);
        const apiClient = win.MCBEApiClient.createApiClient({ csrfToken });
        // Some legacy controller wiring in app.js still references apiClient as a
        // browser global. Keep the runtime return value as the primary API, but
        // expose the same object for those late-initialized controllers.
        win.apiClient = apiClient;
        const appConfig = appConfigFromDocument(doc);
        markViewerMode(doc, appConfig);
        installIconErrorFallback(doc);
        installIconTintHandler(doc);
        installInventoryClipboardHelp(doc);
        if (!csrfToken) {
            consoleObj.error("CSRF-Meta-Tag fehlt – Sicherheitsrisiko!");
        }
        return {
            apiClient,
            appConfig,
            buildErrorMessage: apiClient.buildErrorMessage,
            constants: CONSTANTS,
            csrfToken,
            currentStorageSchema: CURRENT_STORAGE_SCHEMA,
            parseJsonResponse: apiClient.parseJsonResponse,
            storageKeys: STORAGE_KEYS,
            withCsrf: apiClient.withCsrf,
        };
    }

    window.MCBEAppBootstrap = {
        appConfigFromDocument,
        constants: CONSTANTS,
        createRuntimeContext,
        csrfTokenFromDocument,
        currentStorageSchema: CURRENT_STORAGE_SCHEMA,
        installIconErrorFallback,
        installIconTintHandler,
        installInventoryClipboardHelp,
        inventoryClipboardHelpModel,
        markViewerMode,
        storageKeys: STORAGE_KEYS,
    };
}());
