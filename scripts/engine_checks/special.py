"""Bounded special-editor cases and an independent typed-NBT oracle.

Only the writer under test imports the production special-item code. Expected
contents come from these synthetic requests, never from the editor's parser.
Engine gameplay/visuals are deliberately outside this persistence profile.
"""

from __future__ import annotations

from copy import deepcopy

from .cases import append_case, expected_snapshot
from .extended import ENCHANTMENT_IDS, ENCHANTMENT_NAMES
from .protocol import ProbeError


def child(name: str, count: int, slot: int = 0, **extra) -> dict:
    return {"slot": slot, "name": "minecraft:" + name, "count": count, "damage": 0, **extra}


def edit(kind: str, **data) -> dict:
    return {"kind": kind, "data": data}


def make_special_cases(observations: dict, limits: dict) -> list[dict]:
    required = {
        "bundle": 1,
        "yellow_bundle": 1,
        "undyed_shulker_box": 1,
        "blue_shulker_box": 1,
        "diamond": 64,
        "stone": 64,
        "ender_pearl": 16,
        "diamond_sword": 1,
        "writable_book": 1,
        "banner": 16,
        "firework_rocket": 64,
        "firework_star": 64,
    }
    for name, maximum in required.items():
        item_id = "minecraft:" + name
        measured = observations.get(item_id, {}).get("max_amount")
        if type(measured) is not int or measured != maximum or type(limits.get(item_id)) is not int or limits[item_id] != maximum:
            raise ProbeError(f"Special profile requires a measured, curated stack limit for {item_id}")
    durability = observations.get("minecraft:diamond_sword", {}).get("max_durability")
    if type(durability) is not int or durability <= 13:
        raise ProbeError("Special profile requires measured sword durability")
    cases = []

    def add(label, name, special_edit, *, revision=None, mode="create", **extra):
        append_case(
            cases,
            observations,
            "minecraft:writable_book" if name == "written_book" else "minecraft:" + name,
            mode,
            1,
            profile=label,
            special_edit=special_edit,
            revision=revision,
            name="§bProbe · " + label,
            lore=["Grüße 世界", "Persistence ✓"],
            **extra,
        )
        if name == "written_book":
            # The probe signs an engine-created writable book. No invented
            # registry entry or curated limit is needed for the resulting item.
            cases[-1]["id"] = "minecraft:written_book"
            cases[-1]["seed_book"] = {"pages": ["Seed page"], "title": "Seed book", "author": "Engine probe"}

    sword = child(
        "diamond_sword",
        1,
        63,
        damage=12,
        display_name="§aKlinge 世界",
        lore=["Grüße", "Line 2"],
        enchantments=[{"id": ENCHANTMENT_IDS["unbreaking"], "lvl": 3}],
    )
    for name, maximum in (("diamond", 64), ("ender_pearl", 16), ("diamond_sword", 1)):
        contents = [sword] if name == "diamond_sword" else [child(name, maximum, 63)]
        add("bundle_" + name, "bundle", edit("bundle", items=contents), revision={"special_edit": edit("bundle", items=[])} if name == "diamond" else None)
    add(
        "bundle_mixed_63",
        "bundle",
        edit("bundle", items=[child("diamond", 3), child("ender_pearl", 15, 63)]),
        revision={"special_edit": edit("bundle", items=[child("diamond", 4, 5), child("ender_pearl", 15, 63)])},
    )
    add(
        "bundle_nested_64",
        "yellow_bundle",
        edit(
            "bundle",
            items=[
                child("bundle", 1, 63, special_edit=edit("bundle", items=[child("diamond", 60, 63)])),
            ],
        ),
    )
    add("bundle_empty", "bundle", edit("bundle", items=[]), revision={"special_edit": edit("bundle", items=[child("diamond", 64, 63)])})
    add(
        "shulker_full",
        "undyed_shulker_box",
        edit("shulker", items=[child("diamond", 64, slot) for slot in range(27)]),
        revision={"special_edit": edit("shulker", items=[child("ender_pearl", 16, 26)])},
    )
    add(
        "shulker_nested",
        "blue_shulker_box",
        edit(
            "shulker",
            items=[
                child(
                    "yellow_bundle",
                    1,
                    26,
                    special_edit=edit(
                        "bundle",
                        items=[
                            child("writable_book", 1, 63, special_edit=edit("book", pages=[{"text": "Nested\nGrüße 世界"}])),
                        ],
                    ),
                ),
                {**sword, "slot": 0},
            ],
        ),
        revision={
            "special_edit": edit(
                "shulker",
                items=[
                    {**sword, "slot": 7, "from_slot": 0, "damage": 13},
                    child(
                        "yellow_bundle",
                        1,
                        0,
                        from_slot=26,
                        special_edit=edit(
                            "bundle",
                            items=[
                                child("writable_book", 1, 1, from_slot=63, special_edit=edit("book", pages=[{"source_index": 0, "text": "Nested revision ✓"}])),
                            ],
                        ),
                    ),
                ],
            )
        },
    )
    add("shulker_empty", "undyed_shulker_box", edit("shulker", items=[]))
    pages = [{"text": "Grüße 世界\n§lFormat\nLiteral \\n"}, {"text": ""}, {"text": "x" * 256}]
    add(
        "book_pages",
        "writable_book",
        edit("book", pages=pages),
        revision={"special_edit": edit("book", pages=[{"source_index": 2, "text": "x" * 256}, {"source_index": 0, "text": "Revised ✓"}])},
    )
    add("book_full", "writable_book", edit("book", pages=[{"text": f"Page {i + 1}"} for i in range(50)]), revision={"special_edit": edit("book", pages=[])})
    add(
        "book_signed",
        "written_book",
        edit("book", pages=pages, title="Synthetic title", author="Engine probe"),
        mode="decorate",
        revision={"special_edit": edit("book", pages=[{"source_index": 0, "text": "Signed revision"}], title="Revised title", author="Engine probe")},
    )
    patterns = [{"pattern": pattern, "color": color} for pattern, color in zip(("bs", "ts", "cre", "sku", "flo", "moj"), (0, 15, 4, 1, 2, 11), strict=True)]
    add(
        "banner_patterns",
        "banner",
        edit("banner", patterns=patterns),
        damage=11,
        data_value=11,
        revision={"special_edit": edit("banner", patterns=[{**patterns[i], "source_index": i} for i in (5, 0, 3)])},
    )
    add("banner_clear", "banner", edit("banner", patterns=patterns), damage=15, data_value=15, revision={"special_edit": edit("banner", patterns=[])})
    explosions = [
        {"shape": i % 5, "colors": [1, 4, 15], "fade": [0, 11] if i % 2 else [], "trail": bool(i % 2), "flicker": bool((i + 1) % 2)} for i in range(7)
    ]
    add(
        "rocket_effects",
        "firework_rocket",
        edit("fireworks", flight=3, explosions=explosions),
        revision={"special_edit": edit("fireworks", flight=1, explosions=[])},
    )
    add(
        "star_effect",
        "firework_star",
        edit("firework_star", explosions=[{**explosions[3], "colors": [1]}]),
        revision={"special_edit": edit("firework_star", explosions=[{**explosions[4], "source_index": 0, "colors": [4]}])},
    )
    return cases


def revision_cases(cases: list[dict]) -> list[dict]:
    """Keep the original case manifest immutable across both reload cycles."""
    result = deepcopy(cases)
    for case in result:
        revision = case.pop("revision", None)
        case["mode"] = "decorate" if revision is not None else "preserve"
        if revision is not None:
            case.update(revision)
    return result


def resolve_special_edit(request: dict, original) -> dict:
    """Bind test-plan slot references to this parent's actual stored row order.

    BDS may reorder or densify container rows. `from_slot` exists only in the
    probe manifest; production receives its regular parent-bound source_index.
    Expected contents stay independent of these origin lookups.
    """
    from mcbe_editor import nbt

    resolved = deepcopy(request)
    kind = resolved["kind"]
    if kind not in {"bundle", "shulker"}:
        return resolved
    key = "Items" if kind == "shulker" else "storage_item_component_content"
    originals = original.get("tag", {}).get(key, []) if original is not None else []
    for row in resolved["data"]["items"]:
        source = row.pop("from_slot", None)
        base = None
        if source is not None:
            matches = [(i, entry) for i, entry in enumerate(originals) if type(entry.get("Slot")) is nbt.ByteTag and entry["Slot"].py_data == source]
            if len(matches) != 1 or matches[0][1].get("Name", nbt.StringTag("")).py_data != row["name"]:
                raise ProbeError("Missing or ambiguous special revision origin")
            row["source_index"], base = matches[0]
        if "special_edit" in row:
            row["special_edit"] = resolve_special_edit(row["special_edit"], base)
    return resolved


def verify_special(item, request: dict) -> None:
    """Check only known persisted semantics; allow unrelated engine-owned tags."""
    from mcbe_editor import nbt

    from .nbt_roundtrip import disk_snapshot, empty_saved_slot

    missing = object()

    def field(parent, key, tag_type, default=missing):
        tag = parent.get(key)
        if tag is None and default is not missing:
            return default
        if type(tag) is not tag_type:
            raise ProbeError(f"Special NBT has missing or mistyped {key}")
        return tag if tag_type in (nbt.CompoundTag, nbt.ListTag) else tag.py_data

    def equal(actual, expected, key):
        if actual != expected:
            raise ProbeError(f"Special NBT changed {key}")

    def rows(parent, key, expected):
        result = field(parent, key, nbt.ListTag, [])
        if len(result) != len(expected) or any(type(row) is not nbt.CompoundTag for row in result):
            raise ProbeError(f"Special NBT changed {key} rows")
        return result

    def explosion(actual, expected):
        for key, prop in (("FireworkType", "shape"), ("FireworkTrail", "trail"), ("FireworkFlicker", "flicker")):
            equal(field(actual, key, nbt.ByteTag, 0), int(expected[prop]), key)
        for key, prop in (("FireworkColor", "colors"), ("FireworkFade", "fade")):
            equal(list(field(actual, key, nbt.ByteArrayTag, [])), expected[prop], key)

    kind, data = request["kind"], request["data"]
    tag = field(item, "tag", nbt.CompoundTag, nbt.CompoundTag())
    if kind in {"shulker", "bundle"}:
        capacity, key = (27, "Items") if kind == "shulker" else (64, "storage_item_component_content")
        actual = {}
        occupied = {}
        for entry in field(tag, key, nbt.ListTag, []):
            if type(entry) is not nbt.CompoundTag:
                raise ProbeError("Special NBT has an invalid child")
            slot = field(entry, "Slot", nbt.ByteTag)
            if not 0 <= slot < capacity or slot in actual:
                raise ProbeError("Special NBT has duplicate or invalid slots")
            actual[slot] = entry
            if not empty_saved_slot(entry):
                occupied[slot] = entry
        expected = {entry["slot"]: entry for entry in data["items"]}
        equal(occupied.keys(), expected.keys(), "occupied slots")
        for slot, payload in expected.items():
            child_case = {
                "case_id": f"nested/{slot}",
                "id": payload["name"],
                "amount": payload["count"],
                "name": payload.get("display_name", ""),
                "lore": payload.get("lore", []),
                "damage": payload.get("damage", 0),
                "durable": payload["name"] == "minecraft:diamond_sword",
                "enchantments": [{"id": ENCHANTMENT_NAMES[row["id"]], "level": row["lvl"]} for row in payload.get("enchantments", [])],
            }
            equal(disk_snapshot(occupied[slot], child_case), expected_snapshot(child_case), "child metadata")
            if "special_edit" in payload:
                verify_special(occupied[slot], payload["special_edit"])
        if kind == "bundle":
            equal(field(tag, "bundle_weight", nbt.IntTag, 4), 4 + sum(expected_weight(row) for row in data["items"]), "bundle weight")
    elif kind == "book":
        for actual, expected in zip(rows(tag, "pages", data["pages"]), data["pages"], strict=True):
            equal(field(actual, "text", nbt.StringTag, ""), expected["text"], "page text")
        for key in ("title", "author"):
            if key in data:
                equal(field(tag, key, nbt.StringTag), data[key], key)
        if "title" in data:
            equal(field(tag, "generation", nbt.IntTag), 0, "book generation")
    elif kind == "banner":
        equal(field(tag, "Type", nbt.IntTag, 0), 0, "banner type")
        for actual, expected in zip(rows(tag, "Patterns", data["patterns"]), data["patterns"], strict=True):
            equal(field(actual, "Pattern", nbt.StringTag), expected["pattern"], "pattern")
            equal(field(actual, "Color", nbt.IntTag), expected["color"], "pattern color")
    elif kind == "fireworks":
        firework = field(tag, "Fireworks", nbt.CompoundTag)
        equal(field(firework, "Flight", nbt.ByteTag, 1), data["flight"], "flight")
        for actual, expected in zip(rows(firework, "Explosions", data["explosions"]), data["explosions"], strict=True):
            explosion(actual, expected)
    elif kind == "firework_star":
        explosion(field(tag, "FireworksItem", nbt.CompoundTag), data["explosions"][0])
        # Explicit independent single-dye reference colors for these fixtures.
        colors = {(1,): -5231066, (4,): -12827478}
        equal(field(tag, "customColor", nbt.IntTag), colors[tuple(data["explosions"][0]["colors"])], "star color")
    else:
        raise ProbeError("Unknown special profile kind")


def expected_weight(payload: dict) -> int:
    if payload.get("special_edit", {}).get("kind") == "bundle":
        return 4 + sum(expected_weight(row) for row in payload["special_edit"]["data"]["items"])
    limits = {"minecraft:diamond": 64, "minecraft:stone": 64, "minecraft:ender_pearl": 16, "minecraft:diamond_sword": 1, "minecraft:writable_book": 1}
    return payload["count"] * (64 // limits[payload["name"]])


def rejected_container_cases() -> list[dict]:
    """Editor guards, separate from what the engine accepts during gameplay."""
    result = []
    for kind, parent in (("bundle", "minecraft:bundle"), ("shulker", "minecraft:undyed_shulker_box")):
        children = [[child(name, count)] for name, count in (("diamond", 65), ("ender_pearl", 17), ("diamond_sword", 2), ("blue_shulker_box", 1))]
        children += [[child("diamond", 1, 64 if kind == "bundle" else 27)], [child("diamond", 1), child("stone", 1)]]
        if kind == "bundle":
            children += [
                [child("diamond", 64), child("stone", 1, 1)],
                [child("bundle", 1, special_edit=edit("bundle", items=[child("diamond", 61)]))],
                [child("diamond_sword", 1), child("stone", 1, 1)],
            ]
        result.extend({"slot": 0, "name": parent, "count": 1, "damage": 0, "special_edit": edit(kind, items=items)} for items in children)
    return result


def verify_special_rejections() -> int:
    from mcbe_editor import nbt
    from mcbe_editor.inventory import build_inventory_nbt
    from mcbe_editor.item_data import ENCHANTMENTS

    cases = rejected_container_cases()
    for payload in cases:
        original = nbt.CompoundTag({"Inventory": nbt.ListTag([], 10)})
        before = original.save_to()
        try:
            build_inventory_nbt(original, [deepcopy(payload)], ENCHANTMENTS)
        except ValueError:
            if original.save_to() != before:
                raise ProbeError("Rejected special edit mutated its original") from None
        else:
            raise ProbeError("Editor accepted an invalid container edit")
    return len(cases)
