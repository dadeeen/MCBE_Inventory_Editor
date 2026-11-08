(function () {
    "use strict";

    function createVillagerApiClient({ fetchFn = fetch, withCsrf = () => ({}), parseJsonResponse = response => response.json(),
        buildErrorMessage = data => data?.error || "", ...options } = {}) {
        const reads = window.MCBEPlayerApi.createPlayerApiClient({ fetchFn, withCsrf, parseJsonResponse, buildErrorMessage, ...options });
        // A mutation has no automatic retry and is never cancelled at transport
        // level: a lost response does not imply that the write was rolled back.
        const post = async (url, body) => parseJsonResponse(await fetchFn(url, {
            method: "POST", headers: withCsrf(), body: JSON.stringify(body),
        }));
        return {
            scan: (worldPath, scanOptions) => reads.readWorld("/api/villagers/scan", { world_path: worldPath }, scanOptions),
            detail: (payload, readOptions) => reads.readWorld("/api/villagers/detail", payload, readOptions),
            mapPlayers: (payload, readOptions) => reads.readWorld("/api/villagers/map_players", payload, readOptions),
            preview: (payload, readOptions) => reads.readWorld("/api/villagers/preview", payload, readOptions),
            save: payload => post("/api/villagers/save", payload),
            savePreferences: payload => post("/api/villagers/preferences", payload),
        };
    }

    window.MCBEVillagerApi = { createVillagerApiClient };
}());
