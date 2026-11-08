"""Fail-closed evidence for a natural village and genuine client gameplay."""

from __future__ import annotations

import json
import math
from copy import deepcopy

from .protocol import ProbeError

ROLES = ("farmer", "injured", "control")
PHASES = ("seed", "reload1", "reload2")
CASE_IDS = ("before", "trade", "pickup", "after", "chunk_reload")


def make_village_plan() -> dict:
    """The coordinates are measured with /locate in BDS 1.26.61.1."""
    return {
        "format": "mcbe-natural-village-v1",
        "seed": "9172026",
        "trade": {"emerald": 1, "bread": 6},
        "workstation": "minecraft:composter",
        "center": {"x": -232, "y": 67, "z": 840},
        "booths": {"farmer": {"x": -232, "y": 96, "z": 840}, "injured": {"x": -220, "y": 96, "z": 840}, "control": {"x": -244, "y": 96, "z": 840}},
        "names": {role: "MCBE_village_" + role for role in ROLES},
        "landmarks": [
            {"type": "minecraft:bed", "position": {"x": -231, "y": 71, "z": 845}},
            {"type": "minecraft:composter", "position": {"x": -255, "y": 65, "z": 805}},
        ],
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def validate_village_plan(plan: dict) -> None:
    try:
        same = json.dumps(plan, sort_keys=True, allow_nan=False) == json.dumps(make_village_plan(), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        same = False
    require(same, "Natural village plan changed or is incomplete")


def _integer(value, minimum=0) -> bool:
    return type(value) is int and value >= minimum


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_actor_snapshots(actors: dict, *, edited: bool) -> None:
    require(isinstance(actors, dict) and set(actors) == set(ROLES), "Incomplete natural resident observations")
    identities = set()
    for role, actor in actors.items():
        require(isinstance(actor, dict) and set(actor) == {"identity", "type", "current", "maximum", "variant", "items"}, "Malformed village actor observation")
        require(isinstance(actor["identity"], str) and actor["identity"] and actor["identity"] not in identities, "Missing or duplicate natural identity")
        identities.add(actor["identity"])
        require(actor["type"] in {"minecraft:villager", "minecraft:villager_v2"}, "Natural actor is not a villager")
        require(_number(actor["current"]) and _number(actor["maximum"]), "Malformed natural health")
        health = (40, 40) if edited and role == "injured" else (6, 20) if role == "injured" else (20, 20)
        require((actor["current"], actor["maximum"]) == health, "Natural villager health differs from the independent plan")
        require(_integer(actor["variant"]) and actor["variant"] <= 14, "Unknown natural profession")
        require(role != "farmer" or actor["variant"] == 1, "Natural farmer changed profession")
        items = actor["items"]
        require(isinstance(items, list) and len(items) == 8, "Natural supplies need eight slots")
        for item in items:
            require(
                item is None
                or (
                    isinstance(item, dict)
                    and set(item) == {"name", "count"}
                    and isinstance(item["name"], str)
                    and item["name"].startswith("minecraft:")
                    and _integer(item["count"], 1)
                    and item["count"] <= 64
                ),
                "Malformed natural supply item",
            )


def _player(value: dict) -> None:
    require(
        isinstance(value, dict) and set(value) == {"emerald", "bread", "carrot"} and all(_integer(count) for count in value.values()),
        "Malformed client resources",
    )


def _position(position: dict, plan: dict) -> None:
    require(
        isinstance(position, dict) and set(position) == {"x", "y", "z"} and all(_number(value) for value in position.values()),
        "Invalid natural position",
    )
    require(sum((position[key] - plan["center"][key]) ** 2 for key in position) <= 180**2, "Natural actor lies outside the generated village")


def _chunk_evidence(chunks: list, plan: dict) -> None:
    roles = (*ROLES, *("landmark_" + str(index) for index in range(len(plan["landmarks"]))))
    require(isinstance(chunks, list) and len(chunks) == len(roles), "Incomplete native chunk observations")
    require(
        all(isinstance(probe, dict) and set(probe) == {"role", "position", "before", "away", "returned"} for probe in chunks),
        "Malformed native chunk observations",
    )
    require(tuple(probe["role"] for probe in chunks) == roles, "Missing or duplicate actor/landmark chunk observation")
    for probe in chunks:
        _position(probe["position"], plan)
        require(probe["before"] is True and probe["away"] is False and probe["returned"] is True, "Native chunks did not demonstrate loaded-unloaded-loaded")
        if probe["role"].startswith("landmark_"):
            index = int(probe["role"].removeprefix("landmark_"))
            require(probe["position"] == plan["landmarks"][index]["position"], "Wrong natural landmark chunk was observed")


def _carrots(items: list) -> int:
    return sum(item["count"] for item in items if item and item["name"] == "minecraft:carrot")


def same_persisted_actor(actual: dict, expected: dict, role: str) -> bool:
    """Native controls may change jobs; edited health and supplies stay exact."""
    if any(actual[key] != expected[key] for key in ("identity", "type", "current", "maximum")):
        return False
    if role == "farmer":
        return actual["variant"] == expected["variant"] and _carrots(actual["items"]) == _carrots(expected["items"])
    return actual["items"] == expected["items"]


def validate_village_events(events: list[dict], plan: dict, *, phase: str) -> dict:
    validate_village_plan(plan)
    require(phase in PHASES, "Unknown natural village phase")
    expected = (("origin",) if phase == "seed" else ()) + CASE_IDS
    cases = [event for event in events if event.get("kind") == "case"]
    require(tuple(event.get("case_id") for event in cases) == expected, "Missing, duplicate or reordered natural village evidence")
    observations = {event["case_id"]: event.get("snapshot") for event in cases}
    require(all(isinstance(snapshot, dict) for snapshot in observations.values()), "Malformed natural village evidence")
    before, after, reload = (observations[key] for key in ("before", "after", "chunk_reload"))
    for sample in (before, after):
        require(set(sample) == {"actors", "player"}, "Incomplete actor/client observation")
        validate_actor_snapshots(sample["actors"], edited=phase != "seed")
        _player(sample["player"])
    require(set(reload) == {"unloaded", "actors", "chunks"} and reload["unloaded"] is True, "No demonstrated village chunk unload")
    _chunk_evidence(reload["chunks"], plan)
    validate_actor_snapshots(reload["actors"], edited=phase != "seed")
    for role in ROLES:
        require(
            all(sample["actors"][role]["identity"] == before["actors"][role]["identity"] for sample in (after, reload)), "Natural resident identity changed"
        )
    for role in ("injured", "control"):
        require(same_persisted_actor(after["actors"][role], before["actors"][role], role), "Untouched natural resident changed during gameplay")
    require(
        all(same_persisted_actor(reload["actors"][role], after["actors"][role], role) for role in ROLES), "Natural resident state changed across chunk reload"
    )
    if phase == "seed":
        origin = observations["origin"]
        require(set(origin) == {"seed", "center", "natural_residents", "actors", "landmarks"}, "Incomplete natural generation provenance")
        require(origin["landmarks"] == plan["landmarks"], "Missing naturally generated village landmarks")
        require(origin["seed"] == plan["seed"] and origin["center"] == plan["center"] and _integer(origin["natural_residents"], 3), "Wrong natural world")
        require(isinstance(origin["actors"], dict) and set(origin["actors"]) == set(ROLES), "Missing original natural actors")
        for role, actor in origin["actors"].items():
            require(set(actor) == {"identity", "type", "variant", "position", "original_name"}, "Malformed natural origin")
            require(
                actor["identity"] == before["actors"][role]["identity"] and actor["type"] == before["actors"][role]["type"], "Natural identity was substituted"
            )
            require(actor["original_name"] == "", "Natural actor has a pre-existing custom name")
            _position(actor["position"], plan)
        require(before["player"] == {"emerald": 64, "bread": 0, "carrot": 8}, "Unexpected seed player supplies")
    trade = observations["trade"]
    require(set(trade) == {"interactions", "before", "after"} and _integer(trade["interactions"], 1), "No real client interaction with the farmer")
    _player(trade["before"])
    _player(trade["after"])
    require(trade["before"] == before["player"], "Trade did not start from the observed inventory")
    require(
        trade["before"]["emerald"] - trade["after"]["emerald"] == plan["trade"]["emerald"]
        and trade["after"]["bread"] - trade["before"]["bread"] == plan["trade"]["bread"],
        "Client did not finish exactly one bread trade and return its GUI-held currency",
    )
    require(trade["after"]["carrot"] == trade["before"]["carrot"], "Trade phase changed unrelated food")
    pickup = observations["pickup"]
    require(
        set(pickup) == {"sources", "picked_up", "farmer_before", "farmer_after", "player_before", "player_after"}
        and all(_integer(value) for key, value in pickup.items() if key != "sources"),
        "Malformed native food pickup",
    )
    sources = pickup["sources"]
    require(isinstance(sources, list) and 0 < len(sources) <= 8, "Missing client food item entities")
    identities = set()
    for item in sources:
        require(isinstance(item, dict) and set(item) == {"identity", "spawned", "attempted", "player_distance"}, "Malformed food item source")
        require(isinstance(item["identity"], str) and item["identity"] and item["identity"] not in identities, "Missing or duplicate dropped item identity")
        identities.add(item["identity"])
        require(_integer(item["spawned"], 1) and item["spawned"] <= 64 and _integer(item["attempted"], 1), "Malformed native pickup attempt")
        require(item["spawned"] == item["attempted"], "Native farmer pickup targets a different item amount")
        require(_number(item["player_distance"]) and 0 <= item["player_distance"] <= 4, "Food item did not originate near the client")
    require(
        sum(item["spawned"] for item in sources)
        == pickup["picked_up"]
        == pickup["farmer_after"] - pickup["farmer_before"]
        == pickup["player_before"] - pickup["player_after"]
        > 0,
        "Client food drop did not reach the farmer",
    )
    require(
        pickup["player_before"] == trade["after"]["carrot"] and pickup["player_after"] == after["player"]["carrot"],
        "Food pickup is not bound to this client inventory",
    )
    require(
        pickup["farmer_before"] == _carrots(before["actors"]["farmer"]["items"]) and pickup["farmer_after"] == _carrots(after["actors"]["farmer"]["items"]),
        "Food pickup is not bound to the observed farmer inventories",
    )
    require(all(after["player"][key] == trade["after"][key] for key in ("emerald", "bread")), "Post-trade client resources changed")
    return {"status": "pass", "phase": phase, "observations": deepcopy(observations)}
