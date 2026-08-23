(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const BACKUP_CREATE_STATUS_KEY = "backup-create";
    const BACKUP_DELETE_STATUS_KEY = "backup-delete";

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function backupFolderUnavailableTitle(folderState) {
        if (folderState === "loading") return t("Backupordner wird geladen...");
        if (folderState === "unavailable") return t("Backupordner ist derzeit nicht verfügbar.");
        return t("Bitte zuerst eine Welt laden.");
    }

    function backupFolderControls({ backupDir = "", dockerMode = false, folderState = "no-world" } = {}) {
        const hasBackupDir = Boolean(String(backupDir ?? "").trim());
        const unavailableTitle = backupFolderUnavailableTitle(folderState);
        return {
            copyDisabled: !hasBackupDir,
            copyTitle: hasBackupDir ? t("Backupordner-Pfad kopieren") : unavailableTitle,
            openDisabled: !hasBackupDir || dockerMode,
            openTitle: !hasBackupDir
                ? unavailableTitle
                : dockerMode
                    ? t("Im Docker-/LAN-Modus nur Pfad kopieren.")
                    : t("Backupordner im Dateimanager öffnen"),
        };
    }

    function applyBackupFolderControls(elements = {}, model = {}) {
        const { copyButton = null, openButton = null } = elements;
        if (copyButton) {
            copyButton.disabled = Boolean(model.copyDisabled);
            copyButton.title = model.copyTitle || "";
        }
        if (openButton) {
            openButton.disabled = Boolean(model.openDisabled);
            openButton.title = model.openTitle || "";
        }
    }

    function backupSummaryHtml(data = {}) {
        const automaticText = data.max_backups_per_world
            ? t("Automatisch/Legacy: max. {count}", { count: data.max_backups_per_world })
            : t("Automatisch/Legacy: unbegrenzt");
        const recoveryText = data.max_pre_restore_backups_per_world
            ? t("Vor Wiederherstellung: max. {count}", { count: data.max_pre_restore_backups_per_world })
            : t("Vor Wiederherstellung: unbegrenzt");
        return `<div class="backup-summary">${t("Ort: {dir}", { dir: escapeHtml(data.backup_dir || t("unbekannt")) })}<br>${t("Aufbewahrung: {automatic} · {recovery} · Manuell: bis zur Löschung geschützt", { automatic: escapeHtml(automaticText), recovery: escapeHtml(recoveryText) })}</div>`;
    }

    function backupKindLabel(backup = {}) {
        // Der Server liefert kind_label bewusst in der Quellsprache. Übersetzt
        // wird an der Anzeigegrenze über die stabile kind-Kennung, damit die
        // API-Sprache nie die aktive Seitensprache überschreibt.
        if (backup.kind === "automatic") return t("Automatisch");
        if (backup.kind === "manual") return t("Manuell");
        if (backup.kind === "pre_restore") return t("Vor Wiederherstellung");
        if (backup.kind === "legacy") return t("Legacy");
        return backup.kind_label || t("Legacy");
    }

    function backupKindExplanation(backup = {}) {
        // Das Label sagt, wann ein Archiv entstand -- die Aufbewahrungsregel
        // dahinter ist aber das, was bei der Auswahl zählt: nur manuelle
        // Backups überleben jede Rotation, und Pre-Restore-Archive haben ein
        // eigenes Kontingent, damit eine Serie von Speicherungen sie nicht
        // verdrängt. Die konkreten Limits stehen in der Zusammenfassung
        // darüber und werden hier bewusst nicht wiederholt.
        if (backup.kind === "automatic") return t("Automatisch vor jedem Speichervorgang erstellt. Der älteste Eintrag entfällt, sobald das Limit erreicht ist.");
        if (backup.kind === "manual") return t("Von Hand erstellt. Bleibt erhalten, bis du es löschst.");
        if (backup.kind === "pre_restore") return t("Zustand der Welt unmittelbar vor einer Wiederherstellung. Eigenes Kontingent, unabhängig von den Speicher-Backups.");
        // Ein fehlendes kind wird oben wie legacy eingestuft -- Klasse und Label
        // sagen dann "Legacy", also muss die Erklärung mitkommen. Eine bekannte
        // Kennung, die dieses Frontend nicht kennt, bleibt dagegen ohne Erklärung:
        // über deren Rotation lässt sich hier nichts versprechen.
        if (!backup.kind || backup.kind === "legacy") return t("Älteres Archiv ohne Metadaten. Wird wie ein automatisches Backup rotiert.");
        return "";
    }

    function backupTimestamp(isoValue, fallback) {
        if (window.MCBEHtmlUtils?.formatTimestamp) return window.MCBEHtmlUtils.formatTimestamp(isoValue, fallback);
        return String(fallback ?? "");
    }

    function backupIsoTimestamp(backup = {}) {
        return backup.created_at || backup.modified_at || "";
    }

    function backupTimestampTitle(backup = {}) {
        // Die Anzeige folgt Browserzeitzone und Seitensprache; der Tooltip hält
        // den zugrunde liegenden UTC-Wert überprüfbar.
        if (backup.created_at) {
            return ` title="${escapeHtml(t("UTC-Zeitstempel: {value}", { value: backup.created_at }))}"`;
        }
        if (backup.modified_at) {
            return ` title="${escapeHtml(t("UTC-Änderungszeit: {value}", { value: backup.modified_at }))}"`;
        }
        return "";
    }

    function backupRowHtml(backup = {}, { readOnly = false } = {}) {
        const kindLabel = backupKindLabel(backup);
        const kindExplanation = backupKindExplanation(backup);
        const deleteTitle = readOnly ? t("Read-Only-Modus: Backups können nicht gelöscht werden.") : t("Backup löschen");
        const kindClass = `backup-kind backup-kind-${escapeHtml(backup.kind || "legacy")}`;
        const titleLineContents = `<span class="${kindClass}">${escapeHtml(kindLabel)}</span>
                    <span class="backup-filename" title="${escapeHtml(backup.filename)}">${escapeHtml(backup.filename)}</span>`;
        const titleBlock = kindExplanation
            ? `<details class="backup-kind-details">
                <summary class="backup-title-line" role="button" aria-expanded="false">${titleLineContents}</summary>
                <div class="backup-kind-explanation">${escapeHtml(kindExplanation)}</div>
            </details>`
            : `<div class="backup-title-line">${titleLineContents}</div>`;
        return `<div class="backup-row">
            <div class="backup-info">
                ${titleBlock}
                <span class="backup-meta"><span${backupTimestampTitle(backup)}>${escapeHtml(backupTimestamp(backupIsoTimestamp(backup), backup.date))}</span> &nbsp;•&nbsp; ${escapeHtml(backup.size_mb)} MB</span>
            </div>
            <div class="backup-actions">
                <button class="btn btn-secondary btn-sm restore-btn" type="button" data-backup-filename="${escapeHtml(backup.filename)}">🔄 ${t("Wiederherstellen")}</button>
                <button class="btn btn-secondary btn-sm delete-backup-btn" type="button" data-delete-backup-filename="${escapeHtml(backup.filename)}" title="${escapeHtml(deleteTitle)}"${readOnly ? " disabled" : ""}>🗑 ${t("Löschen")}</button>
            </div>
        </div>`;
    }

    function wireBackupKindDisclosures(root) {
        root?.querySelectorAll?.("details.backup-kind-details").forEach(details => {
            const summary = details.querySelector?.("summary.backup-title-line");
            if (!summary || summary.dataset.backupKindDisclosureWired === "true") return;

            const syncExpandedState = () => {
                summary.setAttribute("aria-expanded", details.open ? "true" : "false");
            };
            summary.dataset.backupKindDisclosureWired = "true";
            summary.addEventListener("keydown", event => {
                if (event.key !== "Enter" && event.key !== " ") return;
                // Nicht auf die browserabhängige Tastatur-Aktivierung von
                // <summary> verlassen. preventDefault verhindert dabei ein
                // zweites, natives Umschalten nach dem expliziten Toggle.
                event.preventDefault();
                details.open = !details.open;
                syncExpandedState();
            });
            details.addEventListener("toggle", syncExpandedState);
            syncExpandedState();
        });
    }

    function backupsStatusHtml(status = "loading", message = "") {
        if (status === "loading") {
            return `<div class="no-backups">${t("Lade Sicherheitskopien...")}</div>`;
        }
        if (status === "no-world") {
            // Kein Fehler, sondern eine offene Auswahl. Die rote Fehlerbox
            // würde hier suggerieren, vorhandene Backups seien unlesbar.
            return `<div class="no-backups">${t("Bitte zuerst eine Welt laden.")}</div>`;
        }
        // Die konkrete Servermeldung sagt, was zu tun ist -- "Welt-Ordner
        // existiert nicht" ist eine Handlungsanweisung, der Sammelsatz nicht.
        const errorText = String(message ?? "").trim() || t("Fehler beim Laden der Backups.");
        return `<div class="no-backups error">${escapeHtml(errorText)}</div>`;
    }

    function backupsListHtml(data = {}, { errorMessage = "" } = {}) {
        if (!data.success) {
            return backupsStatusHtml("error", errorMessage);
        }
        const backups = Array.isArray(data.backups) ? data.backups : [];
        const rows = backups.length
            ? backups.map(backup => backupRowHtml(backup, { readOnly: data.read_only === true })).join("")
            : `<div class="no-backups">${t("Keine Backups in dieser Welt gefunden.")}</div>`;
        return backupSummaryHtml(data) + rows;
    }



    function createBackupsController({
        elements = {},
        appConfig = {},
        withCsrf = () => ({}),
        parseJsonResponse = response => response.json(),
        buildErrorMessage = (data, fallback) => data?.error || fallback,
        getWorldPath = () => "",
        copyTextToClipboard = () => {},
        logStatus = () => {},
        showToast = () => {},
        showLoading = () => {},
        hideLoading = () => {},
        onRestoreBackup = () => {},
        guardWorldWriteAction = () => false,
        beginServerStatusRequest = () => null,
        renderWriteGate = () => {},
        syncWriteControls = () => {},
        confirmDelete = filename => window.confirm(`${t("Backup wirklich löschen?")}\n\n${filename}`),
    } = {}) {
        const {
            container = null,
            refreshButton = null,
            openFolderButton = null,
            copyFolderButton = null,
            createButton = null,
        } = elements;
        let lastBackupDir = "";
        let backupsLoadRequestId = 0;
        const backupDeletesInFlight = new Set();
        const logBackupStatus = (key, message, type = "") => logStatus(message, type, { key });

        function isDockerMode() {
            return appConfig.is_docker === true || appConfig.mode === "docker";
        }

        function applyFolderControlsFor(backupDir, folderState = "ready") {
            applyBackupFolderControls({
                copyButton: copyFolderButton,
                openButton: openFolderButton,
            }, backupFolderControls({ backupDir, dockerMode: isDockerMode(), folderState }));
        }

        function createButtonWriteGateBlocked() {
            return createButton?.dataset?.writeGateBlocked === "true";
        }

        function createButtonCanReturnFromBusy() {
            return appConfig.read_only !== true && !createButtonWriteGateBlocked();
        }

        function applyInitialState() {
            applyFolderControlsFor("", getWorldPath() ? "loading" : "no-world");
            if (createButton && appConfig.read_only === true) {
                createButton.disabled = true;
                createButton.title = t("Read-Only-Modus: Backups können nicht erstellt werden.");
            }
        }

        async function createBackup() {
            const worldPath = getWorldPath();
            if (!worldPath) {
                const message = t("Bitte zuerst eine Welt laden.");
                logBackupStatus(BACKUP_CREATE_STATUS_KEY, message, "warning");
                showToast(message, "warning", 4000);
                return;
            }
            if (guardWorldWriteAction()) return false;
            if (createButton) createButton.disabled = true;
            showLoading(t("Backup wird erstellt..."));
            logBackupStatus(BACKUP_CREATE_STATUS_KEY, t("Backup wird erstellt..."), "running");
            const statusRequestOrder = beginServerStatusRequest();
            try {
                const res = await fetch("/api/backup/create", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: worldPath }),
                });
                const data = await parseJsonResponse(res);
                if (data?.write_gate) renderWriteGate(data.write_gate, { requestOrder: statusRequestOrder });
                if (data.success) {
                    const warning = data.cleanup_warning
                        ? ` ${t("Hinweis: {warning}", { warning: data.cleanup_warning })}`
                        : "";
                    const message = `${t("💾 Backup erstellt: {file}.", { file: data.backup_file || "OK" })}${warning}`;
                    logBackupStatus(
                        BACKUP_CREATE_STATUS_KEY,
                        message,
                        data.cleanup_warning ? "warning" : "success",
                    );
                    showToast(
                        message,
                        data.cleanup_warning ? "warning" : "success",
                        data.cleanup_warning ? 7000 : 5000,
                    );
                    await loadBackupsList();
                } else {
                    const message = data.error || t("Backup konnte nicht erstellt werden.");
                    logBackupStatus(BACKUP_CREATE_STATUS_KEY, message, "error");
                    showToast(message, "error", 6000);
                }
            } catch (_e) {
                const message = t("Backup konnte nicht erstellt werden.");
                logBackupStatus(BACKUP_CREATE_STATUS_KEY, message, "error");
                showToast(message, "error", 6000);
            } finally {
                hideLoading();
                if (createButton && createButtonCanReturnFromBusy()) createButton.disabled = false;
            }
        }

        async function openBackupFolder() {
            const requestedWorldPath = getWorldPath();
            if (!requestedWorldPath) return false;
            try {
                const res = await fetch("/api/open_backup_folder", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: requestedWorldPath }),
                });
                const data = await parseJsonResponse(res);
                // Opening the native file manager can take long enough for the
                // user to load another world. A late response must neither
                // replace that world's copy path nor show a toast for the old
                // selection.
                if (requestedWorldPath !== getWorldPath()) return false;
                const outcome = window.MCBEBackupRestoreLogic.openBackupFolderOutcome(data);
                showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                if (outcome.ok && outcome.nextBackupDir) lastBackupDir = outcome.nextBackupDir;
                return outcome.ok;
            } catch (_e) {
                if (requestedWorldPath !== getWorldPath()) return false;
                showToast(t("Fehler beim Öffnen des Backupordners."), "error", 5000);
                return false;
            }
        }

        async function deleteBackup(filename, button = null) {
            const worldPath = getWorldPath();
            if (!worldPath || !filename || appConfig.read_only === true) return false;
            const deletionKey = `${worldPath}\0${filename}`;
            if (backupDeletesInFlight.has(deletionKey)) return false;
            if (!confirmDelete(filename)) return false;
            backupDeletesInFlight.add(deletionKey);
            if (button) button.disabled = true;
            const statusKey = `${BACKUP_DELETE_STATUS_KEY}:${filename}`;
            logBackupStatus(
                statusKey,
                t("Backup wird gelöscht: {file}", { file: filename }),
                "running",
            );
            try {
                const res = await fetch("/api/backup/delete", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: worldPath, backup_file: filename }),
                });
                const data = await parseJsonResponse(res);
                if (!data.success) {
                    const message = data.error || t("Backup konnte nicht gelöscht werden.");
                    logBackupStatus(statusKey, message, "error");
                    showToast(message, "error", 6000);
                    return false;
                }
                const message = t("Backup gelöscht: {file}", { file: data.backup_file || filename });
                logBackupStatus(statusKey, message, "success");
                showToast(message, "success", 4500);
                await loadBackupsList();
                return true;
            } catch (_e) {
                const message = t("Backup konnte nicht gelöscht werden.");
                logBackupStatus(statusKey, message, "error");
                showToast(message, "error", 6000);
                return false;
            } finally {
                backupDeletesInFlight.delete(deletionKey);
                if (button?.isConnected && appConfig.read_only !== true) button.disabled = false;
            }
        }

        async function loadBackupsList() {
            if (!container) return;
            const requestId = ++backupsLoadRequestId;
            const requestedWorldPath = getWorldPath();
            // Der Pfad gehört immer exakt zur zuletzt erfolgreich geladenen
            // Liste. Schon während des Weltwechsels darf keine Aktion mehr auf
            // den Ordner der vorherigen Welt zeigen.
            lastBackupDir = "";
            if (!requestedWorldPath) {
                // Ohne Welt kann die Anfrage nur scheitern -- der Server weist
                // den leeren Pfad zurück, und die Ansicht meldete bisher einen
                // Fehler, wo schlicht noch nichts ausgewählt war. Der Ordner
                // der zuvor geladenen Welt darf dabei nicht offen bleiben.
                container.innerHTML = backupsStatusHtml("no-world");
                applyFolderControlsFor("", "no-world");
                return false;
            }
            container.innerHTML = backupsStatusHtml("loading");
            applyFolderControlsFor("", "loading");
            try {
                const res = await fetch("/api/backups", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: requestedWorldPath }),
                });
                const data = await parseJsonResponse(res);
                if (requestId !== backupsLoadRequestId || requestedWorldPath !== getWorldPath()) return false;
                if (data.success) {
                    lastBackupDir = String(data.backup_dir ?? "").trim();
                    container.innerHTML = backupsListHtml({ ...data, read_only: appConfig.read_only === true });
                    // Restore-Buttons werden mit der Liste neu erzeugt. Den
                    // zentralen Write-Gate deshalb im selben Render-Schritt auf
                    // die neuen Elemente anwenden, statt auf den nächsten Poll
                    // zu warten.
                    syncWriteControls();
                    applyFolderControlsFor(lastBackupDir, lastBackupDir ? "ready" : "unavailable");
                    wireBackupKindDisclosures(container);
                    container.querySelectorAll(".restore-btn[data-backup-filename]").forEach(button => {
                        button.addEventListener("click", () => {
                            // A world can change after this list was rendered but
                            // before the replacement list has arrived. Never send
                            // an old filename to the restore flow for a new world.
                            if (requestedWorldPath !== getWorldPath()) {
                                loadBackupsList();
                                return;
                            }
                            onRestoreBackup(button.dataset.backupFilename || "");
                        });
                    });
                    container.querySelectorAll(".delete-backup-btn[data-delete-backup-filename]").forEach(button => {
                        button.addEventListener("click", () => {
                            if (requestedWorldPath !== getWorldPath()) {
                                loadBackupsList();
                                return;
                            }
                            deleteBackup(button.dataset.deleteBackupFilename || "", button);
                        });
                    });
                } else {
                    container.innerHTML = backupsListHtml(data, {
                        errorMessage: buildErrorMessage(data, t("Fehler beim Laden der Backups.")),
                    });
                    applyFolderControlsFor("", "unavailable");
                }
                return true;
            } catch (e) {
                if (requestId !== backupsLoadRequestId || requestedWorldPath !== getWorldPath()) return false;
                console.error("loadBackupsList:", e);
                container.innerHTML = backupsStatusHtml("error");
                applyFolderControlsFor("", "unavailable");
                return false;
            }
        }

        function wire() {
            applyInitialState();
            refreshButton?.addEventListener("click", loadBackupsList);
            openFolderButton?.addEventListener("click", openBackupFolder);
            copyFolderButton?.addEventListener("click", () => {
                if (!lastBackupDir) return;
                copyTextToClipboard(lastBackupDir, t("Backupordner-Pfad kopiert."));
            });
            createButton?.addEventListener("click", createBackup);
        }

        return {
            createBackup,
            deleteBackup,
            loadBackupsList,
            openBackupFolder,
            wire,
        };
    }

    function collectBackupsElements(doc = document) {
        return {
            container: doc.getElementById("backupsContainer"),
            refreshButton: doc.getElementById("btnRefreshBackups"),
            openFolderButton: doc.getElementById("btnOpenBackupFolder"),
            copyFolderButton: doc.getElementById("btnCopyBackupDir"),
            createButton: doc.getElementById("btnCreateBackup"),
        };
    }

    function createInventoryBackupsController({
        doc = document,
        appConfig = {},
        api = {},
        getWorldPath = () => "",
        copyTextToClipboard = () => {},
        logStatus = () => {},
        showToast = () => {},
        showLoading = () => {},
        hideLoading = () => {},
        onRestoreBackup = () => {},
        guardWorldWriteAction = () => false,
        beginServerStatusRequest = () => null,
        renderWriteGate = () => {},
        syncWriteControls = () => {},
    } = {}) {
        return createBackupsController({
            elements: collectBackupsElements(doc),
            appConfig,
            withCsrf: api.withCsrf,
            parseJsonResponse: api.parseJsonResponse,
            buildErrorMessage: api.buildErrorMessage,
            getWorldPath,
            copyTextToClipboard,
            logStatus,
            showToast,
            showLoading,
            hideLoading,
            onRestoreBackup,
            guardWorldWriteAction,
            beginServerStatusRequest,
            renderWriteGate,
            syncWriteControls,
        });
    }


    window.MCBEBackupsView = {
        applyBackupFolderControls,
        collectBackupsElements,
        createInventoryBackupsController,
        createBackupsController,
        backupFolderControls,
        backupsStatusHtml,
        backupsListHtml,
        wireBackupKindDisclosures,
    };
}());
