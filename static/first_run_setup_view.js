(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const TODO_IDS = ["item_db", "icons"];
    const DISMISSED_KEY = "first_run_setup_dismissed";

    function createFirstRunSetupController({
        elements = {},
        isItemDbPending = () => false,
        isIconsPending = () => false,
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

        function anyPending() {
            return TODO_IDS.some(isPending);
        }

        function isDismissed() {
            return Boolean(loadWorkspace()?.[DISMISSED_KEY]);
        }

        function renderRow(id) {
            const row = rows[id];
            if (!row) return;
            const { mark, state, button } = row;
            const locked = !canWriteAppState();
            // "Done" is derived from the live status rather than from the update
            // call returning cleanly, so a run that silently changed nothing can
            // never tick the box.
            const stateValue = todoState(id);
            const done = stateValue === "done";
            const unknown = stateValue === "unknown";
            const busy = Boolean(running[id]);

            if (mark) mark.textContent = done ? "✓" : busy ? "⋯" : unknown ? "–" : "○";
            if (row.item) {
                row.item.classList.toggle("is-done", done);
                row.item.classList.toggle("is-running", busy);
                row.item.classList.toggle("is-error", Boolean(errors[id]) && !done);
                row.item.classList.toggle("is-unknown", unknown);
            }
            if (state) {
                state.textContent = done
                    ? t("Erledigt.")
                    : busy
                        ? t("Wird geladen…")
                        : errors[id]
                            ? t("Fehlgeschlagen: {error}", { error: errors[id] })
                            : unknown
                                ? t("Status nicht verfügbar. Seite neu laden.")
                            : locked
                                ? readOnlyMessage
                                : "";
            }
            if (button) {
                button.disabled = done || busy || locked || unknown;
                button.textContent = done ? t("Erledigt") : t("Jetzt laden");
                button.style.display = done ? "none" : "";
            }
        }

        function renderBanner() {
            if (!banner) return;
            // The banner is the way back after "Später": it appears only once the
            // overlay has been dismissed, so the two never compete for attention.
            const open = TODO_IDS.filter(isPending);
            const show = open.length > 0 && isDismissed() && !isOpen();
            banner.style.display = show ? "" : "none";
            if (show && bannerDetail) {
                bannerDetail.textContent = t("Offen: {items}. Ohne diese Daten fehlen Items neuerer Minecraft-Versionen und Slots zeigen Ersatzsymbole.", {
                    items: open.map(id => TODO_LABELS[id]()).join(", "),
                });
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
            if (isDismissed() || !anyPending()) {
                render();
                return false;
            }
            open();
            return true;
        }

        async function runTodo(id) {
            if (running[id] || !canWriteAppState() || !isPending(id)) return;
            running[id] = true;
            errors[id] = "";
            render();
            try {
                let result;
                if (id === "item_db") {
                    result = await runItemDbUpdate();
                    if (!result?.success) {
                        throw new Error(result?.error || t("Item-DB-Aktualisierung fehlgeschlagen."));
                    }
                    await refreshItemDbStatus();
                } else {
                    result = await runIconsUpdate();
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
                errors[id] = err?.message || String(err);
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
                ...TODO_IDS.map(id => rows[id]?.button),
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

        return { close, isOpen, maybeOpenOnStart, open, render, runTodo };
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
