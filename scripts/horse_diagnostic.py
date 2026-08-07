#!/usr/bin/env python3
"""One-command diagnostic for experimental mount entity writes.

The script is read-only. By default it inspects minecraft:horse actor records,
checks the matching digp chunk index and writes a compact JSON report that is
easy to share privately for debugging.

With --all-mounts (or --identifiers) it scans further rideable types
(donkey, mule, skeleton horse, camel) and aggregates per-type writer evidence:
observed definitions, attribute lists and tag keys from Minecraft-kept records.
That evidence is the basis for extending the synthetic create path to new
mount types without guessing their NBT structure.

With --dump-nbt the report additionally contains the complete typed NBT tree
(tag type + value for every entry) and the raw record bytes as hex for the
selected identifiers. That is the level of detail a synthetic writer for a
structurally different mount (camel: ChestItems, InventoryVersion, ...) needs.
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

ACTOR_PREFIX = b"actorprefix"
DIGP_PREFIX = b"digp"
IDENTIFIER_KEYS = ("identifier", "Identifier", "id", "Id", "EntityIdentifier")
DEFAULT_IDENTIFIERS = ("minecraft:horse",)
MOUNT_IDENTIFIERS = (
    "minecraft:horse",
    "minecraft:donkey",
    "minecraft:mule",
    "minecraft:skeleton_horse",
    "minecraft:camel",
)
KEY_ATTRIBUTE_NAMES = (
    "minecraft:health",
    "minecraft:movement",
    "minecraft:horse.jump_strength",
)
SUMMARY_KEYS = (
    "UniqueID",
    "Pos",
    "Rotation",
    "Variant",
    "Color",
    "Color2",
    "MarkVariant",
    "Temper",
    "Health",
    "IsTamed",
    "Saddled",
    "Chested",
    "NaturalSpawn",
    "Surface",
    "OnGround",
    "Persistent",
    "OwnerNew",
    "TargetID",
    "LeasherID",
    "Strength",
    "StrengthMax",
)
COMPARE_KEYS = (
    "Variant",
    "Color",
    "Color2",
    "MarkVariant",
    "Temper",
    "Health",
    "IsTamed",
    "Saddled",
    "Chested",
    "NaturalSpawn",
    "Surface",
    "OnGround",
    "Persistent",
    "OwnerNew",
    "TargetID",
    "LeasherID",
    "Strength",
    "StrengthMax",
)


@contextlib.contextmanager
def open_db(world_path: str):
    db = ReadonlyLevelDbAdapter(ensure_valid_world_path(world_path))
    try:
        yield db
    finally:
        db.close()


def safe_ascii(data: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in data)


def load_nbt(raw: bytes):
    try:
        return nbt.load(raw, **LOAD_KWARGS)
    except Exception:
        return None


def scalar(value: Any) -> Any:
    data = getattr(value, "py_data", None)
    if data is not None:
        return data
    data = getattr(value, "value", None)
    if data is not None and not callable(data):
        return data
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def preview_value(value: Any) -> Any:
    if isinstance(value, nbt.ListTag):
        return [preview_value(item) for item in value]
    if isinstance(value, nbt.CompoundTag):
        return {str(key): preview_value(value[key]) for key in value}
    return scalar(value)


def typed_nbt(value: Any) -> dict[str, Any]:
    """Serialize an NBT tag as {"type": ..., "value": ...} recursively.

    preview_value drops the tag types, but a synthetic writer must reproduce
    them exactly (ByteTag vs IntTag vs FloatTag), so the dump keeps them.
    """
    type_name = type(value).__name__.removesuffix("Tag") or type(value).__name__
    if isinstance(value, nbt.CompoundTag):
        return {"type": "Compound", "value": {str(key): typed_nbt(value[key]) for key in value}}
    if isinstance(value, nbt.ListTag):
        return {"type": "List", "value": [typed_nbt(item) for item in value]}
    if isinstance(value, (nbt.ByteArrayTag, nbt.IntArrayTag, nbt.LongArrayTag)):
        return {"type": type_name, "value": [int(item) for item in value]}
    return {"type": type_name, "value": scalar(value)}


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


def actor_suffix(key: bytes) -> bytes | None:
    if key.startswith(ACTOR_PREFIX) and len(key) == len(ACTOR_PREFIX) + 8:
        return key[len(ACTOR_PREFIX) :]
    return None


def unique_id_entry_from_suffix(suffix: bytes) -> bytes | None:
    if len(suffix) != 8:
        return None
    group = int.from_bytes(suffix[:4], "big", signed=False)
    local_id = int.from_bytes(suffix[4:], "big", signed=False)
    if group <= 0 or local_id <= 0:
        return None
    unique_id = -(group << 32) + local_id
    return unique_id.to_bytes(8, "little", signed=True)


def position(root: Any) -> dict[str, float] | None:
    if not isinstance(root, nbt.CompoundTag) or "Pos" not in root:
        return None
    pos = root.get("Pos")
    if not isinstance(pos, nbt.ListTag) or len(pos) < 3:
        return None
    try:
        return {"x": float(scalar(pos[0])), "y": float(scalar(pos[1])), "z": float(scalar(pos[2]))}
    except (TypeError, ValueError):
        return None


def digp_key_for_position(pos: dict[str, float]) -> bytes:
    chunk_x = math.floor(pos["x"] / 16)
    chunk_z = math.floor(pos["z"] / 16)
    return DIGP_PREFIX + int(chunk_x).to_bytes(4, "little", signed=True) + int(chunk_z).to_bytes(4, "little", signed=True)


def chunk_for_position(pos: dict[str, float]) -> dict[str, int]:
    return {"x": math.floor(pos["x"] / 16), "z": math.floor(pos["z"] / 16)}


def split_digp(value: bytes) -> list[bytes]:
    if len(value) % 8 != 0:
        return []
    return [value[index : index + 8] for index in range(0, len(value), 8)]


def root_summary(root: Any) -> dict[str, Any]:
    if not isinstance(root, nbt.CompoundTag):
        return {}
    summary = {key: preview_value(root[key]) for key in SUMMARY_KEYS if key in root}
    summary["tag_count"] = len(root)
    summary["tag_keys"] = [str(key) for key in root]
    if "definitions" in root:
        summary["definitions"] = preview_value(root["definitions"])
    if "internalComponents" in root:
        summary["internalComponents"] = preview_value(root["internalComponents"])
    attrs = root.get("Attributes") if "Attributes" in root else None
    if isinstance(attrs, nbt.ListTag):
        details = []
        names = []
        for attr in attrs:
            if isinstance(attr, nbt.CompoundTag):
                attr_json = preview_value(attr)
                details.append(attr_json)
                if "Name" in attr:
                    names.append(str(scalar(attr.get("Name"))))
        summary["attribute_names"] = names
        summary["attribute_count"] = len(attrs)
        summary["attribute_details"] = details
    return summary


def record_summary(db, key: bytes, raw: bytes, root: Any) -> dict[str, Any] | None:
    suffix = actor_suffix(key)
    pos = position(root)
    if suffix is None or pos is None:
        return None
    digp_key = digp_key_for_position(pos)
    try:
        digp_value = db.get(digp_key)
        digp_exists = True
    except KeyError:
        digp_value = b""
        digp_exists = False
    entries = split_digp(digp_value)
    unique_entry = unique_id_entry_from_suffix(suffix)
    info = root_summary(root)
    info.update(
        {
            "identifier": entity_identifier(root),
            "key_hex": key.hex(),
            "key_ascii": safe_ascii(key),
            "actor_suffix_hex": suffix.hex(),
            "raw_length": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "position": pos,
            "chunk": chunk_for_position(pos),
            "digp_key_hex": digp_key.hex(),
            "digp_exists": digp_exists,
            "digp_value_length": len(digp_value),
            "digp_entry_count": len(entries),
            "digp_entries_hex": [entry.hex() for entry in entries],
            "digp_contains_actor_suffix": suffix in entries,
            "unique_id_entry_hex": unique_entry.hex() if unique_entry else None,
            "digp_contains_unique_id_entry": unique_entry in entries if unique_entry else False,
        }
    )
    return info


def classify(record: dict[str, Any]) -> str:
    if record.get("digp_contains_actor_suffix"):
        if int(record.get("raw_length") or 0) >= 2700:
            return "likely_visible_minecraft_entity"
        return "indexed_but_short_nbt"
    if int(record.get("raw_length") or 0) < 2700:
        return "likely_injected_not_indexed"
    return "not_indexed"


def distance_sq(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_pos = left.get("position") or {}
    right_pos = right.get("position") or {}
    return sum((float(left_pos.get(axis, 0.0)) - float(right_pos.get(axis, 0.0))) ** 2 for axis in ("x", "y", "z"))


def attrs_by_name(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for attr in record.get("attribute_details") or []:
        if isinstance(attr, dict) and attr.get("Name"):
            result[str(attr["Name"])] = attr
    return result


def compare_records(problem: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    problem_tags = set(problem.get("tag_keys") or [])
    reference_tags = set(reference.get("tag_keys") or [])
    scalar_diffs = []
    for key in COMPARE_KEYS:
        if problem.get(key) != reference.get(key):
            scalar_diffs.append({"key": key, "problem": problem.get(key), "reference": reference.get(key)})
    problem_attrs = attrs_by_name(problem)
    reference_attrs = attrs_by_name(reference)
    attr_diffs = []
    for name in sorted(set(problem_attrs) | set(reference_attrs)):
        if problem_attrs.get(name) != reference_attrs.get(name):
            attr_diffs.append({"name": name, "problem": problem_attrs.get(name), "reference": reference_attrs.get(name)})
    return {
        "problem_suffix": problem["actor_suffix_hex"],
        "reference_suffix": reference["actor_suffix_hex"],
        "same_chunk": problem.get("chunk") == reference.get("chunk"),
        "distance": round(math.sqrt(distance_sq(problem, reference)), 3),
        "raw_length_delta_problem_minus_reference": int(problem.get("raw_length") or 0) - int(reference.get("raw_length") or 0),
        "problem_missing_tag_keys": sorted(reference_tags - problem_tags),
        "problem_extra_tag_keys": sorted(problem_tags - reference_tags),
        "scalar_differences": scalar_diffs,
        "attribute_differences": attr_diffs,
        "definitions": {"problem": problem.get("definitions"), "reference": reference.get("definitions")},
        "internalComponents": {"problem": problem.get("internalComponents"), "reference": reference.get("internalComponents")},
    }


def nearest_reference(problem: dict[str, Any], indexed: list[dict[str, Any]]) -> dict[str, Any] | None:
    same_identifier = [record for record in indexed if record.get("identifier") == problem.get("identifier")]
    candidates = same_identifier or indexed
    if not candidates:
        return None
    same_chunk = [record for record in candidates if record.get("chunk") == problem.get("chunk")]
    candidates = same_chunk or candidates
    return min(candidates, key=lambda record: distance_sq(problem, record))


def find_horses(
    world_path: str,
    identifiers: tuple[str, ...] = DEFAULT_IDENTIFIERS,
    dump_identifiers: tuple[str, ...] = (),
) -> dict[str, Any]:
    world_path = os.path.abspath(os.path.normpath(os.path.expanduser(world_path)))
    identifier_set = frozenset(identifiers or DEFAULT_IDENTIFIERS)
    dump_set = frozenset(dump_identifiers) & identifier_set
    records: list[dict[str, Any]] = []
    inspected = 0
    parsed = 0
    entity_like = 0
    with open_db(world_path) as db:
        for key, raw in db.iter_items():
            inspected += 1
            named = load_nbt(raw)
            if named is None:
                continue
            parsed += 1
            root = getattr(named, "tag", None)
            identifier = entity_identifier(root)
            if not identifier:
                continue
            entity_like += 1
            if identifier not in identifier_set:
                continue
            summary = record_summary(db, key, raw, root)
            if summary is None:
                continue
            summary["classification"] = classify(summary)
            if identifier in dump_set:
                summary["nbt_typed"] = typed_nbt(root)
                summary["raw_hex"] = raw.hex()
            records.append(summary)
    records.sort(key=lambda item: (item.get("position", {}).get("x", 0), item.get("position", {}).get("z", 0), item.get("actor_suffix_hex", "")))
    by_identifier: dict[str, int] = {}
    for record in records:
        name = str(record.get("identifier") or "?")
        by_identifier[name] = by_identifier.get(name, 0) + 1
    return {
        "success": True,
        "world": {"name": get_world_name(world_path), "folder_name": os.path.basename(world_path), "path": world_path},
        "scanned_identifiers": sorted(identifier_set),
        "dumped_identifiers": sorted(dump_set),
        "counts": {
            "inspected": inspected,
            "parsed_nbt": parsed,
            "entity_like": entity_like,
            "horses": len(records),
            "by_identifier": by_identifier,
            "raw_nbt_dumps": sum(1 for record in records if "nbt_typed" in record),
        },
        "records": records,
        "diagnosis": build_diagnosis(records),
        "writer_evidence": build_writer_evidence(records),
    }


def build_writer_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-identifier NBT structure evidence from Minecraft-kept records.

    Only digp-indexed records count as evidence: those survived (or were written
    by) Minecraft itself, so their definitions/attributes/tag keys are the
    template a synthetic writer for that mount type has to reproduce.
    """
    evidence: dict[str, dict[str, Any]] = {}
    for record in records:
        if not record.get("digp_contains_actor_suffix"):
            continue
        identifier = str(record.get("identifier") or "?")
        entry = evidence.setdefault(
            identifier,
            {
                "observed_records": 0,
                "definitions_variants": [],
                "attribute_name_variants": [],
                "key_attribute_bases": {},
                "tag_keys_always_present": None,
                "tag_keys_union": set(),
                "raw_length_min": None,
                "raw_length_max": None,
            },
        )
        entry["observed_records"] += 1
        definitions = record.get("definitions")
        if isinstance(definitions, list) and definitions not in entry["definitions_variants"]:
            entry["definitions_variants"].append(definitions)
        attribute_names = record.get("attribute_names")
        if isinstance(attribute_names, list) and attribute_names not in entry["attribute_name_variants"]:
            entry["attribute_name_variants"].append(attribute_names)
        for attr in record.get("attribute_details") or []:
            if isinstance(attr, dict) and attr.get("Name") in KEY_ATTRIBUTE_NAMES:
                bases = entry["key_attribute_bases"].setdefault(str(attr["Name"]), [])
                base = attr.get("Base")
                if base is not None and base not in bases:
                    bases.append(base)
        tag_keys = set(record.get("tag_keys") or [])
        if tag_keys:
            entry["tag_keys_union"] |= tag_keys
            entry["tag_keys_always_present"] = tag_keys if entry["tag_keys_always_present"] is None else entry["tag_keys_always_present"] & tag_keys
        raw_length = int(record.get("raw_length") or 0)
        entry["raw_length_min"] = raw_length if entry["raw_length_min"] is None else min(entry["raw_length_min"], raw_length)
        entry["raw_length_max"] = raw_length if entry["raw_length_max"] is None else max(entry["raw_length_max"], raw_length)
    for entry in evidence.values():
        entry["tag_keys_always_present"] = sorted(entry["tag_keys_always_present"] or set())
        entry["tag_keys_union"] = sorted(entry["tag_keys_union"])
    return evidence


def build_diagnosis(records: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = [record for record in records if record.get("digp_contains_actor_suffix")]
    not_indexed = [record for record in records if not record.get("digp_contains_actor_suffix")]
    short = [record for record in records if int(record.get("raw_length") or 0) < 2700]
    comparisons = []
    for problem in not_indexed:
        reference = nearest_reference(problem, indexed)
        if reference:
            comparisons.append(compare_records(problem, reference))
    return {
        "indexed_horses": len(indexed),
        "not_indexed_horses": len(not_indexed),
        "short_nbt_horses": len(short),
        "likely_visible_suffixes": [record["actor_suffix_hex"] for record in indexed],
        "likely_problem_suffixes": [record["actor_suffix_hex"] for record in not_indexed],
        "comparisons": comparisons,
        "next_action": "Inspect diagnosis.comparisons for missing tags, scalar differences and attribute differences."
        if comparisons
        else "Create one real horse with /summon and rerun this diagnostic."
        if not indexed
        else "No unindexed horses found in this snapshot.",
    }


def write_report(result: dict[str, Any], output: str | None) -> str:
    if output:
        path = Path(output)
    else:
        folder = result["world"]["folder_name"] or "world"
        path = Path.cwd() / f"horse_diagnostic_{folder}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def print_summary(result: dict[str, Any], output_path: str) -> None:
    world = result["world"]
    diagnosis = result["diagnosis"]
    by_identifier = result["counts"].get("by_identifier") or {}
    per_type = " ".join(f"{name.replace('minecraft:', '')}={count}" for name, count in sorted(by_identifier.items())) or "keine"
    print(f"Welt: {world['name']} ({world['folder_name']})")
    print(f"Mounts gefunden: {result['counts']['horses']} ({per_type})")
    print(f"digp verknuepft: {diagnosis['indexed_horses']}")
    print(f"digp fehlt:      {diagnosis['not_indexed_horses']}")
    print()
    for index, record in enumerate(result["records"], start=1):
        pos = record["position"]
        print(
            f"{index}. {str(record.get('identifier', '?')).replace('minecraft:', '')} "
            f"suffix={record['actor_suffix_hex']} "
            f"class={record['classification']} "
            f"pos=({pos['x']:.2f}, {pos['y']:.2f}, {pos['z']:.2f}) "
            f"raw={record['raw_length']} "
            f"digp={record['digp_contains_actor_suffix']}"
        )
    if diagnosis.get("comparisons"):
        print()
        print("Automatischer Vergleich:")
        for item in diagnosis["comparisons"]:
            print(
                f"- problem={item['problem_suffix']} reference={item['reference_suffix']} "
                f"same_chunk={item['same_chunk']} distance={item['distance']} "
                f"raw_delta={item['raw_length_delta_problem_minus_reference']} "
                f"missing_tags={len(item['problem_missing_tag_keys'])} "
                f"extra_tags={len(item['problem_extra_tag_keys'])} "
                f"attr_diffs={len(item['attribute_differences'])}"
            )
    dumped = result.get("dumped_identifiers") or []
    if dumped:
        dump_count = (result["counts"].get("raw_nbt_dumps") or 0) if isinstance(result.get("counts"), dict) else 0
        dump_types = " ".join(str(name).replace("minecraft:", "") for name in dumped)
        print()
        print(f"Raw-NBT-Dump im Report: {dump_count} Record(s) fuer {dump_types} (typisierter NBT-Baum + Roh-Hex).")
    evidence = result.get("writer_evidence") or {}
    if evidence:
        print()
        print("Writer-Evidenz (nur Minecraft-indizierte Records):")
        for identifier, entry in sorted(evidence.items()):
            variants = entry.get("definitions_variants") or []
            print(
                f"- {identifier.replace('minecraft:', '')}: {entry.get('observed_records')} Records, "
                f"{len(variants)} Definitions-Variante(n), raw {entry.get('raw_length_min')}..{entry.get('raw_length_max')}"
            )
            for definitions in variants:
                print(f"    definitions: {definitions}")
    print()
    print(f"Naechster Schritt: {diagnosis['next_action']}")
    print(f"Report: {output_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-command mount diagnostic for Bedrock LevelDB worlds.")
    parser.add_argument("--world", required=True, help="Direct world folder containing db/.")
    parser.add_argument("--output", help="Optional JSON report path. Default: horse_diagnostic_<world-folder>.json")
    parser.add_argument(
        "--all-mounts", action="store_true", help="Scan all rideable types (horse, donkey, mule, skeleton horse, camel) and collect per-type writer evidence."
    )
    parser.add_argument("--identifiers", help="Comma-separated entity identifiers to scan, e.g. minecraft:donkey,minecraft:mule. Overrides --all-mounts.")
    parser.add_argument(
        "--dump-nbt",
        nargs="?",
        const="all",
        metavar="IDENTIFIERS",
        help=(
            "Include the full typed NBT tree and raw hex bytes per record. Optional comma-separated identifiers limit the dump, "
            "e.g. --dump-nbt minecraft:camel; without a value all scanned identifiers are dumped."
        ),
    )
    args = parser.parse_args(argv)
    if args.identifiers:
        identifiers = tuple(part.strip() for part in args.identifiers.split(",") if part.strip())
    elif args.all_mounts:
        identifiers = MOUNT_IDENTIFIERS
    else:
        identifiers = DEFAULT_IDENTIFIERS
    if args.dump_nbt == "all":
        dump_identifiers = identifiers
    elif args.dump_nbt:
        dump_identifiers = tuple(part.strip() for part in args.dump_nbt.split(",") if part.strip())
    else:
        dump_identifiers = ()
    try:
        result = find_horses(args.world, identifiers=identifiers, dump_identifiers=dump_identifiers)
        output_path = write_report(result, args.output)
    except (OSError, ValueError, KeyError) as exc:
        print(f"horse_diagnostic: {exc}", file=sys.stderr)
        return 2
    print_summary(result, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
