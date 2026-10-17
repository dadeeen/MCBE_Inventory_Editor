"""Nested item storage with parent-bound origins and Bedrock bundle weights."""

from __future__ import annotations

from copy import deepcopy

from . import nbt
from .item_data import get_max_stack, has_verified_stack_limit
from .special_items import LIMITS, compound, compound_list, exact_fields, integer, kind_for_item, kind_for_name, reject, rows, scalar, set_scalar

CONTAINER_KEYS = {"shulker": "Items", "bundle": "storage_item_component_content"}
CAPACITIES = {"shulker": 27, "bundle": 64}
BUNDLE_OVERHEAD = 4


def _is_empty_entry(item):
    # Reuse the inventory reader's placeholder contract without introducing an
    # eager cycle: the inventory reader describes contents through this module.
    from .inventory import _item_entry_is_empty_placeholder

    return _item_entry_is_empty_placeholder(item)


def _entries(item, kind):
    tag = compound(item, "tag")
    entries = compound_list(tag, CONTAINER_KEYS[kind], CAPACITIES[kind])
    seen = set()
    for entry in entries:
        slot = integer(scalar(entry, "Slot", nbt.ByteTag, -1), 0, CAPACITIES[kind] - 1)
        if slot in seen:
            reject()
        seen.add(slot)
    if kind == "bundle":
        integer(scalar(tag, "bundle_weight", nbt.IntTag, BUNDLE_OVERHEAD), 0, 2**31 - 1)
    return entries


def read_contents(item, kind, parse_child, *, depth, budget):
    items = []
    for index, entry in enumerate(_entries(item, kind)):
        parsed = parse_child(entry, depth + 1, budget)
        if parsed is not None:
            # Dense engine-created bundles include 64 records even when empty.
            # Count represented items, as the writer does, not placeholders.
            # Per-container slot bounds and the depth limit still bound scans.
            budget[0] -= 1
            if budget[0] < 0:
                reject()
            parsed["source_index"] = index
            items.append(parsed)
    return {"items": items}


def item_weight(item, *, depth=0):
    """Weight inside a bundle; an inner bundle includes its own four units."""
    if _is_empty_entry(item):
        return 0
    # The inventory reader preserves every integer Count representation. Its
    # numeric value determines weight; an untouched wider tag is safe too.
    count_tag = item.get("Count")
    if count_tag is not None and type(count_tag) not in (nbt.ByteTag, nbt.ShortTag, nbt.IntTag, nbt.LongTag):
        reject()
    count = count_tag.py_data if count_tag is not None else 0
    if count == 0:
        return 0
    if depth >= LIMITS["depth"]:
        reject()
    integer(count, 1, 127)
    name = scalar(item, "Name", nbt.StringTag, "")
    kind = kind_for_name(name)
    if kind == "shulker":
        reject("Shulkerkisten dürfen nicht in Bundles oder andere Shulkerkisten gelegt werden.")
    if kind == "bundle":
        if count != 1:
            reject("Ein Bundle im Container muss die Menge 1 haben.")
        return BUNDLE_OVERHEAD + sum(item_weight(child, depth=depth + 1) for child in _entries(item, "bundle"))
    if not has_verified_stack_limit(name):
        reject("Das Gewicht dieses Items ist ungeprüft. Der Bundle-Inhalt kann nicht sicher geändert werden.")
    maximum = get_max_stack(name)
    if maximum not in {1, 16, 64}:
        reject("Das Gewicht dieses Items ist ungeprüft. Der Bundle-Inhalt kann nicht sicher geändert werden.")
    return count * (64 // maximum)


def empty_slot(slot):
    return nbt.CompoundTag(
        {"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(slot), "WasPickedUp": nbt.ByteTag(0)}
    )


def write_contents(item, kind, data, build_child, *, depth, budget):
    exact_fields(data, {"items"})
    capacity = CAPACITIES[kind]
    originals = _entries(item, kind)
    # Use the same distinction between visible items and safe placeholders as
    # the reader, including the less common empty records it preserves.
    # Empty records may use air, absent Count, or another preserved integer type.
    empty_slots = {scalar(entry, "Slot", nbt.ByteTag, -1): entry for entry in originals if _is_empty_entry(entry)}
    result, seen_slots, seen_sources = {}, set(), set()
    for child in rows(data["items"], capacity):
        budget[0] -= 1
        if budget[0] < 0:
            reject()
        slot = integer(child.get("slot"), 0, capacity - 1)
        if slot in seen_slots:
            reject("Ein Container-Slot ist mehrfach belegt.")
        seen_slots.add(slot)
        source = child.get("source_index")
        base = None
        if source is not None:
            integer(source, 0, len(originals) - 1)
            if source in seen_sources:
                reject("Ein Originaleintrag wird im Spezialeditor mehrfach verwendet.")
            seen_sources.add(source)
            base = originals[source]
        built = build_child(child, base, capacity, depth + 1, budget)
        if kind_for_item(built) == "shulker":
            reject("Shulkerkisten dürfen nicht in Bundles oder andere Shulkerkisten gelegt werden.")
        result[slot] = built
    tag = compound(item, "tag")
    if kind == "bundle":
        weight = sum(item_weight(child, depth=depth + 1) for child in result.values())
        if weight > 64:
            reject("Das Bundle ist zu voll. Der Inhalt darf höchstens 64 Gewichtseinheiten belegen.")
        # Engine-created bundles carry 64 slots, including canonical empty items.
        # Preserve existing empty records where possible instead of reshaping them.
        entries = [result.get(slot) or (deepcopy(empty_slots[slot]) if slot in empty_slots else empty_slot(slot)) for slot in range(capacity)]
        set_scalar(tag, "bundle_weight", weight + BUNDLE_OVERHEAD, nbt.IntTag)
    else:
        # Keep the original sequence and untouched empty records. Only deleted
        # occupied slots disappear; newly occupied slots append deterministically.
        entries = []
        remaining = dict(result)
        for original in originals:
            slot = scalar(original, "Slot", nbt.ByteTag, -1)
            if slot in remaining:
                entries.append(remaining.pop(slot))
            elif slot in empty_slots:
                entries.append(deepcopy(original))
        entries.extend(remaining[slot] for slot in sorted(remaining))
    tag[CONTAINER_KEYS[kind]] = nbt.ListTag(entries, 10)
    item["tag"] = tag
