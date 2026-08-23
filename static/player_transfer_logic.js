(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const PLAYER_EXPORT_STATUS_KEY = "player-export";
    const PLAYER_IMPORT_STATUS_KEY = "player-import";

    function cleanPath(value) {
        return String(value || "").trim();
    }

    function prefixedErrorMessage(data = {}, fallback = t("Fehler")) {
        return data && data.error ? `${fallback}: ${data.error}` : fallback;
    }

    function apiErrorMessage(data = {}, fallback = t("Fehler")) {
        if (!data || typeof data !== "object") return fallback;
        const base = data.error || fallback;
        const details = data.details && data.details !== base ? ` — ${data.details}` : "";
        return `${base}${details}`;
    }

    function exportPlayerPlan({
        worldPath = "",
        currentPlayerKey = "",
        isDirty = false,
        writeBlocked = false,
    } = {}) {
        if (!cleanPath(worldPath) || !currentPlayerKey) return { ok: false, reason: "missing_player" };
        if (writeBlocked) {
            return {
                ok: false,
                reason: "write_blocked",
                statusMessage: t("Export ist im Read-Only-Modus deaktiviert."),
                statusType: "warning",
            };
        }
        return {
            ok: true,
            needsDirtyConfirmation: Boolean(isDirty),
            dirtyConfirmationText: t("Es gibt ungespeicherte Änderungen.") + "\n\n" + t("Der Export enthält NUR die zuletzt gespeicherten Daten, nicht die aktuellen Änderungen. Trotzdem exportieren?"),
            loadingText: t("Exportiere Spieler..."),
            statusMessage: t("Exportiere Spieler..."),
            statusType: "running",
            requestBody: {
                world_path: worldPath,
                player_key: currentPlayerKey,
            },
        };
    }

    function exportPlayerOutcome(data = {}) {
        if (data.success) {
            const message = t("Spieler exportiert: {path}", { path: data.export_path });
            return {
                ok: true,
                message,
                statusMessage: message,
                statusType: "success",
                toast: { message },
                actionMessage: message,
                actionType: "export",
                exportPath: data.export_path || "",
            };
        }
        const message = prefixedErrorMessage(data, t("Export fehlgeschlagen"));
        return {
            ok: false,
            statusMessage: message,
            statusType: "error",
            toast: { message, type: "error", ms: 5000 },
        };
    }

    function openExportFolderOutcome(data = {}, lastExportDir = "") {
        if (data.success) {
            const nextDir = data.path || lastExportDir || "";
            return {
                ok: true,
                nextExportDir: nextDir,
                statusMessage: t("Exportordner geöffnet: {path}", { path: nextDir || data.path }),
                statusType: "success",
            };
        }
        const message = apiErrorMessage(data, t("Exportordner konnte nicht geöffnet werden."));
        return {
            ok: false,
            statusMessage: message,
            statusType: "error",
            toast: { message, type: "error", ms: 5000 },
        };
    }

    function browseExportSelectionOutcome(data = {}) {
        if (data.success && data.path) {
            return { ok: true, path: data.path };
        }
        if (data.error) {
            return {
                ok: false,
                statusMessage: t("Fehler: {error}", { error: data.error }),
                statusType: "error",
            };
        }
        return { ok: false, reason: "cancelled" };
    }

    function importPlayerPlan({
        worldPath = "",
        exportPath = "",
        importAsExported = false,
        currentPlayerKey = "",
        currentPlayerEditable = false,
        currentPlayerLabel = "",
        currentPlayerRevision = "",
        currentImportPreview = null,
        worldPresenceSessionId = "",
        isDirty = false,
    } = {}) {
        const cleanWorldPath = cleanPath(worldPath);
        const cleanExportPath = cleanPath(exportPath);
        if (!cleanWorldPath) return { ok: false, reason: "missing_world" };
        if (!cleanExportPath) {
            return {
                ok: false,
                reason: "missing_export_path",
                statusMessage: t("Bitte zuerst eine Import-Datei (.mcbe-player.zip) auswählen."),
                statusType: "error",
            };
        }
        if (!importAsExported && !currentPlayerKey) return { ok: false, reason: "missing_target_player" };
        if (!importAsExported && !currentPlayerEditable) {
            return {
                ok: false,
                reason: "target_not_editable",
                statusMessage: t("Bitte einen bearbeitbaren Zielspieler wählen oder Import als exportierter Spieler aktivieren."),
                statusType: "error",
            };
        }
        if (isDirty) {
            return {
                ok: false,
                reason: "open_changes",
                statusMessage: t("Speichere oder verwirf zuerst die offenen Editor-Änderungen."),
                statusType: "warning",
            };
        }
        const baseRevision = cleanPath(currentPlayerRevision);
        if (!importAsExported && !baseRevision) {
            return {
                ok: false,
                reason: "missing_target_revision",
                statusMessage: t("Der geladene Zielspielerstand fehlt. Lade den Zielspieler neu und prüfe den Import erneut."),
                statusType: "warning",
            };
        }

        const previewMatches = Boolean(
            currentImportPreview &&
            currentImportPreview.export_path === cleanExportPath &&
            cleanPath(currentImportPreview.world_path) === cleanWorldPath,
        );
        const importToken = currentImportPreview && currentImportPreview.import_token;
        if (!previewMatches || currentImportPreview.importable !== true || !importToken || typeof importToken !== "object") {
            return {
                ok: false,
                reason: "preview_required",
                statusMessage: t("Bitte zuerst eine passende erfolgreiche Import-Vorschau abwarten."),
                statusType: "error",
            };
        }
        const exportedPlayerKey = currentImportPreview.player ? cleanPath(currentImportPreview.player.player_key) : "";
        if (importAsExported && !exportedPlayerKey) {
            return {
                ok: false,
                reason: "missing_exported_player_key",
                statusMessage: t("Import als exportierter Spieler nicht möglich: Die Import-Vorschau enthält keinen Spieler-Key."),
                statusType: "error",
            };
        }
        const previewText = currentImportPreview.player
            ? t("Export: {player} aus {world}", { player: currentImportPreview.player.label || t("Unbekannter Spieler"), world: currentImportPreview.source_world_name || t("unbekannter Welt") }) + "\n"
            : "";
        const modeText = importAsExported
            ? t("Der Import legt den exportierten Spieler-Key direkt in der gewählten Welt an. Existiert dieser Key dort bereits, wird abgebrochen.")
            : t("Der Import überschreibt {player} direkt in der gewählten Welt.", { player: currentPlayerLabel });
        const safetyText = t("Vor dem Schreiben wird ein geprüftes Vollbackup erstellt. Der geschriebene Player-Datensatz wird bytegenau nachvalidiert und bei einem Fehler zurückgerollt. Fortfahren?");
        const loadingText = t("Importiere Spieler...");

        return {
            ok: true,
            exportPath: cleanExportPath,
            worldPath: cleanWorldPath,
            targetPlayerKey: importAsExported ? exportedPlayerKey : currentPlayerKey,
            baseRevision: importAsExported ? "" : baseRevision,
            sessionId: worldPresenceSessionId,
            importToken,
            confirmationText: previewText +
                modeText + "\n\n" +
                t("Importiert wird der komplette Player-NBT-Datensatz: Inventar, Enderchest, Position/Stats, Effekte und sonstige erhaltene NBT-Daten.") + "\n\n" +
                safetyText,
            loadingText,
            statusMessage: loadingText,
            statusType: "running",
        };
    }

    function importRequestBody({
        exportPath = "",
        worldPath = "",
        targetPlayerKey = "",
        sessionId = "",
        importAsExported = false,
        importToken = null,
        baseRevision = "",
        confirmPresenceConflict = false,
    } = {}) {
        const body = {
            export_zip: cleanPath(exportPath),
            world_path: worldPath,
            target_player_key: targetPlayerKey,
            session_id: sessionId,
            confirm_overwrite: true,
            import_as_exported_player: Boolean(importAsExported),
            import_token: importToken,
        };
        if (!importAsExported && cleanPath(baseRevision)) body.base_revision = cleanPath(baseRevision);
        if (confirmPresenceConflict) body.confirm_presence_conflict = true;
        return body;
    }

    function importOutcome(data = {}) {
        if (data.success) {
            const createdInfo = data.created_new_player ? " " + t("Neuer Spieler-Key wurde angelegt.") : "";
            const cleanupInfo = data.cleanup_warning ? ` ${t("Hinweis: {warning}", { warning: data.cleanup_warning })}` : "";
            const backupInfo = data.backup_file ? ` ${t("Sicherungsbackup: {backup}", { backup: data.backup_file })}` : "";
            const successMessage = t("Import abgeschlossen und nachvalidiert. Die gewählte Welt wurde aktualisiert.");
            const toastMessage = `${t("Import abgeschlossen und nachvalidiert.")}${createdInfo}${backupInfo}`;
            return {
                ok: true,
                writeGate: data.write_gate || null,
                toast: {
                    message: `${toastMessage}${cleanupInfo}`,
                    type: data.cleanup_warning ? "warning" : "success",
                    ms: data.cleanup_warning ? 7000 : 5000,
                },
                statusMessage: `${successMessage}${backupInfo}${cleanupInfo}`,
                statusType: data.cleanup_warning ? "warning" : "success",
                actionMessage: t("Player direkt importiert und nachvalidiert."),
                actionType: "import",
            };
        }
        const warning = [data.rollback_warning, data.cleanup_warning]
            .filter((value, index, values) => value && values.indexOf(value) === index)
            .join(" ");
        const backupInfo = data.backup_file ? ` ${t("Sicherungsbackup: {backup}", { backup: data.backup_file })}` : "";
        const cleanupInfo = warning ? ` ${t("Hinweis: {warning}", { warning })}` : "";
        const message = `${prefixedErrorMessage(data, t("Import fehlgeschlagen"))}${backupInfo}${cleanupInfo}`;
        return {
            ok: false,
            writeGate: data.write_gate || null,
            statusMessage: message,
            statusType: "error",
            toast: { message, type: "error", ms: (backupInfo || cleanupInfo) ? 9000 : 5000 },
        };
    }

    function presenceConflictRetryPlan() {
        return {
            abortedStatusMessage: t("Import wegen Bearbeitungskonflikt abgebrochen."),
            abortedStatusType: "warning",
            retryLoadingText: t("Importiere trotz bestätigtem Bearbeitungskonflikt..."),
        };
    }



    function createPlayerImportPreviewController({
        elements = {},
        withCsrf = () => ({}),
        parseJsonResponse = response => response.json(),
        getWorldPath = () => "",
        getCurrentPlayer = () => null,
        getCurrentPlayerLabel = () => t("Spieler"),
        getCurrentImportPreview = () => null,
        setCurrentImportPreview = () => {},
        writeBlocked = () => false,
        appConfig = {},
    } = {}) {
        const {
            importPathInput = null,
            importAsExportedCheckbox = null,
            importButton = null,
            targetHint = null,
            preview = null,
            openExportFolderButton = null,
        } = elements;
        let previewTimer = null;
        let previewRequestId = 0;

        function currentImportPath() {
            return importPathInput ? importPathInput.value.trim() : "";
        }

        function updatePlayerExportFolderControl() {
            if (!openExportFolderButton) return;
            const worldPath = getWorldPath();
            const dockerMode = appConfig.is_docker === true || appConfig.mode === "docker";
            const model = window.MCBEPlayerImportView.exportFolderControl({ worldPath, dockerMode });
            window.MCBEPlayerImportView.applyExportFolderControl(openExportFolderButton, model);
        }

        function updateImportControls() {
            const currentPlayer = getCurrentPlayer();
            const importAsExported = importAsExportedCheckbox && importAsExportedCheckbox.checked;
            const canOverwriteSelected = currentPlayer && currentPlayer.editable;
            const model = window.MCBEPlayerImportView.importControlsModel({
                worldPath: getWorldPath(),
                importPath: currentImportPath(),
                importAsExported,
                canOverwriteSelected,
                currentImportPreview: getCurrentImportPreview(),
                writeBlocked: writeBlocked(),
                playerLabel: getCurrentPlayerLabel(),
            });
            window.MCBEPlayerImportView.applyImportControlsModel({
                importButton,
                targetHint,
            }, model);
            updatePlayerExportFolderControl();
        }

        function renderPlayerImportPreview(data, errorMessage = "") {
            if (!preview) return;
            if (!currentImportPath()) {
                window.MCBEPlayerImportView.clearImportPreviewElement(preview);
                setCurrentImportPreview(null);
                updateImportControls();
                return;
            }

            const model = window.MCBEPlayerImportView.importPreviewHtml(data, errorMessage);
            window.MCBEPlayerImportView.applyImportPreviewModel(preview, model);
            updateImportControls();
        }

        function previewStillCurrent(exportPath, worldPath) {
            return currentImportPath() === exportPath && cleanPath(getWorldPath()) === worldPath;
        }

        async function refreshPlayerImportPreview() {
            const requestId = ++previewRequestId;
            if (previewTimer) {
                clearTimeout(previewTimer);
                previewTimer = null;
            }
            const exportPath = currentImportPath();
            const worldPath = cleanPath(getWorldPath());
            if (!exportPath) {
                setCurrentImportPreview(null);
                renderPlayerImportPreview(null);
                return;
            }
            // A refresh invalidates the old confirmation token immediately.
            // Keep the import action disabled until the matching response wins.
            setCurrentImportPreview(null);
            updateImportControls();
            if (preview) {
                window.MCBEPlayerImportView.applyImportPreviewModel(preview, window.MCBEPlayerImportView.importPreviewLoadingModel());
            }
            try {
                const res = await fetch("/api/player/import_preview", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ export_zip: exportPath, world_path: worldPath }),
                });
                const data = await parseJsonResponse(res);
                if (requestId !== previewRequestId || !previewStillCurrent(exportPath, worldPath)) return;
                if (data.success) {
                    const nextPreview = { ...data, export_path: exportPath, world_path: worldPath };
                    setCurrentImportPreview(nextPreview);
                    renderPlayerImportPreview(nextPreview);
                } else {
                    const cleanupInfo = data.cleanup_warning ? ` ${t("Hinweis: {warning}", { warning: data.cleanup_warning })}` : "";
                    const errorMessage = `${data.error || t("Unbekannter Fehler")}${cleanupInfo}`;
                    const nextPreview = {
                        export_path: exportPath,
                        world_path: worldPath,
                        importable: false,
                        error: data.error,
                        cleanup_warning: data.cleanup_warning || "",
                    };
                    setCurrentImportPreview(nextPreview);
                    renderPlayerImportPreview(nextPreview, errorMessage);
                }
            } catch (_e) {
                if (requestId !== previewRequestId || !previewStillCurrent(exportPath, worldPath)) return;
                const nextPreview = { export_path: exportPath, world_path: worldPath, importable: false, error: t("Vorschau konnte nicht geladen werden.") };
                setCurrentImportPreview(nextPreview);
                renderPlayerImportPreview(nextPreview, nextPreview.error);
            }
        }

        function schedulePlayerImportPreview() {
            previewRequestId += 1;
            setCurrentImportPreview(null);
            updateImportControls();
            if (previewTimer) clearTimeout(previewTimer);
            previewTimer = setTimeout(refreshPlayerImportPreview, 350);
        }

        return {
            currentImportPath,
            refreshPlayerImportPreview,
            renderPlayerImportPreview,
            schedulePlayerImportPreview,
            updateImportControls,
            updatePlayerExportFolderControl,
        };
    }


    function createPlayerTransferController({
        elements = {},
        withCsrf = () => ({}),
        parseJsonResponse = response => response.json(),
        getWorldPath = () => "",
        getCurrentPlayerKey = () => "",
        getCurrentPlayer = () => null,
        getCurrentPlayerRevision = () => "",
        getIsDirty = () => false,
        getCurrentImportPreview = () => null,
        getCurrentPlayerLabel = () => "",
        getWorldPresenceSessionId = () => "",
        getLastPlayerExportDir = () => "",
        setLastPlayerExportDir = () => {},
        writeBlocked = () => false,
        guardWorldWriteAction = () => false,
        updatePlayerExportFolderControl = () => {},
        updateImportControls = () => {},
        schedulePlayerImportPreview = () => {},
        refreshPlayerImportPreview = () => {},
        beginServerStatusRequest = () => null,
        renderServerStatus = () => {},
        confirmPresenceConflict = async () => false,
        showConfirmDialog = async () => false,
        showLoading = () => {},
        hideLoading = () => {},
        logStatus = () => {},
        showToast = () => {},
        recordAction = () => {},
        refreshImportedPlayer = async () => {},
    } = {}) {
        const {
            exportButton = null,
            openExportFolderButton = null,
            browseExportButton = null,
            importButton = null,
            importPathInput = null,
            importAsExportedCheckbox = null,
        } = elements;

        function logTransferStatus(key, message, type = "") {
            logStatus(message, type, { key });
        }

        async function exportPlayer() {
            const plan = exportPlayerPlan({
                worldPath: getWorldPath(),
                currentPlayerKey: getCurrentPlayerKey(),
                isDirty: getIsDirty(),
                writeBlocked: writeBlocked(),
            });
            if (!plan.ok) {
                if (plan.statusMessage) {
                    logTransferStatus(PLAYER_EXPORT_STATUS_KEY, plan.statusMessage, plan.statusType);
                }
                return;
            }
            if (plan.needsDirtyConfirmation) {
                const ok = await showConfirmDialog(plan.dirtyConfirmationText);
                if (!ok) return;
            }
            showLoading(plan.loadingText);
            logTransferStatus(PLAYER_EXPORT_STATUS_KEY, plan.statusMessage, plan.statusType);
            try {
                const res = await fetch("/api/player/export", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify(plan.requestBody),
                });
                const data = await parseJsonResponse(res);
                const outcome = exportPlayerOutcome(data);
                if (outcome.ok) {
                    setLastPlayerExportDir(window.MCBEPlayerImportView.directoryFromPath(outcome.exportPath));
                    updatePlayerExportFolderControl();
                    logTransferStatus(PLAYER_EXPORT_STATUS_KEY, outcome.statusMessage, outcome.statusType);
                    showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                    recordAction(outcome.actionMessage, outcome.actionType);
                } else {
                    logTransferStatus(PLAYER_EXPORT_STATUS_KEY, outcome.statusMessage, outcome.statusType);
                    if (outcome.toast) showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                }
            } catch (e) {
                console.error("btnExportPlayer:", e);
                logTransferStatus(PLAYER_EXPORT_STATUS_KEY, t("Verbindungsfehler beim Export."), "error");
                showToast(t("Verbindungsfehler beim Export."), "error", 5000);
            } finally {
                hideLoading();
            }
        }

        async function openExportFolder() {
            const worldPath = getWorldPath();
            if (!worldPath) return;
            try {
                const res = await fetch("/api/open_player_export_folder", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: worldPath }),
                });
                const data = await parseJsonResponse(res);
                const outcome = openExportFolderOutcome(data, getLastPlayerExportDir());
                if (outcome.ok) {
                    setLastPlayerExportDir(outcome.nextExportDir);
                    logStatus(outcome.statusMessage, outcome.statusType);
                } else {
                    logStatus(outcome.statusMessage, outcome.statusType);
                    if (outcome.toast) showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                }
            } catch (e) {
                console.error("btnOpenPlayerExportFolder:", e);
                logStatus(t("Fehler beim Öffnen des Exportordners."), "error");
                showToast(t("Fehler beim Öffnen des Exportordners."), "error", 5000);
            }
        }

        async function browseExportSelection() {
            try {
                const res = await fetch("/api/pick_player_export", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: getWorldPath() || "" }),
                });
                const data = await parseJsonResponse(res);
                const outcome = browseExportSelectionOutcome(data);
                if (outcome.ok) {
                    if (importPathInput) importPathInput.value = outcome.path;
                    schedulePlayerImportPreview();
                } else if (outcome.statusMessage) {
                    logStatus(outcome.statusMessage, outcome.statusType);
                }
            } catch (e) {
                console.error("btnBrowsePlayerExport:", e);
                logStatus(t("Fehler beim Öffnen der Dateiauswahl."), "error");
            }
        }

        async function importPlayer() {
            if (guardWorldWriteAction()) return false;
            const exportPath = String(importPathInput?.value || "").trim();
            const importAsExported = importAsExportedCheckbox && importAsExportedCheckbox.checked;
            const currentPlayer = getCurrentPlayer();
            const plan = importPlayerPlan({
                worldPath: getWorldPath(),
                exportPath,
                importAsExported,
                currentPlayerKey: getCurrentPlayerKey(),
                currentPlayerEditable: Boolean(currentPlayer && currentPlayer.editable),
                currentPlayerLabel: getCurrentPlayerLabel(),
                currentPlayerRevision: getCurrentPlayerRevision(),
                currentImportPreview: getCurrentImportPreview(),
                worldPresenceSessionId: getWorldPresenceSessionId(),
                isDirty: getIsDirty(),
            });
            if (!plan.ok) {
                if (plan.statusMessage) {
                    logTransferStatus(PLAYER_IMPORT_STATUS_KEY, plan.statusMessage, plan.statusType);
                }
                return;
            }

            const confirmed = await showConfirmDialog(plan.confirmationText);
            if (!confirmed) return;
            if (guardWorldWriteAction()) return false;

            showLoading(plan.loadingText);
            logTransferStatus(PLAYER_IMPORT_STATUS_KEY, plan.statusMessage, plan.statusType);
            try {
                const request = (confirmPresenceConflict = false) => importRequestBody({
                    exportPath: plan.exportPath,
                    worldPath: plan.worldPath,
                    targetPlayerKey: plan.targetPlayerKey,
                    sessionId: plan.sessionId,
                    importAsExported,
                    importToken: plan.importToken,
                    baseRevision: plan.baseRevision,
                    confirmPresenceConflict,
                });
                let statusRequestOrder = beginServerStatusRequest();
                const res = await fetch("/api/player/import", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify(request()),
                });
                let data = await parseJsonResponse(res);
                if (!data.success && data.presence_conflict) {
                    hideLoading();
                    const retryPlan = presenceConflictRetryPlan();
                    const proceed = await confirmPresenceConflict(data);
                    if (!proceed) {
                        logTransferStatus(
                            PLAYER_IMPORT_STATUS_KEY,
                            retryPlan.abortedStatusMessage,
                            retryPlan.abortedStatusType,
                        );
                        return;
                    }
                    if (guardWorldWriteAction()) return false;
                    showLoading(retryPlan.retryLoadingText);
                    statusRequestOrder = beginServerStatusRequest();
                    const retry = await fetch("/api/player/import", {
                        method: "POST",
                        headers: withCsrf(),
                        body: JSON.stringify(request(true)),
                    });
                    data = await parseJsonResponse(retry);
                }

                const outcome = importOutcome(data);
                if (outcome.writeGate) {
                    renderServerStatus(
                        { server_status: outcome.writeGate.server_status, write_gate: outcome.writeGate },
                        { requestOrder: statusRequestOrder, authoritativeBlock: true },
                    );
                }
                if (outcome.ok) {
                    let refreshWarning = "";
                    try {
                        await refreshImportedPlayer(plan.targetPlayerKey);
                    } catch (refreshError) {
                        refreshWarning = refreshError?.message
                            ? t("Import wurde gespeichert, aber die Spieleransicht konnte nicht aktualisiert werden: {error}", { error: refreshError.message })
                            : t("Import wurde gespeichert, aber die Spieleransicht konnte nicht aktualisiert werden. Lade die Spieler erneut.");
                    }
                    showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                    logTransferStatus(PLAYER_IMPORT_STATUS_KEY, outcome.statusMessage, outcome.statusType);
                    recordAction(outcome.actionMessage, outcome.actionType);
                    if (refreshWarning) {
                        showToast(refreshWarning, "warning", 6500);
                        logTransferStatus(PLAYER_IMPORT_STATUS_KEY, refreshWarning, "warning");
                    }
                } else {
                    logTransferStatus(PLAYER_IMPORT_STATUS_KEY, outcome.statusMessage, outcome.statusType);
                    if (outcome.toast) showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                    if (data.write_committed === true) {
                        let refreshWarning = "";
                        try {
                            await refreshImportedPlayer(plan.targetPlayerKey);
                        } catch (refreshError) {
                            refreshWarning = refreshError?.message
                                ? t("Der Zielzustand ist nach dem fehlgeschlagenen Import-Rollback unsicher und konnte nicht neu geladen werden: {error}", { error: refreshError.message })
                                : t("Der Zielzustand ist nach dem fehlgeschlagenen Import-Rollback unsicher und konnte nicht neu geladen werden. Lade die Spieler erneut.");
                        }
                        if (refreshWarning) {
                            showToast(refreshWarning, "warning", 8000);
                            logTransferStatus(PLAYER_IMPORT_STATUS_KEY, refreshWarning, "warning");
                        }
                    }
                    if (data.target_revision_stale === true) {
                        let refreshWarning = "";
                        try {
                            await refreshImportedPlayer(plan.targetPlayerKey);
                        } catch (refreshError) {
                            refreshWarning = refreshError?.message
                                ? t("Der geänderte Zielspieler konnte nicht neu geladen werden: {error}", { error: refreshError.message })
                                : t("Der geänderte Zielspieler konnte nicht neu geladen werden. Lade die Spieler erneut.");
                        }
                        if (refreshWarning) {
                            showToast(refreshWarning, "warning", 6500);
                            logTransferStatus(PLAYER_IMPORT_STATUS_KEY, refreshWarning, "warning");
                        }
                    }
                    if (data.preview_stale === true) {
                        await refreshPlayerImportPreview();
                    }
                }
            } catch (e) {
                console.error("btnImportPlayer:", e);
                logTransferStatus(PLAYER_IMPORT_STATUS_KEY, t("Verbindungsfehler beim Import."), "error");
                showToast(t("Verbindungsfehler beim Import."), "error", 5000);
            } finally {
                hideLoading();
            }
        }

        function wire() {
            exportButton?.addEventListener("click", exportPlayer);
            openExportFolderButton?.addEventListener("click", openExportFolder);
            browseExportButton?.addEventListener("click", browseExportSelection);
            importAsExportedCheckbox?.addEventListener("change", updateImportControls);
            importPathInput?.addEventListener("input", schedulePlayerImportPreview);
            importPathInput?.addEventListener("change", refreshPlayerImportPreview);
            importButton?.addEventListener("click", importPlayer);
        }

        return {
            browseExportSelection,
            exportPlayer,
            importPlayer,
            openExportFolder,
            wire,
        };
    }

    function collectPlayerImportPreviewElements(doc = document) {
        return {
            importPathInput: doc.getElementById("playerImportPath"),
            importAsExportedCheckbox: doc.getElementById("playerImportAsExportedKey"),
            importButton: doc.getElementById("btnImportPlayer"),
            targetHint: doc.getElementById("playerImportTargetHint"),
            preview: doc.getElementById("playerImportPreview"),
            openExportFolderButton: doc.getElementById("btnOpenPlayerExportFolder"),
        };
    }

    function createInventoryPlayerImportPreviewController({
        doc = document,
        withCsrf,
        parseJsonResponse,
        getWorldPath = () => "",
        getCurrentPlayer = () => null,
        getCurrentPlayerLabel = () => t("Spieler"),
        getCurrentImportPreview = () => null,
        setCurrentImportPreview = () => {},
        writeBlocked = () => false,
        appConfig = {},
    } = {}) {
        return createPlayerImportPreviewController({
            elements: collectPlayerImportPreviewElements(doc),
            withCsrf,
            parseJsonResponse,
            getWorldPath,
            getCurrentPlayer,
            getCurrentPlayerLabel,
            getCurrentImportPreview,
            setCurrentImportPreview,
            writeBlocked,
            appConfig,
        });
    }

    function collectPlayerTransferElements(doc = document) {
        return {
            exportButton: doc.getElementById("btnExportPlayer"),
            openExportFolderButton: doc.getElementById("btnOpenPlayerExportFolder"),
            browseExportButton: doc.getElementById("btnBrowsePlayerExport"),
            importButton: doc.getElementById("btnImportPlayer"),
            importPathInput: doc.getElementById("playerImportPath"),
            importAsExportedCheckbox: doc.getElementById("playerImportAsExportedKey"),
        };
    }

    function createInventoryPlayerTransferController({
        doc = document,
        withCsrf,
        parseJsonResponse,
        state = {},
        helpers = {},
    } = {}) {
        return createPlayerTransferController({
            elements: collectPlayerTransferElements(doc),
            withCsrf,
            parseJsonResponse,
            getWorldPath: state.getWorldPath,
            getCurrentPlayerKey: state.getCurrentPlayerKey,
            getCurrentPlayer: state.getCurrentPlayer,
            getCurrentPlayerRevision: state.getCurrentPlayerRevision,
            getIsDirty: state.getIsDirty,
            getCurrentImportPreview: state.getCurrentImportPreview,
            getCurrentPlayerLabel: state.getCurrentPlayerLabel,
            getWorldPresenceSessionId: state.getWorldPresenceSessionId,
            getLastPlayerExportDir: state.getLastPlayerExportDir,
            setLastPlayerExportDir: state.setLastPlayerExportDir,
            writeBlocked: helpers.writeBlocked,
            guardWorldWriteAction: helpers.guardWorldWriteAction,
            updatePlayerExportFolderControl: helpers.updatePlayerExportFolderControl,
            updateImportControls: helpers.updateImportControls,
            schedulePlayerImportPreview: helpers.schedulePlayerImportPreview,
            refreshPlayerImportPreview: helpers.refreshPlayerImportPreview,
            beginServerStatusRequest: helpers.beginServerStatusRequest,
            renderServerStatus: helpers.renderServerStatus,
            confirmPresenceConflict: helpers.confirmPresenceConflict,
            showConfirmDialog: helpers.showConfirmDialog,
            showLoading: helpers.showLoading,
            hideLoading: helpers.hideLoading,
            logStatus: helpers.logStatus,
            showToast: helpers.showToast,
            recordAction: helpers.recordAction,
            refreshImportedPlayer: helpers.refreshImportedPlayer,
        });
    }

    window.MCBEPlayerTransferLogic = {
        browseExportSelectionOutcome,
        collectPlayerImportPreviewElements,
        collectPlayerTransferElements,
        createInventoryPlayerImportPreviewController,
        createInventoryPlayerTransferController,
        createPlayerImportPreviewController,
        createPlayerTransferController,
        exportPlayerOutcome,
        exportPlayerPlan,
        importOutcome,
        importPlayerPlan,
        importRequestBody,
        openExportFolderOutcome,
        presenceConflictRetryPlan,
    };
}());
