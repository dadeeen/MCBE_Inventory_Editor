(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const number = value => window.MCBEI18n?.formatNumber(value) ?? String(value);

    const EMPTY_OUTPUT = t("Noch keine Prüfung ausgeführt.");
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

    function sectionSummary(key, counts, details) {
        if (key === "effects" && counts.changed && !counts.added && !counts.removed && details?.descriptions_only === counts.changed) {
            return t("{count} Effektbeschreibungen aktualisiert.", {count: number(counts.changed)});
        }
        const changes = [];
        if (counts.added) changes.push(t("{count} ergänzt", {count: number(counts.added)}));
        if (counts.removed) changes.push(t("{count} entfernt", {count: number(counts.removed)}));
        if (counts.changed) changes.push(t("{count} geändert", {count: number(counts.changed)}));
        return t("{section}: {changes}.", {
            section: t(sectionLabels[key] || key), changes: changes.join(", "),
        });
    }

    function renderResult(outputEl, data, dryRun, scopeText) {
        const doc = outputEl?.ownerDocument;
        const result = doc?.getElementById?.("updateDbResult");
        const auditEl = doc?.getElementById?.("updateDbAudit");
        const technicalNotes = doc?.getElementById?.("updateDbTechnicalNotes");
        const detailsEl = doc?.getElementById?.("updateDbDetails");
        if (!result || !auditEl) return;
        result.replaceChildren();
        auditEl.replaceChildren();
        technicalNotes?.replaceChildren();
        const add = (parent, text, tag = "p") => {
            const el = doc.createElement(tag);
            el.textContent = text;
            parent.appendChild(el);
            return el;
        };
        const report = data.summary;
        const state = !data.success ? "incomplete" : report?.status || "unknown";
        result.dataset.state = state;
        const titles = {
            available: t("Datenbank-Aktualisierung verfügbar"), current: t("Keine inhaltlichen Änderungen"),
            metadata_only: t("Nur Quelleninformationen geändert"), incomplete: t("Prüfung unvollständig oder fehlgeschlagen"),
            unknown: t("Keine Ergebniszusammenfassung verfügbar. Bitte Details prüfen."),
        };
        const title = dryRun || state === "current" ? titles[state] || titles.unknown
            : data.success ? t("Aktualisierung abgeschlossen")
                : data.update_committed ? t("Aktualisierung teilweise übernommen") : t("Aktualisierung fehlgeschlagen");
        add(result, title, "strong");
        if (state === "current") {
            add(result, t("Kein Update erforderlich."), "p").className = "update-db-mode";
        } else if (dryRun && ["available", "metadata_only"].includes(state)) {
            add(result, t("Vorschau – noch nicht übernommen"), "p").className = "update-db-mode";
        } else if (!dryRun && (data.update_committed || data.reloaded)) {
            add(result, t("Änderungen an der Item-Datenbank übernommen."), "p").className = "update-db-mode";
        }
        if (report) {
            const sources = doc.createElement("dl");
            sources.className = "update-db-source-comparison";
            for (const [label, release] of [
                [dryRun ? t("Gespeicherter Quellenstand") : t("Quellenstand vor dem Update"), report.previous_release],
                [t("Geprüfte Quelle"), report.release],
            ]) {
                const field = doc.createElement("div");
                add(field, label, "dt");
                add(field, release ? `Mojang ${release}` : t("Nicht dokumentiert"), "dd");
                sources.appendChild(field);
            }
            result.appendChild(sources);
        }
        add(result, t("Bereich: {scope}", {scope: scopeText})).className = "hint-text";
        if (data.error) add(result, data.error);
        if (data.reload_warning) add(result, data.reload_warning);
        if (!data.success && data.update_committed) add(result, t("Einige Bereiche konnten nicht aktualisiert werden. Die übernommenen Bereiche sind bereits gespeichert."));
        const changes = doc.createElement("ul");
        changes.className = "update-db-change-list";
        for (const [key, counts] of Object.entries(report?.sections || {})) {
            if (!(counts.added || counts.removed || counts.changed)) continue;
            const details = report?.change_details?.[key];
            const primary = ['items', 'stack_limits', 'durability', 'effects', 'enchants'].includes(key);
            const row = add(primary ? changes : auditEl, "", primary ? "li" : "p");
            add(row, sectionSummary(key, counts, details), "span");
            if (key === "items" && counts.changed) {
                add(row, t("Geänderte Katalogeinträge betreffen Anzeigenamen."), "small");
            }
            if (key === "stack_limits" && details) {
                add(row, t("Gespeicherte Stapellimits: {before} → {after}.", {before: number(details.before_count), after: number(details.after_count)}), "small");
                if (details.added_existing_items) add(row, t("Davon {count} Ergänzungen für bereits vorhandene Katalogeinträge.", {count: number(details.added_existing_items)}), "small");
            }
            if (key === "effects" && details?.descriptions_only && details.other_changes + counts.added + counts.removed > 0) {
                add(row, t("Davon {count} Änderungen ausschließlich an Beschreibungstexten.", {count: number(details.descriptions_only)}), "small");
            }
        }
        if (changes.childElementCount) result.appendChild(changes);
        if (report?.status === "available") add(result, t("Der Abgleich berücksichtigt Mojang-Quellen und mitgelieferte Katalogkorrekturen.")).className = "hint-text";
        const removedNonItems = report?.change_details?.items?.removed_non_items || [];
        if (removedNonItems.length) {
            add(auditEl, t("Bereinigte Textschlüssel ({count})", {count: removedNonItems.length}), "strong");
            add(auditEl, t("Diese Einträge sind Beschriftungen aus Sprachdateien und keine Items."));
            add(auditEl, removedNonItems.join(", "));
        }
        const durabilityChanges = report?.change_details?.durability?.changes || [];
        if (durabilityChanges.length) {
            add(auditEl, t("Geänderte Haltbarkeitswerte"), "strong");
            const list = doc.createElement("ul");
            list.className = "update-db-value-list";
            for (const entry of durabilityChanges) add(list, `${entry.id}: ${entry.before} → ${entry.after}`, "li");
            auditEl.appendChild(list);
        }
        const audit = report?.audit;
        if (audit) {
            add(result, t("Automatischer Abgleich: {count} Katalogeinträge geprüft.", {count: number(audit.checked_items)}));
            const issues = audit.issues || [];
            const expectedNames = audit.expected_name_differences || [];
            if (expectedNames.length && technicalNotes) {
                const groups = new Map();
                for (const entry of expectedNames) {
                    if (!groups.has(entry.id)) groups.set(entry.id, []);
                    groups.get(entry.id).push(entry);
                }
                add(technicalNotes, t("Beibehaltene Anzeigenamen ({count})", {count: number(groups.size)}), "strong");
                add(technicalNotes, t("Diese präziseren Katalognamen bleiben erhalten. Sie sind keine ausstehenden Änderungen.")).className = "hint-text";
                const list = doc.createElement("ul");
                list.className = "update-db-name-list";
                const locale = window.MCBEI18n?.isEnglish?.() ? "en" : "de";
                for (const [id, entries] of groups) {
                    const entry = entries.find(entry => entry.locale === locale) || entries[0];
                    const item = add(list, "", "li");
                    add(item, entry.catalog, "strong");
                    const language = entry.locale === locale ? "" : `${String(entry.locale).toUpperCase()} · `;
                    add(item, `${language}${t("Quelle: „{source}“", entry)} · ${id}`, "small");
                }
                technicalNotes.appendChild(list);
            }
            if (!issues.length) add(result, t("Keine Auffälligkeiten in den geprüften Daten."));
            else {
                add(result, t("Abgleich: {findings}. Siehe Änderungsdetails.", {findings: issues.map(issue => `${t(issueLabels[issue.code] || issue.code)}: ${issue.count}`).join(" · ")}));
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
        for (const blocked of report?.blocked || []) {
            const section = String(blocked.section).toLowerCase();
            add(result, `${t(sectionLabels[section === "enchantments" ? "enchants" : section] || blocked.section)}: ${blocked.reason}`);
        }
        if (detailsEl) {
            detailsEl.hidden = !auditEl.childElementCount;
            if (detailsEl.hidden) detailsEl.open = false;
        }
        if (dryRun && state === "available") add(result, t("Erst „Update anwenden“ übernimmt diese Änderungen. Bis dahin zeigt eine erneute Prüfung dieselben Unterschiede.")).className = "hint-text";
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
        actionHint,
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
        let currentResult = null;
        let confirming = false;

        function isCurrentScope(only = onlySelect?.value || null) {
            return currentResult?.only === only;
        }

        function setUpdateControlsDisabled(disabled) {
            const current = isCurrentScope();
            if (dryRunButton) dryRunButton.disabled = disabled;
            if (applyButton) applyButton.disabled = disabled || current;
            if (onlySelect) onlySelect.disabled = disabled;
            if (clearButton) clearButton.disabled = disabled;
            if (actionHint) actionHint.textContent = current
                ? t("Keine Änderungen bei der letzten Prüfung. Für einen neuen Abgleich „Änderungen prüfen“ wählen.")
                : t("Prüfe zuerst die Vorschau. Erst „Update anwenden“ übernimmt Änderungen an der Item-Datenbank.");
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
            currentResult = null;
            setUpdateControlsDisabled(true);
            outputBuffers.delete(outputEl);
            outputEl.textContent = EMPTY_OUTPUT;
            const resultEl = outputEl.ownerDocument?.getElementById?.("updateDbResult");
            if (resultEl) { resultEl.textContent = dryRun ? t("Prüfung läuft …") : t("Aktualisierung läuft …"); resultEl.dataset.state = "running"; }
            const auditEl = outputEl.ownerDocument?.getElementById?.("updateDbAudit");
            if (auditEl) auditEl.replaceChildren();
            outputEl.ownerDocument?.getElementById?.("updateDbTechnicalNotes")?.replaceChildren();
            const detailsEl = outputEl.ownerDocument?.getElementById?.("updateDbDetails");
            if (detailsEl) { detailsEl.open = false; detailsEl.hidden = true; }
            const logDetailsEl = outputEl.ownerDocument?.getElementById?.("updateDbLogDetails");
            if (logDetailsEl) logDetailsEl.open = false;

            const mode = dryRun ? t("Prüfung") : t("Update");
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
                ? t("Quelle: zuvor geprüfte Quellen (Mojang {release})", { release: matchingReview.release })
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

                if (data.success || data.reloaded) progress?.finalizing();
                let clientWarning = "";
                if (data.reloaded) {
                    try {
                        const reloadOutcome = await onReloaded(data) || {};
                        clientWarning = reloadOutcome.warning || "";
                    } catch (reloadError) {
                        console.error("onReloaded:", reloadError);
                        clientWarning = t("Die Item-Datenbank ist aktualisiert, aber die Browseransicht konnte nicht vollständig aktualisiert werden. Lade die Seite neu.");
                    }
                    if (data.summary?.status !== "current") append("\n" + t("Datenbank aktualisiert und Server neu geladen."));
                    if (clientWarning) append(clientWarning);
                }
                if (data.success) {
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
                    if (data.summary?.status === "current" && !clientWarning && !data.reload_warning) {
                        currentResult = {only};
                        const message = t("Kein Update erforderlich.");
                        append("\n" + message);
                        showToast(message, "success", 3000);
                        updateStatus(message, "success", false);
                    } else if (data.reloaded) {
                        if (clientWarning) {
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
                    } else if (dryRun) {
                        append("\n" + t("Prüfung abgeschlossen. Keine Änderungen übernommen."));
                        showToast(t("Prüfung abgeschlossen. Keine Änderungen übernommen."), "success", 3000);
                        updateStatus(t("{mode} erfolgreich.", { mode }), "success", false);
                    } else {
                        append("\n" + t("Update abgeschlossen."));
                        showToast(t("Update abgeschlossen."), "success", 3000);
                        updateStatus(t("{mode} erfolgreich.", { mode }), "success", false);
                    }
                } else {
                    reviewedSources = null;
                    append(`\n${t("Fehler (Code {code}): {error}", { code: data.returncode, error: data.error || t("Unbekannter Fehler") })}`);
                    // The backend message already says what failed.
                    const failure = window.MCBEApiClient.errorMessageInContext(
                        data,
                        reason => t("{mode} fehlgeschlagen: {error}", { mode, error: reason }),
                    );
                    const message = [data.update_committed ? t("Aktualisierung teilweise übernommen") : "", failure, data.reload_warning, clientWarning].filter(Boolean).join("\n");
                    const severity = data.update_committed ? "warning" : "error";
                    updateStatus(message, severity, true);
                    showToast(message, severity, 8000);
                }
                return data;
            } catch (e) {
                reviewedSources = null;
                currentResult = null;
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
            currentResult = null;
            setUpdateControlsDisabled(updateRunning);
            const summary = onlySelect.ownerDocument?.getElementById("updateScopeSummary");
            if (summary) summary.textContent = selectedScopeText(onlySelect);
        });
        applyButton?.addEventListener("click", async () => {
            if (updateRunning || confirming || isCurrentScope()) return;
            confirming = true;
            const only = onlySelect?.value || null;
            const matchingReview = reviewedSources?.only === only ? reviewedSources : null;
            try {
                const ok = await showConfirmDialog(
                    t("Möchtest du die Item-Datenbank aktualisieren?") + "\n\n" +
                    t("Der Abgleich berücksichtigt Mojang-Quellen und mitgelieferte Katalogkorrekturen.") + "\n\n" +
                    t("Bereich: {scope}", {scope: selectedScopeText(onlySelect, only)}) + "\n\n" +
                    (matchingReview
                        ? t("Angewendet werden die zuvor geprüften Quellen (Mojang {release}).", { release: matchingReview.release })
                        : t("Empfohlen: Zuerst „Änderungen prüfen“ wählen und die Vorschau kontrollieren."))
                );
                if (ok && !isCurrentScope(only)) await run(false, true, {only});
            } finally {
                confirming = false;
            }
        });
        clearButton?.addEventListener("click", () => {
            if (updateRunning) return;
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
            actionHint: doc.getElementById("updateDbActionHint"),
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
