"""Player copy skips unreadable source equipment without deleting target gear."""

import json

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import LOCAL_PLAYER_KEY
from tests.nbt_fixtures import make_minimal_player_tag
from tests.node_runner import run_node


def _item(name, *, slot=None, extra=""):
    item = nbt.CompoundTag({"Name": nbt.StringTag(name), "Count": nbt.ByteTag(1 if name else 0), "Damage": nbt.ShortTag(0)})
    if slot is not None:
        item["Slot"] = nbt.ByteTag(slot)
    if extra:
        item["FutureData"] = nbt.StringTag(extra)
    return item


@pytest.mark.parametrize("target_has_equipment", [True, False])
def test_copy_preserves_only_target_slots_skipped_for_readonly_source_equipment(tmp_path, monkeypatch, target_has_equipment):
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    source_key = b"player_synthetic_source"
    source = make_minimal_player_tag()
    source["Inventory"] = nbt.ListTag([_item("minecraft:carrot", slot=0)])
    # Legacy lists with an explicit Slot, and OffHandItem, are readable echoes
    # that cannot be transferred safely into another player's root equipment.
    source["Armor"] = nbt.ListTag([_item("minecraft:iron_helmet", slot=103)])
    source["OffHandItem"] = _item("minecraft:shield")
    target = make_minimal_player_tag()
    target["Inventory"] = nbt.ListTag([_item("minecraft:apple", slot=0)])
    target["Armor"] = nbt.ListTag(
        [
            _item("minecraft:diamond_helmet", extra="keep target helmet") if target_has_equipment else _item(""),
            _item(""),
            _item(""),
            # A genuinely empty source slot still replaces/clears the target.
            _item("minecraft:diamond_boots"),
        ]
    )
    target["Offhand"] = nbt.ListTag([_item("minecraft:shield", extra="keep target shield") if target_has_equipment else _item("")])
    original_helmet = target["Armor"][0].save_to()
    original_shield = target["Offhand"][0].save_to()
    original_source = save_player_nbt(nbt.NamedTag(source))
    database = LevelDbAdapter(str(world / "db"))
    try:
        database.put_batch({LOCAL_PLAYER_KEY: save_player_nbt(nbt.NamedTag(target)), source_key: original_source, b"unrelated": b"unchanged"})
    finally:
        database.close()

    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    target_key_text = encode_player_key(LOCAL_PLAYER_KEY)
    source_key_text = encode_player_key(source_key)
    source_data = service.load_player(str(world), source_key_text)
    target_data = service.load_player(str(world), target_key_text)
    assert source_data["inventory"][103]["root_equipment_read_only"] is True
    assert source_data["inventory"][-106]["root_equipment_read_only"] is True
    source_data = {"inventory": source_data["inventory"]}
    target_data = {"inventory": target_data["inventory"], "player_revision": target_data["player_revision"]}
    result = run_node(
        "const fixture = "
        + json.dumps({"source": source_data, "target": target_data, "world": str(world), "sourceKey": source_key_text, "targetKey": target_key_text})
        + r""";
        const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
        const context = {window: {}, AbortController};
        for (const name of ['player_view_models', 'player_tools', 'save_payload_logic', 'inventory_state']) {
            vm.runInNewContext(fs.readFileSync(`static/${name}.js`, 'utf8'), context);
        }
        (async () => {
            let inventory = structuredClone(fixture.target.inventory);
            const original = structuredClone(inventory);
            const origin = context.window.MCBEInventoryState.createInventoryOriginController({
                getWorldPath: () => fixture.world, getCurrentPlayerKey: () => fixture.targetKey,
            });
            const controller = context.window.MCBEPlayerTools.createPlayerToolsController({
                elements: {copySourcePlayerSelect: {value: fixture.sourceKey}, copyInventoryArea: {checked: true}},
                getWorldPath: () => fixture.world, getCurrentPlayerKey: () => fixture.targetKey,
                getPlayers: () => [{player_key: fixture.sourceKey}], getInventory: () => inventory,
                setInventory: value => {inventory = value}, annotateItemOrigins: origin.annotateItemOrigins,
                showConfirmDialog: async () => true, api: {loadPlayerOrThrow: async () => fixture.source},
            });
            assert.equal(await controller.copyFromSelectedPlayer(), true);
            const logic = context.window.MCBESavePayloadLogic.createSavePayloadLogic({
                getCleanSnapshot: () => ({inv: original, ec: {}, effects: [], abilities: {}, stats: {}}),
                getInventory: () => inventory, getEnderChestInventory: () => ({}),
                getPlayerEffects: () => [], getPlayerAbilities: () => ({}), getPlayerStats: () => ({}),
                getProtectedNbt: () => ({}), getEffectsTouched: () => false, getAbilitiesTouched: () => false,
                getCurrentPlayerKey: () => fixture.targetKey, getCurrentPlayerRevision: () => fixture.target.player_revision,
                getWorldPath: () => fixture.world, getWorldPresenceSessionId: () => '', getServerGuardEpoch: () => 0,
                sectionChanged: (a, b) => JSON.stringify(a) !== JSON.stringify(b),
                removeProtectedStatsFromPayload: value => value,
                itemIsVisiblePresent: item => Boolean(item?.name),
                itemRequiresOriginalNbt: context.window.MCBEInventoryState.itemRequiresOriginalNbt,
            });
            process.stdout.write(JSON.stringify(logic.buildSavePayload()));
        })().catch(error => {console.error(error); process.exitCode = 1});
        """
    )
    payload = json.loads(result.stdout)
    saved = service.save_player(str(world), target_key_text, payload["inventory"], {}, base_revision=payload["base_revision"], root_equipment_editable=True)
    assert saved["success"] is True
    database = service._open_db_readonly(str(world))
    try:
        records = dict(database.iter_items())
    finally:
        database.close()
    final_target = load_player_nbt(records[LOCAL_PLAYER_KEY]).tag
    assert final_target["Armor"][0].save_to() == original_helmet
    assert final_target["Offhand"][0].save_to() == original_shield
    assert final_target["Armor"][3]["Count"].py_data == 0
    assert final_target["Inventory"][0]["Name"].py_data == "minecraft:carrot"
    assert records[source_key] == original_source
    assert records[b"unrelated"] == b"unchanged"
