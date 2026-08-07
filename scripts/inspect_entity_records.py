#!/usr/bin/env python3
"""Inspect Bedrock LevelDB records that look like entity NBT.

This diagnostic helper is intentionally read-only. It opens the world's db/
folder with the project's pure-Python ReadonlyLevelDbAdapter, tries to parse
values as uncompressed little-endian Bedrock NBT and reports records with entity
identifiers such as minecraft:horse.

Use it on a disposable copied world first. The output can contain local
coordinates and entity metadata; do not publish it blindly.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import amulet_nbt as nbt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcbe_editor.bedrock_nbt import LOAD_KWARGS  # noqa: E402
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter  # noqa: E402
from mcbe_editor.world import ensure_valid_world_path, get_world_name  # noqa: E402

ENTITY_IDENTIFIER_KEYS = (
    "identifier",
    "Identifier",
    "id",
    "Id",
    "EntityIdentifier",
)

SCALAR_PREVIEW_KEYS = (
    "identifier",
    "Identifier",
    "id",
    "Id",
    "UniqueID",
    "EntityId",
    "RuntimeID",
    "DimensionId",
    "Pos",
    "Rotation",
    "Variant",
    "Color",
    "MarkVariant",
    "Strength",
    "StrengthMax",
    "Temper",
    "IsTamed",
    "Tamed",
    "Saddled",
    "Saddle",
    "Chested",
    "NaturalSpawn",
    "OnGround",
    "Surface",
    "IsSwimming",
    "OwnerNew",
    "OwnerUUID",
)

ACTOR_PREFIX = b"actorprefix"
DIGP_PREFIX = b"digp"


@contextlib.contextmanager
def _open_readonly_db(world_path: str):
    db_path = ensure_valid_world_path(world_path)
    db = ReadonlyLevelDbAdapter(db_path)
    try:
        yield db
    finally:
        db.close()


def _json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _safe_ascii(data: bytes) -> str:
    chars = []
    for byte in data:
        if 32 <= byte <= 126:
            chars.append(chr(byte))
        else:
            chars.append(".")
    return "".join(chars)


def _known_key_prefix(key: bytes) -> str | None:
    for prefix in (ACTOR_PREFIX, DIGP_PREFIX, b"player_", b"~local_player"):
        if key.startswith(prefix):
            return prefix.decode("ascii", errors="replace")
    return None


def _key_summary(key: bytes) -> dict[str, Any]:
    return {
        "length": len(key),
        "hex": key.hex(),
        "ascii_preview": _safe_ascii(key),
        "known_prefix": _known_key_prefix(key),
    }


def _try_load_nbt(raw: bytes):
    try:
        return nbt.load(raw, **LOAD_KWARGS)
    except Exception:
        return None


def _unwrap_scalar(value: Any) -> Any:
    if value is None:
        return None
    py_data = getattr(value, "py_data", None)
    if py_data is not None:
        return py_data
    value_attr = getattr(value, "value", None)
    if value_attr is not None and not callable(value_attr):
        return value_attr
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _preview_value(value: Any) -> Any:
    if isinstance(value, nbt.ListTag):
        return [_preview_value(item) for item in list(value)[:8]]
    if isinstance(value, nbt.CompoundTag):
        return {str(key): _preview_value(value[key]) for key in list(value.keys())[:16]}
    return _unwrap_scalar(value)


def _entity_identifier(root: Any) -> str | None:
    if not isinstance(root, nbt.CompoundTag):
        return None
    for key in ENTITY_IDENTIFIER_KEYS:
        if key not in root:
            continue
        value = _unwrap_scalar(root.get(key))
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _root_preview(root: Any) -> dict[str, Any]:
    if not isinstance(root, nbt.CompoundTag):
        return {"root_type": type(root).__name__}
    tag_keys = [str(key) for key in root]
    scalars = {}
    for key in SCALAR_PREVIEW_KEYS:
        if key in root:
            scalars[key] = _preview_value(root.get(key))
    return {
        "root_type": "CompoundTag",
        "tag_keys": tag_keys,
        "preview": scalars,
    }


def _actor_suffix(actor_key: bytes) -> bytes | None:
    if actor_key.startswith(ACTOR_PREFIX) and len(actor_key) == len(ACTOR_PREFIX) + 8:
        return actor_key[len(ACTOR_PREFIX) :]
    return None


def _unique_id_entry_from_actor_key(actor_key: bytes) -> bytes | None:
    suffix = _actor_suffix(actor_key)
    if suffix is None:
        return None
    group = int.from_bytes(suffix[:4], "big", signed=False)
    local_id = int.from_bytes(suffix[4:], "big", signed=False)
    if group <= 0 or local_id <= 0:
        return None
    unique_id = -(group << 32) + local_id
    return unique_id.to_bytes(8, "little", signed=True)


def _position_from_root(root: Any) -> dict[str, float] | None:
    if not isinstance(root, nbt.CompoundTag) or "Pos" not in root:
        return None
    pos = root.get("Pos")
    if not isinstance(pos, nbt.ListTag) or len(pos) < 3:
        return None
    try:
        return {"x": float(_unwrap_scalar(pos[0])), "y": float(_unwrap_scalar(pos[1])), "z": float(_unwrap_scalar(pos[2]))}
    except (TypeError, ValueError):
        return None


def _digp_key_for_position(position: dict[str, float]) -> bytes:
    chunk_x = math.floor(float(position["x"]) / 16)
    chunk_z = math.floor(float(position["z"]) / 16)
    return DIGP_PREFIX + int(chunk_x).to_bytes(4, "little", signed=True) + int(chunk_z).to_bytes(4, "little", signed=True)


def _digp_summary(db, actor_key: bytes, root: Any) -> dict[str, Any] | None:
    suffix = _actor_suffix(actor_key)
    unique_id_entry = _unique_id_entry_from_actor_key(actor_key)
    position = _position_from_root(root)
    if suffix is None or unique_id_entry is None or position is None:
        return None
    digp_key = _digp_key_for_position(position)
    chunk_x = math.floor(float(position["x"]) / 16)
    chunk_z = math.floor(float(position["z"]) / 16)
    try:
        value = db.get(digp_key)
        exists = True
    except KeyError:
        value = b""
        exists = False
    valid_shape = len(value) % 8 == 0
    entries = [value[index : index + 8] for index in range(0, len(value), 8)] if valid_shape else []
    return {
        "key": _key_summary(digp_key),
        "chunk": {"x": chunk_x, "z": chunk_z},
        "exists": exists,
        "value_length": len(value),
        "valid_entry_shape": valid_shape,
        "entry_count": len(entries),
        "entries_hex": [entry.hex() for entry in entries[:16]],
        "actor_suffix_hex": suffix.hex(),
        "contains_actor_suffix": suffix in entries,
        "unique_id_entry_hex": unique_id_entry.hex(),
        "contains_unique_id_entry": unique_id_entry in entries,
    }


def inspect_entities(
    world_path: str,
    *,
    identifier: str | None,
    limit: int,
    include_non_matching_entities: bool,
    include_private_paths: bool,
) -> dict[str, Any]:
    world_path = os.path.abspath(os.path.normpath(os.path.expanduser(world_path)))
    normalized_identifier = identifier.strip() if identifier else None
    inspected_values = 0
    parsed_nbt_values = 0
    entity_like_values = 0
    matches: list[dict[str, Any]] = []

    with _open_readonly_db(world_path) as db:
        for key, raw in db.iter_items():
            inspected_values += 1
            named_tag = _try_load_nbt(raw)
            if named_tag is None:
                continue
            parsed_nbt_values += 1
            root = getattr(named_tag, "tag", None)
            found_identifier = _entity_identifier(root)
            if not found_identifier:
                continue
            entity_like_values += 1
            is_match = normalized_identifier is None or found_identifier == normalized_identifier
            if not is_match and not include_non_matching_entities:
                continue
            matches.append(
                {
                    "identifier": found_identifier,
                    "matched_filter": is_match,
                    "key": _key_summary(key),
                    "raw_length": len(raw),
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "digp": _digp_summary(db, key, root),
                    "nbt": _root_preview(root),
                }
            )
            if len(matches) >= limit:
                break

    world = {
        "name": get_world_name(world_path),
        "folder_name": os.path.basename(os.path.normpath(world_path)),
    }
    if include_private_paths:
        world["path"] = world_path
    return {
        "success": True,
        "world": world,
        "filter": {"identifier": normalized_identifier},
        "counts": {
            "inspected_leveldb_values": inspected_values,
            "parsed_nbt_values": parsed_nbt_values,
            "entity_like_values": entity_like_values,
            "returned_records": len(matches),
        },
        "records": matches,
        "privacy": {
            "contains_raw_nbt": False,
            "contains_coordinates_or_entity_metadata": True,
            "safe_to_publish": False,
            "note": "Output can reveal local coordinates and entity/world metadata. Share only privately and deliberately.",
        },
    }


def _print_text(result: dict[str, Any]) -> None:
    world = result["world"]
    counts = result["counts"]
    print(f"Welt: {world.get('name')} ({world.get('folder_name')})")
    print(
        "Records: "
        f"{counts['returned_records']} returned, "
        f"{counts['entity_like_values']} entity-like, "
        f"{counts['parsed_nbt_values']} NBT values parsed, "
        f"{counts['inspected_leveldb_values']} LevelDB values inspected"
    )
    print()
    for index, record in enumerate(result["records"], start=1):
        key = record["key"]
        preview = record["nbt"].get("preview", {})
        print(f"{index}. {record['identifier']} key_prefix={key.get('known_prefix') or '-'} raw={record['raw_length']} bytes")
        print(f"   key_ascii: {key['ascii_preview']}")
        print(f"   key_hex:   {key['hex']}")
        digp = record.get("digp") or {}
        if digp:
            print(
                f"   digp: chunk={digp.get('chunk')} exists={digp.get('exists')} "
                f"contains_unique_id_entry={digp.get('contains_unique_id_entry')} "
                f"contains_actor_suffix={digp.get('contains_actor_suffix')} entries={digp.get('entry_count')}"
            )
            print(f"   digp_key_hex: {digp.get('key', {}).get('hex')}")
            print(f"   digp_entries: {', '.join(digp.get('entries_hex') or [])}")
        for field, value in preview.items():
            print(f"   {field}: {value}")
        tag_keys = record["nbt"].get("tag_keys", [])
        if tag_keys:
            print(f"   tag_keys: {', '.join(tag_keys[:32])}{' ...' if len(tag_keys) > 32 else ''}")
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect readonly Bedrock LevelDB entity NBT records from a direct world folder.")
    parser.add_argument("--world", required=True, help="Direct Bedrock world folder containing the db/ directory.")
    parser.add_argument(
        "--identifier",
        default="minecraft:horse",
        help="Entity identifier to filter for. Default: minecraft:horse. Use empty string to return all entity-like records.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum records to return. Default: 20.")
    parser.add_argument("--include-non-matching-entities", action="store_true", help="Also include other entity-like records up to --limit.")
    parser.add_argument("--include-private-paths", action="store_true", help="Include absolute local paths in JSON output.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    identifier = args.identifier.strip() or None
    try:
        result = inspect_entities(
            args.world,
            identifier=identifier,
            limit=max(1, min(int(args.limit or 20), 500)),
            include_non_matching_entities=bool(args.include_non_matching_entities),
            include_private_paths=bool(args.include_private_paths),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"inspect_entity_records: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(_json_dump(result), end="")
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
