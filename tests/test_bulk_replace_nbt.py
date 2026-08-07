import subprocess
import textwrap
from pathlib import Path

import pytest


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


def test_bulk_fill_marks_deliberate_replacement_and_save_normalization_clears_marker() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: { t: text => text } };
            vm.runInNewContext(fs.readFileSync("static/inventory_state.js", "utf8"), context);

            const state = context.window.MCBEInventoryState;
            const inventory = {
                8: {
                    slot: 8,
                    source_slot: 8,
                    source_player_key: "player-a",
                    source_container: "inventory",
                    source_world_path: "C:/world",
                    name: "minecraft:stone",
                    count: 1,
                },
            };

            state.fillTargets(
                [{ map: inventory, slotId: 8, container: "inventory" }],
                { name: "minecraft:stone", count: 32, damage: 0 },
            );
            assert.strictEqual(inventory[8].replace_original_nbt, true);
            assert.strictEqual(inventory[8].source_player_key, undefined);

            inventory[100] = {
                slot: 100,
                source_slot: 100,
                source_player_key: "player-a",
                source_container: "armor",
                source_world_path: "C:/world",
                source_item_digest: "e".repeat(64),
                root_equipment_read_only: true,
                name: "minecraft:diamond_boots",
                count: 1,
            };
            const origins = state.createInventoryOriginController({
                getWorldPath: () => "C:/world",
                getCurrentPlayerKey: () => "player-a",
                getInventory: () => inventory,
            });
            origins.normalizeOriginsToCurrentSavedState({
                inventory: { 8: "d".repeat(64), 100: "f".repeat(64) },
                ender_chest: {},
            });

            assert.strictEqual(inventory[8].replace_original_nbt, undefined);
            assert.strictEqual(inventory[8].source_player_key, "player-a");
            assert.strictEqual(inventory[8].source_slot, 8);
            assert.strictEqual(inventory[8].source_item_digest, "d".repeat(64));
            assert.strictEqual(inventory[100].source_container, "armor");
            assert.strictEqual(inventory[100].source_item_digest, "f".repeat(64));
            """
        )
    )


def test_bulk_replace_does_not_inherit_same_name_target_nbt() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    original = nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(8),
            "Name": nbt.StringTag("minecraft:stone"),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
            "WasPickedUp": nbt.ByteTag(1),
            "tag": nbt.CompoundTag({"old_marker": nbt.IntTag(999)}),
        }
    )
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
    payload = {
        "slot": 8,
        "name": "minecraft:stone",
        "count": 32,
        "damage": 0,
        "display_name": "",
        "lore": [],
        "enchantments": [],
        "replace_original_nbt": True,
    }

    saved = inventory.build_inventory_nbt(
        player,
        [payload],
        inventory.ENCHANTMENTS,
        target_player_key="player-a",
    )
    by_slot = {entry["Slot"].py_data: entry for entry in saved}
    result = by_slot[8]

    assert result["Count"].py_data == 32
    assert result["WasPickedUp"].py_data == 0
    assert "tag" not in result
