(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const formatNumber = window.MCBEI18n?.formatNumber || ((value, options) => new Intl.NumberFormat("de-DE", options).format(value));
    const number = (value, decimals = 0) => formatNumber(value, {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    });
    let active = null;

    function progressView(progress = {}) {
        const phases = {
            waiting: [t("Update wird vorbereitet …"), t("Bitte dieses Fenster geöffnet lassen."), 0],
            checking: [t("Aktuelles Release wird geprüft …"), t("Die Verbindung zu Mojang/bedrock-samples wird hergestellt."), 0],
            downloading: [t("Release wird heruntergeladen"), t("Anschließend werden die Daten geprüft und verarbeitet."), 0],
            cached: [t("Vorhandener Download wird geprüft …"), t("Der passende Download liegt bereits im Cache."), 1],
            validating: [t("Download wird geprüft …"), t("Der Download ist beendet. Das Archiv wird auf Vollständigkeit geprüft."), 1],
            processing: [t("Daten werden verarbeitet …"), t("Die heruntergeladenen Daten werden für den Editor aufbereitet."), 1],
            rendering: [t("Icons werden erstellt"), t("Texturen und Modelle werden in die Icon-Sammlung übernommen."), 1],
            finalizing: [t("Update wird abgeschlossen …"), t("Die Ergebnisse werden übernommen und die Ansicht aktualisiert."), 2],
        };
        const [label, hint, step] = phases[progress.phase] || phases.waiting;
        const current = Number.isFinite(progress.current) && progress.current >= 0 ? progress.current : null;
        const total = Number.isFinite(progress.total) && progress.total > 0 ? progress.total : null;
        const measured = (progress.phase === "downloading" && progress.unit === "bytes")
            || (progress.phase === "rendering" && progress.unit === "items");
        const percent = measured && current !== null && total !== null
            ? Math.min(100, Math.floor(current * 100 / total)) : null;
        let amount = "";
        if (measured && current !== null) {
            if (progress.unit === "bytes") {
                amount = total === null
                    ? t("{current} MB geladen", { current: number(current / 1e6, 1) })
                    : t("{current} / {total} MB", { current: number(current / 1e6, 1), total: number(total / 1e6, 1) });
            } else {
                amount = total === null
                    ? t("{current} Items verarbeitet", { current: number(current) })
                    : t("{current} / {total} Items", { current: number(current), total: number(total) });
            }
        }
        return { label, hint, step, percent, amount };
    }

    function stop() {
        active?.stop();
    }

    function start(title) {
        stop();
        const overlay = document.getElementById("loadingOverlay");
        const panel = document.getElementById("assetUpdateProgress");
        if (!overlay || !panel || !window.crypto?.getRandomValues) return null;
        const id = Array.from(window.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
        const phase = document.getElementById("assetProgressPhase");
        const value = document.getElementById("assetProgressValue");
        const amount = document.getElementById("assetProgressAmount");
        const bar = document.getElementById("assetProgressBar");
        const fill = document.getElementById("assetProgressFill");
        const hint = document.getElementById("assetProgressHint");
        const steps = Array.from(panel.querySelectorAll("[data-progress-step]"));
        let timer = null;
        let requestController = null;
        let lastProgress = {};
        let missedPolls = 0;
        let polling = true;

        function render(progress, unavailable = false) {
            const view = progressView(progress);
            if (phase.textContent !== view.label) phase.textContent = view.label;
            value.textContent = view.percent === null ? "—" : `${view.percent} %`;
            amount.textContent = view.amount;
            bar.classList.toggle("is-indeterminate", view.percent === null);
            if (view.percent === null) bar.removeAttribute("aria-valuenow");
            else bar.setAttribute("aria-valuenow", String(view.percent));
            fill.style.width = view.percent === null ? "" : `${view.percent}%`;
            hint.textContent = unavailable
                ? t("Live-Fortschritt derzeit nicht verfügbar. Das Update läuft weiter.") : view.hint;
            for (const [index, step] of steps.entries()) {
                step.classList.toggle("is-current", index === view.step);
                step.classList.toggle("is-complete", index < view.step);
            }
        }

        const tracker = {
            headers: { "X-MCBE-Progress": id },
            finalizing() {
                if (active !== tracker) return;
                polling = false;
                clearTimeout(timer);
                requestController?.abort();
                render({ phase: "finalizing" });
            },
            stop() {
                if (active !== tracker) return;
                active = null;
                clearTimeout(timer);
                requestController?.abort();
                panel.hidden = true;
                overlay.classList.remove("has-asset-progress");
            },
        };
        active = tracker;
        panel.hidden = false;
        overlay.classList.add("has-asset-progress");
        document.getElementById("loadingText").textContent = title;
        render({});

        async function poll() {
            if (active !== tracker || !polling) return;
            requestController = new AbortController();
            const timeout = setTimeout(() => requestController?.abort(), 5000);
            try {
                const response = await window.fetch(`/api/update_progress/${id}`, {
                    cache: "no-store", signal: requestController.signal,
                });
                if (!response.ok) throw new Error("Progress unavailable");
                const data = await response.json();
                if (active !== tracker || !polling) return;
                if (data.progress) {
                    lastProgress = data.progress;
                    missedPolls = 0;
                } else {
                    missedPolls += 1;
                }
            } catch (_error) {
                missedPolls += 1;
            } finally {
                clearTimeout(timeout);
                if (active === tracker && polling) {
                    render(lastProgress, missedPolls >= 3);
                    timer = setTimeout(poll, 1000);
                }
            }
        }
        // Let the POST register its snapshot before the first read.
        timer = setTimeout(poll, 250);
        return tracker;
    }

    window.MCBEAssetUpdateProgress = { start, stop, progressView, isRunning: () => active !== null };
}());
