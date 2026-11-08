"""Conservative editing of the vanilla villager's eight supply slots."""

from __future__ import annotations

from typing import Any

from . import item_data, nbt
from .entities import scalar_integer
from .i18n import request_locale, t
from .inventory import _build_item_compound, validate_inventory_item

CAPACITY = 8
# Vanilla shareables with stored_in_inventory, including the farmer's supplies.
# https://github.com/Mojang/bedrock-samples/blob/v1.26.60.5/behavior_pack/entities/villager_v2.json
SUPPLY_ITEMS = (
    "minecraft:bread",
    "minecraft:carrot",
    "minecraft:potato",
    "minecraft:beetroot",
    "minecraft:wheat",
    "minecraft:wheat_seeds",
    "minecraft:beetroot_seeds",
    "minecraft:torchflower_seeds",
    "minecraft:pitcher_pod",
    "minecraft:bone_meal",
)
_ITEM_FIELDS = {"Slot", "Name", "Count", "Damage", "WasPickedUp"}


def allowed_items() -> list[dict[str, Any]]:
    catalog = item_data.catalog_values()["ITEMS"]
    language = 1 if request_locale() == "en" else 0
    return [
        {"name": name, "label": catalog.get(name, [name, name])[language], "max_count": min(64, item_data.get_max_stack(name))}
        for name in SUPPLY_ITEMS
        if item_data.is_addable_item_id(name)
    ]


def normalize_inventory_changes(changes: Any) -> dict[str, Any]:
    if not isinstance(changes, dict) or set(changes) != {"inventory"}:
        raise ValueError(t("Vorräte werden getrennt von Gesundheitswerten geändert."))
    patches = changes["inventory"]
    if not isinstance(patches, list) or not 1 <= len(patches) <= CAPACITY:
        raise ValueError(t("Eine Vorratsänderung muss zwischen 1 und 8 Slots enthalten."))
    normalized = []
    seen = set()
    allowed = {item["name"]: item["max_count"] for item in allowed_items()}
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) != {"slot", "item"}:
            raise ValueError(t("Eine Vorratsänderung benötigt einen Slot und ein Item oder einen ausdrücklich leeren Slot."))
        slot = patch["slot"]
        if type(slot) is not int or slot not in range(CAPACITY) or slot in seen:
            raise ValueError(t("Vorratsslots müssen eindeutig sein und zwischen 0 und 7 liegen."))
        seen.add(slot)
        item = patch["item"]
        if item is None:
            normalized.append({"slot": slot, "item": None})
            continue
        if not isinstance(item, dict) or set(item) != {"name", "count"} or not isinstance(item.get("name"), str) or item["name"] not in allowed:
            raise ValueError(t("Für Vorräte sind nur die angebotenen Nahrung- und Saatgut-Items sowie Knochenmehl erlaubt."))
        if type(item["count"]) is not int or not 1 <= item["count"] <= allowed[item["name"]]:
            raise ValueError(t("Die Vorratsmenge muss eine ganze Zahl innerhalb der Stapelgrenze sein."))
        # Reuse the normal item policy as well as the narrower supply allowlist.
        validated = validate_inventory_item({"slot": slot, **item}, {}, allowed_slots=range(CAPACITY))
        normalized.append({"slot": slot, "item": {"name": validated["name"], "count": validated["count"]}})
    return {"inventory": sorted(normalized, key=lambda patch: patch["slot"])}


def _item_view(item: nbt.CompoundTag) -> dict[str, Any] | None:
    name = item.get("Name")
    name = name.py_data if isinstance(name, nbt.StringTag) else None
    count = scalar_integer(item.get("Count"))
    if isinstance(item.get("Count"), nbt.ByteTag) and count is not None:
        count &= 0xFF
    if name == "" and count == 0:
        return None
    return {"name": name, "count": count}


def _item_reason(item: nbt.CompoundTag, options: dict[str, int]) -> str | None:
    if set(item) != _ITEM_FIELDS or not isinstance(item.get("Name"), nbt.StringTag):
        return t("Dieser Slot enthält unbekannte Item-Daten und bleibt unverändert.")
    if (
        not isinstance(item.get("Count"), nbt.ByteTag)
        or not isinstance(item.get("Damage"), nbt.ShortTag)
        or item["Damage"].py_data != 0
        or not isinstance(item.get("WasPickedUp"), nbt.ByteTag)
        or item["WasPickedUp"].py_data not in (0, 1)
    ):
        return t("Dieser Slot enthält unbekannte Item-Daten und bleibt unverändert.")
    name, count = item["Name"].py_data, item["Count"].py_data
    if name == "" and count == 0:
        return None
    if name not in options or not 1 <= count <= options[name]:
        return t("Dieses Item oder seine Menge wird im Vorratseditor nur angezeigt.")
    return None


def inventory_state(tag: nbt.CompoundTag, *, blocked_reason: str | None = None) -> dict[str, Any]:
    """Recognize the fixed Bedrock ChestItems representation without guessing.

    Native records have eight Compound entries, including explicit empty slots,
    with Byte Slot values matching their list indexes. Other containers and
    InventoryVersion are outside this editor's write scope.
    """
    options = allowed_items()
    allowed = {item["name"]: item["max_count"] for item in options}
    entries = tag.get("ChestItems")
    reason = blocked_reason
    if entries is None:
        reason = reason or t("Ein gespeichertes Vorratsinventar fehlt. Es wird kein unbekanntes Inventarformat angelegt.")
    elif "Inventory" in tag or "Items" in tag:
        reason = reason or t("Mehrere Inventarstrukturen verhindern eine eindeutige Vorratsbearbeitung.")
    elif not isinstance(entries, nbt.ListTag) or len(entries) != CAPACITY or entries.list_data_type != nbt.CompoundTag.tag_id:
        reason = reason or t("Das Vorratsinventar hat kein unterstütztes Format mit genau 8 Slots.")
    elif any(not isinstance(item.get("Slot"), nbt.ByteTag) or item["Slot"].py_data != index for index, item in enumerate(entries)):
        reason = reason or t("Die gespeicherten Vorratsslots sind unvollständig, doppelt oder anders angeordnet.")
    structure_valid = (
        isinstance(entries, nbt.ListTag)
        and entries.list_data_type == nbt.CompoundTag.tag_id
        and len(entries) == CAPACITY
        and all(isinstance(item.get("Slot"), nbt.ByteTag) and item["Slot"].py_data == index for index, item in enumerate(entries))
    )
    slots = []
    for slot in range(CAPACITY):
        item = entries[slot] if structure_valid else None
        item_reason = reason or (_item_reason(item, allowed) if item is not None else None)
        slots.append({"slot": slot, "item": _item_view(item) if item is not None else None, "editable": item_reason is None, "reason": item_reason})
    return {
        "capacity": CAPACITY,
        "present": entries is not None,
        "editable": not reason and any(slot["editable"] for slot in slots),
        "reason": reason,
        "slots": slots,
        "allowed_items": options,
    }


def patch_inventory(tag: nbt.CompoundTag, patches: list[dict[str, Any]]) -> None:
    """Apply already normalized patches only to validated native supply slots."""
    state = inventory_state(tag)
    if not state["editable"]:
        raise ValueError(state["reason"] or t("Das Vorratsinventar kann nicht sicher bearbeitet werden."))
    for patch in patches:
        slot = patch["slot"]
        if not state["slots"][slot]["editable"]:
            raise ValueError(state["slots"][slot]["reason"])
    for patch in patches:
        slot, item = patch["slot"], patch["item"]
        original = tag["ChestItems"][slot]
        if item == state["slots"][slot]["item"]:
            continue
        if item is None:
            # Retain the fixed list shape and each slot's native bookkeeping.
            replacement = original.copy()
            replacement["Name"] = nbt.StringTag("")
            replacement["Count"] = nbt.ByteTag(0)
        else:
            validated = validate_inventory_item({"slot": slot, **item}, {}, allowed_slots=range(CAPACITY))
            base = original if original["Name"].py_data == item["name"] else None
            replacement = _build_item_compound(base, validated, "Vorrat", False)
            replacement["WasPickedUp"] = original["WasPickedUp"]
        tag["ChestItems"][slot] = replacement
