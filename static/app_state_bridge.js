(function () {
    "use strict";

    function defaultConsole() {
        return typeof console === "undefined" ? null : console;
    }

    function createPatchAssigner(setters = {}, { onUnknownKey = null } = {}) {
        const safeSetters = setters && typeof setters === "object" ? setters : {};

        function assignPatch(patch = {}) {
            if (!patch || typeof patch !== "object") return;

            Object.entries(patch).forEach(([key, value]) => {
                const setter = safeSetters[key];
                if (typeof setter === "function") {
                    setter(value);
                    return;
                }
                if (typeof onUnknownKey === "function") onUnknownKey(key, value);
            });
        }

        assignPatch.knownKeys = () => Object.keys(safeSetters);
        return assignPatch;
    }

    function pickState(state = {}, keys = []) {
        const output = {};
        (keys || []).forEach(key => {
            output[key] = state?.[key];
        });
        return output;
    }

    function unknownPatchKeyLogger(consoleObj = defaultConsole(), prefix = "Unbekanntes App-State-Feld") {
        return key => {
            if (consoleObj && typeof consoleObj.warn === "function") {
                consoleObj.warn(`${prefix}: ${key}`);
            }
        };
    }

    window.MCBEAppStateBridge = {
        createPatchAssigner,
        pickState,
        unknownPatchKeyLogger,
    };
}());
