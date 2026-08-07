"""Bedrock NBT I/O helpers.

Minecraft Bedrock LevelDB player records are little-endian NBT and their
strings are UTF-8-ish, not Java's modified UTF-8.  Amulet's defaults target
Java NBT, so always use the Bedrock decoder/encoder here.  Without this,
valid Bedrock player data that contains literal NUL bytes inside string
payloads can fail with mutf-8 UnicodeDecodeError and get misclassified as
unreadable.
"""

from typing import Any, cast

import amulet_nbt as nbt

LOAD_KWARGS: dict[str, Any] = {
    "compressed": False,
    "little_endian": True,
    "string_decoder": nbt.utf8_escape_decoder,
}

SAVE_KWARGS: dict[str, Any] = {
    "compressed": False,
    "little_endian": True,
    "string_encoder": nbt.utf8_escape_encoder,
}


def load_player_nbt(raw_bytes: bytes) -> Any:
    """Load an uncompressed little-endian Bedrock player NBT NamedTag."""
    return nbt.load(raw_bytes, **LOAD_KWARGS)


def save_player_nbt(named_tag: Any) -> bytes:
    """Serialize a Bedrock player NBT NamedTag without Java MUTF-8 encoding."""
    return cast(bytes, named_tag.save_to(**SAVE_KWARGS))
