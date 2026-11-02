(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const number = value => window.MCBEI18n?.formatNumber(value) ?? String(value);

    const EMPTY_OUTPUT = t("Noch keine Prüfung ausgeführt.");
    const outputBuffers = new WeakMap();
    const sectionLabels = {
        items: "Katalogeinträge", confirmed_item_labels: "Vergleichswerte für Anzeigenamen", stack_limits: "Stapellimits", durability: "Haltbarkeitswerte",
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

    function currentResultMessage(verificationRequired, only) {
        if (!verificationRequired) return t("Kein Update erforderlich.");
        return only
            ? t("Keine Änderungen im gewählten Bereich. Für die vollständige Prüfung „Alles“ wählen, prüfen und anwenden.")
            : t("Keine inhaltlichen Änderungen. „Update anwenden“ bestätigt die vollständige Prüfung der Item-Datenbank.");
    }

    // A transaction may save only the failure report. The API outcome describes
    // the catalog data, while update_committed tells the parent to reload files.
    function catalogDataSaved(result) {
        return result?.update_committed === true && result.outcome !== "failed" && result.outcome !== "current";
    }

    function sourceFailureMessage(data) {
        if (data?.category === "network-or-dns") return t("Online-Quelle nicht erreichbar.");
        if (data?.category === "client-connection") return t("Verbindung zum Editor unterbrochen.");
        if (data?.category === "github-rate-limit") return t("GitHub-Anfragelimit erreicht. Bitte später erneut versuchen.");
        return "";
    }

    function compactUpdateMessage(data, dryRun, quality = {}) {
        if (!data.success && !catalogDataSaved(data) && sourceFailureMessage(data)) return sourceFailureMessage(data);
        if (!data.success && dryRun) return data.summary?.blocked?.length || quality.blocked?.length
            ? t("Prüfung unvollständig. Details prüfen.") : t("Prüfung fehlgeschlagen. Details prüfen.");
        if (!data.success) {
            if (!catalogDataSaved(data)) return t("Aktualisierung fehlgeschlagen. Details prüfen.");
            return data.outcome === "partial" ? t("Teilweise aktualisiert. Details prüfen.") : t("Änderungen gespeichert. Hinweise in den Details.");
        }
        if (data.client_warning || data.reload_warning) return t("Datenbank aktualisiert. Anzeige noch nicht erneuert. Details prüfen.");
        if (data.summary?.status === "current") {
            if (data.verification_required) return t("Prüfung abgeschlossen. Bestätigung erforderlich.");
            return quality.hasWarnings ? t("Bereits aktuell. Hinweise in den Details.") : t("Bereits aktuell.");
        }
        return dryRun ? t("Prüfung abgeschlossen mit Hinweisen. Details prüfen.") : t("Aktualisiert mit Hinweisen. Details prüfen.");
    }

    function renderResult(outputEl, data, dryRun, scopeText, only = null) {
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
        const quality = window.MCBEDataSourceView?.itemDbQualityModel(report?.quality) || {};
        const state = !data.success ? "incomplete" : report?.status || "unknown";
        result.dataset.state = !data.success && !catalogDataSaved(data) ? "failed" : state;
        const titles = {
            available: t("Datenbank-Aktualisierung verfügbar"), current: t("Keine inhaltlichen Änderungen"),
            metadata_only: t("Nur Quelleninformationen geändert"), incomplete: t("Prüfung unvollständig oder fehlgeschlagen"),
            unknown: t("Keine Ergebniszusammenfassung verfügbar. Bitte Details prüfen."),
        };
        const outcomeTitles = { current: t("Bereits aktuell"), updated_with_warnings: t("Aktualisiert mit Hinweisen"), partial: t("Teilweise aktualisiert"), failed: t("Fehlgeschlagen – nichts übernommen") };
        const title = !dryRun && outcomeTitles[data.outcome] ? outcomeTitles[data.outcome]
            : dryRun || state === "current" ? titles[state] || titles.unknown
            : data.success ? t("Aktualisierung abgeschlossen")
                : data.update_committed ? t("Aktualisierung teilweise übernommen") : t("Aktualisierung fehlgeschlagen");
        add(result, title, "strong");
        if (state === "current") {
            add(result, currentResultMessage(data.verification_required === true, only), "p").className = "update-db-mode";
        } else if (dryRun && ["available", "metadata_only"].includes(state)) {
            add(result, t("Vorschau – noch nicht übernommen"), "p").className = "update-db-mode";
        } else if (!dryRun && data.outcome === "partial" && catalogDataSaved(data)) {
            const groups = new Set((report?.blocked || []).map(entry => String(entry.section).toLowerCase()));
            const sections = [...groups].map(key => sectionLabels[key === "enchantments" ? "enchants" : key]).filter(Boolean).map(label => t(label));
            add(result, sections.length
                ? t("Die geprüften Änderungen sind gespeichert. Der bisherige Stand für {sections} bleibt erhalten.", {sections: sections.join(", ")})
                : t("Die geprüften Änderungen sind gespeichert."), "p").className = "update-db-mode";
        } else if (!dryRun && data.outcome !== "failed" && (data.update_committed || data.reloaded)) {
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
            auditEl.appendChild(sources);
        }
        add(auditEl, t("Bereich: {scope}", {scope: scopeText})).className = "hint-text";
        if (quality.brief && data.outcome !== "partial") add(result, quality.brief);
        if (quality.summary) add(auditEl, quality.summary);
        for (const line of quality.lines || []) add(auditEl, line);
        if (quality.details?.length) {
            add(auditEl, t("Namensherkunft"), "strong");
            for (const line of quality.details) add(auditEl, line);
        }
        for (const message of new Set([data.error, data.hint, data.reload_warning, data.client_warning, data.pending_reload_warning].filter(Boolean))) add(auditEl, message);
        if (data.reload_warning) add(result, t("Bitte den Editor neu starten."));
        else if (data.client_warning) add(result, t("Hinweise zum weiteren Vorgehen stehen in den Details."));
        else if (sourceFailureMessage(data)) add(result, sourceFailureMessage(data));
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
            add(auditEl, t("Automatischer Abgleich: {count} Katalogeinträge geprüft.", {count: number(audit.checked_items)}));
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
            if (!issues.length && !quality.hasWarnings) add(result, t("Keine Auffälligkeiten in den geprüften Daten."));
            else if (issues.length) {
                add(auditEl, t("Abgleich: {findings}. Siehe Änderungsdetails.", {findings: issues.map(issue => `${t(issueLabels[issue.code] || issue.code)}: ${issue.count}`).join(" · ")}));
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
            if (quality.blocked?.includes(section === "enchantments" ? "enchants" : section)) continue;
            add(auditEl, `${t(sectionLabels[section === "enchantments" ? "enchants" : section] || blocked.section)}: ${blocked.reason}`);
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
        onApplyResult = () => {},
        canWriteAppState = () => true,
        startUpdateProgress = title => window.MCBEAssetUpdateProgress?.start(title),
    } = {}) {
        const append = (text) => appendOutput(outputEl, text);
        let updateRunning = false;
        let reviewedSources = null;
        let currentResult = null;
        let confirming = false;
        const unresolvedRuns = new Map();
        let pendingReloadWarning = "";

        function isApplyUnnecessary(only = onlySelect?.value || null) {
            return currentResult?.only === only && (!currentResult.verificationRequired || only !== null);
        }

        function setUpdateControlsDisabled(disabled) {
            const only = onlySelect?.value || null;
            const current = currentResult?.only === only;
            const locked = !canWriteAppState();
            if (dryRunButton) dryRunButton.disabled = disabled || locked;
            if (applyButton) applyButton.disabled = disabled || locked || isApplyUnnecessary(only);
            if (onlySelect) onlySelect.disabled = disabled || locked;
            if (clearButton) clearButton.disabled = disabled;
            if (actionHint) actionHint.textContent = locked ? t("Nur ansehen: Diese Instanz darf keine App-Daten schreiben.")
                : current && currentResult.verificationRequired
                ? currentResultMessage(true, only)
                : current
                    ? t("Keine Änderungen bei der letzten Prüfung. Für einen neuen Abgleich „Änderungen prüfen“ wählen.")
                    : t("Prüfe zuerst die Vorschau. Erst „Update anwenden“ übernimmt Änderungen an der Item-Datenbank.");
        }

        async function run(dryRun, force = false, options = {}) {
            if (!canWriteAppState()) return {success: false, error: t("Nur ansehen: Diese Instanz darf keine App-Daten schreiben.")};
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
            const only = Object.prototype.hasOwnProperty.call(options, "only")
                ? (options.only || null)
                : (onlySelect?.value || null);
            const statusKey = ["database-update", dryRun ? "dry-run" : "apply", only].filter(Boolean).join(":");
            const matchingReview = !dryRun && reviewedSources?.only === only ? reviewedSources : null;
            const resolveKeys = [];
            unresolvedRuns.delete(statusKey);
            if (dryRun) reviewedSources = null;
            let statusDetails = "";
            let needsReload = false;
            const scopeDetail = only ? t("Bereich: {scope}", {scope: selectedScopeText(onlySelect, only)}) : "";
            const updateStatus = (message, type, active) => {
                if (active && type !== "running") unresolvedRuns.set(statusKey, {only, dryRun, needsReload});
                logStatus(message, type, {
                    key: statusKey, active, resolveKeys: [...resolveKeys],
                    details: [scopeDetail, statusDetails].filter(Boolean).join("\n\n"),
                });
            };
            append(`\n${t("=== {mode} gestartet ===", { mode })}`);
            append(t("Bereich: {scope}", { scope: selectedScopeText(onlySelect, only) }));
            append(matchingReview
                ? t("Quelle: zuvor geprüfte Quellen (Mojang {release})", { release: matchingReview.release })
                : t("Quelle: neuestes Mojang-Release automatisch prüfen"));
            append("");

            showLoading(t("{mode} wird ausgeführt...", { mode }));
            const progress = startUpdateProgress(dryRun ? t("Item-Datenbank prüfen") : t("Item-Datenbank aktualisieren"));
            updateStatus(t("{mode} läuft...", { mode }), "running", true);

            let responseReceived = false;
            let result;
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
                responseReceived = true;
                const data = await parseJsonResponse(res);
                const quality = window.MCBEDataSourceView?.itemDbQualityModel(data.summary?.quality) || {};
                const reviewToken = data.update_review_token || data.release_cache_token;
                // A partial preview can still bind safe sections to the checked source.
                const hasPreviewReceipt = dryRun && reviewToken && data.resource_pack_release;
                if (hasPreviewReceipt) {
                    reviewedSources = { only, token: reviewToken, release: data.resource_pack_release };
                }

                if (data.output) append(data.output);

                if (data.success || data.reloaded) progress?.finalizing();
                let clientWarning = "";
                if (data.reloaded) {
                    try {
                        const reloadOutcome = await onReloaded(data) || {};
                        clientWarning = reloadOutcome.warning || "";
                    } catch (reloadError) {
                        console.error("onReloaded:", reloadError);
                        clientWarning = data.outcome === "failed" ? t("Der Prüfstatus konnte im Browser nicht aktualisiert werden. Lade die Seite neu.")
                            : t("Die Item-Datenbank ist aktualisiert, aber die Browseransicht konnte nicht vollständig aktualisiert werden. Lade die Seite neu.");
                    }
                    if (data.outcome === "failed") append("\n" + t("Prüfbericht gespeichert und Status neu geladen."));
                    else if (data.summary?.status !== "current") append("\n" + t("Item-Datenbank aktualisiert."));
                    if (clientWarning) append(clientWarning);
                }
                // A later preview must not erase the still-active explanation
                // for an earlier saved update whose view could not be refreshed.
                const reloadWarning = data.reload_warning || (!dryRun && data.success && data.update_committed && !data.reloaded
                    ? t("Die Item-Datenbank wurde gespeichert. Bitte den Editor neu starten, um sie zu laden.") : "");
                needsReload = Boolean(clientWarning || reloadWarning);
                if (data.outcome !== "failed") {
                    if (!dryRun && data.reloaded && !clientWarning && !reloadWarning) pendingReloadWarning = "";
                    if (clientWarning || reloadWarning) pendingReloadWarning = clientWarning || reloadWarning;
                }
                const feedbackData = { ...data, reload_warning: reloadWarning, client_warning: clientWarning, pending_reload_warning: pendingReloadWarning };
                statusDetails = [...new Set([
                    data.error, data.hint, reloadWarning, clientWarning, pendingReloadWarning,
                    quality.summary, ...(quality.lines || []),
                    ...(data.summary?.blocked || []).map(entry => `${t(sectionLabels[entry.section] || entry.section)}: ${entry.reason}`),
                ].filter(Boolean))].join("\n\n");
                renderResult(outputEl, feedbackData, dryRun, selectedScopeText(onlySelect, only), only);
                const notice = compactUpdateMessage(feedbackData, dryRun, quality);
                if (data.success) {
                    // Applying a checked scope resolves its earlier preview failure.
                    // A preview can only resolve a failed write when it confirms that
                    // the database is already current and fully verified.
                    const verifiedCurrent = data.summary?.status === "current" && data.verification_required === false;
                    for (const [key, run] of unresolvedRuns) {
                        if (only !== null && run.only !== only) continue;
                        if (run.needsReload && (!data.reloaded || clientWarning || reloadWarning)) continue;
                        if (dryRun && !run.dryRun && !verifiedCurrent) continue;
                        resolveKeys.push(key);
                        unresolvedRuns.delete(key);
                    }
                    if (!dryRun) {
                        reviewedSources = null;
                    }
                    // A player-view warning does not invalidate the confirmed database state.
                    if (data.summary?.status === "current" && !reloadWarning) {
                        currentResult = {only, verificationRequired: data.verification_required === true};
                    }
                    if (currentResult && !clientWarning) {
                        const message = [currentResultMessage(currentResult.verificationRequired, only), quality.summary].filter(Boolean).join(" ");
                        append("\n" + message);
                        showToast(notice, quality.hasWarnings ? "warning" : "success", 3000);
                        updateStatus(notice, quality.hasWarnings ? "warning" : "success", Boolean(quality.hasWarnings));
                    } else if (quality.hasWarnings && !clientWarning && !reloadWarning) {
                        const message = [dryRun ? t("Prüfung abgeschlossen mit Hinweisen.") : t("Aktualisiert mit Hinweisen"), quality.summary].filter(Boolean).join(" ");
                        append("\n" + message);
                        showToast(notice, "warning", 5000);
                        updateStatus(notice, "warning", true);
                    } else if (data.reloaded) {
                        if (clientWarning) {
                            showToast(notice, "warning", 8000);
                            updateStatus(notice, "warning", true);
                        } else {
                            showToast(t("Item-Datenbank aktualisiert."), "success", 5000);
                            updateStatus(t("{mode} erfolgreich.", { mode }), "success", false);
                        }
                    } else if (!dryRun && data.update_committed) {
                        append(`\n${reloadWarning}`);
                        updateStatus(notice, "warning", true);
                        showToast(notice, "warning", 8000);
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
                    if (!hasPreviewReceipt) reviewedSources = null;
                    append(`\n${t("Fehler (Code {code}): {error}", { code: data.returncode, error: data.error || t("Unbekannter Fehler") })}`);
                    // The backend message already says what failed.
                    const failure = window.MCBEApiClient.errorMessageInContext(
                        data,
                        reason => t("{mode} fehlgeschlagen: {error}", { mode, error: reason }),
                    );
                    const message = [data.outcome === "partial" ? t("Aktualisierung teilweise übernommen") : "", failure, data.reload_warning, clientWarning].filter(Boolean).join("\n");
                    const severity = catalogDataSaved(data) ? "warning" : "error";
                    append(message);
                    updateStatus(notice, severity, true);
                    showToast(notice, severity, 8000);
                }
                result = clientWarning || reloadWarning ? feedbackData : data;
                return result;
            } catch (e) {
                reviewedSources = null;
                currentResult = null;
                console.error("runUpdateDb:", e);
                const message = e?.message || t("Verbindungsfehler beim Datenbank-Update.");
                statusDetails = message;
                append(`\n${t("{mode} fehlgeschlagen: {error}", { mode, error: message })}`);
                result = {success: false, error: message, ...(!responseReceived ? {category: "client-connection"} : {})};
                const notice = compactUpdateMessage(result, dryRun);
                updateStatus(notice, "error", true);
                showToast(notice, "error", 5000);
                renderResult(outputEl, {...result, pending_reload_warning: pendingReloadWarning}, dryRun, selectedScopeText(onlySelect, only), only);
                return result;
            } finally {
                if (!dryRun && result) {
                    try { await onApplyResult(result); }
                    catch (err) { console.error("Item-DB setup status:", err); }
                }
                progress?.stop();
                hideLoading();
                updateRunning = false;
                setUpdateControlsDisabled(false);
            }
        }

        setUpdateControlsDisabled(false);
        dryRunButton?.addEventListener("click", () => run(true, false));
        onlySelect?.addEventListener?.("change", () => {
            reviewedSources = null;
            currentResult = null;
            setUpdateControlsDisabled(updateRunning);
            const summary = onlySelect.ownerDocument?.getElementById("updateScopeSummary");
            if (summary) summary.textContent = selectedScopeText(onlySelect);
        });
        applyButton?.addEventListener("click", async () => {
            if (!canWriteAppState() || updateRunning || confirming || isApplyUnnecessary()) return;
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
                if (ok && canWriteAppState() && !isApplyUnnecessary(only)) await run(false, true, {only});
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
        onApplyResult = () => {},
        canWriteAppState = () => true,
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
            onApplyResult,
            canWriteAppState,
        });
    }


    window.MCBEUpdateDbView = {
        EMPTY_OUTPUT,
        appendOutput,
        catalogDataSaved,
        sourceFailureMessage,
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
