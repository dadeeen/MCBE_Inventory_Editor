(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const EMPTY_OUTPUT = t("Noch kein Update ausgeführt.");
    const outputBuffers = new WeakMap();
    const sectionLabels = {
        items: "Katalogeinträge", stack_limits: "Stapellimits", durability: "Haltbarkeitswerte",
        effects: "Effekte", enchants: "Verzauberungen", addable_items: "Hinzufügbare Items",
        block_items: "Block-Items", block_only_items: "Reine Block-IDs",
        enchantable: "Verzauberbare Items", wearable: "Tragbare Items", allow_off_hand: "Nebenhand-Items",
    };
    const issueLabels = {
        invalid_ids: "Ungültige IDs", missing_names: "Fehlende DE/EN-Namen", missing_entries: "Fehlende Katalogreferenzen",
        invalid_stack_limits: "Ungültige Stapellimits", invalid_durability: "Ungültige Haltbarkeitswerte",
        unverified_stack_limits: "Ungeprüfte Stapellimits", name_differences_de: "Abweichende deutsche Namen",
        name_differences_en: "Abweichende englische Namen", source_conflicts_stack_limits: "Abweichende Stapellimits der Quellen",
        source_conflicts_durability: "Abweichende Haltbarkeitswerte der Quellen",
    };

    function renderResult(outputEl, data, dryRun, scopeText) {
        const doc = outputEl?.ownerDocument;
        const result = doc?.getElementById?.("updateDbResult");
        const auditEl = doc?.getElementById?.("updateDbAudit");
        if (!result || !auditEl) return;
        result.replaceChildren();
        auditEl.replaceChildren();
        const add = (parent, text, tag = "p") => {
            const el = doc.createElement(tag);
            el.textContent = text;
            parent.appendChild(el);
        };
        const report = data.summary;
        const state = !data.success ? "incomplete" : report?.status || "unknown";
        result.dataset.state = state;
        const titles = {
            available: t("Update verfügbar"), current: t("Keine inhaltlichen Änderungen"),
            metadata_only: t("Nur Quelleninformationen geändert"), incomplete: t("Prüfung unvollständig oder fehlgeschlagen"),
            unknown: t("Keine Ergebniszusammenfassung verfügbar. Bitte Details prüfen."),
        };
        let title = dryRun ? titles[state] || titles.unknown : data.success ? t("Update abgeschlossen.") : t("Update fehlgeschlagen.");
        if (dryRun && state === "available" && report?.release) title = t("Update auf Mojang {release} verfügbar", {release: report.release});
        add(result, title, "strong");
        add(result, t("Bereich: {scope}", {scope: scopeText}));
        if (data.error) add(result, data.error);
        if (data.reload_warning) add(result, data.reload_warning);
        for (const [key, counts] of Object.entries(report?.sections || {})) {
            if (!(counts.added || counts.removed || counts.changed)) continue;
            add(['items', 'stack_limits', 'durability', 'effects', 'enchants'].includes(key) ? result : auditEl,
                t("{section}: {added} ergänzt, {removed} entfernt, {changed} geändert.", {
                    section: t(sectionLabels[key] || key), ...counts,
                }));
        }
        const audit = report?.audit;
        if (audit) {
            add(result, t("Automatischer Abgleich: {count} Katalogeinträge geprüft.", {count: audit.checked_items}));
            const issues = audit.issues || [];
            const expectedNames = audit.expected_name_differences || [];
            if (expectedNames.length) {
                add(auditEl, t("Erwartete Namensabweichungen ({count})", {count: new Set(expectedNames.map(entry => entry.id)).size}), "strong");
                for (const entry of expectedNames) add(auditEl, `${String(entry.locale).toUpperCase()} · ${t("{id}: Katalog „{catalog}“ · Quelle „{source}“", entry)}`);
            }
            if (!issues.length) add(result, t("Keine Auffälligkeiten in den geprüften Daten."));
            else {
                add(result, t("Abgleich: {findings}. Details anzeigen.", {findings: issues.map(issue => `${t(issueLabels[issue.code] || issue.code)}: ${issue.count}`).join(" · ")}));
                for (const issue of issues) {
                    add(auditEl, `${t(issueLabels[issue.code] || issue.code)} (${issue.count})`, "strong");
                    if (issue.comparisons?.length) {
                        for (const entry of issue.comparisons) add(auditEl, t("{id}: Katalog „{catalog}“ · Quelle „{source}“", entry));
                    } else add(auditEl, (issue.items || []).join(', '));
                }
                if (issues.some(issue => issue.code.startsWith('name_differences_'))) {
                    add(auditEl, t("Abweichende Namen sind kein automatischer Fehler. Vorhandene Übersetzungen werden nicht allein wegen dieses Abgleichs ersetzt."));
                }
            }
        }
        for (const blocked of report?.blocked || []) add(result, `${blocked.section}: ${blocked.reason}`);
        if (dryRun) add(result, t("Keine Änderungen an der Item-Datenbank übernommen."));
    }

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
        const wrapper = outputEl.closest?.(".update-db-output-wrapper");
        if (wrapper) wrapper.hidden = false;
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

    function updateDbPayload({ dryRun, force, onlySelect, only = undefined, expectedUpdateReviewToken = null }) {
        const payload = {
            dry_run: dryRun,
            force,
            only: only === undefined ? (onlySelect?.value || null) : only,
        };
        if (!dryRun && expectedUpdateReviewToken) {
            payload.expected_update_review_token = expectedUpdateReviewToken;
        }
        return payload;
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
        fetchImpl = window.fetch.bind(window),
        parseJsonResponse,
        withCsrf,
        showLoading = () => {},
        hideLoading = () => {},
        logStatus = () => {},
        showToast = () => {},
        showConfirmDialog = async () => true,
        onReloaded = () => {},
        startUpdateProgress = title => window.MCBEAssetUpdateProgress?.start(title),
    } = {}) {
        const append = (text) => appendOutput(outputEl, text);
        let updateRunning = false;
        let reviewedSources = null;

        function setUpdateControlsDisabled(disabled) {
            if (dryRunButton) dryRunButton.disabled = disabled;
            if (applyButton) applyButton.disabled = disabled;
            if (onlySelect) onlySelect.disabled = disabled;
        }

        async function run(dryRun, force = false, options = {}) {
            options = options && typeof options === "object" ? options : {};
            if (!outputEl) {
                return { success: false, error: t("Update-Ausgabe ist nicht verfügbar.") };
            }
            if (updateRunning || window.MCBEAssetUpdateProgress?.isRunning()) {
                return { success: false, busy: true, error: t("Ein Update läuft bereits.") };
            }
            updateRunning = true;
            setUpdateControlsDisabled(true);
            outputBuffers.delete(outputEl);
            outputEl.textContent = EMPTY_OUTPUT;
            const resultEl = outputEl.ownerDocument?.getElementById?.("updateDbResult");
            if (resultEl) { resultEl.textContent = t("Prüfung läuft …"); resultEl.dataset.state = "running"; }
            const auditEl = outputEl.ownerDocument?.getElementById?.("updateDbAudit");
            if (auditEl) auditEl.replaceChildren();
            const detailsEl = outputEl.ownerDocument?.getElementById?.("updateDbDetails");
            if (detailsEl) detailsEl.open = false;

            const mode = dryRun ? "Dry-Run" : "Update";
            const statusKey = dryRun ? "database-update:dry-run" : "database-update:apply";
            const only = Object.prototype.hasOwnProperty.call(options, "only")
                ? (options.only || null)
                : (onlySelect?.value || null);
            const matchingReview = !dryRun && reviewedSources?.only === only ? reviewedSources : null;
            if (dryRun) reviewedSources = null;
            const updateStatus = (message, type, active = undefined) => logStatus(message, type, {
                key: statusKey,
                active,
            });
            append(`\n${t("=== {mode} gestartet ===", { mode })}`);
            append(t("Bereich: {scope}", { scope: selectedScopeText(onlySelect, only) }));
            append(matchingReview
                ? t("Quelle: im Dry-Run geprüfte Quellen (Mojang {release})", { release: matchingReview.release })
                : t("Quelle: neuestes Mojang-Release automatisch prüfen"));
            append("");

            showLoading(t("{mode} wird ausgeführt...", { mode }));
            const progress = startUpdateProgress(dryRun ? t("Item-Datenbank prüfen") : t("Item-Datenbank aktualisieren"));
            updateStatus(t("{mode} läuft...", { mode }), "running", true);

            try {
                const res = await fetchImpl("/api/update_db", {
                    method: "POST",
                    headers: { ...withCsrf(), ...progress?.headers },
                    body: JSON.stringify(updateDbPayload({
                        dryRun,
                        force,
                        onlySelect,
                        only,
                        expectedUpdateReviewToken: matchingReview?.token || null,
                    })),
                });
                const data = await parseJsonResponse(res);

                if (data.output) append(data.output);
                renderResult(outputEl, data, dryRun, selectedScopeText(onlySelect, only));

                if (data.success) {
                    progress?.finalizing();
                    const reviewToken = data.update_review_token || data.release_cache_token;
                    if (dryRun && reviewToken && data.resource_pack_release) {
                        reviewedSources = {
                            only,
                            token: reviewToken,
                            release: data.resource_pack_release,
                        };
                    } else if (!dryRun) {
                        reviewedSources = null;
                    }
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
                    // The backend message already says what failed.
                    const message = window.MCBEApiClient.errorMessageInContext(
                        data,
                        reason => t("{mode} fehlgeschlagen: {error}", { mode, error: reason }),
                    );
                    updateStatus(message, "error", true);
                    showToast(message, "error", 5000);
                }
                return data;
            } catch (e) {
                console.error("runUpdateDb:", e);
                const message = e?.message || t("Verbindungsfehler beim Datenbank-Update.");
                append(`\n${t("{mode} fehlgeschlagen: {error}", { mode, error: message })}`);
                updateStatus(t("{mode} fehlgeschlagen: {error}", { mode, error: message }), "error", true);
                showToast(message, "error", 5000);
                renderResult(outputEl, {success: false, error: message}, dryRun, selectedScopeText(onlySelect, only));
                return { success: false, error: message };
            } finally {
                progress?.stop();
                hideLoading();
                updateRunning = false;
                setUpdateControlsDisabled(false);
            }
        }

        dryRunButton?.addEventListener("click", () => run(true, false));
        onlySelect?.addEventListener?.("change", () => {
            reviewedSources = null;
            const summary = onlySelect.ownerDocument?.getElementById("updateScopeSummary");
            if (summary) summary.textContent = selectedScopeText(onlySelect);
        });
        applyButton?.addEventListener("click", async () => {
            const only = onlySelect?.value || null;
            const matchingReview = reviewedSources?.only === only ? reviewedSources : null;
            const ok = await showConfirmDialog(
                t("Möchtest du die offizielle Datenbank wirklich aktualisieren?") + "\n\n" +
                t("Dies aktualisiert item_db.json mit den neuesten Daten aus dem Mojang/bedrock-samples Release.") + "\n\n" +
                (matchingReview
                    ? t("Angewendet werden die im Dry-Run geprüften Quellen (Mojang {release}).", { release: matchingReview.release })
                    : t("Empfohlen: Erst 'Dry-Run ausführen' und die Änderungen prüfen."))
            );
            if (!ok) return;
            run(false, true);
        });
        clearButton?.addEventListener("click", () => {
            if (outputEl) {
                outputBuffers.delete(outputEl);
                outputEl.textContent = EMPTY_OUTPUT;
                const wrapper = outputEl.closest?.(".update-db-output-wrapper");
                if (wrapper) wrapper.hidden = true;
                dryRunButton?.focus?.();
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
