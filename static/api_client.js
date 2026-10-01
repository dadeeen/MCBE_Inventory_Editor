(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function localizedErrorMessage(data, fallback = t("Unbekannter Fehler")) {
        if (!data || typeof data !== "object") return fallback;
        if (typeof data.message_key === "string" && data.message_key) {
            return t(data.message_key, data.params && typeof data.params === "object" ? data.params : undefined);
        }
        return data.message || data.error || fallback;
    }

    // Generic answers of the server's own error handlers say nothing about
    // the failed action, so the caller's context stays in front of them.
    const GENERIC_ERROR_KEYS = new Set([
        "Interner Serverfehler",
        "Seite nicht gefunden.",
        "Unbekannter Fehler",
    ]);

    // A specific backend error (message_key or message) is a complete message
    // with its own context, such as "Fehler beim Speichern des Spielers: ...".
    // An unreadable answer, a generic one or a bare "error" only carries a
    // technical reason.
    function hasBackendErrorMessage(data) {
        if (!data || typeof data !== "object") return false;
        if (data.response_unreadable === true || data.error_message_missing === true) return false;
        if (typeof data.message_key === "string" && data.message_key) {
            return !GENERIC_ERROR_KEYS.has(data.message_key);
        }
        return Boolean(String(data.message || "").trim());
    }

    function technicalErrorReason(data, fallback = t("Unbekannter Fehler")) {
        if (!data || typeof data !== "object") return fallback;
        return String(data.error || "").trim() || fallback;
    }

    // Shows a specific backend message as it is; otherwise the caller's
    // context (for example "Fehler beim Speichern: {error}") frames the reason.
    function errorMessageInContext(data, withContext, fallbackReason = t("Unbekannter Fehler")) {
        if (hasBackendErrorMessage(data)) return localizedErrorMessage(data, fallbackReason);
        return withContext(technicalErrorReason(data, fallbackReason));
    }

    function buildErrorMessage(data, fallback = "") {
        const context = String(fallback || "");
        if (!hasBackendErrorMessage(data)) {
            const reason = technicalErrorReason(data, "");
            if (!reason) return context || t("Unbekannter Fehler");
            return context && reason !== context ? t("{message} ({reason})", { message: context, reason }) : reason;
        }
        const base = localizedErrorMessage(data, context || t("Unbekannter Fehler"));
        const details = data.details && data.details !== base ? ` — ${data.details}` : "";
        return `${base}${details}`;
    }

    function unreadableResponseError(text, status) {
        const body = String(text || "").trim();
        if (!body) return t("HTTP {status}: Leere Serverantwort", { status: status || "?" });
        // An error page of a proxy or the server is no message for the user.
        if (body.startsWith("<")) return t("HTTP {status}: Serverantwort ist kein JSON", { status: status || "?" });
        return body.slice(0, 600);
    }

    function createApiClient({ csrfToken = "" } = {}) {
        function withCsrf() {
            return { "Content-Type": "application/json", "X-CSRF-Token": csrfToken };
        }

        async function parseJsonResponse(res) {
            const contentType = res.headers.get("content-type") || "";
            let text = "";
            try {
                text = await res.text();
            } catch (_e) {
                text = "";
            }

            let data = null;
            if (text && (contentType.includes("application/json") || text.trim().startsWith("{") || text.trim().startsWith("["))) {
                try {
                    data = JSON.parse(text);
                } catch (_e) {
                    data = null;
                }
            }

            if (!data || typeof data !== "object") {
                data = {
                    success: false,
                    response_unreadable: true,
                    error: unreadableResponseError(text, res.status),
                };
            }

            if (typeof data.success !== "boolean") data.response_unreadable = true;

            if (!res.ok && data.success !== true) {
                data.success = false;
                data.http_status = res.status;
                const message = localizedErrorMessage(data, "");
                if (!message) data.error_message_missing = true;
                data.error = message || t("HTTP {status}: Anfrage fehlgeschlagen", { status: res.status });
                data.message = data.error;
            }
            if (data.success === false && data.code === "backup_limit_exceeded" && window.CustomEvent) {
                window.dispatchEvent?.(new window.CustomEvent("mcbe-backup-limit"));
            }
            return data;
        }

        return {
            buildErrorMessage,
            errorMessageInContext,
            hasBackendErrorMessage,
            localizedErrorMessage,
            parseJsonResponse,
            withCsrf,
        };
    }

    window.MCBEApiClient = {
        buildErrorMessage,
        createApiClient,
        errorMessageInContext,
        hasBackendErrorMessage,
        localizedErrorMessage,
    };
}());
