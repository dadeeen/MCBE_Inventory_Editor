(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function createPlayerApiClient({
        fetchFn = fetch,
        withCsrf = () => ({}),
        parseJsonResponse = async response => response.json(),
        buildErrorMessage = (data, fallback = t("Fehler")) => data?.error || fallback,
    } = {}) {
        async function postJson(url, body) {
            const response = await fetchFn(url, {
                method: "POST",
                headers: withCsrf(),
                body: JSON.stringify(body),
            });
            return parseJsonResponse(response);
        }

        function listPlayers(worldPath) {
            return postJson("/api/players", { world_path: worldPath });
        }

        function loadPlayer(worldPath, playerKey) {
            return postJson("/api/player/load", {
                world_path: worldPath,
                player_key: playerKey,
            });
        }

        async function loadPlayerOrThrow(worldPath, playerKey, fallbackMessage = t("Spieler konnte nicht geladen werden.")) {
            const data = await loadPlayer(worldPath, playerKey);
            if (!data.success) throw new Error(buildErrorMessage(data, fallbackMessage));
            return data;
        }

        function previewStateTransfer(worldPath, sourcePlayerKey, targetPlayerKey) {
            return postJson("/api/player/state_transfer_preview", {
                world_path: worldPath,
                source_player_key: sourcePlayerKey,
                target_player_key: targetPlayerKey,
            });
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
