(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const TODO_IDS = ["item_db", "icons"];
    const DISMISSED_KEY = "first_run_setup_dismissed";

    function createFirstRunSetupController({
        elements = {},
        isItemDbPending = () => false,
        isIconsPending = () => false,
        getIconsPendingHint = () => "",
        getItemDbFeedback = () => ({}),
        getStatusError = () => "",
        runItemDbUpdate = async () => {},
        runIconsUpdate = async () => {},
        refreshItemDbStatus = async () => {},
        refreshIconSources = async () => {},
        canWriteAppState = () => true,
        loadWorkspace = () => ({}),
        saveWorkspace = () => {},
        readOnlyMessage = "",
    } = {}) {
        const { overlay = null, closeButton = null, rows = {}, banner = null, bannerDetail = null, bannerButton = null } = elements;
        const documentObj = elements.documentObj || overlay?.ownerDocument || (typeof document !== "undefined" ? document : null);
        const running = {};
        const errors = {};
        const statusErrors = {};
        const results = {};
        let returnFocus = null;

        const TODO_LABELS = {
            item_db: () => t("Item-Datenbank"),
            icons: () => t("Item-Icons"),
        };

        function todoState(id) {
            const pending = id === "item_db" ? isItemDbPending() : isIconsPending();
            if (pending === null || pending === undefined) return "unknown";
            return pending ? "pending" : "done";
        }

        function isPending(id) {
            return todoState(id) === "pending";
        }

        function needsSetup(id) {
            const state = todoState(id);
            if (state === "unknown" && id === "item_db") return Boolean(results.item_db?.update_committed || getItemDbFeedback()?.reloadWarning);
            return state === "pending";
        }

        function isDismissed() {
            return Boolean(loadWorkspace()?.[DISMISSED_KEY]);
        }

        function recordUpdateResult(id, result) {
            results[id] = result;
            delete errors[id];
            delete statusErrors[id];
        }

        async function onItemDbApply(result) {
            recordUpdateResult("item_db", result);
            render();
            if (result?.update_committed && !result.reloaded && !running.item_db) await refreshItemDbStatus();
        }

        function renderRow(id) {
            const row = rows[id];
            if (!row) return;
            const { mark, state, button, details, detailsContent, detailsSummary } = row;
            const locked = !canWriteAppState();
            // "Done" is derived from the live status rather than from the update
            // call returning cleanly, so a run that silently changed nothing can
            // never tick the box.
            const stateValue = todoState(id);
            const done = stateValue === "done";
            const unknown = stateValue === "unknown";
            const busy = Boolean(running[id]);
            const feedback = id === "item_db" ? getItemDbFeedback() || {} : {};
            const iconHint = id === "icons" ? getIconsPendingHint() : "";
            // A verified live status supersedes a failed or incomplete attempt,
            // including when another browser repaired the installation.
            const previous = results[id];
            const obsoleteIconIssue = id === "icons" && (previous?.success === false || previous?.client_warning || previous?.scan_warning);
            if (done && (previous?.outcome === "partial" || previous?.outcome === "failed" || obsoleteIconIssue)) {
                recordUpdateResult(id, null);
            } else if (done && previous?.reload_warning) {
                results[id] = {...previous, reload_warning: ""};
            }
            const result = results[id];
            const saved = id === "item_db" && window.MCBEUpdateDbView.catalogDataSaved(result);
            const confirmedCurrent = result?.outcome === "current" && result.item_db?.verification?.verified === true;
            const failed = result?.outcome === "failed" || (result?.success === false && !saved && !result.scan_warning);
            const error = unknown ? getStatusError(id) || statusErrors[id] || errors[id] : errors[id];
            const partial = !failed && !done && (feedback.partial || result?.outcome === "partial" || (id === "icons" && (result?.client_warning || result?.scan_warning)));
            const keepResultNotes = saved || result?.client_warning || result?.reload_warning || result?.scan_warning;
            const resultNotes = [result?.error, result?.hint, result?.reload_warning, result?.client_warning, result?.scan_warning,
                ...(window.MCBEDataSourceView?.itemDbBlockedMessages(result?.summary?.blocked) || [])].filter(Boolean);

            if (mark) mark.textContent = done ? "✓" : busy ? "⋯" : partial ? "!" : unknown ? "–" : "○";
            if (row.item) {
                row.item.classList.toggle("is-done", done);
                row.item.classList.toggle("is-running", busy);
                row.item.classList.toggle("is-error", Boolean(failed || error) && !done && !busy && !partial && !saved && !confirmedCurrent);
                row.item.classList.toggle("is-unknown", unknown);
                row.item.classList.toggle("is-warning", Boolean(partial || ((saved || confirmedCurrent) && error)) && !done && !busy);
            }
            if (state) {
                if (done) state.textContent = feedback.warnings || (keepResultNotes && resultNotes.length)
                    ? t("Erledigt. Hinweise in den Details.") : t("Erledigt.");
                else if (busy) state.textContent = running[id] === "status" ? t("Status wird geprüft…") : t("Wird geladen…");
                else if (failed) state.textContent = window.MCBEUpdateDbView.sourceFailureMessage(result) || t("Fehlgeschlagen. Details prüfen.");
                else if (unknown && feedback.reloadWarning) state.textContent = t("Bitte den Editor neu starten.");
                else if (unknown && confirmedCurrent) state.textContent = t("Datenbank geprüft. Status erneut prüfen.");
                else if (unknown) state.textContent = saved
                    ? t("Änderungen gespeichert. Status erneut prüfen.") : t("Status nicht verfügbar. Bitte erneut prüfen.");
                else if (partial) state.textContent = saved && result.outcome === "partial"
                    ? t("Teilweise aktualisiert. Details prüfen.") : t("Prüfung unvollständig. Details prüfen.");
                else if (error) state.textContent = saved
                    ? t("Änderungen gespeichert. Details prüfen.") : t("Fehlgeschlagen. Details prüfen.");
                else if (locked) state.textContent = readOnlyMessage;
                else state.textContent = iconHint;
            }
            if (button) {
                button.disabled = done || TODO_IDS.some(todo => running[todo]) || (locked && !unknown);
                button.textContent = done ? t("Erledigt") : unknown ? t("Status erneut prüfen")
                    : failed || partial ? t("Erneut versuchen") : iconHint ? t("Icons abgleichen") : t("Jetzt laden");
                button.style.display = done ? "none" : "";
            }
            if (details && detailsContent) {
                const lines = busy ? [] : [...new Set([
                    !done ? error : "", ...(!done || keepResultNotes ? resultNotes : []), ...(feedback.details || []),
                ].filter(Boolean))];
                const text = lines.join("\n\n");
                if (detailsContent.textContent !== text) detailsContent.textContent = text;
                details.hidden = !text;
                if (details.hidden) {
                    details.open = false;
                    if ([detailsSummary, detailsContent].includes(documentObj?.activeElement)) {
                        (button && !button.disabled && button.style.display !== "none" ? button : closeButton)?.focus?.();
                    }
                }
            }
        }

        function renderBanner() {
            if (!banner) return;
            // The banner is the way back after "Später": it appears only once the
            // overlay has been dismissed, so the two never compete for attention.
            const open = TODO_IDS.filter(needsSetup);
            const show = open.length > 0 && isDismissed() && !isOpen();
            banner.style.display = show ? "" : "none";
            banner.classList.toggle("includes-icon-setup", show && open.includes("icons"));
            if (show && bannerDetail) {
                bannerDetail.textContent = [
                    t("Offen: {items}.", { items: open.map(id => TODO_LABELS[id]()).join(", ") }),
                    open.includes("item_db") ? t("Prüfe die Item-Daten auf Aktualität.") : "",
                    open.includes("icons") ? getIconsPendingHint() || t("Die Slots zeigen Ersatzsymbole, bis Icons eingerichtet sind.") : "",
                ].filter(Boolean).join(" ");
            }
        }

        function render() {
            TODO_IDS.forEach(renderRow);
            if (closeButton) {
                closeButton.textContent = TODO_IDS.every(id => todoState(id) === "done") ? t("Fertig") : t("Später");
            }
            renderBanner();
        }

        function open() {
            if (!overlay) return;
            if (!isOpen()) {
                returnFocus = documentObj?.activeElement || null;
            }
            overlay.style.display = "flex";
            render();
            const firstAction = TODO_IDS
                .map(id => rows[id]?.button)
                .find(button => button && !button.disabled && button.style?.display !== "none");
            (firstAction || closeButton)?.focus?.();
        }

        function close() {
            const wasOpen = isOpen();
            if (overlay) overlay.style.display = "none";
            // Remember the choice even when both todos are done: reopening an
            // overlay that has nothing left to do would only be noise.
            saveWorkspace({ [DISMISSED_KEY]: true });
            render();
            if (wasOpen) {
                returnFocus?.focus?.();
                returnFocus = null;
            }
        }

        function isOpen() {
            return Boolean(overlay && overlay.style.display !== "none");
        }

        function maybeOpenOnStart() {
            if (isDismissed() || !TODO_IDS.some(needsSetup)) {
                render();
                return false;
            }
            open();
            return true;
        }

        async function runTodo(id) {
            if (!TODO_IDS.includes(id) || TODO_IDS.some(todo => running[todo])) return;
            const retryStatus = todoState(id) === "unknown";
            if (!retryStatus && (!canWriteAppState() || !isPending(id))) return;
            running[id] = retryStatus ? "status" : "update";
            if (!retryStatus) recordUpdateResult(id, null);
            statusErrors[id] = "";
            render();
            try {
                // An unavailable status is not permission to download assets.
                // A successful read may reveal pending setup for a later click.
                if (retryStatus) {
                    await (id === "icons" ? refreshIconSources() : refreshItemDbStatus());
                    if (todoState(id) === "unknown") {
                        throw new Error(getStatusError(id) || t("Status nicht verfügbar. Bitte erneut prüfen."));
                    }
                    return;
                }
                let result;
                if (id === "item_db") {
                    result = await runItemDbUpdate();
                    recordUpdateResult(id, result);
                    if (result?.success || result?.update_committed) await refreshItemDbStatus();
                    if (result?.outcome === "partial" && result?.update_committed) return;
                    if (!result?.success) {
                        throw new Error(result?.error || t("Item-DB-Aktualisierung fehlgeschlagen."));
                    }
                } else {
                    result = await runIconsUpdate();
                    recordUpdateResult(id, result);
                    if (!result?.success) {
                        throw new Error(result?.error || t("Icon-Aktualisierung fehlgeschlagen."));
                    }
                    await refreshIconSources();
                }
                const refreshedState = todoState(id);
                if (refreshedState !== "done") {
                    throw new Error(refreshedState === "unknown"
                        ? t("Aktualisierung abgeschlossen, der Status konnte jedoch nicht bestätigt werden.")
                        : t("Aktualisierung abgeschlossen, der Status ist jedoch weiterhin offen."));
                }
            } catch (err) {
                (retryStatus || todoState(id) === "unknown" ? statusErrors : errors)[id] = err?.message || String(err);
            } finally {
                running[id] = false;
                render();
            }
        }

        TODO_IDS.forEach(id => {
            rows[id]?.button?.addEventListener("click", () => runTodo(id));
        });
        closeButton?.addEventListener("click", close);
        bannerButton?.addEventListener("click", open);
        documentObj?.addEventListener?.("keydown", event => {
            if (!isOpen()) return;
            if (event.key === "Escape") {
                event.preventDefault?.();
                close();
                return;
            }
            if (event.key !== "Tab") return;
            const actions = [
                ...TODO_IDS.flatMap(id => {
                    const row = rows[id];
                    return [
                        !row?.details?.hidden && row?.detailsSummary,
                        !row?.details?.hidden && row?.details?.open && row?.detailsContent,
                        row?.button,
                    ];
                }),
                closeButton,
            ].filter(button => button && !button.disabled && button.style?.display !== "none");
            if (!actions.length) return;
            const currentIndex = actions.indexOf(documentObj.activeElement);
            const step = event.shiftKey ? -1 : 1;
            const nextIndex = currentIndex < 0
                ? (event.shiftKey ? actions.length - 1 : 0)
                : (currentIndex + step + actions.length) % actions.length;
            event.preventDefault?.();
            actions[nextIndex].focus?.();
        });

        return { close, isOpen, maybeOpenOnStart, onItemDbApply, open, render, runTodo };
    }

    function collectFirstRunSetupElements(doc = document) {
        const rows = {};
        TODO_IDS.forEach(id => {
            const item = doc.querySelector(`[data-first-run-todo="${id}"]`);
            rows[id] = {
                item,
                mark: item?.querySelector("[data-role='mark']") || null,
                state: item?.querySelector("[data-role='state']") || null,
                button: item?.querySelector("[data-role='run']") || null,
                details: item?.querySelector("[data-role='details']") || null,
                detailsContent: item?.querySelector("[data-role='details-content']") || null,
                detailsSummary: item?.querySelector("[data-role='details'] > summary") || null,
            };
        });
        const banner = doc.getElementById("setupTodoBanner");
        return {
            documentObj: doc,
            overlay: doc.getElementById("firstRunSetupOverlay"),
            closeButton: doc.getElementById("btnFirstRunSetupClose"),
            banner,
            bannerDetail: banner?.querySelector("[data-role='detail']") || null,
            bannerButton: doc.getElementById("btnSetupTodoBanner"),
            rows,
        };
    }

    function createInventoryFirstRunSetupController({ doc = document, ...deps } = {}) {
        return createFirstRunSetupController({ ...deps, elements: collectFirstRunSetupElements(doc) });
    }

    window.MCBEFirstRunSetupView = {
        TODO_IDS,
        collectFirstRunSetupElements,
        createFirstRunSetupController,
        createInventoryFirstRunSetupController,
    };
}());
