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

    function backupFolderControls({ backupDir = "", dockerMode = false } = {}) {
        const disabled = !backupDir || dockerMode;
        return {
            copyDisabled: !backupDir,
            openDisabled: disabled,
            openTitle: disabled ? t("Im Docker-/LAN-Modus nur Pfad kopieren.") : t("Backupordner im Dateimanager öffnen"),
        };
    }

    function applyBackupFolderControls(elements = {}, model = {}) {
        const { copyButton = null, openButton = null } = elements;
        if (copyButton) copyButton.disabled = Boolean(model.copyDisabled);
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

    function backupRowHtml(backup = {}, { readOnly = false } = {}) {
        const kindLabel = backup.kind_label || "Legacy";
        const deleteTitle = readOnly ? t("Read-Only-Modus: Backups können nicht gelöscht werden.") : t("Backup löschen");
        return `<div class="backup-row">
            <div class="backup-info">
                <div class="backup-title-line">
                    <span class="backup-kind backup-kind-${escapeHtml(backup.kind || "legacy")}">${escapeHtml(kindLabel)}</span>
                    <span class="backup-filename" title="${escapeHtml(backup.filename)}">${escapeHtml(backup.filename)}</span>
                </div>
                <span class="backup-meta">${escapeHtml(backup.date)} &nbsp;•&nbsp; ${escapeHtml(backup.size_mb)} MB</span>
            </div>
            <div class="backup-actions">
                <button class="btn btn-secondary btn-sm restore-btn" type="button" data-backup-filename="${escapeHtml(backup.filename)}">🔄 ${t("Wiederherstellen")}</button>
                <button class="btn btn-secondary btn-sm delete-backup-btn" type="button" data-delete-backup-filename="${escapeHtml(backup.filename)}" title="${escapeHtml(deleteTitle)}"${readOnly ? " disabled" : ""}>🗑 ${t("Löschen")}</button>
            </div>
        </div>`;
    }

    function backupsStatusHtml(status = "loading") {
        if (status === "loading") {
            return `<div class="no-backups">${t("Lade Sicherheitskopien...")}</div>`;
        }
        return `<div class="no-backups error">${t("Fehler beim Laden der Backups.")}</div>`;
    }

    function backupsListHtml(data = {}) {
        if (!data.success) {
            return backupsStatusHtml("error");
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
        getWorldPath = () => "",
        copyTextToClipboard = () => {},
        logStatus = () => {},
        showToast = () => {},
        showLoading = () => {},
        hideLoading = () => {},
        onRestoreBackup = () => {},
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

        function createButtonWriteGateBlocked() {
            return createButton?.dataset?.writeGateBlocked === "true";
        }

        function createButtonCanReturnFromBusy() {
            return appConfig.read_only !== true && !createButtonWriteGateBlocked();
        }

        function applyInitialState() {
            if (copyFolderButton) copyFolderButton.disabled = true;
            if (openFolderButton) openFolderButton.disabled = true;
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
            if (createButton) createButton.disabled = true;
            showLoading(t("Backup wird erstellt..."));
            logBackupStatus(BACKUP_CREATE_STATUS_KEY, t("Backup wird erstellt..."), "running");
            try {
                const res = await fetch("/api/backup/create", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: worldPath }),
                });
                const data = await parseJsonResponse(res);
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
            const worldPath = getWorldPath();
            if (!worldPath) return;
            try {
                const res = await fetch("/api/open_backup_folder", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: worldPath }),
                });
                const data = await parseJsonResponse(res);
                const outcome = window.MCBEBackupRestoreLogic.openBackupFolderOutcome(data);
                showToast(outcome.toast.message, outcome.toast.type, outcome.toast.ms);
                if (outcome.ok && outcome.nextBackupDir) lastBackupDir = outcome.nextBackupDir;
            } catch (_e) {
                showToast(t("Fehler beim Öffnen des Backupordners."), "error", 5000);
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
            container.innerHTML = backupsStatusHtml("loading");
            try {
                const res = await fetch("/api/backups", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify({ world_path: requestedWorldPath }),
                });
                const data = await parseJsonResponse(res);
                if (requestId !== backupsLoadRequestId || requestedWorldPath !== getWorldPath()) return false;
                if (data.success) {
                    lastBackupDir = data.backup_dir || "";
                    container.innerHTML = backupsListHtml({ ...data, read_only: appConfig.read_only === true });
                    applyBackupFolderControls({
                        copyButton: copyFolderButton,
                        openButton: openFolderButton,
                    }, backupFolderControls({
                        backupDir: lastBackupDir,
                        dockerMode: appConfig.is_docker === true || appConfig.mode === "docker",
                    }));
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
                    container.innerHTML = backupsListHtml(data);
                }
                return true;
            } catch (e) {
                if (requestId !== backupsLoadRequestId || requestedWorldPath !== getWorldPath()) return false;
                console.error("loadBackupsList:", e);
                container.innerHTML = backupsStatusHtml("error");
                return false;
            }
        }

        function wire() {
            applyInitialState();
            refreshButton?.addEventListener("click", loadBackupsList);
            openFolderButton?.addEventListener("click", openBackupFolder);
            copyFolderButton?.addEventListener("click", () => copyTextToClipboard(lastBackupDir, t("Backupordner-Pfad kopiert.")));
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
    } = {}) {
        return createBackupsController({
            elements: collectBackupsElements(doc),
            appConfig,
            withCsrf: api.withCsrf,
            parseJsonResponse: api.parseJsonResponse,
            getWorldPath,
            copyTextToClipboard,
            logStatus,
            showToast,
            showLoading,
            hideLoading,
            onRestoreBackup,
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
    };
}());
