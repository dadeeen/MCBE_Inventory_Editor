#!/usr/bin/env python3
"""Distil a committable mount reference from Minecraft-written actor records.

The mount writer's per-type constants (definitions sets, attribute bases, tag
presence) are claims about what Minecraft itself produces.  This script turns a
private reference world into a small, reviewable JSON fixture so those claims
can be re-checked by an always-on test instead of a manual comparison.

Only *type-invariant* evidence is recorded.  Values Minecraft rolls per specimen
(health, jump strength, temper) are listed by name as "varying" and never
asserted.  Nothing world-specific or user-authored is written to the fixture:
custom names are dropped entirely, and coordinates, entity ids and owner ids are
recorded by tag name only.  See fixtures/README.md for the privacy boundary.

Usage:
    python scripts/export_mount_reference.py \
        --world "fixtures/private/<reference world>" \
        --output tests/fixtures/mount_reference.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import amulet_nbt as nbt  # noqa: E402

from mcbe_editor.bedrock_nbt import LOAD_KWARGS  # noqa: E402
from mcbe_editor.db import ReadonlyLevelDbAdapter  # noqa: E402
from mcbe_editor.mount_write import ACTOR_PREFIX, SYNTHETIC_CREATABLE_MOUNT_TYPES  # noqa: E402

# User-authored text.  Never recorded, not even as a tag name.
EXCLUDED_TAGS = frozenset({"CustomName", "CustomNameVisible"})
# Recorded as "this tag must exist", never with its value: world coordinates and
# entity/player identities.
NAME_ONLY_TAGS = frozenset(
    {
        "Pos",
        "Rotation",
        "UniqueID",
        "internalComponents",
        "OwnerNew",
        "LoveCause",
        "TargetID",
        "LeasherID",
    }
)


def _scalar(value: Any) -> Any:
    return getattr(value, "py_data", None)


def _is_baby(tag: nbt.CompoundTag, definitions: list[str]) -> bool:
    if "IsBaby" in tag and int(_scalar(tag["IsBaby"]) or 0) == 1:
        return True
    return any("baby" in entry for entry in definitions)


def _definitions(tag: nbt.CompoundTag) -> list[str]:
    raw = tag.get("definitions")
    if not isinstance(raw, nbt.ListTag):
        return []
    return [str(_scalar(item)) for item in raw]


def _comparable_tags(tag: nbt.CompoundTag) -> dict[str, Any]:
    """Scalar tag values worth comparing, keyed by tag name."""

    values: dict[str, Any] = {}
    for key in tag:
        name = str(key)
        if name in EXCLUDED_TAGS or name in NAME_ONLY_TAGS:
            continue
        value = tag[name]
        if isinstance(value, (nbt.CompoundTag, nbt.ListTag)):
            continue
        data = _scalar(value)
        if isinstance(data, (int, float, str)):
            values[name] = data
    return values


def _attribute_bases(tag: nbt.CompoundTag) -> dict[str, float]:
    result: dict[str, float] = {}
    raw = tag.get("Attributes")
    if not isinstance(raw, nbt.ListTag):
        return result
    for entry in raw:
        if not isinstance(entry, nbt.CompoundTag):
            continue
        name = str(_scalar(entry.get("Name")) or "")
        base = _scalar(entry.get("Base"))
        if name and isinstance(base, (int, float)):
            result[name] = float(base)
    return result


def collect(world_path: Path) -> dict[str, list[dict[str, Any]]]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    db = ReadonlyLevelDbAdapter(str(world_path / "db"))
    try:
        for key, raw in db.iter_items():
            if not (key.startswith(ACTOR_PREFIX) and len(key) == len(ACTOR_PREFIX) + 8):
                continue
            try:
                tag = nbt.load(raw, **LOAD_KWARGS).tag
            except Exception:
                continue
            identifier = str(_scalar(tag.get("identifier")) or "")
            if identifier not in SYNTHETIC_CREATABLE_MOUNT_TYPES:
                continue
            definitions = _definitions(tag)
            if _is_baby(tag, definitions):
                continue
            by_type[identifier].append(
                {
                    "tag_names": {str(name) for name in tag if str(name) not in EXCLUDED_TAGS},
                    "values": _comparable_tags(tag),
                    "attributes": _attribute_bases(tag),
                    "definitions": definitions,
                    "variant": _scalar(tag.get("Variant")) if "Variant" in tag else None,
                    "mark_variant": _scalar(tag.get("MarkVariant")) if "MarkVariant" in tag else None,
                }
            )
    finally:
        db.close()
    return by_type


# One specimen cannot tell a type-invariant value apart from a per-specimen roll,
# so its values are recorded as unconfirmed and the test does not assert them.
MIN_RECORDS_FOR_INVARIANT = 2


def distil(records: list[dict[str, Any]]) -> dict[str, Any]:
    all_names = [record["tag_names"] for record in records]
    required = sorted(set.intersection(*all_names)) if all_names else []
    optional = sorted(set.union(*all_names) - set(required)) if all_names else []

    stable_tags: dict[str, Any] = {}
    varying_tags: list[str] = []
    for name in required:
        if name in NAME_ONLY_TAGS:
            continue
        seen = {record["values"].get(name) for record in records if name in record["values"]}
        if len(seen) == 1 and None not in seen:
            stable_tags[name] = next(iter(seen))
        elif seen:
            varying_tags.append(name)

    stable_attributes: dict[str, float] = {}
    varying_attributes: list[str] = []
    attribute_names = sorted(set.intersection(*[set(record["attributes"]) for record in records])) if records else []
    for name in attribute_names:
        seen = {record["attributes"][name] for record in records}
        if len(seen) == 1:
            stable_attributes[name] = next(iter(seen))
        else:
            varying_attributes.append(name)

    definition_variants = sorted({tuple(record["definitions"]) for record in records})
    # Entries every observed specimen carries.  The rest is driven by per-specimen
    # state such as a horse's colour/markings or a camel sitting down.
    common_definitions = sorted(set.intersection(*[set(variant) for variant in definition_variants])) if definition_variants else []
    # Colour/marking evidence: which definitions the game emits for a concrete
    # Variant/MarkVariant pair.  This is what validates the writer's lookup tables.
    variant_definitions = [
        dict(pair)
        for pair in sorted(
            {
                (("variant", record["variant"]), ("mark_variant", record["mark_variant"]), ("definitions", tuple(record["definitions"])))
                for record in records
                if record["variant"] is not None and record["mark_variant"] is not None
            }
        )
    ]
    confirmed = len(records) >= MIN_RECORDS_FOR_INVARIANT
    result = {
        "record_count": len(records),
        "required_tags": required,
        "optional_tags": optional,
        "invariant_tags": dict(sorted(stable_tags.items())) if confirmed else {},
        "varying_tags": sorted(varying_tags),
        "invariant_attributes": dict(sorted(stable_attributes.items())) if confirmed else {},
        "varying_attributes": sorted(varying_attributes),
        "common_definitions": common_definitions,
        "definitions_variants": [list(variant) for variant in definition_variants],
        "variant_definitions": [{**entry, "definitions": list(entry["definitions"])} for entry in variant_definitions],
    }
    if not confirmed:
        result["unconfirmed_single_specimen"] = {
            "reason": (
                f"only {len(records)} adult record(s); a single specimen cannot separate type-invariant values "
                "from per-specimen rolls, so nothing here is asserted. Add a second adult and regenerate."
            ),
            "tags": dict(sorted(stable_tags.items())),
            "attributes": dict(sorted(stable_attributes.items())),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--world", required=True, action="append", help="Reference world folder containing db/. Repeatable.")
    parser.add_argument("--output", default="tests/fixtures/mount_reference.json", help="Fixture path to write.")
    parser.add_argument("--label", default="", help="Optional short note about the reference world (no personal data).")
    args = parser.parse_args(argv)

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in args.world:
        world_path = Path(os.path.abspath(os.path.expanduser(entry)))
        if not (world_path / "db").is_dir():
            print(f"No db/ folder in {world_path}", file=sys.stderr)
            return 2
        for identifier, records in collect(world_path).items():
            by_type[identifier].extend(records)
    if not by_type:
        print("No adult mount records found.", file=sys.stderr)
        return 1

    fixture = {
        "_comment": (
            "Distilled from Minecraft-written actor records; regenerate with scripts/export_mount_reference.py. "
            "Only type-invariant evidence is asserted. Per-specimen rolls are listed under varying_* and never "
            "compared. No coordinates, entity ids, owner ids or custom names are stored."
        ),
        "label": args.label,
        "mounts": {identifier: distil(records) for identifier, records in sorted(by_type.items())},
    }
    output = Path(os.path.abspath(os.path.expanduser(args.output)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")

    print(f"Reference written: {output}")
    warned = False
    for identifier, data in fixture["mounts"].items():
        print(
            f"  {identifier:26s} {data['record_count']} record(s), "
            f"{len(data['required_tags'])} required tags, "
            f"{len(data['invariant_tags'])} invariant values, "
            f"{len(data['invariant_attributes'])} invariant attributes"
        )
        if "unconfirmed_single_specimen" in data:
            warned = True
            print(f"      ! only {data['record_count']} adult record - values are not asserted.")
    if warned:
        print("\nNote: types with a single adult record need a second specimen before")
        print("invariant values can be told apart from per-specimen rolls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
