(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function createPlayerApiClient({
        fetchFn = fetch,
        withCsrf = () => ({}),
        parseJsonResponse = async response => response.json(),
        buildErrorMessage = (data, fallback = t("Fehler")) => data?.error || fallback,
        readTimeoutMs = 15000,
        operationTimeoutMs = 310000,
        createReadId = () => window.crypto?.getRandomValues
            ? Array.from(window.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("") : null,
    } = {}) {
        const unfinished = new Map();
        async function postJson(url, body) {
            const response = await fetchFn(url, {
                method: "POST",
                headers: withCsrf(),
                body: JSON.stringify(body),
            });
            return parseJsonResponse(response);
        }

        function read(url, body, options = {}, headers = {}) {
            return window.MCBEApiClient.readJson(url, {
                method: "POST",
                headers: { ...withCsrf(), ...headers },
                body: JSON.stringify(body),
            }, { fetchFn, parseJsonResponse, timeoutMs: readTimeoutMs, signal: options.signal });
        }

        function waitForPoll(milliseconds, signal) {
            return new Promise((resolve, reject) => {
                const cancel = () => {
                    clearTimeout(timer);
                    signal?.removeEventListener("abort", cancel);
                    const error = new Error(t("Leseanfrage abgebrochen."));
                    error.name = "AbortError";
                    reject(error);
                };
                const timer = setTimeout(() => {
                    signal?.removeEventListener("abort", cancel);
                    resolve();
                }, milliseconds);
                signal?.addEventListener("abort", cancel, { once: true });
                if (signal?.aborted) cancel();
            });
        }

        async function readWorld(url, body, options = {}) {
            if (options.signal?.aborted) return read(url, body, options);
            const key = JSON.stringify([url, body]);
            for (const [oldKey, entry] of unfinished) {
                if (Date.now() - entry.started > operationTimeoutMs) unfinished.delete(oldKey);
            }
            const previous = unfinished.get(key);
            const id = previous?.id || createReadId();
            // Legacy clients without Web Crypto retain the synchronous API.
            if (!id) return read(url, body, options);
            // Response ordering belongs to the logical read, including retries
            // of a completed response that was lost on its way to the browser.
            const entry = previous || { id, started: Date.now(), context: options.operationContext };
            unfinished.set(key, entry);
            if (unfinished.size > 16) unfinished.delete(unfinished.keys().next().value);
            const cancel = () => {
                unfinished.delete(key);
                // Separate transport: the caller's signal is already aborted.
                window.MCBEApiClient.readJson(`/api/world_reads/${id}`, {
                    method: "DELETE", headers: withCsrf(),
                }, { fetchFn, parseJsonResponse, timeoutMs: readTimeoutMs }).catch(() => {});
            };
            options.signal?.addEventListener("abort", cancel, { once: true });
            try {
                options.onOperation?.(entry.context);
                let data = await read(url, body, options, { "X-MCBE-Read-ID": id });
                let firstPoll = true;
                while (data.pending === true && data.success === true) {
                    if (data.read_id !== id) throw new Error(t("Die Ladeantwort gehört zu einer anderen Anfrage."));
                    options.onProgress?.(data.progress || {});
                    if (Date.now() - entry.started >= operationTimeoutMs) {
                        cancel();
                        const error = new Error(t("Das Laden der Welt hat zu lange gedauert. Der Lesevorgang wurde beendet."));
                        error.name = "TimeoutError";
                        error.code = "read_timeout";
                        throw error;
                    }
                    await waitForPoll(firstPoll ? 200 : 1000, options.signal);
                    firstPoll = false;
                    data = await window.MCBEApiClient.readJson(`/api/world_reads/${id}`, {
                        headers: withCsrf(),
                    }, { fetchFn, parseJsonResponse, timeoutMs: readTimeoutMs, signal: options.signal });
                }
                if ([408, 504].includes(data.http_status) && !data.code) {
                    const error = new Error(t("HTTP {status}: Die Anfrage hat das Zeitlimit überschritten.", { status: data.http_status }));
                    error.name = "TimeoutError";
                    throw error;
                }
                if (data.response_unreadable) throw new Error(buildErrorMessage(data, t("Die Ladeantwort konnte nicht gelesen werden.")));
                unfinished.delete(key);
                return data;
            } finally {
                options.signal?.removeEventListener("abort", cancel);
            }
        }

        function listPlayers(worldPath, options = {}) {
            return readWorld("/api/players", { world_path: worldPath }, options);
        }

        function loadPlayer(worldPath, playerKey, options = {}) {
            return readWorld("/api/player/load", {
                world_path: worldPath,
                player_key: playerKey,
            }, options);
        }

        async function loadPlayerOrThrow(worldPath, playerKey, fallbackMessage = t("Spieler konnte nicht geladen werden."), options = {}) {
            const data = await loadPlayer(worldPath, playerKey, options);
            if (!data.success) throw new Error(buildErrorMessage(data, fallbackMessage));
            return data;
        }

        function previewStateTransfer(worldPath, sourcePlayerKey, targetPlayerKey, options = {}) {
            return read("/api/player/state_transfer_preview", {
                world_path: worldPath,
                source_player_key: sourcePlayerKey,
                target_player_key: targetPlayerKey,
            }, options);
        }

        function applyStateTransfer({
            worldPath,
            sourcePlayerKey,
            targetPlayerKey,
            transferToken,
            serverGuardEpoch,
            serverGuardToken = "",
            sessionId = "",
            confirmPresenceConflict = false,
        }) {
            const body = {
                world_path: worldPath,
                source_player_key: sourcePlayerKey,
                target_player_key: targetPlayerKey,
                transfer_token: transferToken,
                confirm_transfer: true,
                server_guard_epoch: serverGuardEpoch,
                server_guard_token: serverGuardToken,
                session_id: sessionId,
            };
            if (confirmPresenceConflict) body.confirm_presence_conflict = true;
            return postJson("/api/player/state_transfer", body);
        }

        return {
            applyStateTransfer,
            listPlayers,
            loadPlayer,
            loadPlayerOrThrow,
            previewStateTransfer,
        };
    }

    window.MCBEPlayerApi = {
        createPlayerApiClient,
    };
}());
