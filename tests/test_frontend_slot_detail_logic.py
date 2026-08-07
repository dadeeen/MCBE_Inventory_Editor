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


def test_frontend_slot_detail_logic_builds_and_preserves_same_item_nbt() -> None:
    _run_node(
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


def test_frontend_slot_detail_logic_scopes_entity_metadata_and_preserves_only_existing_overstacks() -> None:
    _run_node(
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
    _run_node(
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
    _run_node(
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
    _run_node(
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
    _run_node(
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


def test_frontend_data_variant_unknown_values_are_only_preserved_from_a_verified_source() -> None:
    _run_node(
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
                    },
                }))),
                { selectedDamage: 0, preserveUnknown: false },
            );
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
    _run_node(
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
    _run_node(
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

            assert.strictEqual(changed.item.damage, 1561);
            assert.strictEqual(changed.item.display_name.length, 512);
            """
        )
    )


def test_frontend_slot_detail_logic_apply_single_slot_plan() -> None:
    _run_node(
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
    _run_node(
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


def test_frontend_slot_detail_logic_keeps_custom_name_padding() -> None:
    """Name padding is valid Bedrock formatting and must survive the form.

    Trimming here silently rewrote the custom name of every untouched item,
    because the browser echoes the complete container on every save.
    """

    _run_node(
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
