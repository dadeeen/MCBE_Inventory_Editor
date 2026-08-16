(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function createIconSourcesController({
        elements = {},
        fetchImpl = fetch,
        parseJsonResponse,
        withCsrf,
        iconManagerView = window.MCBEIconManagerView,
        appConfig = {},
        permissions = null,
        getVersion = () => "dev",
        getWorldPath = () => "",
        getSelectedWorldPath = () => "",
        itemEmoji = () => "",
        itemLabel = value => value,
        loadWorkspace = () => ({}),
        saveWorkspace = () => ({}),
        isInventoryOpen = () => false,
        onIconData = () => {},
        onIconDataApplied = () => {},
        onIconStatusUnavailable = () => {},
        copyTextToClipboard = async () => {},
        showToast = () => {},
        showConfirmDialog = async () => true,
        showLoading = () => {},
        hideLoading = () => {},
        logStatus = () => {},
        appendUpdateOutput = () => {},
        consoleObj = console,
    } = {}) {
        const {
            panel,
            sourcePathInput,
            addButton,
            pickPackButton,
            pickFolderButton,
            rescanButton,
            updateVanillaButton,
            hintBanner,
            emptyStateHint,
            emptyStateVanillaButton,
        } = elements;
        let iconSourceSummary = { count: 0, roots: [], warnings: [] };
        let iconRescanRunning = false;

        function summaryFromIconData(data) {
            const { icons: _icons, _by_token: _byToken, ...summary } = data || {};
            return summary;
        }

        async function postJson(url, body = undefined) {
            const options = {
                method: "POST",
                headers: withCsrf(),
            };
            if (body !== undefined) options.body = JSON.stringify(body);
            const res = await fetchImpl(url, options);
            return await parseJsonResponse(res);
        }

        function requireSuccess(data, fallbackMessage) {
            if (!data || data.success === false) {
                throw new Error(data?.error || fallbackMessage);
            }
            return data;
        }

        function applyIconIndexData(data) {
            iconSourceSummary = summaryFromIconData(data);
            onIconData({
                data,
                icons: data?.icons || {},
                summary: iconSourceSummary,
            });
            renderIconManager(data);
            renderIconHints();
            onIconDataApplied(data);
            return iconSourceSummary;
        }

        function canRescanIcons() {
            if (typeof permissions === "function") {
                return permissions()?.canRescanIcons !== false;
            }
            return appConfig?.read_only !== true;
        }

        function canWriteAppState() {
            if (typeof permissions === "function") {
                return permissions()?.canWriteAppState !== false;
            }
            return appConfig?.read_only !== true;
        }

        const READ_ONLY_SOURCES_MESSAGE = t("Icon-Quellen können im Read-Only-Modus nicht geändert werden.");

        function applyAppStateControlLocks() {
            const locked = !canWriteAppState();
            const controls = [addButton, pickPackButton, pickFolderButton, updateVanillaButton, emptyStateVanillaButton, sourcePathInput];
            for (const control of controls) {
                if (!control) continue;
                control.disabled = locked;
                control.title = locked ? READ_ONLY_SOURCES_MESSAGE : "";
            }
        }

        function iconManagerSummaryText(data = null) {
            return iconManagerView.iconManagerSummaryText(data || iconSourceSummary || {}, {
                version: getVersion() || "dev",
            });
        }

        function renderIconManager(data = null) {
            if (!panel) return;
            const summary = data || iconSourceSummary || {};
            panel.innerHTML = iconManagerView.iconManagerHtml(summary, {
                itemEmoji,
                itemLabel,
            });
            panel.querySelector("#btnFocusIconSource")?.addEventListener("click", () => {
                sourcePathInput?.focus();
                sourcePathInput?.scrollIntoView?.({ behavior: "smooth", block: "center" });
            });
            const sourcesLocked = !canWriteAppState();
            const wireSourceButton = (selector, handler) => {
                panel.querySelectorAll(selector).forEach(btn => {
                    if (sourcesLocked) {
                        btn.disabled = true;
                        btn.title = READ_ONLY_SOURCES_MESSAGE;
                        return;
                    }
                    btn.addEventListener("click", () => handler(btn));
                });
            };
            wireSourceButton(".icon-source-remove", btn => removeIconSource(btn.dataset.path || ""));
            wireSourceButton(".icon-source-toggle", btn => setIconSourceEnabled(btn.dataset.path || "", btn.dataset.enabled === "1"));
            wireSourceButton(".icon-source-move", btn => moveIconSource(btn.dataset.path || "", btn.dataset.direction || "up"));
            panel.querySelector("#btnCopyIconDiagnostics")?.addEventListener("click", () => {
                copyTextToClipboard(iconManagerSummaryText(summary), t("Icon-Diagnose kopiert."));
            });
        }

        async function confirmVanillaIconsUpdate() {
            const ok = await showConfirmDialog(
                t("Vanilla-Icons aus dem offiziellen Mojang/bedrock-samples Full-Release laden?") + "\n\n" +
                t("Das lädt ein Resource-Pack-ZIP von GitHub/Mojang, extrahiert nur relevante Texturen nach data/icons/vanilla und scannt den Icon-Index neu.")
            );
            if (!ok) return;
            await updateVanillaIcons();
        }

        function renderIconHints() {
            const count = Number(iconSourceSummary?.count || 0);
            if (emptyStateHint) emptyStateHint.style.display = count > 0 ? "none" : "";
            if (!hintBanner) return;
            const dismissed = Boolean(loadWorkspace()?.icon_hint_dismissed);
            if (count > 0 || dismissed || !isInventoryOpen()) {
                hintBanner.style.display = "none";
                hintBanner.innerHTML = "";
                return;
            }
            const locked = !canWriteAppState();
            hintBanner.innerHTML = `
                <div class="icon-hint-banner-text">
                    <strong>${t("Keine Item-Icons eingerichtet")}</strong>
                    <span>${t("Die App zeigt Ersatzsymbole. Optional: Vanilla-Icons laden oder unter Werkzeuge &amp; Einstellungen &rarr; Icons ein eigenes Resource-Pack w&auml;hlen.")}</span>
                </div>
                <div class="inline-actions">
                    <button id="btnIconHintVanilla" class="btn btn-primary btn-sm" type="button"${locked ? ` disabled title="${READ_ONLY_SOURCES_MESSAGE}"` : ""}>${t("Vanilla-Icons laden")}</button>
                    <button id="btnIconHintDismiss" class="btn-text" type="button">${t("Nicht mehr anzeigen")}</button>
                </div>`;
            hintBanner.style.display = "";
            hintBanner.querySelector("#btnIconHintVanilla")?.addEventListener("click", () => confirmVanillaIconsUpdate());
            hintBanner.querySelector("#btnIconHintDismiss")?.addEventListener("click", () => {
                saveWorkspace({ icon_hint_dismissed: true });
                renderIconHints();
            });
        }

        async function loadLocalIconIndex({ rescan = false, throwOnError = false } = {}) {
            try {
                const data = rescan && canRescanIcons()
                    ? await postJson("/api/icons/scan", { world_path: getWorldPath() || getSelectedWorldPath() || "" })
                    : await parseJsonResponse(await fetchImpl("/api/icons/status"));
                requireSuccess(
                    data,
                    rescan ? t("Icon-Scan fehlgeschlagen.") : t("Icon-Status konnte nicht geladen werden."),
                );
                applyIconIndexData(data);
            } catch (err) {
                consoleObj.warn("Local icon index unavailable", err);
                onIconStatusUnavailable(err);
                if (throwOnError) throw err;
            }
        }

        async function refreshIconSources({ rescan = false, throwOnError = false } = {}) {
            await loadLocalIconIndex({ rescan, throwOnError });
            return iconSourceSummary;
        }

        async function addIconSource(path) {
            if (!canWriteAppState()) {
                showToast(READ_ONLY_SOURCES_MESSAGE, "warning");
                return;
            }
            const clean = String(path || "").trim();
            if (!clean) {
                showToast(t("Bitte Resource-Pack-, ZIP-, MCPACK- oder Icon-Ordner-Pfad eingeben."), "warning");
                return;
            }
            if (addButton) addButton.disabled = true;
            showLoading(t("Icon-Quelle wird geprüft und indiziert..."));
            try {
                const data = requireSuccess(
                    await postJson("/api/icons/sources/add", { path: clean }),
                    t("Icon-Quelle konnte nicht hinzugefügt werden.")
                );
                applyIconIndexData(data);
                if (sourcePathInput) sourcePathInput.value = "";
                showToast(t("Icon-Quelle gespeichert. {count} Icons erkannt.", { count: data.count || 0 }), "success");
            } catch (err) {
                showToast(err?.message || t("Icon-Quelle konnte nicht hinzugefügt werden."), "error");
            } finally {
                hideLoading();
                if (addButton) addButton.disabled = false;
            }
        }

        async function removeIconSource(path) {
            if (!path) return;
            if (!canWriteAppState()) {
                showToast(READ_ONLY_SOURCES_MESSAGE, "warning");
                return;
            }
            const ok = await showConfirmDialog(t("Icon-Quelle entfernen? Gespeichert ist nur der Pfad; Texturen werden nicht gelöscht."));
            if (!ok) return;
            try {
                const data = requireSuccess(
                    await postJson("/api/icons/sources/remove", { path }),
                    t("Icon-Quelle konnte nicht entfernt werden.")
                );
                applyIconIndexData(data);
                showToast(t("Icon-Quelle entfernt."), "success");
            } catch (err) {
                showToast(err?.message || t("Icon-Quelle konnte nicht entfernt werden."), "error");
            }
        }

        async function setIconSourceEnabled(path, enabled) {
            if (!path) return;
            if (!canWriteAppState()) {
                showToast(READ_ONLY_SOURCES_MESSAGE, "warning");
                return;
            }
            try {
                const data = requireSuccess(
                    await postJson("/api/icons/sources/set_enabled", { path, enabled }),
                    t("Icon-Quelle konnte nicht aktualisiert werden.")
                );
                applyIconIndexData(data);
                showToast(enabled ? t("Icon-Quelle aktiviert.") : t("Icon-Quelle deaktiviert."), "success");
            } catch (err) {
                showToast(err?.message || t("Icon-Quelle konnte nicht aktualisiert werden."), "error");
            }
        }

        async function moveIconSource(path, direction) {
            if (!path) return;
            if (!canWriteAppState()) {
                showToast(READ_ONLY_SOURCES_MESSAGE, "warning");
                return;
            }
            try {
                const data = requireSuccess(
                    await postJson("/api/icons/sources/move", { path, direction }),
                    t("Icon-Quelle konnte nicht verschoben werden.")
                );
                applyIconIndexData(data);
                showToast(t("Icon-Quelle verschoben."), "success");
            } catch (err) {
                showToast(err?.message || t("Icon-Quelle konnte nicht verschoben werden."), "error");
            }
        }

        async function pickIconSource(kind) {
            if (!canWriteAppState()) {
                showToast(READ_ONLY_SOURCES_MESSAGE, "warning");
                return;
            }
            try {
                const endpoint = kind === "folder" ? "/api/icons/pick_folder" : "/api/icons/pick_pack";
                const data = await postJson(endpoint);
                if (data.path) await addIconSource(data.path);
            } catch (err) {
                showToast(err?.message || t("Icon-Quelle konnte nicht gewählt werden."), "error");
            }
        }

        async function updateVanillaIcons() {
            if (!canWriteAppState()) {
                showToast(READ_ONLY_SOURCES_MESSAGE, "warning");
                return { success: false, error: READ_ONLY_SOURCES_MESSAGE };
            }
            for (const control of [updateVanillaButton, emptyStateVanillaButton]) {
                if (control) control.disabled = true;
            }
            showLoading(t("Vanilla-Icons werden geladen..."));
            const updateStatus = (message, type, active = undefined) => logStatus(message, type, {
                key: "vanilla-icons-update",
                active,
            });
            updateStatus(t("Vanilla-Icons werden aus Mojang/bedrock-samples geladen..."), "running", true);
            try {
                const data = await postJson("/api/icons/vanilla/update", {});
                if (data.output) appendUpdateOutput(`\n=== ${t("Vanilla-Icons")} ===\n${data.output}`);
                if (!data.success) {
                    const message = data.error || t("Vanilla-Icons konnten nicht geladen werden.");
                    updateStatus(message, "error", true);
                    showToast(message, "error", 6000);
                    return { ...data, success: false, error: message };
                }
                if (data.scan_warning) {
                    appendUpdateOutput(`\n${data.scan_warning}`);
                    updateStatus(data.scan_warning, "warning", true);
                    showToast(data.scan_warning, "warning", 8000);
                    return { ...data, success: false, error: data.scan_warning };
                }
                applyIconIndexData(data);
                const mapped = data.manifest?.mapped_items ?? data.count ?? 0;
                const known = data.manifest?.known_items ?? "?";
                const message = t("Vanilla-Icons aktualisiert: {mapped} von {known} Item-IDs zugeordnet.", { mapped, known });
                updateStatus(message, "success", false);
                showToast(message, "success", 5000);
                return data;
            } catch (err) {
                consoleObj.error("updateVanillaIcons:", err);
                const message = err?.message || t("Verbindungsfehler beim Laden der Vanilla-Icons.");
                updateStatus(message, "error", true);
                showToast(message, "error", 6000);
                return { success: false, error: message };
            } finally {
                hideLoading();
                applyAppStateControlLocks();
            }
        }

        function wire() {
            applyAppStateControlLocks();
            addButton?.addEventListener("click", () => addIconSource(sourcePathInput?.value || ""));
            sourcePathInput?.addEventListener("keydown", event => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    addIconSource(sourcePathInput.value || "");
                }
            });
            pickPackButton?.addEventListener("click", () => pickIconSource("pack"));
            pickFolderButton?.addEventListener("click", () => pickIconSource("folder"));
            rescanButton?.addEventListener("click", async () => {
                if (iconRescanRunning) return;
                if (!canRescanIcons()) {
                    await refreshIconSources({ rescan: false });
                    showToast(t("Icon-Scan ist im Read-Only-Modus deaktiviert."), "warning");
                    return;
                }
                iconRescanRunning = true;
                if (rescanButton) rescanButton.disabled = true;
                showLoading(t("Icon-Quellen werden erneut gescannt..."));
                try {
                    const summary = await refreshIconSources({ rescan: true, throwOnError: true });
                    const count = Number(summary.count || 0);
                    showToast(count ? t("Icon-Scan abgeschlossen: {count} Icons.", { count }) : t("Icon-Scan abgeschlossen: keine passenden Texturen gefunden."), count ? "success" : "warning");
                } catch (err) {
                    showToast(err?.message || t("Icon-Scan fehlgeschlagen."), "error", 6000);
                } finally {
                    hideLoading();
                    iconRescanRunning = false;
                    if (rescanButton) rescanButton.disabled = false;
                }
            });
            updateVanillaButton?.addEventListener("click", () => confirmVanillaIconsUpdate());
            emptyStateVanillaButton?.addEventListener("click", () => confirmVanillaIconsUpdate());
        }

        return {
            addIconSource,
            applyAppStateControlLocks,
            applyIconIndexData,
            canRescanIcons,
            canWriteAppState,
            confirmVanillaIconsUpdate,
            iconManagerSummaryText,
            loadLocalIconIndex,
            moveIconSource,
            pickIconSource,
            refreshIconSources,
            removeIconSource,
            renderIconHints,
            renderIconManager,
            setIconSourceEnabled,
            updateVanillaIcons,
            wire,
        };
    }

    function collectInventoryIconSourceElements(doc = document) {
        return {
            panel: doc.getElementById("iconManagerPanel"),
            sourcePathInput: doc.getElementById("iconSourcePath"),
            addButton: doc.getElementById("btnAddIconSource"),
            pickPackButton: doc.getElementById("btnPickIconPack"),
            pickFolderButton: doc.getElementById("btnPickIconFolder"),
            rescanButton: doc.getElementById("btnRescanIcons"),
            updateVanillaButton: doc.getElementById("btnUpdateVanillaIcons"),
            hintBanner: doc.getElementById("iconHintBanner"),
            emptyStateHint: doc.getElementById("emptyStateIconHint"),
            emptyStateVanillaButton: doc.getElementById("btnEmptyStateVanillaIcons"),
        };
    }

    function createInventoryIconSourcesController({
        doc = document,
        api = {},
        appConfig = {},
        permissions = null,
        itemCatalog = {},
        itemLabel = value => value,
        getWorldPath = () => "",
        getSelectedWorldPath = () => "",
        loadWorkspace = () => ({}),
        saveWorkspace = () => ({}),
        isInventoryOpen = () => false,
        copyTextToClipboard = async () => {},
        showToast = () => {},
        showConfirmDialog = async () => true,
        showLoading = () => {},
        hideLoading = () => {},
        logStatus = () => {},
        appendUpdateOutput = () => {},
        onIconData = () => {},
        onIconDataApplied = () => {},
        onIconStatusUnavailable = () => {},
    } = {}) {
        return createIconSourcesController({
            elements: collectInventoryIconSourceElements(doc),
            parseJsonResponse: api.parseJsonResponse,
            withCsrf: api.withCsrf,
            appConfig,
            permissions,
            getVersion: () => appConfig?.distribution?.project_version || "dev",
            getWorldPath,
            getSelectedWorldPath,
            itemEmoji: itemCatalog.getItemEmoji,
            itemLabel,
            loadWorkspace,
            saveWorkspace,
            isInventoryOpen,
            copyTextToClipboard,
            showToast,
            showConfirmDialog,
            showLoading,
            hideLoading,
            logStatus,
            appendUpdateOutput,
            onIconData,
            onIconDataApplied,
            onIconStatusUnavailable,
        });
    }

    window.MCBEIconSourcesController = {
        collectInventoryIconSourceElements,
        createIconSourcesController,
        createInventoryIconSourcesController,
    };
}());
