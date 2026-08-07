(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function readStoredBool(storage, key) {
        try {
            return storage?.getItem(key) === "1";
        } catch (_e) {
            return false;
        }
    }

    function writeStoredBool(storage, key, value) {
        try {
            storage?.setItem(key, value ? "1" : "0");
        } catch (_e) {}
    }

    function resolve(value) {
        return typeof value === "function" ? value() : value;
    }

    function createInventoryViewPreferences(deps = {}) {
        const {
            storage,
            slotNumbersKey,
            enderCollapsedKey,
            inventoryContainer,
            toggleSlotNumbers,
            enderChestSection,
            enderChestButton,
        } = deps;
        let showSlotNumbers = readStoredBool(storage, slotNumbersKey);
        let enderChestCollapsed = readStoredBool(storage, enderCollapsedKey);

        function getInventoryContainer() {
            return resolve(inventoryContainer);
        }

        function getToggleSlotNumbers() {
            return resolve(toggleSlotNumbers);
        }

        function getEnderChestSection() {
            return resolve(enderChestSection);
        }

        function getEnderChestButton() {
            return resolve(enderChestButton);
        }

        function applyInventoryViewPreferences() {
            const container = getInventoryContainer();
            if (!container) return;
            container.classList.toggle("show-slot-numbers", showSlotNumbers);
            const toggle = getToggleSlotNumbers();
            if (toggle) toggle.checked = showSlotNumbers;
        }

        function applyEnderChestVisibility() {
            const section = getEnderChestSection();
            const grid = section?.querySelector(".ender-chest-grid");
            if (!section || !grid) return;
            section.classList.toggle("collapsed", enderChestCollapsed);
            grid.style.display = enderChestCollapsed ? "none" : "grid";
            const button = getEnderChestButton();
            if (button) button.textContent = enderChestCollapsed ? t("Aufklappen") : t("Einklappen");
        }

        function setSlotNumbersVisible(value) {
            showSlotNumbers = Boolean(value);
            writeStoredBool(storage, slotNumbersKey, showSlotNumbers);
            applyInventoryViewPreferences();
            return showSlotNumbers;
        }

        function setEnderChestCollapsed(value) {
            enderChestCollapsed = Boolean(value);
            writeStoredBool(storage, enderCollapsedKey, enderChestCollapsed);
            applyEnderChestVisibility();
            return enderChestCollapsed;
        }

        function wireControls({ onSlotNumbersChanged = () => {} } = {}) {
            getToggleSlotNumbers()?.addEventListener("change", () => {
                setSlotNumbersVisible(Boolean(getToggleSlotNumbers()?.checked));
                onSlotNumbersChanged(showSlotNumbers);
            });
            getEnderChestButton()?.addEventListener("click", () => setEnderChestCollapsed(!enderChestCollapsed));
            applyInventoryViewPreferences();
            applyEnderChestVisibility();
        }

        return {
            applyEnderChestVisibility,
            applyInventoryViewPreferences,
            getEnderChestCollapsed: () => enderChestCollapsed,
            getShowSlotNumbers: () => showSlotNumbers,
            setEnderChestCollapsed,
            setSlotNumbersVisible,
            wireControls,
        };
    }


    function createConfiguredInventoryViewPreferences({
        doc = document,
        storage,
        slotNumbersKey,
        enderCollapsedKey,
    } = {}) {
        return createInventoryViewPreferences({
            storage,
            slotNumbersKey,
            enderCollapsedKey,
            inventoryContainer: () => doc.getElementById("inventoryContainer"),
            toggleSlotNumbers: () => doc.getElementById("toggleSlotNumbers"),
            enderChestSection: () => doc.getElementById("enderChestSection"),
            enderChestButton: () => doc.getElementById("btnToggleEnderChest"),
        });
    }

    window.MCBEInventoryViewPreferences = {
        createInventoryViewPreferences,
        createConfiguredInventoryViewPreferences,
        readStoredBool,
        writeStoredBool,
    };
}());
