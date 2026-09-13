"""Bedrock NBT I/O helpers.

Minecraft Bedrock LevelDB player records are little-endian NBT and their
strings use Bedrock UTF-8 with escaped invalid bytes, not Java modified UTF-8.
Keep the explicit codec options here for all player and entity I/O.
"""

from typing import Any, cast

from mcbe_editor import nbt

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


def literal_string_tag(value: str) -> Any:
    """Create user text with literal UTF-8 bytes, retaining the codec's raw form.

    Existing escaped strings keep their usual codec semantics. Explicit UTF-8
    applies only when creating a new tag from a user's Unicode text.
    """
    codec: Any = nbt
    raw = codec.NamedTag(codec.StringTag(value)).save_to(**{**SAVE_KWARGS, "string_encoder": str.encode})
    return load_player_nbt(raw).tag
