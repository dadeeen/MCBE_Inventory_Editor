"""Shared policy for technical identifiers exposed by Mojang registries."""

from __future__ import annotations

import re

TECHNICAL_BLOCK_ONLY_ID_PATTERNS = (
    re.compile(r"_double_slab$"),
    re.compile(r"^minecraft:double_(?:stone|wooden)_(?:block_)?slab\d?$"),
    re.compile(r"_standing_sign$"),
    re.compile(r"_wall_sign$"),
)


def is_technical_block_only_item_id(item_id: str) -> bool:
    """Return whether an identifier represents a technical block state."""

    normalized = str(item_id or "").strip().lower()
    return any(pattern.search(normalized) for pattern in TECHNICAL_BLOCK_ONLY_ID_PATTERNS)
