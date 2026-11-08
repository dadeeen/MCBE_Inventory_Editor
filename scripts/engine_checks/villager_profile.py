"""Finite, independent expectations for native Vanilla villager persistence."""

from __future__ import annotations

import json
import math
from copy import deepcopy

from .protocol import ProbeError

SUPPLY_IDS = (
    "minecraft:bread",
    "minecraft:carrot",
    "minecraft:potato",
    "minecraft:beetroot",
    "minecraft:wheat",
    "minecraft:wheat_seeds",
    "minecraft:beetroot_seeds",
    "minecraft:torchflower_seeds",
    "minecraft:pitcher_pod",
    "minecraft:bone_meal",
)
STAGES = ("seed", "edited", "revised")
VILLAGER_PREFIX = "MCBE_villager_"


def _plan() -> list[dict]:
    items = [None] * 8
    items[1] = {"name": "minecraft:carrot", "count": 1}
    cases = []

    def append(name, seed_current, edited, revised, edit, revise, *, batch=None):
        case = {
            "case_id": name,
            "name": VILLAGER_PREFIX + name,
            "kind": "control" if edit is None else "health",
            "seed": {"current": seed_current, "maximum": 20, "items": deepcopy(items)},
            "edited": {"current": edited[0], "maximum": edited[1], "items": deepcopy(items)},
            "revised": {"current": revised[0], "maximum": revised[1], "items": deepcopy(items)},
            "edit": edit,
            "revise": revise,
        }
        if batch:
            case["batch"] = batch
        cases.append(case)

    append("control", 20, (20, 20), (20, 20), None, None)
    append("current", 20, (7, 20), (3, 20), {"current_health": 7}, {"current_health": 3})
    append("heal", 6, (20, 20), (5, 20), {"heal": True}, {"current_health": 5})
    append("max_up", 20, (40, 40), (40, 60), {"max_health": 40, "heal": True}, {"max_health": 60})
    append("max_down", 20, (40, 40), (20, 20), {"max_health": 40, "heal": True}, {"max_health": 20})
    append("fractional", 20, (1.5, 20), (20, 20), {"current_health": 1.5}, {"heal": True})
    append("upper", 20, (2048, 2048), (20, 20), {"max_health": 2048, "heal": True}, {"max_health": 20})
    append("max_only", 20, (20, 40), (20, 20), {"max_health": 40}, {"max_health": 20})
    for name in ("batch_a", "batch_b"):
        append(name, 20, (9, 20), (20, 20), {"current_health": 9}, {"heal": True}, batch="health_batch")
    for index, item in enumerate(SUPPLY_IDS):
        seed_items = deepcopy(items)
        seed_items[3] = {"name": "minecraft:bread", "count": 2}
        seed_items[7] = {"name": "minecraft:carrot", "count": 3}
        edited_items = deepcopy(items)
        edited_items[0], edited_items[7] = {"name": item, "count": 1}, {"name": item, "count": 64}
        revised_items = deepcopy(items)
        revised_items[7] = {"name": SUPPLY_IDS[(index + 1) % len(SUPPLY_IDS)], "count": 1}
        cases.append(
            {
                "case_id": f"supply_{index}",
                "name": VILLAGER_PREFIX + f"supply_{index}",
                "kind": "supply",
                "seed": {"current": 20, "maximum": 20, "items": seed_items},
                "edited": {"current": 20, "maximum": 20, "items": edited_items},
                "revised": {"current": 20, "maximum": 20, "items": revised_items},
                "edit": {"inventory": [{"slot": slot, "item": edited_items[slot]} for slot in (0, 3, 7)]},
                "revise": {"inventory": [{"slot": slot, "item": revised_items[slot]} for slot in (0, 7)]},
            }
        )
    for case in cases:
        for stage in STAGES:
            case[stage]["name"] = case["name"]
    for identifier, names in (
        ("name_new", ("", "Egon (Braune Wolle)", "Egons Hof 🌾")),
        ("name_rename", ("Alter Name", "Jörg – Schäfer", "Händler <&> 🐑")),
        ("name_remove", ("Diesen Namen entfernen", "", "Wieder benannt")),
        ("name_limit", ("", "Ä" * 79 + "🌾", "")),
    ):
        cases.append(
            {
                "case_id": identifier,
                "name": VILLAGER_PREFIX + identifier,
                "kind": "name",
                **{stage: {"current": 20, "maximum": 20, "items": deepcopy(items), "name": name} for stage, name in zip(STAGES, names, strict=True)},
                "edit": {"name": names[1]},
                "revise": {"name": names[2]},
            }
        )
    return cases


def make_villager_cases(observations: dict, limits: dict) -> list[dict]:
    for item in SUPPLY_IDS:
        measured = observations.get(item, {}).get("max_amount")
        recorded = limits.get(item)
        if type(measured) is not int or type(recorded) is not int or measured != 64 or recorded != 64:
            raise ProbeError("Villager supplies require every independently planned item and its measured/curated limit of 64")
    return _plan()


def validate_case_plan(cases: list[dict]) -> None:
    try:
        matches = isinstance(cases, list) and json.dumps(cases, sort_keys=True, allow_nan=False) == json.dumps(_plan(), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        matches = False
    if not matches:
        raise ProbeError("Villager manifest omitted or changed its independent planned cases")


def expected_snapshots(cases: list[dict], stage: str) -> dict[str, dict]:
    validate_case_plan(cases)
    if stage not in STAGES:
        raise ProbeError("Unknown villager expectation stage")
    return {case["name"]: deepcopy(case[stage]) for case in cases}


def validate_villager_events(events: list[dict], cases: list[dict], *, stage: str = "seed") -> dict:
    expected = expected_snapshots(cases, stage)
    by_id = {case["case_id"]: case for case in cases}
    seen = set()
    for event in events:
        if event.get("kind") != "case":
            continue
        identifier = event.get("case_id")
        if identifier not in by_id or identifier in seen:
            raise ProbeError("Unexpected or duplicate live villager observation")
        seen.add(identifier)
        actual = event.get("snapshot")
        if not isinstance(actual, dict) or set(actual) != {"type", "current", "maximum", "items", "name"}:
            raise ProbeError("Malformed live villager observation")
        if actual["type"] not in {"minecraft:villager", "minecraft:villager_v2"}:
            raise ProbeError("Observed actor is not a Vanilla villager")
        if any(type(actual[field]) not in (int, float) or not math.isfinite(actual[field]) for field in ("current", "maximum")):
            raise ProbeError("Malformed live villager health")
        items = actual["items"]
        if not isinstance(items, list) or len(items) != 8:
            raise ProbeError("Incomplete live villager inventory")
        if any(item is not None and (not isinstance(item, dict) or set(item) != {"name", "count"} or type(item["count"]) is not int) for item in items):
            raise ProbeError("Malformed live villager supply item")
        if {key: actual[key] for key in ("current", "maximum", "items", "name")} != expected[by_id[identifier]["name"]]:
            raise ProbeError("Engine changed villager name, health or supplies: " + identifier)
    if seen != by_id.keys():
        raise ProbeError("Engine omitted planned villager observations")
    return {"status": "pass", "cases": len(seen), "stage": stage}


def edit_groups(cases: list[dict], action: str) -> list[list[dict]]:
    validate_case_plan(cases)
    if action not in {"edit", "revise"}:
        raise ProbeError("Unknown villager edit action")
    groups = {}
    for case in cases:
        if case[action] is not None:
            groups.setdefault(case.get("batch", case["case_id"]), []).append(case)
    return list(groups.values())
