(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const SAVE_STATUS_KEY = "player-save";

    function createSaveController(deps) {
        const {
            applyCreatedTagState,
            buildChangeSummary,
            buildSavePayload,
            finalizePendingMounts = () => {},
            confirmPresenceConflict,
            currentPlayerLabel,
            flashSaveButton,
            getCreateRequiresConfirmation,
            getCurrentPlayerKey,
            getCurrentWriteGate,
            getIsDirty,
            getPendingMounts = () => [],
            getWorldPath,
            hideLoading,
            loadBackupsList,
            logStatus,
            markReloadRequired = () => {},
            markCleanState,
            normalizeOriginsToCurrentSavedState,
            openSaveReview,
            payloadContainsUserChanges,
            postSavePayload,
            recordAction,
            renderWriteGate,
            setPrimarySaveDisabled,
            setReviewConfirmDisabled,
            showConfirmDialog,
            showLoading,
            showToast,
            updateCurrentPlayerRevision,
            updateWorldPresence,
            updateWriteControls,
            validateInventoryState,
            writeBlocked,
        } = deps;

        function logSaveStatus(message, type = "") {
            logStatus(message, type, { key: SAVE_STATUS_KEY });
        }

        async function confirmMissingTagCreates(payload) {
            const createFlags = getCreateRequiresConfirmation();
            if (createFlags.inventory && Array.isArray(payload.inventory) && payload.inventory.length > 0) {
                const ok = await showConfirmDialog(
                    t("Dieser Spieler hat aktuell keinen Inventory-Tag. Wenn du Inventar-Slots speicherst, legt die App erstmals einen neuen Bedrock-Inventory-Tag an.") + " " +
                    t("Das ist absichtlich möglich, aber nicht automatisch.") + " " + t("Wirklich ein neues Inventar für diesen Spieler anlegen?")
                );
                if (!ok) {
                    logSaveStatus(t("Speichern abgebrochen: Inventory-Tag wurde nicht angelegt."), "warning");
                    return false;
                }
                payload.allow_create_inventory = true;
            }
            if (createFlags.enderChest && Array.isArray(payload.ender_chest) && payload.ender_chest.length > 0) {
                const ok = await showConfirmDialog(
                    t("Dieser Spieler hat aktuell keinen EnderChestInventory-Tag. Wenn du Enderchest-Slots speicherst, legt die App erstmals eine neue Bedrock-Enderchest-Liste an.") + " " +
                    t("Das ist absichtlich möglich, aber nicht automatisch.") + " " + t("Wirklich eine neue Enderchest-Liste für diesen Spieler anlegen?")
                );
                if (!ok) {
                    logSaveStatus(t("Speichern abgebrochen: EnderChestInventory-Tag wurde nicht angelegt."), "warning");
                    return false;
                }
                payload.allow_create_ender_chest = true;
            }
            if (createFlags.effects && Array.isArray(payload.effects) && payload.effects.length > 0) {
                const ok = await showConfirmDialog(
                    t("Dieser Spieler hat aktuell keinen ActiveEffects-Tag. Wenn du aktive Effekte speicherst, legt die App erstmals eine neue Bedrock-Effektliste an.") + " " +
                    t("Das ist absichtlich möglich, aber nicht automatisch.") + " " + t("Wirklich eine neue Effektliste anlegen?")
                );
                if (!ok) {
                    logSaveStatus(t("Speichern abgebrochen: ActiveEffects-Tag wurde nicht angelegt."), "warning");
                    return false;
                }
                payload.allow_create_effects = true;
            }
            if (createFlags.abilities && payload.abilities && Object.keys(payload.abilities).some(key => key !== "_opaque")) {
                const ok = await showConfirmDialog(
                    t("Dieser Spieler hat aktuell keinen abilities-Tag. Wenn du Fähigkeiten speicherst, legt die App erstmals einen neuen Bedrock-abilities-Compound an.") + " " +
                    t("Das ist absichtlich möglich, aber nicht automatisch.") + " " + t("Wirklich Fähigkeiten für diesen Spieler anlegen?")
                );
                if (!ok) {
                    logSaveStatus(t("Speichern abgebrochen: abilities-Tag wurde nicht angelegt."), "warning");
                    return false;
                }
                payload.allow_create_abilities = true;
            }
            return true;
        }

        async function confirmUnknownServerStatus(writeGate) {
            if (!writeGate?.requires_unknown_server_confirmation) return false;
            renderWriteGate(writeGate);
            hideLoading();
            const status = writeGate.server_status || {};
            const detailText = [
                writeGate.reason,
                status.message,
                status.server_host ? `Server: ${status.server_host}:${status.server_port || "?"}` : "",
            ].filter(Boolean).join("\n");
            const ok = await showConfirmDialog(
                t("Der Serverstatus konnte nicht sicher geprüft werden. Es wurde noch nichts geschrieben.") + "\n\n" +
                t("Bestätige nur, wenn du sicher bist, dass Minecraft bzw. der Bedrock-Server diese Welt nicht geöffnet hat.") + " " +
                t("Wenn der Server beim erneuten Prüfversuch online erkannt wird, blockiert die App den Schreibvorgang weiterhin."),
                {
                    okLabel: t("Ich bin sicher, der Server ist gestoppt"),
                    cancelLabel: t("Nicht speichern"),
                    detailLabel: t("Statusprüfung"),
                    detailText,
                }
            );
            if (!ok) {
                logSaveStatus(t("Speichern abgebrochen: Serverstatus wurde nicht bestätigt."), "warning");
                showToast(t("Speichern abgebrochen: Serverstatus nicht bestätigt."), "warning", 5000);
                return false;
            }
            logSaveStatus(t("Serverstatus unbekannt wurde bestätigt. Schreibprüfung wird erneut ausgeführt..."), "running");
            return true;
        }

        function finalizeCommittedMountResults(results, options) {
            try {
                const outcome = finalizePendingMounts(results, options);
                return outcome && typeof outcome === "object"
                    ? outcome
                    : { complete: true, reloadRequired: false };
            } catch (error) {
                // Der Server-Commit ist bereits bestätigt. Ein Fehler beim lokalen
                // Verarbeiten optionaler Mount-Details darf deshalb weder als Erfolg
                // erscheinen noch einen erneuten Save ermöglichen.
                console.error("finalizePendingMounts:", error);
                return { complete: false, reloadRequired: true, reason: "finalize_error" };
            }
        }

        function enterReloadRequiredState(message) {
            try {
                markReloadRequired(message);
            } catch (error) {
                // Der lokale Schreibschutz ist Nachbearbeitung eines bereits
                // bestätigten Commits. Auch ein Fehler darin darf die eigentliche
                // committed-response-Behandlung nicht unterbrechen.
                console.error("markReloadRequired:", error);
            }
        }

        async function performSaveCurrentPlayer({ skipReview = false } = {}) {
            if (!getWorldPath() || !getCurrentPlayerKey() || !getIsDirty()) return;
            if (writeBlocked()) {
                const currentWriteGate = getCurrentWriteGate();
                logSaveStatus(currentWriteGate.reason || t("Schreibaktion aktuell blockiert."), "error");
                showToast(currentWriteGate.reason || t("Schreibaktion aktuell blockiert."), "error", 5000);
                return;
            }

            const saveWorldPath = getWorldPath();
            const savePlayerKey = getCurrentPlayerKey();
            const saveContextIsCurrent = () => getWorldPath() === saveWorldPath && getCurrentPlayerKey() === savePlayerKey;
            const payload = buildSavePayload();
            const hasPlayerChanges = payloadContainsUserChanges(payload);
            const pendingMounts = getPendingMounts();
            const hasForeignPendingMount = pendingMounts.some(mount => (
                (mount?.worldPath && mount.worldPath !== saveWorldPath)
                || (mount?.playerKey && mount.playerKey !== savePlayerKey)
            ));
            if (hasForeignPendingMount) {
                const message = t("Vorgemerkte Mounts gehören zu einer anderen Welt oder einem anderen Spieler. Speichern wurde zum Schutz der Weltdaten blockiert; Welt neu laden.");
                enterReloadRequiredState(message);
                logSaveStatus(message, "error");
                showToast(message, "error", 8000);
                updateWriteControls();
                return;
            }
            if (!hasPlayerChanges && pendingMounts.length === 0) {
                markCleanState();
                logSaveStatus(t("Keine speicherbaren Änderungen erkannt. Es wurde kein Backup erstellt und nichts geschrieben."), "warning");
                showToast(t("Keine speicherbaren Änderungen erkannt."), "warning", 3000);
                return;
            }
            if (hasPlayerChanges) {
                const confirmedCreates = await confirmMissingTagCreates(payload);
                if (!confirmedCreates) return;
                if (!saveContextIsCurrent()) return;
            }

            const summary = buildChangeSummary({ limit: 14, includeSections: true });
            const validation = validateInventoryState({ limit: 14 });
            if (!skipReview) {
                const confirmed = await openSaveReview(summary, validation);
                if (!confirmed) return;
                if (!saveContextIsCurrent()) return;
            } else if (validation.errors > 0) {
                logSaveStatus(t("Speichern wegen Validierungsfehlern blockiert."), "error");
                showToast(t("Speichern wegen Validierungsfehlern blockiert."), "error", 5000);
                return;
            }

            setPrimarySaveDisabled(true);
            setReviewConfirmDisabled(true);
            const wasDirty = getIsDirty();
            // Sobald der Server einen (Teil-)Commit bestätigt, darf die UI nicht mehr in
            // einen wiederholbaren Zustand zurückfallen – auch nicht, wenn die Verarbeitung
            // optionaler Mount-Details anschließend fehlschlägt.
            let writeCommitted = false;
            const shownCleanupWarnings = new Set();
            const cleanupWarningText = () => Array.from(shownCleanupWarnings).join(" ");
            const logSaveOutcome = (message, type = "") => {
                const cleanupWarning = cleanupWarningText();
                const finalMessage = cleanupWarning
                    ? `${message} ${t("Hinweis: {warning}", { warning: cleanupWarning })}`
                    : message;
                const finalType = cleanupWarning && type === "success" ? "warning" : type;
                logSaveStatus(finalMessage, finalType);
            };
            const reportChangedSaveContext = data => {
                let message = "";
                let type = "warning";
                if (data?.success || data?.write_committed === true) {
                    message = data.validation_failed === true
                        ? t("Vorheriger Spieler wurde geschrieben, aber die Nachvalidierung ist fehlgeschlagen. Nicht erneut speichern; Backup prüfen.")
                        : t("Vorheriger Spieler wurde gespeichert; aktuelle Ansicht wurde nicht überschrieben.");
                    type = data.validation_failed === true ? "error" : "warning";
                } else if (data?.error) {
                    message = t("Speicherversuch für den vorherigen Spieler fehlgeschlagen: {error}. Die aktuelle Ansicht wurde nicht verändert.", {
                        error: data.error,
                    });
                    type = "error";
                } else {
                    message = t("Speichern abgebrochen: Welt oder Spieler wurde während des Vorgangs gewechselt.");
                }
                logSaveOutcome(message, type);
                showToast(message, type, 6500);
            };
            const surfaceCleanupWarning = data => {
                const warning = String(data?.cleanup_warning || "").trim();
                if (!warning || shownCleanupWarnings.has(warning)) return;
                shownCleanupWarnings.add(warning);
                showToast(warning, "warning", 8000);
            };

            showLoading(t("Speichern läuft: Backup erstellen, Änderung schreiben, Datenbankverbindung schließen..."));
            logSaveStatus(t("Backup wird erstellt, Änderung gespeichert und DB-Verbindung geschlossen..."), "running");
            try {
                if (pendingMounts.length) {
                    showLoading(pendingMounts.length === 1
                        ? t("1 vorgemerkte Mount-Erzeugung wird gespeichert und validiert...")
                        : t("{count} vorgemerkte Mount-Erzeugungen werden gemeinsam gespeichert und validiert...", { count: pendingMounts.length }));
                }
                let data = await postSavePayload(payload, pendingMounts);
                surfaceCleanupWarning(data);
                if (!saveContextIsCurrent()) {
                    reportChangedSaveContext(data);
                    return;
                }
                if (!data.success && data.write_gate?.requires_unknown_server_confirmation && payload.confirm_unknown_server_status !== true) {
                    const proceed = await confirmUnknownServerStatus(data.write_gate);
                    if (!proceed) {
                        logSaveOutcome(t("Speichern abgebrochen: Serverstatus wurde nicht bestätigt."), "warning");
                        if (wasDirty) setPrimarySaveDisabled(false);
                        return;
                    }
                    if (!saveContextIsCurrent()) {
                        reportChangedSaveContext();
                        return;
                    }
                    payload.confirm_unknown_server_status = true;
                    showLoading(t("Serverstatus bestätigt: Schreibprüfung wird erneut ausgeführt..."));
                    data = await postSavePayload(payload, pendingMounts);
                    surfaceCleanupWarning(data);
                    if (!saveContextIsCurrent()) {
                        reportChangedSaveContext(data);
                        return;
                    }
                }
                if (!data.success && data.presence_conflict) {
                    hideLoading();
                    const proceed = await confirmPresenceConflict(data);
                    if (!proceed) {
                        logSaveOutcome(t("Speichern wegen Bearbeitungskonflikt abgebrochen."), "warning");
                        if (wasDirty) setPrimarySaveDisabled(false);
                        return;
                    }
                    if (!saveContextIsCurrent()) {
                        reportChangedSaveContext();
                        return;
                    }
                    showLoading(t("Speichere trotz bestätigtem Bearbeitungskonflikt..."));
                    payload.confirm_presence_conflict = true;
                    data = await postSavePayload(payload, pendingMounts);
                    surfaceCleanupWarning(data);
                    if (!saveContextIsCurrent()) {
                        reportChangedSaveContext(data);
                        return;
                    }
                }

                if (data.write_gate) {
                    renderWriteGate(data.write_gate);
                }
                const mountResults = Array.isArray(data.mounts) ? data.mounts : [];
                const committedWriteFailure = data.success === false && data.write_committed === true;
                if (committedWriteFailure) {
                    writeCommitted = true;
                    if (pendingMounts.length) {
                        finalizeCommittedMountResults(mountResults, { validationFailed: true });
                    }
                    updateCurrentPlayerRevision(data.player_revision);
                    if (hasPlayerChanges) {
                        applyCreatedTagState(payload);
                        normalizeOriginsToCurrentSavedState(data.item_source_digests);
                    }
                    markCleanState();
                    await updateWorldPresence();
                    loadBackupsList();
                    const message = data.error || t("Die Änderungen wurden geschrieben, aber die Nachprüfung ist fehlgeschlagen. Nicht erneut speichern; Backup prüfen.");
                    enterReloadRequiredState(message);
                    logSaveOutcome(message, "error");
                    showToast(message, "error", 8000);
                    recordAction(t("Geschrieben, Nachvalidierung fehlgeschlagen. Backup: {backup}", { backup: data.backup_file || t("erstellt") }), "error");
                } else if (data.success) {
                    const noWritePerformed = data.no_op === true && mountResults.length === 0;
                    writeCommitted = !noWritePerformed;
                    const mountFinalization = pendingMounts.length
                        ? finalizeCommittedMountResults(mountResults)
                        : { complete: true, reloadRequired: false };
                    showLoading(t("Speichern abschließen: Antwort prüfen und UI aktualisieren..."));
                    updateCurrentPlayerRevision(data.player_revision);
                    if (mountFinalization.reloadRequired === true) {
                        if (hasPlayerChanges) {
                            applyCreatedTagState(payload);
                            normalizeOriginsToCurrentSavedState(data.item_source_digests);
                        }
                        markCleanState();
                        await updateWorldPresence();
                        loadBackupsList();
                        const message = mountFinalization.reason === "count_mismatch"
                            ? t("Änderungen wurden geschrieben, aber die Mount-Antwort des Servers ist unvollständig. Nicht erneut speichern; Welt neu laden und Backup prüfen.")
                            : t("Änderungen wurden geschrieben, aber die Mount-Nachbearbeitung ist fehlgeschlagen. Nicht erneut speichern; Welt neu laden und Backup prüfen.");
                        enterReloadRequiredState(message);
                        logSaveOutcome(message, "error");
                        showToast(message, "error", 8000);
                        recordAction(t("Geschrieben, Neuladen erforderlich. Backup: {backup}", { backup: data.backup_file || t("erstellt") }), "error");
                    } else if (noWritePerformed) {
                        if (hasPlayerChanges) {
                            // The save response is authoritative even when bytes match.
                            // Refresh provenance before marking the UI clean.
                            normalizeOriginsToCurrentSavedState(data.item_source_digests);
                        }
                        markCleanState();
                        await updateWorldPresence();
                        const message = data.message || t("Keine Änderungen erkannt. Es wurde nichts geschrieben.");
                        logSaveOutcome(message, "warning");
                        showToast(t("Keine speicherbaren Änderungen erkannt."), "warning", 3000);
                        recordAction(t("Speichern übersprungen: keine Änderung"), "save");
                    } else {
                        if (hasPlayerChanges) {
                            applyCreatedTagState(payload);
                            normalizeOriginsToCurrentSavedState(data.item_source_digests);
                        }
                        markCleanState();
                        await updateWorldPresence();
                        const mountText = mountResults.length ? ` · ${mountResults.length === 1 ? t("1 Mount erzeugt") : t("{count} Mounts erzeugt", { count: mountResults.length })}` : "";
                        logSaveOutcome(t("Änderungen gespeichert{mounts}. Backup: {backup}", { mounts: mountText, backup: data.backup_file || mountResults[0]?.backup_file || t("erstellt") }), "success");
                        loadBackupsList();
                        showToast(t("Änderungen gespeichert{mounts}. Sicherung: {backup}", { mounts: mountText, backup: data.backup_file || mountResults[0]?.backup_file || t("erstellt") }), "success", 4500);
                        recordAction(t("Gespeichert. Backup: {backup}", { backup: data.backup_file || t("erstellt") }), "save");
                        flashSaveButton();
                    }
                } else {
                    if (data.write_gate) {
                        renderWriteGate(data.write_gate);
                    }
                    logSaveOutcome(t("Fehler beim Speichern: {error}", { error: data.error }), "error");
                    showToast(t("Fehler beim Speichern: {error}", { error: data.error }), "error", 5000);
                    if (wasDirty) setPrimarySaveDisabled(false);
                }
            } catch (e) {
                console.error("saveCurrentPlayer:", e);
                if (writeCommitted) {
                    // Der Schreibvorgang ist bestätigt. Der Fehler betrifft nur die
                    // Nachbearbeitung; ein erneutes Speichern würde denselben Batch
                    // doppelt schreiben. Button gesperrt lassen, Neuladen empfehlen.
                    const message = t("Änderungen wurden geschrieben, aber die Nachbearbeitung ist fehlgeschlagen. Nicht erneut speichern; Welt neu laden und Backup prüfen.");
                    enterReloadRequiredState(message);
                    logSaveOutcome(message, "error");
                    showToast(message, "error", 8000);
                } else if (pendingMounts.length) {
                    // Bei einem Transport-/Parsingfehler kann der atomare Workspace-
                    // Batch bereits committed worden sein, obwohl keine auswertbare
                    // Antwort angekommen ist. Ein erneuter Save könnte die Mounts mit
                    // neuen Actor-IDs doppelt erzeugen; deshalb bleibt Schreiben bis
                    // zum Neuladen gesperrt.
                    const message = t("Die Verbindung wurde während der Mount-Speicherung unterbrochen. Ob der Batch bereits geschrieben wurde, ist unbekannt. Nicht erneut speichern; Welt neu laden und Backup prüfen.");
                    enterReloadRequiredState(message);
                    logSaveOutcome(message, "error");
                    showToast(message, "error", 8000);
                } else {
                    const message = e?.message || t("Verbindungsfehler beim Speichern.");
                    logSaveOutcome(t("Fehler beim Speichern: {error}", { error: message }), "error");
                    showToast(t("Fehler beim Speichern: {error}", { error: message }), "error", 5000);
                    if (wasDirty) setPrimarySaveDisabled(false);
                }
            } finally {
                setReviewConfirmDisabled(false);
                hideLoading();
                updateWriteControls();
            }
        }

        let activeSavePromise = null;

        function saveCurrentPlayer(options = {}) {
            if (activeSavePromise) return activeSavePromise;
            const attempt = performSaveCurrentPlayer(options);
            const trackedAttempt = attempt.finally(() => {
                if (activeSavePromise === trackedAttempt) activeSavePromise = null;
            });
            activeSavePromise = trackedAttempt;
            return trackedAttempt;
        }

        return {
            confirmMissingTagCreates,
            confirmUnknownServerStatus,
            saveCurrentPlayer,
        };
    }


    function createdTagStatePatch(payload = {}, { currentPlayer = null, protectedNbt = null } = {}) {
        const patch = {};
        if (payload.allow_create_inventory) {
            patch.inventoryCreateRequiresConfirmation = false;
            if (currentPlayer) currentPlayer.has_inventory_tag = true;
            if (protectedNbt) protectedNbt.has_inventory_tag = true;
        }
        if (payload.allow_create_ender_chest) {
            patch.enderChestCreateRequiresConfirmation = false;
            patch.hasEnderChest = true;
            if (currentPlayer) currentPlayer.has_ender_chest_tag = true;
            if (protectedNbt) protectedNbt.has_ender_chest_tag = true;
        }
        if (payload.allow_create_effects) {
            patch.effectsCreateRequiresConfirmation = false;
            if (protectedNbt) protectedNbt.has_active_effects_tag = true;
        }
        if (payload.allow_create_abilities) {
            patch.abilitiesCreateRequiresConfirmation = false;
            if (protectedNbt) protectedNbt.has_abilities_tag = true;
        }
        return patch;
    }


    function createSaveAppController(deps = {}) {
        const {
            logic = {},
            payload = {},
            controller = {},
        } = deps;
        let saveLogic = null;
        let savePayloadLogic = null;
        let saveController = null;

        function getSaveLogic() {
            if (!saveLogic) {
                saveLogic = window.MCBESaveLogic.createSaveLogic(logic);
            }
            return saveLogic;
        }

        function getSavePayloadLogic() {
            if (!savePayloadLogic) {
                savePayloadLogic = window.MCBESavePayloadLogic.createSavePayloadLogic(payload);
            }
            return savePayloadLogic;
        }

        function getSaveController() {
            if (!saveController) {
                saveController = createSaveController({
                    ...controller,
                    buildSavePayload: () => getSavePayloadLogic().buildSavePayload(),
                });
            }
            return saveController;
        }

        return {
            buildChangedStatsPayload: () => getSavePayloadLogic().buildChangedStatsPayload(),
            buildChangeSummary: options => getSaveLogic().buildChangeSummary(options),
            buildChangeSummaryText: (summary, validation) => getSaveLogic().buildChangeSummaryText(summary, validation),
            changeKindLabel: kind => getSaveLogic().changeKindLabel(kind),
            collectEditorDecisionDetails: (summary, validation) => getSaveLogic().collectEditorDecisionDetails(summary, validation),
            decisionLogText: (summary, validation) => getSaveLogic().decisionLogText(summary, validation),
            saveCurrentPlayer: options => getSaveController().saveCurrentPlayer(options),
            shouldSyncAbilitiesFromUIForSave: () => getSavePayloadLogic().shouldSyncAbilitiesFromUIForSave(),
            validateInventoryState: options => getSaveLogic().validateInventoryState(options),
        };
    }

    function createConfiguredSaveAppController(deps = {}) {
        const {
            api = {},
            constants = {},
            helpers = {},
            itemCatalog = {},
            state = {},
            ui = {},
        } = deps;
        const {
            fetchFn = fetch,
            parseJsonResponse = async res => res.json(),
            withCsrf = () => ({}),
        } = api;
        const {
            maxBedrockStackCount = 127,
        } = constants;
        const {
            assignAppState = () => {},
            beginServerStatusRequest = () => null,
            buildChangeSummary = () => ({}),
            collectAbilitiesFromUI = () => ({}),
            finalizePendingMounts = () => {},
            confirmPresenceConflict = async () => false,
            currentPlayerLabel = () => t("Spieler"),
            hideLoading = () => {},
            itemDisplayName = item => item?.Name || item?.id || "Item",
            itemIsVisiblePresent = () => false,
            itemRequiresOriginalNbt = () => false,
            loadBackupsList = () => {},
            logStatus = () => {},
            markReloadRequired = () => {},
            markCleanState = () => {},
            normalizeOriginsToCurrentSavedState = () => {},
            openSaveReview = async () => false,
            recordAction = () => {},
            removeProtectedStatsFromPayload = payload => payload,
            renderServerStatus = () => {},
            sectionChanged = () => false,
            showConfirmDialog = async () => false,
            showLoading = () => {},
            showToast = () => {},
            slotDisplayName = () => "Slot",
            syncEffectsFromUI = () => [],
            takeSnapshot = () => ({}),
            updateWorldPresence = async () => {},
            updateWriteControls = () => {},
            validateInventoryState = () => ({ errors: 0 }),
            writeBlocked = () => false,
        } = helpers;
        const {
            saveButton = null,
            saveReviewConfirmButton = null,
            flashDurationMs = 1500,
            getWorldLabel = () => t("Geladene Welt"),
        } = ui;

        let saveAppController = null;
        const saveStatusRequestOrders = new WeakMap();
        const getCreateRequiresConfirmation = () => ({
            inventory: state.getInventoryCreateRequiresConfirmation?.() || false,
            enderChest: state.getEnderChestCreateRequiresConfirmation?.() || false,
            effects: state.getEffectsCreateRequiresConfirmation?.() || false,
            abilities: state.getAbilitiesCreateRequiresConfirmation?.() || false,
        });
        const getCleanSnapshot = () => state.getCleanSnapshot?.() || null;

        function flashSaveButton() {
            if (!saveButton) return;
            saveButton.classList.add("save-flash");
            setTimeout(() => saveButton.classList.remove("save-flash"), flashDurationMs);
        }

        async function postSavePayload(payload, pendingMountsOverride = null) {
            const statusRequestOrder = beginServerStatusRequest();
            const pendingMounts = Array.isArray(pendingMountsOverride)
                ? pendingMountsOverride
                : (state.getPendingMounts?.() || []);
            const requestPayload = { ...payload };
            if (pendingMounts.length) {
                requestPayload.mounts = pendingMounts.map(mount => ({
                    mount_type: mount.mountType,
                    create_mode: mount.createMode,
                    placement_radius: mount.placementRadius,
                    preferred_offset: mount.preferredOffset,
                    horse_profile: mount.horseProfile,
                    mount_stats: mount.mountStats,
                    tamed: mount.tamed === true,
                    allow_unchecked_placement: mount.allowUncheckedPlacement === true,
                }));
            }
            const res = await fetchFn(pendingMounts.length ? "/api/workspace/save" : "/api/player/save", {
                method: "POST",
                headers: withCsrf(),
                body: JSON.stringify(requestPayload),
            });
            const data = await parseJsonResponse(res);
            if (data?.write_gate && typeof data.write_gate === "object") {
                saveStatusRequestOrders.set(data.write_gate, statusRequestOrder);
            }
            return data;
        }

        saveAppController = createSaveAppController({
            logic: {
                buildChangedStatsPayload: () => saveAppController.buildChangedStatsPayload(),
                currentPlayerLabel,
                getCleanSnapshot,
                getCreateRequiresConfirmation,
                getCurrentWriteGate: () => state.getCurrentWriteGate?.(),
                getEnchantmentsDb: () => state.getEnchantmentsDb?.() || {},
                getEnderChestInventory: () => state.getEnderChestInventory?.() || {},
                getHasEnderChest: () => state.getHasEnderChest?.() || false,
                getHiddenUnknownSlots: () => state.getHiddenUnknownSlots?.() || {},
                getInventory: () => state.getInventory?.() || {},
                getPendingMounts: () => state.getPendingMounts?.() || [],
                getPlayerAbilities: () => state.getPlayerAbilities?.() || {},
                getPlayerEffects: () => state.getPlayerEffects?.() || [],
                getProtectedKnownSlots: () => state.getProtectedKnownSlots?.() || {},
                getProtectedNbt: () => state.getProtectedNbt?.() || {},
                getWorldLabel,
                getMaxDamage: itemCatalog.getMaxDamage,
                getMaxStack: itemCatalog.getMaxStack,
                hasMeaningfulObjectKeys: window.MCBESavePayloadLogic.hasMeaningfulObjectKeys,
                itemDisplayName,
                itemIsVisiblePresent,
                isKnownItemId: itemCatalog.isKnownItemId,
                isValidItemId: itemCatalog.isValidItemId,
                maxBedrockStackCount,
                sectionChanged,
                slotDisplayName,
                takeSnapshot,
                writeBlocked,
            },
            payload: {
                collectAbilitiesFromUI,
                getAbilitiesTouched: () => state.getAbilitiesTouched?.() || false,
                getCleanSnapshot,
                getCurrentPlayerKey: () => state.getCurrentPlayerKey?.() || "",
                getCurrentPlayerRevision: () => state.getCurrentPlayerRevision?.() || "",
                getEnderChestInventory: () => state.getEnderChestInventory?.() || {},
                getEffectsTouched: () => state.getEffectsTouched?.() || false,
                getInventory: () => state.getInventory?.() || {},
                getPlayerAbilities: () => state.getPlayerAbilities?.() || {},
                getPlayerEffects: () => state.getPlayerEffects?.() || [],
                getPlayerStats: () => state.getPlayerStats?.() || {},
                getProtectedNbt: () => state.getProtectedNbt?.() || {},
                getServerGuardEpoch: () => state.getCurrentPlayerServerGuardEpoch?.() || 0,
                getServerGuardToken: () => state.getCurrentPlayerServerGuardToken?.() || "",
                getWorldPath: () => state.getWorldPath?.() || "",
                getWorldPresenceSessionId: () => state.getWorldPresenceSessionId?.() || "",
                itemIsVisiblePresent,
                itemRequiresOriginalNbt,
                removeProtectedStatsFromPayload,
                sectionChanged,
                setPlayerAbilities: value => state.setPlayerAbilities?.(value),
                syncEffectsFromUI,
            },
            controller: {
                applyCreatedTagState: payload => assignAppState(
                    createdTagStatePatch(payload, {
                        currentPlayer: state.getCurrentPlayer?.(),
                        protectedNbt: state.getProtectedNbt?.(),
                    })
                ),
                buildChangeSummary,
                finalizePendingMounts,
                confirmPresenceConflict,
                currentPlayerLabel,
                flashSaveButton,
                getCreateRequiresConfirmation,
                getCurrentPlayerKey: () => state.getCurrentPlayerKey?.() || "",
                getCurrentWriteGate: () => state.getCurrentWriteGate?.(),
                getIsDirty: () => state.getIsDirty?.() || false,
                getPendingMounts: () => state.getPendingMounts?.() || [],
                getWorldPath: () => state.getWorldPath?.() || "",
                hideLoading,
                loadBackupsList,
                logStatus,
                markReloadRequired,
                markCleanState,
                normalizeOriginsToCurrentSavedState,
                openSaveReview,
                payloadContainsUserChanges: window.MCBESavePayloadLogic.payloadContainsUserChanges,
                postSavePayload,
                recordAction,
                renderWriteGate: writeGate => renderServerStatus(
                    { server_status: writeGate.server_status, write_gate: writeGate },
                    { requestOrder: saveStatusRequestOrders.get(writeGate) ?? null },
                ),
                setPrimarySaveDisabled: disabled => { if (saveButton) saveButton.disabled = disabled; },
                setReviewConfirmDisabled: disabled => { if (saveReviewConfirmButton) saveReviewConfirmButton.disabled = disabled; },
                showConfirmDialog,
                showLoading,
                showToast,
                updateCurrentPlayerRevision: playerRevision => state.setCurrentPlayerRevision?.(playerRevision || state.getCurrentPlayerRevision?.() || ""),
                updateWorldPresence,
                updateWriteControls,
                validateInventoryState,
                writeBlocked,
            },
        });

        return saveAppController;
    }


    window.MCBESaveController = {
        createConfiguredSaveAppController,
        createSaveAppController,
        createSaveController,
        createdTagStatePatch,
    };
}());
