from __future__ import annotations

import json
from copy import deepcopy
from itertools import combinations

import pytest

from scripts.engine_checks.cases import append_case, expected_snapshot, make_cases
from scripts.engine_checks.extended import (
    DATA_VARIANTS,
    ENCHANTMENT_IDS,
    ENCHANTMENT_NAMES,
    POTION_DATA_VALUES,
    POTION_ITEMS,
    extend_cases,
    matrix_result,
    validate_behavior_events,
)
from scripts.engine_checks.nbt_roundtrip import disk_snapshot
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.runner import ROOT


@pytest.fixture
def measured_matrix():
    db = json.loads((ROOT / "mcbe_editor/resources/item_db.json").read_text(encoding="utf-8"))
    ids = sorted({*DATA_VARIANTS, *POTION_ITEMS.values(), "minecraft:stone", "minecraft:oak_sign", "minecraft:red_cushion", "minecraft:diamond_pickaxe"})
    enchantments = {name: db["enchantments"][str(ENCHANTMENT_IDS[name])][2] for name in ENCHANTMENT_NAMES}
    events = [{"kind": "matrix_registry", "enchantments": enchantments, "effects": list(POTION_DATA_VALUES), "deliveries": list(POTION_ITEMS)}]
    for item_id in ids:
        allowed = ["efficiency", "mending", "unbreaking"] if item_id == "minecraft:diamond_pickaxe" else []
        pairs = [{"left": a, "right": b, "forward": True, "reverse": True} for a, b in combinations(allowed, 2)]
        events.append({"kind": "enchantability", "id": item_id, "allowed": allowed, "pairs": pairs})
    events.extend({"kind": "potion", "effect": effect, "delivery": delivery, "id": item_id}
                  for effect in POTION_DATA_VALUES for delivery, item_id in POTION_ITEMS.items())
    return events, ids, db


@pytest.mark.parametrize("mutation", [
    "missing-item", "missing-potion", "duplicate-potion", "missing-pair", "typed-pair", "level", "new-enchantment", "wrong-potion-id",
])
def test_extended_matrix_never_accepts_missing_or_malformed_domains(measured_matrix, mutation):
    events, ids, db = deepcopy(measured_matrix)
    matrix_result(events, ids, db)
    item = next(event for event in events if event["kind"] == "enchantability" and event["allowed"])
    if mutation == "missing-item":
        events.remove(item)
    elif mutation == "missing-potion":
        events.pop()
    elif mutation == "duplicate-potion":
        events.append(events[-1])
    elif mutation == "missing-pair":
        item["pairs"].pop()
    elif mutation == "typed-pair":
        item["pairs"][0]["forward"] = 1
    elif mutation == "level":
        events[0]["enchantments"]["unbreaking"] += 1
    elif mutation == "new-enchantment":
        events[0]["enchantments"]["future"] = 1
    else:
        events[-1]["id"] = "minecraft:stone"
    with pytest.raises(ProbeError):
        matrix_result(events, ids, db)


def test_extended_plan_covers_levels_pairs_variants_and_metadata_merge_cases(measured_matrix):
    events, ids, db = measured_matrix
    matrix = matrix_result(events, ids, db)
    observations = {item: {"max_amount": db["stack_limits"][item], "max_durability": db["durability"].get(item)} for item in ids}
    cases = make_cases(ids, observations, db["stack_limits"])
    plan = extend_cases(cases, observations, matrix)
    levels = {case["enchantments"][0]["level"] for case in cases
              if case.get("coverage") == "enchantment-level" and case["enchantments"][0]["id"] == "efficiency"}
    assert levels == {1, 2, 3, 4, 5}
    assert plan["counts"]["enchantment_pairs"] == 3
    assert plan["counts"]["potion_variants"] == 2 * len(POTION_DATA_VALUES) * len(POTION_ITEMS)
    assert plan["counts"]["data_variants"] == 2 * sum(len(values) for values in DATA_VARIANTS.values())
    assert plan["counts"]["gameplay_cases"] == 6
    assert all(case["slot"] != 26 for case in cases)
    indexed = {case["case_id"]: case for case in cases}
    assert len(indexed) == len(cases)
    assert any(indexed[pair["left"]]["name"] != indexed[pair["right"]]["name"] for pair in plan["merges"])
    assert any(indexed[pair["left"]]["lore"] != indexed[pair["right"]]["lore"] for pair in plan["merges"])


def test_seeded_enchantments_have_independent_explicit_expectations():
    cases = []
    append_case(cases, {"minecraft:bow": {"max_durability": 384}}, "minecraft:bow", "preserve", 1,
                enchantments=[{"id": "power", "level": 5}], seeded_metadata=True)
    assert expected_snapshot(cases[0], seed=True)["enchantments"] == [{"id": "power", "level": 5}]
    assert expected_snapshot({**cases[0], "mode": "create"}, seed=True) is None


def test_disk_observer_reads_enchantments_and_potion_variants_independently():
    from mcbe_editor import nbt

    enchanted = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:bow"), "Count": nbt.ByteTag(1),
                               "tag": nbt.CompoundTag({"ench": nbt.ListTag([
                                   nbt.CompoundTag({"id": nbt.ShortTag(19), "lvl": nbt.ShortTag(5)})])})})
    case = {"case_id": "bow", "amount": 1, "durable": True}
    assert disk_snapshot(enchanted, case)["enchantments"] == [{"id": "power", "level": 5}]
    enchanted["tag"]["ench"].append(deepcopy(enchanted["tag"]["ench"][0]))
    with pytest.raises(ProbeError, match="duplicate"):
        disk_snapshot(enchanted, case)
    potion = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:splash_potion"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(21)})
    case = {"case_id": "potion", "amount": 1, "data_value": 21, "potion": {"effect": "minecraft:healing", "delivery": "ThrownSplash"}}
    assert disk_snapshot(potion, case)["potion"] == case["potion"]
    potion["Damage"] = nbt.ShortTag(0)
    with pytest.raises(ProbeError, match="variant"):
        disk_snapshot(potion, case)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "failure", "unknown"])
def test_behavior_results_require_every_planned_operation(mutation):
    plan = {"merges": [{"id": "merge"}], "gameplay": [{"id": "hopper"}]}
    events = [{"kind": "behavior", "id": key, "passed": True} for key in ("merge", "hopper")]
    validate_behavior_events(events, plan)
    if mutation == "missing":
        events.pop()
    elif mutation == "duplicate":
        events.append(events[0])
    elif mutation == "failure":
        events[0]["passed"] = False
    else:
        events[0]["id"] = "unknown"
    with pytest.raises(ProbeError):
        validate_behavior_events(events, plan)
