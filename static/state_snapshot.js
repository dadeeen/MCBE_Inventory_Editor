(function () {
    "use strict";

    function cloneJson(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function snapshotHash(snapshot) {
        return JSON.stringify(snapshot);
    }

    function sectionChanged(beforeValue, afterValue) {
        return JSON.stringify(beforeValue || null) !== JSON.stringify(afterValue || null);
    }

    function createStateSnapshot(getState) {
        function takeSnapshot() {
            const state = getState();
            return {
                inv: cloneJson(state.inventory || {}),
                ec: cloneJson(state.enderChestInventory || {}),
                stats: cloneJson(state.playerStats || {}),
                effects: cloneJson(state.playerEffects || []),
                abilities: cloneJson(state.playerAbilities || {}),
                mounts: cloneJson(state.pendingMounts || []),
            };
        }

        return {
            cloneJson,
            sectionChanged,
            snapshotHash,
            takeSnapshot,
        };
    }

    window.MCBEStateSnapshot = {
        cloneJson,
        createStateSnapshot,
        sectionChanged,
        snapshotHash,
    };
}());
