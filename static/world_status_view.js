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

    function loadPathChecklist(pathText = "") {
        return [
            { ok: !!pathText, text: t("Pfad ist ausgewählt") },
            { ok: pathText.toLowerCase().includes("minecraftworlds") || pathText.includes("/worlds/") || pathText.includes("\\worlds\\"), text: t("Pfad wirkt wie ein Bedrock-Weltpfad") },
            { ok: !/minecraftworlds[\\/]*$/i.test(pathText), text: t("Nicht nur der Sammelordner gewählt") },
        ];
    }

    function loadErrorHtml({ message, hints = [], pathText = "", requestId = "" } = {}) {
        const checklistHtml = loadPathChecklist(pathText)
            .map(item => `<div class="load-check ${item.ok ? "ok" : "warn"}"><span>${item.ok ? "✓" : "!"}</span>${escapeHtml(item.text)}</div>`)
            .join("");
        const requestHtml = requestId ? `<div class="error-request">Request-ID: <code>${escapeHtml(requestId)}</code></div>` : "";
        const cleanHints = Array.isArray(hints) ? hints.filter(Boolean) : [];
        const hintsHtml = cleanHints.length
            ? `<ul>${cleanHints.map(hint => `<li>${escapeHtml(hint)}</li>`).join("")}</ul>`
            : `<ul><li>${t("Prüfe, ob der Pfad auf den direkten Weltordner zeigt, der den Unterordner <code>db</code> enthält.")}</li><li>${t("Schließe Minecraft/den Bedrock Server vollständig und versuche es erneut.")}</li></ul>`;
        return `
        <div class="load-error-title">${t("Welt konnte nicht geladen werden")}</div>
        <div class="load-error-message">${escapeHtml(message)}</div>
        <div class="load-checklist">${checklistHtml}</div>
        <div class="load-error-help"><strong>${t("Was du tun kannst:")}</strong>${hintsHtml}</div>
        ${requestHtml}
    `;
    }

    function applyLoadErrorPanel(element, html = "") {
        if (!element) return;
        element.innerHTML = html;
        element.style.display = "block";
    }

    function clearLoadErrorPanel(element) {
        if (!element) return;
        element.style.display = "none";
        element.innerHTML = "";
    }

    function selectedWorldDirtyHint({ isDirty = false, worldPath = "", selectedPath = "" } = {}) {
        const visible = Boolean(isDirty && worldPath && selectedPath === worldPath);
        return {
            visible,
            text: visible ? t("Ungespeicherte Änderungen") : "",
        };
    }

    function selectedWorldBarModel({ selectedWorld = null, fromManual = false, isDocker = false } = {}) {
        if (!selectedWorld) {
            return {
                visible: false,
                loadDisabled: true,
                openDisabled: true,
                openTitle: "",
                name: "",
                pathText: "",
                pathTitle: "",
            };
        }
        const source = selectedWorld.source_label ? t(selectedWorld.source_label) : (fromManual ? t("Manueller Pfad") : t("Suchergebnis"));
        const folder = selectedWorld.folder || selectedWorld.path || "";
        const openDisabled = isDocker === true;
        return {
            visible: true,
            loadDisabled: false,
            name: selectedWorld.name || selectedWorld.folder || t("Ausgewählte Welt"),
            openDisabled,
            openTitle: openDisabled
                ? t("Im Docker-/LAN-Modus kann der Browser keinen Host-Explorer öffnen.")
                : t("Ausgewählten Weltordner im Dateimanager öffnen"),
            pathText: `${source} · ${folder}`,
            pathTitle: selectedWorld.path || "",
        };
    }

    function pathHintModel(text = "", type = "") {
        return {
            text,
            className: `path-card-hint ${type}`.trim(),
        };
    }

    function applyPathHintModel(element, model = {}) {
        if (!element) return;
        element.textContent = model.text || "";
        element.className = model.className || "path-card-hint";
    }

    function applySelectedWorldBarModel(elements = {}, model = {}) {
        const {
            bar = null,
            name = null,
            path = null,
            safetyNote = null,
            loadButton = null,
            openButton = null,
        } = elements;
        if (bar) bar.style.display = model.visible ? "flex" : "none";
        if (!model.visible) return false;
        if (name) name.textContent = model.name || "";
        if (path) {
            path.textContent = model.pathText || "";
            path.title = model.pathTitle || "";
        }
        if (safetyNote) {
            safetyNote.textContent = "";
            safetyNote.style.display = "none";
        }
        if (loadButton) loadButton.disabled = Boolean(model.loadDisabled);
        if (openButton) {
            openButton.disabled = Boolean(model.openDisabled);
            openButton.title = model.openTitle || "";
        }
        return true;
    }

    function applySelectedWorldDirtyHint(element, hint = {}) {
        if (!element) return;
        element.textContent = hint.text || "";
        element.style.display = hint.visible ? "inline-flex" : "none";
    }

    function changeCountText(total = 0) {
        if (total > 0) return total === 1 ? t("1 Änderung") : t("{count} Änderungen", { count: total });
        return t("Änderungen");
    }

    function dirtyBannerText({ playerLabel = "", changeTotal = 0 } = {}) {
        return t("{player} · {changes} · Backup automatisch vor dem Schreiben.", { player: playerLabel, changes: changeCountText(changeTotal) });
    }

    function safeEditBannerText({ blocked = false, blockedReason = "", isDirty = false, changeTotal = 0 } = {}) {
        if (blocked) return blockedReason || t("Schreibaktionen sind aktuell blockiert.");
        if (isDirty) return t("Ungespeicherte Änderungen: {changes}", { changes: changeCountText(changeTotal) });
        return t("Keine ungespeicherten Änderungen.");
    }

    function safeEditBannerTitle({ blocked = false, isDirty = false } = {}) {
        if (blocked) return t("Schreiben gesperrt");
        if (isDirty) return t("Bereit zum Speichern");
        return t("Bereit zum Bearbeiten");
    }

    function dirtyUiModel({
        worldPath = "",
        currentPlayerKey = "",
        isDirty = false,
        blocked = false,
        blockedReason = "",
        playerLabel = "",
        changeTotal = 0,
    } = {}) {
        const hasEditablePlayer = Boolean(worldPath && currentPlayerKey);
        const showDirtyBanner = Boolean(hasEditablePlayer && isDirty);
        const safeEditChangeTotal = isDirty && !blocked ? changeTotal : 0;
        return {
            dirtyBannerDisplay: showDirtyBanner ? "flex" : "none",
            dirtyBannerText: showDirtyBanner ? dirtyBannerText({ playerLabel, changeTotal }) : "",
            dirtyReviewDisabled: !showDirtyBanner || blocked,
            dirtySaveDisabled: !showDirtyBanner || blocked,
            dirtyDiscardDisabled: !showDirtyBanner,
            savePreviewDisabled: !hasEditablePlayer || !isDirty || blocked,
            saveDiscardDisabled: !hasEditablePlayer || !isDirty,
            safeEditBlocked: Boolean(blocked),
            safeEditDirty: Boolean(isDirty),
            safeEditTitle: safeEditBannerTitle({ blocked, isDirty }),
            safeEditText: safeEditBannerText({
                blocked,
                blockedReason,
                isDirty,
                changeTotal: safeEditChangeTotal,
            }),
        };
    }

    function applyDirtyBannerModel(elements = {}, model = {}) {
        const {
            banner = null,
            text = null,
            reviewButton = null,
            saveButton = null,
            discardButton = null,
        } = elements;
        if (banner) banner.style.display = model.dirtyBannerDisplay || "none";
        if (text && model.dirtyBannerText) text.textContent = model.dirtyBannerText;
        if (reviewButton) reviewButton.disabled = Boolean(model.dirtyReviewDisabled);
        if (saveButton) saveButton.disabled = Boolean(model.dirtySaveDisabled);
        if (discardButton) discardButton.disabled = Boolean(model.dirtyDiscardDisabled);
    }

    function applySavePreviewTriggerModel(elements = {}, model = {}) {
        const {
            previewButton = null,
            discardButton = null,
            safeEditBanner = null,
        } = elements;
        if (previewButton) previewButton.disabled = Boolean(model.savePreviewDisabled);
        if (discardButton) discardButton.disabled = Boolean(model.saveDiscardDisabled);
        if (safeEditBanner) {
            safeEditBanner.classList.toggle("dirty", Boolean(model.safeEditDirty));
            safeEditBanner.classList.toggle("blocked", Boolean(model.safeEditBlocked));
            const title = safeEditBanner.querySelector("strong");
            const text = safeEditBanner.querySelector("span");
            if (title) title.textContent = model.safeEditTitle || "";
            if (text) text.textContent = model.safeEditText || "";
        }
    }



    function createWorldStatusController({
        elements = {},
        appConfig = {},
        buildErrorMessage = (data, fallback = t("Fehler")) => data?.error || fallback,
        getSelectedWorld = () => null,
        setSelectedWorld = () => {},
        getWorldPath = () => "",
        getIsDirty = () => false,
        getCurrentPlayerKey = () => "",
        getLastRenderedWorlds = () => [],
        buildChangeSummary = () => ({ total: 0 }),
        effectiveWriteGate = () => ({}),
        writeBlocked = gate => gate?.allowed === false && gate?.requires_unknown_server_confirmation !== true,
        currentPlayerLabel = () => t("Spieler"),
        renderWorldCards = () => {},
        showConfirmDialog = async () => false,
    } = {}) {
        const {
            loadErrorPanel = null,
            autoPathHint = null,
            worldPathInput = null,
            selectedWorldBar = null,
            selectedWorldName = null,
            selectedWorldPath = null,
            selectedWorldSafetyNote = null,
            loadButton = null,
            openSelectedWorldButton = null,
            dirtyBanner = null,
            dirtyBannerText = null,
            dirtyReviewButton = null,
            dirtySaveButton = null,
            dirtyDiscardButton = null,
            savePreviewButton = null,
            safeEditDiscardButton = null,
            safeEditBanner = null,
        } = elements;

        function clearLoadError() {
            clearLoadErrorPanel(loadErrorPanel);
        }

        function renderLoadError(data, fallback = t("Welt konnte nicht geladen werden.")) {
            if (!loadErrorPanel) return;
            const message = buildErrorMessage(data, fallback);
            const selectedWorld = getSelectedWorld();
            const pathText = (worldPathInput?.value || selectedWorld?.path || "").trim();
            const html = loadErrorHtml({
                message,
                hints: data?.hints,
                pathText,
                requestId: data?.request_id || "",
            });
            applyLoadErrorPanel(loadErrorPanel, html);
        }

        function updateAutoPathHint(text, type = "") {
            const model = pathHintModel(text, type);
            applyPathHintModel(autoPathHint, model);
        }

        function localWorldAccessNeedsConfirmation() {
            // Reads stay available; server status is enforced at write boundaries.
            return false;
        }

        async function confirmLocalWorldAccessBeforeOpen(_path) {
            return true;
        }

        function updateSelectedWorld(world, { fromManual = false } = {}) {
            const selectedWorld = world && world.path ? world : null;
            setSelectedWorld(selectedWorld);
            if (selectedWorld && worldPathInput) worldPathInput.value = selectedWorld.path;
            const model = selectedWorldBarModel({
                selectedWorld,
                fromManual,
                isDocker: appConfig.is_docker === true || appConfig.mode === "docker",
            });
            const visible = applySelectedWorldBarModel({
                bar: selectedWorldBar,
                name: selectedWorldName,
                path: selectedWorldPath,
                safetyNote: selectedWorldSafetyNote,
                loadButton,
                openButton: openSelectedWorldButton,
            }, model);
            if (!visible) return;
            updateSelectedWorldDirtyHint();
        }

        function updateSelectedWorldDirtyHint() {
            const selectedWorld = getSelectedWorld();
            const hint = selectedWorldDirtyHint({
                isDirty: getIsDirty(),
                worldPath: getWorldPath(),
                selectedPath: selectedWorld?.path || "",
            });
            applySelectedWorldDirtyHint(selectedWorldSafetyNote, hint);
        }

        function dirtyModel() {
            const gate = effectiveWriteGate();
            const blocked = writeBlocked(gate);
            const summary = getIsDirty() ? buildChangeSummary({ limit: 3, includeSections: false }) : { total: 0 };
            return dirtyUiModel({
                worldPath: getWorldPath(),
                currentPlayerKey: getCurrentPlayerKey(),
                isDirty: getIsDirty(),
                blocked,
                blockedReason: gate?.reason || "",
                playerLabel: currentPlayerLabel(),
                changeTotal: summary.total,
            });
        }

        function updateSavePreviewTrigger(model = null) {
            let viewModel = model;
            if (!viewModel) {
                const gate = effectiveWriteGate();
                const blocked = writeBlocked(gate);
                const summary = getIsDirty() && !blocked ? buildChangeSummary({ limit: 3, includeSections: false }) : { total: 0 };
                viewModel = dirtyUiModel({
                    worldPath: getWorldPath(),
                    currentPlayerKey: getCurrentPlayerKey(),
                    isDirty: getIsDirty(),
                    blocked,
                    blockedReason: gate?.reason || "",
                    playerLabel: currentPlayerLabel(),
                    changeTotal: summary.total,
                });
            }
            applySavePreviewTriggerModel({
                previewButton: savePreviewButton,
                discardButton: safeEditDiscardButton,
                safeEditBanner,
            }, viewModel);
        }

        function updateDirtyBanner() {
            const model = dirtyModel();
            applyDirtyBannerModel({
                banner: dirtyBanner,
                text: dirtyBannerText,
                reviewButton: dirtyReviewButton,
                saveButton: dirtySaveButton,
                discardButton: dirtyDiscardButton,
            }, model);
            updateSelectedWorldDirtyHint();
            const lastRenderedWorlds = getLastRenderedWorlds();
            if (Array.isArray(lastRenderedWorlds) && lastRenderedWorlds.length) renderWorldCards(lastRenderedWorlds);
            updateSavePreviewTrigger(model);
        }

        return {
            clearLoadError,
            confirmLocalWorldAccessBeforeOpen,
            localWorldAccessNeedsConfirmation,
            renderLoadError,
            updateAutoPathHint,
            updateDirtyBanner,
            updateSavePreviewTrigger,
            updateSelectedWorld,
            updateSelectedWorldDirtyHint,
        };
    }

    function collectWorldStatusElements(doc = document) {
        return {
            loadErrorPanel: doc.getElementById("loadErrorPanel"),
            autoPathHint: doc.getElementById("autoPathHint"),
            worldPathInput: doc.getElementById("worldPath"),
            selectedWorldBar: doc.getElementById("selectedWorldBar"),
            selectedWorldName: doc.getElementById("selectedWorldName"),
            selectedWorldPath: doc.getElementById("selectedWorldPath"),
            selectedWorldSafetyNote: doc.getElementById("selectedWorldSafetyNote"),
            loadButton: doc.getElementById("btnLoad"),
            openSelectedWorldButton: doc.getElementById("btnOpenSelectedWorld"),
            dirtyBanner: doc.getElementById("dirtyBanner"),
            dirtyBannerText: doc.getElementById("dirtyBannerText"),
            dirtyReviewButton: doc.getElementById("btnDirtyReview"),
            dirtySaveButton: doc.getElementById("btnDirtySave"),
            dirtyDiscardButton: doc.getElementById("btnDirtyDiscardChanges"),
            savePreviewButton: doc.getElementById("btnShowSavePreview"),
            safeEditDiscardButton: doc.getElementById("btnSafeEditDiscardChanges"),
            safeEditBanner: doc.getElementById("safeEditBanner"),
        };
    }

    function createInventoryWorldStatusController({ doc = document, ...deps } = {}) {
        return createWorldStatusController({
            ...deps,
            elements: collectWorldStatusElements(doc),
        });
    }

    window.MCBEWorldStatusView = {
        applyDirtyBannerModel,
        collectWorldStatusElements,
        createInventoryWorldStatusController,
        createWorldStatusController,
        applyLoadErrorPanel,
        applyPathHintModel,
        applySavePreviewTriggerModel,
        applySelectedWorldBarModel,
        applySelectedWorldDirtyHint,
        clearLoadErrorPanel,
        loadErrorHtml,
        selectedWorldDirtyHint,
        selectedWorldBarModel,
        pathHintModel,
        dirtyUiModel,
        dirtyBannerText,
        safeEditBannerText,
        safeEditBannerTitle,
    };
}());
