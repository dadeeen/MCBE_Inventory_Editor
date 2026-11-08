"""Independent harness corruption checks; synthetic fixtures are not BDS evidence."""

from copy import deepcopy
import json
import struct

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from scripts.engine_checks import villager_worker as worker
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.villager_profile import SUPPLY_IDS, expected_snapshots, make_villager_cases, validate_case_plan, validate_villager_events


@pytest.fixture
def villager_cases():
    return make_villager_cases({name: {"max_amount": 64} for name in SUPPLY_IDS}, dict.fromkeys(SUPPLY_IDS, 64))


def synthetic_records(cases, stage="seed", *, tagged=True):
    """Native-shaped doubles with real typed sparse health, independently encoded."""
    records = {b"unrelated-world-record": b"opaque\xff\x00"}
    for index, case in enumerate(cases):
        snapshot = case[stage]
        suffix = struct.pack("<Q", index + 1)
        position = [(index % 5) * 8 + 2.5, 81, (index // 5) * 8 + 2.5]
        health = nbt.CompoundTag(
            {
                "Name": nbt.StringTag("minecraft:health"),
                "Base": nbt.FloatTag(20),
                "DefaultMax": nbt.FloatTag(snapshot["maximum"]),
                "DefaultMin": nbt.FloatTag(0),
            }
        )
        if snapshot["current"] != 20 or stage != "seed":
            health["Current"] = nbt.FloatTag(snapshot["current"])
        if stage != "seed":
            health["Max"] = nbt.FloatTag(snapshot["maximum"])
        items = []
        for slot, item in enumerate(snapshot["items"]):
            items.append(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(slot),
                        "Name": nbt.StringTag(item["name"] if item else ""),
                        "Count": nbt.ByteTag(item["count"] if item else 0),
                        "Damage": nbt.ShortTag(0),
                        "WasPickedUp": nbt.ByteTag(slot % 2),
                    }
                )
            )
        root = nbt.CompoundTag(
            {
                "identifier": nbt.StringTag("minecraft:villager_v2"),
                "CustomName": nbt.StringTag(snapshot["name"]),
                **({"Tags": nbt.ListTag([nbt.StringTag(case["name"])])} if tagged else {}),
                "UniqueID": nbt.LongTag(2**54 + index),
                "Pos": nbt.ListTag([nbt.FloatTag(value) for value in position]),
                "Variant": nbt.IntTag(0),
                "MarkVariant": nbt.IntTag(1),
                "TradeTier": nbt.IntTag(0),
                "TradeExperience": nbt.IntTag(0),
                "Offers": nbt.CompoundTag({"Recipes": nbt.ListTag([], list_data_type=10)}),
                "Armor": nbt.ListTag([], list_data_type=10),
                "Mainhand": nbt.ListTag([], list_data_type=10),
                "Offhand": nbt.ListTag([], list_data_type=10),
                "ChestItems": nbt.ListTag(items),
                "Attributes": nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag("minecraft:movement"), "Base": nbt.FloatTag(0.5)}), health]),
                "internalComponents": nbt.CompoundTag(
                    {"EntityStorageKeyComponent": nbt.CompoundTag({"StorageKey": nbt.StringTag(nbt.utf8_escape_decoder(suffix))})}
                ),
            }
        )
        records[b"actorprefix" + suffix] = save_player_nbt(nbt.NamedTag(root))
        reference = b"digp" + struct.pack("<ii", int(position[0] // 16), int(position[2] // 16))
        records[reference] = records.get(reference, b"") + suffix
    return records


def mutate_actor(records, change, *, index=0):
    key = b"actorprefix" + struct.pack("<Q", index + 1)
    named = load_player_nbt(records[key])
    change(named.tag)
    records[key] = save_player_nbt(named)


def test_villager_plan_is_complete_independent_and_uses_supported_boundaries(villager_cases):
    assert len(villager_cases) == 24
    assert sum(case["kind"] == "health" for case in villager_cases) == 9
    assert sum(case["kind"] == "supply" for case in villager_cases) == 10
    assert {case["edited"]["current"] for case in villager_cases} >= {1.5, 7, 9, 20, 40, 2048}
    supplies = [case for case in villager_cases if case["kind"] == "supply"]
    assert {case["edited"]["items"][7]["name"] for case in supplies} == set(SUPPLY_IDS)
    assert all(case["edited"]["items"][0]["count"] == 1 and case["edited"]["items"][7]["count"] == 64 for case in supplies)
    assert all(case["revised"]["items"][0] is None and case["revised"]["items"][7]["count"] == 1 for case in supplies)


@pytest.mark.parametrize("fault", ["missing", "changed", "boolean", "float"])
def test_villager_plan_requires_every_measured_and_curated_supply(fault):
    observations, limits = {name: {"max_amount": 64} for name in SUPPLY_IDS}, dict.fromkeys(SUPPLY_IDS, 64)
    if fault == "missing":
        observations.pop(SUPPLY_IDS[-1])
    else:
        limits[SUPPLY_IDS[-1]] = {"changed": 16, "boolean": True, "float": 64.0}[fault]
    with pytest.raises(ProbeError):
        make_villager_cases(observations, limits)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "boolean", "float", "nan"])
def test_case_manifest_cannot_silently_shrink_or_change_primitive_types(villager_cases, fault):
    validate_case_plan(villager_cases)
    altered = deepcopy(villager_cases)
    if fault == "missing":
        altered.pop()
    elif fault == "duplicate":
        altered[-1] = altered[0]
    else:
        altered[0]["seed"]["items"][1]["count"] = {"boolean": True, "float": 1.0, "nan": float("nan")}[fault]
    with pytest.raises(ProbeError):
        validate_case_plan(altered)


@pytest.mark.parametrize("stage", ["seed", "edited", "revised"])
@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_type", "health", "item", "boolean_count", "extra_slot", "name"])
def test_live_villager_observer_rejects_incomplete_or_corrupt_engine_evidence(villager_cases, stage, fault):
    events = [{"kind": "case", "case_id": case["case_id"], "snapshot": {"type": "minecraft:villager_v2", **deepcopy(case[stage])}} for case in villager_cases]
    assert validate_villager_events(events, villager_cases, stage=stage)["cases"] == 24
    if fault == "name":
        events[0]["snapshot"]["name"] = "Wrong name"
    elif fault == "missing":
        events.pop()
    elif fault == "duplicate":
        events.append(deepcopy(events[0]))
    elif fault == "wrong_type":
        events[0]["snapshot"]["type"] = "minecraft:zombie"
    elif fault == "health":
        events[0]["snapshot"]["current"] = 19
    elif fault == "item":
        events[0]["snapshot"]["items"][1]["name"] = "minecraft:bread"
    elif fault == "boolean_count":
        events[0]["snapshot"]["items"][1]["count"] = True
    else:
        events[0]["snapshot"]["items"].append(None)
    with pytest.raises(ProbeError):
        validate_villager_events(events, villager_cases, stage=stage)


@pytest.mark.parametrize(
    "fault",
    [
        "current",
        "max",
        "missing_base",
        "wrong_base_type",
        "wrong_current_type",
        "nan",
        "duplicate_attribute",
        "count",
        "slot",
        "damage",
        "pickup",
        "missing_actor",
        "uid",
        "storage_key",
        "index_missing",
        "index_duplicate",
        "index_chunk",
        "index_dimension",
        "index_trailing",
        "position",
    ],
)
def test_native_disk_oracle_rejects_sparse_health_inventory_and_identity_corruption(villager_cases, fault):
    records = synthetic_records(villager_cases)
    expected = expected_snapshots(villager_cases, "seed")
    baseline = worker.verify_records(records, villager_cases, expected)["baselines"]
    altered = dict(records)
    if fault == "missing_actor":
        altered.pop(b"actorprefix" + struct.pack("<Q", 1))
    elif fault.startswith("index_"):
        key = b"digp" + struct.pack("<ii", 0, 0)
        suffix = struct.pack("<Q", 1)
        if fault == "index_missing":
            altered[key] = altered[key][8:]
        elif fault == "index_duplicate":
            altered[key] += suffix
        elif fault == "index_chunk":
            altered[key] = altered[key][8:]
            altered[b"digp" + struct.pack("<ii", 100, 100)] = suffix
        elif fault == "index_dimension":
            altered[key] = altered[key][8:]
            altered[key + struct.pack("<i", 1)] = suffix
        else:
            altered[key] += b"x"
    else:

        def change(root):
            health = worker.health_attribute(root)
            if fault == "current":
                health["Current"] = nbt.FloatTag(1)
            elif fault == "max":
                health["Max"] = nbt.FloatTag(21)
            elif fault == "missing_base":
                del health["Base"]
            elif fault == "wrong_base_type":
                health["Base"] = nbt.IntTag(20)
            elif fault == "wrong_current_type":
                health["Current"] = nbt.IntTag(20)
            elif fault == "nan":
                health["Current"] = nbt.FloatTag(float("nan"))
            elif fault == "duplicate_attribute":
                root["Attributes"].append(deepcopy(health))
            elif fault == "count":
                root["ChestItems"][1]["Count"] = nbt.ByteTag(2)
            elif fault == "slot":
                root["ChestItems"][1]["Slot"] = nbt.ByteTag(0)
            elif fault == "damage":
                root["ChestItems"][1]["Damage"] = nbt.ShortTag(1)
            elif fault == "pickup":
                root["ChestItems"][1]["WasPickedUp"] = nbt.ByteTag(2)
            elif fault == "uid":
                root["UniqueID"] = nbt.LongTag(0)
            elif fault == "storage_key":
                root["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"] = nbt.StringTag("wrong")
            else:
                root["Pos"][0] = nbt.FloatTag(100)

        mutate_actor(altered, change)
    with pytest.raises(ProbeError):
        worker.verify_records(altered, villager_cases, expected, baseline)


@pytest.mark.parametrize(
    "field", ["Variant", "MarkVariant", "Armor", "Mainhand", "Offhand", "TradeTier", "TradeExperience", "Offers", "health_base", "other_attribute"]
)
def test_saved_readonly_villager_fields_remain_part_of_the_oracle(villager_cases, field):
    records = synthetic_records(villager_cases)
    expected = expected_snapshots(villager_cases, "seed")
    baseline = worker.verify_records(records, villager_cases, expected)["baselines"]

    def change(root):
        if field == "health_base":
            worker.health_attribute(root)["Base"] = nbt.FloatTag(19)
            worker.health_attribute(root)["Current"] = nbt.FloatTag(20)
        elif field == "other_attribute":
            root["Attributes"][0]["Base"] = nbt.FloatTag(1)
        else:
            root[field] = nbt.StringTag("changed")

    mutate_actor(records, change)
    with pytest.raises(ProbeError, match="untouched"):
        worker.verify_records(records, villager_cases, expected, baseline)


def test_only_first_warmup_can_accept_engine_offers_initialization(villager_cases):
    records = synthetic_records(villager_cases)
    expected = expected_snapshots(villager_cases, "seed")
    baseline = worker.verify_records(records, villager_cases, expected)["baselines"]
    mutate_actor(records, lambda root: root["Offers"].update({"engine_initialization": nbt.IntTag(1)}))
    with pytest.raises(ProbeError, match="untouched"):
        worker.verify_records(records, villager_cases, expected, baseline)
    initialized = worker.verify_records(records, villager_cases, expected, baseline, initialize_offers=True)
    assert len(initialized["initialization_changes"]) == 1
    worker.verify_records(records, villager_cases, expected, initialized["baselines"])
    mutate_actor(records, lambda root: root["Offers"].update({"engine_initialization": nbt.IntTag(2)}))
    with pytest.raises(ProbeError, match="untouched"):
        worker.verify_records(records, villager_cases, expected, initialized["baselines"])
    mutate_actor(records, lambda root: root.update({"Variant": nbt.IntTag(2)}))
    with pytest.raises(ProbeError, match="untouched"):
        worker.verify_records(records, villager_cases, expected, baseline, initialize_offers=True)


@pytest.fixture
def villager_run(tmp_path, villager_cases):
    from mcbe_editor.leveldb_writer import LevelDbWriter
    from scripts.engine_checks.runner import WORLD_NAME, sha256, source_hashes, write_json

    world = tmp_path / "server/worlds" / WORLD_NAME
    (world / "db").mkdir(parents=True)
    (world / "level.dat").write_bytes(b"synthetic fixture world metadata")
    (world / "levelname.txt").write_text("Synthetic villager harness", encoding="utf-8")
    db = LevelDbWriter(str(world / "db"))
    try:
        db.put_batch(synthetic_records(villager_cases))
    finally:
        db.close()
    write_json(tmp_path / "cases.json", villager_cases)
    write_json(tmp_path / "catalog.json", {"synthetic_test_catalog": True})
    report = {
        "format": "mcbe-engine-check-v1",
        "suite": "villagers",
        "run_id": "a" * 32,
        "phases": {"seed": "pass"},
        "editor": source_hashes(),
        "cases_sha256": sha256(tmp_path / "cases.json"),
        "catalog_sha256": sha256(tmp_path / "catalog.json"),
    }
    write_json(tmp_path / "run.json", report)
    return tmp_path, world, report


def test_worker_exercises_real_service_backups_noops_and_revisions_on_native_shaped_doubles(villager_run):
    from scripts.engine_checks.runner import write_json

    directory, _world, report = villager_run
    assert worker.run(directory, "seed")["cases"] == 24
    with pytest.raises(ProbeError, match="once"):
        worker.run(directory, "seed")
    with pytest.raises(ProbeError, match="out of order"):
        worker.run(directory, "edit")
    worker.run(directory, "warmup1")
    worker.run(directory, "warmup2")
    edited = worker.run(directory, "edit")
    assert {key: edited[key] for key in ("backed_up_saves", "no_op_checks", "stale_revision_rejections", "changed_actors")} == {
        "backed_up_saves": 22,
        "no_op_checks": 22,
        "stale_revision_rejections": 22,
        "changed_actors": 23,
    }
    worker.run(directory, "verify")
    with pytest.raises(ProbeError, match="two verified"):
        worker.run(directory, "revise")
    report["phases"].update(reload1="pass", reload2="pass")
    write_json(directory / "run.json", report)
    revised = worker.run(directory, "revise")
    assert revised["backed_up_saves"] == revised["stale_revision_rejections"] == 1
    assert revised["no_op_checks"] == 22 and revised["central_workspace"] is True
    worker.run(directory, "verify")
    with pytest.raises(ProbeError, match="precede"):
        worker.run(directory, "warmup1")


@pytest.mark.parametrize("fault", ["cases_hash", "catalog_hash", "source_hash", "seed_missing", "wrong_suite", "wrong_run_id"])
def test_worker_rejects_unbound_inputs_before_opening_the_database(villager_run, monkeypatch, fault):
    from scripts.engine_checks.runner import write_json

    directory, _world, report = villager_run
    if fault == "cases_hash":
        report["cases_sha256"] = "bad"
    elif fault == "catalog_hash":
        report["catalog_sha256"] = "bad"
    elif fault == "source_hash":
        report["editor"]["editor_source_sha256"] = "bad"
    elif fault == "seed_missing":
        report["phases"]["seed"] = "running"
    elif fault == "wrong_suite":
        report["suite"] = "items"
    else:
        report["run_id"] = "not-a-run"
    write_json(directory / "run.json", report)
    monkeypatch.setattr(worker, "_read_records", lambda *_: pytest.fail("Invalid input reached database reader"))
    with pytest.raises(ProbeError):
        worker.run(directory, "seed")


def test_villager_reload_script_observes_without_reconstructing_or_repairing(villager_cases):
    from tests.node_runner import run_node

    run_node(
        "const cases = "
        + json.dumps(villager_cases)
        + ";\n"
        + r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('scripts/engine_checks/pack/scripts/villagers.js', 'utf8')
    .replace(/^import .*;\s*/m, '').replace('export function* ', 'function* ');
for (const phase of ['warmup1','warmup2','reload1','reload2','reload3','reload4']) {
    const fail = () => { throw new Error('Reload attempted mutation'); };
    const entities = cases.map(test => ({nameTag:test.seed.name,hasTag:tag=>tag===test.name,typeId:'minecraft:villager_v2',
        getComponent(id) {
            if(id === 'minecraft:health') return {currentValue:test.seed.current,effectiveMax:20,setCurrentValue:fail};
            return {container:{size:8,setItem:fail,getItem:slot=>{
                const item=test.seed.items[slot]; return item?{typeId:item.name,amount:item.count}:undefined;
            }}};
        }}));
    const world={getDimension:()=>({getEntities:()=>entities,spawnEntity:fail,runCommand:fail,getBlock:fail})};
    const probe=new Function('ItemStack','world',source+'; return villagerRoundtrip;')(fail,world);
    const events=[];
    for(const _ of probe({phase,cases},(kind,fields)=>events.push({kind,...fields}))) {}
    assert.equal(events.length,cases.length);
    assert.deepEqual(events.map(event=>event.case_id),cases.map(test=>test.case_id));
}
"""
    )


@pytest.mark.parametrize("fault", ["name", "name_type", "name_missing", "tag_missing", "tag_duplicate", "extra_identity"])
def test_native_name_and_test_identity_corruption_cannot_pass(villager_cases, fault):
    records = synthetic_records(villager_cases)
    expected = expected_snapshots(villager_cases, "seed")
    baseline = worker.verify_records(records, villager_cases, expected)["baselines"]

    def corrupt(root):
        if fault == "name":
            root["CustomName"] = nbt.StringTag("Unplanned name")
        elif fault == "name_type":
            root["CustomName"] = nbt.IntTag(1)
        elif fault == "name_missing":
            del root["CustomName"]
        elif fault == "tag_missing":
            del root["Tags"]
        elif fault == "tag_duplicate":
            root["Tags"].append(nbt.StringTag(villager_cases[0]["name"]))
        else:
            root["Tags"].append(nbt.StringTag(villager_cases[1]["name"]))

    mutate_actor(records, corrupt)
    with pytest.raises(ProbeError):
        worker.verify_records(records, villager_cases, expected, baseline)
