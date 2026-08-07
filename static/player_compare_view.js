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

    function comparisonCard(label, summary = {}) {
        return `<div class="compare-card"><h4>${escapeHtml(label)}</h4><p>${t("Inventar")}: ${escapeHtml(summary.inv)}</p><p>${t("Enderchest")}: ${escapeHtml(summary.ec)}</p><p>${t("Beschädigt")}: ${escapeHtml(summary.damaged)}</p><p>XP: ${escapeHtml(summary.xp)}</p><p>${t("Leben/Hunger")}: ${escapeHtml(summary.health)} / ${escapeHtml(summary.food)}</p></div>`;
    }

    function comparisonHtml({ currentLabel = "", current = {}, otherLabel = "", other = {} } = {}) {
        return `
        <div class="compare-grid">
            ${comparisonCard(currentLabel, current)}
            ${comparisonCard(otherLabel, other)}
        </div>
    `;
    }

    function comparisonLoadingHtml() {
        return `<div class="no-backups">${t("Vergleich wird geladen...")}</div>`;
    }

    function comparisonErrorHtml(message = t("Vergleich fehlgeschlagen.")) {
        return `<div class="no-backups error">${escapeHtml(message || t("Vergleich fehlgeschlagen."))}</div>`;
    }

    window.MCBEPlayerCompareView = {
        comparisonErrorHtml,
        comparisonHtml,
        comparisonLoadingHtml,
    };
}());
