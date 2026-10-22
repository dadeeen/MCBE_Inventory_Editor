"""Equipment harness regressions using synthetic NBT, never an actual BDS run."""

from copy import deepcopy
import json

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from scripts.engine_checks.cases import expected_snapshot
from scripts.engine_checks.client_profile import CONTROL_NAME, CONTROL_SLOTS, client_worker, verify_player_items
from scripts.engine_checks.equipment import EQUIPMENT_SLOTS, equipment_items, exercise_equipment_service, make_equipment_cases, verify_equipment
from scripts.engine_checks.extended import ENCHANTMENT_IDS
from scripts.engine_checks.nbt_roundtrip import read_records
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.service_profile import assignments, make_service_cases


@pytest.fixture
def equipment_inputs():
    from scripts.engine_checks.runner import ROOT

    catalog = json.loads((ROOT / "mcbe_editor/resources/item_db.json").read_text(encoding="utf-8"))
    # Explicit test doubles for engine measurements; no live-engine evidence.
    observations = {item: {"max_amount": maximum, "max_durability": catalog["durability"].get(item)} for item, maximum in catalog["stack_limits"].items()}
    return observations, catalog


@pytest.fixture
def equipment_cases(equipment_inputs):
    observations, catalog = equipment_inputs
    return make_equipment_cases(observations, catalog["stack_limits"])


def empty_equipment():
    return nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0), "WasPickedUp": nbt.ByteTag(0)})


def fixture_item(case, *, seed):
    snapshot = expected_snapshot(case, seed=seed)
    if snapshot is None:
        return empty_equipment()
    tag = nbt.CompoundTag({"future_probe": nbt.LongTag(2**50)})
    if snapshot["damage"]:
        tag["Damage"] = nbt.IntTag(snapshot["damage"])
    display = nbt.CompoundTag()
    if snapshot["name"]:
        display["Name"] = nbt.StringTag(snapshot["name"])
    if snapshot["lore"]:
        display["Lore"] = nbt.ListTag([nbt.StringTag(line) for line in snapshot["lore"]])
    if display:
        tag["display"] = display
    if snapshot["enchantments"]:
        tag["ench"] = nbt.ListTag(
            [nbt.CompoundTag({"id": nbt.ShortTag(ENCHANTMENT_IDS[value["id"]]), "lvl": nbt.ShortTag(value["level"])}) for value in snapshot["enchantments"]]
        )
    if seed and "seed_book" in case:
        book = case["seed_book"]
        tag.update(
            {
                "generation": nbt.IntTag(0),
                "title": nbt.StringTag(book["title"]),
                "author": nbt.StringTag(book["author"]),
                "pages": nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag(page), "photoname": nbt.StringTag("")}) for page in book["pages"]]),
            }
        )
    return nbt.CompoundTag(
        {
            "Name": nbt.StringTag(snapshot["id"]),
            "Count": nbt.ByteTag(snapshot["amount"]),
            "Damage": nbt.ShortTag(case.get("data_value", 0)),
            "WasPickedUp": nbt.ByteTag(0),
            "tag": tag,
        }
    )


def fixture_equipment(cases, *, seed=True, body=True):
    root = nbt.CompoundTag({"Armor": nbt.ListTag([empty_equipment() for _ in range(4)]), "Offhand": nbt.ListTag([empty_equipment()])})
    if body:
        root["Armor"].append(nbt.CompoundTag({"OpaqueBody": nbt.LongArrayTag([2**50, -3])}))
    for case in cases:
        field, index, _ = EQUIPMENT_SLOTS[case["equipment_slot"]]
        root[field][index] = fixture_item(case, seed=seed)
    return root


def fixture_player(container_cases, equipment_cases, *, body=True):
    root = fixture_equipment(equipment_cases, body=body)
    for field, slot in CONTROL_SLOTS.items():
        root[field] = nbt.ListTag(
            [
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(slot),
                        "Name": nbt.StringTag("minecraft:stone"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                        "tag": nbt.CompoundTag({"display": nbt.CompoundTag({"Name": nbt.StringTag(CONTROL_NAME)})}),
                    }
                )
            ]
        )
    locations = assignments(container_cases)
    for case in container_cases:
        if case["mode"] == "create":
            continue
        field, slot = locations[case["case_id"]]
        item = fixture_item(case, seed=True)
        item["Slot"] = nbt.ByteTag(slot)
        root[field].append(item)
    root["OpaqueRoot"] = nbt.LongArrayTag([2**50, -8])
    return nbt.NamedTag(root)


@pytest.fixture
def synthetic_world(tmp_path, monkeypatch):
    import mcbe_editor.db as db_module

    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr(db_module, "_runtime_app_modules", lambda: ())
    monkeypatch.setattr(db_module, "_registered_write_guard", None)

    def create(player):
        world = tmp_path / "nonplayable"
        (world / "db").mkdir(parents=True)
        (world / "levelname.txt").write_text("Synthetic nonplayable fixture", encoding="utf-8")
        key = b"player_server_equipment_synthetic"
        records = {
            key: save_player_nbt(player),
            b"player_equipment_synthetic": save_player_nbt(
                nbt.NamedTag(nbt.CompoundTag({"MsaId": nbt.StringTag("synthetic"), "ServerId": nbt.StringTag("synthetic")}))
            ),
            b"unrelated": b"preserved",
        }
        write_records(world, records)
        return world, key, records

    return create


def write_records(world, records):
    from mcbe_editor.db import LevelDbAdapter

    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch(records)
    finally:
        db.close()


def test_equipment_plan_covers_fixed_slots_and_distinct_operations(equipment_cases):
    assert {case["equipment_slot"]: case["mode"] for case in equipment_cases} == {
        "Head": "preserve",
        "Chest": "decorate",
        "Legs": "clear",
        "Feet": "create",
        "Offhand": "decorate",
    }
    assert len({case["case_id"] for case in equipment_cases}) == 5
    assert all(case["case_id"].startswith("equipment_") and case["carrier"].startswith("MCBE_ENGINE_CARRIER_") for case in equipment_cases)
    cleared = next(case for case in equipment_cases if case["mode"] == "clear")
    assert expected_snapshot(cleared, seed=True)["id"] == "minecraft:diamond_leggings"
    assert expected_snapshot(cleared) is None
    created = next(case for case in equipment_cases if case["mode"] == "create")
    assert expected_snapshot(created, seed=True) is None
    assert expected_snapshot(created)["id"] == "minecraft:diamond_boots"


@pytest.mark.parametrize("fault", ["missing", "uncurated", "changed", "boolean", "curated_boolean", "durability", "boolean_durability"])
def test_equipment_plan_rejects_unverified_measurements(equipment_inputs, fault):
    observations, catalog = deepcopy(equipment_inputs)
    item = "minecraft:diamond_chestplate"
    if fault == "missing":
        del observations[item]
    elif fault == "uncurated":
        del catalog["stack_limits"][item]
    elif fault == "changed":
        observations[item]["max_amount"] = 2
    elif fault == "boolean":
        observations[item]["max_amount"] = True
    elif fault == "curated_boolean":
        catalog["stack_limits"][item] = True
    else:
        observations[item]["max_durability"] = 13 if fault == "durability" else True
    with pytest.raises(ProbeError, match="measured"):
        make_equipment_cases(observations, catalog["stack_limits"])


@pytest.mark.parametrize("seed", [True, False])
@pytest.mark.parametrize("body", [True, False])
def test_equipment_observer_reads_dense_shapes_and_empty_slots(equipment_cases, seed, body):
    root = fixture_equipment(equipment_cases, seed=seed, body=body)
    assert verify_equipment(root, equipment_cases, seed=seed) == {"status": "pass", "cases": 5}
    assert equipment_items(root)["Feet" if seed else "Legs"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "missing_armor",
        "short_armor",
        "long_armor",
        "missing_offhand",
        "extra_offhand",
        "legacy",
        "slot",
        "count_type",
        "damage_type",
        "wrong_slot",
        "retained_clear",
        "lost_create",
        "empty_tag",
        "empty_name",
    ],
)
def test_equipment_oracle_detects_dense_list_and_semantic_corruption(equipment_cases, fault):
    root = fixture_equipment(equipment_cases, seed=False)
    verify_equipment(root, equipment_cases)
    if fault == "missing_armor":
        del root["Armor"]
    elif fault == "short_armor":
        root["Armor"] = nbt.ListTag(list(root["Armor"])[:3])
    elif fault == "long_armor":
        root["Armor"].append(empty_equipment())
    elif fault == "missing_offhand":
        del root["Offhand"]
    elif fault == "extra_offhand":
        root["Offhand"].append(empty_equipment())
    elif fault == "legacy":
        root["OffHandItem"] = empty_equipment()
    elif fault == "slot":
        root["Armor"][0]["Slot"] = nbt.ByteTag(0)
    elif fault == "count_type":
        root["Offhand"][0]["Count"] = nbt.ShortTag(1)
    elif fault == "damage_type":
        root["Armor"][1]["tag"]["Damage"] = nbt.ShortTag(13)
    elif fault == "wrong_slot":
        root["Armor"][0], root["Armor"][1] = root["Armor"][1], root["Armor"][0]
    elif fault == "retained_clear":
        root["Armor"][2] = fixture_equipment(equipment_cases)["Armor"][2]
    elif fault == "lost_create":
        root["Armor"][3] = empty_equipment()
    elif fault == "empty_tag":
        root["Armor"][2]["tag"] = nbt.CompoundTag({"unexpected": nbt.IntTag(1)})
    else:
        root["Armor"][2]["Name"] = nbt.IntTag(0)
    with pytest.raises(ProbeError):
        verify_equipment(root, equipment_cases)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown"])
def test_equipment_oracle_requires_a_complete_slot_plan(equipment_cases, fault):
    root = fixture_equipment(equipment_cases)
    verify_equipment(root, equipment_cases, seed=True)
    cases = deepcopy(equipment_cases)
    if fault == "missing":
        cases.pop()
    else:
        cases[-1]["equipment_slot"] = "Head" if fault == "duplicate" else "Mainhand"
    with pytest.raises(ProbeError, match="each fixed slot"):
        verify_equipment(root, cases, seed=True)


@pytest.mark.parametrize("body", [True, False])
def test_client_worker_checks_all_container_special_and_equipment_cases(tmp_path, synthetic_world, equipment_inputs, equipment_cases, body):
    observations, catalog = equipment_inputs
    container_cases = make_service_cases(observations, catalog["stack_limits"], catalog["enchantments"])
    cases = container_cases + equipment_cases
    assert len(container_cases) == 48 and len(cases) == 53
    player = fixture_player(container_cases, equipment_cases, body=body)
    world, key, before = synthetic_world(player)
    assert verify_player_items(before[key], cases, seed=True)["cases"] == 53
    result = client_worker(tmp_path, world, read_records(world), cases, "edit")
    assert result["cases"] == 53 and result["equipment_cases"] == 5
    assert result["equipment"] == {"status": "pass", "cases": 5, "backed_up_saves": 1, "no_op_checks": 1}
    assert result["player_service"]["backed_up_saves"] == 5
    assert client_worker(tmp_path, world, read_records(world), cases, "verify")["cases"] == 53
    after = read_records(world)
    assert {record: raw for record, raw in after.items() if record != key} == {record: raw for record, raw in before.items() if record != key}
    saved = load_player_nbt(after[key]).tag
    assert saved["OpaqueRoot"].save_to() == player.tag["OpaqueRoot"].save_to()
    assert saved["Armor"][0].save_to() == player.tag["Armor"][0].save_to()
    assert [item.save_to() for item in saved["Armor"][4:]] == [item.save_to() for item in player.tag["Armor"][4:]]
    assert all(0 <= item["Slot"].py_data <= 35 for item in saved["Inventory"])
    # Outer item semantics still match when a nested signed-book page is lost.
    book = next(case for case in container_cases if "seed_book" in case)
    field, slot = assignments(container_cases)[book["case_id"]]
    item = next(item for item in saved[field] if item["Slot"].py_data == slot)
    item["tag"]["pages"][0]["text"] = nbt.StringTag("corrupted after reload")
    with pytest.raises(ProbeError, match="page text"):
        verify_player_items(save_player_nbt(nbt.NamedTag(saved)), cases)


@pytest.mark.parametrize("fault", ["player_field", "container", "record", "preserved_item", "body", "clear", "no_op"])
def test_equipment_service_detects_corrupt_production_writes(monkeypatch, synthetic_world, equipment_cases, fault):
    from mcbe_editor.services import BedrockEditorService

    player = fixture_player([], equipment_cases)
    world, key, _before = synthetic_world(player)
    verify_equipment(player.tag, equipment_cases, seed=True)
    original_save = BedrockEditorService.save_player

    def broken_save(self, *args, **kwargs):
        response = original_save(self, *args, **kwargs)
        if bool(response.get("no_op")) != (fault == "no_op"):
            return response
        if fault in {"record", "no_op"}:
            write_records(world, {b"unrelated": b"corrupted"})
        else:
            changed = load_player_nbt(read_records(world)[key])
            if fault == "player_field":
                changed.tag["OpaqueRoot"] = nbt.IntTag(4)
            elif fault == "container":
                changed.tag["Inventory"][0]["Count"] = nbt.ByteTag(2)
            elif fault == "preserved_item":
                changed.tag["Armor"][0]["tag"]["future_probe"] = nbt.LongTag(0)
            elif fault == "body":
                changed.tag["Armor"][4]["OpaqueBody"] = nbt.IntTag(0)
            else:
                changed.tag["Armor"][2] = deepcopy(player.tag["Armor"][2])
            write_records(world, {key: save_player_nbt(changed)})
        return response

    monkeypatch.setattr(BedrockEditorService, "save_player", broken_save)
    with pytest.raises(ProbeError):
        exercise_equipment_service(world, key, equipment_cases)
