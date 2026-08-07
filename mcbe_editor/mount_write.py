"""Experimental Bedrock entity write helpers for Mounts.

This module intentionally supports only a minimal minecraft:horse create path.
It writes a new actorprefix record and updates the matching digp chunk index.
The web route is responsible for CSRF, read-only blocking, server guard checks,
presence conflict checks and the final write gate.
"""

from __future__ import annotations

import contextlib
import math
import os
import random
from dataclasses import dataclass
from typing import Any

import amulet_nbt as nbt

from .backup import create_backup, get_backups_dir, prune_backups, remove_backup_after_aborted_write
from .bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from .db import close_db_preserving_active_exception
from .i18n import t
from .mount_profile import (
    HORSE_TEMPER_MAX,
    HORSE_TEMPER_MIN,
    horse_profile_attribute_values,
    horse_profile_summary,
    normalize_horse_profile,
)
from .mounts import MOUNT_TYPE_DEFINITIONS
from .players import decode_player_key
from .service_errors import denied_write_actor, denied_write_permission_hint
from .world import ensure_valid_world_path

ACTOR_PREFIX = b"actorprefix"
DIGP_PREFIX = b"digp"
MAX_DIGP_VALUE_BYTES = 8 * 4096
MIN_ENTITY_ACTOR_GROUP = 2
EQUINE_TEMPLATE_IDENTIFIERS = ("minecraft:horse", "minecraft:donkey", "minecraft:mule")
CREATE_MODE_AUTO = "auto"
CREATE_MODE_SYNTHETIC_FULL = "synthetic_full"
CREATE_MODE_TEMPLATE_CLONE = "template_clone"
CREATE_MODES = (CREATE_MODE_AUTO, CREATE_MODE_SYNTHETIC_FULL, CREATE_MODE_TEMPLATE_CLONE)
MIN_PLAUSIBLE_HORSE_NBT_BYTES = 2700
MIN_PLAUSIBLE_HORSE_TAG_COUNT = 60


@dataclass(frozen=True)
class EquineTemplate:
    identifier: str
    value: bytes


@dataclass(frozen=True)
class HorseMountRecord:
    actor_key: bytes
    actor_value: bytes
    digp_key: bytes
    digp_value: bytes
    unique_id: int
    position: dict[str, float]
    create_mode: str
    template_identifier: str | None = None
    horse_profile: dict[str, Any] | None = None
    mount_type: str = "minecraft:horse"
    mount_stats: dict[str, Any] | None = None
    tamed: bool = False
    owner_unique_id: int | None = None
    previous_digp_value: bytes = b""


def normalize_create_mode(value: Any) -> str:
    if value in (None, ""):
        return CREATE_MODE_AUTO
    mode = str(value).strip()
    if mode not in CREATE_MODES:
        raise ValueError(t("Ungültiger Pferd-Create-Modus: {mode}", mode=mode))
    return mode


def _float_value(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} muss eine Zahl sein.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} muss eine Zahl sein.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field_name} muss endlich sein.")
    return result


def normalize_mount_position(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("selected_position muss ein Objekt mit x/y/z sein.")
    return {
        "x": round(_float_value(value.get("x"), "selected_position.x"), 3),
        "y": round(_float_value(value.get("y"), "selected_position.y"), 3),
        "z": round(_float_value(value.get("z"), "selected_position.z"), 3),
    }


def actor_key_suffix(actor_key: bytes) -> bytes:
    if not actor_key.startswith(ACTOR_PREFIX) or len(actor_key) != len(ACTOR_PREFIX) + 8:
        raise ValueError("Ungültiger actorprefix-Key.")
    return actor_key[len(ACTOR_PREFIX) :]


def _parse_actor_key(actor_key: bytes) -> tuple[int, int] | None:
    if not actor_key.startswith(ACTOR_PREFIX) or len(actor_key) != len(ACTOR_PREFIX) + 8:
        return None
    suffix = actor_key_suffix(actor_key)
    group = int.from_bytes(suffix[:4], "big", signed=False)
    local_id = int.from_bytes(suffix[4:], "big", signed=False)
    if group <= 0 or local_id <= 0:
        return None
    return group, local_id


def unique_id_from_actor_key(actor_key: bytes) -> int:
    parsed = _parse_actor_key(actor_key)
    if parsed is None:
        raise ValueError("Ungültiger actorprefix-Key.")
    group, local_id = parsed
    return -(group << 32) + local_id


def digp_entry_for_actor_key(actor_key: bytes) -> bytes:
    """Return the 8-byte actor reference used by Bedrock digp chunk indexes."""

    return actor_key_suffix(actor_key)


def _actor_key_from_parts(group: int, local_id: int) -> bytes:
    return ACTOR_PREFIX + group.to_bytes(4, "big", signed=False) + local_id.to_bytes(4, "big", signed=False)


def next_actor_key(existing_keys: list[bytes]) -> bytes:
    used = {key for key in existing_keys if _parse_actor_key(key) is not None}
    groups: dict[int, int] = {}
    for key in used:
        parsed = _parse_actor_key(key)
        if parsed is None:
            continue
        group, local_id = parsed
        groups[group] = max(groups.get(group, 0), local_id)

    # Minecraft-created persisted entities in the inspected Bedrock worlds used
    # actor groups >= 2, while the injected group-1 horse was accepted on disk
    # but removed from digp when Minecraft loaded the world. Prefer the highest
    # existing entity-like group, but never start below group 2.
    group = max(max(groups, default=0), MIN_ENTITY_ACTOR_GROUP)
    local_id = groups.get(group, 0) + 1
    while local_id <= 0xFFFFFFFF:
        candidate = _actor_key_from_parts(group, local_id)
        if candidate not in used:
            return candidate
        local_id += 1

    for next_group in range(group + 1, 0xFFFFFFFF):
        candidate = _actor_key_from_parts(next_group, 1)
        if candidate not in used:
            return candidate
    raise ValueError("Kein freier actorprefix-Key gefunden.")


def chunk_coordinates_for_position(position: dict[str, float]) -> tuple[int, int]:
    x = _float_value(position.get("x"), "selected_position.x")
    z = _float_value(position.get("z"), "selected_position.z")
    chunk_x = math.floor(x / 16)
    chunk_z = math.floor(z / 16)
    if not -(2**31) <= chunk_x < 2**31 or not -(2**31) <= chunk_z < 2**31:
        raise ValueError("Mount-Position liegt außerhalb des unterstützten Chunk-Koordinatenbereichs.")
    return int(chunk_x), int(chunk_z)


def digp_key_for_position(position: dict[str, float]) -> bytes:
    chunk_x, chunk_z = chunk_coordinates_for_position(position)
    return DIGP_PREFIX + chunk_x.to_bytes(4, "little", signed=True) + chunk_z.to_bytes(4, "little", signed=True)


def split_digp_value(value: bytes | None) -> list[bytes]:
    raw = value or b""
    if len(raw) % 8 != 0:
        raise ValueError("digp-Wert hat eine unerwartete Länge und wird nicht verändert.")
    if len(raw) > MAX_DIGP_VALUE_BYTES:
        raise ValueError("digp-Wert ist unerwartet groß und wird nicht verändert.")
    return [raw[index : index + 8] for index in range(0, len(raw), 8)]


def merge_digp_value(existing_value: bytes | None, actor_entry: bytes) -> bytes:
    if len(actor_entry) != 8:
        raise ValueError("Actor-Referenz für digp muss 8 Bytes lang sein.")
    chunks = split_digp_value(existing_value)
    if actor_entry in chunks:
        return existing_value or b""
    return (existing_value or b"") + actor_entry


def digp_reference_summary(digp_value: bytes | None, actor_entry: bytes, *, unique_id_entry: bytes | None = None) -> dict[str, Any]:
    chunks = split_digp_value(digp_value)
    summary: dict[str, Any] = {
        "entry_count": len(chunks),
        "contains_actor_suffix": actor_entry in chunks,
        "actor_suffix_hex": actor_entry.hex(),
        "entries_hex": [chunk.hex() for chunk in chunks[:16]],
    }
    if unique_id_entry is not None:
        summary["unique_id_entry_hex"] = unique_id_entry.hex()
        summary["contains_unique_id_entry"] = unique_id_entry in chunks
    return summary


def _unique_id_entry_for_actor_key(actor_key: bytes) -> bytes:
    return unique_id_from_actor_key(actor_key).to_bytes(8, "little", signed=True)


def _tag_data(value: Any) -> Any:
    data = getattr(value, "py_data", None)
    if data is not None:
        return data
    data = getattr(value, "value", None)
    if data is not None and not callable(data):
        return data
    return value


def _entity_identifier(root: Any) -> str | None:
    if not isinstance(root, nbt.CompoundTag):
        return None
    for key in ("identifier", "Identifier", "id", "Id", "EntityIdentifier"):
        if key not in root:
            continue
        value = _tag_data(root[key])
        if isinstance(value, str) and value:
            return value
    return None


def _load_entity_tag(raw: bytes) -> nbt.CompoundTag | None:
    try:
        named = nbt.load(raw, **LOAD_KWARGS)
    except Exception:
        return None
    tag = getattr(named, "tag", None)
    return tag if isinstance(tag, nbt.CompoundTag) else None


def _template_priority(identifier: str, tag: nbt.CompoundTag, raw: bytes) -> tuple[int, int, int]:
    identifier_priority = {"minecraft:horse": 0, "minecraft:donkey": 10, "minecraft:mule": 20}.get(identifier, 100)
    is_baby = int(_tag_data(tag.get("IsBaby", 0)) or 0) if "IsBaby" in tag else 0
    baby_penalty = 5 if is_baby else 0
    # Prefer larger records within the same class because they tend to include
    # the complete Minecraft-written item-list/equipment structure.
    return identifier_priority + baby_penalty, -len(raw), 0


def find_equine_template(db) -> EquineTemplate | None:
    candidates: list[tuple[tuple[int, int, int], EquineTemplate]] = []
    for key, raw in db.iter_items():
        if not isinstance(key, bytes) or not key.startswith(ACTOR_PREFIX):
            continue
        tag = _load_entity_tag(raw)
        if tag is None:
            continue
        identifier = _entity_identifier(tag)
        if identifier not in EQUINE_TEMPLATE_IDENTIFIERS:
            continue
        candidates.append((_template_priority(identifier, tag, raw), EquineTemplate(identifier=identifier, value=raw)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def find_equine_template_value(db) -> bytes | None:
    template = find_equine_template(db)
    return template.value if template else None


def _attribute(
    name: str,
    *,
    base: float,
    current: float | None = None,
    default_max: float,
    default_min: float = 0.0,
    max_value: float | None = None,
    min_value: float = 0.0,
):
    current_value = base if current is None else current
    max_tag_value = default_max if max_value is None else max_value
    return nbt.CompoundTag(
        {
            "Name": nbt.StringTag(name),
            "Base": nbt.FloatTag(float(base)),
            "Current": nbt.FloatTag(float(current_value)),
            "DefaultMax": nbt.FloatTag(float(default_max)),
            "DefaultMin": nbt.FloatTag(float(default_min)),
            "Max": nbt.FloatTag(float(max_tag_value)),
            "Min": nbt.FloatTag(float(min_value)),
        }
    )


# Every scanned horse, donkey, mule and camel record carries this exact
# underwater_movement base; the skeleton horse is the one type that differs
# (see MOUNT_WRITE_SPECS).
DEFAULT_UNDERWATER_MOVEMENT = 0.019999999552965164


def _rideable_attributes(health: float, movement: float, jump_strength: float | None, underwater_movement: float = DEFAULT_UNDERWATER_MOVEMENT) -> nbt.ListTag:
    # jump_strength None: the type has no minecraft:horse.jump_strength
    # attribute at all (evidence: camel records carry only 11 attributes).
    very_large = 3.4028234663852886e38
    attributes = [
        _attribute("minecraft:health", base=health, default_max=health),
        _attribute("minecraft:follow_range", base=16.0, default_max=2048.0, max_value=2048.0),
        _attribute("minecraft:knockback_resistance", base=0.0, default_min=-2.0, default_max=1.0, max_value=1.0, min_value=-2.0),
        _attribute("minecraft:movement", base=movement, default_max=very_large, max_value=very_large),
        _attribute("minecraft:underwater_movement", base=underwater_movement, default_max=very_large, max_value=very_large),
        _attribute("minecraft:lava_movement", base=0.019999999552965164, default_max=very_large, max_value=very_large),
        _attribute("minecraft:absorption", base=0.0, default_max=16.0, max_value=16.0),
        _attribute("minecraft:luck", base=0.0, default_min=-1024.0, default_max=1024.0, max_value=1024.0, min_value=-1024.0),
    ]
    if jump_strength is not None:
        attributes.append(_attribute("minecraft:horse.jump_strength", base=jump_strength, default_max=very_large, max_value=very_large))
    attributes.extend(
        [
            _attribute("minecraft:friction_modifier", base=1.0, default_max=256.0, max_value=256.0),
            _attribute("minecraft:bounciness", base=0.0, default_max=1.0, max_value=1.0),
            _attribute("minecraft:air_drag_modifier", base=1.0, default_max=256.0, max_value=256.0),
        ]
    )
    return nbt.ListTag(attributes)


def _horse_attributes(horse_profile: Any = None) -> nbt.ListTag:
    profile = normalize_horse_profile(horse_profile)
    profile_attributes = horse_profile_attribute_values(profile)
    return _rideable_attributes(
        profile_attributes["minecraft:health"],
        profile_attributes["minecraft:movement"],
        profile_attributes["minecraft:horse.jump_strength"],
    )


# Stats the game stores as an integer tag.  Accepting 7.9 here and writing
# IntTag(7) would report a value the record never carries, so they are rejected
# up front instead of silently truncated.
INTEGER_MOUNT_STATS = frozenset({"temper"})


def normalize_mount_stats(mount_type: str, value: Any) -> dict[str, float]:
    """Validate user-chosen stat overrides against the per-type vanilla ranges."""
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("mount_stats muss ein Objekt sein.")
    editable = MOUNT_WRITE_SPECS.get(mount_type, {}).get("editable_stats") or {}
    label = MOUNT_WRITE_LABELS.get(mount_type, mount_type)
    result: dict[str, float] = {}
    for key, raw in value.items():
        if raw in (None, ""):
            continue
        if key not in editable:
            raise ValueError(f"{label} hat kein einstellbares Feld '{key}'.")
        low, high = editable[key]
        number = _float_value(raw, f"mount_stats.{key}")
        if not low <= number <= high:
            raise ValueError(f"mount_stats.{key} muss zwischen {low:g} und {high:g} liegen (Vanilla-Bereich).")
        if key in INTEGER_MOUNT_STATS:
            if number != int(number):
                raise ValueError(f"mount_stats.{key} muss eine ganze Zahl sein.")
            number = float(int(number))
        result[key] = number
    return result


def _mount_stat_values(
    mount_type: str, mount_stats: dict[str, float] | None = None, rng: random.Random | None = None, tamed: bool = False
) -> dict[str, float | None]:
    """Resolve the health/movement/jump/temper values a non-horse record carries.

    Presence of a key means "already resolved" (even when its value is None,
    e.g. camel without a jump attribute), so feeding a resolved dict back in
    is a pure pass-through and never re-rolls randomized fields.

    ``tamed`` matters because taming removes Temper entirely; without it the
    resolved dict would report a taming progress the record never carries.
    """
    spec = MOUNT_WRITE_SPECS[mount_type]
    rng = rng or random.Random()
    stats = mount_stats or {}
    if "health" in stats and stats["health"] is not None:
        health = stats["health"]
    else:
        health = float(rng.randint(15, 30)) if spec["health"] == RANDOM_LIKE_GAME else float(spec["health"])
    if "jump_strength" in stats:
        jump_strength: float | None = stats["jump_strength"]
    else:
        jump_spec = spec["jump_strength"]
        jump_strength = rng.uniform(0.4, 1.0) if jump_spec == RANDOM_LIKE_GAME else None if jump_spec is None else float(jump_spec)
    if tamed and spec["tamed"] is not None:
        temper: float | None = None
    elif "temper" in stats:
        temper = stats["temper"]
    else:
        temper_spec = spec["temper"]
        # Same rng as the health roll, so one resolved dict describes one specimen.
        temper = rng.randint(HORSE_TEMPER_MIN, HORSE_TEMPER_MAX) if temper_spec == RANDOM_LIKE_GAME else None if temper_spec is None else int(temper_spec)
    return {"health": float(health), "movement": float(spec["movement"]), "jump_strength": jump_strength, "temper": temper}


def _mount_attributes(mount_type: str, horse_profile: Any = None, mount_stats: dict[str, float] | None = None) -> nbt.ListTag:
    """Build the attribute list from *already resolved* stats.

    ``mount_stats`` must be a fully resolved dict, so this never rolls anything
    and takes no rng: the record's randomized values are decided once by the
    caller, otherwise the attributes would describe a different specimen than
    the tags.
    """
    if mount_type == "minecraft:horse":
        return _horse_attributes(horse_profile)
    values = _mount_stat_values(mount_type, mount_stats=mount_stats)
    return _rideable_attributes(
        values["health"],
        values["movement"],
        values["jump_strength"],
        float(MOUNT_WRITE_SPECS[mount_type]["underwater_movement"]),
    )


def _attribute_name(attribute: Any) -> str | None:
    if not isinstance(attribute, nbt.CompoundTag):
        return None
    value = attribute.get("Name")
    data = _tag_data(value) if value is not None else None
    return data if isinstance(data, str) and data else None


def _merge_horse_attributes(existing_attributes: Any, horse_profile: Any = None) -> nbt.ListTag:
    attributes = _horse_attributes(horse_profile)
    known_names = {_attribute_name(attribute) for attribute in attributes}
    extras: list[nbt.CompoundTag] = []
    if isinstance(existing_attributes, nbt.ListTag):
        for attribute in existing_attributes:
            name = _attribute_name(attribute)
            if name and name not in known_names and isinstance(attribute, nbt.CompoundTag):
                extras.append(attribute)
    return nbt.ListTag([*[attribute for attribute in attributes], *extras])


def _apply_horse_profile_tags(tag: nbt.CompoundTag, horse_profile: Any = None) -> nbt.CompoundTag:
    profile = normalize_horse_profile(horse_profile)
    tag["Attributes"] = _merge_horse_attributes(tag.get("Attributes"), profile)
    # Evidenz aus echten Records: Pferde tragen die Grundfarbe in Variant,
    # die Markierung in MarkVariant; Color/Color2 bleiben 0.
    tag["Variant"] = nbt.IntTag(int(profile.color))
    tag["Color"] = nbt.ByteTag(0)
    tag["Color2"] = nbt.ByteTag(0)
    tag["MarkVariant"] = nbt.IntTag(int(profile.mark_variant))
    # Sonst behielte der Klon den Zähmfortschritt des Templates, und ein im
    # Profil gesetzter Wert würde hier still verschwinden.
    tag["Temper"] = nbt.IntTag(int(profile.temper))
    return tag


def _empty_item() -> nbt.CompoundTag:
    return nbt.CompoundTag(
        {
            "Count": nbt.ByteTag(0),
            "Damage": nbt.ShortTag(0),
            "Name": nbt.StringTag(""),
            "WasPickedUp": nbt.ByteTag(0),
        }
    )


def _armor_list() -> nbt.ListTag:
    return nbt.ListTag([_empty_item(), _empty_item(), _empty_item(), _empty_item(), _empty_item()])


def _single_item_list() -> nbt.ListTag:
    return nbt.ListTag([_empty_item()])


def _chest_items_list(slot_count: int) -> nbt.ListTag:
    # Evidence (camel raw dump): ChestItems entries are empty items plus a
    # Slot byte 0..n-1, unlike Armor/Mainhand/Offhand entries.
    items = []
    for slot in range(slot_count):
        item = _empty_item()
        item["Slot"] = nbt.ByteTag(slot)
        items.append(item)
    return nbt.ListTag(items)


def _horse_bool_tags() -> dict[str, nbt.ByteTag]:
    return {
        "Chested": nbt.ByteTag(0),
        "Dead": nbt.ByteTag(0),
        "Invulnerable": nbt.ByteTag(0),
        "IsAngry": nbt.ByteTag(0),
        "IsAutonomous": nbt.ByteTag(0),
        "IsBaby": nbt.ByteTag(0),
        "IsEating": nbt.ByteTag(0),
        "IsGliding": nbt.ByteTag(0),
        "IsGlobal": nbt.ByteTag(0),
        "IsIllagerCaptain": nbt.ByteTag(0),
        "IsOrphaned": nbt.ByteTag(0),
        "IsOutOfControl": nbt.ByteTag(0),
        "IsPregnant": nbt.ByteTag(0),
        "IsRoaring": nbt.ByteTag(0),
        "IsScared": nbt.ByteTag(0),
        "IsStunned": nbt.ByteTag(0),
        "IsSwimming": nbt.ByteTag(0),
        "IsTamed": nbt.ByteTag(0),
        "IsTrusting": nbt.ByteTag(0),
        "LootDropped": nbt.ByteTag(0),
        # Evidenz (alle Minecraft-behaltenen Records, inkl. /summon-Tiere):
        # Persistent=1, NaturalSpawn=0, Surface=0. Der Nachher-Dump vom
        # Kamel-Ladetest zeigt, dass Minecraft diese Werte unverändert
        # übernimmt statt sie zu normalisieren - ohne Persistent=1 könnten
        # erzeugte Mounts wie natürlich gespawnte Tiere despawnen.
        "NaturalSpawn": nbt.ByteTag(0),
        "OnGround": nbt.ByteTag(1),
        "Persistent": nbt.ByteTag(1),
        "Saddled": nbt.ByteTag(0),
        "Sheared": nbt.ByteTag(0),
        "ShowBottom": nbt.ByteTag(0),
        "Sitting": nbt.ByteTag(0),
        # Evidenz: alle 73 gescannten Minecraft-Pferderecords tragen 1. Der Wert
        # steuert die Body-Slot-Migration beim Laden; 0 hätte Minecraft dazu
        # gebracht, an einem frisch geschriebenen Pferd noch eine Migration zu
        # versuchen. Esel/Maultier/Skelettpferd entfernen das Tag weiter in
        # _mount_bool_tags, das Kamel setzt es dort explizit.
        "SkipBodySlotUpgrade": nbt.ByteTag(1),
        "Surface": nbt.ByteTag(0),
        "canPickupItems": nbt.ByteTag(0),
        "expDropEnabled": nbt.ByteTag(1),
        "hasBoundOrigin": nbt.ByteTag(0),
        "hasSetCanPickupItems": nbt.ByteTag(1),
    }


def _mount_bool_tags(mount_type: str) -> dict[str, nbt.ByteTag]:
    tags = _horse_bool_tags()
    spec = MOUNT_WRITE_SPECS.get(mount_type)
    if spec is not None:
        # Evidenz: Esel/Maultier/Skelettpferd-Records haben kein
        # SkipBodySlotUpgrade, Kamele tragen es mit 1; Skelettpferde und
        # Kamele stehen auf IsTamed=1.
        if spec["skip_body_slot_upgrade"] is None:
            tags.pop("SkipBodySlotUpgrade", None)
        else:
            tags["SkipBodySlotUpgrade"] = nbt.ByteTag(int(spec["skip_body_slot_upgrade"]))
        tags["IsTamed"] = nbt.ByteTag(int(spec["is_tamed"]))
    return tags


# Bedrock component-group names from the vanilla horse behavior definitions.
# Index order matches the Color/MarkVariant byte values written to the NBT.
HORSE_BASE_COLOR_DEFINITIONS: dict[int, str] = {
    0: "+minecraft:base_white",
    1: "+minecraft:base_creamy",
    2: "+minecraft:base_chestnut",
    3: "+minecraft:base_brown",
    4: "+minecraft:base_black",
    5: "+minecraft:base_gray",
    6: "+minecraft:base_darkbrown",
}
HORSE_MARKINGS_DEFINITIONS: dict[int, str] = {
    0: "+minecraft:markings_none",
    1: "+minecraft:markings_white_details",
    2: "+minecraft:markings_white_fields",
    3: "+minecraft:markings_white_dots",
    4: "+minecraft:markings_black_dots",
}


# Sentinel for spec values the game rolls per specimen (donkey/mule health,
# skeleton horse jump strength).  jump_strength None means the attribute is
# absent entirely (camel).
RANDOM_LIKE_GAME = "random"
# Observed in every Minecraft-written camel record; the game rewrites it to
# its own version on the next world load, so any plausible value works.
OBSERVED_INVENTORY_VERSION = "1.26.33"

# Evidence-based write specs for further rideable types.  All values come from
# real Minecraft-written records collected via scripts/horse_diagnostic.py
# --all-mounts / --dump-nbt (reports 2026-07-10): definitions sets, fixed
# float32 attribute bases and per-type tag differences.  skip_body_slot_upgrade
# None = tag absent (donkey/mule/skeleton horse); camel keeps it at 1.
# chest_item_slots/include_breeding_tags reproduce the camel-only extra tags
# (ChestItems, BreedCooldown, InLove, LoveCause, InventoryVersion).
# editable_stats lists the fields the vanilla game itself randomizes per
# specimen (inclusive ranges); only those may be user-overridden so every
# written record stays within values Minecraft produces on its own.
# tamed describes the player-tamed variant (wild-vs-tamed dumps 2026-07-10):
# taming rewrites definitions to -_wild/+_tamed/+_unchested, removes Temper
# entirely, sets IsTamed 1, adds a 16-slot ChestItems inventory plus
# InventoryVersion, sets OwnerNew to the taming player's UniqueID, and for
# breedable types (donkey, not the sterile mule) adds the breeding tags.
# None = no tamed variant (horse lacks evidence; skeleton horse and camel
# already spawn tamed).
# Entries only list what differs from these defaults; the merge below keeps
# direct spec["key"] reads safe and surfaces a missing key at import time.
_MOUNT_SPEC_DEFAULTS: dict[str, Any] = {
    "skip_body_slot_upgrade": None,
    "chest_item_slots": 0,
    "include_breeding_tags": False,
    "editable_stats": {},
    "tamed": None,
    "underwater_movement": DEFAULT_UNDERWATER_MOVEMENT,
    # None = the type carries no Temper tag at all (skeleton horse and camel
    # spawn tamed).  RANDOM_LIKE_GAME = rolled per specimen like the game does.
    "temper": None,
}
_MOUNT_WRITE_SPEC_OVERRIDES: dict[str, dict[str, Any]] = {
    "minecraft:donkey": {
        "definitions": ("+minecraft:donkey", "+minecraft:donkey_adult", "+minecraft:donkey_wild"),
        "health": RANDOM_LIKE_GAME,
        "movement": 0.17499999701976776,
        "jump_strength": 0.5,
        "temper": RANDOM_LIKE_GAME,
        "is_tamed": 0,
        # Temper is only editable on the wild variant; taming removes the tag,
        # so a value set together with tamed=True is dropped by _mount_stat_values.
        "editable_stats": {"health": (15.0, 30.0), "temper": (float(HORSE_TEMPER_MIN), float(HORSE_TEMPER_MAX))},
        "tamed": {
            "definitions": ("+minecraft:donkey", "+minecraft:donkey_adult", "-minecraft:donkey_wild", "+minecraft:donkey_tamed", "+minecraft:donkey_unchested"),
            "chest_item_slots": 16,
            "include_breeding_tags": True,
        },
    },
    "minecraft:mule": {
        "definitions": ("+minecraft:mule", "+minecraft:mule_adult", "+minecraft:mule_wild"),
        "health": RANDOM_LIKE_GAME,
        "movement": 0.17499999701976776,
        "jump_strength": 0.5,
        "temper": RANDOM_LIKE_GAME,
        "is_tamed": 0,
        "editable_stats": {"health": (15.0, 30.0), "temper": (float(HORSE_TEMPER_MIN), float(HORSE_TEMPER_MAX))},
        "tamed": {
            "definitions": ("+minecraft:mule", "+minecraft:mule_adult", "-minecraft:mule_wild", "+minecraft:mule_tamed", "+minecraft:mule_unchested"),
            "chest_item_slots": 16,
            "include_breeding_tags": False,
        },
    },
    "minecraft:skeleton_horse": {
        "definitions": ("+minecraft:skeleton_horse", "+minecraft:skeleton_horse_adult"),
        "health": 15.0,
        "movement": 0.20000000298023224,
        # Skeleton horses swim: 6/6 scanned records carry 0.08 here, every other
        # rideable type carries DEFAULT_UNDERWATER_MOVEMENT.
        "underwater_movement": 0.07999999821186066,
        "jump_strength": RANDOM_LIKE_GAME,
        "is_tamed": 1,
        "editable_stats": {"jump_strength": (0.4, 1.0)},
    },
    "minecraft:camel": {
        "definitions": ("+minecraft:camel", "+minecraft:camel_adult", "+minecraft:camel_standing"),
        "health": 32.0,
        "movement": 0.09000000357627869,
        "jump_strength": None,
        "is_tamed": 1,
        "skip_body_slot_upgrade": 1,
        "chest_item_slots": 5,
        "include_breeding_tags": True,
    },
}
MOUNT_WRITE_SPECS: dict[str, dict[str, Any]] = {
    mount_type: {**_MOUNT_SPEC_DEFAULTS, **overrides} for mount_type, overrides in _MOUNT_WRITE_SPEC_OVERRIDES.items()
}
TAMEABLE_MOUNT_TYPES = tuple(mount_type for mount_type, spec in MOUNT_WRITE_SPECS.items() if spec["tamed"] is not None)
SYNTHETIC_CREATABLE_MOUNT_TYPES = ("minecraft:horse", *MOUNT_WRITE_SPECS)
# Labels have a single source of truth in mounts.MOUNT_TYPE_DEFINITIONS.
MOUNT_WRITE_LABELS = {mount_type: MOUNT_TYPE_DEFINITIONS[mount_type]["label"] for mount_type in SYNTHETIC_CREATABLE_MOUNT_TYPES}


def _require_synthetic_creatable(mount_type: str) -> None:
    if mount_type not in SYNTHETIC_CREATABLE_MOUNT_TYPES:
        supported = ", ".join(MOUNT_WRITE_LABELS[value] for value in SYNTHETIC_CREATABLE_MOUNT_TYPES)
        raise ValueError(t("Create unterstützt aktuell nur: {supported}", supported=supported))


def _require_tameable_if_tamed(mount_type: str, tamed: bool) -> None:
    if tamed and mount_type not in TAMEABLE_MOUNT_TYPES:
        supported = ", ".join(MOUNT_WRITE_LABELS[value] for value in TAMEABLE_MOUNT_TYPES)
        raise ValueError(t("Gezähmt erzeugen ist nur für {supported} belegt; Skelettpferd und Kamel spawnen ohnehin zahm.", supported=supported))


def horse_definition_strings(color: Any = 0, mark_variant: Any = 1) -> list[str]:
    base = HORSE_BASE_COLOR_DEFINITIONS.get(int(color) if isinstance(color, (int, float)) else 0, HORSE_BASE_COLOR_DEFINITIONS[0])
    markings = HORSE_MARKINGS_DEFINITIONS.get(int(mark_variant) if isinstance(mark_variant, (int, float)) else 1, HORSE_MARKINGS_DEFINITIONS[1])
    return [
        "+minecraft:horse",
        "+minecraft:horse_adult",
        "+minecraft:horse_wild",
        base,
        markings,
    ]


def _horse_definitions(horse_profile: Any = None) -> nbt.ListTag:
    profile = normalize_horse_profile(horse_profile)
    return nbt.ListTag([nbt.StringTag(value) for value in horse_definition_strings(profile.color, profile.mark_variant)])


def expected_mount_definition_strings(mount_type: str, profile_summary: dict[str, Any] | None = None, tamed: bool = False) -> list[str]:
    if mount_type == "minecraft:horse":
        summary = profile_summary if isinstance(profile_summary, dict) else {}
        return horse_definition_strings(summary.get("color", 0), summary.get("mark_variant", 1))
    spec = MOUNT_WRITE_SPECS[mount_type]
    if tamed and spec["tamed"] is not None:
        return list(spec["tamed"]["definitions"])
    return list(spec["definitions"])


def expected_mount_attribute_count(mount_type: str) -> int:
    spec = MOUNT_WRITE_SPECS.get(mount_type)
    if spec is not None and spec["jump_strength"] is None:
        return 11
    return 12


def _mount_definitions(mount_type: str, horse_profile: Any = None) -> nbt.ListTag:
    if mount_type == "minecraft:horse":
        return _horse_definitions(horse_profile)
    return nbt.ListTag([nbt.StringTag(value) for value in MOUNT_WRITE_SPECS[mount_type]["definitions"]])


def _storage_key_component(actor_suffix: bytes | None) -> nbt.CompoundTag:
    if actor_suffix is None:
        return nbt.CompoundTag({})
    if len(actor_suffix) != 8:
        raise ValueError("Actor-Suffix muss 8 Bytes lang sein.")
    return nbt.CompoundTag(
        {
            "EntityStorageKeyComponent": nbt.CompoundTag(
                {
                    # Bedrock stores the raw actor-suffix bytes in a StringTag,
                    # including invalid UTF-8 bytes.  latin-1 would turn bytes
                    # >= 0x80 into valid multi-byte UTF-8 on serialization and
                    # Minecraft would then treat the expanded bytes as a new
                    # StorageKey.  Use the same reversible escape codec as all
                    # other Bedrock NBT I/O in this project.
                    "StorageKey": nbt.StringTag(nbt.utf8_escape_decoder(actor_suffix)),
                }
            )
        }
    )


def _storage_key_bytes(tag: nbt.CompoundTag) -> bytes | None:
    try:
        value = tag["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"]
    except Exception:
        return None
    data = _tag_data(value)
    if isinstance(data, str):
        try:
            return nbt.utf8_escape_encoder(data)
        except (UnicodeEncodeError, ValueError):
            return None
    if isinstance(data, bytes):
        return data
    return None


def _apply_horse_identity(
    tag: nbt.CompoundTag, position: dict[str, float], unique_id: int, actor_suffix: bytes | None, horse_profile: Any = None
) -> nbt.CompoundTag:
    pos = normalize_mount_position(position)
    tag["identifier"] = nbt.StringTag("minecraft:horse")
    tag["definitions"] = _horse_definitions(horse_profile)
    tag["UniqueID"] = nbt.LongTag(int(unique_id))
    tag["Pos"] = nbt.ListTag([nbt.FloatTag(pos["x"]), nbt.FloatTag(pos["y"]), nbt.FloatTag(pos["z"])])
    tag["Rotation"] = nbt.ListTag([nbt.FloatTag(0.0), nbt.FloatTag(0.0)])
    tag["internalComponents"] = _storage_key_component(actor_suffix)
    tag["Variant"] = nbt.IntTag(0)
    tag["IsBaby"] = nbt.ByteTag(0)
    # Wie beim synthetischen Writer: echte behaltene Records tragen
    # Persistent=1 und NaturalSpawn=0; ohne Persistent droht Despawn.
    tag["NaturalSpawn"] = nbt.ByteTag(0)
    tag["Surface"] = nbt.ByteTag(0)
    tag["Persistent"] = nbt.ByteTag(1)
    tag["OnGround"] = nbt.ByteTag(1)
    tag["OwnerNew"] = nbt.LongTag(-1)
    tag["TargetID"] = nbt.LongTag(-1)
    tag["LeasherID"] = nbt.LongTag(-1)
    _apply_horse_profile_tags(tag, horse_profile)
    for key in ("Age", "GrowthPaused", "Health"):
        if key in tag:
            del tag[key]
    if "Armor" not in tag or not isinstance(tag["Armor"], nbt.ListTag):
        tag["Armor"] = _armor_list()
    if "Mainhand" not in tag or not isinstance(tag["Mainhand"], nbt.ListTag):
        tag["Mainhand"] = _single_item_list()
    if "Offhand" not in tag or not isinstance(tag["Offhand"], nbt.ListTag):
        tag["Offhand"] = _single_item_list()
    return tag


def build_horse_actor_nbt_from_template(
    template_value: bytes, position: dict[str, float], unique_id: int, actor_suffix: bytes | None = None, horse_profile: Any = None
) -> bytes:
    tag = _load_entity_tag(template_value)
    if tag is None:
        raise ValueError("Equine-Template konnte nicht gelesen werden.")
    return nbt.NamedTag(_apply_horse_identity(tag, position, unique_id, actor_suffix, horse_profile)).save_to(**SAVE_KWARGS)


def build_horse_actor_nbt(
    position: dict[str, float],
    unique_id: int,
    actor_suffix: bytes | None = None,
    horse_profile: Any = None,
    mount_type: str = "minecraft:horse",
    mount_stats: dict[str, float] | None = None,
    tamed: bool = False,
    owner_unique_id: int | None = None,
) -> bytes:
    _require_synthetic_creatable(mount_type)
    _require_tameable_if_tamed(mount_type, tamed)
    pos = normalize_mount_position(position)
    is_horse = mount_type == "minecraft:horse"
    profile = normalize_horse_profile(horse_profile) if is_horse else None
    spec = MOUNT_WRITE_SPECS.get(mount_type)
    tamed_spec = spec["tamed"] if (tamed and spec is not None) else None
    # Resolve once so the attributes and Temper below describe the same specimen
    # instead of two independent rolls.
    stat_values = None if is_horse else _mount_stat_values(mount_type, mount_stats=mount_stats, tamed=tamed)
    tag = nbt.CompoundTag(
        {
            "Air": nbt.ShortTag(300),
            "Armor": _armor_list(),
            "Attributes": _mount_attributes(mount_type, profile, mount_stats=stat_values),
            "Color": nbt.ByteTag(0),
            "Color2": nbt.ByteTag(0),
            "DeathTime": nbt.ShortTag(0),
            "FallDistance": nbt.FloatTag(0.0),
            "HurtTime": nbt.ShortTag(0),
            "LeasherID": nbt.LongTag(-1),
            "Mainhand": _single_item_list(),
            "MarkVariant": nbt.IntTag(int(profile.mark_variant) if is_horse else 0),
            "Offhand": _single_item_list(),
            "OwnerNew": nbt.LongTag(-1),
            "PortalCooldown": nbt.IntTag(0),
            "Pos": nbt.ListTag([nbt.FloatTag(pos["x"]), nbt.FloatTag(pos["y"]), nbt.FloatTag(pos["z"])]),
            "Rotation": nbt.ListTag([nbt.FloatTag(0.0), nbt.FloatTag(0.0)]),
            "SkinID": nbt.IntTag(0),
            "Strength": nbt.IntTag(0),
            "StrengthMax": nbt.IntTag(0),
            "Tags": nbt.ListTag([]),
            "TargetID": nbt.LongTag(-1),
            "TradeExperience": nbt.IntTag(0),
            "TradeTier": nbt.IntTag(0),
            "UniqueID": nbt.LongTag(int(unique_id)),
            "Variant": nbt.IntTag(int(profile.color) if is_horse else 0),
            "boundX": nbt.IntTag(0),
            "boundY": nbt.IntTag(0),
            "boundZ": nbt.IntTag(0),
            "definitions": _mount_definitions(mount_type, profile),
            "identifier": nbt.StringTag(mount_type),
            "internalComponents": _storage_key_component(actor_suffix),
            **_mount_bool_tags(mount_type),
        }
    )
    # Evidenz (wild-vs-gezähmt-Dumps): gezähmte Tiere haben kein Temper mehr.
    # Der Zähmfortschritt wird wie im Spiel pro Exemplar gewürfelt: 41 gescannte
    # Pferde-, Esel- und Maultier-Records streuen über 0..98 ohne festen Wert.
    temper = profile.temper if is_horse else (stat_values or {}).get("temper")
    if temper is not None and tamed_spec is None:
        tag["Temper"] = nbt.IntTag(int(temper))
    chest_item_slots = int(tamed_spec["chest_item_slots"]) if tamed_spec is not None else int(spec["chest_item_slots"]) if spec is not None else 0
    if chest_item_slots:
        tag["ChestItems"] = _chest_items_list(chest_item_slots)
        tag["InventoryVersion"] = nbt.StringTag(OBSERVED_INVENTORY_VERSION)
    include_breeding = tamed_spec["include_breeding_tags"] if tamed_spec is not None else spec["include_breeding_tags"] if spec is not None else False
    if include_breeding:
        # Evidenz (Kamel- und Zähm-Dumps): BreedCooldown/InLove Int, LoveCause
        # Long stehen in jedem zuchtfähigen Minecraft-Record dieses Zustands.
        tag["BreedCooldown"] = nbt.IntTag(0)
        tag["InLove"] = nbt.IntTag(0)
        tag["LoveCause"] = nbt.LongTag(0)
    if tamed_spec is not None:
        tag["definitions"] = nbt.ListTag([nbt.StringTag(value) for value in tamed_spec["definitions"]])
        tag["IsTamed"] = nbt.ByteTag(1)
        if owner_unique_id is not None:
            tag["OwnerNew"] = nbt.LongTag(int(owner_unique_id))
    return nbt.NamedTag(tag).save_to(**SAVE_KWARGS)


def build_horse_mount_record(
    db,
    position: dict[str, float],
    create_mode: str = CREATE_MODE_AUTO,
    horse_profile: Any = None,
    mount_type: str = "minecraft:horse",
    mount_stats: Any = None,
    tamed: bool = False,
    owner_unique_id: int | None = None,
) -> HorseMountRecord:
    _require_synthetic_creatable(mount_type)
    normalized_position = normalize_mount_position(position)
    create_mode = normalize_create_mode(create_mode)
    is_horse = mount_type == "minecraft:horse"
    profile = normalize_horse_profile(horse_profile) if is_horse else None
    profile_summary = horse_profile_summary(profile) if profile is not None else None
    if is_horse and mount_stats not in (None, "", {}):
        raise ValueError("mount_stats gilt nur für Nicht-Pferd-Mounts; Pferde nutzen das Pferd-Profil.")
    _require_tameable_if_tamed(mount_type, tamed)
    # Feste + gewürfelte Werte einmal auflösen, damit der Record die
    # tatsächlich geschriebenen Werte berichten kann.
    stat_values = None if is_horse else _mount_stat_values(mount_type, mount_stats=normalize_mount_stats(mount_type, mount_stats), tamed=tamed)
    existing_actor_keys = []
    for key, _value in db.iter_items():
        if isinstance(key, bytes) and key.startswith(ACTOR_PREFIX):
            existing_actor_keys.append(key)
    actor_key = next_actor_key(existing_actor_keys)
    actor_suffix = actor_key_suffix(actor_key)
    unique_id = unique_id_from_actor_key(actor_key)
    if not is_horse and create_mode == CREATE_MODE_TEMPLATE_CLONE:
        raise ValueError("Template-Clone ist nur für Pferde implementiert; dieser Mount-Typ nutzt den synthetischen Writer.")
    template = None if (create_mode == CREATE_MODE_SYNTHETIC_FULL or not is_horse) else find_equine_template(db)
    if create_mode == CREATE_MODE_TEMPLATE_CLONE and template is None:
        raise ValueError("Template-Clone wurde angefordert, aber in der Welt wurde kein Horse/Donkey/Mule-Template gefunden.")
    if template is not None:
        actor_value = build_horse_actor_nbt_from_template(template.value, normalized_position, unique_id, actor_suffix, profile)
        effective_mode = CREATE_MODE_TEMPLATE_CLONE
        template_identifier = template.identifier
    else:
        actor_value = build_horse_actor_nbt(
            normalized_position, unique_id, actor_suffix, profile, mount_type=mount_type, mount_stats=stat_values, tamed=tamed, owner_unique_id=owner_unique_id
        )
        effective_mode = CREATE_MODE_SYNTHETIC_FULL
        template_identifier = None
    digp_key = digp_key_for_position(normalized_position)
    try:
        existing_digp = db.get(digp_key)
    except KeyError:
        existing_digp = b""
    digp_entry = digp_entry_for_actor_key(actor_key)
    digp_value = merge_digp_value(existing_digp, digp_entry)
    return HorseMountRecord(
        actor_key=actor_key,
        actor_value=actor_value,
        digp_key=digp_key,
        digp_value=digp_value,
        unique_id=unique_id,
        position=normalized_position,
        create_mode=effective_mode,
        template_identifier=template_identifier,
        horse_profile=profile_summary,
        mount_type=mount_type,
        mount_stats=dict(stat_values) if stat_values is not None else None,
        tamed=bool(tamed),
        owner_unique_id=owner_unique_id if tamed else None,
        previous_digp_value=existing_digp,
    )


def validate_horse_mount_write(db, record: HorseMountRecord, *, expected_digp_value: bytes | None = None) -> dict[str, Any]:
    actor_suffix = actor_key_suffix(record.actor_key)
    actor_entry = digp_entry_for_actor_key(record.actor_key)
    planned_digp_value = record.digp_value if expected_digp_value is None else expected_digp_value
    expected_digp_key = digp_key_for_position(record.position)
    errors: list[str] = []
    checks: dict[str, bool] = {
        "digp_key_matches_position": record.digp_key == expected_digp_key,
    }
    details: dict[str, Any] = {
        "actor_key_hex": record.actor_key.hex(),
        "actor_suffix_hex": actor_suffix.hex(),
        "digp_key_hex": record.digp_key.hex(),
        "expected_digp_key_hex": expected_digp_key.hex(),
        "expected_unique_id": record.unique_id,
        "planned_actor_value_length": len(record.actor_value),
        "planned_digp_value_length": len(planned_digp_value),
    }
    if not checks["digp_key_matches_position"]:
        errors.append("digp-Key passt nicht zum Chunk der finalen Mount-Position")

    try:
        actor_value = db.get(record.actor_key)
        checks["actor_record_exists"] = True
    except KeyError:
        actor_value = None
        checks["actor_record_exists"] = False
        errors.append("actorprefix record fehlt nach dem Schreiben")
    checks["actor_value_matches_write_plan"] = actor_value == record.actor_value
    if not checks["actor_value_matches_write_plan"]:
        errors.append("actorprefix-Wert stimmt nicht bytegenau mit dem Schreibplan überein")

    try:
        digp_value = db.get(record.digp_key)
        checks["digp_record_exists"] = True
    except KeyError:
        digp_value = b""
        checks["digp_record_exists"] = False
        errors.append("digp record fehlt nach dem Schreiben")
    checks["digp_value_matches_write_plan"] = digp_value == planned_digp_value
    if not checks["digp_value_matches_write_plan"]:
        errors.append("digp-Wert stimmt nicht bytegenau mit dem Schreibplan überein")

    try:
        digp_chunks = split_digp_value(digp_value)
        checks["digp_contains_actor_suffix"] = actor_entry in digp_chunks
        previous_digp_value = getattr(record, "previous_digp_value", b"") or b""
        checks["digp_preserves_previous_value"] = digp_value.startswith(previous_digp_value)
        details["digp_entry_count"] = len(digp_chunks)
        details["previous_digp_value_length"] = len(previous_digp_value)
        details["digp_entries_hex"] = [chunk.hex() for chunk in digp_chunks[:16]]
    except ValueError as exc:
        checks["digp_contains_actor_suffix"] = False
        checks["digp_preserves_previous_value"] = False
        details["digp_entry_count"] = None
        errors.append(str(exc))
    if not checks.get("digp_contains_actor_suffix"):
        errors.append("digp enthält den Actor-Suffix nicht")
    if not checks.get("digp_preserves_previous_value"):
        errors.append("digp hat bestehende Actor-Referenzen nicht bytegenau erhalten")

    tag = _load_entity_tag(actor_value or b"") if actor_value is not None else None
    checks["actor_nbt_parseable"] = tag is not None
    if tag is None:
        errors.append("actorprefix NBT ist nicht lesbar")
    else:
        identifier = _entity_identifier(tag)
        definitions = [str(_tag_data(item)) for item in tag.get("definitions", [])] if isinstance(tag.get("definitions"), nbt.ListTag) else []
        attributes = tag.get("Attributes")
        attribute_count = len(attributes) if isinstance(attributes, nbt.ListTag) else 0
        storage_key = _storage_key_bytes(tag)
        unique_id = _tag_data(tag.get("UniqueID")) if "UniqueID" in tag else None
        raw_length = len(actor_value or b"")
        tag_count = len(tag)

        details.update(
            {
                "identifier": identifier,
                "unique_id": unique_id,
                "storage_key_hex": storage_key.hex() if storage_key is not None else None,
                "definitions": definitions,
                "attribute_count": attribute_count,
                "raw_length": raw_length,
                "tag_count": tag_count,
            }
        )
        record_mount_type = getattr(record, "mount_type", "minecraft:horse") or "minecraft:horse"
        checks["identifier_matches_mount_type"] = identifier == record_mount_type
        checks["unique_id_matches_actor_key"] = unique_id == record.unique_id
        checks["storage_key_matches_actor_suffix"] = storage_key == actor_suffix
        expected_definitions = expected_mount_definition_strings(record_mount_type, record.horse_profile, tamed=getattr(record, "tamed", False))
        details["expected_definitions"] = expected_definitions
        checks["definitions_complete"] = all(value in definitions for value in expected_definitions)
        checks["attributes_complete"] = attribute_count >= expected_mount_attribute_count(record_mount_type)
        checks["equipment_lists_present"] = all(isinstance(tag.get(key), nbt.ListTag) for key in ("Armor", "Mainhand", "Offhand"))
        checks["no_top_level_health"] = "Health" not in tag
        checks["raw_length_plausible"] = raw_length >= MIN_PLAUSIBLE_HORSE_NBT_BYTES
        checks["tag_count_plausible"] = tag_count >= MIN_PLAUSIBLE_HORSE_TAG_COUNT

        for key, message in {
            "identifier_matches_mount_type": f"identifier ist nicht {record_mount_type}",
            "unique_id_matches_actor_key": "UniqueID passt nicht zum actorprefix-Key",
            "storage_key_matches_actor_suffix": "StorageKey passt nicht zum Actor-Suffix",
            "definitions_complete": "Mount definitions sind unvollständig",
            "attributes_complete": "Attribute-Liste ist unvollständig",
            "equipment_lists_present": "Armor/Mainhand/Offhand sind keine Listen",
            "no_top_level_health": "Top-Level Health ist vorhanden",
            "raw_length_plausible": "NBT ist unerwartet kurz",
            "tag_count_plausible": "NBT enthält unerwartet wenige Top-Level-Tags",
        }.items():
            if not checks.get(key):
                errors.append(message)

    ok = all(checks.values()) if checks else False
    return {
        "ok": ok,
        "checks": checks,
        "details": details,
        "errors": errors,
    }


def _normalize_validation(validation: Any) -> dict[str, Any]:
    """Coerce a mount validation result into the guaranteed ``ok/checks/details/errors`` shape.

    The batch is already committed when this runs.  A validator that returns an
    unexpected value (``{}``, ``None`` or a non-dict) must therefore never cause a
    ``KeyError`` on ``validation["ok"]`` and re-raise into the normal, seemingly
    retryable error path.  Missing fields are filled conservatively so such a
    write is reported as committed-but-unvalidated, not as a repeatable failure.
    """

    if not isinstance(validation, dict):
        return {
            "ok": False,
            "checks": {},
            "details": {"validation_result_type": type(validation).__name__},
            "errors": ["Nachvalidierung lieferte kein strukturiertes Ergebnis."],
        }
    normalized = dict(validation)
    normalized["ok"] = bool(validation.get("ok"))
    checks = validation.get("checks")
    normalized["checks"] = checks if isinstance(checks, dict) else {}
    details = validation.get("details")
    normalized["details"] = dict(details) if isinstance(details, dict) else {}
    errors = validation.get("errors")
    normalized["errors"] = [str(item) for item in errors] if isinstance(errors, (list, tuple)) else []
    if "ok" not in validation and not normalized["errors"]:
        normalized["errors"] = ["Nachvalidierung lieferte kein 'ok'-Feld; Schreibvorgang gilt als nicht bestätigt."]
    return normalized


def _merge_post_write_errors(validation: Any, post_write_errors: list[str]) -> dict[str, Any]:
    """Fold post-write step failures into a mount validation result.

    The batch is already committed at this point, so a failed close or backup
    prune must never turn the write into a seemingly retryable error.  The result
    is downgraded to ``ok=False`` while keeping the existing validation details.
    """

    base = validation if isinstance(validation, dict) else {}
    details = dict(base.get("details") or {})
    details["post_write_errors"] = [*details.get("post_write_errors", []), *post_write_errors]
    return {
        "ok": False,
        "checks": base.get("checks", {}),
        "details": details,
        "errors": [*(base.get("errors") or []), *post_write_errors],
    }


def create_horse_mount_with_service(
    service,
    world_path: str,
    encoded_player_key: str,
    preview: dict[str, Any],
    *,
    create_mode: str = CREATE_MODE_AUTO,
    horse_profile: Any = None,
    mount_stats: Any = None,
    tamed: bool = False,
    pre_write_check=None,
) -> dict[str, Any]:
    mount_type = str(preview.get("mount_type") or "")
    _require_synthetic_creatable(mount_type)
    is_horse = mount_type == "minecraft:horse"
    create_mode = normalize_create_mode(create_mode)
    profile = normalize_horse_profile(horse_profile) if is_horse else None
    mount_stats = None if is_horse else normalize_mount_stats(mount_type, mount_stats)
    tamed = bool(tamed)
    _require_tameable_if_tamed(mount_type, tamed)
    position = normalize_mount_position(preview.get("selected_position"))
    with service._locked_world(world_path):
        ensure_valid_world_path(world_path)
        player_key = decode_player_key(encoded_player_key)
        db = None
        backup_file = None
        write_attempted = False
        try:
            db = service._open_db(world_path)
            player_info = service._get_player_info(db, player_key)
            if not player_info["editable"]:
                raise ValueError(f"Dieser Spieler ist read-only: {player_info['reason']}")
            service._read_player(db, player_key)
            db.close()
            db = None

            try:
                backup_file = create_backup(world_path, prune_after=False)
            except PermissionError as exc:
                raise ValueError(
                    t(
                        "Mount-Erzeugung abgelehnt: {actor} verweigert Zugriff beim Erstellen des Backups. Backup-Ordner: {backup_dir}. {hint}",
                        actor=denied_write_actor(),
                        backup_dir=get_backups_dir(world_path),
                        hint=denied_write_permission_hint(),
                    )
                ) from exc

            db = service._open_db(world_path)
            player_raw = service._read_player(db, player_key)
            owner_unique_id = None
            if tamed:
                # Evidenz: Zähmen setzt OwnerNew auf die UniqueID des Spielers.
                player_tag = _load_entity_tag(player_raw)
                owner_value = _tag_data(player_tag.get("UniqueID")) if isinstance(player_tag, nbt.CompoundTag) and "UniqueID" in player_tag else None
                if not isinstance(owner_value, int):
                    raise ValueError("Gezähmt erzeugen abgelehnt: Die UniqueID des Referenzspielers konnte nicht gelesen werden.")
                owner_unique_id = owner_value
            record = build_horse_mount_record(
                db,
                position,
                create_mode=create_mode,
                horse_profile=profile,
                mount_type=mount_type,
                mount_stats=mount_stats,
                tamed=tamed,
                owner_unique_id=owner_unique_id,
            )
            actor_entry = digp_entry_for_actor_key(record.actor_key)
            unique_id_entry = _unique_id_entry_for_actor_key(record.actor_key)
            digp_summary = digp_reference_summary(record.digp_value, actor_entry, unique_id_entry=unique_id_entry)
            if pre_write_check:
                pre_write_check()
            write_attempted = True
            db.put_batch(
                {
                    record.actor_key: record.actor_value,
                    record.digp_key: record.digp_value,
                }
            )
            # Ab hier ist der Batch committed. Ab diesem Punkt darf kein Fehler
            # mehr wie ein wiederholbarer Pre-Write-Fehler nach außen dringen:
            # Nachvalidierung, DB-Schließen, Backup-Bereinigung und der Aufbau der
            # Antwort werden von einer gemeinsamen Post-Write-Fehlergrenze
            # umschlossen. Jede Ausnahme danach erzeugt ein strukturiertes
            # Ergebnis mit write_committed=True (error_phase="post_write").
            try:
                try:
                    validation = validate_horse_mount_write(db, record)
                except Exception as exc:
                    # Der Batch ist bereits geschrieben. Eine Ausnahme der
                    # Nachvalidierung darf deshalb niemals wie ein sicher
                    # wiederholbarer Pre-Write-Fehler behandelt werden.
                    validation = {
                        "ok": False,
                        "checks": {},
                        "details": {"exception_type": type(exc).__name__},
                        "errors": [f"Nachvalidierung konnte nicht abgeschlossen werden: {exc}"],
                    }
                # Ergebnis defensiv normalisieren: ein Validator, der ein
                # unerwartetes Objekt (z. B. {}) zurückgibt, darf nach dem Commit
                # keinen KeyError auf validation["ok"] auslösen.
                validation = _normalize_validation(validation)

                # Fehler beim Schließen der DB oder beim Bereinigen der Backups
                # dürfen den Schreibstatus nicht überschreiben; sie werden als
                # Post-Write-Teilfehler übernommen.
                post_write_errors: list[str] = []
                try:
                    db.close()
                except Exception as exc:
                    post_write_errors.append(f"Datenbank konnte nach dem Schreiben nicht sauber geschlossen werden: {exc}")
                finally:
                    db = None
                try:
                    prune_backups(world_path, keep_paths=[backup_file])
                except Exception as exc:
                    post_write_errors.append(f"Alte Backups konnten nach dem Schreiben nicht bereinigt werden: {exc}")
                if post_write_errors:
                    validation = _merge_post_write_errors(validation, post_write_errors)
                chunk_x, chunk_z = chunk_coordinates_for_position(record.position)
                mount_label = MOUNT_WRITE_LABELS[mount_type]
                validation_failed = not validation["ok"]
                failure_message = (
                    "Mount wurde geschrieben, aber die direkte Nachvalidierung ist fehlgeschlagen. "
                    "Nicht erneut erzeugen; stelle bei Zweifeln das angegebene Backup wieder her. " + ", ".join(validation["errors"])
                    if validation_failed
                    else None
                )
                return {
                    "success": not validation_failed,
                    "message": (
                        t(
                            "Experimentelles Mount ({label}) wurde erzeugt und direkt validiert. Bitte Weltkopie prüfen, bevor du damit weiterarbeitest.",
                            label=mount_label,
                        )
                        if not validation_failed
                        else failure_message
                    ),
                    "error": failure_message,
                    "write_committed": True,
                    "validation_failed": validation_failed,
                    "mount_type": mount_type,
                    "mount_label": mount_label,
                    "selected_position": record.position,
                    "backup_file": os.path.basename(backup_file),
                    "actor_key_hex": record.actor_key.hex(),
                    "actor_suffix_hex": actor_entry.hex(),
                    "unique_id_entry_hex": unique_id_entry.hex(),
                    "digp_key_hex": record.digp_key.hex(),
                    "digp_reference": digp_summary,
                    "chunk": {"x": chunk_x, "z": chunk_z},
                    "unique_id": record.unique_id,
                    "create_mode_requested": create_mode,
                    "create_mode_effective": record.create_mode,
                    "template_identifier": record.template_identifier,
                    "horse_profile": record.horse_profile,
                    "mount_stats": record.mount_stats,
                    "tamed": record.tamed,
                    "owner_unique_id": record.owner_unique_id,
                    "post_create_validation": validation,
                    "validation_warning": None if validation["ok"] else ", ".join(validation["errors"]),
                }
            except Exception as exc:
                # Unerwarteter Fehler nach dem Commit (z. B. beim Aufbau der
                # Antwort). Der Batch ist geschrieben: strukturiert als
                # Post-Write-Fehler melden, niemals als wiederholbaren 500.
                with contextlib.suppress(Exception):
                    if db is not None:
                        db.close()
                db = None
                post_write_message = (
                    "Die Daten wurden geschrieben, die Nachverarbeitung ist jedoch fehlgeschlagen. "
                    "Nicht erneut erzeugen; stelle bei Zweifeln das angegebene Backup wieder her."
                )
                return {
                    "success": False,
                    "write_committed": True,
                    "validation_failed": True,
                    "error_phase": "post_write",
                    "error": post_write_message,
                    "message": post_write_message,
                    "mount_type": mount_type,
                    "mount_label": MOUNT_WRITE_LABELS.get(mount_type, mount_type),
                    "selected_position": record.position,
                    "backup_file": os.path.basename(backup_file) if backup_file else None,
                    "post_write_error_detail": f"{type(exc).__name__}: {exc}",
                }
        except Exception as exc:
            if backup_file and not write_attempted:
                remove_backup_after_aborted_write(backup_file, exc, operation="mount.create")
            raise
        finally:
            close_db_preserving_active_exception(db, context="Mount-Erzeugung vor dem Commit")
