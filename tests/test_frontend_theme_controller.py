import textwrap

from tests.node_runner import run_node


def test_frontend_theme_controller_normalizes_persists_and_applies_theme() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/theme_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/theme_controller.js" });

            const stored = new Map([["theme", "light"]]);
            const storage = {
                getItem(key) {
                    return stored.has(key) ? stored.get(key) : null;
                },
                setItem(key, value) {
                    stored.set(key, value);
                },
            };
            const documentElement = { dataset: {} };
            const themeSelect = { value: "" };
            const systemThemeQuery = {
                matches: true,
                addEventListener(name, callback) {
                    assert.strictEqual(name, "change");
                    this.change = callback;
                },
            };

            const controller = context.window.MCBEThemeController.createThemeController({
                storage,
                storageKey: "theme",
                documentElement,
                themeSelect,
                systemThemeQuery,
            });

            assert.strictEqual(controller.getTheme(), "light");
            assert.strictEqual(controller.applyTheme("minecraft"), "minecraft");
            assert.strictEqual(controller.getTheme(), "minecraft");
            assert.strictEqual(documentElement.dataset.theme, "minecraft");
            assert.strictEqual(themeSelect.value, "minecraft");
            assert.strictEqual(stored.get("theme"), "minecraft");

            assert.strictEqual(controller.applyTheme("unknown"), "dark");
            assert.strictEqual(documentElement.dataset.theme, "dark");
            assert.strictEqual(themeSelect.value, "dark");
            assert.strictEqual(stored.get("theme"), "dark");
            assert.strictEqual(context.window.MCBEThemeController.normalizeTheme("system"), "system");
            assert.strictEqual(controller.applyTheme("system"), "system");
            assert.strictEqual(documentElement.dataset.theme, "light");
            assert.strictEqual(themeSelect.value, "system");
            assert.strictEqual(stored.get("theme"), "system");
            systemThemeQuery.matches = false;
            systemThemeQuery.change();
            assert.strictEqual(documentElement.dataset.theme, "dark");
            assert.strictEqual(controller.getTheme(), "system");
            controller.applyTheme("minecraft");
            systemThemeQuery.matches = true;
            systemThemeQuery.change();
            assert.strictEqual(documentElement.dataset.theme, "minecraft");
            """
        )
    )
