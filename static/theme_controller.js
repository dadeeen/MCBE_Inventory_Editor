(function () {
    "use strict";

    const DEFAULT_THEME = "dark";
    const ALLOWED_THEMES = ["system", "dark", "light", "minecraft"];

    function readStoredTheme(storage, key) {
        try {
            return storage?.getItem(key) || DEFAULT_THEME;
        } catch (_e) {
            return DEFAULT_THEME;
        }
    }

    function normalizeTheme(theme) {
        return ALLOWED_THEMES.includes(theme) ? theme : DEFAULT_THEME;
    }

    function resolve(value) {
        return typeof value === "function" ? value() : value;
    }

    function createThemeController(deps = {}) {
        const {
            storage,
            storageKey,
            documentElement,
            themeSelect,
            systemThemeQuery = window.matchMedia?.("(prefers-color-scheme: light)"),
        } = deps;
        let currentTheme = normalizeTheme(readStoredTheme(storage, storageKey));

        function getDocumentElement() {
            return resolve(documentElement);
        }

        function getThemeSelect() {
            return resolve(themeSelect);
        }

        function persistTheme(theme) {
            try {
                storage?.setItem(storageKey, theme);
            } catch (_e) {}
        }

        function applyResolvedTheme() {
            const root = getDocumentElement();
            if (root?.dataset) {
                root.dataset.theme = currentTheme === "system"
                    ? (systemThemeQuery?.matches ? "light" : "dark")
                    : currentTheme;
            }
        }

        systemThemeQuery?.addEventListener?.("change", () => {
            if (currentTheme === "system") applyResolvedTheme();
        });

        function applyTheme(theme) {
            currentTheme = normalizeTheme(theme);
            applyResolvedTheme();
            const select = getThemeSelect();
            if (select) select.value = currentTheme;
            persistTheme(currentTheme);
            return currentTheme;
        }

        return {
            applyTheme,
            getTheme: () => currentTheme,
            normalizeTheme,
        };
    }


    function createConfiguredThemeController({ doc = document, storage = localStorage, storageKey = "mcbe-inventory-editor:theme" } = {}) {
        return createThemeController({
            storage,
            storageKey,
            documentElement: () => doc.documentElement,
            themeSelect: () => doc.getElementById("themeSelect"),
        });
    }

    window.MCBEThemeController = {
        createThemeController,
        createConfiguredThemeController,
        normalizeTheme,
        readStoredTheme,
    };
}());
