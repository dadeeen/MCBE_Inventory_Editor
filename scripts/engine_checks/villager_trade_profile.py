"""Independent finite cases for native trade regeneration and tier persistence.

This is an opt-in engine profile, not a claim about completed engine runs.
No expected profession or experience threshold is imported from the editor.
"""

from __future__ import annotations

import json
from copy import deepcopy

from .protocol import ProbeError

PROFESSIONS = (
    "farmer",
    "fisherman",
    "shepherd",
    "fletcher",
    "librarian",
    "cartographer",
    "cleric",
    "armorer",
    "weaponsmith",
    "toolsmith",
    "butcher",
    "leatherworker",
    "mason",
)
EXPERIENCE = (0, 10, 70, 150, 250)
STAGES = ("seed", "edited", "revised")


def make_trade_cases() -> list[dict]:
    cases = []

    def append(identifier, source, target, tier, revised_profession, revised_tier, *, control=False):
        name = "MCBE_trade_" + identifier
        first_experience = EXPERIENCE[tier]
        revised_experience = max(EXPERIENCE[revised_tier], 1 if revised_tier == 0 and first_experience > 0 else 0)
        if revised_profession != target:
            revised_experience = EXPERIENCE[revised_tier]
        case = {
            "case_id": identifier,
            "name": name,
            "kind": "control" if control else "profession" if source != target else "tier",
            "seed": {"profession": source, "tier": 0, "experience": 0},
            "edited": {"profession": target, "tier": tier, "experience": first_experience},
            "revised": {"profession": revised_profession, "tier": revised_tier, "experience": revised_experience},
            "edit": None if control else {"career": {"profession": target, "trade_tier": tier}},
            "revise": None if control else {"career": {"profession": revised_profession, "trade_tier": revised_tier}},
        }
        for stage in STAGES:
            case[stage].update(current=20, maximum=20, items=[None] * 8, name=name)
        cases.append(case)

    append("control", "farmer", "farmer", 0, "farmer", 0, control=True)
    for index, target in enumerate(PROFESSIONS):
        append("profession_" + target, PROFESSIONS[(index + 1) % len(PROFESSIONS)], target, index % 5, target, (index + 1) % 5)
    for tier in range(1, 5):
        append("tier_" + str(tier), "farmer", "farmer", tier, "farmer", 0)
    append("unemployed", "farmer", "unemployed", 0, "farmer", 4)
    return cases


def validate_trade_plan(cases: list[dict]) -> None:
    try:
        valid = isinstance(cases, list) and json.dumps(cases, sort_keys=True, allow_nan=False) == json.dumps(make_trade_cases(), sort_keys=True)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ProbeError("Trade cases differ from the independent complete plan")


def validate_trade_events(events: list[dict], cases: list[dict], *, stage: str) -> dict:
    """Live probes establish identity/health/supplies; offers are a disk oracle.

    The stable Script API does not expose the trade UI. This observer must never
    pretend that an emitted case event proves recipe contents or a purchase.
    """
    validate_trade_plan(cases)
    if stage not in STAGES:
        raise ProbeError("Unknown trade expectation stage")
    expected = {case["case_id"]: {key: deepcopy(case[stage][key]) for key in ("current", "maximum", "items", "name")} for case in cases}
    seen = set()
    for event in events:
        if event.get("kind") != "case":
            continue
        identifier, actual = event.get("case_id"), event.get("snapshot")
        if identifier not in expected or identifier in seen or not isinstance(actual, dict):
            raise ProbeError("Unexpected or duplicate live trade actor")
        seen.add(identifier)
        if set(actual) != {"type", "current", "maximum", "items", "name"} or actual["type"] != "minecraft:villager_v2":
            raise ProbeError("Malformed live trade actor")
        if {key: value for key, value in actual.items() if key != "type"} != expected[identifier]:
            raise ProbeError("Engine changed untouched trade actor name, health or supplies")
    if seen != set(expected):
        raise ProbeError("Engine omitted planned trade actors")
    return {"status": "pass", "cases": len(seen), "stage": stage}
