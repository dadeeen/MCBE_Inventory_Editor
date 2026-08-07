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


def test_frontend_item_availability_classifies_primary_and_variant_rules() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const payload = JSON.parse(fs.readFileSync("mcbe_editor/resources/item_availability.json", "utf8"));
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_availability.js", "utf8"), context, {
                filename: "static/item_availability.js",
            });

            const catalog = context.window.MCBEItemAvailability.createItemAvailabilityCatalog(payload);
            assert.strictEqual(catalog.categoryFor(" MINECRAFT:BARRIER "), "technical");
            assert.strictEqual(catalog.categoryFor("minecraft:allay_spawn_egg"), "creative");
            assert.strictEqual(catalog.categoryFor("minecraft:ender_dragon_spawn_egg"), "command_only");
            assert.strictEqual(catalog.categoryFor("minecraft:potion", 36), "creative");
            assert.strictEqual(catalog.categoryFor("minecraft:potion", "36"), "creative");
            assert.strictEqual(catalog.categoryFor("minecraft:potion", 0), null);
            assert.strictEqual(catalog.categoryFor("minecraft:tipped_arrow", 36), null);
            assert.strictEqual(catalog.categoryFor("minecraft:apple"), null);

            const badge = catalog.badgeFor("minecraft:bedrock");
            assert.strictEqual(badge.key, "creative");
            assert.strictEqual(badge.label, "Kreativ");
            assert.ok(badge.description.includes("Überlebensmodus"));
            assert.ok(!badge.label.includes("Nur"));
            assert.ok(badge.ariaLabel.includes("Klassifikation: Kreativ"));
            """
        )
    )


def test_frontend_item_availability_replaces_state_and_translates_at_render_time() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const translations = {
                "Kreativ": "Creative",
                "Im Kreativinventar verfügbar, im normalen Überlebensmodus nicht als Gegenstand erhältlich.": "Creative description",
                "Klassifikation: {label}. {description}": "Classification: {label}. {description}",
            };
            const context = {
                window: {
                    t(text, params) {
                        return String(translations[text] || text).replace(
                            /\{(\w+)\}/g,
                            (match, key) => params && key in params ? String(params[key]) : match,
                        );
                    },
                },
            };
            vm.runInNewContext(fs.readFileSync("static/item_availability.js", "utf8"), context);
            const catalog = context.window.MCBEItemAvailability.createItemAvailabilityCatalog({
                schema_version: 1,
                source_release: "v1",
                reviewed_at: "2026-08-03",
                references: [{ title: "source" }],
                classifications: { creative: ["minecraft:bedrock"] },
                variants: {},
            });

            assert.strictEqual(catalog.badgeFor("minecraft:bedrock").label, "Creative");
            assert.strictEqual(
                catalog.badgeFor("minecraft:bedrock").ariaLabel,
                "Classification: Creative. Creative description",
            );
            const metadata = catalog.metadata();
            metadata.references.push({ title: "mutated" });
            assert.strictEqual(catalog.metadata().references.length, 1);

            catalog.replace({ classifications: {}, variants: {} });
            assert.strictEqual(catalog.categoryFor("minecraft:bedrock"), null);
            """
        )
    )
