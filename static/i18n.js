(function () {
    "use strict";

    const LOCALE_COOKIE_NAME = "mcbe_locale";
    const SUPPORTED_LOCALES = ["de", "en"];

    function readCatalog(doc) {
        const holder = doc.getElementById("i18nCatalog");
        if (!holder || !holder.textContent) return {};
        try {
            const parsed = JSON.parse(holder.textContent);
            return parsed && typeof parsed === "object" ? parsed : {};
        } catch (err) {
            return {};
        }
    }

    const doc = typeof document === "undefined" ? null : document;
    const locale = doc && SUPPORTED_LOCALES.includes(doc.documentElement.lang) ? doc.documentElement.lang : "de";
    const localeTag = locale === "en" ? "en-US" : "de-DE";
    const catalog = doc ? readCatalog(doc) : {};
    const baseCollator = typeof Intl !== "undefined" && Intl.Collator
        ? new Intl.Collator(localeTag, { sensitivity: "base" })
        : null;

    function substitute(text, params) {
        if (!params) return text;
        return String(text).replace(/\{(\w+)\}/g, (match, key) => (key in params ? String(params[key]) : match));
    }

    function t(text, params) {
        const source = String(text);
        const translated = Object.prototype.hasOwnProperty.call(catalog, source) ? catalog[source] : source;
        return substitute(translated, params);
    }

    function isEnglish() {
        return locale === "en";
    }

    function localizedPair(de, en) {
        const primary = isEnglish() ? en || "" : de || en || "";
        const secondaryCandidate = isEnglish() ? "" : en || "";
        return {
            primary: String(primary),
            secondary: secondaryCandidate && secondaryCandidate !== primary ? String(secondaryCandidate) : "",
        };
    }

    function compare(left, right) {
        const a = String(left ?? "");
        const b = String(right ?? "");
        return baseCollator ? baseCollator.compare(a, b) : a.localeCompare(b);
    }

    function formatNumber(value, options) {
        const number = Number(value);
        if (!Number.isFinite(number)) return String(value ?? "");
        return new Intl.NumberFormat(localeTag, options).format(number);
    }

    function formatDate(value, options) {
        const date = value instanceof Date ? value : new Date(value);
        if (Number.isNaN(date.getTime())) return String(value ?? "");
        return new Intl.DateTimeFormat(localeTag, options || { dateStyle: "short", timeStyle: "medium" }).format(date);
    }

    function tp(count, singular, plural, params = {}) {
        const number = Number(count);
        const key = new Intl.PluralRules(localeTag).select(number) === "one" ? singular : plural;
        return t(key, { ...params, count });
    }

    function setLocale(nextLocale) {
        if (!doc || !SUPPORTED_LOCALES.includes(nextLocale) || nextLocale === locale) return;
        doc.cookie = LOCALE_COOKIE_NAME + "=" + nextLocale + "; path=/; max-age=31536000; samesite=lax";
        window.location.reload();
    }

    function initLanguageSwitcher() {
        if (!doc) return;
        const select = doc.getElementById("languageSelect");
        if (!select) return;
        select.value = locale;
        select.addEventListener("change", () => setLocale(select.value));
    }

    function onReady() {
        initLanguageSwitcher();
    }

    if (doc) {
        if (doc.readyState === "loading") {
            doc.addEventListener("DOMContentLoaded", onReady);
        } else {
            onReady();
        }
    }

    window.MCBEI18n = {
        locale,
        localeTag,
        t,
        isEnglish,
        localizedPair,
        compare,
        formatNumber,
        formatDate,
        tp,
        setLocale,
        initLanguageSwitcher,
    };
    window.t = t;
}());
