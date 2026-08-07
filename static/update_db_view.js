(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const EMPTY_OUTPUT = t("Noch kein Update ausgeführt.");
    const outputBuffers = new WeakMap();

    function outputLineType(line) {
        const text = String(line || "").trim();
        if (!text) return "";
        if (/^===.*===$/.test(text) || text.includes("Minecraft Bedrock Item-DB Updater")) return "banner";
        if (/^--- .* ---$/.test(text)) return "step";
        if (/\b(Fehler|fehlgeschlagen|Error|failed)\b/i.test(text)) return "error";
        if (/\b(Warnung|warning|unbekannt|unknown|Dry-Run)\b/i.test(text)) return "warning";
        if (/\b(aktuell|Fertig|updated|current)\b|keine Änderungen|Verwende gecachte|->/.test(text)) return "success";
        return "";
    }

    function renderOutput(outputEl, text) {
        const doc = outputEl?.ownerDocument;
        if (!doc?.createDocumentFragment || !doc?.createElement || typeof outputEl.replaceChildren !== "function") {
            outputEl.textContent = text;
            return;
        }
        const fragment = doc.createDocumentFragment();
        String(text).split("\n").forEach((line, index, lines) => {
            const span = doc.createElement("span");
            const type = outputLineType(line);
            if (type) span.className = `update-log-${type}`;
            span.textContent = line;
            fragment.appendChild(span);
            if (index < lines.length - 1) fragment.appendChild(doc.createTextNode("\n"));
        });
        outputEl.replaceChildren(fragment);
    }

    function appendOutput(outputEl, text) {
        if (!outputEl) return;
        const initial = outputEl.textContent === EMPTY_OUTPUT ? "" : outputEl.textContent;
        const current = outputBuffers.has(outputEl) ? outputBuffers.get(outputEl) : initial;
        const raw = String(text ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
        const addition = raw ? raw.replace(/\n+$/g, "") + "\n" : "\n";
        const next = current + addition;
        outputBuffers.set(outputEl, next);
        renderOutput(outputEl, next);
        outputEl.scrollTop = outputEl.scrollHeight;
    }

    function selectedScopeText(selectEl, value = undefined) {
        const selectedValue = value === undefined ? selectEl?.value : value;
        if (!selectedValue) return t("Alles");
        const matchingOption = Array.from(selectEl?.options || []).find(option => option.value === selectedValue);
        return matchingOption?.text || String(selectedValue);
    }

    function updateDbPayload({ dryRun, force, onlySelect, useCacheCheckbox, only = undefined }) {
        return {
            dry_run: dryRun,
            force,
            only: only === undefined ? (onlySelect?.value || null) : only,
            use_cache: Boolean(useCacheCheckbox?.checked),
        };
    }

    async function refreshLoadedPlayerAfterDbUpdate({
        currentPlayerKey = "",
        isDirty = false,
        loadPlayer = async () => false,
    } = {}) {
        if (!currentPlayerKey) return {};
        if (isDirty) {
            return {
                warning: t("Die Item-Datenbank ist aktualisiert. Der geladene Spieler wurde wegen ungespeicherter Änderungen nicht automatisch neu geladen. Speichere oder verwirf sie und lade den Spieler danach neu."),
            };
        }

        const reloaded = await loadPlayer(currentPlayerKey, true, { showLoadingOverlay: false });
        if (reloaded) return {};
        return {
            warning: t("Die Item-Datenbank ist aktualisiert, aber der geladene Spieler konnte nicht automatisch neu geladen werden. Lade ihn manuell neu."),
        };
    }

    function createUpdateDbController({
        outputEl,
        dryRunButton,
        applyButton,
        clearButton,
        onlySelect,
        useCacheCheckbox,
        fetchImpl = window.fetch.bind(window),
        parseJsonResponse,
        withCsrf,
        showLoading = () => {},
        hideLoading = () => {},
        logStatus = () => {},
        showToast = () => {},
        showConfirmDialog = async () => true,
        onReloaded = () => {},
    } = {}) {
        const append = (text) => appendOutput(outputEl, text);
        let updateRunning = false;

        function setUpdateControlsDisabled(disabled) {
            if (dryRunButton) dryRunButton.disabled = disabled;
            if (applyButton) applyButton.disabled = disabled;
            if (onlySelect) onlySelect.disabled = disabled;
            if (useCacheCheckbox) useCacheCheckbox.disabled = disabled;
        }

        async function run(dryRun, force = false, options = {}) {
            options = options && typeof options === "object" ? options : {};
            if (!outputEl) {
                return { success: false, error: t("Update-Ausgabe ist nicht verfügbar.") };
            }
            if (updateRunning) {
                return { success: false, busy: true, error: t("Ein Datenbank-Update läuft bereits.") };
            }
            updateRunning = true;
            setUpdateControlsDisabled(true);

            const mode = dryRun ? "Dry-Run" : "Update";
            const statusKey = dryRun ? "database-update:dry-run" : "database-update:apply";
            const only = Object.prototype.hasOwnProperty.call(options, "only")
                ? (options.only || null)
                : (onlySelect?.value || null);
            const updateStatus = (message, type, active = undefined) => logStatus(message, type, {
                key: statusKey,
                active,
            });
            append(`\n${t("=== {mode} gestartet ===", { mode })}`);
            append(t("Bereich: {scope}", { scope: selectedScopeText(onlySelect, only) }));
            append(`Cache: ${useCacheCheckbox?.checked ? t("verwenden") : t("nicht verwenden")}`);
            append("");

            showLoading(t("{mode} wird ausgeführt...", { mode }));
            updateStatus(t("{mode} läuft...", { mode }), "running", true);

            try {
                const res = await fetchImpl("/api/update_db", {
                    method: "POST",
                    headers: withCsrf(),
                    body: JSON.stringify(updateDbPayload({ dryRun, force, onlySelect, useCacheCheckbox, only })),
                });
                const data = await parseJsonResponse(res);

                if (data.output) append(data.output);

                if (data.success) {
                    if (data.reloaded) {
                        let clientWarning = "";
                        try {
                            const reloadOutcome = await onReloaded(data) || {};
                            clientWarning = reloadOutcome.warning || "";
                        } catch (reloadError) {
                            console.error("onReloaded:", reloadError);
                            clientWarning = t("Die Item-Datenbank ist aktualisiert, aber die Browseransicht konnte nicht vollständig aktualisiert werden. Lade die Seite neu.");
                        }
                        append("\n" + t("Datenbank aktualisiert und Server neu geladen."));
                        if (clientWarning) {
                            append(clientWarning);
                            showToast(clientWarning, "warning", 8000);
                            updateStatus(clientWarning, "warning", true);
                        } else {
                            showToast(t("Datenbank aktualisiert. Server wurde neu geladen."), "success", 5000);
                            updateStatus(t("{mode} erfolgreich.", { mode }), "success", false);
                        }
                    } else if (!dryRun && data.update_committed) {
                        const warning = data.reload_warning ||
                            t("Die Item-Datenbank wurde aktualisiert, aber der Server konnte sie nicht neu laden. Bitte Anwendung neu starten.");
                        append(`\n${warning}`);
                        updateStatus(warning, "warning", true);
                        showToast(warning, "warning", 8000);
                    } else {
                        append("\n" + t("Dry-Run abgeschlossen."));
                        showToast(t("Dry-Run abgeschlossen."), "success", 3000);
                        updateStatus(t("{mode} erfolgreich.", { mode }), "success", false);
                    }
                } else {
                    append(`\n${t("Fehler (Code {code}): {error}", { code: data.returncode, error: data.error || t("Unbekannter Fehler") })}`);
                    updateStatus(t("{mode} fehlgeschlagen: {error}", { mode, error: data.error }), "error", true);
                    showToast(t("{mode} fehlgeschlagen: {error}", { mode, error: data.error }), "error", 5000);
                }
                return data;
            } catch (e) {
                console.error("runUpdateDb:", e);
                append(`\n${t("Verbindungsfehler: {error}", { error: e.message })}`);
                updateStatus(t("Verbindungsfehler beim Datenbank-Update."), "error", true);
                showToast(t("Verbindungsfehler beim Datenbank-Update."), "error", 5000);
                return { success: false, error: e?.message || String(e) };
            } finally {
                hideLoading();
                updateRunning = false;
                setUpdateControlsDisabled(false);
            }
        }

        dryRunButton?.addEventListener("click", () => run(true, false));
        applyButton?.addEventListener("click", async () => {
            const ok = await showConfirmDialog(
                t("Möchtest du die offizielle Datenbank wirklich aktualisieren?") + "\n\n" +
                t("Dies aktualisiert item_db.json mit den neuesten Daten aus dem Mojang/bedrock-samples Release.") + "\n\n" +
                t("Empfohlen: Erst 'Dry-Run ausführen' und die Änderungen prüfen.")
            );
            if (!ok) return;
            run(false, true);
        });
        clearButton?.addEventListener("click", () => {
            if (outputEl) {
                outputBuffers.delete(outputEl);
                outputEl.textContent = EMPTY_OUTPUT;
            }
        });

        return {
            appendOutput: append,
            isRunning: () => updateRunning,
            run,
        };
    }

    function collectUpdateDbElements(doc = document) {
        return {
            outputEl: doc.getElementById("updateDbOutput"),
            dryRunButton: doc.getElementById("btnUpdateDbDryRun"),
            applyButton: doc.getElementById("btnUpdateDbApply"),
            clearButton: doc.getElementById("btnClearUpdateOutput"),
            onlySelect: doc.getElementById("updateOnlySelect"),
            useCacheCheckbox: doc.getElementById("updateDbUseCache"),
        };
    }

    function createInventoryUpdateDbController({
        doc = document,
        api = {},
        showLoading = () => {},
        hideLoading = () => {},
        logStatus = () => {},
        showToast = () => {},
        showConfirmDialog = async () => true,
        onReloaded = () => {},
    } = {}) {
        return createUpdateDbController({
            ...collectUpdateDbElements(doc),
            parseJsonResponse: api.parseJsonResponse,
            withCsrf: api.withCsrf,
            showLoading,
            hideLoading,
            logStatus,
            showToast,
            showConfirmDialog,
            onReloaded,
        });
    }


    window.MCBEUpdateDbView = {
        EMPTY_OUTPUT,
        appendOutput,
        collectUpdateDbElements,
        createInventoryUpdateDbController,
        createUpdateDbController,
        outputLineType,
        refreshLoadedPlayerAfterDbUpdate,
        renderOutput,
        selectedScopeText,
        updateDbPayload,
    };
}());
