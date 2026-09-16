"""Opt-in real client profile. All account-bearing data stays in ignored runs."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from .cases import expected_snapshot
from .protocol import ProbeError
from .service_profile import assignments

CLIENT_API_VERSION = "2.11.0-beta"
CONTROL_SLOTS = {"Inventory": 34, "EnderChestInventory": 25}
CONTROL_NAME = "MCBE client untouched control"


def enable_client_experiment(server: Path) -> None:
    """Only the fresh, already bootstrapped disposable world is accepted."""
    from mcbe_editor import nbt

    from .runner import WORLD_NAME

    path = server / "worlds" / WORLD_NAME / "level.dat"
    raw = path.read_bytes()
    if len(raw) < 8 or struct.unpack("<I", raw[4:8])[0] != len(raw) - 8:
        raise ProbeError("Unexpected generated level.dat framing")
    level = nbt.load(raw[8:], compressed=False, little_endian=True)
    level.tag["experiments"] = nbt.CompoundTag({
        "gametest": nbt.ByteTag(1), "experiments_ever_used": nbt.ByteTag(1), "saved_with_toggled_experiments": nbt.ByteTag(1),
    })
    payload = level.save_to(compressed=False, little_endian=True)
    path.write_bytes(raw[:4] + struct.pack("<I", len(payload)) + payload)


def player_items(root, field: str) -> dict:
    from mcbe_editor import nbt

    from .nbt_roundtrip import empty_saved_slot, value

    items = root.get(field)
    if not isinstance(items, nbt.ListTag):
        raise ProbeError("Client did not persist the expected inventory containers")
    result = {}
    seen = set()
    maximum = 35 if field == "Inventory" else 26
    for item in items:
        if not isinstance(item, nbt.CompoundTag) or not isinstance(item.get("Slot"), nbt.ByteTag):
            raise ProbeError("Invalid player item slot encoding")
        slot = value(item, "Slot")
        if not 0 <= slot <= maximum or slot in seen:
            raise ProbeError("Duplicate or invalid player slot")
        seen.add(slot)
        if not empty_saved_slot(item):
            result[slot] = item
    return result


def control_case(field: str) -> dict:
    return {"case_id": field + "/control", "id": "minecraft:stone", "amount": 1, "name": CONTROL_NAME,
            "lore": [], "damage": 0, "enchantments": []}


def verify_player_items(raw: bytes, cases: list[dict], *, seed: bool = False) -> dict:
    from mcbe_editor.bedrock_nbt import load_player_nbt

    from .nbt_roundtrip import disk_snapshot

    root = load_player_nbt(raw).tag
    locations = assignments(cases)
    containers = {field: player_items(root, field) for field in CONTROL_SLOTS}
    for field, items in containers.items():
        expected = {CONTROL_SLOTS[field]} | {locations[case["case_id"]][1] for case in cases
                                            if locations[case["case_id"]][0] == field and (not seed or case["mode"] != "create")}
        if set(items) != expected:
            raise ProbeError("Client persistence lost items or contains unexpected slots")
        control = control_case(field)
        if disk_snapshot(items[CONTROL_SLOTS[field]], control) != expected_snapshot(control):
            raise ProbeError("Client persistence changed an untouched control")
    for case in cases:
        field, slot = locations[case["case_id"]]
        expected = expected_snapshot(case, seed=seed)
        item = containers[field].get(slot)
        actual = None if item is None else disk_snapshot(item, case)
        if actual != expected:
            raise ProbeError("Client persistence changed tested item semantics: " + case["case_id"])
    return {"status": "pass", "cases": len(cases), "containers": len(containers)}


def client_worker(run_dir: Path, world: Path, records: dict, cases: list[dict], action: str) -> dict:
    from mcbe_editor.bedrock_nbt import load_player_nbt

    from .nbt_roundtrip import read_records
    from .player_service import exercise_player_service
    from .runner import write_json

    identity_file = run_dir / "private-player-key.json"
    if action == "verify":
        key = bytes.fromhex(json.loads(identity_file.read_text(encoding="utf-8"))["key"])
        if key not in records:
            raise ProbeError("Original client player record disappeared")
        return verify_player_items(records[key], cases)
    if identity_file.exists():
        raise ProbeError("Client edit phase must run only once")
    players = [key for key in records if key.startswith(b"player_") or key == b"~local_player"]
    if len(players) != 1:
        raise ProbeError("Fresh client world must contain exactly one real player record")
    key = players[0]
    verify_player_items(records[key], cases, seed=True)
    before = load_player_nbt(records[key]).tag
    locations = assignments(cases)
    keep = [(field, slot) for field, slot in CONTROL_SLOTS.items()]
    keep.extend(locations[case["case_id"]] for case in cases if case["mode"] == "preserve")
    frozen = {(field, slot): player_items(before, field)[slot].save_to() for field, slot in keep}
    results, checks = exercise_player_service(world, (key,), cases)
    if any(player_items(results[0], field)[slot].save_to() != original for (field, slot), original in frozen.items()):
        raise ProbeError("Player service changed an untouched real-client item")
    verified = verify_player_items(read_records(world)[key], cases)
    # Never include this record key in summaries, status files or public fixtures.
    write_json(identity_file, {"key": key.hex()})
    return {**verified, "player_service": {**checks, "real_players": 1, "client_login_verified": False}}
