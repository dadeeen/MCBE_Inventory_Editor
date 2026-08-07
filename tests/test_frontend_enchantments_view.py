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


def test_frontend_enchantments_view_unavailable_text_matches_item_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/enchantments_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/enchantments_view.js" });

            const view = context.window.MCBEEnchantmentsView;
            assert.strictEqual(
                view.unavailableEnchantmentsText({ hasExistingEnchantments: false }),
                "Dieses Item ist nach Vanilla-Regeln nicht verzauberbar. Der Editor legt dafür keine neue Enchantment-NBT an.",
            );
            const empty = view.unavailableEnchantmentsHtml({ hasExistingEnchantments: false });
            assert.ok(empty.includes("Der Editor legt dafür keine neue Enchantment-NBT an."));
            assert.ok(empty.includes("no-backups compact"));

            const existing = view.unavailableEnchantmentsHtml({ hasExistingEnchantments: true });
            assert.ok(existing.includes("Vorhandene ungewöhnliche Enchantment-NBT"));
            assert.strictEqual(
                view.unavailableEnchantmentsText({ itemName: "minecraft:book" }),
                "Ein normales Buch speichert keine Verzauberungen. Wähle „Verzaubertes Buch“, um Verzauberungen zu bearbeiten.",
            );
            """
        )
    )


def test_frontend_enchantments_view_row_model_and_html_escape_values() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const code = fs.readFileSync("static/enchantments_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(code, context, { filename: "static/enchantments_view.js" });

            const view = context.window.MCBEEnchantmentsView;
            const model = view.enchantmentRowModel({
                id: 7,
                info: {
                    name_de: "Schärfe <S>",
                    name_en: "Sharpness & More",
                    max_lvl: 5,
                },
                activeEnchantment: { id: 7, lvl: 3 },
                compatible: false,
            });
            const html = view.enchantmentRowHtml(model);

            assert.strictEqual(model.className, "ench-row readonly");
            assert.strictEqual(model.currentLevel, 3);
            assert.strictEqual(model.sliderMax, 5);
            assert.strictEqual(model.levelDisabled, true);
            assert.ok(html.includes("Schärfe &lt;S&gt;"));
            assert.ok(html.includes("Sharpness &amp; More"));
            assert.ok(html.includes("unpassend, wird erhalten"));
            assert.ok(html.includes('value="3"'));
            assert.ok(html.includes("checked"));
            assert.ok(html.includes("disabled"));
            assert.ok(!html.includes("Schärfe <S>"));
            """
        )
    )


def test_frontend_enchantments_view_prioritizes_english_name_in_english_locale() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: { MCBEI18n: {
                locale: "en",
                localizedPair: (de, en) => ({ primary: en || "", secondary: "" }),
            } } };
            vm.runInNewContext(fs.readFileSync("static/enchantments_view.js", "utf8"), context, {
                filename: "static/enchantments_view.js",
            });

            const view = context.window.MCBEEnchantmentsView;
            const model = view.enchantmentRowModel({
                id: 0,
                info: { name_de: "Schutz", name_en: "Protection", max_lvl: 4 },
            });
            const html = view.enchantmentRowHtml(model);
            assert.strictEqual(model.primaryName, "Protection");
            assert.strictEqual(model.secondaryName, "");
            assert.ok(html.includes("Protection"));
            assert.ok(!html.includes("Schutz"));

            const missingEnglish = view.enchantmentRowModel({
                id: 99,
                info: { name_de: "Nur Deutsch", name_en: "", max_lvl: 1 },
            });
            assert.strictEqual(missingEnglish.primaryName, "99");
            assert.strictEqual(missingEnglish.secondaryName, "");

            const sameName = view.enchantmentRowModel({
                id: 10,
                info: { name_de: "Regeneration", name_en: "Regeneration", max_lvl: 1 },
            });
            assert.strictEqual(sameName.secondaryName, "");
            """
        )
    )


def test_frontend_enchantments_view_row_element_uses_model_class_and_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/enchantments_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/enchantments_view.js" });

            const view = context.window.MCBEEnchantmentsView;
            const created = [];
            const doc = {
                createElement(tagName) {
                    const el = { tagName, className: "", innerHTML: "" };
                    created.push(el);
                    return el;
                },
            };
            const model = view.enchantmentRowModel({
                id: 16,
                info: { name_de: "Schärfe", name_en: "Sharpness", max_lvl: 5 },
                activeEnchantment: { id: 16, lvl: 2 },
                compatible: true,
            });
            const row = view.enchantmentRowElement(model, doc);

            assert.strictEqual(created.length, 1);
            assert.strictEqual(row.tagName, "div");
            assert.strictEqual(row.className, "ench-row");
            assert.ok(row.innerHTML.includes("Schärfe"));
            assert.ok(row.innerHTML.includes('value="2"'));
            """
        )
    )


def test_frontend_enchantments_view_action_buttons_model_and_applier() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/enchantments_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/enchantments_view.js" });

            const view = context.window.MCBEEnchantmentsView;
            const model = view.enchantmentActionButtonsModel({
                enchantmentCount: 2,
                enchantable: true,
                maxableCount: 1,
            });
            assert.strictEqual(model.countText, "2");
            assert.strictEqual(model.maxAllDisabled, false);
            assert.strictEqual(model.maxAllTitle, "Hebt vorhandene passende Verzauberungen auf ihr Vanilla-Maximallevel an");
            assert.strictEqual(model.clearAllDisabled, false);

            const elements = {
                count: { innerText: "" },
                maxAllButton: { disabled: true, title: "" },
                clearAllButton: { disabled: true },
            };
            view.applyEnchantmentActionButtonsModel(elements, model);
            assert.strictEqual(elements.count.innerText, "2");
            assert.strictEqual(elements.maxAllButton.disabled, false);
            assert.strictEqual(elements.maxAllButton.title, "Hebt vorhandene passende Verzauberungen auf ihr Vanilla-Maximallevel an");
            assert.strictEqual(elements.clearAllButton.disabled, false);

            const unavailable = view.enchantmentActionButtonsModel({
                enchantmentCount: 0,
                enchantable: false,
                maxableCount: 0,
            });
            view.applyEnchantmentActionButtonsModel(elements, unavailable);
            assert.strictEqual(elements.count.innerText, "0");
            assert.strictEqual(elements.maxAllButton.disabled, true);
            assert.strictEqual(elements.maxAllButton.title, "Dieses Item ist nach Vanilla-Regeln nicht verzauberbar");
            assert.strictEqual(elements.clearAllButton.disabled, true);
            """
        )
    )


def test_frontend_enchantments_view_unavailable_element_uses_text_content() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/enchantments_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/enchantments_view.js" });

            const view = context.window.MCBEEnchantmentsView;
            const doc = {
                createElement(tagName) {
                    return { tagName, className: "", textContent: "" };
                },
            };
            const note = view.unavailableEnchantmentsElement({ hasExistingEnchantments: true }, doc);

            assert.strictEqual(note.tagName, "div");
            assert.strictEqual(note.className, "no-backups compact");
            assert.ok(note.textContent.includes("Vorhandene ungewöhnliche Enchantment-NBT"));

            const bookNote = view.enchantedBookInfoElement(doc);
            assert.strictEqual(bookNote.tagName, "div");
            assert.strictEqual(bookNote.className, "no-backups compact");
            assert.ok(bookNote.textContent.includes("mehrere Verzauberungen gemeinsam speichern"));
            """
        )
    )
