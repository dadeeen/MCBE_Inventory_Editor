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

    function itemDbStatusRank(status = null) {
        if (!status) return 1;
        return status.status === "ok" && status.verification?.verified === true ? 0 : 1;
    }

    function itemDbStatusValue(status = null) {
        if (!status) return t("lädt");
        if (status.status === "unavailable") return t("Status nicht verfügbar");
        if (status.status !== "ok") return t("Herkunft fehlt");
        return status.verification?.verified === true ? t("geprüft") : t("Prüfung offen");
    }

    function itemDbSourceText(status = null) {
        if (!status) return t("Status wird geladen");
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
            return { rank: 1, value: t("Status nicht verfügbar"), detail: t("Icon-Status konnte nicht geladen werden.") };
        }
        const health = summary?.health || {};
        const count = Number(summary?.count || 0);
        const warnings = Array.isArray(summary?.warnings) ? summary.warnings.length : 0;
        const sourceCount = Number(health.enabled_sources || (summary?.sources || []).filter(src => src.enabled !== false).length || 0);
        const existingSources = Number(health.existing_sources || (summary?.sources || []).filter(src => src.enabled !== false && src.exists).length || 0);
        const scanned = Number(summary?.scanned_files || 0);
        if (count > 0) {
            return {
                rank: warnings ? 1 : 0,
                value: warnings ? t("Hinweise") : t("bereit"),
                detail: t("{count} lokale Icons · {files} Dateien geprüft", { count: formatDeNumber(count), files: formatDeNumber(scanned) }),
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
                        <th>${t("Datum")}</th>
                        <th>Resource Pack</th>
                    </tr>
                </thead>
                <tbody>
                    ${entries.map(entry => `
                    <tr>
                        <td>${versionEntryCell(entry, "generated_at")}</td>
                        <td>${versionEntryCell(entry, "resource_pack_release")}</td>
                    </tr>`).join("")}
                </tbody>
            </table>
        `;
        } else {
            body = `<div class="no-backups">${t("Noch keine Versionseinträge vorhanden. Führe ein DB-Update aus.")}</div>`;
        }
        return `<div class="item-db-version-history"${hidden}>${body}</div>`;
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
        return `
            <div class="data-source-header">
                <div>
                    <strong>${t("Datenquellenstatus")}</strong>
                    <small>${t("Item-Datenbank, lokale Icons und Welt-Kompatibilität werden hier zusammengeführt.")}</small>
                </div>
                <button class="btn-text" type="button" data-open-db-status>${t("Item-DB öffnen")}</button>
            </div>
            <div class="status-tile-grid data-source-grid">
                ${statusTile(t("Item-DB"), itemDbStatusValue(itemDbStatus), `${itemDbCountsText(itemDbStatus)} · ${itemDbSourceText(itemDbStatus)}`, dbRank)}
                ${statusTile(t("Icons"), iconState.value, iconState.detail, iconState.rank)}
                ${statusTile(t("Unbekannte Items"), unknownValue, unknownDetail, unknownItems ? 1 : 0)}
            </div>
        `;
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
                    <span>${t("Aktive Item-Datenbank")}</span>
                    <strong>${escapeHtml(itemDbStatusValue(itemDbStatus))}</strong>
                    <small>${escapeHtml(sourceLine)}</small>
                </div>
                <button class="btn btn-secondary btn-sm" type="button" data-toggle-db-versions aria-expanded="${historyVisible ? "true" : "false"}">${historyVisible ? t("Versionen ausblenden") : t("Versionen ansehen")}</button>
            </div>
            <div class="status-tile-grid data-source-grid">
                ${statusTile(t("Einträge"), t("geladen"), itemDbCountsText(itemDbStatus), 0)}
                ${statusTile(t("Schema"), `v${itemDbStatus?.schema_version || "?"}`, historyText, dbRank)}
                ${statusTile(t("Pfad"), itemDbStatus?.is_configured_persistent ? t("Datenordner") : t("gebündelt"), pathText, 0)}
            </div>
            ${itemDbVersionHistoryHtml({
                visible: historyVisible,
                loading: historyLoading,
                error: historyError,
                entries: historyEntries,
            })}
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
                assetDataStatusPanel.querySelector("[data-open-db-status]")?.addEventListener("click", openItemDbStatus);
            }

            if (itemDbStatusPanel) {
                itemDbStatusPanel.innerHTML = itemDbStatusHtml({
                    itemDbStatus,
                    appItemDbPath: appConfig?.item_db_path,
                    historyVisible,
                    historyLoading,
                    historyError,
                    historyEntries,
                });
                itemDbStatusPanel.querySelector("[data-toggle-db-versions]")?.addEventListener("click", toggleVersionHistory);
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
            render();
            try {
                const res = await fetch("/api/item-db/versions");
                const data = await parseJsonResponse(res);
                if (!data.success) throw new Error(data.error || t("Unbekannter Fehler"));
                historyEntries = Array.isArray(data.entries) ? data.entries : [];
            } catch (err) {
                historyEntries = [];
                historyError = err.message || String(err);
                logStatus(t("Versionshistorie konnte nicht geladen werden."), "warning");
            } finally {
                historyLoading = false;
                render();
            }
        }

        function applyItemDbStatus(status) {
            const normalizedStatus = status || null;
            setItemDbStatus(normalizedStatus);
            render();
            renderStatusCenter();
            onItemDbStatusApplied(normalizedStatus);
            return normalizedStatus;
        }

        async function loadItemDbStatus() {
            try {
                const res = await fetch("/api/item-db/status");
                const data = await parseJsonResponse(res);
                if (!data?.item_db) throw new Error(t("Item-DB-Status konnte nicht geladen werden."));
                applyItemDbStatus(data.item_db);
            } catch (err) {
                console.warn("Item-DB status unavailable", err);
                applyItemDbStatus({ status: "unavailable", message: t("Item-DB-Status konnte nicht geladen werden."), counts: {} });
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
        itemDbStatusRank,
        itemDbStatusValue,
        itemDbSourceText,
        itemDbStatusHtml,
        iconStateSummary,
        itemDbVersionHistoryHtml,
        createDataSourceController,
    };
}());
