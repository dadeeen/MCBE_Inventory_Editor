#!/usr/bin/env python3
"""Diff two Bedrock world LevelDB snapshots without writing to either world.

Intended workflow for entity-write research:

1. Copy a disposable Bedrock world to a BEFORE folder.
2. Open another copy, create/spawn exactly one test entity, close Minecraft.
3. Run this script against BEFORE and AFTER to see added/changed/deleted keys.

The script reports key hex/ascii, known prefixes and value hashes/lengths. It does
not print raw LevelDB values.
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter  # noqa: E402
from mcbe_editor.world import ensure_valid_world_path, get_world_name  # noqa: E402

KNOWN_KEY_PREFIXES = (
    b"actorprefix",
    b"digp",
    b"Overworld",
    b"Nether",
    b"TheEnd",
    b"player_",
    b"~local_player",
    b"AutonomousEntities",
)


def _json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@contextlib.contextmanager
def _open_readonly_db(world_path: str):
    db_path = ensure_valid_world_path(world_path)
    db = ReadonlyLevelDbAdapter(db_path)
    try:
        yield db
    finally:
        db.close()


def _safe_ascii(data: bytes) -> str:
    chars = []
    for byte in data:
        if 32 <= byte <= 126:
            chars.append(chr(byte))
        else:
            chars.append(".")
    return "".join(chars)


def _known_key_prefix(key: bytes) -> str | None:
    for prefix in KNOWN_KEY_PREFIXES:
        if key.startswith(prefix):
            return prefix.decode("ascii", errors="replace")
    return None


def _value_summary(raw: bytes) -> dict[str, Any]:
    return {
        "length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _record_summary(key: bytes, raw: bytes | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "key": {
            "length": len(key),
            "hex": key.hex(),
            "ascii_preview": _safe_ascii(key),
            "known_prefix": _known_key_prefix(key),
        }
    }
    if raw is not None:
        result["value"] = _value_summary(raw)
    return result


def _load_key_index(world_path: str) -> dict[bytes, dict[str, Any]]:
    index: dict[bytes, dict[str, Any]] = {}
    with _open_readonly_db(world_path) as db:
        for key, raw in db.iter_items():
            index[key] = _value_summary(raw)
    return index


def _world_summary(world_path: str, *, include_private_paths: bool) -> dict[str, Any]:
    world_path = os.path.abspath(os.path.normpath(os.path.expanduser(world_path)))
    result = {
        "name": get_world_name(world_path),
        "folder_name": os.path.basename(os.path.normpath(world_path)),
    }
    if include_private_paths:
        result["path"] = world_path
    return result


def _prefix_allowed(key: bytes, prefixes: list[bytes] | None) -> bool:
    if not prefixes:
        return True
    return any(key.startswith(prefix) for prefix in prefixes)


def diff_worlds(
    before_world: str,
    after_world: str,
    *,
    prefixes: list[bytes] | None,
    limit: int,
    include_private_paths: bool,
) -> dict[str, Any]:
    before_world = os.path.abspath(os.path.normpath(os.path.expanduser(before_world)))
    after_world = os.path.abspath(os.path.normpath(os.path.expanduser(after_world)))
    before = _load_key_index(before_world)
    after = _load_key_index(after_world)

    before_keys = set(before)
    after_keys = set(after)
    added_keys = sorted(key for key in after_keys - before_keys if _prefix_allowed(key, prefixes))
    deleted_keys = sorted(key for key in before_keys - after_keys if _prefix_allowed(key, prefixes))
    changed_keys = sorted(key for key in before_keys & after_keys if before[key]["sha256"] != after[key]["sha256"] and _prefix_allowed(key, prefixes))

    return {
        "success": True,
        "before_world": _world_summary(before_world, include_private_paths=include_private_paths),
        "after_world": _world_summary(after_world, include_private_paths=include_private_paths),
        "filter": {
            "prefixes": [prefix.decode("ascii", errors="replace") for prefix in prefixes] if prefixes else [],
            "limit_per_section": limit,
        },
        "counts": {
            "before_keys": len(before),
            "after_keys": len(after),
            "added": len(added_keys),
            "changed": len(changed_keys),
            "deleted": len(deleted_keys),
        },
        "added": [_record_summary(key, None) | {"value": after[key]} for key in added_keys[:limit]],
        "changed": [
            {
                **_record_summary(key, None),
                "before_value": before[key],
                "after_value": after[key],
            }
            for key in changed_keys[:limit]
        ],
        "deleted": [_record_summary(key, None) | {"value": before[key]} for key in deleted_keys[:limit]],
        "privacy": {
            "contains_raw_values": False,
            "contains_local_keys_and_hashes": True,
            "safe_to_publish": False,
            "note": "Output can reveal world structure and entity/chunk key metadata. Share only privately and deliberately.",
        },
    }


def _print_section(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"{title}: {len(rows)} shown")
    for index, row in enumerate(rows, start=1):
        key = row["key"]
        value = row.get("value") or row.get("after_value") or {}
        print(
            f"{index}. prefix={key.get('known_prefix') or '-'} key_len={key['length']} value_len={value.get('length')} sha={str(value.get('sha256', ''))[:16]}"
        )
        print(f"   key_ascii: {key['ascii_preview']}")
        print(f"   key_hex:   {key['hex']}")
        if "before_value" in row:
            print(f"   before: len={row['before_value']['length']} sha={row['before_value']['sha256']}")
            print(f"   after:  len={row['after_value']['length']} sha={row['after_value']['sha256']}")
    print()


def _print_text(result: dict[str, Any]) -> None:
    counts = result["counts"]
    print(f"Before: {result['before_world']['name']} ({result['before_world']['folder_name']})")
    print(f"After:  {result['after_world']['name']} ({result['after_world']['folder_name']})")
    print(f"Keys: before={counts['before_keys']} after={counts['after_keys']} added={counts['added']} changed={counts['changed']} deleted={counts['deleted']}")
    print()
    _print_section("Added", result["added"])
    _print_section("Changed", result["changed"])
    _print_section("Deleted", result["deleted"])


def _parse_prefixes(values: list[str] | None) -> list[bytes] | None:
    if not values:
        return None
    prefixes: list[bytes] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        if text.startswith("0x"):
            prefixes.append(bytes.fromhex(text[2:]))
        else:
            prefixes.append(text.encode("utf-8"))
    return prefixes or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Readonly diff of two Bedrock world LevelDB snapshots.")
    parser.add_argument("--before", required=True, help="Direct Bedrock world folder before the test action.")
    parser.add_argument("--after", required=True, help="Direct Bedrock world folder after the test action.")
    parser.add_argument(
        "--prefix",
        action="append",
        help="Only include keys starting with this text prefix. Repeatable. Examples: actorprefix, digp. Use 0x... for hex.",
    )
    parser.add_argument("--limit", type=int, default=50, help="Maximum rows per added/changed/deleted section. Default: 50.")
    parser.add_argument("--include-private-paths", action="store_true", help="Include absolute local paths in JSON output.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = diff_worlds(
            args.before,
            args.after,
            prefixes=_parse_prefixes(args.prefix),
            limit=max(1, min(int(args.limit or 50), 1000)),
            include_private_paths=bool(args.include_private_paths),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"diff_leveldb_keys: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(_json_dump(result), end="")
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
