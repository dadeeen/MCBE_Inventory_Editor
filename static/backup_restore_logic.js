(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const BACKUP_RESTORE_STATUS_KEY = "backup-restore";

    function openBackupFolderOutcome(data = {}) {
        if (data.success) {
            return {
                ok: true,
                nextBackupDir: data.path || "",
                toast: { message: t("Backupordner geöffnet."), type: "success", ms: 2500 },
            };
        }
        return {
            ok: false,
            toast: {
                message: data.error || t("Backupordner konnte nicht geöffnet werden."),
                type: "error",
                ms: 5000,
            },
        };
    }

    function restorePreviewRequestBody({ worldPath = "", filename = "" } = {}) {
        return {
            world_path: worldPath,
            backup_file: filename,
        };
    }

    function restorePreviewFailure(data = {}) {
        const message = t("Restore-Vorschau fehlgeschlagen: {error}", { error: data.error || t("Unbekannter Fehler") });
        return {
            statusMessage: message,
            statusType: "error",
            toast: {
                message,
                type: "error",
                ms: 5000,
            },
        };
    }

    function restoreCancelledOutcome() {
        return {
            statusMessage: t("Wiederherstellung abgebrochen."),
            statusType: "warning",
        };
    }

    function restoreStartPlan() {
        return {
            loadingText: t("Stelle Backup wieder her..."),
            statusMessage: t("Stelle Backup wieder her..."),
            statusType: "running",
        };
    }

    function restoreRequestBody({
        worldPath = "",
        filename = "",
        backupToken = null,
        sessionId = "",
        confirmPresenceConflict = false,
    } = {}) {
        const body = {
            world_path: worldPath,
            backup_file: filename,
            backup_token: backupToken,
            session_id: sessionId,
        };
        if (confirmPresenceConflict) body.confirm_presence_conflict = true;
        return body;
    }

    function restorePresenceConflictRetryPlan() {
        return {
            abortedStatusMessage: t("Restore wegen Bearbeitungskonflikt abgebrochen."),
            abortedStatusType: "warning",
            retryLoadingText: t("Stelle Backup trotz bestätigtem Bearbeitungskonflikt wieder her..."),
        };
    }

    function restoreOutcome(data = {}) {
        if (data.success) {
            const preRestore = data.pre_restore_backup ? ` ${t("Vorheriges Backup: {file}", { file: data.pre_restore_backup })}` : "";
            const cleanupWarning = data.cleanup_warning ? ` ${t("Hinweis: {warning}", { warning: data.cleanup_warning })}` : "";
            return {
                ok: true,
                writeGate: data.write_gate || null,
                toast: {
                    message: `${t("Backup erfolgreich wiederhergestellt.")}${preRestore}${cleanupWarning} ${t("Welt wird neu geladen...")}`,
                    type: data.cleanup_warning ? "warning" : "success",
                    ms: data.cleanup_warning ? 7000 : 5000,
                },
                reloadLoadingText: t("Welt nach Restore neu laden..."),
            };
        }
        const cleanupWarning = data.cleanup_warning ? ` ${t("Hinweis: {warning}", { warning: data.cleanup_warning })}` : "";
        const errorMessage = data.error || t("Unbekannter Fehler");
        return {
            ok: false,
            writeGate: data.write_gate || null,
            statusMessage: `${t("Restaurierung fehlgeschlagen: {error}", { error: errorMessage })}${cleanupWarning}`,
            statusType: "error",
            toast: {
                message: `${t("Wiederherstellung fehlgeschlagen: {error}", { error: errorMessage })}${cleanupWarning}`,
                type: "error",
                ms: cleanupWarning ? 9000 : 5000,
            },
        };
    }

    function restorePlayersLoadFailureOutcome(cleanupWarning = "") {
        const cleanupInfo = cleanupWarning ? ` ${t("Hinweis: {warning}", { warning: cleanupWarning })}` : "";
        return {
            ok: false,
            statusMessage: `${t("Backup wiederhergestellt, automatisches Neuladen fehlgeschlagen. Bitte Welt neu laden.")}${cleanupInfo}`,
            statusType: "warning",
            toast: {
                message: `${t("Backup wiederhergestellt, aber die Welt konnte danach nicht automatisch neu geladen werden. Bitte Welt neu laden.")}${cleanupInfo}`,
                type: "warning",
                ms: cleanupWarning ? 9000 : 7000,
            },
        };
    }

    function restoreWorldChangedOutcome() {
        return {
            statusMessage: t("Wiederherstellung abgebrochen: Die ausgewählte Welt wurde seit der Vorschau gewechselt."),
            statusType: "warning",
            toast: {
                message: t("Die ausgewählte Welt wurde seit der Restore-Vorschau gewechselt. Bitte Vorschau erneut öffnen."),
                type: "warning",
                ms: 7000,
            },
        };
    }

    function restoredPlayerReloadPlan({ players = [], preferredPlayerKey = "" } = {}) {
        const editablePlayers = Array.isArray(players) ? players.filter(player => player?.editable) : [];
        const preferredPlayer = preferredPlayerKey
            ? editablePlayers.find(player => player.player_key === preferredPlayerKey) || null
            : null;
        const playerToLoad = preferredPlayer || editablePlayers[0] || null;
        if (!playerToLoad) {
            return {
                hasEditablePlayer: false,
                statusMessage: t("Backup wiederhergestellt. Kein editierbarer Spieler gefunden."),
                statusType: "warning",
                toast: {
                    message: t("Backup wiederhergestellt. Kein editierbarer Spieler gefunden."),
                    type: "warning",
                    ms: 5200,
                },
            };
        }
        return {
            hasEditablePlayer: true,
            playerKey: playerToLoad.player_key,
            usedFallbackPlayer: Boolean(preferredPlayerKey && playerToLoad.player_key !== preferredPlayerKey),
        };
    }

    function restoredPlayerLoadOutcome({
        expectedPlayerKey = "",
        currentPlayerKey = "",
        usedFallbackPlayer = false,
    } = {}) {
        if (currentPlayerKey !== expectedPlayerKey) {
            return {
                ok: false,
                statusMessage: t("Backup wiederhergestellt, aber der Spieler konnte nicht automatisch neu geladen werden. Bitte Spieler neu laden."),
                statusType: "warning",
                toast: {
                    message: t("Backup wiederhergestellt, aber der Spieler konnte nicht automatisch neu geladen werden. Bitte Spieler neu laden."),
                    type: "warning",
                    ms: 7000,
                },
            };
        }
        if (usedFallbackPlayer) {
            return {
                ok: true,
                statusMessage: t("Backup wiederhergestellt. Der vorherige Spieler wurde nicht gefunden; erster editierbarer Spieler wurde geladen."),
                statusType: "warning",
                toast: {
                    message: t("Backup wiederhergestellt. Vorheriger Spieler nicht gefunden; erster editierbarer Spieler geladen."),
                    type: "warning",
                    ms: 5200,
                },
            };
        }
        return {
            ok: true,
            statusMessage: t("Backup wiederhergestellt. Spieler wurde aus dem wiederhergestellten Stand neu geladen."),
            statusType: "success",
        };
    }



    function createBackupRestoreController({
        elements = {},
        withCsrf = () => ({}),
        parseJsonResponse = response => response.json(),
        getWorldPath = () => "",
        getWorldName = () => t("Geladene Welt"),
        getCurrentPlayerKey = () => "",
        getPlayers = () => [],
        setPlayers = () => {},
        getWorldPresenceSessionId = () => "",
        confirmPresenceConflict = async () => false,
        clearLoadError = () => {},
        resetLoadedPlayerState = () => {},
        loadPlayersList = async () => false,
        loadBackupsList = async () => {},
        beginServerStatusRequest = () => null,
        renderWriteGate = () => {},
        renderPlayersList = () => {},
        renderPlayerToolOptions = () => {},
        renderWorldAnalysis = () => {},
        updateWorldPresence = async () => {},
        setWorkflowView = () => {},
        loadPlayer = async () => {},
        showLoading = () => {},
        hideLoading = () => {},
        logStatus = () => {},
        showToast = () => {},
    } = {}) {
        const {
            overlay = null,
            summary = null,
            confirmInput = null,
            confirmButton = null,
            cancelButton = null,
            closeButton = null,
        } = elements;

        function logRestoreStatus(message, type = "") {
            logStatus(message, type, { key: BACKUP_RESTORE_STATUS_KEY });
        }

        function renderRestoreReview(data, filename, targetWorld = {}) {
            if (!summary) return;
            const model = window.MCBERestoreReview.restoreReviewModel(data, filename, {
                worldName: targetWorld.worldName || getWorldName(),
                worldPath: targetWorld.worldPath || getWorldPath(),
            });
            summary.innerHTML = window.MCBERestoreReview.restoreReviewHtml(model);
        }

        function openRestoreReview(preview, filename, targetWorld = {}) {
            renderRestoreReview(preview, filename, targetWorld);
            return new Promise(resolve => {
                if (!overlay) {
                    resolve(true);
                    return;
                }
                const required = t("WIEDERHERSTELLEN");
                const cleanup = (value) => {
                    overlay.style.display = "none";
                    confirmButton?.removeEventListener("click", onConfirm);
                    cancelButton?.removeEventListener("click", onCancel);
                    closeButton?.removeEventListener("click", onCancel);
                    overlay.removeEventListener("click", onOverlayClick);
                    confirmInput?.removeEventListener("input", onInput);
                    document.removeEventListener("keydown", onKeyDown);
                    resolve(value);
                };
                const onConfirm = () => cleanup(true);
                const onCancel = () => cleanup(false);
                const onOverlayClick = (event) => { if (event.target === overlay) cleanup(false); };
                const onKeyDown = (event) => { if (event.key === "Escape") cleanup(false); };
                const onInput = () => {
                    if (confirmButton) confirmButton.disabled = String(confirmInput?.value || "").trim().toUpperCase() !== required;
                };
                if (confirmInput) confirmInput.value = "";
                if (confirmButton) confirmButton.disabled = true;
                confirmButton?.addEventListener("click", onConfirm);
                cancelButton?.addEventListener("click", onCancel);
                closeButton?.addEventListener("click", onCancel);
                overlay.addEventListener("click", onOverlayClick);
                confirmInput?.addEventListener("input", onInput);
                document.addEventListener("keydown", onKeyDown);
                overlay.style.display = "flex";
                setTimeout(() => confirmInput?.focus(), 40);
            });
        }

        async function loadRestorePreview(filename, worldPath = getWorldPath()) {
            const res = await fetch("/api/backup/restore_preview", {
                method: "POST",
                headers: withCsrf(),
                body: JSON.stringify(restorePreviewRequestBody({
                    worldPath,
                    filename,
                })),
            });
            return await parseJsonResponse(res);
        }

        async function reloadWorldAfterRestore(preferredPlayerKey = "", cleanupWarning = "") {
            const cleanupInfo = cleanupWarning
                ? ` ${t("Hinweis: {warning}", { warning: cleanupWarning })}`
                : "";
            clearLoadError();
            resetLoadedPlayerState({ showEmptyState: false });
            setPlayers([]);

            const playersLoaded = await loadPlayersList(false);
            await loadBackupsList();

            if (!playersLoaded) {
                const outcome = restorePlayersLoadFailureOutcome(cleanupWarning);
                logRestoreStatus(outcome.statusMessage, outcome.statusType);
                showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                return false;
            }

            const reloadPlan = restoredPlayerReloadPlan({
                players: getPlayers(),
                preferredPlayerKey,
            });

            if (!reloadPlan.hasEditablePlayer) {
                renderPlayersList();
                renderPlayerToolOptions();
                renderWorldAnalysis();
                await updateWorldPresence();
                setWorkflowView("player", { scroll: false });
                logRestoreStatus(`${reloadPlan.statusMessage}${cleanupInfo}`, reloadPlan.statusType);
                showToast(reloadPlan.toast.message, reloadPlan.toast.type, reloadPlan.toast.ms);
                return true;
            }

            await loadPlayer(reloadPlan.playerKey, true, { showLoadingOverlay: false });
            const reloadOutcome = restoredPlayerLoadOutcome({
                expectedPlayerKey: reloadPlan.playerKey,
                currentPlayerKey: getCurrentPlayerKey(),
                usedFallbackPlayer: reloadPlan.usedFallbackPlayer,
            });
            if (!reloadOutcome.ok) {
                logRestoreStatus(`${reloadOutcome.statusMessage}${cleanupInfo}`, reloadOutcome.statusType);
                showToast(
                    `${reloadOutcome.toast.message}${cleanupInfo}`,
                    reloadOutcome.toast.type,
                    cleanupWarning ? 9000 : reloadOutcome.toast.ms,
                );
                return false;
            }
            logRestoreStatus(
                `${reloadOutcome.statusMessage}${cleanupInfo}`,
                cleanupWarning ? "warning" : reloadOutcome.statusType,
            );
            if (reloadOutcome.toast) showToast(reloadOutcome.toast.message, reloadOutcome.toast.type, reloadOutcome.toast.ms);
            return true;
        }

        async function restoreBackup(filename) {
            const previewWorldPath = getWorldPath();
            const previewWorldName = getWorldName();
            showLoading(t("Lade Restore-Vorschau..."));
            let preview = null;
            try {
                preview = await loadRestorePreview(filename, previewWorldPath);
                if (!preview.success) {
                    hideLoading();
                    const outcome = restorePreviewFailure(preview);
                    logRestoreStatus(outcome.statusMessage, outcome.statusType);
                    showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                    return;
                }
            } catch (e) {
                hideLoading();
                const message = t("Restore-Vorschau konnte nicht geladen werden: {error}", { error: e.message });
                logRestoreStatus(message, "error");
                showToast(message, "error", 5000);
                return;
            } finally {
                hideLoading();
            }

            const confirmed = await openRestoreReview(preview, filename, {
                worldName: previewWorldName,
                worldPath: previewWorldPath,
            });
            if (!confirmed) {
                const outcome = restoreCancelledOutcome();
                logRestoreStatus(outcome.statusMessage, outcome.statusType);
                return;
            }

            if (getWorldPath() !== previewWorldPath) {
                const outcome = restoreWorldChangedOutcome();
                logRestoreStatus(outcome.statusMessage, outcome.statusType);
                showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                return;
            }

            const restoredWorldPath = previewWorldPath;
            const preferredPlayerKey = getCurrentPlayerKey();
            const startPlan = restoreStartPlan();
            showLoading(startPlan.loadingText);
            logRestoreStatus(startPlan.statusMessage, startPlan.statusType);
            try {
                const request = (confirmPresenceConflict = false) => restoreRequestBody({
                    worldPath: restoredWorldPath,
                    filename,
                    backupToken: preview.backup_token,
                    sessionId: getWorldPresenceSessionId(),
                    confirmPresenceConflict,
                });
                let statusRequestOrder = beginServerStatusRequest();
                const res = await fetch("/api/restore_backup", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify(request()),
                });
                let data = await parseJsonResponse(res);
                if (!data.success && data.presence_conflict) {
                    hideLoading();
                    const retryPlan = restorePresenceConflictRetryPlan();
                    const proceed = await confirmPresenceConflict(data);
                    if (!proceed) {
                        logRestoreStatus(retryPlan.abortedStatusMessage, retryPlan.abortedStatusType);
                        return;
                    }
                    showLoading(retryPlan.retryLoadingText);
                    statusRequestOrder = beginServerStatusRequest();
                    const retry = await fetch("/api/restore_backup", {
                        method: "POST",
                        headers: withCsrf(),
                        body: JSON.stringify(request(true)),
                    });
                    data = await parseJsonResponse(retry);
                }
                const outcome = restoreOutcome(data);
                if (outcome.writeGate) {
                    renderWriteGate(outcome.writeGate, { requestOrder: statusRequestOrder });
                }
                if (!outcome.ok) {
                    logRestoreStatus(outcome.statusMessage, outcome.statusType);
                    if (outcome.toast) showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                    return;
                }
                try {
                    const reloaded = await reloadWorldAfterRestore(preferredPlayerKey, data.cleanup_warning || "");
                    if (reloaded) {
                        showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                    }
                } catch (reloadError) {
                    console.error("reloadWorldAfterRestore:", reloadError);
                    const reloadFailure = restorePlayersLoadFailureOutcome(data.cleanup_warning || "");
                    logRestoreStatus(reloadFailure.statusMessage, reloadFailure.statusType);
                    showToast(reloadFailure.toast.message, reloadFailure.toast.type, reloadFailure.toast.ms);
                }
            } catch (e) {
                console.error("restoreBackup:", e);
                logRestoreStatus(t("Fehler bei der Verbindung zur Wiederherstellung."), "error");
                showToast(t("Fehler bei der Verbindung zur Wiederherstellung."), "error", 5000);
            } finally {
                hideLoading();
            }
        }

        return {
            loadRestorePreview,
            openRestoreReview,
            reloadWorldAfterRestore,
            renderRestoreReview,
            restoreBackup,
        };
    }


    function createConfiguredBackupRestoreController({
        doc = document,
        api = {},
        state = {},
        flow = {},
        helpers = {},
    } = {}) {
        return createBackupRestoreController({
            elements: {
                overlay: doc.getElementById("restoreReviewOverlay"),
                summary: doc.getElementById("restoreReviewSummary"),
                confirmInput: doc.getElementById("restoreConfirmInput"),
                confirmButton: doc.getElementById("btnRestoreReviewConfirm"),
                cancelButton: doc.getElementById("btnRestoreReviewCancel"),
                closeButton: doc.getElementById("btnRestoreReviewClose"),
            },
            withCsrf: api.withCsrf,
            parseJsonResponse: api.parseJsonResponse,
            getWorldPath: state.getWorldPath,
            getWorldName: state.getWorldName,
            getCurrentPlayerKey: state.getCurrentPlayerKey,
            getPlayers: state.getPlayers,
            setPlayers: state.setPlayers,
            getWorldPresenceSessionId: state.getWorldPresenceSessionId,
            confirmPresenceConflict: flow.confirmPresenceConflict,
            clearLoadError: flow.clearLoadError,
            resetLoadedPlayerState: flow.resetLoadedPlayerState,
            loadPlayersList: flow.loadPlayersList,
            loadBackupsList: flow.loadBackupsList,
            beginServerStatusRequest: flow.beginServerStatusRequest,
            renderWriteGate: flow.renderWriteGate,
            renderPlayersList: flow.renderPlayersList,
            renderPlayerToolOptions: flow.renderPlayerToolOptions,
            renderWorldAnalysis: flow.renderWorldAnalysis,
            updateWorldPresence: flow.updateWorldPresence,
            setWorkflowView: flow.setWorkflowView,
            loadPlayer: flow.loadPlayer,
            showLoading: helpers.showLoading,
            hideLoading: helpers.hideLoading,
            logStatus: helpers.logStatus,
            showToast: helpers.showToast,
        });
    }

    window.MCBEBackupRestoreLogic = {
        createBackupRestoreController,
        createConfiguredBackupRestoreController,
        openBackupFolderOutcome,
        restoreCancelledOutcome,
        restoreOutcome,
        restorePlayersLoadFailureOutcome,
        restorePresenceConflictRetryPlan,
        restorePreviewFailure,
        restorePreviewRequestBody,
        restoreRequestBody,
        restoreStartPlan,
        restoreWorldChangedOutcome,
        restoredPlayerLoadOutcome,
        restoredPlayerReloadPlan,
    };
}());
