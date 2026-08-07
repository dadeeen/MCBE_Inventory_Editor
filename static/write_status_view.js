(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const PLAYER_WRITE_GATE_NOTICE_KEY = "player-write-gate";
    const EDIT_CONTROL_SELECTOR = [
        "#multiSelectPanel input",
        "#multiSelectPanel select",
        "#multiSelectPanel textarea",
        "#detailEditorPanel input",
        "#detailEditorPanel select",
        "#detailEditorPanel textarea",
        "#dashStats input",
        "#dashStats select",
        "#dashStats textarea",
        "#dashEffects input",
        "#dashEffects select",
        "#dashEffects textarea",
        "#btnBulkFill",
        "#btnBulkClear",
        "#btnBulkSetCount",
        "#btnBulkRepairSelected",
        "#btnRepairAll",
        "#btnApplySingle",
        "#btnApplySingleEnch",
        "#btnQuickClearSlot",
        "#btnQuickMaxStack",
        "#btnQuickRepairSlot",
        "#btnMaxAllEnch",
        "#btnClearAllEnch",
        "#btnApplyStats",
        "#btnResetAbilitySpeeds",
        "#btnAddEffect",
        "#btnApplyEffects",
        "#dashEffects .effect-remove",
        "#btnCopyFromPlayer",
        "#btnBrowserDetail",
        "#btnBrowserBulk",
        "#btnUndo",
        "#btnRedo",
    ].join(", ");
    const GUARDED_DYNAMIC_EDIT_SELECTOR = [
        '.context-item[data-action="paste"]',
        '.context-item[data-action="cut"]',
        '.context-item[data-action="clear"]',
        ".browser-item",
        "#btnMountCreate",
    ].join(", ");

    function writeControlModel({ isDirty = false, blocked = false, blockedReason = "", hasEditablePlayer = false } = {}) {
        return {
            saveDisabled: !isDirty || blocked,
            restoreDisabled: blocked,
            restoreTitle: blocked ? blockedReason : t("Backup wiederherstellen"),
            backupCreateDisabled: blocked,
            backupCreateTitle: blocked ? blockedReason : t("Backup erstellen"),
            editDisabled: blocked && hasEditablePlayer,
            editTitle: blocked ? blockedReason : "",
        };
    }

    function currentRestoreButtons(baseButtons = []) {
        const buttons = Array.from(baseButtons || []).filter(Boolean);
        if (typeof document === "undefined") return buttons;
        const seen = new Set(buttons);
        document.querySelectorAll(".restore-btn").forEach(button => {
            if (!seen.has(button)) {
                buttons.push(button);
                seen.add(button);
            }
        });
        return buttons;
    }

    function applyWriteControlModel(elements = {}, model = {}) {
        const {
            saveButtons = [],
            restoreButtons = [],
            backupCreateButtons = [],
            editControls = [],
        } = elements;
        for (const button of saveButtons || []) {
            if (button) button.disabled = Boolean(model.saveDisabled);
        }
        for (const button of currentRestoreButtons(restoreButtons)) {
            button.disabled = Boolean(model.restoreDisabled);
            button.title = model.restoreTitle || "";
        }
        for (const button of backupCreateButtons || []) {
            if (!button) continue;
            const disabled = Boolean(model.backupCreateDisabled);
            button.disabled = disabled;
            button.title = model.backupCreateTitle || "";
            if (button.dataset) button.dataset.writeGateBlocked = disabled ? "true" : "false";
        }
        const currentEditControls = typeof editControls === "function" ? editControls() : editControls;
        for (const control of currentEditControls || []) {
            if (!control || !("disabled" in control)) continue;
            const dataset = control.dataset || null;
            if (model.editDisabled) {
                if (dataset && dataset.writeGateEditBlocked !== "true") {
                    dataset.writeGatePreviousDisabled = control.disabled ? "true" : "false";
                    dataset.writeGatePreviousTitle = control.title || "";
                    dataset.writeGateEditBlocked = "true";
                }
                control.disabled = true;
                control.title = model.editTitle || "";
                control.setAttribute?.("aria-disabled", "true");
            } else if (dataset?.writeGateEditBlocked === "true") {
                control.disabled = dataset.writeGatePreviousDisabled === "true";
                control.title = dataset.writeGatePreviousTitle || "";
                control.removeAttribute?.("aria-disabled");
                delete dataset.writeGatePreviousDisabled;
                delete dataset.writeGatePreviousTitle;
                delete dataset.writeGateEditBlocked;
            }
        }
    }

    function serverStatusBadgeModel({ gate = {}, status = {}, appConfig = {} } = {}) {
        const statusText = status.status || "unknown";
        const labelMap = { online: "online", offline: "offline", unknown: t("unbekannt") };
        const serverName = status.server_name || appConfig.server_name || "Bedrock Server";
        const className = `server-status-badge ${statusText} ${gate.allowed ? "allowed" : "blocked"}`;
        const writeText = gate.allowed ? t("Schreiben freigegeben") : t("Schreiben gesperrt");
        const manualStopTitle = t("Der Editor stoppt Minecraft oder den Bedrock-Server nicht automatisch. Stoppe den Server manuell in deiner Umgebung, bevor du Welten bearbeitest.");
        if (gate.status_check_failed === true) {
            return {
                className: `${className} status-check-failed`,
                text: t("Server: zuletzt {status} · Prüfung fehlgeschlagen", { status: labelMap[statusText] || statusText }),
                title: `${gate.status_check_error || gate.reason || t("Serverstatus konnte nicht abgefragt werden.")} ${manualStopTitle}`.trim(),
            };
        }
        if (appConfig.mode === "local" && appConfig.require_server_offline !== true) {
            return {
                className,
                text: t("Server: unbekannt · manuell prüfen"),
                title: `${t("Lokalmodus: Es ist unbekannt, ob Minecraft oder ein Bedrock-Server diese Welt parallel geöffnet hat.")} ${manualStopTitle}`,
            };
        }
        const actionText = gate.stale_loaded_player === true
            ? statusText === "online"
                ? t("Server stoppen und Spieler neu laden")
                : t("Spieler neu laden")
            : statusText === "online"
                ? t("manuell stoppen")
                : statusText === "unknown" ? t("manuell prüfen") : "";
        const text = actionText
            ? t("Server: {status} · {write} · {action}", {
                status: labelMap[statusText] || statusText,
                write: writeText,
                action: actionText,
            })
            : t("Server: {status} · {write}", {
                status: labelMap[statusText] || statusText,
                write: writeText,
            });
        const actionTitle = statusText === "online" || statusText === "unknown" ? manualStopTitle : "";
        const detailText = gate.stale_loaded_player === true
            ? (gate.reason || status.message || "")
            : (status.message || gate.reason || "");
        return {
            className,
            text,
            title: `${serverName}: ${detailText} ${actionTitle}`.trim(),
        };
    }

    function applyServerStatusBadgeModel(element, model = {}) {
        if (!element) return;
        element.className = model.className || "server-status-badge unknown blocked";
        element.textContent = model.text || "";
        element.title = model.title || "";
    }

    function fallbackWriteGate(appConfig = {}, message = t("Serverstatus noch nicht geprüft.")) {
        // Spiegelt das Backend-write_gate: MCBE_ALLOW_EDIT_WHILE_ONLINE ist
        // veraltet. Ein unbekannter Status bleibt in jedem Betriebsmodus
        // bearbeitbar, benötigt aber vor jedem tatsächlichen Schreibversuch
        // eine ausdrückliche Bestätigung.
        return {
            allowed: false,
            reason: t("Serverstatus unbekannt. Bitte bestätige vor dem Schreiben ausdrücklich, dass der Server gestoppt ist."),
            override_active: false,
            requires_unknown_server_confirmation: true,
            server_status: {
                status: "unknown",
                message,
                server_name: appConfig.server_name || "Bedrock Server",
                server_host: appConfig.server_host || null,
                server_port: appConfig.server_port || null,
                require_server_offline: appConfig.require_server_offline === true,
            },
        };
    }



    // Zentrales Berechtigungsmodell. Spiegelt die Backend-Policy-Tabelle
    // (tests/test_read_only_mode.py): world_write hängt am vollen Write-Gate,
    // app_write/local_file/Export/Import-Vorschau nur am Read-Only-Modus.
    function permissionModel({ gate = {}, appConfig = {} } = {}) {
        const readOnly = appConfig?.read_only === true || gate?.read_only === true;
        const canConfirmUnknown = gate?.requires_unknown_server_confirmation === true;
        const canWriteWorld = !readOnly && (gate?.allowed !== false || canConfirmUnknown);
        return {
            readOnly,
            canWriteWorld,
            canWriteAppState: !readOnly,
            canExport: !readOnly,
            canImportPreview: !readOnly,
            canRescanIcons: !readOnly,
            reason: canWriteWorld ? "" : (gate?.reason || ""),
        };
    }

    function normalizeServerGuardEpoch(value) {
        const parsed = Number(value);
        return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
    }

    function serverStatusRevision(payload = {}, gate = {}, status = {}) {
        return normalizeServerGuardEpoch(
            payload.server_status_revision
                ?? gate.server_status_revision
                ?? status.server_status_revision,
        );
    }

    function serverGuardToken(payload = {}, gate = {}, status = {}) {
        const token = payload.server_guard_token
            ?? gate.server_guard_token
            ?? status.server_guard_token;
        return typeof token === "string" ? token.trim() : "";
    }

    function localizedRecordText(record = {}, valueField, keyField, paramsField) {
        const source = record?.[keyField] || record?.[valueField] || "";
        return source ? t(source, record?.[paramsField] || undefined) : "";
    }

    function localizeServerStatusPayload(payload = {}) {
        const hasGate = Boolean(payload.write_gate);
        const sourceGate = payload.write_gate || {};
        const sourceStatus = payload.server_status || sourceGate.server_status || {};
        const status = {
            ...sourceStatus,
            message: localizedRecordText(sourceStatus, "message", "message_key", "message_params"),
        };
        const gate = {
            ...sourceGate,
            reason: localizedRecordText(sourceGate, "reason", "reason_key", "reason_params"),
            server_status: status,
        };
        return {
            ...payload,
            server_status: status,
            write_gate: hasGate ? gate : undefined,
        };
    }

    function createWriteGateController({
        appConfig = {},
        elements = {},
        parseJsonResponse = response => response.json(),
        getCurrentWriteGate = () => fallbackWriteGate(appConfig),
        setCurrentWriteGate = () => {},
        getCurrentServerGuardEpoch = () => 0,
        setCurrentServerGuardEpoch = () => {},
        getCurrentServerGuardToken = () => "",
        setCurrentServerGuardToken = () => {},
        getCurrentServerStatusRevision = () => 0,
        setCurrentServerStatusRevision = () => {},
        getCurrentPlayerServerGuardEpoch = () => 0,
        getCurrentPlayerServerGuardToken = () => "",
        getCurrentPlayerStaleReason = () => "",
        setCurrentPlayerStaleReason = () => {},
        getCurrentPlayerKey = () => "",
        getIsDirty = () => false,
        buildChangeSummary = () => ({ total: 0 }),
        updateImportControls = () => {},
        updatePlayerTransferControls = () => {},
        renderSaveWorkflowPanel = () => {},
        updateDirtyBanner = () => {},
        updateHeaderStatusStack = () => {},
        renderStatusCenter = () => {},
        logStatus = () => {},
        clearStatus = () => false,
        showToast = () => {},
        staleReason = t("Nur ansehen: Der Bedrock-Server wurde seit dem Laden dieses Spielers online gesehen. Stoppe den Server und lade den Spieler neu, um ihn zu bearbeiten."),
        changedServerStateReason = t("Nur ansehen: Der Bedrock-Serverzustand hat sich seit dem Laden dieses Spielers geändert. Lade den Spieler neu, um ihn zu bearbeiten."),
    } = {}) {
        const {
            serverStatusBadge = null,
            saveButtons = [],
            restoreButtons = [],
            backupCreateButtons = [],
            editControls = [],
        } = elements;
        let nextServerStatusRequestOrder = 0;
        let appliedServerStatusRequestOrder = 0;
        let serverStatusRefreshInFlight = false;

        function beginServerStatusRequest() {
            nextServerStatusRequestOrder += 1;
            return nextServerStatusRequestOrder;
        }

        function normalizedRequestOrder(value) {
            const parsed = Number(value);
            if (Number.isInteger(parsed) && parsed > 0) {
                nextServerStatusRequestOrder = Math.max(nextServerStatusRequestOrder, parsed);
                return parsed;
            }
            return beginServerStatusRequest();
        }

        function clearLoadedPlayerStaleState() {
            setCurrentPlayerStaleReason("");
            clearStatus(PLAYER_WRITE_GATE_NOTICE_KEY);
        }

        function effectiveWriteGate() {
            const currentWriteGate = getCurrentWriteGate();
            if (appConfig?.read_only === true) {
                return {
                    ...currentWriteGate,
                    allowed: false,
                    reason: t("Read-Only-Modus aktiv (MCBE_READ_ONLY). Diese Instanz erlaubt nur das Ansehen von Welten."),
                    blocked_operation: "read_only",
                    read_only: true,
                    override_active: false,
                    requires_unknown_server_confirmation: false,
                };
            }
            const stale = getCurrentPlayerStaleReason();
            if (!stale) return currentWriteGate;
            return {
                ...currentWriteGate,
                allowed: false,
                reason: stale,
                blocked_operation: "server_guard",
                stale_loaded_player: true,
                server_guard_epoch: getCurrentServerGuardEpoch(),
                server_guard_token: getCurrentServerGuardToken(),
                server_status_revision: getCurrentServerStatusRevision(),
            };
        }

        function writeBlocked() {
            const gate = effectiveWriteGate();
            return gate?.allowed === false && gate?.requires_unknown_server_confirmation !== true;
        }

        function editingBlocked() {
            return Boolean(getCurrentPlayerKey()) && writeBlocked();
        }

        function permissions() {
            return permissionModel({ gate: effectiveWriteGate(), appConfig });
        }

        function markLoadedPlayerStale(reason = staleReason) {
            if (!getCurrentPlayerKey() || getCurrentPlayerStaleReason()) return;
            setCurrentPlayerStaleReason(reason);
            logStatus(reason, "error", {
                category: "write-gate",
                key: PLAYER_WRITE_GATE_NOTICE_KEY,
                active: true,
            });
            showToast(reason, "error", 7000);
            updateWriteControls();
            renderSaveWorkflowPanel();
            renderStatusCenter();
        }

        function updateWriteControls() {
            const gate = effectiveWriteGate();
            const blocked = gate?.allowed === false && gate?.requires_unknown_server_confirmation !== true;
            const model = writeControlModel({
                isDirty: getIsDirty(),
                blocked,
                blockedReason: gate?.reason || "",
                hasEditablePlayer: Boolean(getCurrentPlayerKey()),
                summary: buildChangeSummary({ limit: 3, includeSections: false }),
            });
            applyWriteControlModel({ saveButtons, restoreButtons, backupCreateButtons, editControls }, model);
            updateImportControls();
            updatePlayerTransferControls();
            renderSaveWorkflowPanel();
            updateDirtyBanner();
        }

        function renderServerStatus(payload, { requestOrder = null } = {}) {
            if (!payload) return false;
            const incomingRequestOrder = normalizedRequestOrder(requestOrder);
            if (incomingRequestOrder < appliedServerStatusRequestOrder) return false;
            appliedServerStatusRequestOrder = incomingRequestOrder;
            const localizedPayload = localizeServerStatusPayload(payload);
            const previousGate = getCurrentWriteGate();
            const gate = localizedPayload.write_gate || previousGate;
            const status = localizedPayload.server_status || gate.server_status || {};
            const incomingRevision = serverStatusRevision(localizedPayload, gate, status);
            const incomingGuardToken = serverGuardToken(localizedPayload, gate, status);
            setCurrentWriteGate(gate);
            setCurrentServerGuardEpoch(Math.max(
                getCurrentServerGuardEpoch(),
                normalizeServerGuardEpoch(localizedPayload.server_guard_epoch ?? gate.server_guard_epoch),
            ));
            if (incomingGuardToken) setCurrentServerGuardToken(incomingGuardToken);
            setCurrentServerStatusRevision(Math.max(
                getCurrentServerStatusRevision(),
                incomingRevision,
            ));
            const tokenChanged = Boolean(
                incomingGuardToken
                && getCurrentPlayerServerGuardToken()
                && incomingGuardToken !== getCurrentPlayerServerGuardToken(),
            );
            const legacyOnlineChange = Boolean(
                !incomingGuardToken
                && status.status === "online"
                && getCurrentServerGuardEpoch() > getCurrentPlayerServerGuardEpoch(),
            );
            if (
                getCurrentPlayerKey() &&
                appConfig?.require_server_offline === true &&
                gate.override_active !== true &&
                (tokenChanged || legacyOnlineChange)
            ) {
                markLoadedPlayerStale(
                    tokenChanged && status.status !== "online"
                        ? changedServerStateReason
                        : staleReason,
                );
            }

            const model = serverStatusBadgeModel({ gate: effectiveWriteGate(), status, appConfig });
            if (serverStatusBadge) applyServerStatusBadgeModel(serverStatusBadge, model);
            updateWriteControls();
            updateHeaderStatusStack();
            return true;
        }

        function renderServerStatusFailure(message, { requestOrder = null } = {}) {
            const fallbackGate = fallbackWriteGate(appConfig, message);
            const previousGate = getCurrentWriteGate() || {};
            const previousStatus = previousGate.server_status;
            const status = previousStatus && typeof previousStatus === "object"
                ? previousStatus
                : fallbackGate.server_status;
            const preserveOnlineBlock = (
                appConfig?.require_server_offline === true
                && status.status === "online"
                && previousGate.allowed === false
            );
            const failureGate = {
                ...fallbackGate,
                ...(preserveOnlineBlock ? {
                    allowed: false,
                    reason: previousGate.reason || t("Server läuft noch. Bitte Server stoppen."),
                    override_active: false,
                    requires_unknown_server_confirmation: false,
                } : {}),
                server_status: status,
                status_check_failed: true,
                status_check_error: message,
            };
            return renderServerStatus({
                server_status: status,
                write_gate: failureGate,
            }, { requestOrder });
        }

        async function refreshServerStatus() {
            if (serverStatusRefreshInFlight) return false;
            serverStatusRefreshInFlight = true;
            const requestOrder = beginServerStatusRequest();
            try {
                const res = await fetch("/api/server_status");
                const data = await parseJsonResponse(res);
                if (data.success) {
                    return renderServerStatus(data, { requestOrder });
                }
                return renderServerStatusFailure(
                    data?.error || t("Serverstatus konnte nicht abgefragt werden."),
                    { requestOrder },
                );
            } catch (_e) {
                return renderServerStatusFailure(
                    t("Serverstatus konnte nicht abgefragt werden."),
                    { requestOrder },
                );
            } finally {
                serverStatusRefreshInFlight = false;
            }
        }

        return {
            beginServerStatusRequest,
            clearLoadedPlayerStaleState,
            editingBlocked,
            effectiveWriteGate,
            markLoadedPlayerStale,
            normalizeServerGuardEpoch,
            permissions,
            refreshServerStatus,
            renderServerStatus,
            renderServerStatusFailure,
            updateWriteControls,
            writeBlocked,
        };
    }

    function collectWriteGateElements(doc = document) {
        return {
            serverStatusBadge: doc.getElementById("serverStatusBadge"),
            saveButtons: [
                doc.getElementById("btnSave"),
                doc.getElementById("btnDirtyReview"),
                doc.getElementById("btnDirtySave"),
                doc.getElementById("btnShowSavePreview"),
            ],
            restoreButtons: doc.querySelectorAll(".restore-btn"),
            backupCreateButtons: [doc.getElementById("btnCreateBackup")],
            editControls: () => doc.querySelectorAll(EDIT_CONTROL_SELECTOR),
        };
    }

    function createInventoryWriteGateController({ doc = document, ...deps } = {}) {
        const controller = createWriteGateController({
            ...deps,
            elements: collectWriteGateElements(doc),
        });
        let editGuardWired = false;
        function blockedFeedback() {
            const reason = controller.effectiveWriteGate()?.reason || t("Bearbeitung ist aktuell gesperrt.");
            deps.showToast?.(reason, "warning", 4500);
        }
        function guardEditEvent(event) {
            if (!controller.editingBlocked()) return;
            const target = event?.target;
            const slot = target?.closest?.(".inventory-slot");
            const guardedClick = event?.type === "click" && target?.closest?.(GUARDED_DYNAMIC_EDIT_SELECTOR);
            const guardedDrag = (event?.type === "dragstart" || event?.type === "drop") && slot;
            const key = String(event?.key || "").toLowerCase();
            const editableTextTarget = Boolean(target?.closest?.('input, textarea, select, [contenteditable="true"]'));
            const guardedKey = event?.type === "keydown"
                && (
                    (slot && (key === "delete" || key === "backspace"))
                    || (!editableTextTarget && (event.ctrlKey || event.metaKey) && (key === "x" || key === "v"))
                );
            if (!guardedClick && !guardedDrag && !guardedKey) return;
            event.preventDefault?.();
            event.stopImmediatePropagation?.();
            blockedFeedback();
        }
        function wireEditGuard() {
            if (editGuardWired || typeof doc.addEventListener !== "function") return;
            editGuardWired = true;
            for (const eventName of ["click", "keydown", "dragstart", "drop"]) {
                doc.addEventListener(eventName, guardEditEvent, true);
            }
        }
        wireEditGuard();
        return {
            ...controller,
            guardEditEvent,
            wireEditGuard,
        };
    }

    window.MCBEWriteStatusView = {
        applyServerStatusBadgeModel,
        collectWriteGateElements,
        createInventoryWriteGateController,
        createWriteGateController,
        applyWriteControlModel,
        EDIT_CONTROL_SELECTOR,
        fallbackWriteGate,
        localizeServerStatusPayload,
        normalizeServerGuardEpoch,
        permissionModel,
        PLAYER_WRITE_GATE_NOTICE_KEY,
        serverGuardToken,
        serverStatusRevision,
        writeControlModel,
        serverStatusBadgeModel,
    };
}());
