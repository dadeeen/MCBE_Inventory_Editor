(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function statusSeverityRank(value) {
        if (value === "error" || value === "blocked" || value === "missing") return 2;
        if (value === "warning" || value === "unknown" || value === "check") return 1;
        return 0;
    }

    function statusSeverityClass(rank) {
        return rank >= 2 ? "error" : rank === 1 ? "warning" : "ok";
    }

    function statusSeverityLabel(rank) {
        return rank >= 2 ? t("Prüfen") : rank === 1 ? t("Hinweise") : t("Alles OK");
    }

    function statusTile(label, value, detail, rank = 0) {
        const cls = statusSeverityClass(rank);
        return `<div class="status-tile ${cls}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail || "")}</small></div>`;
    }

    function formatDeNumber(value) {
        return window.MCBEI18n?.formatNumber?.(value || 0) || Number(value || 0).toLocaleString();
    }

    function formatItemDbTime(value) {
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return window.MCBEI18n?.formatDate?.(date) || date.toLocaleString();
    }

    function itemDbCountsText(status = {}) {
        const counts = status?.counts || {};
        return t("{items} Items · {effects} Effekte · {enchantments} Verzauberungen", { items: formatDeNumber(counts.items), effects: formatDeNumber(counts.effects), enchantments: formatDeNumber(counts.enchantments) });
    }

    function itemDbQualityModel(quality) {
        const sections = { items: "Items", effects: "Effekte", enchants: "Verzauberungen" };
        const sources = { curated: "geprüfter Katalogname", existing: "beibehaltener Name", other_language: "andere Sprache", identifier: "technische Kennung", microsoft: "Microsoft-Learn-Itemliste", composed: "aus Quellen zusammengesetzter Name" };
        const reasons = { ambiguous: "Quellzuordnung mehrdeutig", composed: "Bezeichnung und Titel stehen in der Quelle getrennt", category: "geprüfte Sammelbezeichnung für Varianten", editorial: "redaktionelle Bezeichnung des Editors", documented: "Bezeichnung aus offizieller Mojang-Dokumentation" };
        const lines = [], details = [], blocked = [];
        let unresolved = 0, notes = 0;
        if (quality?.schema !== 1 || !quality.sections) return { hasWarnings: false, hasNotes: false, blocked, summary: "", lines, details };
        for (const [section, label] of Object.entries(sections)) {
            const entry = quality.sections[section];
            if (!entry) continue;
            if (entry.status === "blocked") {
                blocked.push(section);
                lines.push(t("{section} unverändert: {reason}", { section: t(label), reason: entry.reason || t("Die Quelldaten konnten nicht sicher zugeordnet werden.") }));
                lines.push(t("Beibehaltener Quellenstand: {release}.", { release: entry.release || t("Nicht dokumentiert") }));
            }
            for (const [locale, language] of [["de", "DE"], ["en", "EN"]]) {
                const names = entry.locales?.[locale];
                if (!names || !Number.isInteger(names.total) || !Number.isInteger(names.official)) continue;
                const missing = Math.max(0, names.total - Math.max(0, names.official));
                const fallbacks = Array.isArray(names.fallbacks) ? names.fallbacks : [];
                const retained = Array.isArray(names.retained) ? names.retained : [];
                if (!missing && !retained.length) continue;
                lines.push(t("{section} ({language}): {official} von {total} offiziellen Namen verfügbar.", {
                    section: t(label), language: t(language), official: formatDeNumber(Math.max(0, names.official)), total: formatDeNumber(names.total),
                }));
                // Old reports remain readable. Missing classifications cannot
                // be silently promoted to checked names.
                unresolved += Math.max(0, missing - fallbacks.length);
                const entries = [...fallbacks, ...retained];
                for (const entry of entries) {
                    const uncertain = !entry || !sources[entry.source] || entry.reason === "ambiguous" || ["identifier", "other_language"].includes(entry.source);
                    if (uncertain) unresolved++; else notes++;
                }
                for (const entry of entries.filter(entry => entry && typeof entry.id === "string").slice(0, 100)) {
                    const explanation = reasons[entry.reason] || (retained.includes(entry) ? "abweichend vom verfügbaren Mojang-Namen" : "kein eindeutig zugeordneter Quellenname");
                    details.push(`${t(label)} · ${t(language)} · ${entry.id}: ${t(sources[entry.source] || "technische Kennung")} · ${t(explanation)}`);
                }
                if (entries.length > 100) details.push(t("{count} weitere Namenseinträge", { count: formatDeNumber(entries.length - 100) }));
            }
        }
        return {
            hasWarnings: blocked.length > 0 || unresolved > 0,
            hasNotes: notes > 0,
            blocked, lines, details,
            brief: blocked.length ? t("Einige Bereiche bleiben unverändert. Details prüfen.")
                : unresolved ? t("Einige Namen sind nicht eindeutig. Die Datenbank bleibt nutzbar.") : "",
            summary: [
                unresolved ? t("Für {count} Sprachwerte fehlt ein eindeutiger Name in der jeweiligen Sprache.", { count: formatDeNumber(unresolved) }) : "",
                unresolved ? t("Vorhandene Namen bleiben nutzbar. Ein erneuter Download derselben Quelle behebt fehlende Übersetzungen nicht.") : "",
                notes && !unresolved && !blocked.length ? t("Geprüfte Editor-Namen und eigene Namen bleiben erhalten. Kein Handlungsbedarf wegen der Namen.") : "",
            ].filter(Boolean).join(" "),
        };
    }

    function itemDbQualityHtml(quality) {
        const model = itemDbQualityModel(quality);
        if (!model.hasWarnings && !model.hasNotes) return "";
        return `<div class="${model.hasWarnings ? "tool-notice" : "hint-text"}" data-db-quality>
            ${model.brief || model.summary ? `<p>${escapeHtml(model.brief || model.summary)}</p>` : ""}
            ${model.lines.length || model.details.length ? `<details class="tool-details"><summary>${t("Details anzeigen")}</summary>${model.brief && model.summary ? `<p>${escapeHtml(model.summary)}</p>` : ""}<strong>${t("Namensherkunft")}</strong><p>${t("Die Quellenabdeckung zählt Namen aus den aktuellen Mojang-Sprachdateien. Bezeichnungen aus Mojang-Dokumentation, redaktionelle und eigene Namen sind getrennt gekennzeichnet. Deutsch und Englisch werden getrennt gezählt.")}</p>${model.lines.map(line => `<p>${escapeHtml(line)}</p>`).join("")}<ul>${model.details.map(line => `<li>${escapeHtml(line)}</li>`).join("")}</ul></details>` : ""}
        </div>`;
    }

    function itemDbSetupFeedback(status) {
        const model = itemDbQualityModel(status?.update_quality);
        return {
            partial: model.blocked.length > 0,
            warnings: model.hasWarnings,
            reloadWarning: status?.reload_warning || "",
            details: [status?.reload_warning, model.summary, ...model.lines, ...model.details].filter(Boolean),
        };
    }

    function itemDbBlockedMessages(blocked) {
        const sections = { items: "Items", effects: "Effekte", enchants: "Verzauberungen", enchantments: "Verzauberungen", source: "Quelldaten" };
        return (Array.isArray(blocked) ? blocked : []).map(entry => {
            const key = String(entry.section || "source").toLowerCase();
            return `${t(sections[key] || entry.section)}: ${entry.reason || t("Die Quelldaten konnten nicht sicher zugeordnet werden.")}`;
        });
    }

    function itemDbStatusRank(status = null) {
        if (!status || status.reload_warning) return 1;
        if (itemDbQualityModel(status.update_quality).hasWarnings) return 1;
        return status.status === "ok" && status.verification?.verified === true ? 0 : 1;
    }

    function itemDbStatusValue(status = null) {
        if (!status) return t("lädt");
        if (status.status === "conflict") return t("Katalogbereich gesperrt");
        if (status.reload_warning) return t("Item-DB-Aktualisierung fehlgeschlagen.");
        if (status.status === "unavailable") return t("Status nicht verfügbar");
        if (status.status !== "ok") return t("Herkunft fehlt");
        const quality = itemDbQualityModel(status.update_quality);
        if (quality.blocked.length) return t("Prüfung unvollständig");
        if (quality.hasWarnings && status.verification?.verified === true) return t("geprüft mit Hinweisen");
        return status.verification?.verified === true ? t("geprüft") : t("Prüfung offen");
    }

    function itemDbSourceText(status = null) {
        if (!status) return t("Status wird geladen");
        if (status.status === "conflict") return status.message || t("Katalogbereich gesperrt");
        if (status.reload_warning) return status.reload_warning;
        if (status.status === "unavailable") return status.message || t("Item-DB-Status konnte nicht geladen werden.");
        const meta = status.source_version || {};
        if (status.source_version_present) {
            const parts = [];
            if (meta.resource_pack_release) parts.push(`Mojang ${meta.resource_pack_release}`);
            const verified = formatItemDbTime(status.verification?.verified_at);
            const generated = formatItemDbTime(meta.generated_at);
            if (verified) parts.push(t("geprüft {when}", { when: verified }));
            else if (generated) parts.push(t("erzeugt {when}", { when: generated }));
            return parts.length ? parts.join(" · ") : t("Quellmetadaten vorhanden");
        }
        return t("Quellmetadaten fehlen; die Datenbank wird konservativ verwendet.");
    }

    function iconStateSummary(summary = {}) {
        if (summary?.status === "loading") {
            return { rank: 1, value: t("lädt"), detail: t("Status wird geladen") };
        }
        if (summary?.status === "unavailable") {
            return { rank: 1, value: t("Status nicht verfügbar"), detail: summary.message || t("Icon-Status konnte nicht geladen werden.") };
        }
        const health = summary?.health || {};
        const count = Number(summary?.count || 0);
        const warnings = Array.isArray(summary?.warnings) ? summary.warnings.length : 0;
        const sourceCount = Number(health.enabled_sources || (summary?.sources || []).filter(src => src.enabled !== false).length || 0);
        const existingSources = Number(health.existing_sources || (summary?.sources || []).filter(src => src.enabled !== false && src.exists).length || 0);
        const scanned = Number(summary?.scanned_files || 0);
        const cacheState = summary?.vanilla_cache?.state;
        if (count > 0) {
            if (cacheState === "stale" || cacheState === "damaged") {
                return { rank: 1, value: t("Prüfen"), detail: cacheState === "damaged"
                    ? t("Einige Vanilla-Icons fehlen oder wurden verändert. Prüfe unter Icons die Aktualität.")
                    : t("Die Icon-Zuordnung muss geprüft werden. Prüfe unter Icons die Aktualität.") };
            }
            const missingPatterns = Boolean(summary?.missing_banner_patterns?.length);
            return {
                rank: warnings || missingPatterns ? 1 : 0,
                value: warnings || missingPatterns ? t("Hinweise") : t("bereit"),
                detail: missingPatterns ? t("Bannermuster fehlen")
                    : t("{count} lokale Icons · {files} Dateien geprüft", { count: formatDeNumber(count), files: formatDeNumber(scanned) }),
            };
        }
        if (sourceCount > 0) {
            return {
                rank: 1,
                value: t("Fallback"),
                detail: t("0 passende Texturen · {existing}/{sources} Quellen vorhanden", { existing: formatDeNumber(existingSources), sources: formatDeNumber(sourceCount) }),
            };
        }
        return { rank: 1, value: t("Fallback"), detail: t("keine Icon-Quelle geladen") };
    }

    function versionEntryCell(entry, key, maxLength = 0) {
        const value = entry && entry[key] !== undefined && entry[key] !== null ? String(entry[key]) : "";
        return escapeHtml(maxLength && value.length > maxLength ? value.slice(0, maxLength) : value);
    }

    function itemDbVersionHistoryHtml({ visible = false, loading = false, error = "", entries = null } = {}) {
        const hidden = visible ? "" : " hidden";
        let body = "";
        if (loading) {
            body = `<div class="no-backups">${t("Versionshistorie wird geladen...")}</div>`;
        } else if (error) {
            body = `<div class="no-backups">${t("Versionshistorie konnte nicht geladen werden: {error}", { error: escapeHtml(error) })}</div>`;
        } else if (Array.isArray(entries) && entries.length) {
            // Wiki comparison details are intentionally not shown to users.
            body = `
            <table class="version-table">
                <thead>
                    <tr>
                        <th scope="col">${t("Datum")}</th>
                        <th scope="col">Resource Pack</th>
                    </tr>
                </thead>
                <tbody>
                    ${entries.map(entry => `
                    <tr>
                        <td>${escapeHtml(formatItemDbTime(entry?.generated_at))}</td>
                        <td>${versionEntryCell(entry, "resource_pack_release")}</td>
                    </tr>`).join("")}
                </tbody>
            </table>
        `;
        } else {
            body = `<div class="no-backups">${t("Noch keine Versionseinträge vorhanden. Führe ein DB-Update aus.")}</div>`;
        }
        return `<div id="itemDbVersionHistory" class="item-db-version-history" role="region" aria-label="${t("Versionsverlauf")}" tabindex="0"${hidden}>${body}</div>`;
    }

    function assetDataStatusHtml({
        itemDbStatus = null,
        iconSummary = {},
        unknownItems = 0,
        hasCurrentPlayer = false,
    } = {}) {
        const iconState = iconStateSummary(iconSummary);
        const dbRank = itemDbStatusRank(itemDbStatus);
        const unknownValue = hasCurrentPlayer
            ? (unknownItems ? t("{count} ID(s)", { count: formatDeNumber(unknownItems) }) : t("keine"))
            : t("wartet");
        const unknownDetail = hasCurrentPlayer
            ? (unknownItems ? t("Item-Daten werden erhalten; DB-Stand prüfen.") : t("geladener Spieler passt zur Item-DB"))
            : t("nach dem Laden eines Spielers sichtbar");
        const notices = [];
        if (dbRank && itemDbStatus) notices.push(`<p>${escapeHtml(itemDbStatusValue(itemDbStatus))} · ${escapeHtml(itemDbSourceText(itemDbStatus))}</p>`);
        if (hasCurrentPlayer && unknownItems) notices.push(`<p>${escapeHtml(t("Unbekannte Items"))}: ${escapeHtml(unknownValue)} · ${escapeHtml(unknownDetail)}</p>`);
        if (iconSummary?.status === "unavailable") notices.push(`<p>${escapeHtml(iconState.detail)}</p>`);
        if (!notices.length) return "";
        return `<div class="tool-notice">${notices.join("")}<button class="btn-text" type="button" data-open-db-status>${t("Item-DB öffnen")}</button></div>`;
    }

    function itemDbStatusHtml({
        itemDbStatus = null,
        appItemDbPath = "",
        historyVisible = false,
        historyLoading = false,
        historyError = "",
        historyEntries = null,
    } = {}) {
        const dbRank = itemDbStatusRank(itemDbStatus);
        const sourceLine = itemDbSourceText(itemDbStatus);
        const statusClass = statusSeverityClass(dbRank);
        const pathText = itemDbStatus?.path || appItemDbPath || "item_db.json";
        const historyText = itemDbStatus?.history_count
            ? t("{count} Versionseinträge", { count: formatDeNumber(itemDbStatus.history_count) })
            : t("keine Versionshistorie");
        return `
            <div class="item-db-status-hero ${statusClass}">
                <div>
                    <div class="item-db-version-line"><strong>${t("Aktive Item-Datenbank")}</strong><span>${escapeHtml(itemDbStatus?.source_version?.resource_pack_release ? `Mojang ${itemDbStatus.source_version.resource_pack_release}` : t("Herkunft fehlt"))}</span></div>
                    ${dbRank ? `<small>${escapeHtml(itemDbStatusValue(itemDbStatus))} · ${escapeHtml(sourceLine)}</small>` : ""}
                </div>
                <span>${escapeHtml(itemDbCountsText(itemDbStatus))}</span>
            </div>
            ${itemDbQualityHtml(itemDbStatus?.update_quality)}
            <details class="tool-details" data-db-details><summary>${t("Technische Details")}</summary>
            <dl class="tool-facts">
                <div><dt>${t("Prüfnachweis")}</dt><dd>${escapeHtml(itemDbStatusValue(itemDbStatus))} · ${t("Bestätigt die gespeicherte Datenbank und ihre Quellenmetadaten, nicht die Aktualität oder Spielkompatibilität.")}</dd></div>
                <div><dt>${t("Aktive Item-Datenbank")}</dt><dd>${escapeHtml(sourceLine)}</dd></div>
                <div><dt>${t("Schema")}</dt><dd>v${escapeHtml(itemDbStatus?.schema_version || "?")} · ${escapeHtml(historyText)}</dd></div>
                <div><dt>${t("Pfad")}</dt><dd>${escapeHtml(pathText)}</dd></div>
            </dl>
            <p class="hint-text">${t("Updates laden offizielle Identifier und Namen aus Mojang/bedrock-samples. Verzauberungs-Maximalstufen stammen aus einer mitgelieferten, geprüften Vanilla-Tabelle.")}</p>
            <button class="btn-text" type="button" data-toggle-db-versions aria-controls="itemDbVersionHistory" aria-expanded="${historyVisible ? "true" : "false"}">${t("Versionsverlauf ({count})", { count: formatDeNumber(Array.isArray(historyEntries) ? historyEntries.length : itemDbStatus?.history_count) })}</button>
            ${itemDbVersionHistoryHtml({
                visible: historyVisible,
                loading: historyLoading,
                error: historyError,
                entries: historyEntries,
            })}</details>
        `;
    }


    function createDataSourceController({
        elements = {},
        appConfig = {},
        parseJsonResponse = async response => response.json(),
        getItemDbStatus = () => null,
        setItemDbStatus = () => {},
        getIconSourceSummary = () => ({}),
        getUnknownItemCount = () => 0,
        hasCurrentPlayer = () => false,
        openItemDbStatus = () => {},
        renderStatusCenter = () => {},
        onItemDbStatusApplied = () => {},
        logStatus = () => {},
    } = {}) {
        const {
            assetDataStatusPanel = null,
            itemDbStatusPanel = null,
        } = elements;
        let historyVisible = false;
        let historyEntries = null;
        let historyLoading = false;
        let historyError = "";
        let historyRequestId = 0;
        let statusRequestId = 0;

        function render() {
            const itemDbStatus = getItemDbStatus();
            const unknownItems = getUnknownItemCount();

            if (assetDataStatusPanel) {
                assetDataStatusPanel.innerHTML = assetDataStatusHtml({
                    itemDbStatus,
                    iconSummary: getIconSourceSummary(),
                    unknownItems,
                    hasCurrentPlayer: Boolean(hasCurrentPlayer()),
                });
                assetDataStatusPanel.hidden = !assetDataStatusPanel.innerHTML.trim();
                assetDataStatusPanel.querySelector("[data-open-db-status]")?.addEventListener("click", openItemDbStatus);
            }

            if (itemDbStatusPanel) {
                const activeElement = itemDbStatusPanel.ownerDocument?.activeElement;
                const restoreToggleFocus = activeElement === itemDbStatusPanel.querySelector("[data-toggle-db-versions]");
                const previousHistory = itemDbStatusPanel.querySelector(".item-db-version-history");
                const restoreHistoryFocus = Boolean(previousHistory && activeElement === previousHistory);
                const historyScrollTop = previousHistory?.scrollTop || 0;
                const detailsOpen = itemDbStatusPanel.querySelector("[data-db-details]")?.open || false;
                itemDbStatusPanel.innerHTML = itemDbStatusHtml({
                    itemDbStatus,
                    appItemDbPath: appConfig?.item_db_path,
                    historyVisible,
                    historyLoading,
                    historyError,
                    historyEntries,
                });
                const details = itemDbStatusPanel.querySelector("[data-db-details]");
                if (details) details.open = detailsOpen;
                itemDbStatusPanel.querySelector("[data-toggle-db-versions]")?.addEventListener("click", toggleVersionHistory);
                if (restoreToggleFocus) itemDbStatusPanel.querySelector("[data-toggle-db-versions]")?.focus();
                const history = itemDbStatusPanel.querySelector(".item-db-version-history");
                if (history && historyVisible) {
                    history.scrollTop = historyScrollTop;
                    if (restoreHistoryFocus) history.focus({ preventScroll: true });
                }
            }
        }

        async function toggleVersionHistory() {
            if (historyVisible) {
                historyVisible = false;
                render();
                return;
            }
            historyVisible = true;
            if (Array.isArray(historyEntries)) {
                render();
                return;
            }

            historyLoading = true;
            historyError = "";
            const requestId = ++historyRequestId;
            render();
            try {
                const res = await fetch("/api/item-db/versions");
                const data = await parseJsonResponse(res);
                if (requestId !== historyRequestId) return;
                if (!data.success) throw new Error(data.error || t("Unbekannter Fehler"));
                historyEntries = Array.isArray(data.entries) ? data.entries : [];
            } catch (err) {
                if (requestId !== historyRequestId) return;
                historyEntries = null;
                historyError = err.message || String(err);
                logStatus(t("Versionshistorie konnte nicht geladen werden."), "warning");
            } finally {
                if (requestId === historyRequestId) {
                    historyLoading = false;
                    render();
                }
            }
        }

        function applyItemDbStatus(status) {
            const normalizedStatus = status || null;
            // A status refresh can follow an update of the database and history.
            statusRequestId++;
            historyRequestId++;
            historyVisible = false;
            historyEntries = null;
            historyLoading = false;
            historyError = "";
            setItemDbStatus(normalizedStatus);
            render();
            renderStatusCenter();
            onItemDbStatusApplied(normalizedStatus);
            return normalizedStatus;
        }

        async function loadItemDbStatus() {
            const requestId = ++statusRequestId;
            try {
                const res = await fetch("/api/item-db/status");
                const data = await parseJsonResponse(res);
                if (requestId !== statusRequestId) return;
                if (!data?.item_db) throw new Error(data?.error || t("Item-DB-Status konnte nicht geladen werden."));
                applyItemDbStatus(data.item_db);
            } catch (err) {
                if (requestId !== statusRequestId) return;
                console.warn("Item-DB status unavailable", err);
                applyItemDbStatus({ status: "unavailable", message: err?.message || t("Item-DB-Status konnte nicht geladen werden."), counts: {} });
            }
        }

        return {
            applyItemDbStatus,
            loadItemDbStatus,
            render,
            toggleVersionHistory,
        };
    }

    function collectDataSourceElements(doc = document) {
        return {
            assetDataStatusPanel: doc.getElementById("assetDataStatusPanel"),
            itemDbStatusPanel: doc.getElementById("itemDbStatusPanel"),
        };
    }

    function createInventoryDataSourceController({ doc = document, ...deps } = {}) {
        return createDataSourceController({
            ...deps,
            elements: collectDataSourceElements(doc),
        });
    }

    window.MCBEDataSourceView = {
        assetDataStatusHtml,
        collectDataSourceElements,
        createInventoryDataSourceController,
        statusSeverityRank,
        statusSeverityClass,
        statusSeverityLabel,
        statusTile,
        formatDeNumber,
        formatItemDbTime,
        itemDbCountsText,
        itemDbQualityModel,
        itemDbQualityHtml,
        itemDbSetupFeedback,
        itemDbBlockedMessages,
        itemDbStatusRank,
        itemDbStatusValue,
        itemDbSourceText,
        itemDbStatusHtml,
        iconStateSummary,
        itemDbVersionHistoryHtml,
        createDataSourceController,
    };
}());
