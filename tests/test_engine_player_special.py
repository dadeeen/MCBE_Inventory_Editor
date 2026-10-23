"""Synthetic harness regressions; these tests do not start BDS or a client."""

from copy import deepcopy
import json

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.db import LevelDbAdapter
from scripts.engine_checks.cases import expected_snapshot
from scripts.engine_checks.client_profile import player_items
from scripts.engine_checks.extended import ENCHANTMENT_IDS
from scripts.engine_checks.nbt_roundtrip import carriers, disk_snapshot, indexed_items, read_records, run
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.runner import ROOT, WORLD_NAME, sha256, write_json
from scripts.engine_checks.service_profile import assignments, make_service_cases
from tests.test_engine_checks import synthetic_carriers
from tests.test_engine_players import synthetic_player

PLAYER_KEY = b"player_server_special_probe"


@pytest.fixture
def player_cases():
    catalog = json.loads((ROOT / "mcbe_editor/resources/item_db.json").read_text(encoding="utf-8"))
    observations = {item: {"max_amount": limit, "max_durability": catalog["durability"].get(item)} for item, limit in catalog["stack_limits"].items()}
    return make_service_cases(observations, catalog["stack_limits"], catalog["enchantments"])


def seed_carriers(cases):
    """Typed test doubles for engine-created originals, including signed books."""
    records = synthetic_carriers(cases)
    found = carriers(records, {case["carrier"] for case in cases})
    for case in cases:
        snapshot = expected_snapshot(case, seed=True)
        if snapshot is None:
            continue
        _key, actor, field = found[case["carrier"]]
        item = indexed_items(actor.tag[field])[case["slot"]]
        item["Damage"] = nbt.ShortTag(case.get("data_value", 0))
        tag = item["tag"]
        tag["display"] = nbt.CompoundTag({"Name": nbt.StringTag(snapshot["name"]), "Lore": nbt.ListTag([nbt.StringTag(line) for line in snapshot["lore"]], 8)})
        if case["durable"]:
            tag["Damage"] = nbt.IntTag(snapshot["damage"])
        tag["ench"] = nbt.ListTag(
            [nbt.CompoundTag({"id": nbt.ShortTag(ENCHANTMENT_IDS[row["id"]]), "lvl": nbt.ShortTag(row["level"])}) for row in snapshot["enchantments"]], 10
        )
    for key, actor, _field in found.values():
        records[key] = save_player_nbt(actor)
    return records


def write_records(world, records):
    database = LevelDbAdapter(str(world / "db"))
    try:
        database.put_batch(records)
    finally:
        database.close()


def prepare_run(run_dir, cases, suite):
    world = run_dir / "server" / "worlds" / WORLD_NAME
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text("Synthetic nonplayable fixture", encoding="utf-8")
    records = seed_carriers(cases)
    if suite == "client":
        player = synthetic_player([])
        sources = carriers(records, {case["carrier"] for case in cases})
        locations = assignments(cases)
        for case in cases:
            if case["mode"] == "create":
                continue
            _key, actor, source_field = sources[case["carrier"]]
            item = deepcopy(indexed_items(actor.tag[source_field])[case["slot"]])
            field, slot = locations[case["case_id"]]
            item["Slot"] = nbt.ByteTag(slot)
            player.tag[field].append(item)
        # Root equipment is deliberately present. The normal container flow
        # must not select its virtual UI slots as move/delete candidates.
        empty = nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0)})
        helmet = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:diamond_helmet"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
        shield = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:shield"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
        player.tag["Armor"] = nbt.ListTag([helmet, *(deepcopy(empty) for _ in range(3))], 10)
        player.tag["Offhand"] = nbt.ListTag([shield], 10)
        records = {PLAYER_KEY: save_player_nbt(player), b"unrelated": records[b"unrelated"]}
    write_records(world, records)
    write_json(run_dir / "cases.json", cases)
    write_json(
        run_dir / "run.json",
        {"format": "mcbe-engine-check-v1", "suite": suite, "phases": {"seed": "pass"}, "cases_sha256": sha256(run_dir / "cases.json")},
    )
    return world


def stored_case(records, cases, profile, suite):
    case = next(case for case in cases if case.get("profile") == profile)
    if suite == "client":
        key = PLAYER_KEY
        named = load_player_nbt(records[key])
        field, slot = assignments(cases)[case["case_id"]]
        item = player_items(named.tag, field)[slot]
    else:
        key, named, field = carriers(records, {case["carrier"]})[case["carrier"]]
        item = indexed_items(named.tag[field])[case["slot"]]
    return case, key, named, item


def corrupt_contents(item, profile):
    if profile == "bundle_mixed_63":
        item["tag"]["bundle_weight"] = nbt.IntTag(4)
    elif profile == "shulker_nested":
        bundle = next(child for child in item["tag"]["Items"] if child["Slot"].py_data == 26)
        book = next(child for child in bundle["tag"]["storage_item_component_content"] if child["Slot"].py_data == 63)
        book["tag"]["pages"][0]["text"] = nbt.StringTag("lost nested content")
    else:
        item["tag"]["pages"].pop(1)


def test_special_profile_is_bounded_and_keeps_assignments_stable_with_equipment(player_cases):
    special = [case for case in player_cases if "special_edit" in case]
    assert [case["profile"] for case in special] == ["bundle_mixed_63", "shulker_nested", "book_signed"]
    assert len(player_cases) == 48
    assert len({case["case_id"] for case in player_cases}) == 48
    assert len({(case["carrier"], case["slot"]) for case in player_cases}) == 48
    assert all("revision" not in case for case in special)
    planned = assignments(player_cases)
    assert len(set(planned.values())) == 48
    assert all(location not in {("Inventory", 34), ("EnderChestInventory", 25)} for location in planned.values())
    interleaved = [dict(case_id="equipment_head", equipment_slot="Head"), *player_cases[:13], dict(case_id="equipment_offhand", equipment_slot="Offhand")]
    interleaved.extend(player_cases[13:])
    assert assignments(interleaved) == planned


@pytest.mark.parametrize("suite,players", [("service", 2), ("client", 1)])
def test_service_and_client_workers_check_special_contents_without_additional_phases(tmp_path, player_cases, suite, players):
    world = prepare_run(tmp_path, player_cases, suite)
    before = read_records(world)
    result = run(tmp_path, "edit")
    assert result["cases"] == 48
    assert result["player_service"]["special_content_cases"] == 3
    assert result["player_service"]["backed_up_saves"] == 5 * players
    assert result["player_service"]["intermediate_state_checks"] == 5 * players
    assert run(tmp_path, "verify")["status"] == "pass"
    assert read_records(world)[b"unrelated"] == before[b"unrelated"]
    if suite == "client":
        original = load_player_nbt(before[PLAYER_KEY]).tag
        current = load_player_nbt(read_records(world)[PLAYER_KEY]).tag
        assert all(current[field].save_to() == original[field].save_to() for field in ("Armor", "Offhand", "Opaque"))


@pytest.mark.parametrize("keep_display", [False, True])
def test_client_signed_book_uses_title_without_hiding_lost_custom_name(tmp_path, player_cases, keep_display):
    world = prepare_run(tmp_path, player_cases, "client")
    case, key, named, item = stored_case(read_records(world), player_cases, "book_signed", "client")
    if keep_display:
        del item["tag"]["display"]["Name"]
    else:
        del item["tag"]["display"]
    write_records(world, {key: save_player_nbt(named)})
    assert disk_snapshot(item, case) == expected_snapshot(case, seed=True)
    assert run(tmp_path, "edit")["status"] == "pass"
    assert run(tmp_path, "verify")["status"] == "pass"

    case, key, named, item = stored_case(read_records(world), player_cases, "book_signed", "client")
    assert item["tag"]["display"]["Name"].py_data == case["name"]
    assert item["tag"]["title"].py_data != case["name"]
    del item["tag"]["display"]["Name"]
    write_records(world, {key: save_player_nbt(named)})
    with pytest.raises(ProbeError, match="semantics"):
        run(tmp_path, "verify")


@pytest.mark.parametrize("suite", ["service", "client"])
@pytest.mark.parametrize("profile", ["bundle_mixed_63", "shulker_nested", "book_signed"])
def test_worker_rejects_special_content_loss_even_when_outer_item_snapshot_is_unchanged(tmp_path, player_cases, suite, profile):
    world = prepare_run(tmp_path, player_cases, suite)
    assert run(tmp_path, "edit")["status"] == "pass"
    assert run(tmp_path, "verify")["status"] == "pass"
    case, key, named, item = stored_case(read_records(world), player_cases, profile, suite)
    outer = disk_snapshot(item, case)
    corrupt_contents(item, profile)
    assert disk_snapshot(item, case) == outer
    write_records(world, {key: save_player_nbt(named)})
    with pytest.raises(ProbeError, match="Special NBT changed"):
        run(tmp_path, "verify")


def test_initial_service_write_cannot_freeze_corrupted_special_contents_as_expected(tmp_path, monkeypatch, player_cases):
    from mcbe_editor.services import BedrockEditorService

    # Establish the unchanged fixture first; the injected failure must be the
    # reason for rejecting the second run, not an unrelated malformed seed.
    prepare_run(tmp_path / "baseline", player_cases, "client")
    assert run(tmp_path / "baseline", "edit")["status"] == "pass"
    run_dir = tmp_path / "fault"
    world = prepare_run(run_dir, player_cases, "client")
    real_save = BedrockEditorService.save_player
    writes = 0

    def broken_save(*args, **kwargs):
        nonlocal writes
        result = real_save(*args, **kwargs)
        if result.get("success") and not result.get("no_op"):
            writes += 1
            if writes == 1:
                _case, key, named, item = stored_case(read_records(world), player_cases, "book_signed", "client")
                corrupt_contents(item, "book_signed")
                write_records(world, {key: save_player_nbt(named)})
        return result

    monkeypatch.setattr(BedrockEditorService, "save_player", broken_save)
    with pytest.raises(ProbeError, match="Special NBT changed"):
        run(run_dir, "edit")
    assert writes == 1
