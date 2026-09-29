(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function worldPresenceModel(data, { worldPath = "", playerLabel = "" } = {}) {
        const otherSessions = Number(data?.other_sessions || 0);
        if (!worldPath || otherSessions <= 0) {
            return {
                visible: false,
                className: "presence-warning",
                text: "",
                alertKey: "",
            };
        }

        const samePlayer = Number(data.same_player_sessions || 0);
        const dirty = Number(data.other_dirty_sessions || 0);
        const samePlayerDirty = Number(data.same_player_dirty_sessions || 0);
        const noun = otherSessions === 1 ? t("Browser-Sitzung") : t("Browser-Sitzungen");
        const details = [];
        if (samePlayer > 0) details.push(t("{count} davon mit demselben Spieler", { count: samePlayer }));
        if (dirty > 0) details.push(t("{count} mit ungespeicherten Änderungen", { count: dirty }));

        let text = t("⚠️ Diese Welt ist aktuell in {count} weiterer {noun} geöffnet.", { count: otherSessions, noun });
        if (details.length) text += ` ${details.join(", ")}.`;
        text += " " + t("Bitte sprecht euch vor dem Speichern/Restore ab; veraltete Saves werden zusätzlich blockiert.");
        if (samePlayerDirty > 0) {
            text = t("🚧 Achtung: Eine andere Sitzung bearbeitet vermutlich denselben Spieler ({player}) und hat ungespeicherte Änderungen.", { player: playerLabel }) + " " + text;
        }

        return {
            visible: true,
            className: samePlayer > 0 ? "presence-warning strong" : "presence-warning",
            text,
            alertKey: `${otherSessions}:${samePlayer}:${dirty}:${samePlayerDirty}`,
        };
    }

    function presenceConflictText(data) {
        const conflict = data?.presence_conflict || {};
        const count = Number(conflict.dirty_relevant_sessions || 0);
        const noun = count === 1 ? t("andere Sitzung") : t("andere Sitzungen");
        const details = (conflict.sessions || [])
            .slice(0, 3)
            .map(s => `• ${t("{player}, seit {seconds}s nicht aktualisiert", { player: s.player_label || t("Spieler"), seconds: s.idle_seconds || 0 })}`)
            .join("\n");
        return `${data.error || t("Es gibt einen Bearbeitungskonflikt.")}\n\n${t("{count} {noun} mit ungespeicherten Änderungen wurde erkannt.", { count: count || t("Mindestens eine"), noun })}${details ? "\n" + details : ""}\n\n${t("Trotzdem fortfahren?")}`;
    }

    function applyWorldPresenceModel(element, model = {}) {
        if (!element) return;
        element.className = model.className || "presence-warning";
        element.textContent = model.visible ? (model.text || "") : "";
        element.style.display = model.visible ? "block" : "none";
    }

    // Watches the loaded player for changes made outside this page, e.g. in
    // Minecraft. The poll reports the world's fingerprint; once it differs
    // from loading and stayed the same over one poll, the server reads the
    // player's stored revision, and only a different revision counts.
    function playerWatchKey({ worldPath = "", playerKey = "", loadedFingerprint = "", revision = "" } = {}) {
        return worldPath && playerKey && loadedFingerprint && revision
            ? [worldPath, playerKey, loadedFingerprint, revision].join("\n")
            : "";
    }

    function nextPlayerWatch(watch, context = {}, { data = null, requestKey = "", busy = false } = {}) {
        const key = playerWatchKey(context);
        // Another world, player or revision (after loading or saving) starts over.
        const next = watch && watch.key === key
            ? { ...watch }
            : { key, baseline: key ? context.loadedFingerprint : "", seen: "", changed: false };
        // A response to an older state, or one arriving while this page saves
        // or loads, may describe a revision the page has not received yet.
        if (!key || !data || requestKey !== key || busy) return next;
        const fingerprint = typeof data.world_fingerprint === "string" ? data.world_fingerprint : "";
        if (!fingerprint) return next;
        if (typeof data.player_revision === "string") {
            next.changed = data.player_revision !== context.revision;
            next.baseline = fingerprint;
            next.seen = "";
            return next;
        }
        next.seen = fingerprint === next.baseline ? "" : fingerprint;
        return next;
    }

    function playerWatchRequest(watch) {
        return watch?.key ? { fingerprint_baseline: watch.baseline, fingerprint_seen: watch.seen } : {};
    }

    window.MCBEPresenceView = {
        applyWorldPresenceModel,
        nextPlayerWatch,
        playerWatchRequest,
        worldPresenceModel,
        presenceConflictText,
    };
}());

(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const view = window.MCBEPresenceView || {};

    function createWorldPresenceController({
        win = window,
        sessionKey,
        intervalMs = 10000,
        elements = {},
        withCsrf,
        parseJsonResponse,
        getWorldPath,
        getCurrentPlayerKey,
        getCurrentPlayerLabel,
        getCurrentPlayerRevision,
        getLoadedWorldFingerprint,
        getIsDirty,
        getIsBusy,
        reloadPlayer,
        logStatus,
        showToast,
        showConfirmDialog,
    } = {}) {
        let timer = null;
        let lastAlertKey = "";
        let cachedSessionId = "";
        let leaveSent = false;
        let playerWatch = null;

        function sessionId() {
            try {
                let id = win.sessionStorage.getItem(sessionKey);
                if (!id) {
                    const randomPart = (win.crypto && win.crypto.getRandomValues)
                        ? Array.from(win.crypto.getRandomValues(new Uint32Array(4))).map(n => n.toString(36)).join("")
                        : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
                    id = `web-${randomPart}`;
                    win.sessionStorage.setItem(sessionKey, id);
                }
                return id;
            } catch (_e) {
                if (!cachedSessionId) {
                    cachedSessionId = `web-${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
                }
                return cachedSessionId;
            }
        }

        function render(data) {
            const banner = elements.banner;
            if (!banner) return;
            const model = view.worldPresenceModel(data, {
                worldPath: getWorldPath?.() || "",
                playerLabel: getCurrentPlayerLabel?.() || t("Spieler"),
            });
            view.applyWorldPresenceModel(banner, model);
            if (!model.visible) {
                lastAlertKey = model.alertKey;
                return;
            }
            if (model.alertKey !== lastAlertKey) {
                lastAlertKey = model.alertKey;
                showToast?.(model.text, "warning", 7000);
            }
        }

        function playerWatchContext() {
            return {
                worldPath: getWorldPath?.() || "",
                playerKey: getCurrentPlayerKey?.() || "",
                loadedFingerprint: getLoadedWorldFingerprint?.() || "",
                revision: getCurrentPlayerRevision?.() || "",
            };
        }

        function renderPlayerChanged() {
            const banner = elements.playerChangedBanner;
            const changed = playerWatch?.changed === true;
            if (banner) {
                const wasVisible = banner.style.display !== "none";
                banner.style.display = changed ? "flex" : "none";
                if (changed && !wasVisible) {
                    showToast?.(t("Dieser Spieler wurde seit dem Laden verändert, z. B. in Minecraft. Speichern würde abgelehnt."), "warning", 7000);
                }
            }
        }

        async function reloadChangedPlayer() {
            if (getIsDirty?.() === true) {
                const ok = await showConfirmDialog?.(t("Deine ungespeicherten Änderungen gehen beim Neuladen verloren. Spieler trotzdem neu laden?"));
                if (!ok) return false;
            }
            return reloadPlayer?.();
        }

        function wirePlayerChangedBanner() {
            elements.playerChangedButton?.addEventListener("click", () => { reloadChangedPlayer(); });
        }

        async function update({ silent = true } = {}) {
            playerWatch = view.nextPlayerWatch(playerWatch, playerWatchContext());
            renderPlayerChanged();
            const worldPath = getWorldPath?.() || "";
            if (!worldPath) {
                render(null);
                return null;
            }
            const requestKey = playerWatch.key;
            const watchFields = getIsBusy?.() === true ? {} : view.playerWatchRequest(playerWatch);
            try {
                const res = await fetch("/api/world/presence", {
                    method: "POST",
                    headers: withCsrf?.(),
                    body: JSON.stringify({
                        session_id: sessionId(),
                        world_path: worldPath,
                        player_key: getCurrentPlayerKey?.() || "",
                        player_label: getCurrentPlayerLabel?.() || t("Spieler"),
                        dirty: getIsDirty?.() === true,
                        ...watchFields,
                    }),
                });
                const data = await parseJsonResponse(res);
                if (data.success) {
                    leaveSent = false;
                    render(data);
                    playerWatch = view.nextPlayerWatch(playerWatch, playerWatchContext(), {
                        data,
                        requestKey: Object.keys(watchFields).length ? requestKey : "",
                        busy: getIsBusy?.() === true,
                    });
                    renderPlayerChanged();
                    return data;
                }
                if (!silent) logStatus?.(t("Präsenz-Hinweis konnte nicht aktualisiert werden: {error}", { error: data.error }), "warning");
            } catch (e) {
                if (!silent) console.warn("updateWorldPresence:", e);
            }
            return null;
        }

        async function confirmConflict(data) {
            return showConfirmDialog?.(view.presenceConflictText(data));
        }

        function scheduleUpdate(delayMs = 600) {
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => update(), delayMs);
        }

        function leave() {
            if (leaveSent) return;
            leaveSent = true;
            try {
                fetch("/api/world/presence/leave", {
                    method: "POST",
                    headers: withCsrf?.(),
                    body: JSON.stringify({ session_id: sessionId() }),
                    keepalive: true,
                });
            } catch (_e) {}
        }

        function wireBeforeUnload() {
            // beforeunload can be canceled by the unsaved-changes prompt, which
            // would create a false disconnect.  pagehide only fires when the page
            // is actually being hidden/unloaded; TTL cleanup remains the fallback
            // for browsers that suppress the keepalive request.
            win.addEventListener("pagehide", leave);
        }

        function startPolling() {
            return win.setInterval(() => update(), intervalMs);
        }

        return {
            confirmConflict,
            leave,
            reloadChangedPlayer,
            render,
            scheduleUpdate,
            sessionId,
            startPolling,
            update,
            wireBeforeUnload,
            wirePlayerChangedBanner,
        };
    }


    function createConfiguredWorldPresenceController({
        win = window,
        doc = document,
        sessionKey,
        intervalMs = 10000,
        api = {},
        state = {},
        helpers = {},
    } = {}) {
        return createWorldPresenceController({
            win,
            sessionKey,
            intervalMs,
            elements: {
                banner: doc.getElementById("worldPresenceBanner"),
                playerChangedBanner: doc.getElementById("playerChangedBanner"),
                playerChangedButton: doc.getElementById("btnReloadChangedPlayer"),
            },
            withCsrf: api.withCsrf,
            parseJsonResponse: api.parseJsonResponse,
            getWorldPath: state.getWorldPath,
            getCurrentPlayerKey: state.getCurrentPlayerKey,
            getCurrentPlayerLabel: state.getCurrentPlayerLabel,
            getCurrentPlayerRevision: state.getCurrentPlayerRevision,
            getLoadedWorldFingerprint: state.getLoadedWorldFingerprint,
            getIsDirty: state.getIsDirty,
            getIsBusy: state.getIsBusy,
            reloadPlayer: helpers.reloadPlayer,
            logStatus: helpers.logStatus,
            showToast: helpers.showToast,
            showConfirmDialog: helpers.showConfirmDialog,
        });
    }

    window.MCBEPresenceView = {
        ...view,
        createWorldPresenceController,
        createConfiguredWorldPresenceController,
    };
}());
