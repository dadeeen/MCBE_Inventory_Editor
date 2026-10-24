import textwrap

from tests.node_runner import run_node


def test_reverted_slot_restores_representation_but_preserves_identity_and_nbt_intent() -> None:
    run_node(r"""
        const assert = require('assert'), fs = require('fs'), vm = require('vm');
        const context = { window: {} };
        for (const file of ['entity_variant_editor', 'slot_detail_logic']) {
            vm.runInNewContext(fs.readFileSync(`static/${file}.js`, 'utf8'), context);
        }
        const restore = context.window.MCBESlotDetailLogic.restoreEquivalentItem;
        const baseline = { slot: 4, name: 'minecraft:stone', count: 2, damage: 0,
            source_slot: 4, source_player_key: 'player', source_container: 'inventory',
            source_world_path: 'world', source_item_digest: 'a'.repeat(64),
            nbt_view: { original: true }, stack_key: 'original',
            has_protected_nbt: true, special_item: { kind: 'test', data: { a: 1, b: 2 } } };
        const candidate = { enchantments: [], lore: [], display_name: '', ...baseline,
            special_item: { data: { b: 2, a: 1 }, kind: 'test' } };
        delete candidate.nbt_view;
        delete candidate.stack_key;
        assert.equal(JSON.stringify(restore(candidate, baseline)), JSON.stringify(baseline));
        assert.notEqual(restore(candidate, baseline), baseline);
        for (const changes of [
            { source_slot: 5 }, { source_player_key: 'other' }, { source_container: 'ender_chest' },
            { source_world_path: 'other' }, { source_item_digest: 'b'.repeat(64) },
            { replace_original_nbt: true }, { protected_nbt_dropped: true },
            { special_edit: { kind: 'test', data: {} } }, { has_protected_nbt: false },
            { count: 3 }, { display_name: 'Changed' }, { lore: ['Changed'] },
            { enchantments: [{ id: 9, lvl: 1 }] },
        ]) {
            const changed = { ...candidate, ...changes };
            assert.equal(restore(changed, baseline), changed, JSON.stringify(changes));
        }
        assert.equal(restore(null, baseline), null);
        assert.equal(restore(candidate, null), candidate);

        const rawText = { ...baseline, display_name: 'First\r\nSecond', lore: ['A\r\nB', 'C\rD'] };
        const normalizedText = { ...rawText, count: 7, display_name: 'FirstSecond', lore: ['A', 'B', 'C', 'D'] };
        const preservedText = restore(normalizedText, rawText);
        assert.equal(preservedText.count, 7);
        assert.equal(preservedText.display_name, rawText.display_name);
        assert.equal(JSON.stringify(preservedText.lore), JSON.stringify(rawText.lore));
        assert.equal(normalizedText.display_name, 'FirstSecond');
        for (const identity of [{ source_item_digest: 'b'.repeat(64) }, { replace_original_nbt: true }]) {
            const replacement = { ...normalizedText, ...identity };
            assert.equal(restore(replacement, rawText), replacement);
        }

        const entity = context.window.MCBEEntityVariantEditor;
        for (const [name, metadata, edit] of [
            ['minecraft:axolotl_bucket', { entity_id: 'minecraft:axolotl', variant: 1, is_baby: false, can_edit: true },
                { kind: 'axolotl', variant: 1, is_baby: false }],
            ['minecraft:tropical_fish_bucket', { entity_id: 'minecraft:tropical_fish', variant: 0, mark_variant: 1, color: 2, color2: 3, can_edit: true },
                { kind: 'tropical_fish', variant: 0, mark_variant: 1, color: 2, color2: 3 }],
        ]) {
            const original = { ...baseline, name, entity_variant: metadata };
            const reverted = { ...candidate, name, entity_variant_edit: edit,
                entity_variant: entity.updatedEntityVariantMetadata(metadata, edit) };
            assert.equal(JSON.stringify(restore(reverted, original)), JSON.stringify(original));
            for (const extra of [{ replace_original_nbt: true }, { source_item_digest: 'b'.repeat(64) }]) {
                const replacement = { ...reverted, ...extra };
                assert.equal(restore(replacement, original), replacement);
            }
            const changed = { ...reverted, entity_variant_edit: { ...edit, variant: 4 } };
            assert.equal(restore(changed, original), changed);
            // An edit already present in the baseline is still pending work.
            const pending = { ...original, entity_variant_edit: edit };
            assert.equal(restore(candidate, pending), candidate);
        }
    """)


def test_followup_slot_edits_preserve_pending_nbt_warnings_and_entity_edits() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require('assert');
            const fs = require('fs');
            const vm = require('vm');
            const context = {window: {}};
            vm.runInNewContext(fs.readFileSync('static/slot_detail_logic.js', 'utf8'), context);
            const build = context.window.MCBESlotDetailLogic.buildDetailItemFromForm;
            const metadata = {
                replace_original_nbt: true, protected_nbt_dropped: true,
                previous_name: 'minecraft:written_book',
                special_nbt_defaulted: true, special_nbt_requirement: 'book',
                entity_variant_edit: {kind: 'axolotl', variant: 4, is_baby: true},
            };
            let previousItem = {slot: 0, name: 'minecraft:stone', count: 1, damage: 0, ...metadata};
            for (const rawCustomName of ['A', 'Ab', 'Abc']) {
                const result = build({slotId: 0, rawName: previousItem.name,
                    rawCount: 2, rawDamage: 0, rawCustomName, previousItem});
                assert.equal(result.ok, true);
                for (const [key, value] of Object.entries(metadata)) {
                    assert.equal(JSON.stringify(result.item[key]), JSON.stringify(value), key);
                }
                previousItem = result.item;
            }
            const replaced = build({slotId: 0, rawName: 'minecraft:dirt', rawCount: 1,
                rawDamage: 0, previousItem, itemRequiresOriginalNbt: () => false});
            assert.equal(replaced.item.protected_nbt_dropped, true);
            assert.equal(replaced.item.previous_name, 'minecraft:written_book');
            assert.equal(replaced.item.special_nbt_defaulted, undefined);
            assert.equal(replaced.item.entity_variant_edit, undefined);
            """
        )
    )


def test_followup_root_equipment_edits_preserve_storage_metadata() -> None:
    run_node(r"""
        const assert = require('assert'), fs = require('fs'), vm = require('vm');
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync('static/slot_detail_logic.js', 'utf8'), context);
        const { buildDetailItemFromForm: build, restoreEquivalentItem: restore } = context.window.MCBESlotDetailLogic;
        for (const extra of [{}, { root_equipment_read_only: true }]) {
            const original = { slot: 103, name: 'minecraft:diamond_helmet', count: 1, damage: 16,
                source_slot: 103, source_player_key: 'player', source_container: 'inventory',
                source_world_path: 'world', source_item_digest: 'a'.repeat(64),
                root_equipment_source_tag: 'Armor', root_equipment_source_index: 0,
                nbt_view: { tag: 'original' }, ...extra };
            let item = original;
            for (const damage of [21, 16]) {
                const result = build({ slotId: 103, previousItem: item, rawName: item.name,
                    rawCount: 1, rawDamage: damage, maxDamage: 363 });
                assert.equal(result.ok, true);
                item = result.item;
                assert.equal(item.root_equipment_source_tag, 'Armor');
                assert.equal(item.root_equipment_source_index, 0);
                assert.equal(item.root_equipment_read_only, extra.root_equipment_read_only);
            }
            assert.equal(JSON.stringify(restore(item, original)), JSON.stringify(original));
            const replacement = build({ slotId: 103, previousItem: item,
                rawName: 'minecraft:iron_helmet', rawCount: 1, rawDamage: 0 });
            assert.equal(replacement.item.root_equipment_source_tag, undefined);
            assert.equal(replacement.item.root_equipment_source_index, undefined);
            assert.equal(replacement.item.replace_original_nbt, true);
        }
    """)


def test_frontend_slot_detail_logic_builds_and_preserves_same_item_nbt() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_detail_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_detail_logic.js" });

            const logic = context.window.MCBESlotDetailLogic;
            const previousItem = {
                slot: 4,
                source_slot: 12,
                source_player_key: "player-a",
                source_container: "inventory",
                source_world_path: "world-a",
                source_item_digest: "a".repeat(64),
                name: "minecraft:stone",
                count: 64,
                damage: 0,
                display_name: "Alter Name",
                lore: ["A"],
                enchantments: [],
                has_protected_nbt: true,
                item_tag_opaque: true,
                protected_nbt_summary: "keep",
                origin_world_mismatch: true,
                replace_original_nbt: true,
                nbt_view: "{keep:true}",
            };
            const result = logic.buildDetailItemFromForm({
                slotId: 4,
                previousItem,
                rawName: " minecraft:stone ",
                rawCount: "99",
                rawDamage: "4",
                rawCustomName: "Alter Name",
                rawLore: "A",
                enchantments: [],
                currentPlayerKey: "player-b",
                worldPath: "world-b",
                maxStack: 64,
                maxDamage: 0,
                isValidItemId: () => true,
            });

            assert.strictEqual(result.ok, true);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(result.item)), {
                slot: 4,
                source_slot: 12,
                source_player_key: "player-a",
                source_container: "inventory",
                source_world_path: "world-a",
                source_item_digest: "a".repeat(64),
                name: "minecraft:stone",
                count: 64,
                damage: 0,
                display_name: "Alter Name",
                lore: ["A"],
                enchantments: [],
                has_protected_nbt: true,
                item_tag_opaque: true,
                protected_nbt_summary: "keep",
                origin_world_mismatch: true,
                replace_original_nbt: true,
                nbt_view: "{keep:true}",
            });
            """
        )
    )


def test_frontend_slot_detail_logic_keeps_absent_optional_fields_on_noop() -> None:
    run_node(r"""
        const assert = require("assert"), fs = require("fs"), vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/slot_detail_logic.js", "utf8"), context);
        const previousItem = { slot: 0, name: "minecraft:banner", count: 1, damage: 4,
            special_item: { kind: "banner", editable: true, data: { patterns: [] } } };
        const result = context.window.MCBESlotDetailLogic.buildDetailItemFromForm({
            slotId: 0, previousItem, rawName: previousItem.name, rawCount: "1.0", rawDamage: "4",
            rawCustomName: "", rawLore: "", enchantments: [], maxStack: 16, maxDamage: 15,
            isValidItemId: () => true,
        });
        assert.equal(result.ok, true);
        assert.equal(JSON.stringify(result.item), JSON.stringify(previousItem));
        assert.notEqual(result.item, previousItem);
    """)


def test_frontend_slot_detail_logic_scopes_entity_metadata_and_preserves_only_existing_overstacks() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/slot_detail_logic.js", "utf8"),
                context,
                { filename: "static/slot_detail_logic.js" },
            );
            const logic = context.window.MCBESlotDetailLogic;
            const axolotlBucket = {
                name: "minecraft:axolotl_bucket",
                count: 1,
                entity_variant: { display_name_en: "Leucistic Axolotl" },
            };

            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.entityVariantMetadataForItem(
                    axolotlBucket,
                    "minecraft:axolotl_bucket",
                ))),
                { display_name_en: "Leucistic Axolotl" },
            );
            assert.strictEqual(
                logic.entityVariantMetadataForItem(axolotlBucket, "minecraft:stone"),
                null,
            );
            assert.strictEqual(
                logic.entityVariantMetadataForItem(axolotlBucket, ""),
                null,
            );

            const oversizedBed = {
                name: "minecraft:bed",
                count: 64,
                damage: 0,
                enchantments: [],
            };
            assert.strictEqual(logic.buildDetailItemFromForm({
                previousItem: oversizedBed,
                rawName: "minecraft:bed",
                rawCount: 64,
                maxStack: 1,
            }).item.count, 64);
            assert.strictEqual(logic.buildDetailItemFromForm({
                previousItem: oversizedBed,
                rawName: "minecraft:bed",
                rawCount: 32,
                maxStack: 1,
            }).item.count, 1);
            assert.strictEqual(logic.buildDetailItemFromForm({
                rawName: "minecraft:bed",
                rawCount: 64,
                maxStack: 1,
            }).item.count, 1);
            """
        )
    )


def test_frontend_slot_detail_logic_empty_invalid_and_nbt_drop_cases() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_detail_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_detail_logic.js" });

            const logic = context.window.MCBESlotDetailLogic;
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.loreLinesFromText(
                "  first  \n\nsecond-long",
                { maxLines: 3, maxLineLength: 20 },
            ))), ["  first  ", "", "second-long"]);

            const previousLore = ["Block A", "", "  indented  "];
            const unchangedLore = logic.buildDetailItemFromForm({
                slotId: 1,
                previousItem: {
                    slot: 1,
                    name: "minecraft:stone",
                    count: 1,
                    damage: 0,
                    lore: previousLore,
                    enchantments: [],
                },
                rawName: "minecraft:stone",
                rawLore: previousLore.join("\n"),
            });
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(unchangedLore.item.lore)),
                previousLore,
            );

            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.buildDetailItemFromForm({
                rawName: "bad",
                isValidItemId: () => false,
            }))), {
                ok: false,
                error: "Ungültige Item-ID. Erwartet wird z. B. minecraft:stone.",
            });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.buildDetailItemFromForm({
                rawName: "minecraft:air",
            }))), { ok: true, item: null });

            const changed = logic.buildDetailItemFromForm({
                slotId: 7,
                containerName: "ender_chest",
                previousItem: { name: "minecraft:shulker_box", has_protected_nbt: true },
                rawName: "minecraft:chest",
                rawCount: "1",
                rawDamage: "0",
                currentPlayerKey: "player",
                worldPath: "world",
                isValidItemId: () => true,
                itemRequiresOriginalNbt: item => Boolean(item.has_protected_nbt),
                specialItemNbtRequirement: name => name === "minecraft:chest" ? "block_entity" : null,
            });

            assert.strictEqual(changed.ok, true);
            assert.strictEqual(changed.item.protected_nbt_dropped, true);
            assert.strictEqual(changed.item.previous_name, "minecraft:shulker_box");
            assert.strictEqual(changed.item.special_nbt_defaulted, true);
            assert.strictEqual(changed.item.special_nbt_requirement, "block_entity");
            assert.strictEqual(changed.item.source_container, "ender_chest");
            """
        )
    )


def test_frontend_slot_detail_logic_rejects_non_registry_item_only_when_new() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/slot_detail_logic.js", "utf8"), context, {
                filename: "static/slot_detail_logic.js",
            });
            const logic = context.window.MCBESlotDetailLogic;
            const deps = {
                rawName: "minecraft:element_32",
                isValidItemId: () => true,
                isAddableItemId: () => false,
            };
            const created = logic.buildDetailItemFromForm(deps);
            assert.strictEqual(created.ok, false);
            assert.match(created.error, /kein registriertes Vanilla-Inventaritem/);

            const existing = logic.buildDetailItemFromForm({
                ...deps,
                previousItem: { name: "minecraft:element_32", count: 1, damage: 0, enchantments: [] },
            });
            assert.strictEqual(existing.ok, true);
            """
        )
    )


def test_frontend_slot_detail_logic_applies_and_clears_availability_badge() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/slot_detail_logic.js", "utf8"), context, {
                filename: "static/slot_detail_logic.js",
            });
            const badge = {
                hidden: true,
                textContent: "stale",
                title: "stale",
                dataset: { itemAvailability: "stale" },
                attributes: { "aria-label": "stale" },
                setAttribute(name, value) { this.attributes[name] = value; },
                removeAttribute(name) { delete this.attributes[name]; },
            };

            context.window.MCBESlotDetailLogic.applyItemAvailabilityBadge(badge, {
                key: "creative",
                label: "Kreativ",
                description: "Beschreibung",
                ariaLabel: "Klassifikation: Kreativ. Beschreibung",
            });
            assert.strictEqual(badge.hidden, false);
            assert.strictEqual(badge.textContent, "Kreativ");
            assert.strictEqual(badge.title, "Beschreibung");
            assert.strictEqual(badge.dataset.itemAvailability, "creative");
            assert.strictEqual(badge.attributes["aria-label"], "Klassifikation: Kreativ. Beschreibung");

            context.window.MCBESlotDetailLogic.applyItemAvailabilityBadge(badge, null);
            assert.strictEqual(badge.hidden, true);
            assert.strictEqual(badge.textContent, "");
            assert.strictEqual(badge.title, "");
            assert.strictEqual(badge.dataset.itemAvailability, undefined);
            assert.strictEqual(badge.attributes["aria-label"], undefined);
            """
        )
    )


def test_frontend_slot_detail_logic_carries_only_explicit_entity_variant_edits() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/slot_detail_logic.js", "utf8"),
                context,
                { filename: "static/slot_detail_logic.js" },
            );
            const logic = context.window.MCBESlotDetailLogic;
            const previousItem = {
                slot: 2,
                name: "minecraft:axolotl_bucket",
                count: 1,
                damage: 0,
                display_name: "",
                lore: [],
                enchantments: [],
                has_preserved_nbt: true,
                entity_variant: {
                    variant: 2,
                    display_name_en: "Gold Axolotl",
                },
                nbt_view: { original: true },
            };
            const edit = {
                kind: "axolotl",
                variant: 4,
                is_baby: true,
            };
            const metadata = {
                variant: 4,
                display_name_en: "Blue Axolotl",
                is_baby: true,
            };

            const changed = logic.buildDetailItemFromForm({
                slotId: 2,
                previousItem,
                rawName: "minecraft:axolotl_bucket",
                rawCount: 1,
                rawDamage: 0,
                entityVariantEdit: edit,
                entityVariantMetadata: metadata,
            });
            assert.strictEqual(changed.ok, true);
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(changed.item.entity_variant_edit)),
                edit,
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(changed.item.entity_variant)),
                metadata,
            );
            assert.strictEqual(Object.hasOwn(changed.item, "nbt_view"), false);

            const unchanged = logic.buildDetailItemFromForm({
                slotId: 2,
                previousItem,
                rawName: "minecraft:axolotl_bucket",
                rawCount: 1,
                rawDamage: 0,
            });
            assert.strictEqual(Object.hasOwn(unchanged.item, "entity_variant_edit"), false);
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(unchanged.item.nbt_view)),
                { original: true },
            );
            """
        )
    )


def test_frontend_data_variant_unknown_values_are_only_preserved_from_the_current_item() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/slot_detail_logic.js", "utf8"),
                context,
                { filename: "static/slot_detail_logic.js" },
            );
            const plan = context.window.MCBESlotDetailLogic.dataVariantSelectionPlan;
            const variants = [{ damage: 0 }, { damage: 2 }];

            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(plan({
                    itemName: "minecraft:empty_map",
                    damageValue: 99,
                    variants,
                    sourceItem: {
                        name: "minecraft:empty_map",
                        damage: 99,
                        source_item_digest: "verified",
                    },
                }))),
                { selectedDamage: 99, preserveUnknown: true },
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(plan({
                    itemName: "minecraft:empty_map",
                    damageValue: 99,
                    variants,
                    sourceItem: {
                        name: "minecraft:empty_map",
                        damage: 99,
                        source_index: 3,
                    },
                }))),
                { selectedDamage: 99, preserveUnknown: true },
            );
            for (const sourceItem of [null, { name: 'minecraft:stone', damage: 99 },
                { name: 'minecraft:empty_map', damage: 98 }]) {
                assert.deepStrictEqual(
                    JSON.parse(JSON.stringify(plan({
                        itemName: 'minecraft:empty_map', damageValue: 99, variants, sourceItem,
                    }))),
                    { selectedDamage: 0, preserveUnknown: false },
                );
            }
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(plan({
                    itemName: "minecraft:empty_map",
                    damageValue: 2,
                    variants,
                }))),
                { selectedDamage: 2, preserveUnknown: false },
            );
            """
        )
    )


def test_frontend_slot_detail_logic_rejects_incompatible_new_enchantments() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_detail_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_detail_logic.js" });

            const logic = context.window.MCBESlotDetailLogic;
            const result = logic.buildDetailItemFromForm({
                slotId: 1,
                rawName: "minecraft:stone",
                enchantments: [{ id: 17, lvl: 1 }],
                isValidItemId: () => true,
                isEnchantableItem: () => false,
                isEnchantmentCompatible: () => false,
                detailItemLabel: () => "Stein",
            });

            assert.strictEqual(result.ok, false);
            assert.strictEqual(
                result.error,
                "Stein ist nach Vanilla-Regeln nicht verzauberbar. Entferne die Verzauberungen oder wähle ein verzauberbares Item.",
            );
            """
        )
    )


def test_frontend_slot_detail_logic_preserves_unchanged_values_outside_local_limits() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/slot_detail_logic.js", "utf8"),
                context,
                { filename: "static/slot_detail_logic.js" },
            );
            const logic = context.window.MCBESlotDetailLogic;
            const longName = `  ${"x".repeat(600)}  `;
            const previousItem = {
                slot: 3,
                name: "minecraft:diamond_sword",
                count: 1,
                damage: 9999,
                display_name: longName,
                lore: [],
                enchantments: [],
                source_item_digest: "verified",
            };

            const preserved = logic.buildDetailItemFromForm({
                slotId: 3,
                previousItem,
                rawName: previousItem.name,
                rawCount: "1",
                rawDamage: "9999",
                rawCustomName: longName,
                maxStack: 1,
                maxDamage: 1561,
                maxDisplayName: 512,
            });

            assert.strictEqual(preserved.ok, true);
            assert.strictEqual(preserved.item.damage, 9999);
            assert.strictEqual(preserved.item.display_name, longName);

            const changed = logic.buildDetailItemFromForm({
                slotId: 3,
                previousItem,
                rawName: previousItem.name,
                rawCount: "1",
                rawDamage: "8888",
                rawCustomName: `changed-${"y".repeat(600)}`,
                maxStack: 1,
                maxDamage: 1561,
                maxDisplayName: 512,
            });

            assert.strictEqual(changed.ok, false);
            assert.match(changed.error, /Anzeigename/);
            const validChange = logic.buildDetailItemFromForm({
                slotId: 3,
                previousItem,
                rawName: previousItem.name,
                rawCount: "1",
                rawDamage: "8888",
                rawCustomName: "Neuer Name",
                maxStack: 1,
                maxDamage: 1561,
                maxDisplayName: 512,
            });
            assert.strictEqual(validChange.item.damage, 1561);
            assert.strictEqual(validChange.item.display_name, "Neuer Name");
            """
        )
    )


def test_frontend_slot_detail_logic_apply_single_slot_plan() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_detail_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_detail_logic.js" });

            const logic = context.window.MCBESlotDetailLogic;
            const item = { slot: 1, name: "minecraft:stone", count: 1 };
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.applySingleSlotPlan({
                protectedKnown: true,
                buildResult: { ok: true, item },
            }))), { ok: false, reason: "protected_slot", showProtected: true });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.applySingleSlotPlan({
                buildResult: { ok: false, error: "bad" },
            }))), {
                ok: false,
                reason: "invalid_item",
                toast: { message: "bad", type: "warning", ms: 4000 },
            });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.applySingleSlotPlan({
                previousItem: item,
                buildResult: { ok: true, item },
            }))), { ok: false, reason: "unchanged", refreshQuickActions: true });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.applySingleSlotPlan({
                previousItem: item,
                buildResult: { ok: true, item: null },
            }))), { ok: true, operation: "clear", item: null, requiresUndo: true });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.applySingleSlotPlan({
                previousItem: null,
                buildResult: { ok: true, item },
            }))), { ok: true, operation: "set", item, requiresUndo: true });
            """
        )
    )


def test_frontend_slot_detail_logic_quick_action_plans() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_detail_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_detail_logic.js" });

            const logic = context.window.MCBESlotDetailLogic;
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.quickClearSlotPlan({
                hasTarget: true,
                protectedKnown: true,
                rawName: "minecraft:stone",
            }))), { ok: false, reason: "protected_slot", showProtected: true });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.quickClearSlotPlan({
                hasTarget: true,
                rawName: "minecraft:air",
            }))), { ok: false, reason: "empty_slot", refreshQuickActions: true });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.quickClearSlotPlan({
                hasTarget: true,
                rawName: "minecraft:stone",
            }))), { ok: true, requiresUndo: true });

            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.quickMaxStackPlan({
                hasTarget: true,
                rawName: "",
                maxStack: 64,
            }))).toast, { message: "Wähle zuerst ein Item aus.", type: "warning", ms: 3000 });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.quickMaxStackPlan({
                hasTarget: true,
                rawName: "minecraft:stone",
                maxStack: 64,
            }))), { ok: true, count: 64 });

            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.quickRepairSlotPlan({
                hasTarget: true,
                repairableDamage: false,
            }))), {
                ok: false,
                reason: "not_repairable",
                refreshQuickActions: true,
                toast: {
                    message: "Dieses Item hat keine reparierbare Abnutzung.",
                    type: "warning",
                    ms: 3000,
                },
            });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.quickRepairSlotPlan({
                hasTarget: true,
                repairableDamage: true,
            }))), { ok: true, damage: 0 });
            """
        )
    )


def test_frontend_slot_detail_controller_blocks_quick_actions_at_execution_time() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/slot_detail_logic.js", "utf8"),
                context,
                { filename: "static/slot_detail_logic.js" },
            );

            function fakeButton() {
                return {
                    handlers: {},
                    addEventListener(name, handler) { this.handlers[name] = handler; },
                    click() { this.handlers.click(); },
                };
            }

            const clearButton = fakeButton();
            const maxStackButton = fakeButton();
            const repairButton = fakeButton();
            const count = { value: "21", addEventListener() {} };
            const toasts = [];
            const dirtyCalls = [];
            const statuses = [];
            const actions = [];
            const controller = context.window.MCBESlotDetailLogic.createSlotDetailController({
                elements: {
                    btnQuickClearSlot: clearButton,
                    btnQuickMaxStack: maxStackButton,
                    btnQuickRepairSlot: repairButton,
                    detailCount: count,
                },
                itemCatalog: {},
                editingBlocked: () => true,
                getEditingBlockedReason: () => "Nur ansehen: Server online.",
                setDirty: value => dirtyCalls.push(value),
                logStatus: (...args) => statuses.push(args),
                recordAction: (...args) => actions.push(args),
                showToast: (...args) => toasts.push(args),
            });
            controller.wire();

            clearButton.click();
            maxStackButton.click();
            repairButton.click();

            assert.strictEqual(count.value, "21");
            assert.deepStrictEqual(dirtyCalls, []);
            assert.deepStrictEqual(statuses, []);
            assert.deepStrictEqual(actions, []);
            assert.strictEqual(toasts.length, 3);
            assert.ok(toasts.every(toast => toast[0] === "Nur ansehen: Server online."));
            assert.ok(toasts.every(toast => toast[1] === "warning"));
            """
        )
    )


def test_frontend_slot_detail_logic_keeps_custom_name_padding() -> None:
    """Name padding is valid Bedrock formatting and must survive the form.

    Trimming here silently rewrote the custom name of every untouched item,
    because the browser echoes the complete container on every save.
    """

    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_detail_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_detail_logic.js" });

            const logic = context.window.MCBESlotDetailLogic;
            const build = rawCustomName => logic.buildDetailItemFromForm({
                slotId: 4,
                previousItem: null,
                rawName: "minecraft:stone",
                rawCount: "1",
                rawDamage: "0",
                rawCustomName,
                rawLore: "",
                enchantments: [],
                currentPlayerKey: "player-a",
                worldPath: "world-a",
                maxStack: 64,
                maxDamage: 0,
                isValidItemId: () => true,
            });

            for (const padded of ["   Zentriert   ", "Nachlaufend ", " Fuehrend"]) {
                const result = build(padded);
                assert.strictEqual(result.ok, true);
                assert.strictEqual(
                    result.item.display_name,
                    padded,
                    `Custom-Name ${JSON.stringify(padded)} wurde beschnitten`,
                );
            }
            """
        )
    )


def test_shared_item_form_validates_capacity_variants_and_preserves_originals() -> None:
    run_node(
        r"""
        const assert = require('assert');
        const vm = require('vm');
        const fs = require('fs');
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync('static/slot_detail_logic.js', 'utf8'), context);
        const logic = context.window.MCBESlotDetailLogic;
        const catalog = {
            getMaxStack: name => name === 'minecraft:diamond_sword' ? 1 : 64,
            getMaxDamage: () => 100,
            itemUsesDurabilityDamage: name => name === 'minecraft:diamond_sword',
            hasVerifiedStackLimit: () => true,
            isValidItemId: () => true, isAddableItemId: () => true,
            isEnchantableItemForEditor: name => name === 'minecraft:diamond_sword',
            isEnchantmentCompatibleWithItem: (id, name) => name === 'minecraft:diamond_sword' && id === 9,
            dataValueVariantsForId: name => name === 'minecraft:banner' ? [{damage: 0}, {damage: 1}] : [],
        };
        const base = { catalog, slotId: 0, rawName: 'minecraft:stone', rawCount: 1, rawDamage: 0 };
        for (const rawCount of ['', '1.5', '65', '2x', -1, 128]) {
            assert.strictEqual(logic.buildItemForm({...base, rawCount}).ok, false);
        }
        assert.strictEqual(logic.buildItemForm({...base, rawCount: 64}).item.count, 64);
        assert.strictEqual(logic.buildItemForm({...base, rawCount: '1e1', rawDamage: '1e1'}).ok, false);
        assert.strictEqual(logic.buildItemForm({...base, rawName: 'minecraft:diamond_sword', rawDamage: '1e1'}).item.damage, 10);
        assert.strictEqual(logic.buildItemForm({...base, rawCount: '1e1'}).item.count, 10);
        const limit = { maximum: 4, error: '' };
        assert.strictEqual(logic.buildItemForm({...base, countLimit: limit, rawCount: 5}).ok, false);
        assert.strictEqual(logic.buildItemForm({...base, countLimit: limit, rawCount: 4}).item.count, 4);
        for (const rawDamage of ['', '1.5', -1, 101]) assert.strictEqual(logic.buildItemForm({...base, rawDamage}).ok, false);
        assert.strictEqual(logic.buildItemForm({...base, rawName: 'minecraft:banner', rawDamage: 2}).ok, false);
        const previousItem = {slot: 0, name: 'minecraft:banner', count: 65, damage: 2, enchantments: [{id: 999, lvl: 99}]};
        const saved = JSON.stringify(previousItem);
        assert.strictEqual(logic.buildItemForm({...base, previousItem, rawName: previousItem.name,
            rawCount: 65, rawDamage: 2, enchantments: previousItem.enchantments}).ok, true);
        assert.strictEqual(JSON.stringify(previousItem), saved);
        assert.strictEqual(logic.buildItemForm({...base, enchantments: [{id: 9, lvl: 1}], enchantmentsDb: {9: {max_lvl: 5}}}).ok, false);
        assert.strictEqual(logic.buildItemForm({...base, rawName: 'minecraft:diamond_sword',
            enchantments: [{id: 9, lvl: 6}], enchantmentsDb: {9: {max_lvl: 5}}}).ok, false);
        const state = logic.itemFormModel({...base, rawName: 'minecraft:diamond_sword'});
        assert.strictEqual(state.readOnlyCount, true);
        assert.strictEqual(state.maximum, 1);
        const original = {...previousItem, display_name: 'Keep name', lore: ['Keep lore'],
            source_item_digest: 'verified', nbt_view: {type: 'CompoundTag', value: {}}};
        const unchanged = logic.buildItemForm({...base, previousItem: original, rawName: original.name,
            rawCount: original.count, rawDamage: original.damage, rawCustomName: original.display_name,
            rawLore: original.lore.join('\n'), enchantments: original.enchantments});
        assert.strictEqual(JSON.stringify(unchanged.item), JSON.stringify(original));
        assert.strictEqual(logic.applySingleSlotPlan({previousItem: original, buildResult: unchanged}).reason, 'unchanged');
        assert.notStrictEqual(unchanged.item, original);
        unchanged.item.lore.push('Only the draft');
        assert.strictEqual(original.lore.length, 1);
        """
    )


def test_shared_damage_editor_distinguishes_modes_and_preserves_unknown_original_values() -> None:
    run_node(
        r"""
        const assert = require('assert');
        const vm = require('vm');
        const fs = require('fs');
        const context = {window: {}};
        for (const file of ['item_catalog.js', 'slot_detail_logic.js']) {
            vm.runInNewContext(fs.readFileSync('static/' + file, 'utf8'), context);
        }
        const db = JSON.parse(fs.readFileSync('mcbe_editor/resources/item_db.json', 'utf8'));
        const catalog = context.window.MCBEItemCatalog.createItemCatalog({
            getItemsDb: () => db.items,
            getCompatItemAliases: () => db.compat_item_aliases,
            getAddableItems: () => new Set(db.addable_items),
            getItemIconIndex: () => ({}),
            getStackLimits: () => db.stack_limits,
            getMaxDamageMap: () => db.durability,
            itemIdRe: /^[a-z0-9_.-]+:[a-z0-9_.-]+$/,
            defaultMaxDamage: 32767,
            maxBedrockStackCount: 127,
        });
        const logic = context.window.MCBESlotDetailLogic;
        const describe = (itemName, damageValue, sourceItem = null) =>
            logic.itemDamageEditorModel({catalog, itemName, damageValue, sourceItem});
        const plain = describe('minecraft:stone', 0);
        assert.strictEqual(plain.mode, 'none');
        assert.strictEqual(plain.note, '');
        assert.strictEqual(plain.remaining, null);
        assert.strictEqual(plain.error, '');
        const tool = describe('minecraft:diamond_sword', 100);
        assert.strictEqual(tool.mode, 'durability');
        assert.strictEqual(tool.maxDamage, 1561);
        assert.strictEqual(tool.remaining, 1461);
        assert.strictEqual(tool.error, '');
        const map = describe('minecraft:empty_map', 2);
        assert.strictEqual(map.mode, 'variant');
        assert.strictEqual(map.remaining, null);
        assert.strictEqual(map.error, '');
        assert.deepStrictEqual(Array.from(map.variants, value => value.damage), [0, 2]);

        for (const [name, damage, mode] of [
            ['minecraft:stone', -7, 'none'],
            ['minecraft:stone', 40000, 'none'],
            ['minecraft:empty_map', -7, 'variant'],
            ['minecraft:potion', 99, 'variant'],
            ['minecraft:diamond_sword', -7, 'durability'],
            ['minecraft:diamond_sword', 2000, 'durability'],
        ]) {
            // A contained child has a parent-bound index, not an inventory digest.
            const original = {slot: 6, source_index: 3, name, count: 1, damage,
                display_name: 'Keep', lore: ['Original'], enchantments: [],
                has_protected_nbt: true, nbt_view: {extra: {bytes: [0, -1, 127]}}};
            const snapshot = JSON.stringify(original);
            const state = describe(name, damage, original);
            assert.strictEqual(state.mode, mode);
            assert.strictEqual(state.value, damage);
            assert.strictEqual(state.preserveUnknown, true);
            assert.strictEqual(state.error, '');
            assert.strictEqual(state.remaining, null);
            assert.ok(state.note.includes(String(damage)));
            assert.strictEqual(JSON.stringify(original), snapshot);

            const fields = {catalog, slotId: 6, previousItem: original, rawName: name,
                rawCount: 1, rawDamage: String(damage), rawCustomName: 'Keep', rawLore: 'Original'};
            const echoed = logic.buildItemForm(fields);
            assert.strictEqual(echoed.ok, true);
            assert.strictEqual(JSON.stringify(echoed.item), snapshot);
            assert.notStrictEqual(echoed.item, original);
            const renamed = logic.buildItemForm({...fields, rawCustomName: 'Renamed'});
            assert.strictEqual(renamed.ok, true);
            assert.strictEqual(renamed.item.damage, damage);
            assert.strictEqual(renamed.item.display_name, 'Renamed');
            assert.strictEqual(renamed.item.has_protected_nbt, true);
            assert.strictEqual(JSON.stringify(original), snapshot);

            for (const foreign of [null, {...original, name: 'minecraft:diamond'}, {...original, damage: damage + 1}]) {
                const rejected = describe(name, damage, foreign);
                assert.strictEqual(rejected.preserveUnknown, false);
                assert.ok(rejected.error);
                assert.strictEqual(logic.buildItemForm({...fields, previousItem: foreign}).ok, false);
            }
        }

        const original = {slot: 0, name: 'minecraft:diamond_sword', count: 1, damage: 2000};
        const fields = {catalog, slotId: 0, previousItem: original,
            rawName: original.name, rawCount: 1};
        for (const value of [0, 10, 1561]) {
            const corrected = logic.buildItemForm({...fields, rawDamage: value});
            assert.strictEqual(corrected.ok, true);
            assert.strictEqual(corrected.item.damage, value);
            assert.strictEqual(describe(original.name, value, original).remaining, 1561 - value);
        }
        for (const value of ['', '2.5', '20px', -8, 1562, 2001]) {
            assert.strictEqual(logic.buildItemForm({...fields, rawDamage: value}).ok, false);
        }
        assert.strictEqual(original.damage, 2000);
        """
    )
