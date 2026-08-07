#!/usr/bin/env python3
"""Export decoded Bedrock entity NBT records as JSON.

Read-only helper for comparing an entity created by Minecraft with one created
by the experimental mount writer.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
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

IDENTIFIER_KEYS = ("identifier", "Identifier", "id", "Id", "EntityIdentifier")
ACTOR_PREFIX = b"actorprefix"


@contextlib.contextmanager
def open_db(world_path: str):
    db = ReadonlyLevelDbAdapter(ensure_valid_world_path(world_path))
    try:
        yield db
    finally:
        db.close()


def safe_ascii(data: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in data)


def key_info(key: bytes) -> dict[str, Any]:
    return {
        "ascii": safe_ascii(key),
        "hex": key.hex(),
        "len": len(key),
        "actor_suffix_hex": key[len(ACTOR_PREFIX) :].hex() if key.startswith(ACTOR_PREFIX) else None,
    }


def scalar(value: Any) -> Any:
    data = getattr(value, "py_data", None)
    if data is not None:
        return data
    data = getattr(value, "value", None)
    if data is not None and not callable(data):
        return data
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex(), "bytes_ascii": safe_ascii(value)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def to_jsonable(value: Any, *, depth: int, max_depth: int) -> Any:
    if depth > max_depth:
        return {"truncated": True, "type": type(value).__name__}
    if isinstance(value, nbt.CompoundTag):
        return {str(key): to_jsonable(value[key], depth=depth + 1, max_depth=max_depth) for key in value}
    if isinstance(value, nbt.ListTag):
        return [to_jsonable(item, depth=depth + 1, max_depth=max_depth) for item in value]
    return scalar(value)


def entity_identifier(root: Any) -> str | None:
    if not isinstance(root, nbt.CompoundTag):
        return None
    for key in IDENTIFIER_KEYS:
        if key not in root:
            continue
        value = scalar(root.get(key))
        if isinstance(value, str) and value:
            return value
    return None


def load_nbt(data: bytes):
    try:
        return nbt.load(data, **LOAD_KWARGS)
    except Exception:
        return None


def export(world_path: str, identifier: str | None, limit: int, max_depth: int) -> dict[str, Any]:
    world_path = os.path.abspath(os.path.normpath(os.path.expanduser(world_path)))
    records: list[dict[str, Any]] = []
    inspected = 0
    parsed = 0
    entity_like = 0
    with open_db(world_path) as db:
        for key, value in db.iter_items():
            inspected += 1
            named = load_nbt(value)
            if named is None:
                continue
            parsed += 1
            root = getattr(named, "tag", None)
            found = entity_identifier(root)
            if not found:
                continue
            entity_like += 1
            if identifier and found != identifier:
                continue
            records.append(
                {
                    "identifier": found,
                    "key": key_info(key),
                    "value_len": len(value),
                    "value_sha256": hashlib.sha256(value).hexdigest(),
                    "nbt": to_jsonable(root, depth=0, max_depth=max_depth),
                }
            )
            if len(records) >= limit:
                break
    return {
        "success": True,
        "world": {"name": get_world_name(world_path), "folder_name": os.path.basename(world_path)},
        "counts": {"inspected": inspected, "parsed_nbt": parsed, "entity_like": entity_like, "returned": len(records)},
        "filter": {"identifier": identifier},
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export decoded Bedrock entity NBT records as JSON.")
    parser.add_argument("--world", required=True)
    parser.add_argument("--identifier", default="minecraft:horse")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-depth", type=int, default=20)
    args = parser.parse_args(argv)
    identifier = args.identifier.strip() or None
    try:
        result = export(args.world, identifier, max(1, args.limit), max(1, args.max_depth))
    except (OSError, ValueError, KeyError) as exc:
        print(f"export_entity_nbt: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
