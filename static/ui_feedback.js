(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const UNKNOWN_SERVER_WRITE_PATHS = new Set([
        "/api/restore_backup",
        "/api/player/import",
        "/api/player/state_transfer",
        "/api/backup/create",
    ]);
    const DEDUPED_WRITE_PATHS = new Set([
        "/api/player/save",
        "/api/restore_backup",
        "/api/player/import",
        "/api/player/state_transfer",
        "/api/backup/create",
    ]);
    const inFlightWriteRequests = new Set();
    // Bestätigungen gelten nur für kurzlebige Retry-Ketten derselben Aktion,
    // nicht für identische Requests Stunden später: Ablauf per TTL und
    // Löschen nach erfolgreichem Abschluss.
    const UNKNOWN_SERVER_CONFIRMATION_TTL_MS = 5 * 60 * 1000;
    const confirmedUnknownServerWriteRequests = new Map();

    function storeUnknownServerConfirmation(key, now = Date.now()) {
        confirmedUnknownServerWriteRequests.set(key, now);
    }

    function clearUnknownServerConfirmation(key) {
        confirmedUnknownServerWriteRequests.delete(key);
    }

    function hasUnknownServerConfirmation(key, now = Date.now()) {
        const confirmedAt = confirmedUnknownServerWriteRequests.get(key);
        if (confirmedAt === undefined) return false;
        if (now - confirmedAt > UNKNOWN_SERVER_CONFIRMATION_TTL_MS) {
            confirmedUnknownServerWriteRequests.delete(key);
            return false;
        }
        return true;
    }

    function showCopyFallback({ overlay, textEl, text = "", onMissing = null } = {}) {
        if (!overlay || !textEl) {
            if (typeof onMissing === "function") onMissing();
            return false;
        }
        textEl.value = text || "";
        overlay.style.display = "flex";
        setTimeout(() => {
            textEl.focus();
            textEl.select();
        }, 0);
        return true;
    }

    function closeCopyFallback(overlay) {
        if (overlay) overlay.style.display = "none";
    }

    function renderConfirmMessage(msgEl, message, options = {}) {
        msgEl.replaceChildren();
        if (options.detailText) {
            String(message).split("\n\n").forEach((part) => {
                const paragraph = document.createElement("p");
                paragraph.className = "modal-message-block";
                paragraph.textContent = part;
                msgEl.appendChild(paragraph);
            });
            const detail = document.createElement("div");
            detail.className = "modal-message-detail";
            const label = document.createElement("span");
            label.className = "modal-message-detail-label";
            label.textContent = `${options.detailLabel || "Details"}:`;
            const text = document.createElement("code");
            text.textContent = options.detailText;
            detail.append(label, text);
            msgEl.appendChild(detail);
        } else {
            msgEl.textContent = message;
        }
    }

    let activeConfirmFinish = null;
    let loadingRequested = false;

    function showConfirmDialog(message, options = {}) {
        // The application owns one modal confirmation surface. If another action
        // requests it concurrently, cancel the stale action explicitly so its
        // Promise cannot remain unresolved after the button handlers are replaced.
        activeConfirmFinish?.(false);
        return new Promise((resolve) => {
            const overlay = document.getElementById("confirmOverlay");
            const msgEl = document.getElementById("confirmMessage");
            const okBtn = document.getElementById("confirmOk");
            const cancelBtn = document.getElementById("confirmCancel");
            if (!overlay || !msgEl || !okBtn || !cancelBtn) {
                resolve(false);
                return;
            }
            const loadingOverlay = document.getElementById("loadingOverlay");
            if (loadingOverlay?.style.display === "flex") loadingRequested = true;
            if (loadingRequested && loadingOverlay) loadingOverlay.style.display = "none";
            let settled = false;
            const finish = value => {
                if (settled) return;
                settled = true;
                if (activeConfirmFinish === finish) activeConfirmFinish = null;
                overlay.style.display = "none";
                cancelBtn.style.display = "";
                okBtn.textContent = t("Fortfahren");
                cancelBtn.textContent = t("Abbrechen");
                okBtn.onclick = null;
                cancelBtn.onclick = null;
                if (loadingRequested && loadingOverlay) loadingOverlay.style.display = "flex";
                resolve(value);
            };
            activeConfirmFinish = finish;
            renderConfirmMessage(msgEl, message, options);
            const requestedOkLabel = options.okLabel || t("Fortfahren");
            const okLabel = requestedOkLabel === t("Ja, Server ist gestoppt")
                ? t("Ich bin sicher, der Server ist gestoppt")
                : requestedOkLabel;
            const cancelLabel = options.cancelLabel === undefined ? t("Abbrechen") : options.cancelLabel;
            okBtn.textContent = okLabel;
            cancelBtn.textContent = cancelLabel || "";
            cancelBtn.style.display = cancelLabel ? "" : "none";
            overlay.style.display = "flex";
            okBtn.focus?.();
            okBtn.onclick = () => finish(true);
            cancelBtn.onclick = () => finish(false);
        });
    }

    function showLoading(text) {
        const overlay = document.getElementById("loadingOverlay");
        const textEl = document.getElementById("loadingText");
        if (!overlay || !textEl) return;
        loadingRequested = true;
        textEl.textContent = text;
        const confirmOverlay = document.getElementById("confirmOverlay");
        overlay.style.display = confirmOverlay?.style.display === "flex" ? "none" : "flex";
    }

    function hideLoading() {
        loadingRequested = false;
        const overlay = document.getElementById("loadingOverlay");
        if (!overlay) return;
        overlay.style.display = "none";
    }

    function showToast(msg, type = "success", duration = 3000) {
        let container = document.querySelector(".toast-container");
        if (!container) {
            container = document.createElement("div");
            container.className = "toast-container";
            document.body.appendChild(container);
        }
        const toast = document.createElement("div");
        toast.className = `toast toast-${type}`;
        // Anzeige-Grenze: Auch Server-Meldungen laufen durch t(); unbekannte
        // Texte bleiben unverändert (deutsche Quelle als Fallback).
        toast.textContent = t(msg);
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add("toast-fade");
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    function requestPath(input, win = window) {
        const rawUrl = typeof input === "string" ? input : input?.url;
        if (!rawUrl) return "";
        try {
            return new URL(rawUrl, win?.location?.href || "http://localhost/").pathname;
        } catch (_e) {
            return String(rawUrl).split("?", 1)[0];
        }
    }

    function requestMethod(input, init = {}) {
        return String(init?.method || input?.method || "GET").toUpperCase();
    }

    function jsonBodyFromInit(init = {}) {
        if (!init || typeof init.body !== "string") return null;
        try {
            const parsed = JSON.parse(init.body);
            return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
        } catch (_e) {
            return null;
        }
    }

    async function responseJson(response) {
        try {
            const readable = response && typeof response.clone === "function" ? response.clone() : response;
            if (!readable || typeof readable.json !== "function") return null;
            return await readable.json();
        } catch (_e) {
            return null;
        }
    }

    function duplicateWriteResponse() {
        const payload = {
            success: false,
            error: t("Diese Schreibaktion läuft bereits. Bitte warte, bis der laufende Vorgang abgeschlossen ist."),
            duplicate_request: true,
        };
        return new Response(JSON.stringify(payload), {
            status: 409,
            headers: { "Content-Type": "application/json" },
        });
    }

    function writeRequestKey(path, init = {}) {
        return `${path}\n${typeof init.body === "string" ? init.body : ""}`;
    }

    function stableJsonObject(value = {}) {
        return JSON.stringify(Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]])));
    }

    function unknownConfirmationKey(path, requestBody = {}) {
        const comparable = { ...requestBody };
        delete comparable.confirm_presence_conflict;
        delete comparable.confirm_unknown_server_status;
        return `${path}\n${stableJsonObject(comparable)}`;
    }

    function applyStoredUnknownServerConfirmation(path, init = {}) {
        if (!UNKNOWN_SERVER_WRITE_PATHS.has(path)) return init;
        const requestBody = jsonBodyFromInit(init);
        if (!requestBody || requestBody.confirm_unknown_server_status === true) return init;
        if (!hasUnknownServerConfirmation(unknownConfirmationKey(path, requestBody))) return init;
        return {
            ...init,
            body: JSON.stringify({
                ...requestBody,
                confirm_unknown_server_status: true,
            }),
        };
    }

    async function confirmUnknownServerWrite(writeGate = {}) {
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
                cancelLabel: t("Nicht schreiben"),
                detailLabel: t("Statusprüfung"),
                detailText,
            }
        );
        if (!ok) {
            showToast(t("Schreibaktion abgebrochen: Serverstatus nicht bestätigt."), "warning", 5000);
        }
        return ok;
    }

    function installUnknownServerWriteConfirmationFetchGuard(win = window) {
        if (!win || win.__MCBEUnknownServerWriteConfirmationFetchGuardInstalled) return false;
        const originalFetch = win.fetch;
        if (typeof originalFetch !== "function") return false;
        win.__MCBEUnknownServerWriteConfirmationFetchGuardInstalled = true;
        win.fetch = async function guardedFetch(input, init = {}) {
            const path = requestPath(input, win);
            const method = requestMethod(input, init);
            const effectiveInit = method === "POST" ? applyStoredUnknownServerConfirmation(path, init) : init;
            const shouldDedupe = method === "POST" && DEDUPED_WRITE_PATHS.has(path);
            const dedupeKey = shouldDedupe ? writeRequestKey(path, effectiveInit) : "";
            if (shouldDedupe) {
                if (inFlightWriteRequests.has(dedupeKey)) return duplicateWriteResponse();
                inFlightWriteRequests.add(dedupeKey);
            }
            try {
                const response = await originalFetch.call(this, input, effectiveInit);
                if (method !== "POST" || !UNKNOWN_SERVER_WRITE_PATHS.has(path)) {
                    return response;
                }
                const requestBody = jsonBodyFromInit(effectiveInit);
                if (!requestBody) return response;
                const confirmationKey = unknownConfirmationKey(path, requestBody);
                if (requestBody.confirm_unknown_server_status === true) {
                    // Abgeschlossene Aktion: gespeicherte Bestätigung ist verbraucht.
                    const confirmedData = await responseJson(response);
                    if (confirmedData?.success === true) clearUnknownServerConfirmation(confirmationKey);
                    return response;
                }
                const data = await responseJson(response);
                const writeGate = data?.write_gate;
                if (!data || data.success !== false || writeGate?.requires_unknown_server_confirmation !== true) {
                    return response;
                }
                const proceed = await confirmUnknownServerWrite(writeGate);
                if (!proceed) return response;
                storeUnknownServerConfirmation(confirmationKey);
                const retryInit = {
                    ...effectiveInit,
                    body: JSON.stringify({
                        ...requestBody,
                        confirm_unknown_server_status: true,
                    }),
                };
                const retryResponse = await originalFetch.call(this, input, retryInit);
                const retryData = await responseJson(retryResponse);
                if (retryData?.success === true) clearUnknownServerConfirmation(confirmationKey);
                return retryResponse;
            } finally {
                if (shouldDedupe) inFlightWriteRequests.delete(dedupeKey);
            }
        };
        return true;
    }



    function createClipboardFeedbackController({
        elements = {},
        clipboard = navigator.clipboard,
        logStatus = () => {},
        clearStatus = () => {},
        showToastFn = showToast,
    } = {}) {
        const fallbackStatusKey = "clipboard-copy:fallback";
        const {
            overlay = null,
            textEl = null,
            closeButton = null,
            doneButton = null,
            selectButton = null,
        } = elements;

        function showFallback(text) {
            const shown = showCopyFallback({
                overlay,
                textEl,
                text,
                onMissing: () => logStatus(
                    t("Kopieren nicht automatisch möglich. Bitte Browser-Zwischenablage/HTTPS prüfen."),
                    "warning",
                    { key: fallbackStatusKey, active: true },
                ),
            });
            if (shown) {
                logStatus(
                    t("Der Browser hat den automatischen Zwischenablagezugriff blockiert. Der Text ist markiert und kann mit Strg+C kopiert werden."),
                    "info",
                    { key: fallbackStatusKey, active: false },
                );
            }
            return shown;
        }

        function closeFallback() {
            closeCopyFallback(overlay);
            clearStatus(fallbackStatusKey);
        }

        async function copyTextToClipboard(text, successMessage = t("In die Zwischenablage kopiert.")) {
            if (!text) return false;
            try {
                if (!clipboard || typeof clipboard.writeText !== "function") {
                    throw new Error("Clipboard API nicht verfügbar");
                }
                await clipboard.writeText(text);
                clearStatus(fallbackStatusKey);
                logStatus(successMessage, "success");
                showToastFn(successMessage, "success", 2500);
                return true;
            } catch (_e) {
                showFallback(text);
                return false;
            }
        }

        function wire() {
            closeButton?.addEventListener("click", closeFallback);
            doneButton?.addEventListener("click", closeFallback);
            selectButton?.addEventListener("click", () => {
                textEl?.focus();
                textEl?.select();
            });
            overlay?.addEventListener("click", event => {
                if (event.target === overlay) closeFallback();
            });
        }

        return {
            closeFallback,
            copyTextToClipboard,
            showFallback,
            wire,
        };
    }


    function collectClipboardFeedbackElements(doc = document) {
        return {
            overlay: doc.getElementById("copyFallbackOverlay"),
            textEl: doc.getElementById("copyFallbackText"),
            closeButton: doc.getElementById("btnCopyFallbackClose"),
            doneButton: doc.getElementById("btnCopyFallbackDone"),
            selectButton: doc.getElementById("btnCopyFallbackSelect"),
        };
    }

    function createInventoryClipboardFeedbackController({ doc = document, ...deps } = {}) {
        return createClipboardFeedbackController({
            ...deps,
            elements: collectClipboardFeedbackElements(doc),
        });
    }


    function createHelpOverlayController({
        doc = document,
        openButton = null,
        closeButton = null,
        overlay = null,
    } = {}) {
        function open() {
            if (overlay) overlay.style.display = "flex";
        }

        function close() {
            if (overlay) overlay.style.display = "none";
        }

        function wire() {
            openButton?.addEventListener("click", open);
            closeButton?.addEventListener("click", close);
            overlay?.addEventListener("click", event => {
                if (event.target === overlay) close();
            });
            doc.addEventListener("keydown", event => {
                if (event.key === "Escape" && overlay?.style.display === "flex") close();
            });
        }

        return { close, open, wire };
    }

    installUnknownServerWriteConfirmationFetchGuard();

    window.MCBEUiFeedback = {
        createClipboardFeedbackController,
        collectClipboardFeedbackElements,
        createInventoryClipboardFeedbackController,
        createHelpOverlayController,
        installUnknownServerWriteConfirmationFetchGuard,
        showCopyFallback,
        closeCopyFallback,
        showConfirmDialog,
        showLoading,
        hideLoading,
        showToast,
    };
}());
