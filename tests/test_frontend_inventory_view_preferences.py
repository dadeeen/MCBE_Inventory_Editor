import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_inventory_view_preferences_persist_and_apply_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_view_preferences.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_view_preferences.js" });

            function fakeClassList() {
                const classes = new Set();
                return {
                    classes,
                    toggle(name, enabled) {
                        enabled ? classes.add(name) : classes.delete(name);
                    },
                    contains(name) {
                        return classes.has(name);
                    },
                };
            }

            const stored = new Map([
                ["slots", "1"],
                ["ender", "0"],
            ]);
            const storage = {
                getItem(key) {
                    return stored.has(key) ? stored.get(key) : null;
                },
                setItem(key, value) {
                    stored.set(key, value);
                },
            };
            const inventoryContainer = { classList: fakeClassList() };
            const toggleSlotNumbers = { checked: false };
            const grid = { style: { display: "" } };
            const enderChestSection = {
                classList: fakeClassList(),
                querySelector(selector) {
                    return selector === ".ender-chest-grid" ? grid : null;
                },
            };
            const enderChestButton = { textContent: "" };

            const prefs = context.window.MCBEInventoryViewPreferences.createInventoryViewPreferences({
                storage,
                slotNumbersKey: "slots",
                enderCollapsedKey: "ender",
                inventoryContainer,
                toggleSlotNumbers,
                enderChestSection,
                enderChestButton,
            });

            assert.strictEqual(prefs.getShowSlotNumbers(), true);
            assert.strictEqual(prefs.getEnderChestCollapsed(), false);

            prefs.applyInventoryViewPreferences();
            assert.strictEqual(inventoryContainer.classList.contains("show-slot-numbers"), true);
            assert.strictEqual(toggleSlotNumbers.checked, true);

            prefs.setSlotNumbersVisible(false);
            assert.strictEqual(stored.get("slots"), "0");
            assert.strictEqual(inventoryContainer.classList.contains("show-slot-numbers"), false);
            assert.strictEqual(toggleSlotNumbers.checked, false);

            prefs.applyEnderChestVisibility();
            assert.strictEqual(enderChestSection.classList.contains("collapsed"), false);
            assert.strictEqual(grid.style.display, "grid");
            assert.strictEqual(enderChestButton.textContent, "Einklappen");

            prefs.setEnderChestCollapsed(true);
            assert.strictEqual(stored.get("ender"), "1");
            assert.strictEqual(enderChestSection.classList.contains("collapsed"), true);
            assert.strictEqual(grid.style.display, "none");
            assert.strictEqual(enderChestButton.textContent, "Aufklappen");
            """
        )
    )


def test_frontend_inventory_view_preferences_localize_ender_chest_toggle() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_view_preferences.js", "utf8");
            const translations = { "Aufklappen": "Expand", "Einklappen": "Collapse" };
            const context = { window: { t: text => translations[text] || text } };
            vm.runInNewContext(code, context, { filename: "static/inventory_view_preferences.js" });

            const classes = new Set();
            const grid = { style: { display: "" } };
            const section = {
                classList: { toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); } },
                querySelector(selector) { return selector === ".ender-chest-grid" ? grid : null; },
            };
            const button = { textContent: "" };
            const prefs = context.window.MCBEInventoryViewPreferences.createInventoryViewPreferences({
                storage: { getItem() { return null; }, setItem() {} },
                slotNumbersKey: "slots",
                enderCollapsedKey: "ender",
                enderChestSection: section,
                enderChestButton: button,
            });

            prefs.applyEnderChestVisibility();
            assert.strictEqual(button.textContent, "Collapse");
            prefs.setEnderChestCollapsed(true);
            assert.strictEqual(button.textContent, "Expand");
            assert.strictEqual(grid.style.display, "none");
            assert.strictEqual(classes.has("collapsed"), true);
            """
        )
    )
