"""Shared Vanilla identifier, registry and compatibility policies."""

from __future__ import annotations

import re
from typing import Any

from .path_safety import is_unsafe_windows_name


def is_vanilla_registry_id(value: object) -> bool:
    """Accept an optional Vanilla namespace and one portable identifier."""
    if not isinstance(value, str):
        return False
    name = value.removeprefix("minecraft:")
    return re.fullmatch(r"[a-z0-9_.-]+", name) is not None and not is_unsafe_windows_name(name)


def release_version_key(value: object) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)+)", str(value or "").strip(), flags=re.IGNORECASE)
    if not match:
        return ()
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def validated_behavior_item_source(raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Item-DB-Abschnitt behavior_item_source muss ein Objekt sein.")
    result: dict[str, Any] = {
        "resource_pack_release": str(raw.get("resource_pack_release", "") or "").strip(),
    }
    for field in ("stack_limit_items", "durability_items"):
        values = raw.get(field, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"Item-DB-Abschnitt behavior_item_source.{field} muss eine Liste von Item-IDs sein.")
        result[field] = frozenset(item_id for value in values if (item_id := str(value or "").strip().lower()) and ":" in item_id)
    return result


def catalog_registry(raw: dict[str, Any], *, allow_legacy_fallback: bool = True) -> dict[str, frozenset[str]]:
    """Read positive and technical IDs, including the pre-registry format."""

    def checked_id(value: object, field: str) -> str:
        if isinstance(value, str) and (
            is_vanilla_registry_id(value) or (not value.startswith("minecraft:") and re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", value))
        ):
            return value
        raise ValueError(f"Ungültige Item-ID in {field}.")

    def ids(field: str) -> frozenset[str]:
        values = raw.get(field, [])
        if not isinstance(values, list) or (field == "addable_items" and field in raw and not values):
            raise ValueError(f"Ungültige Item-Liste in {field}.")
        return frozenset(checked_id(value, field) for value in values)

    named = frozenset(checked_id(value, "items") for value in raw["items"])
    block_only = ids("block_only_items")
    addable = ids("addable_items")
    if allow_legacy_fallback and "addable_items" not in raw:
        addable = frozenset(key for key in named if not is_non_item_lang_key_id(key)) - block_only
    technical = frozenset(key for key in addable if is_technical_block_only_item_id(key))
    return {
        "ADDABLE_ITEM_IDS": addable - technical,
        "BLOCK_ITEM_IDS": ids("block_items"),
        "BLOCK_ONLY_ITEM_IDS": block_only | technical,
        "UNREVIEWED_ITEM_IDS": frozenset(),
    }


def apply_reviewed_registry(current: dict[str, Any], bundled: dict[str, frozenset[str]], *, newer_positive_registry: bool) -> None:
    """Use a newer explicit registry in full, otherwise retain the reviewed IDs."""
    reviewed = bundled["ADDABLE_ITEM_IDS"]
    current["BLOCK_ITEM_IDS"] |= bundled["BLOCK_ITEM_IDS"]
    current["BLOCK_ONLY_ITEM_IDS"] |= bundled["BLOCK_ONLY_ITEM_IDS"]
    if reviewed:
        if newer_positive_registry:
            current["UNREVIEWED_ITEM_IDS"] = current["ADDABLE_ITEM_IDS"] - reviewed
        else:
            current["ADDABLE_ITEM_IDS"] = reviewed


TECHNICAL_BLOCK_ONLY_ID_PATTERNS = (
    re.compile(r"_double_slab$"),
    re.compile(r"^minecraft:double_(?:stone|wooden)_(?:block_)?slab\d?$"),
    re.compile(r"_standing_sign$"),
    re.compile(r"_wall_sign$"),
)


# Tooltip and message lines of the vanilla language files, not items. Their
# keys look like item names (item.canBreak=Can break:, item.unbreakable=,
# item.itemLock.cantDrop=, item.worldbuilder.block.failed=), so an earlier
# generator and the updater's legacy key pattern took them for item IDs. None of
# them is in Mojang's item registry or in Microsoft's item list.
NON_ITEM_LANG_KEY_IDS = frozenset(
    {
        "minecraft:armor",
        "minecraft:canbreak",
        "minecraft:canplace",
        "minecraft:customproperties",
        "minecraft:dyed",
        "minecraft:itemlock",
        "minecraft:unbreakable",
        "minecraft:worldbuilder",
    }
)


def is_technical_block_only_item_id(item_id: str) -> bool:
    """Return whether an identifier represents a technical block state."""

    normalized = str(item_id or "").strip().lower()
    return any(pattern.search(normalized) for pattern in TECHNICAL_BLOCK_ONLY_ID_PATTERNS)


def is_non_item_lang_key_id(item_id: str) -> bool:
    """Return whether an identifier names a tooltip line instead of an item."""

    normalized = str(item_id or "").strip().lower()
    if normalized and ":" not in normalized:
        normalized = f"minecraft:{normalized}"
    return normalized in NON_ITEM_LANG_KEY_IDS
