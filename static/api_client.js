(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function createApiClient({ csrfToken = "" } = {}) {
        function localizedErrorMessage(data, fallback = t("Unbekannter Fehler")) {
            if (!data || typeof data !== "object") return fallback;
            if (typeof data.message_key === "string" && data.message_key) {
                return t(data.message_key, data.params && typeof data.params === "object" ? data.params : undefined);
            }
            return data.message || data.error || fallback;
        }

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
                    error: text.trim() ? text.trim().slice(0, 600) : t("HTTP {status}: Leere Serverantwort", { status: res.status || "?" }),
                };
            }

            if (!res.ok && data.success !== true) {
                data.success = false;
                data.http_status = res.status;
                const fallback = t("HTTP {status}: Anfrage fehlgeschlagen", { status: res.status });
                data.error = localizedErrorMessage(data, fallback);
                data.message = data.error;
            }
            return data;
        }

        function buildErrorMessage(data, fallback = t("Unbekannter Fehler")) {
            if (!data || typeof data !== "object") return fallback;
            const base = localizedErrorMessage(data, fallback);
            const details = data.details && data.details !== base ? ` — ${data.details}` : "";
            return `${base}${details}`;
        }

        return {
            buildErrorMessage,
            localizedErrorMessage,
            parseJsonResponse,
            withCsrf,
        };
    }

    window.MCBEApiClient = {
        createApiClient,
    };
}());
