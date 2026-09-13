"""Apply one identical player edit through a selectable NBT backend.

Helper process for ``tests/test_nbt_reference_write_path.py``; it is not a
test itself. ``--backend amulet`` installs Amulet-NBT as ``mcbe_editor.nbt``
before the application is imported, which is exactly the module binding the
editor used before the standard-library codec. ``--backend project`` keeps the
normal codec. Everything else -- service layer, validation, backups and the
LevelDB write -- is the unchanged application code.

The JSON report contains each edited player's view before and after the save,
the raw player records and one digest over every other database value. The
world path is replaced by ``<world>`` so reports of two copies compare literally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLAYER_KEY_PREFIX = b"player_"
LOCAL_PLAYER_KEYS = (b"~local_player", b"local_player")
VIEW_FIELDS = (
    "player",
    "player_revision",
    "inventory",
    "ender_chest",
    "has_ender_chest",
    "stats",
    "effects",
    "abilities",
    "hidden_unknown_slots",
    "protected_nbt",
)


def install_backend(backend: str) -> None:
    if backend == "amulet":
        import amulet_nbt

        sys.modules["mcbe_editor.nbt"] = amulet_nbt
    elif backend != "project":
        raise SystemExit(f"Unknown NBT backend: {backend}")


def edit_payload(before: dict) -> dict:
    """Build the identical edit from a loaded player view, independent of the backend."""
    inventory = {int(slot): item for slot, item in before["inventory"].items()}
    inventory[0] = {"slot": 0, "name": "minecraft:diamond", "count": 7, "damage": 0, "display_name": "", "lore": [], "enchantments": []}
    inventory[1] = {
        "slot": 1,
        "name": "minecraft:diamond_sword",
        "count": 1,
        "damage": 0,
        "display_name": "Differential",
        "lore": ["Zeile 1", "Grüße 世界"],
        "enchantments": [{"id": 9, "lvl": 3}],
    }
    ender_chest = None
    if before.get("has_ender_chest"):
        chest = {int(slot): item for slot, item in before["ender_chest"].items()}
        chest[0] = {"slot": 0, "name": "minecraft:diamond", "count": 3, "damage": 0, "display_name": "", "lore": [], "enchantments": []}
        ender_chest = [chest[slot] for slot in sorted(chest)]
    opaque = (before.get("protected_nbt") or {}).get("stat_fields_opaque") or {}
    stats = {name: value for name, value in (("xp_level", 42), ("health", 19.0), ("food_level", 19), ("xp_progress", 0.25)) if name not in opaque}
    effects = None
    if before.get("effects") and not any(effect.get("opaque") for effect in before["effects"]):
        effects = [dict(effect) for effect in before["effects"]]
        effects[0].update({"duration": 1234, "amplifier": 1})
    abilities = None
    current = before.get("abilities") or {}
    if current and "_opaque" not in current:
        abilities = {"mayfly": not current.get("mayfly", False), "fly_speed": 0.1}
    return {
        "inventory": [inventory[slot] for slot in sorted(inventory)],
        "ender_chest": ender_chest,
        "stats": stats,
        "effects": effects,
        "abilities": abilities,
    }


def view(loaded: dict) -> dict:
    result = {field: loaded.get(field) for field in VIEW_FIELDS}
    result["compatibility_player"] = (loaded.get("compatibility") or {}).get("player")
    return result


def dump_database(db) -> dict:
    """Raw player records plus one digest over every other key and value."""
    digest = hashlib.sha256()
    count = 0
    players = {}
    for key, value in db.iter_items():
        if key.startswith(PLAYER_KEY_PREFIX) or key in LOCAL_PLAYER_KEYS:
            players[key.hex()] = value.hex()
            continue
        digest.update(len(key).to_bytes(4, "little") + key + hashlib.sha256(value).digest())
        count += 1
    return {"non_player_count": count, "non_player_digest": digest.hexdigest(), "player_records": players}


def run(backend: str, world: Path, *, edit: bool) -> dict:
    install_backend(backend)
    import mcbe_editor.db as db_module
    from mcbe_editor.db import LevelDbAdapter
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.services import BedrockEditorService

    # Disposable copies only: keep the web write guard out, as the private-world tests do.
    db_module._runtime_app_modules = lambda: ()
    db_module._registered_write_guard = None
    world_path = str(world.resolve())
    report = {"backend": backend, "nbt_module": sys.modules["mcbe_editor.nbt"].__name__, "players": {}}
    if edit:
        service = BedrockEditorService(ITEMS, ENCHANTMENTS)
        for player in service.list_players(world_path)["players"]:
            if not (player.get("editable") and player.get("player_key")):
                continue
            key = player["player_key"]
            before = service.load_player(world_path, key)
            payload = edit_payload(before)
            entry = {"kind": player.get("kind"), "payload": payload, "before": view(before)}
            try:
                result = service.save_player(
                    world_path,
                    key,
                    payload["inventory"],
                    payload["stats"],
                    ender_chest_list=payload["ender_chest"],
                    effects_list=payload["effects"],
                    abilities_dict=payload["abilities"],
                    base_revision=before["player_revision"],
                )
                entry["save"] = {"success": result.get("success"), "no_op": result.get("no_op")}
            except Exception as exc:  # noqa: BLE001 - recorded and compared literally between backends
                entry["save"] = {"error": f"{type(exc).__name__}: {exc}"}
            entry["after"] = view(service.load_player(world_path, key))
            report["players"][key] = entry
    db = LevelDbAdapter(str(world / "db"))
    try:
        report.update(dump_database(db))
    finally:
        db.close()
    text = json.dumps(report, sort_keys=True, default=str)
    for variant in {world_path, world_path.replace("\\", "/"), str(world), str(world).replace("\\", "/")}:
        text = text.replace(json.dumps(variant)[1:-1], "<world>")
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("project", "amulet"), required=True)
    parser.add_argument("--world", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--no-edit", action="store_true", help="Only record the database state")
    args = parser.parse_args(argv)
    report = run(args.backend, args.world, edit=not args.no_edit)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
