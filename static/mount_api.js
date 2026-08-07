(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function createMountApiClient({
        fetchFn = fetch,
        withCsrf = () => ({}),
        parseJsonResponse = async response => response.json(),
        buildErrorMessage = (data, fallback = t("Fehler")) => data?.error || fallback,
    } = {}) {
        function errorFromResponse(data, fallbackMessage, properties = {}) {
            const error = new Error(buildErrorMessage(data, fallbackMessage));
            error.data = data;
            error.writeCommitted = data?.write_committed === true;
            error.validationFailed = data?.validation_failed === true;
            error.errorPhase = data?.error_phase || null;
            Object.assign(error, properties);
            return error;
        }

        async function postJson(url, body) {
            const response = await fetchFn(url, {
                method: "POST",
                headers: withCsrf(),
                body: JSON.stringify(body),
            });
            return parseJsonResponse(response);
        }

        function previewMount({ worldPath, playerKey, preferredOffset = null, placementRadius = 6, mountType = "minecraft:horse" } = {}) {
            const payload = {
                world_path: worldPath,
                player_key: playerKey,
                mount_type: mountType,
                placement_radius: placementRadius,
            };
            if (preferredOffset) payload.preferred_offset = preferredOffset;
            return postJson("/api/mount/preview", payload);
        }

        async function previewMountOrThrow(options = {}, fallbackMessage = t("Mount-Vorschau konnte nicht geladen werden.")) {
            const data = await previewMount(options);
            if (!data.success) throw new Error(buildErrorMessage(data, fallbackMessage));
            return data;
        }

        function createMount({ worldPath, playerKey, mountType = "minecraft:horse", createMode = "synthetic_full", serverGuardEpoch = null, serverGuardToken = "", preferredOffset = null, placementRadius = 6, horseProfile = null, mountStats = null, tamed = false, allowUncheckedPlacement = false, confirmUnknownServerStatus = false } = {}) {
            const payload = {
                world_path: worldPath,
                player_key: playerKey,
                mount_type: mountType,
                create_mode: createMode,
                placement_radius: placementRadius,
                allow_unchecked_placement: allowUncheckedPlacement === true,
            };
            if (Number.isInteger(serverGuardEpoch)) payload.server_guard_epoch = serverGuardEpoch;
            if (typeof serverGuardToken === "string" && serverGuardToken) payload.server_guard_token = serverGuardToken;
            if (preferredOffset) payload.preferred_offset = preferredOffset;
            if (horseProfile) payload.horse_profile = horseProfile;
            if (mountStats) payload.mount_stats = mountStats;
            if (tamed === true) payload.tamed = true;
            if (confirmUnknownServerStatus === true) payload.confirm_unknown_server_status = true;
            return postJson("/api/mount/create", payload);
        }

        async function createMountOrThrow(options = {}, fallbackMessage = t("Mount konnte nicht erzeugt werden.")) {
            let data = await createMount(options);
            // Gleiche Schleife wie beim Spieler-Speichern: Bei unbekanntem
            // Serverstatus einmal explizit bestätigen lassen und dann mit
            // confirm_unknown_server_status erneut schreiben.
            if (
                !data.success &&
                data.write_gate?.requires_unknown_server_confirmation === true &&
                options.confirmUnknownServerStatus !== true &&
                typeof options.onUnknownServerStatus === "function"
            ) {
                const confirmed = await options.onUnknownServerStatus(data.write_gate);
                if (confirmed !== true) {
                    throw errorFromResponse(data, fallbackMessage, { unknownServerDeclined: true });
                }
                data = await createMount({ ...options, confirmUnknownServerStatus: true });
            }
            if (!data.success) throw errorFromResponse(data, fallbackMessage);
            return data;
        }

        return {
            previewMount,
            previewMountOrThrow,
            createMount,
            createMountOrThrow,
        };
    }

    window.MCBEMountApi = {
        createMountApiClient,
    };
}());
