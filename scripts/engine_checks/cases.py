"""Deterministic coverage, with expectations independent of NBT serialization."""

from __future__ import annotations

SLOTS_PER_CARRIER = 26  # Slot 26 is an untouched engine-created control item.
CARRIER_PREFIX = "MCBE_ENGINE_CARRIER_"
CONTROL_NAME = "MCBE untouched control"


def make_cases(item_ids: list[str], observations: dict, limits: dict) -> list[dict]:
    cases = []

    def add(item_id, mode, amount, **extra):
        index = len(cases)
        cases.append({
            "case_id": f"case_{index:05d}", "id": item_id, "mode": mode, "amount": amount,
            "carrier": f"{CARRIER_PREFIX}{index // SLOTS_PER_CARRIER:04d}", "slot": index % SLOTS_PER_CARRIER,
            "name": "", "lore": [], "damage": 0, "enchantments": [], **extra,
        })

    for item_id in sorted(item_ids):
        if item_id not in observations or observations[item_id]["max_amount"] > 127:
            continue
        maximum = observations[item_id]["max_amount"]
        add(item_id, "create", 1)
        # Existing maximal stacks must survive even before a candidate limit is promoted.
        add(item_id, "preserve", maximum)
        if item_id in limits and maximum > 1:
            add(item_id, "create", maximum)
            if maximum > 2:
                add(item_id, "create", maximum - 1)
    for item_id in ("minecraft:stone", "minecraft:oak_sign", "minecraft:diamond_pickaxe", "minecraft:bow"):
        if item_id in observations:
            add(item_id, "decorate", 1, name="§bEngine Prüflauf 世界", lore=["Grüße aus dem Editor", "Roundtrip ✓"])
    for item_id in ("minecraft:diamond_pickaxe", "minecraft:bow"):
        durability = observations.get(item_id, {}).get("max_durability")
        if durability and item_id in limits:
            add(item_id, "decorate", 1, damage=durability - 1)
    return cases


def expected_snapshot(case: dict, *, seed: bool = False) -> dict | None:
    if seed and case["mode"] == "create":
        return None
    return {
        "id": case["id"], "amount": case["amount"],
        "name": "" if seed else case["name"], "lore": [] if seed else case["lore"],
        "damage": 0 if seed else case["damage"], "enchantments": [] if seed else case["enchantments"],
    }


def validate_case_events(events: list[dict], cases: list[dict], *, seed: bool = False) -> None:
    from .protocol import ProbeError

    expected = {case["case_id"]: expected_snapshot(case, seed=seed) for case in cases}
    observed = {}
    for event in events:
        if event["kind"] != "case":
            continue
        key = event.get("case_id")
        if key not in expected or key in observed:
            raise ProbeError("Unexpected or duplicate roundtrip case")
        observed[key] = event.get("snapshot")
    if observed.keys() != expected.keys():
        raise ProbeError("Roundtrip probe omitted cases")
    for key, snapshot in expected.items():
        if observed[key] != snapshot:
            raise ProbeError(f"Engine changed item semantics in {key}: expected {snapshot!r}, observed {observed[key]!r}")
