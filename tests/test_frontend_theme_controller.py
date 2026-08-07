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


def test_frontend_theme_controller_normalizes_persists_and_applies_theme() -> None:
    _run_node(
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

            const controller = context.window.MCBEThemeController.createThemeController({
                storage,
                storageKey: "theme",
                documentElement,
                themeSelect,
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
            """
        )
    )
