(function () {
    "use strict";

    // Layout changes only the presentation layer. World/player are the editing
    // context, inventory/player data/mounts are independent destinations, and
    // saving is an action rather than the last stage of a wizard.
    const DEFAULT_LAYOUT = "classic";
    const ALLOWED_LAYOUTS = Object.freeze(["classic", "studio", "focus"]);
    // Keep these aligned with the single-column inspector breakpoints in
    // layout_variants.css (Studio) and focus_workspace.css (Focus).
    const STACKED_INSPECTOR_MAX_WIDTH = Object.freeze({ studio: 1180, focus: 1279 });
    const VIEW_INFO = Object.freeze({
        world: {
            title: "Welt auswählen",
            description: "Die Welt legt den Datenkontext fest. Du kannst sie jederzeit wechseln.",
        },
        player: {
            title: "Spieler auswählen",
            description: "Wähle oder wechsle den aktiven Spieler. Danach stehen die Editoren unabhängig voneinander bereit.",
        },
        inventory: {
            title: "Inventar bearbeiten",
            description: "Bearbeite Items, Ausrüstung und Enderchest des gewählten Spielers.",
        },
        "player-edit": {
            title: "Spielerdaten bearbeiten",
            description: "Bearbeite Eigenschaften, Fähigkeiten, Effekte und Spielerfunktionen unabhängig vom Inventar.",
        },
        mounts: {
            title: "Mounts (experimentell)",
            description: "Optionaler Bereich: Mounts erstellen und prüfen. Nicht nötig für andere Änderungen.",
        },
        save: {
            title: "Änderungen prüfen & speichern",
            description: "Prüfe vorgemerkte Änderungen und speichere mit vorherigem Backup.",
        },
        tools: {
            title: "Werkzeuge & Diagnose",
            description: "Nutze Backups, Icon-Verwaltung und Diagnosen unabhängig von der Bearbeitung.",
        },
    });

    function normalizeLayout(value) {
        return ALLOWED_LAYOUTS.includes(value) ? value : DEFAULT_LAYOUT;
    }

    function readStoredLayout(storage, key) {
        try {
            return normalizeLayout(storage?.getItem(key));
        } catch (_error) {
            return DEFAULT_LAYOUT;
        }
    }

    function editingContextModel({ worldLoaded = false, playerLoaded = false, isDirty = false,
        worldLabel = "", playerLabel = "" } = {}) {
        // The labels are presentation-only. Never use them for API/world/player identity.
        return {
            world: worldLoaded && worldLabel.trim() ? worldLabel.trim() : "Welt auswählen",
            player: playerLoaded && playerLabel.trim() ? playerLabel.trim() : "Spieler auswählen",
            saveStatus: isDirty ? "Ungespeicherte Änderungen" : "Keine Änderungen",
        };
    }

    function createLayoutController({
        storage = null,
        storageKey = "mcbe-inventory-editor:layout",
        root = null,
        select = null,
        body = null,
        heading = null,
        description = null,
        mode = null,
        contextWorld = null,
        contextPlayer = null,
        saveStatus = null,
        worldSource = null,
        playerSource = null,
        translate = value => value,
        observerFactory = null,
        detailPanel = null,
        multiSelectPanel = null,
        onInspectorOpen = null,
        onClassicLayout = null,
        onAlternativeLayout = null,
    } = {}) {
        const resolve = value => typeof value === "function" ? value() : value;
        let current = readStoredLayout(storage, storageKey);
        let wired = false;

        function setText(element, value) {
            if (element && element.textContent !== value) element.textContent = value;
        }

        function refreshWorkflow(view) {
            const info = VIEW_INFO[view] || VIEW_INFO.world;
            setText(resolve(heading), translate(info.title));
            setText(resolve(description), translate(info.description));
            setText(resolve(mode), translate(current === "studio" ? "Studio · Arbeitsbereiche"
                : current === "focus" ? "Fokus · Arbeitsbereiche" : "Arbeitsbereich"));
        }

        function refreshContext() {
            const classes = resolve(body)?.classList;
            const state = editingContextModel({
                worldLoaded: Boolean(classes?.contains("app-world-loaded")),
                playerLoaded: Boolean(classes?.contains("app-player-loaded")),
                isDirty: Boolean(classes?.contains("app-dirty")),
                worldLabel: String(resolve(worldSource)?.textContent || ""),
                playerLabel: String(resolve(playerSource)?.textContent || ""),
            });
            const worldReady = Boolean(classes?.contains("app-world-loaded"));
            const playerReady = Boolean(classes?.contains("app-player-loaded"));
            setText(resolve(contextWorld), worldReady && String(resolve(worldSource)?.textContent || "").trim()
                ? state.world : translate("Welt auswählen"));
            setText(resolve(contextPlayer), playerReady && String(resolve(playerSource)?.textContent || "").trim()
                ? state.player : translate("Spieler auswählen"));
            setText(resolve(saveStatus), translate(state.saveStatus));
        }

        function applyLayout(value) {
            const previous = current;
            current = normalizeLayout(value);
            const html = resolve(root);
            if (html?.dataset) html.dataset.layout = current;
            const control = resolve(select);
            if (control) control.value = current;
            try { storage?.setItem(storageKey, current); } catch (_error) {}
            // Classic has no dedicated player-data navigation. Return to the
            // original player view without resetting the player or edited data.
            if (previous !== "classic" && current === "classic" &&
                    resolve(body)?.dataset?.workflowView === "player-edit") onClassicLayout?.();
            if (previous === "classic" && current !== "classic" &&
                    resolve(body)?.dataset?.workflowView === "player" &&
                    resolve(body)?.classList?.contains("app-player-loaded")) onAlternativeLayout?.();
            refreshWorkflow(resolve(body)?.dataset?.workflowView);
            refreshContext();
            if (previous !== current && resolve(body)?.dataset?.workflowView === "inventory") {
                for (const candidate of [detailPanel, multiSelectPanel]) {
                    const panel = resolve(candidate);
                    if (panel?.style?.display === "flex") onInspectorOpen?.(panel, current);
                }
            }
            return current;
        }

        function wire() {
            if (wired) return;
            wired = true;
            const control = resolve(select);
            control?.addEventListener?.("change", () => applyLayout(control.value));
            if (observerFactory && resolve(body)) {
                const observer = observerFactory(() => {
                    refreshWorkflow(resolve(body)?.dataset?.workflowView);
                    refreshContext();
                });
                observer.observe(resolve(body), { attributes: true, attributeFilter: ["data-workflow-view", "class"] });
                for (const source of [resolve(worldSource), resolve(playerSource)]) {
                    if (!source) continue;
                    const labelObserver = observerFactory(refreshContext);
                    labelObserver.observe(source, { childList: true, subtree: true, characterData: true });
                }
            }
            for (const panel of [resolve(detailPanel), resolve(multiSelectPanel)]) {
                if (!observerFactory || !panel || !onInspectorOpen) continue;
                let wasOpen = panel.style.display === "flex";
                const observer = observerFactory(() => {
                    const isOpen = panel.style.display === "flex";
                    if (!wasOpen && isOpen && current !== "classic") onInspectorOpen(panel, current);
                    wasOpen = isOpen;
                });
                observer.observe(panel, { attributes: true, attributeFilter: ["style"] });
            }
        }

        return { applyLayout, getLayout: () => current, refreshWorkflow, refreshContext, wire };
    }

    function createConfiguredLayoutController({ doc = document, storage = localStorage } = {}) {
        return createLayoutController({
            storage,
            root: () => doc.documentElement,
            body: () => doc.body,
            select: () => doc.getElementById("layoutSelect"),
            heading: () => doc.getElementById("layoutViewTitle"),
            description: () => doc.getElementById("layoutViewDescription"),
            mode: () => doc.getElementById("layoutModeLabel"),
            contextWorld: () => doc.getElementById("layoutCurrentWorld"),
            contextPlayer: () => doc.getElementById("layoutCurrentPlayer"),
            saveStatus: () => doc.getElementById("layoutSaveStatus"),
            worldSource: () => doc.getElementById("worldName"),
            playerSource: () => doc.getElementById("playerSummaryName"),
            detailPanel: () => doc.getElementById("detailEditorPanel"),
            multiSelectPanel: () => doc.getElementById("multiSelectPanel"),
            onClassicLayout: () => window.setWorkflowView?.("player", { scroll: false, preserveEditor: true }),
            onAlternativeLayout: () => window.setWorkflowView?.("player-edit", { scroll: false, preserveEditor: true }),
            onInspectorOpen: (panel, layout) => {
                // Let the browser place the inspector first. Do not scroll if
                // the user has already changed view/layout or closed it again.
                window.requestAnimationFrame(() => {
                    if (layout === "classic") {
                        if (window.innerWidth <= 1024 && doc.body?.dataset?.workflowView === "inventory" &&
                                doc.documentElement?.dataset?.layout === layout && panel.style.display === "flex") {
                            doc.querySelector?.('.btn-toggle[data-panel="right"]')?.click();
                        }
                        return;
                    }
                    if (window.innerWidth > STACKED_INSPECTOR_MAX_WIDTH[layout]
                            || doc.documentElement?.dataset?.layout !== layout
                            || doc.body?.dataset?.workflowView !== "inventory"
                            || panel.style.display !== "flex") return;
                    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
                    panel.scrollIntoView?.({
                        behavior: reducedMotion ? "instant" : "smooth",
                        block: "start",
                    });
                });
            },
            translate: value => window.t ? window.t(value) : value,
            observerFactory: callback => new MutationObserver(callback),
        });
    }

    function init() {
        const controller = createConfiguredLayoutController();
        controller.applyLayout(controller.getLayout());
        controller.wire();
        return controller;
    }

    window.MCBELayoutController = {
        ALLOWED_LAYOUTS,
        VIEW_INFO,
        editingContextModel,
        createConfiguredLayoutController,
        createLayoutController,
        normalizeLayout,
        readStoredLayout,
        init,
    };

    if (typeof document !== "undefined") {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
        else init();
    }
}());
