"""Shared policy for identifiers in Mojang data that are no ordinary items."""

from __future__ import annotations

import re

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
