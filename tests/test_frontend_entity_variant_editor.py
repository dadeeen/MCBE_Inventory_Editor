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


def test_entity_variant_editor_requires_an_existing_concrete_bucket_variant() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = {
                window: {
                    t: text => text,
                    MCBEI18n: {
                        localizedPair: (de, en) => ({ primary: en }),
                    },
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/entity_variant_editor.js", "utf8"),
                context,
                { filename: "static/entity_variant_editor.js" },
            );
            const editor = context.window.MCBEEntityVariantEditor;

            const generic = editor.editorModel({
                item: { name: "minecraft:axolotl_bucket" },
                itemName: "minecraft:axolotl_bucket",
            });
            assert.strictEqual(generic.visible, true);
            assert.strictEqual(generic.editable, false);
            assert.strictEqual(generic.state, "generic");
            assert.match(generic.note, /Gültiger Kreativ-Eimer|Valid creative bucket/);
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(editor.genericAxolotlColorOptions())),
                [{ value: "generic", label: "Zufällig beim Aussetzen" }],
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(editor.genericAxolotlAgeOptions())),
                [{ value: "adult", label: "Erwachsen beim Aussetzen" }],
            );
            assert.strictEqual(editor.sourceEditFromModel(generic), null);

            const wrongSource = editor.editorModel({
                item: {
                    name: "minecraft:stone",
                    entity_variant: { variant: 4, is_baby: false },
                },
                itemName: "minecraft:axolotl_bucket",
            });
            assert.strictEqual(wrongSource.editable, false);

            const unapprovedMetadata = editor.editorModel({
                item: {
                    name: "minecraft:axolotl_bucket",
                    entity_variant: { variant: 4, is_baby: false },
                },
                itemName: "minecraft:axolotl_bucket",
            });
            assert.strictEqual(unapprovedMetadata.editable, false);
            assert.strictEqual(unapprovedMetadata.state, "captured");

            const unresolved = editor.editorModel({
                item: {
                    name: "minecraft:axolotl_bucket",
                    entity_variant_state: "unresolved",
                },
                itemName: "minecraft:axolotl_bucket",
            });
            assert.strictEqual(unresolved.editable, false);
            assert.strictEqual(unresolved.state, "unresolved");
            assert.match(unresolved.note, /nicht sicher aufgelöst|could not be resolved safely/);

            const captured = editor.editorModel({
                item: {
                    name: "minecraft:axolotl_bucket",
                    entity_variant: {
                        variant: 4,
                        is_baby: true,
                        can_edit: true,
                    },
                },
                itemName: "minecraft:axolotl_bucket",
            });
            assert.strictEqual(captured.editable, true);
            assert.strictEqual(captured.state, "captured");
            assert.strictEqual(captured.variant, 4);
            assert.strictEqual(captured.isBaby, true);
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(editor.sourceEditFromModel(captured))),
                { kind: "axolotl", variant: 4, is_baby: true },
            );

            const englishOptions = editor.axolotlColorOptions();
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(englishOptions)),
                [
                    { value: "0", label: "Leucistic" },
                    { value: "1", label: "Cyan" },
                    { value: "2", label: "Gold" },
                    { value: "3", label: "Wild/Brown" },
                    { value: "4", label: "Blue" },
                ],
            );
            assert.strictEqual(englishOptions.some(option => option.label.includes("Leuzistisch")), false);
            """
        )
    )


def test_entity_variant_editor_builds_validated_edits_and_updated_preview_metadata() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = {
                window: {
                    t: text => text,
                    MCBEI18n: {
                        localizedPair: (de, en) => ({
                            primary: de,
                            secondary: en && en !== de ? en : "",
                        }),
                    },
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/entity_variant_editor.js", "utf8"),
                context,
                { filename: "static/entity_variant_editor.js" },
            );
            const editor = context.window.MCBEEntityVariantEditor;
            assert.strictEqual(
                editor.axolotlColorOptions()[0].label,
                "Leuzistisch (Leucistic)",
            );

            const axolotlEdit = editor.editFromValues({
                kind: "axolotl",
                axolotlVariant: "2",
                axolotlAge: "baby",
            });
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(axolotlEdit)),
                { kind: "axolotl", variant: 2, is_baby: true },
            );
            assert.strictEqual(editor.editFromValues({
                kind: "axolotl",
                axolotlVariant: "5",
                axolotlAge: "adult",
            }), null);

            const originalAxolotl = {
                variant: 0,
                key: "lucy",
                display_name_de: "Leuzistischer Axolotl",
                display_name_en: "Leucistic Axolotl",
                unknown_future_field: "preserve",
            };
            const updatedAxolotl = editor.updatedEntityVariantMetadata(originalAxolotl, axolotlEdit);
            assert.strictEqual(updatedAxolotl.variant, 2);
            assert.strictEqual(updatedAxolotl.is_baby, true);
            assert.strictEqual(updatedAxolotl.icon_key, "mcbe:axolotl_gold_baby");
            assert.strictEqual(updatedAxolotl.unknown_future_field, "preserve");
            assert.strictEqual(originalAxolotl.variant, 0);

            const wildAxolotl = editor.updatedEntityVariantMetadata(originalAxolotl, {
                kind: "axolotl",
                variant: 3,
                is_baby: false,
            });
            assert.strictEqual(wildAxolotl.label_de, "Wild/Braun");
            assert.strictEqual(wildAxolotl.label_en, "Wild/Brown");

            const fishEdit = editor.editFromValues({
                kind: "tropical_fish",
                tropicalPattern: "1:3",
                tropicalColor: "14",
                tropicalColor2: "0",
            });
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(fishEdit)),
                {
                    kind: "tropical_fish",
                    variant: 1,
                    mark_variant: 3,
                    color: 14,
                    color2: 0,
                },
            );
            const updatedFish = editor.updatedEntityVariantMetadata(
                { unknown_future_field: "preserve" },
                fishEdit,
            );
            assert.strictEqual(updatedFish.display_name_de, "Tropenfisch: Blockfish, Rot/Weiß");
            assert.strictEqual(updatedFish.display_name_en, "Tropical Fish: Blockfish, Red/White");
            assert.strictEqual(
                updatedFish.fields[0].raw,
                "item.tropicalBodyBlockfishMulti.name",
            );
            assert.strictEqual(updatedFish.unknown_future_field, "preserve");
            assert.strictEqual(editor.editsEqual(fishEdit, {
                kind: "tropical_fish",
                variant: 1,
                mark_variant: 3,
                color: 14,
                color2: 0,
            }), true);

            const sameColorFish = editor.updatedEntityVariantMetadata(
                {},
                {
                    kind: "tropical_fish",
                    variant: 0,
                    mark_variant: 3,
                    color: 4,
                    color2: 4,
                },
            );
            assert.strictEqual(sameColorFish.label_de, "Dasher, Gelb");
            assert.strictEqual(sameColorFish.label_en, "Dasher, Yellow");
            assert.strictEqual(sameColorFish.fields.length, 3);
            assert.strictEqual(sameColorFish.fields[2].key, "Color2ID");
            """
        )
    )
