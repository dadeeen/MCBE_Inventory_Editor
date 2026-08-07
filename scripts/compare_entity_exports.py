#!/usr/bin/env python3
"""Compare two exported entity NBT records from export_entity_nbt.py."""

from __future__ import annotations

import argparse
import json
from typing import Any


def load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def by_suffix(records: list[dict[str, Any]], suffix: str) -> dict[str, Any]:
    suffix = suffix.lower().replace(" ", "")
    for record in records:
        if str(record.get("key", {}).get("actor_suffix_hex", "")).lower() == suffix:
            return record
    raise SystemExit(f"No record with actor suffix {suffix!r} found.")


def value_at(data: Any, path: tuple[str, ...]) -> Any:
    value = data
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def type_name(value: Any) -> str:
    if value is None:
        return "missing"
    return type(value).__name__


def diff_values(left: Any, right: Any, path: str, rows: list[dict[str, Any]]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        keys = sorted(set(left) | set(right))
        for key in keys:
            diff_values(left.get(key), right.get(key), f"{path}.{key}" if path else key, rows)
        return
    if isinstance(left, list) and isinstance(right, list):
        if left != right:
            rows.append({"path": path, "left_type": "list", "right_type": "list", "left": left, "right": right})
        return
    if left != right:
        rows.append({"path": path, "left_type": type_name(left), "right_type": type_name(right), "left": left, "right": right})


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    nbt = record.get("nbt", {})
    return {
        "actor_suffix": record.get("key", {}).get("actor_suffix_hex"),
        "value_len": record.get("value_len"),
        "identifier": record.get("identifier"),
        "UniqueID": nbt.get("UniqueID"),
        "Pos": nbt.get("Pos"),
        "Rotation": nbt.get("Rotation"),
        "Variant": nbt.get("Variant"),
        "MarkVariant": nbt.get("MarkVariant"),
        "Temper": nbt.get("Temper"),
        "NaturalSpawn": nbt.get("NaturalSpawn"),
        "Surface": nbt.get("Surface"),
        "Persistent": nbt.get("Persistent"),
        "tag_count": len(nbt) if isinstance(nbt, dict) else None,
        "attribute_names": [attr.get("Name") for attr in nbt.get("Attributes", []) if isinstance(attr, dict)] if isinstance(nbt, dict) else [],
        "definitions": nbt.get("definitions") if isinstance(nbt, dict) else None,
        "internalComponents": nbt.get("internalComponents") if isinstance(nbt, dict) else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two records from export_entity_nbt.py JSON output.")
    parser.add_argument("export_json")
    parser.add_argument("--left-suffix", required=True, help="Actor suffix hex for left/injected record.")
    parser.add_argument("--right-suffix", required=True, help="Actor suffix hex for right/real record.")
    parser.add_argument("--max-diffs", type=int, default=200)
    args = parser.parse_args(argv)

    data = load_json(args.export_json)
    records = data.get("records", [])
    left = by_suffix(records, args.left_suffix)
    right = by_suffix(records, args.right_suffix)
    rows: list[dict[str, Any]] = []
    diff_values(left.get("nbt", {}), right.get("nbt", {}), "nbt", rows)
    result = {
        "success": True,
        "left_summary": summarize(left),
        "right_summary": summarize(right),
        "diff_count": len(rows),
        "diffs": rows[: max(1, args.max_diffs)],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
