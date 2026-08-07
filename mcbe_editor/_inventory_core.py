import math
import re
from collections.abc import Mapping
from typing import Any, TypedDict

import amulet_nbt as nbt

from mcbe_editor.item_data import (
    EFFECTS,
    ENCHANTMENTS,
    get_max_damage,
    get_max_stack,
    is_addable_item_id,
    is_enchantable_item_id,
    is_enchantment_compatible_with_item,
    is_known_item_id,
)

from .bedrock_nbt import load_player_nbt, save_player_nbt
from .i18n import t

VALID_INVENTORY_SLOTS = set(range(36)) | {-106, 100, 101, 102, 103}
ENDER_CHEST_SLOTS = set(range(27))
MAX_DAMAGE = 32767
MAX_BEDROCK_STACK_COUNT = 127
MAX_LORE_LINES = 50
MAX_TEXT_LENGTH = 512
ITEM_ID_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_.-]+$")
MAX_NBT_VIEW_DEPTH = 8
MAX_NBT_VIEW_ITEMS = 80
MAX_NBT_VIEW_STRING = 512
ROOT_ITEM_LIST_TAGS = ("Armor", "Offhand", "Mainhand", "PlayerUIItems")
VANILLA_PLAYER_DIMENSION_IDS = frozenset({0, 1, 2})
AXOLOTL_ITEM_IDS = {"minecraft:axolotl_bucket", "minecraft:bucketaxolotl"}
AXOLOTL_ENTITY_ID = "minecraft:axolotl"
TROPICAL_FISH_BUCKET_ITEM_IDS = {
    "minecraft:tropical_fish_bucket",
    "minecraft:buckettropical",
    "minecraft:bucketcustomfish",
}
TROPICAL_FISH_ENTITY_IDS = {"minecraft:tropicalfish", "minecraft:tropical_fish"}
DATA_VALUE_VARIANT_DAMAGE_VALUES = {
    "minecraft:bed": frozenset(range(16)),
    "minecraft:item.bed": frozenset(range(16)),
    "minecraft:banner": frozenset(range(16)),
    "minecraft:goat_horn": frozenset(range(8)),
    "minecraft:ominous_bottle": frozenset(range(5)),
    "minecraft:suspicious_stew": frozenset(range(13)),
    "minecraft:empty_map": frozenset({0, 2}),
    "minecraft:emptymap": frozenset({0, 2}),
}
AXOLOTL_VARIANTS = {
    0: {"key": "lucy", "label_de": "Leuzistisch", "label_en": "Leucistic", "display_de": "Leuzistischer Axolotl", "display_en": "Leucistic Axolotl"},
    1: {"key": "cyan", "label_de": "Türkis", "label_en": "Cyan", "display_de": "Türkiser Axolotl", "display_en": "Cyan Axolotl"},
    2: {"key": "gold", "label_de": "Gold", "label_en": "Gold", "display_de": "Gold-Axolotl", "display_en": "Gold Axolotl"},
    3: {"key": "wild", "label_de": "Wild/Braun", "label_en": "Wild/Brown", "display_de": "Brauner/Wilder Axolotl", "display_en": "Wild/Brown Axolotl"},
    4: {"key": "blue", "label_de": "Blau", "label_en": "Blue", "display_de": "Blauer Axolotl", "display_en": "Blue Axolotl"},
}
AXOLOTL_VARIANT_BY_COLOR_TOKEN = {
    "lucy": 0,
    "leucistic": 0,
    "cyan": 1,
    "gold": 2,
    "wild": 3,
    "brown": 3,
    "blue": 4,
}
AXOLOTL_COLOR_LANG_KEY_BY_VARIANT = {
    0: "item.axolotlColorLucy.name",
    1: "item.axolotlColorCyan.name",
    2: "item.axolotlColorGold.name",
    3: "item.axolotlColorWild.name",
    4: "item.axolotlColorBlue.name",
}
# Vanilla's ageable duration is 1,200 seconds; Bedrock persists the remaining
# baby growth time as negative ticks.
AXOLOTL_BABY_AGE_TICKS = -24_000
DYE_COLOR_LABELS = {
    "black": ("Schwarz", "Black"),
    "blue": ("Blau", "Blue"),
    "brown": ("Braun", "Brown"),
    "cyan": ("Türkis", "Cyan"),
    "gray": ("Grau", "Gray"),
    "green": ("Grün", "Green"),
    "light_blue": ("Hellblau", "Light Blue"),
    "light_gray": ("Hellgrau", "Light Gray"),
    "lime": ("Hellgrün", "Lime"),
    "magenta": ("Magenta", "Magenta"),
    "orange": ("Orange", "Orange"),
    "pink": ("Rosa", "Pink"),
    "purple": ("Violett", "Purple"),
    "red": ("Rot", "Red"),
    "silver": ("Hellgrau", "Light Gray"),
    "white": ("Weiß", "White"),
    "yellow": ("Gelb", "Yellow"),
}
TROPICAL_FISH_COLOR_LABELS = {
    **DYE_COLOR_LABELS,
    "plum": ("Pflaumenblau", "Plum"),
    "rose": ("Rose", "Rose"),
    # Mojang's Bedrock language keys use "Silver" for tropical fish colors.
    # Keep this distinct from dye/item labels, where "silver" is treated as
    # today's light gray color.
    "silver": ("Silber", "Silver"),
    "sky": ("Himmel", "Sky"),
    "teal": ("Aquamarin", "Teal"),
}
TROPICAL_FISH_GROUP_LABELS = {
    "anemone": ("Anemone", "Anemone"),
    "blacktang": ("Schwarzer Segelflossendoktor", "Black Tang"),
    "bluedory": ("Paletten-Doktorfisch", "Blue Dory"),
    "butterflyfish": ("Falterfisch", "Butterfly Fish"),
    "cichlid": ("Buntbarsch", "Chichlid"),
    "clownfish": ("Clownfisch", "Clownfish"),
    "cottoncandybetta": ("Zuckerwatte-Kampffisch", "Cotton Candy Betta"),
    "dottyback": ("Zwergbarsch", "Dottyback"),
    "emperorredsnapper": ("Kaiser-Schnapper", "Emperor Red Snapper"),
    "goatfish": ("Meerbarbe", "Goatfish"),
    "moorishidol": ("Halfterfisch", "Moorish Idol"),
    "ornatebutterfly": ("Orangestreifen-Falterfisch", "Ornate Butterfly"),
    "parrotfish": ("Papageienfisch", "Parrotfish"),
    "queenangelfish": ("Königin-Engelfisch", "Queen Angel Fish"),
    "redcichlid": ("Roter Buntbarsch", "Red Cichlid"),
    "redlippedblenny": ("Rotlippen-Schleimfisch", "Red Lipped Blenny"),
    "redsnapper": ("Roter Schnapper", "Red Snapper"),
    "threadfin": ("Fadenflosser", "Threadfin"),
    "tomatoclown": ("Weißbinden-Glühkohlen-Anemonenfisch", "Tomato Clown"),
    "triggerfish": ("Drückerfisch", "Triggerfish"),
    "yellowtailparrot": ("Gelbschwanz-Papageienfisch", "Yellowtail Parrot"),
    "yellowtang": ("Gelber Segelflossen-Doktorfisch", "Yellow Tang"),
}
TROPICAL_FISH_COLOR_TOKEN_BY_VALUE = {
    0: "White",
    1: "Orange",
    2: "Magenta",
    3: "Sky",
    4: "Yellow",
    5: "Lime",
    6: "Rose",
    7: "Gray",
    8: "Silver",
    9: "Teal",
    10: "Plum",
    11: "Blue",
    12: "Brown",
    13: "Green",
    14: "Red",
    15: "Black",
}
TROPICAL_FISH_COLOR_VALUE_BY_TOKEN = {token.lower(): value for value, token in TROPICAL_FISH_COLOR_TOKEN_BY_VALUE.items()}
TROPICAL_FISH_PATTERN_BY_VALUES = {
    (0, 0): ("Kob", "Kabeljau", "Kob"),
    (0, 1): ("Sunstreak", "SunStreak", "SunStreak"),
    (0, 2): ("Snooper", "Snooper", "Snooper"),
    (0, 3): ("Dasher", "Dasher/Flitzer", "Dasher"),
    (0, 4): ("Brinely", "Brinely", "Brinely"),
    (0, 5): ("Spotty", "Spotty", "Spotty"),
    (1, 0): ("Flopper", "Flopper", "Flopper"),
    (1, 1): ("Stripey", "Stripey", "Stripey"),
    (1, 2): ("Glitter", "Glitter", "Glitter"),
    (1, 3): ("Blockfish", "Blockfish", "Blockfish"),
    (1, 4): ("Betty", "Betty", "Betty"),
    (1, 5): ("Clayfish", "Clayfish", "Clayfish"),
}
TROPICAL_FISH_PATTERN_VALUES_BY_TOKEN = {token.lower(): values for values, (token, _label_de, _label_en) in TROPICAL_FISH_PATTERN_BY_VALUES.items()}
# Vanilla school presets from Mojang's current tropical-fish behavior pack.
TROPICAL_FISH_PRESET_VALUES = {
    "anemone": (1, 1, 1, 7),
    "blacktang": (1, 0, 7, 7),
    "bluedory": (0, 1, 7, 3),
    "butterflyfish": (0, 4, 0, 7),
    "cichlid": (0, 1, 11, 7),
    "clownfish": (0, 0, 1, 0),
    "cottoncandybetta": (0, 5, 6, 3),
    "dottyback": (1, 3, 10, 4),
    "emperorredsnapper": (1, 5, 0, 14),
    "goatfish": (0, 5, 0, 4),
    "moorishidol": (1, 2, 0, 7),
    "ornatebutterfly": (1, 5, 0, 1),
    "parrotfish": (0, 3, 9, 6),
    "queenangelfish": (0, 4, 5, 3),
    "redcichlid": (1, 4, 14, 0),
    "redlippedblenny": (0, 2, 7, 14),
    "redsnapper": (1, 3, 14, 0),
    "threadfin": (1, 0, 0, 4),
    "tomatoclown": (0, 1, 14, 0),
    "triggerfish": (0, 1, 7, 0),
    "yellowtang": (1, 1, 4, 4),
    "yellowtailparrot": (0, 3, 9, 4),
}
# Exact casing from the current Vanilla resource-pack language keys
# (resource_pack/texts/en_US.lang). The normalized preset keys above are not
# sufficient to reconstruct these machine-readable identifiers safely.
TROPICAL_FISH_GROUP_LANG_TOKEN_BY_KEY = {
    "anemone": "Anemone",
    "blacktang": "BlackTang",
    "bluedory": "BlueDory",
    "butterflyfish": "ButterflyFish",
    "cichlid": "Cichlid",
    "clownfish": "Clownfish",
    "cottoncandybetta": "CottonCandyBetta",
    "dottyback": "Dottyback",
    "emperorredsnapper": "EmperorRedSnapper",
    "goatfish": "Goatfish",
    "moorishidol": "MoorishIdol",
    "ornatebutterfly": "OrnateButterfly",
    "parrotfish": "Parrotfish",
    "queenangelfish": "QueenAngelFish",
    "redcichlid": "RedCichlid",
    "redlippedblenny": "RedLippedBlenny",
    "redsnapper": "RedSnapper",
    "threadfin": "Threadfin",
    "tomatoclown": "TomatoClown",
    "triggerfish": "Triggerfish",
    "yellowtang": "YellowTang",
    "yellowtailparrot": "YellowtailParrot",
}
TROPICAL_FISH_PRESET_KEY_BY_VALUES = {values: key for key, values in TROPICAL_FISH_PRESET_VALUES.items()}


class EnchantmentEntry(TypedDict):
    id: int
    lvl: int


class EntityVariantField(TypedDict):
    key: str
    label_de: str
    label_en: str
    raw: str
    display_de: str
    display_en: str


class EntityVariantInfo(TypedDict, total=False):
    entity_id: str
    key: str
    kind_label_de: str
    kind_label_en: str
    value_label_de: str
    value_label_en: str
    label_de: str
    label_en: str
    display_name_de: str
    display_name_en: str
    source: str
    variant: int
    icon_key: str
    adult_icon_key: str
    baby_icon_key: str
    is_baby: bool
    mark_variant: int
    color: int
    color2: int
    can_edit: bool
    fields: list[EntityVariantField]


class ParsedItemSlot(TypedDict):
    slot: int
    source_slot: int
    name: str
    count: int
    damage: int
    display_name: str
    lore: list[str]
    enchantments: list[EnchantmentEntry]
    has_unknown_enchantments: bool
    has_protected_nbt: bool
    has_preserved_nbt: bool
    item_tag_opaque: bool
    entity_variant: EntityVariantInfo | None
    entity_variant_state: str | None
    preserved_nbt_summary: list[str]
    protected_nbt_summary: list[str]
    nbt_view: dict[str, Any]


class PlayerStats(TypedDict):
    pos: list[float]
    dimension_id: int | None
    health: float
    gamemode: int
    xp_level: int
    xp_progress: float
    food_level: int
    food_saturation: float


SCALAR_STAT_TAGS = {
    # Bedrock data seen in the wild can store Health as ShortTag even though
    # the editor writes the canonical FloatTag. Numeric variants are safe to
    # replace when the user explicitly edits health; non-numeric/future shapes
    # remain opaque and are preserved.
    "health": ("Health", (nbt.ByteTag, nbt.ShortTag, nbt.IntTag, nbt.LongTag, nbt.FloatTag, nbt.DoubleTag)),
    "gamemode": (("PlayerGameType", (nbt.IntTag,)), ("PlayerGameMode", (nbt.IntTag,))),
    "xp_level": (("PlayerLevel", (nbt.IntTag,)), ("XPLevel", (nbt.IntTag,))),
    "xp_progress": (("PlayerLevelProgress", (nbt.FloatTag,)), ("XPProgress", (nbt.FloatTag,))),
    "food_level": ("foodLevel", (nbt.IntTag,)),
    "food_saturation": ("foodSaturationLevel", (nbt.FloatTag,)),
}

ATTRIBUTE_STAT_TAGS = {
    "health": "minecraft:health",
    "xp_level": "minecraft:player.level",
    "xp_progress": "minecraft:player.experience",
    "food_level": "minecraft:player.hunger",
    "food_saturation": "minecraft:player.saturation",
}

ABILITY_TAG_FIELDS = {
    "fly_speed": ("flySpeed", (nbt.FloatTag,)),
    "walk_speed": ("walkSpeed", (nbt.FloatTag,)),
    "mayfly": ("mayfly", (nbt.ByteTag,)),
    "flying": ("flying", (nbt.ByteTag,)),
    "invulnerable": ("invulnerable", (nbt.ByteTag,)),
    "maybuild": ("mayBuild", (nbt.ByteTag,), ("maybuild",)),
    "instabuild": ("instabuild", (nbt.ByteTag,)),
}

# The value the editor shows for a missing ability tag. Writing exactly this
# value back must stay a no-op, otherwise editing one ability would synthesize
# every other field into a compound that never carried them.
ABILITY_DEFAULTS = {
    "fly_speed": 0.05,
    "walk_speed": 0.1,
    "mayfly": False,
    "flying": False,
    "invulnerable": False,
    "maybuild": True,
    "instabuild": False,
}


def _ability_tag_spec(field_name: str):
    spec = ABILITY_TAG_FIELDS.get(field_name)
    if not spec:
        return None
    tag_name, expected_types, *aliases = spec
    alias_names = tuple(aliases[0]) if aliases else ()
    return tag_name, expected_types, alias_names


def _iter_ability_tag_names(field_name: str):
    spec = _ability_tag_spec(field_name)
    if not spec:
        return
    tag_name, _expected_types, aliases = spec
    yield tag_name
    yield from aliases


def _ability_read_value(abilities_tag, field_name: str, fallback):
    spec = _ability_tag_spec(field_name)
    if not spec:
        return fallback
    tag_name, expected_types, aliases = spec
    for candidate_name in (tag_name, *aliases):
        try:
            if candidate_name in abilities_tag and isinstance(abilities_tag[candidate_name], expected_types):
                return get_tag_value(abilities_tag.get(candidate_name), fallback)
        except (AttributeError, TypeError):
            continue
    return fallback


EFFECT_CONTROL_TAGS = {
    "Id": (nbt.ByteTag,),
    "Amplifier": (nbt.ByteTag,),
    "Duration": (nbt.IntTag,),
    "Ambient": (nbt.ByteTag,),
    "ShowParticles": (nbt.ByteTag,),
    "ShowIcon": (nbt.ByteTag,),
}

# The value ``parse_effects`` reports for a missing control tag. Older Bedrock
# effect entries can lack ShowIcon entirely; echoing the displayed default back
# must not append the tag to an otherwise untouched effect.
EFFECT_CONTROL_DEFAULTS = {
    "Id": 0,
    "Amplifier": 0,
    "Duration": 0,
    "Ambient": False,
    "ShowParticles": True,
    "ShowIcon": True,
}

NUMERIC_TAG_TYPES = (
    nbt.ByteTag,
    nbt.ShortTag,
    nbt.IntTag,
    nbt.LongTag,
    nbt.FloatTag,
    nbt.DoubleTag,
)

INTEGER_TAG_TYPES = (
    nbt.ByteTag,
    nbt.ShortTag,
    nbt.IntTag,
    nbt.LongTag,
)

INTEGER_TAG_RANGES = {
    nbt.ByteTag: (-128, 127),
    nbt.ShortTag: (-32768, 32767),
    nbt.IntTag: (-2147483648, 2147483647),
    nbt.LongTag: (-9223372036854775808, 9223372036854775807),
}


def _iter_scalar_stat_specs(field_name: str):
    spec = SCALAR_STAT_TAGS.get(field_name)
    if not spec:
        return
    if isinstance(spec[0], str):
        yield spec
        return
    yield from spec


def _scalar_stat_read_tag(player_tag, field_name: str):
    for tag_name, expected_types in _iter_scalar_stat_specs(field_name) or ():
        try:
            if tag_name in player_tag and isinstance(player_tag[tag_name], expected_types):
                return tag_name
        except (AttributeError, TypeError):
            continue
    return None


def _set_scalar_stat_value(player_tag, field_name: str, tag_cls, value):
    specs = list(_iter_scalar_stat_specs(field_name) or ())
    if not specs:
        return
    existing_names = []
    for tag_name, _expected_types in specs:
        try:
            if tag_name in player_tag:
                existing_names.append(tag_name)
        except (AttributeError, TypeError):
            continue
    for tag_name in existing_names or [specs[0][0]]:
        player_tag[tag_name] = tag_cls(value)


def _scalar_stat_opaque_fields(player_tag):
    opaque = {}
    for field_name in SCALAR_STAT_TAGS:
        for tag_name, expected_types in _iter_scalar_stat_specs(field_name) or ():
            try:
                if tag_name in player_tag and not isinstance(player_tag[tag_name], expected_types):
                    opaque[field_name] = tag_name
                    break
            except (AttributeError, TypeError):
                continue
    return opaque


def _ability_field_opaque_fields(player_tag):
    opaque = {}
    try:
        abilities_tag = player_tag.get("abilities")
    except AttributeError:
        return opaque
    if abilities_tag is None or not isinstance(abilities_tag, nbt.CompoundTag):
        return opaque
    for field_name in ABILITY_TAG_FIELDS:
        spec = _ability_tag_spec(field_name)
        if not spec:
            continue
        _canonical_name, expected_types, _aliases = spec
        for tag_name in _iter_ability_tag_names(field_name) or ():
            try:
                if tag_name in abilities_tag and not isinstance(abilities_tag[tag_name], expected_types):
                    opaque[field_name] = tag_name
                    break
            except (AttributeError, TypeError):
                continue
    return opaque


def _is_ability_field_opaque(player_tag, field_name: str) -> bool:
    spec = _ability_tag_spec(field_name)
    if not spec:
        return False
    _canonical_name, expected_types, _aliases = spec
    try:
        abilities_tag = player_tag.get("abilities")
        return isinstance(abilities_tag, nbt.CompoundTag) and any(
            tag_name in abilities_tag and not isinstance(abilities_tag[tag_name], expected_types) for tag_name in _iter_ability_tag_names(field_name) or ()
        )
    except (AttributeError, TypeError):
        return False


def _effect_control_fields_opaque(effect_tag):
    if not isinstance(effect_tag, nbt.CompoundTag):
        return True
    for tag_name, expected_types in EFFECT_CONTROL_TAGS.items():
        try:
            if tag_name in effect_tag and not isinstance(effect_tag[tag_name], expected_types):
                return True
        except (AttributeError, TypeError):
            return True
    return False


def _active_effects_opaque_entry_count(player_tag):
    try:
        active_effects_tag = player_tag.get("ActiveEffects")
    except AttributeError:
        return 0
    if not isinstance(active_effects_tag, nbt.ListTag):
        return 0
    opaque_count = 0
    seen_editable_ids = set()
    for effect_tag in active_effects_tag:
        if _effect_control_fields_opaque(effect_tag):
            opaque_count += 1
            continue
        effect_id = _effect_id_from_tag(effect_tag)
        if effect_id in EFFECTS:
            if effect_id in seen_editable_ids:
                # The browser edits effects by their Vanilla ID. A second normal
                # entry with the same ID has no unambiguous editable identity and
                # therefore has to be preserved as opaque data.
                opaque_count += 1
            else:
                seen_editable_ids.add(effect_id)
    return opaque_count


def _is_scalar_stat_field_opaque(player_tag, field_name: str) -> bool:
    for tag_name, expected_types in _iter_scalar_stat_specs(field_name) or ():
        try:
            if tag_name in player_tag and not isinstance(player_tag[tag_name], expected_types):
                return True
        except (AttributeError, TypeError):
            continue
    return False


def get_tag_value(tag, default=None):
    if tag is None:
        return default
    try:
        val = tag.py_data
    except AttributeError:
        return default
    if isinstance(val, float) and not math.isfinite(val):
        return 0.0 if default is None else default
    return val


def _safe_int_from_tag(tag, default: int = 0) -> int:
    try:
        return int(get_tag_value(tag, default))
    except (OverflowError, TypeError, ValueError):
        return default


def _integer_tag_value_in_range(value, tag_cls) -> bool:
    bounds = INTEGER_TAG_RANGES.get(tag_cls)
    if bounds is None:
        return True
    try:
        parsed = int(value)
    except (OverflowError, TypeError, ValueError):
        return False
    if parsed != value:
        return False
    minimum, maximum = bounds
    return minimum <= parsed <= maximum


def _numeric_tag_for_type(tag_cls, value):
    if tag_cls in INTEGER_TAG_RANGES and not _integer_tag_value_in_range(value, tag_cls):
        return None
    if tag_cls in (nbt.FloatTag, nbt.DoubleTag):
        try:
            if not math.isfinite(float(value)):
                return None
        except (OverflowError, TypeError, ValueError):
            return None
    try:
        return tag_cls(value)
    except (OverflowError, TypeError, ValueError):
        return None


def _optional_int_from_tag(tag):
    if tag is None:
        return None
    try:
        return int(get_tag_value(tag))
    except (OverflowError, TypeError, ValueError):
        return None


def _compound_child(compound, name: str):
    if not _is_compound_tag(compound):
        return None
    try:
        child = compound.get(name)
    except AttributeError:
        return None
    return child if _is_compound_tag(child) else None


def _compound_path(compound, *path: str):
    current = compound
    for name in path:
        current = _compound_child(current, name)
        if current is None:
            return None
    return current


def _string_from_compound(compound, key: str) -> str:
    if not _is_compound_tag(compound):
        return ""
    try:
        value = compound.get(key)
    except AttributeError:
        return ""
    return str(get_tag_value(value, "")).strip()


def _int_from_compound(compound, key: str):
    if not _is_compound_tag(compound):
        return None
    try:
        return _optional_int_from_tag(compound.get(key))
    except AttributeError:
        return None


def _integer_tag_value_from_compound(compound, key: str):
    if not _is_compound_tag(compound):
        return None
    try:
        tag = compound.get(key)
    except AttributeError:
        return None
    return _optional_int_from_tag(tag) if isinstance(tag, INTEGER_TAG_TYPES) else None


def _scalar_string_from_compound(compound, key: str) -> str:
    if not _is_compound_tag(compound):
        return ""
    try:
        value = compound.get(key)
    except AttributeError:
        return ""
    scalar = get_tag_value(value, None)
    if scalar is None or isinstance(scalar, (dict, list, tuple, set)):
        return ""
    return str(scalar).strip()


def _deep_clone_tag(tag):
    """Detach an NBT tag from the loaded snapshot without changing its encoding.

    ``copy.deepcopy`` resets the declared element type of every *empty* ListTag
    to byte, which silently rewrites preserved add-on NBT on save.  A Bedrock
    serialize/deserialize round trip keeps the encoding byte-exact and is deep,
    the same technique :func:`player_state_transfer._clone_tag` relies on.
    """

    return load_player_nbt(save_player_nbt(nbt.NamedTag(nbt.CompoundTag({"value": tag})))).tag["value"]


def _entity_data_candidate_compounds(item):
    candidates = [item]
    tag_compound = _compound_child(item, "tag")
    if tag_compound is None:
        return candidates
    candidates.append(tag_compound)
    candidates.extend(
        candidate
        for candidate in [
            _compound_child(tag_compound, "EntityTag"),
            _compound_child(tag_compound, "SaveData"),
            _compound_path(tag_compound, "EntityTag", "SaveData"),
        ]
        if candidate is not None
    )
    return candidates


def _normalize_entity_identifier(value: str) -> str:
    identifier = str(value or "").lower().partition("<")[0].strip()
    if identifier in {"tropicalfish", "tropical_fish", "minecraft:tropicalfish"}:
        return "minecraft:tropical_fish"
    if identifier == "axolotl":
        return AXOLOTL_ENTITY_ID
    return identifier


def _compact_variant_token(value: str) -> str:
    token = str(value or "").strip()
    token = re.sub(r"\.name$", "", token, flags=re.IGNORECASE)
    token = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", token)
    return re.sub(r"[^a-z0-9]+", "", token.lower())


def _variant_label_from_map(raw_value: str, labels: dict[str, tuple[str, str]], prefixes: tuple[str, ...]) -> tuple[str, str] | None:
    compact = _compact_variant_token(raw_value)
    candidates = [compact]
    for prefix in prefixes:
        if compact.startswith(prefix):
            candidates.append(compact[len(prefix) :])
    for candidate in candidates:
        if candidate in labels:
            return labels[candidate]
    return None


def _tropical_fish_field(compound, key: str, label_de: str, label_en: str, labels=None, prefixes=()):
    if not _is_compound_tag(compound):
        return None
    try:
        raw_tag = compound.get(key)
    except AttributeError:
        return None
    if not isinstance(raw_tag, nbt.StringTag):
        return None
    raw_value = str(get_tag_value(raw_tag, "")).strip()
    if not raw_value:
        return None
    label = _variant_label_from_map(raw_value, labels or {}, prefixes) if labels else None
    display_de, display_en = label if label else (raw_value, raw_value)
    return {
        "key": key,
        "label_de": label_de,
        "label_en": label_en,
        "raw": raw_value,
        "display_de": display_de,
        "display_en": display_en,
    }


def _item_name_from_tag(item) -> str:
    if not hasattr(item, "get"):
        return ""
    return str(get_tag_value(item.get("Name"), "")).strip().lower()


def _item_is_damageable(name: str) -> bool:
    return get_max_damage(name) != MAX_DAMAGE


def _item_tag_damage_tag(item):
    if not hasattr(item, "get"):
        return None
    tag_compound = item.get("tag")
    if not _is_compound_tag(tag_compound):
        return None
    damage_tag = tag_compound.get("Damage")
    return damage_tag if isinstance(damage_tag, INTEGER_TAG_TYPES) else None


def _read_editable_item_damage(item, name: str) -> int:
    if _item_is_damageable(name):
        tag_damage = _item_tag_damage_tag(item)
        if tag_damage is not None:
            return _safe_int_from_tag(tag_damage, 0)
    return _safe_int_from_tag(item.get("Damage"), 0)


def _allowed_item_tag_keys(item) -> set[str]:
    allowed = {"display", "ench", "enchantments"}
    if _item_is_damageable(_item_name_from_tag(item)):
        allowed.add("Damage")
    return allowed


KNOWN_PRESERVED_ITEM_TAG_KEYS = {
    # Bedrock vanilla item metadata that is not owned by the visible form yet,
    # but is common enough that it must not be labelled as future/modded.
    "AppendCustomName",
    "ActorIdentifier",
    "Age",
    "Baby",
    "Base",
    "BodyID",
    "Color2ID",
    "ColorID",
    "CustomName",
    "Fireworks",
    "FireworksItem",
    "GroupName",
    "EntityTag",
    "Identifier",
    "IsBaby",
    "Patterns",
    "RepairCost",
    "SaveData",
    "Trim",
    "Variant",
    "author",
    "chargedItem",
    "customColor",
    "generation",
    "identifier",
    "map_display_players",
    "map_is_init",
    "map_is_scaling",
    "map_name_index",
    "map_scale",
    "map_uuid",
    "pages",
    "resolved",
    "title",
    "trackingHandle",
    "wasJustBrewed",
}

ENTITY_VARIANT_PRESERVED_ITEM_TAG_KEYS = {
    "Color",
    "Color2",
    "MarkVariant",
}


def _known_preserved_item_tag_keys(item) -> set[str]:
    known_keys = set(KNOWN_PRESERVED_ITEM_TAG_KEYS)
    name = _item_name_from_tag(item)
    actor = _contained_actor_identifier(item)
    if name in AXOLOTL_ITEM_IDS | TROPICAL_FISH_BUCKET_ITEM_IDS or actor in {AXOLOTL_ENTITY_ID, *TROPICAL_FISH_ENTITY_IDS}:
        known_keys.update(ENTITY_VARIANT_PRESERVED_ITEM_TAG_KEYS)
    return known_keys


def _is_string_list_tag(tag) -> bool:
    return _is_list_tag(tag) and all(isinstance(entry, nbt.StringTag) for entry in tag)


def _set_editable_item_damage(item_compound, name: str, damage: int):
    if _item_is_damageable(name):
        tag_compound = item_compound.get("tag")
        existing_tag_damage = _item_tag_damage_tag(item_compound)
        root_damage = _safe_int_from_tag(item_compound.get("Damage"), 0)
        if existing_tag_damage is None and root_damage > 0:
            _set_numeric_tag_preserving_type(item_compound, "Damage", damage, nbt.ShortTag)
            return
        if tag_compound is None and damage > 0:
            tag_compound = nbt.CompoundTag({})
            item_compound["tag"] = tag_compound
        if tag_compound is not None and not _is_compound_tag(tag_compound) and damage != root_damage:
            # The requested value belongs in tag.Damage, but replacing an opaque
            # item tag would destroy future/add-on metadata. Never report success
            # while silently leaving the old damage in place.
            raise ValueError(t("Item-Metadaten können nicht bearbeitet werden, weil der vorhandene Item-tag einen unbekannten NBT-Typ verwendet."))
        if _is_compound_tag(tag_compound):
            if existing_tag_damage is not None:
                _set_numeric_tag_preserving_type(tag_compound, "Damage", damage, nbt.IntTag)
            elif damage > 0:
                tag_compound["Damage"] = nbt.IntTag(damage)
        if "Damage" not in item_compound:
            item_compound["Damage"] = nbt.ShortTag(0)
        return
    _set_numeric_tag_preserving_type(item_compound, "Damage", damage, nbt.ShortTag)


def _scalar_stat_value(player_tag, field_name: str, default):
    tag_name = _scalar_stat_read_tag(player_tag, field_name)
    if tag_name:
        return get_tag_value(player_tag.get(tag_name), default)
    attr_value = _attribute_stat_current_value(player_tag, field_name)
    return default if attr_value is None else attr_value


def _find_attribute_entry(player_tag, field_name: str):
    attribute_name = ATTRIBUTE_STAT_TAGS.get(field_name)
    if not attribute_name:
        return None
    attributes = player_tag.get("Attributes") if hasattr(player_tag, "get") else None
    if not _is_list_tag(attributes):
        return None
    for entry in attributes:
        if not _is_compound_tag(entry):
            continue
        if str(get_tag_value(entry.get("Name"), "")).strip() == attribute_name:
            return entry
    return None


def _attribute_stat_current_value(player_tag, field_name: str):
    entry = _find_attribute_entry(player_tag, field_name)
    if not entry:
        return None
    current = entry.get("Current")
    if isinstance(current, NUMERIC_TAG_TYPES):
        return get_tag_value(current)
    return None


def _attribute_stat_field_opaque(player_tag, field_name: str) -> str | None:
    entry = _find_attribute_entry(player_tag, field_name)
    if entry is None:
        return None
    current = entry.get("Current")
    if current is not None and not isinstance(current, NUMERIC_TAG_TYPES):
        return f"{ATTRIBUTE_STAT_TAGS[field_name]}.Current"
    return None


def _sync_attribute_stat(player_tag, field_name: str, value):
    entry = _find_attribute_entry(player_tag, field_name)
    if entry is None:
        return
    current = entry.get("Current")
    tag_cls = type(current) if isinstance(current, NUMERIC_TAG_TYPES) else nbt.FloatTag
    # Reusing the original tag class keeps an unusual world's NBT shape, but the
    # class has to be able to carry the value. A raw tag_cls(value) wraps silently:
    # ByteTag(200) becomes -56 and IntTag(0.6) becomes 0, and both would be written.
    tag = _numeric_tag_for_type(tag_cls, float(value))
    if tag is None:
        raise ValueError(
            t(
                "Wert {value} passt nicht in den vorhandenen NBT-Typ des Attributs {attribute}.",
                value=value,
                attribute=ATTRIBUTE_STAT_TAGS[field_name],
            )
        )
    entry["Current"] = tag


def _enchantment_id_from_tag(ench_tag) -> int:
    if not hasattr(ench_tag, "get"):
        return -1
    return _safe_int_from_tag(ench_tag.get("id"), -1)


def _enchantment_level_from_tag(ench_tag) -> int:
    if not hasattr(ench_tag, "get"):
        return 0
    return _safe_int_from_tag(ench_tag.get("lvl"), 0)


def _editable_known_enchantment_values(ench_tag, enchantments_db=ENCHANTMENTS) -> tuple[int, int] | None:
    """Return an editable known enchantment without normalizing malformed NBT.

    Known IDs with a missing, unparsable, or out-of-range level are still
    valuable original data. They stay opaque and are preserved verbatim instead
    of being exposed as an invalid UI value that blocks unrelated saves.
    """

    if not hasattr(ench_tag, "get"):
        return None
    try:
        raw_id = ench_tag.get("id")
        raw_level = ench_tag.get("lvl")
    except AttributeError:
        return None
    if raw_id is None or raw_level is None:
        return None
    ench_id = _optional_int_from_tag(raw_id)
    ench_level = _optional_int_from_tag(raw_level)
    if ench_id not in enchantments_db or ench_level is None:
        return None
    try:
        max_level = int(enchantments_db[ench_id][2])
    except (IndexError, TypeError, ValueError):
        return None
    if not 1 <= ench_level <= max_level:
        return None
    return ench_id, ench_level


def _extract_known_enchantments(ench_list, enchantments_db=ENCHANTMENTS, seen_ids=None):
    enchantments = []
    seen_ids = seen_ids if seen_ids is not None else set()
    if not _is_list_tag(ench_list):
        return enchantments
    for ench in ench_list:
        editable_values = _editable_known_enchantment_values(ench, enchantments_db)
        if editable_values is None:
            continue
        e_id, e_level = editable_values
        if e_id in seen_ids:
            continue
        enchantments.append({"id": e_id, "lvl": e_level})
        seen_ids.add(e_id)
    return enchantments


def _item_known_enchantments(item, enchantments_db=ENCHANTMENTS):
    enchantments = []
    seen_enchantment_ids = set()
    if not hasattr(item, "get") or "tag" not in item:
        return enchantments
    tag_compound = item["tag"]
    if not _is_compound_tag(tag_compound):
        return enchantments
    if "ench" in tag_compound:
        enchantments.extend(_extract_known_enchantments(tag_compound["ench"], enchantments_db=enchantments_db, seen_ids=seen_enchantment_ids))
    if "enchantments" in tag_compound:
        enchantments.extend(_extract_known_enchantments(tag_compound["enchantments"], enchantments_db=enchantments_db, seen_ids=seen_enchantment_ids))
    return enchantments


def _enchantments_match_original(item, enchantments, enchantments_db=ENCHANTMENTS) -> bool:
    return _item_known_enchantments(item, enchantments_db=enchantments_db) == enchantments


def _copy_enchantment_tag_with_level(original_tag, ench_id: int, ench_lvl: int):
    # Preserve future/add-on fields attached to a known enchantment compound.
    # The editor owns only id/lvl; everything else must survive a normal save.
    ench_tag = original_tag.copy() if original_tag is not None else nbt.CompoundTag()
    _set_numeric_tag_preserving_type(ench_tag, "id", ench_id, nbt.ShortTag)
    _set_numeric_tag_preserving_type(ench_tag, "lvl", ench_lvl, nbt.ShortTag)
    return ench_tag


def _has_unknown_enchantments(ench_list, enchantments_db=ENCHANTMENTS) -> bool:
    if not _is_list_tag(ench_list):
        return True
    return any(_enchantment_id_from_tag(ench) not in enchantments_db for ench in ench_list)


def _compound_has_extra_keys(compound, allowed_keys: set[str]) -> bool:
    try:
        return bool(set(compound.keys()) - allowed_keys)
    except AttributeError:
        # A tag with an unexpected type is still opaque data that the editor
        # cannot show faithfully. It must be treated as protected.
        return True


def _item_control_field_type_issues(item) -> list[str]:
    issues = []
    if not _is_compound_tag(item):
        return ["Item-Eintrag hat einen unerwarteten NBT-Typ"]
    if "Slot" in item and not isinstance(item["Slot"], INTEGER_TAG_TYPES):
        issues.append("Slot hat einen unerwarteten NBT-Typ")
    if "Name" in item and not isinstance(item["Name"], nbt.StringTag):
        issues.append("Name hat einen unerwarteten NBT-Typ")
    if "Count" in item and not isinstance(item["Count"], INTEGER_TAG_TYPES):
        issues.append("Count hat einen unerwarteten NBT-Typ")
    if "Damage" in item and not isinstance(item["Damage"], INTEGER_TAG_TYPES):
        issues.append("Damage hat einen unerwarteten NBT-Typ")
    if "WasPickedUp" in item and not isinstance(item["WasPickedUp"], INTEGER_TAG_TYPES):
        issues.append("WasPickedUp hat einen unerwarteten NBT-Typ")
    return issues


def _is_standard_block_item_tag(tag) -> bool:
    """Return True for Bedrock's normal root ``Block`` item snapshot."""

    if not _is_compound_tag(tag):
        return False
    if _compound_has_extra_keys(tag, {"name", "states", "version"}):
        return False
    if "name" not in tag or not isinstance(tag["name"], nbt.StringTag):
        return False
    if "states" in tag and not _is_compound_tag(tag["states"]):
        return False
    return "version" not in tag or isinstance(tag["version"], INTEGER_TAG_TYPES)


def _allowed_item_root_keys(item) -> set[str]:
    allowed = {"Slot", "Name", "Count", "Damage", "WasPickedUp", "tag"}
    block_tag = item.get("Block") if hasattr(item, "get") else None
    if _is_standard_block_item_tag(block_tag):
        allowed.add("Block")
    for list_name in ("CanDestroy", "CanPlaceOn"):
        try:
            if list_name in item and _is_string_list_tag(item[list_name]):
                allowed.add(list_name)
        except (AttributeError, TypeError):
            continue
    return allowed


def _preserved_item_root_keys(item) -> list[str]:
    preserved = []
    try:
        if "Block" in item and _is_standard_block_item_tag(item["Block"]):
            preserved.append("Block")
        for list_name in ("CanDestroy", "CanPlaceOn"):
            if list_name in item and _is_string_list_tag(item[list_name]):
                preserved.append(list_name)
    except (AttributeError, TypeError):
        pass
    return preserved


def _preserved_item_tag_keys(item) -> list[str]:
    try:
        tag_compound = item.get("tag")
    except AttributeError:
        return []
    if not _is_compound_tag(tag_compound):
        return []
    editable_keys = _allowed_item_tag_keys(item)
    known_preserved_keys = _known_preserved_item_tag_keys(item)
    return sorted(key for key in tag_compound if key in known_preserved_keys and key not in editable_keys)


def _item_has_protected_nbt(item) -> bool:
    """Return True when an item has data the visible editor does not own.

    The save path preserves this data whenever the item identity can be traced
    back to an original source item. Exposing this flag lets the browser mark
    slots as not fully WYSIWYG instead of pretending every preserved field is
    visible in the form.
    """

    if _compound_has_extra_keys(item, _allowed_item_root_keys(item)):
        return True
    if _item_control_field_type_issues(item):
        return True
    if "tag" not in item:
        return False

    tag_compound = item["tag"]
    if not _is_compound_tag(tag_compound):
        return True
    allowed_tag_keys = _allowed_item_tag_keys(item) | _known_preserved_item_tag_keys(item)
    if _compound_has_extra_keys(tag_compound, allowed_tag_keys):
        return True
    if "Damage" in tag_compound and not isinstance(tag_compound["Damage"], INTEGER_TAG_TYPES):
        return True

    if "display" in tag_compound:
        display_tag = tag_compound["display"]
        if not _is_compound_tag(display_tag) or _compound_has_extra_keys(display_tag, {"Name", "Lore"}):
            return True
        if "Name" in display_tag and not isinstance(display_tag["Name"], nbt.StringTag):
            return True
        if "Lore" in display_tag:
            lore_tag = display_tag["Lore"]
            if not _is_list_tag(lore_tag) or any(not isinstance(line, nbt.StringTag) for line in lore_tag):
                return True

    seen_editable_enchantment_ids = set()
    for list_name in ("ench", "enchantments"):
        if list_name not in tag_compound:
            continue
        if not _is_list_tag(tag_compound[list_name]):
            return True
        for ench in tag_compound[list_name]:
            if _compound_has_extra_keys(ench, {"id", "lvl"}):
                return True
            editable_values = _editable_known_enchantment_values(ench)
            ench_id = _enchantment_id_from_tag(ench)
            if ench_id in ENCHANTMENTS:
                if editable_values is None or ench_id in seen_editable_enchantment_ids:
                    return True
                seen_editable_enchantment_ids.add(ench_id)

    return False


def _item_protected_nbt_summary(item) -> list[str]:
    summary = []
    try:
        root_extra = sorted(set(item.keys()) - _allowed_item_root_keys(item))
    except AttributeError:
        return ["Item-Eintrag hat einen unerwarteten NBT-Typ"]
    if root_extra:
        summary.append(f"Root-Felder: {', '.join(root_extra[:6])}{' ...' if len(root_extra) > 6 else ''}")
    summary.extend(_item_control_field_type_issues(item))
    if "tag" not in item:
        return summary

    tag_compound = item["tag"]
    if not _is_compound_tag(tag_compound):
        summary.append("tag hat einen unerwarteten NBT-Typ")
        return summary

    allowed_tag_keys = _allowed_item_tag_keys(item) | _known_preserved_item_tag_keys(item)
    tag_extra = sorted(set(tag_compound.keys()) - allowed_tag_keys)
    if tag_extra:
        summary.append(f"Item-tag-Felder: {', '.join(tag_extra[:6])}{' ...' if len(tag_extra) > 6 else ''}")
    if "Damage" in tag_compound and not isinstance(tag_compound["Damage"], INTEGER_TAG_TYPES):
        summary.append("Item-tag-Damage hat einen unerwarteten NBT-Typ")

    if "display" in tag_compound:
        display_tag = tag_compound["display"]
        if not _is_compound_tag(display_tag):
            summary.append("display hat einen unerwarteten NBT-Typ")
        else:
            display_extra = sorted(set(display_tag.keys()) - {"Name", "Lore"})
            if display_extra:
                summary.append(f"Display-Felder: {', '.join(display_extra[:6])}{' ...' if len(display_extra) > 6 else ''}")
            if "Name" in display_tag and not isinstance(display_tag["Name"], nbt.StringTag):
                summary.append("Display-Name hat einen unerwarteten NBT-Typ")
            if "Lore" in display_tag:
                lore_tag = display_tag["Lore"]
                if not _is_list_tag(lore_tag) or any(not isinstance(line, nbt.StringTag) for line in lore_tag):
                    summary.append("Lore hat einen unerwarteten NBT-Typ")

    seen_editable_enchantment_ids = set()
    protected_enchantment_count = 0
    for list_name in ("ench", "enchantments"):
        if list_name not in tag_compound:
            continue
        if not _is_list_tag(tag_compound[list_name]):
            summary.append(f"{list_name} hat einen unerwarteten NBT-Typ")
            continue
        extra_count = 0
        for ench in tag_compound[list_name]:
            if _compound_has_extra_keys(ench, {"id", "lvl"}):
                extra_count += 1
            editable_values = _editable_known_enchantment_values(ench)
            ench_id = _enchantment_id_from_tag(ench)
            if ench_id in ENCHANTMENTS:
                if editable_values is None or ench_id in seen_editable_enchantment_ids:
                    protected_enchantment_count += 1
                else:
                    seen_editable_enchantment_ids.add(ench_id)
        if extra_count:
            summary.append(t("{count} Verzauberungseintrag/Einträge mit Zusatzfeldern", count=extra_count))
    if protected_enchantment_count:
        summary.append(t("{count} nicht eindeutig bearbeitbare Verzauberungseinträge", count=protected_enchantment_count))

    return summary


def _item_preserved_nbt_summary(item) -> list[str]:
    summary = []
    root_keys = _preserved_item_root_keys(item)
    if root_keys:
        summary.append(f"Standard-Root-Felder: {', '.join(root_keys)}")
    tag_keys = _preserved_item_tag_keys(item)
    if tag_keys:
        summary.append(f"Bekannte Item-tag-Felder: {', '.join(tag_keys[:8])}{' ...' if len(tag_keys) > 8 else ''}")
    try:
        tag_compound = item.get("tag")
    except AttributeError:
        tag_compound = None
    if _is_compound_tag(tag_compound) and "display" in tag_compound and _is_compound_tag(tag_compound["display"]):
        display_extra = sorted(set(tag_compound["display"].keys()) - {"Name", "Lore"})
        if display_extra:
            summary.append(f"Erhaltene Display-Felder: {', '.join(display_extra[:6])}{' ...' if len(display_extra) > 6 else ''}")
    return summary


def _item_has_preserved_nbt(item) -> bool:
    return bool(_item_preserved_nbt_summary(item) or _item_protected_nbt_summary(item))


def _contained_actor_identifier(item) -> str:
    for compound in reversed(_entity_data_candidate_compounds(item)):
        for key in ("identifier", "Identifier", "ActorIdentifier", "id"):
            actor_tag = compound.get(key) if hasattr(compound, "get") else None
            if not isinstance(actor_tag, nbt.StringTag):
                continue
            value = _normalize_entity_identifier(str(get_tag_value(actor_tag, "")))
            if value:
                return value
    return ""


def _axolotl_variant_value(item):
    compounds = _entity_data_candidate_compounds(item)
    invalid_numeric_source = ""
    for compound in reversed(compounds):
        for key in ("Variant", "ColorID", "BodyID"):
            tag = compound.get(key)
            if not isinstance(tag, NUMERIC_TAG_TYPES):
                continue
            value = _integer_tag_value_from_compound(compound, key)
            if value in AXOLOTL_VARIANTS:
                return value, key, True
            # The deepest numeric entity state remains authoritative for
            # editability. A valid language-key field may still provide a
            # read-only label, but an outer numeric value must not mask it.
            invalid_numeric_source = key
            break
        if invalid_numeric_source:
            break
    for compound in reversed(compounds):
        for key in ("Variant", "ColorID", "BodyID"):
            raw_value = _scalar_string_from_compound(compound, key)
            compact = _compact_variant_token(raw_value)
            for prefix in ("itemaxolotlcolor", "axolotlcolor", "color"):
                if compact.startswith(prefix):
                    compact = compact[len(prefix) :]
                    break
            if compact in AXOLOTL_VARIANT_BY_COLOR_TOKEN:
                return AXOLOTL_VARIANT_BY_COLOR_TOKEN[compact], key, False
    return None, invalid_numeric_source, False


def _axolotl_age_state(item) -> tuple[bool, bool]:
    compounds = _entity_data_candidate_compounds(item)
    for compound in reversed(compounds):
        for key in ("IsBaby", "Baby"):
            tag = compound.get(key)
            if isinstance(tag, NUMERIC_TAG_TYPES) and not isinstance(tag, INTEGER_TAG_TYPES):
                return False, False
            value = _integer_tag_value_from_compound(compound, key)
            if value is not None:
                return bool(value), True
        age_tag = compound.get("Age")
        if isinstance(age_tag, NUMERIC_TAG_TYPES) and not isinstance(age_tag, INTEGER_TAG_TYPES):
            return False, False
        age = _integer_tag_value_from_compound(compound, "Age")
        if age is not None:
            return age < 0, True
    for compound in reversed(compounds):
        body_id = _compact_variant_token(_scalar_string_from_compound(compound, "BodyID"))
        if body_id:
            if "baby" in body_id:
                return True, False
            if "adult" in body_id:
                return False, False
    return False, False


def _edited_axolotl_age(current_age: int, is_baby: bool) -> int:
    if not is_baby:
        return max(current_age, 0)
    if current_age < 0:
        return min(current_age, -1)
    return AXOLOTL_BABY_AGE_TICKS


def _mapped_compact_token(raw_value: str, mapping: dict, prefixes=(), suffixes=()):
    compact = _compact_variant_token(raw_value)
    candidates = [compact]
    for prefix in prefixes:
        if compact.startswith(prefix):
            candidates.append(compact[len(prefix) :])
    for candidate in list(candidates):
        for suffix in suffixes:
            if candidate.endswith(suffix):
                candidates.append(candidate[: -len(suffix)])
    for candidate in candidates:
        if candidate in mapping:
            return mapping[candidate]
    return None


def _tropical_group_token(raw_value: str) -> str:
    compact = _compact_variant_token(raw_value)
    candidates = [compact]
    for prefix in ("itemtropicalschool", "tropicalschool", "school"):
        if compact.startswith(prefix):
            candidates.append(compact[len(prefix) :])
    return next((candidate for candidate in candidates if candidate in TROPICAL_FISH_GROUP_LABELS), "")


def _tropical_pattern_values(raw_value: str):
    return _mapped_compact_token(
        raw_value,
        TROPICAL_FISH_PATTERN_VALUES_BY_TOKEN,
        prefixes=("itemtropicalbody", "tropicalbody", "body"),
        suffixes=("single", "multi"),
    )


def _tropical_body_shape(raw_value: str) -> str:
    compact = _compact_variant_token(raw_value)
    if compact.endswith("single"):
        return "single"
    if compact.endswith("multi"):
        return "multi"
    return ""


def _tropical_color_value(raw_value: str):
    return _mapped_compact_token(
        raw_value,
        TROPICAL_FISH_COLOR_VALUE_BY_TOKEN,
        prefixes=("itemtropicalcolor", "tropicalcolor", "color"),
    )


def _tropical_state_field(key: str, raw: str, display_de: str, display_en: str) -> EntityVariantField:
    labels = {
        "BodyID": ("Körperform", "Body"),
        "ColorID": ("Farbe 1", "Color 1"),
        "Color2ID": ("Farbe 2", "Color 2"),
    }
    label_de, label_en = labels[key]
    return {
        "key": key,
        "label_de": label_de,
        "label_en": label_en,
        "raw": raw,
        "display_de": display_de,
        "display_en": display_en,
    }


def _tropical_fish_bucket_variant(item, actor: str) -> EntityVariantInfo | None:
    name = _item_name_from_tag(item)
    if name not in TROPICAL_FISH_BUCKET_ITEM_IDS and actor not in TROPICAL_FISH_ENTITY_IDS:
        return None

    display_fields = {}
    source_keys = []
    state = {
        "variant": None,
        "mark_variant": None,
        "color": None,
        "color2": None,
    }
    numeric_state_keys = set()
    state_keys = {
        "Variant": ("variant", 0, 1),
        "MarkVariant": ("mark_variant", 0, 5),
        "Color": ("color", 0, 15),
        "Color2": ("color2", 0, 15),
    }
    group_token = ""
    body_pattern = None
    body_shape = ""

    compounds = _entity_data_candidate_compounds(item)
    for compound in compounds:
        for field in (
            _tropical_fish_field(
                compound,
                "GroupName",
                "Name",
                "Name",
                TROPICAL_FISH_GROUP_LABELS,
                ("itemtropicalschool", "tropicalschool", "school"),
            ),
            _tropical_fish_field(
                compound,
                "BodyID",
                "Körperform",
                "Body",
                TROPICAL_FISH_GROUP_LABELS,
                ("itemtropicalschool", "tropicalschool", "school"),
            ),
            _tropical_fish_field(
                compound,
                "ColorID",
                "Farbe 1",
                "Color 1",
                TROPICAL_FISH_COLOR_LABELS,
                ("itemtropicalcolor", "tropicalcolor", "color"),
            ),
            _tropical_fish_field(
                compound,
                "Color2ID",
                "Farbe 2",
                "Color 2",
                TROPICAL_FISH_COLOR_LABELS,
                ("itemtropicalcolor", "tropicalcolor", "color"),
            ),
        ):
            if field is None:
                continue
            display_fields[field["key"]] = field
            if field["key"] not in source_keys:
                source_keys.append(field["key"])

        for raw_key in ("GroupName", "BodyID"):
            raw_value = _scalar_string_from_compound(compound, raw_key)
            group_token = _tropical_group_token(raw_value) or group_token
        raw_body = _scalar_string_from_compound(compound, "BodyID")
        body_pattern = _tropical_pattern_values(raw_body) or body_pattern
        body_shape = _tropical_body_shape(raw_body) or body_shape
        for raw_key, state_key in (("ColorID", "color"), ("Color2ID", "color2")):
            raw_value = _scalar_string_from_compound(compound, raw_key)
            color_value = _tropical_color_value(raw_value)
            if state[state_key] is None and color_value is not None:
                state[state_key] = color_value

    resolved_numeric_state_keys = set()
    for compound in reversed(compounds):
        for raw_key, (state_key, minimum, maximum) in state_keys.items():
            if state_key in resolved_numeric_state_keys:
                continue
            tag = compound.get(raw_key)
            if not isinstance(tag, NUMERIC_TAG_TYPES):
                continue
            resolved_numeric_state_keys.add(state_key)
            value = _integer_tag_value_from_compound(compound, raw_key)
            if value is None or not minimum <= value <= maximum:
                continue
            state[state_key] = value
            numeric_state_keys.add(state_key)
            if raw_key not in source_keys:
                source_keys.append(raw_key)

    if group_token in TROPICAL_FISH_PRESET_VALUES:
        preset = TROPICAL_FISH_PRESET_VALUES[group_token]
        for state_key, value in zip(("variant", "mark_variant", "color", "color2"), preset, strict=True):
            if state[state_key] is None:
                state[state_key] = value
    if body_pattern is not None:
        if state["variant"] is None:
            state["variant"] = body_pattern[0]
        if state["mark_variant"] is None:
            state["mark_variant"] = body_pattern[1]

    has_state = all(state[key] is not None for key in ("variant", "mark_variant", "color", "color2"))
    has_numeric_state = numeric_state_keys == {"variant", "mark_variant", "color", "color2"}
    if not display_fields and not has_state:
        return None

    if "BodyID" in display_fields and body_pattern is not None:
        pattern = TROPICAL_FISH_PATTERN_BY_VALUES.get(body_pattern)
        if pattern:
            _token, label_de, label_en = pattern
            if body_pattern == (0, 3):
                colors_known = state["color"] is not None and state["color2"] is not None
                single_shape = state["color"] == state["color2"] if colors_known else body_shape == "single"
                label_de = "Dasher" if single_shape else "Flitzer"
            display_fields["BodyID"]["display_de"] = label_de
            display_fields["BodyID"]["display_en"] = label_en

    if "BodyID" not in display_fields and state["variant"] is not None and state["mark_variant"] is not None:
        pattern = TROPICAL_FISH_PATTERN_BY_VALUES.get((state["variant"], state["mark_variant"]))
        if pattern:
            token, label_de, label_en = pattern
            known_same_color = state["color"] is not None and state["color2"] is not None and state["color"] == state["color2"]
            if (state["variant"], state["mark_variant"]) == (0, 3):
                label_de = "Dasher" if known_same_color else "Flitzer"
            display_fields["BodyID"] = _tropical_state_field(
                "BodyID",
                f"item.tropicalBody{token}{'Single' if known_same_color else 'Multi'}.name",
                label_de,
                label_en,
            )
    for field_key, state_key in (("ColorID", "color"), ("Color2ID", "color2")):
        if field_key in display_fields or state[state_key] is None:
            continue
        token = TROPICAL_FISH_COLOR_TOKEN_BY_VALUE[state[state_key]]
        label_de, label_en = TROPICAL_FISH_COLOR_LABELS[token.lower()]
        display_fields[field_key] = _tropical_state_field(
            field_key,
            f"item.tropicalColor{token}.name",
            label_de,
            label_en,
        )

    fields = [display_fields[key] for key in ("GroupName", "BodyID", "ColorID", "Color2ID") if key in display_fields]
    group = display_fields.get("GroupName")
    body = display_fields.get("BodyID")
    color1 = display_fields.get("ColorID")
    color2 = display_fields.get("Color2ID")
    name_part = group or body
    visible_colors = (color1,) if color1 and color2 and state["color"] == state["color2"] else (color1, color2)
    color_part_de = "/".join(field["display_de"] for field in visible_colors if field)
    color_part_en = "/".join(field["display_en"] for field in visible_colors if field)
    display_parts_de = [name_part["display_de"]] if name_part else []
    display_parts_en = [name_part["display_en"]] if name_part else []
    if color_part_de:
        display_parts_de.append(color_part_de)
        display_parts_en.append(color_part_en)

    key_parts = [_compact_variant_token(field["display_en"] or field["raw"]) for field in fields]
    result: EntityVariantInfo = {
        "entity_id": "minecraft:tropical_fish",
        "key": "_".join(part for part in key_parts if part) or "tropical_fish",
        "kind_label_de": "Tropenfisch-Bucket",
        "kind_label_en": "Tropical Fish Bucket",
        "label_de": ", ".join(display_parts_de) or "Tropenfisch",
        "label_en": ", ".join(display_parts_en) or "Tropical Fish",
        "display_name_de": f"Tropenfisch: {', '.join(display_parts_de)}" if display_parts_de else "Tropenfisch",
        "display_name_en": f"Tropical Fish: {', '.join(display_parts_en)}" if display_parts_en else "Tropical Fish",
        "fields": fields,
        "source": ", ".join(source_keys),
        # BodyID/ColorID/GroupName also drive the bucket's localized label,
        # but those strings alone are not proof of a complete captured entity.
        # Only expose mutation when all four numeric entity-state fields exist.
        "can_edit": has_numeric_state,
    }
    if state["variant"] is not None:
        result["variant"] = state["variant"]
    if state["mark_variant"] is not None:
        result["mark_variant"] = state["mark_variant"]
    if state["color"] is not None:
        result["color"] = state["color"]
    if state["color2"] is not None:
        result["color2"] = state["color2"]
    return result


def _item_entity_variant(item) -> EntityVariantInfo | None:
    name = _item_name_from_tag(item)
    actor = _contained_actor_identifier(item)
    if name in AXOLOTL_ITEM_IDS and actor and actor != AXOLOTL_ENTITY_ID:
        return None
    if name in TROPICAL_FISH_BUCKET_ITEM_IDS and actor and actor not in TROPICAL_FISH_ENTITY_IDS:
        return None
    if name in AXOLOTL_ITEM_IDS or actor == AXOLOTL_ENTITY_ID:
        variant_value, source_field, numeric_variant = _axolotl_variant_value(item)
        if variant_value is None:
            return None
        variant = AXOLOTL_VARIANTS[variant_value]
        key = variant["key"]
        is_baby, numeric_age = _axolotl_age_state(item)
        icon_key = f"mcbe:axolotl_{key}{'_baby' if is_baby else ''}"
        return {
            "entity_id": AXOLOTL_ENTITY_ID,
            "variant": variant_value,
            "key": key,
            "kind_label_de": "Entity-Variante",
            "kind_label_en": "Entity variant",
            "value_label_de": "Axolotl-Datenwert",
            "value_label_en": "Axolotl data value",
            "label_de": variant["label_de"],
            "label_en": variant["label_en"],
            "display_name_de": variant["display_de"],
            "display_name_en": variant["display_en"],
            "icon_key": icon_key,
            "adult_icon_key": f"mcbe:axolotl_{key}",
            "baby_icon_key": f"mcbe:axolotl_{key}_baby",
            "is_baby": is_baby,
            "source": source_field,
            # Language keys are useful for display, but editing them without
            # numeric Variant + age state could create a bucket whose label and
            # spawned entity disagree.
            "can_edit": numeric_variant and numeric_age,
        }
    return _tropical_fish_bucket_variant(item, actor)


def _item_entity_variant_state(item, variant: EntityVariantInfo | None) -> str | None:
    """Classify axolotl buckets without inventing a concrete stored animal."""
    if _item_name_from_tag(item) not in AXOLOTL_ITEM_IDS:
        return None
    if variant is not None:
        return "captured"

    evidence_keys = {
        "ActorIdentifier",
        "Age",
        "Baby",
        "BodyID",
        "ColorID",
        "EntityTag",
        "Identifier",
        "IsBaby",
        "SaveData",
        "Variant",
        "definitions",
        "identifier",
    }
    if _contained_actor_identifier(item):
        return "unresolved"
    if any(any(key in compound for key in evidence_keys) for compound in _entity_data_candidate_compounds(item)):
        return "unresolved"
    return "generic"


def _finite_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _finite_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (OverflowError, TypeError, ValueError):
        return default
    return parsed


def _parse_bool_input(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, float) and math.isfinite(value) and value in (0.0, 1.0):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "ja"}:
            return True
        if normalized in {"false", "0", "no", "nein"}:
            return False
    if value is None:
        return default
    raise ValueError("Ungültiger boolescher Wert empfangen.")


def _strict_float(value, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(t("Ungültiger {field}: {value}", field=field_name, value=value))
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ValueError(t("Ungültiger {field}: {value}", field=field_name, value=value)) from None
    if not math.isfinite(parsed):
        raise ValueError(t("Ungültiger {field}: {value}", field=field_name, value=value))
    return parsed


def _strict_int(value, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(t("Ungültiger {field}: {value}", field=field_name, value=value))
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        raise ValueError(t("Ungültiger {field}: {value}", field=field_name, value=value))
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    raise ValueError(t("Ungültiger {field}: {value}", field=field_name, value=value))


def _signed_byte_to_unsigned(value: int) -> int:
    return value + 256 if value < 0 else value


def _unsigned_to_signed_byte(value: int) -> int:
    return value - 256 if value > 127 else value


def _is_compound_tag(tag) -> bool:
    return isinstance(tag, nbt.CompoundTag)


def _is_list_tag(tag) -> bool:
    return isinstance(tag, nbt.ListTag)


def _nbt_view_value(tag, depth: int = 0):
    tag_type = type(tag).__name__
    if depth >= MAX_NBT_VIEW_DEPTH:
        return {"type": tag_type, "value": "<gekürzt: maximale Tiefe erreicht>"}

    if _is_compound_tag(tag):
        value = {}
        keys = sorted(str(key) for key in tag)
        for key in keys[:MAX_NBT_VIEW_ITEMS]:
            value[key] = _nbt_view_value(tag[key], depth + 1)
        result = {"type": tag_type, "value": value}
        if len(keys) > MAX_NBT_VIEW_ITEMS:
            result["truncated"] = f"{len(keys) - MAX_NBT_VIEW_ITEMS} weitere Felder"
        return result

    if _is_list_tag(tag):
        entries = list(tag)
        result = {"type": tag_type, "value": [_nbt_view_value(entry, depth + 1) for entry in entries[:MAX_NBT_VIEW_ITEMS]]}
        if len(entries) > MAX_NBT_VIEW_ITEMS:
            result["truncated"] = t("{count} weitere Einträge", count=len(entries) - MAX_NBT_VIEW_ITEMS)
        return result

    value = get_tag_value(tag)
    if isinstance(value, str) and len(value) > MAX_NBT_VIEW_STRING:
        value = value[:MAX_NBT_VIEW_STRING] + "..."
    elif isinstance(value, (bytes, bytearray, list, tuple)) or hasattr(value, "tolist"):
        converted = value.tolist() if hasattr(value, "tolist") else value
        sequence = list(converted)
        value = sequence[:MAX_NBT_VIEW_ITEMS]
        if len(sequence) > MAX_NBT_VIEW_ITEMS:
            return {"type": tag_type, "value": value, "truncated": f"{len(sequence) - MAX_NBT_VIEW_ITEMS} weitere Werte"}
    return {"type": tag_type, "value": value}


def _is_editable_item_list(tag) -> bool:
    return _is_list_tag(tag)


def _root_item_list_presence_count(player_tag, tag_name: str) -> int:
    tag = player_tag.get(tag_name) if hasattr(player_tag, "get") else None
    if not _is_list_tag(tag):
        return 0
    count = 0
    empty_fields = {"Slot", "Name", "Count", "Damage", "WasPickedUp"}
    for entry in tag:
        if not _is_compound_tag(entry):
            count += 1
            continue
        try:
            keys = set(entry.keys())
        except AttributeError:
            count += 1
            continue
        if not keys:
            continue
        if keys - empty_fields:
            count += 1
            continue
        name = str(get_tag_value(entry.get("Name"), "")).strip().lower()
        try:
            item_count = int(get_tag_value(entry.get("Count"), 0))
        except (OverflowError, TypeError, ValueError):
            count += 1
            continue
        if item_count > 0 or (name and name not in {"air", "minecraft:air"}):
            count += 1
    return count


def _root_item_list_presence_counts(player_tag):
    return {tag_name: present for tag_name in ROOT_ITEM_LIST_TAGS if (present := _root_item_list_presence_count(player_tag, tag_name)) > 0}


def _root_item_list_opaque_flags(player_tag):
    return {tag_name: True for tag_name in ROOT_ITEM_LIST_TAGS if tag_name in player_tag and not _is_list_tag(player_tag[tag_name])}


def protected_player_nbt_flags(player_tag):
    """Return flags for player-level NBT shapes the editor must not rewrite.

    The UI only shows structured forms for Bedrock's standard list/compound
    shapes. If a future version or add-on stores one of those known keys with
    an unexpected tag type, normal saves must preserve it instead of replacing
    it with a standard shape built from default form values.
    """

    return {
        "has_inventory_tag": "Inventory" in player_tag,
        "has_ender_chest_tag": "EnderChestInventory" in player_tag,
        "has_active_effects_tag": "ActiveEffects" in player_tag,
        "has_abilities_tag": "abilities" in player_tag,
        "inventory_opaque": "Inventory" in player_tag and not _is_list_tag(player_tag["Inventory"]),
        "ender_chest_opaque": "EnderChestInventory" in player_tag and not _is_list_tag(player_tag["EnderChestInventory"]),
        "active_effects_opaque": "ActiveEffects" in player_tag and not _is_list_tag(player_tag["ActiveEffects"]),
        "abilities_opaque": "abilities" in player_tag and not _is_compound_tag(player_tag["abilities"]),
        "ability_fields_opaque": _ability_field_opaque_fields(player_tag),
        "dimension_id_missing": "DimensionId" not in player_tag,
        "dimension_id_opaque": _dimension_id_tag_opaque(player_tag),
        "pos_opaque": _position_tag_opaque(player_tag),
        "pos_missing": "Pos" not in player_tag,
        "stat_fields_opaque": _scalar_stat_opaque_fields(player_tag),
        "active_effect_entries_opaque": _active_effects_opaque_entry_count(player_tag),
        "root_item_lists_present": _root_item_list_presence_counts(player_tag),
        "root_item_lists_opaque": _root_item_list_opaque_flags(player_tag),
    }


def _tag_item_name_matches(item_tag, normalized_name: str) -> bool:
    if not item_tag or not hasattr(item_tag, "get"):
        return False
    original_name = str(get_tag_value(item_tag.get("Name"), "")).strip()
    return bool(original_name) and original_name.lower() == normalized_name


def _parse_item_slot(item) -> ParsedItemSlot:
    if not _item_entry_has_editable_shape(item):
        raise ValueError("Inventar-Eintrag hat keinen sicher editierbaren NBT-Aufbau.")

    slot = _read_item_slot(item, 0)
    name = str(get_tag_value(item.get("Name"), ""))
    count = _safe_int_from_tag(item.get("Count"), 0)
    damage = _read_editable_item_damage(item, name.strip().lower())

    display_name = ""
    lore = []
    enchantments = []
    has_unknown_enchantments = False

    if "tag" in item:
        tag_compound = item["tag"]
        if _is_compound_tag(tag_compound):
            if "display" in tag_compound and _is_compound_tag(tag_compound["display"]):
                display_comp = tag_compound["display"]
                display_name = get_tag_value(display_comp.get("Name"), "")
                lore_list = display_comp.get("Lore")
                if _is_list_tag(lore_list):
                    lore = [str(get_tag_value(x, "")) for x in lore_list]

            seen_enchantment_ids = set()
            if "ench" in tag_compound:
                enchantments.extend(_extract_known_enchantments(tag_compound["ench"], seen_ids=seen_enchantment_ids))
                has_unknown_enchantments = _has_unknown_enchantments(tag_compound["ench"])
            if "enchantments" in tag_compound:
                enchantments.extend(_extract_known_enchantments(tag_compound["enchantments"], seen_ids=seen_enchantment_ids))
                has_unknown_enchantments = has_unknown_enchantments or _has_unknown_enchantments(tag_compound["enchantments"])

    entity_variant = _item_entity_variant(item)
    return {
        "slot": slot,
        # Opaque same-container origin marker used to preserve future/add-on NBT
        # when an existing item is moved or copied to another known slot.  The
        # editor may change the target slot, but the backend can still copy the
        # original compound and only update controlled fields.
        "source_slot": slot,
        "name": name,
        "count": count,
        "damage": damage,
        "display_name": display_name,
        "lore": lore,
        "enchantments": enchantments,
        "has_unknown_enchantments": has_unknown_enchantments,
        "has_protected_nbt": _item_has_protected_nbt(item),
        "has_preserved_nbt": _item_has_preserved_nbt(item),
        "item_tag_opaque": "tag" in item and not _is_compound_tag(item["tag"]),
        "entity_variant": entity_variant,
        "entity_variant_state": _item_entity_variant_state(item, entity_variant),
        "preserved_nbt_summary": _item_preserved_nbt_summary(item),
        "protected_nbt_summary": _item_protected_nbt_summary(item),
        "nbt_view": _nbt_view_value(item),
    }


def _read_item_slot(item, default=None):
    if not hasattr(item, "get"):
        return default
    slot_tag = item.get("Slot")
    if slot_tag is not None and not isinstance(slot_tag, INTEGER_TAG_TYPES):
        return default
    try:
        return int(get_tag_value(slot_tag, default))
    except (OverflowError, TypeError, ValueError):
        return default


def _item_entry_has_editable_shape(item) -> bool:
    """Return whether an inventory entry can be represented as a visible item.

    Bedrock/add-ons may theoretically place non-compound entries, entries
    without a Name/Count, or other opaque data inside an otherwise standard
    Inventory list. Those entries must not be shown as editable items because a
    normal save could clear unknown NBT. Empty Bedrock placeholder compounds are
    handled separately by ``_item_entry_is_empty_placeholder`` so empty slots stay
    usable without treating them as unsafe data.
    """

    if not _is_compound_tag(item):
        return False
    if "Slot" not in item:
        return False
    if _item_control_field_type_issues(item):
        return False
    name = str(get_tag_value(item.get("Name"), "")).strip()
    if not name or name.lower() == "minecraft:air":
        return False
    try:
        count = int(get_tag_value(item.get("Count"), None))
    except (OverflowError, TypeError, ValueError):
        return False
    return count > 0


def _item_entry_is_empty_placeholder(item) -> bool:
    """Return True for Bedrock empty-slot placeholders that are safe to reuse.

    Some Bedrock player records contain fixed-length inventory/ender lists with
    empty slot compounds such as ``{Slot: 23}``, ``{Slot: 23, Name: air}``, or
    count-zero variants.  Earlier safety logic classified these as protected NBT
    and therefore locked almost every empty slot.  A placeholder is only accepted
    when all present fields are standard empty-item fields and there is no
    payload/tag data that would be lost.  Untouched placeholders are preserved;
    if the user writes an item into that slot, the placeholder is replaced.
    """

    if not _is_compound_tag(item):
        return False
    try:
        keys = set(item.keys())
    except AttributeError:
        return False
    if not keys or "Slot" not in keys:
        return False
    allowed = {"Slot", "Name", "Count", "Damage", "WasPickedUp"}
    if keys - allowed:
        return False
    if _item_control_field_type_issues(item):
        return False
    name = str(get_tag_value(item.get("Name"), "")).strip().lower()
    if name not in {"", "minecraft:air", "air"}:
        return False
    try:
        count = int(get_tag_value(item.get("Count"), 0))
    except (OverflowError, TypeError, ValueError):
        return False
    if count > 0 and name not in {"minecraft:air", "air"}:
        return False
    return count <= 0 or name in {"minecraft:air", "air"}


def items_by_slot_for_origin(list_tag):
    """Map slot IDs to the item compound the UI can faithfully reference.

    Duplicate or future/opaque entries can exist in the same NBT list.  For
    preserving source NBT during moves/copies, prefer the editable item the UI
    actually rendered.  A later protected duplicate with the same slot must not
    hide the visible item's original compound, otherwise a normal save can rebuild
    the visible item from JSON and lose its preserved add-on/future fields.
    """

    items_by_slot = {}
    if not _is_list_tag(list_tag):
        return items_by_slot
    for item in list_tag:
        slot = _read_item_slot(item)
        if slot is None:
            continue
        if _item_entry_has_editable_shape(item) or slot not in items_by_slot:
            items_by_slot[slot] = item
    return items_by_slot


def _original_items_by_slot(player_tag, tag_name):
    return items_by_slot_for_origin(player_tag[tag_name]) if tag_name in player_tag else {}


def nbt_to_json(player_tag) -> tuple[dict[int, ParsedItemSlot], dict[int, Any]]:
    inventory_data = {}
    original_items = {}

    if "Inventory" in player_tag and _is_list_tag(player_tag["Inventory"]):
        original_items = items_by_slot_for_origin(player_tag["Inventory"])
        for item in player_tag["Inventory"]:
            try:
                parsed = _parse_item_slot(item)
            except (AttributeError, OverflowError, TypeError, ValueError):
                continue
            slot = parsed["slot"]
            # Only expose slots that the UI/API intentionally edits. Unknown
            # Bedrock inventory slots are preserved server-side when saving, but
            # hidden from the browser so a normal save cannot fail on or rewrite
            # data the editor does not understand.
            if slot in VALID_INVENTORY_SLOTS:
                inventory_data[slot] = parsed

    return inventory_data, original_items


def parse_ender_chest(player_tag) -> dict[int, ParsedItemSlot]:
    chest_data = {}
    if "EnderChestInventory" in player_tag and _is_list_tag(player_tag["EnderChestInventory"]):
        for item in player_tag["EnderChestInventory"]:
            try:
                parsed = _parse_item_slot(item)
            except (AttributeError, OverflowError, TypeError, ValueError):
                continue
            if parsed["slot"] in ENDER_CHEST_SLOTS:
                chest_data[parsed["slot"]] = parsed

    return chest_data


def _hidden_slot_summary(player_tag, tag_name, valid_slots):
    """Summarize entries the UI cannot faithfully edit for one item list.

    Unknown/future slot IDs are hidden and preserved. A more subtle case is a
    standard slot ID that contains a non-editable/opaque item entry. If the UI
    shows that slot as empty, the user could paste a new item into it and create
    an ambiguous duplicate slot while the protected entry is still preserved.
    Report those protected-only slots explicitly so the browser can mark them as
    blocked instead of pretending they are empty.
    """

    hidden = 0
    protected_known = 0
    protected_slots = set()
    editable_slots = set()
    if tag_name in player_tag and _is_list_tag(player_tag[tag_name]):
        for item in player_tag[tag_name]:
            slot = _read_item_slot(item)
            if slot not in valid_slots:
                hidden += 1
            elif _item_entry_has_editable_shape(item):
                editable_slots.add(slot)
            elif _item_entry_is_empty_placeholder(item):
                # Empty fixed-list placeholders are safe and should not lock the slot.
                continue
            else:
                protected_known += 1
                protected_slots.add(slot)
    return {
        "hidden": hidden,
        "protected_known": protected_known,
        "protected_known_slots": sorted(protected_slots - editable_slots),
    }


def count_hidden_unknown_slots(player_tag):
    """Count preserved inventory entries that the UI deliberately does not edit."""

    inventory_summary = _hidden_slot_summary(player_tag, "Inventory", VALID_INVENTORY_SLOTS)
    ender_summary = _hidden_slot_summary(player_tag, "EnderChestInventory", ENDER_CHEST_SLOTS)

    flags = protected_player_nbt_flags(player_tag)
    return {
        "inventory": inventory_summary["hidden"],
        "ender_chest": ender_summary["hidden"],
        "inventory_protected_known": inventory_summary["protected_known"],
        "ender_chest_protected_known": ender_summary["protected_known"],
        "inventory_protected_known_slots": inventory_summary["protected_known_slots"],
        "ender_chest_protected_known_slots": ender_summary["protected_known_slots"],
        "inventory_opaque": flags["inventory_opaque"],
        "ender_chest_opaque": flags["ender_chest_opaque"],
    }


def extract_player_stats(player_tag) -> PlayerStats:
    defaults = [0.0, 70.0, 0.0]
    pos = defaults.copy()
    if "Pos" in player_tag and _is_list_tag(player_tag["Pos"]):
        raw_pos = list(player_tag["Pos"])[:3]
        for idx, default in enumerate(defaults):
            if idx < len(raw_pos):
                pos[idx] = _finite_float(get_tag_value(raw_pos[idx], default), default)

    dimension_id = None
    dimension_tag = player_tag.get("DimensionId")
    if isinstance(dimension_tag, nbt.IntTag):
        dimension_id = _finite_int(get_tag_value(dimension_tag, None), None)

    return {
        "pos": pos,
        "dimension_id": dimension_id,
        "health": _finite_float(_scalar_stat_value(player_tag, "health", 20.0), 20.0),
        "gamemode": _finite_int(_scalar_stat_value(player_tag, "gamemode", 0), 0),
        "xp_level": _finite_int(_scalar_stat_value(player_tag, "xp_level", 0), 0),
        "xp_progress": _finite_float(_scalar_stat_value(player_tag, "xp_progress", 0.0), 0.0),
        "food_level": _finite_int(_scalar_stat_value(player_tag, "food_level", 20), 20),
        "food_saturation": _finite_float(_scalar_stat_value(player_tag, "food_saturation", 20.0), 20.0),
    }


def parse_effects(player_tag):
    effects = []
    if "ActiveEffects" not in player_tag or not _is_list_tag(player_tag["ActiveEffects"]):
        return effects
    seen_editable_ids = set()
    for eff in player_tag["ActiveEffects"]:
        if not hasattr(eff, "get"):
            effects.append(
                {
                    "id": -1,
                    "amplifier": 0,
                    "duration": 0,
                    "ambient": False,
                    "show_particles": True,
                    "show_icon": True,
                    "opaque": True,
                }
            )
            continue
        e_id = _signed_byte_to_unsigned(_finite_int(get_tag_value(eff.get("Id"), 0), 0))
        amplifier = _signed_byte_to_unsigned(_finite_int(get_tag_value(eff.get("Amplifier"), 0), 0))
        duration = _finite_int(get_tag_value(eff.get("Duration"), 0), 0)
        ambient = bool(get_tag_value(eff.get("Ambient"), False))
        show_particles = bool(get_tag_value(eff.get("ShowParticles"), True))
        show_icon = bool(get_tag_value(eff.get("ShowIcon"), True))
        effect_data = {
            "id": e_id,
            "amplifier": amplifier,
            "duration": duration,
            "ambient": ambient,
            "show_particles": show_particles,
            "show_icon": show_icon,
        }
        if _effect_control_fields_opaque(eff):
            effect_data["opaque"] = True
            effect_data["opaque_reason"] = "Effekt enthält unerwartete NBT-Typen und wird geschützt erhalten."
        elif e_id in EFFECTS and e_id in seen_editable_ids:
            effect_data["opaque"] = True
            effect_data["opaque_reason"] = "Doppelter Effekt mit derselben ID wird geschützt erhalten."
        elif e_id in EFFECTS:
            seen_editable_ids.add(e_id)
        effects.append(effect_data)
    return effects


def parse_abilities(player_tag):
    if "abilities" not in player_tag:
        return {}
    ab = player_tag["abilities"]
    if not _is_compound_tag(ab):
        return {"_opaque": True}
    defaults = ABILITY_DEFAULTS
    return {
        "fly_speed": _finite_float(_ability_read_value(ab, "fly_speed", defaults["fly_speed"]), defaults["fly_speed"]),
        "walk_speed": _finite_float(_ability_read_value(ab, "walk_speed", defaults["walk_speed"]), defaults["walk_speed"]),
        "mayfly": bool(_ability_read_value(ab, "mayfly", defaults["mayfly"])),
        "flying": bool(_ability_read_value(ab, "flying", defaults["flying"])),
        "invulnerable": bool(_ability_read_value(ab, "invulnerable", defaults["invulnerable"])),
        "maybuild": bool(_ability_read_value(ab, "maybuild", defaults["maybuild"])),
        "instabuild": bool(_ability_read_value(ab, "instabuild", defaults["instabuild"])),
    }


def validate_effect(effect_data):
    if not isinstance(effect_data, Mapping):
        raise ValueError("Ungültige Effekt-Daten empfangen.")
    try:
        e_id = _strict_int(effect_data["id"], "Effekt-ID")
        amplifier = _strict_int(effect_data.get("amplifier", 0), "Verstärkung")
        duration = _strict_int(effect_data.get("duration", 0), "Dauer")
    except (KeyError, TypeError, ValueError):
        raise ValueError("Ungültige Effekt-Daten empfangen.") from None
    if not (0 <= e_id <= 255):
        raise ValueError(t("Effekt-ID außerhalb des gültigen Bereichs (0-255): {value}", value=e_id))
    if e_id not in EFFECTS:
        raise ValueError(f"Unbekannte Effekt-ID: {e_id}")
    if not (0 <= amplifier <= 255):
        raise ValueError(t("Verstärkung außerhalb des gültigen Bereichs (0-255): {value}", value=amplifier))
    if not (0 <= duration <= 2_147_483_647):
        raise ValueError(t("Dauer außerhalb des gültigen Bereichs: {value}", value=duration))
    try:
        ambient = _parse_bool_input(effect_data.get("ambient", False), False)
        show_particles = _parse_bool_input(effect_data.get("show_particles", True), True)
        show_icon = _parse_bool_input(effect_data.get("show_icon", True), True)
    except ValueError:
        raise ValueError("Ungültige Effekt-Daten empfangen.") from None
    return {
        "id": e_id,
        "amplifier": amplifier,
        "duration": duration,
        "ambient": ambient,
        "show_particles": show_particles,
        "show_icon": show_icon,
    }


def _validated_entity_variant_edit(item_data, name: str, slot: int):
    raw_edit = item_data.get("entity_variant_edit")
    if raw_edit is None:
        return None
    if not isinstance(raw_edit, dict):
        raise ValueError(t("Ungültige Entityvarianten-Daten in Slot {slot}.", slot=slot))

    kind = str(raw_edit.get("kind", "")).strip()
    expected_kind = ""
    if name in AXOLOTL_ITEM_IDS:
        expected_kind = "axolotl"
    elif name in TROPICAL_FISH_BUCKET_ITEM_IDS:
        expected_kind = "tropical_fish"
    if not expected_kind or kind != expected_kind:
        raise ValueError(t("Die Entityvariante passt nicht zum Item in Slot {slot}.", slot=slot))

    def strict_int(key: str, minimum: int, maximum: int) -> int:
        value = raw_edit.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(t("Ungültige Entityvarianten-Daten in Slot {slot}.", slot=slot))
        return value

    if kind == "axolotl":
        if set(raw_edit) - {"kind", "variant", "is_baby"}:
            raise ValueError(t("Ungültige Entityvarianten-Daten in Slot {slot}.", slot=slot))
        is_baby = raw_edit.get("is_baby")
        if not isinstance(is_baby, bool):
            raise ValueError(t("Ungültige Entityvarianten-Daten in Slot {slot}.", slot=slot))
        return {
            "kind": kind,
            "variant": strict_int("variant", 0, 4),
            "is_baby": is_baby,
        }

    if set(raw_edit) - {"kind", "variant", "mark_variant", "color", "color2"}:
        raise ValueError(t("Ungültige Entityvarianten-Daten in Slot {slot}.", slot=slot))
    return {
        "kind": kind,
        "variant": strict_int("variant", 0, 1),
        "mark_variant": strict_int("mark_variant", 0, 5),
        "color": strict_int("color", 0, 15),
        "color2": strict_int("color2", 0, 15),
    }


def validate_inventory_item(item_data, enchantments_db, is_ender_chest=False, *, defer_stack_limit=False, defer_original_bounds=False):
    """Validate browser item fields before resolving preserved source NBT.

    Write builders defer the catalog limit only until the exact source item is
    known, then immediately call :func:`validate_item_stack_count`. Direct
    callers keep strict Vanilla limits.

    ``defer_original_bounds`` postpones the damage, display name and lore limits
    the same way, for :func:`validate_item_original_bounds`. The payload always
    carries the complete container, so an existing item outside those limits --
    an add-on tool, or one from a newer game version than the local catalog --
    would otherwise block edits to every other slot.
    """
    # A JSON list can carry anything. Reject non-object entries up front so the
    # keyed access below -- and every ``item_data.get(...)`` after it -- cannot
    # raise TypeError/AttributeError and surface as an opaque HTTP 500.
    if not isinstance(item_data, Mapping):
        raise ValueError("Ungültige Item-Daten empfangen.")
    try:
        slot = _strict_int(item_data["slot"], "Slot")
        name = str(item_data["name"]).strip().lower()
        count = _strict_int(item_data["count"], "Menge")
        damage = _strict_int(item_data.get("damage", 0), "Damage-Wert")
    except (KeyError, TypeError, ValueError):
        raise ValueError("Ungültige Item-Daten empfangen.") from None

    valid_slots = ENDER_CHEST_SLOTS if is_ender_chest else VALID_INVENTORY_SLOTS
    if slot not in valid_slots:
        raise ValueError(t("Ungültiger Slot: {slot}", slot=slot))

    source_player_key = item_data.get("source_player_key")
    if source_player_key is not None:
        source_player_key = str(source_player_key).strip() or None

    source_container = item_data.get("source_container")
    if source_container is not None:
        source_container = str(source_container).strip() or None

    source_valid_slots = valid_slots
    if source_container == "inventory":
        source_valid_slots = VALID_INVENTORY_SLOTS
    elif source_container == "ender_chest":
        source_valid_slots = ENDER_CHEST_SLOTS

    source_slot = slot
    if "source_slot" in item_data:
        try:
            candidate_source_slot = _strict_int(item_data.get("source_slot"), "Quellslot")
        except ValueError:
            candidate_source_slot = slot
        if candidate_source_slot in source_valid_slots:
            source_slot = candidate_source_slot

    source_world_path = item_data.get("source_world_path")
    if source_world_path is not None:
        source_world_path = str(source_world_path).strip() or None

    if not name or name == "minecraft:air":
        return None
    if len(name) > MAX_TEXT_LENGTH or not ITEM_ID_RE.fullmatch(name):
        raise ValueError(t("Ungültige Item-ID: {name}", name=name))
    max_stack = get_max_stack(name) if is_known_item_id(name) else MAX_BEDROCK_STACK_COUNT
    effective_max_stack = MAX_BEDROCK_STACK_COUNT if defer_stack_limit else max_stack
    if not (1 <= count <= effective_max_stack):
        raise ValueError(t("Ungültige Menge für Slot {slot}: {count}. Erlaubt sind 1 bis {max} für {name}.", slot=slot, count=count, max=max_stack, name=name))
    item_max_damage = get_max_damage(name)
    if not defer_original_bounds and not (0 <= damage <= item_max_damage):
        raise ValueError(
            t(
                "Ungültiger Damage-Wert für Slot {slot}: {damage}. Erlaubt sind 0 bis {max} für {name}.",
                slot=slot,
                damage=damage,
                max=item_max_damage,
                name=name,
            )
        )

    # Leading/trailing spaces are valid Bedrock name formatting, exactly like in
    # Lore below. Trimming here would silently rewrite the custom name of every
    # untouched item whenever an unrelated slot is edited.
    display_name = str(item_data.get("display_name", ""))
    if not defer_original_bounds and len(display_name) > MAX_TEXT_LENGTH:
        raise ValueError(f"Anzeigename in Slot {slot} ist zu lang.")

    lore = item_data.get("lore", [])
    if not isinstance(lore, list):
        raise ValueError(f"Lore in Slot {slot} muss eine Liste sein.")
    # Empty lines and surrounding spaces are valid Lore formatting. Only fold
    # embedded line breaks because each list entry represents exactly one line.
    lore = [str(line).replace("\n", " ").replace("\r", " ") for line in lore]
    if not defer_original_bounds and (len(lore) > MAX_LORE_LINES or any(len(line) > MAX_TEXT_LENGTH for line in lore)):
        raise ValueError(f"Lore in Slot {slot} ist zu lang.")

    raw_enchantments = item_data.get("enchantments", [])
    if not isinstance(raw_enchantments, list):
        raise ValueError(t("Verzauberungen in Slot {slot} müssen eine Liste sein.", slot=slot))
    enchantments = []
    seen_enchantment_ids = set()
    for ench in raw_enchantments:
        # A non-object entry raises TypeError on the subscript below, which the route
        # could only report as an opaque HTTP 500 instead of an invalid-input error.
        if not isinstance(ench, Mapping):
            raise ValueError(t("Ungültige Verzauberung in Slot {slot}.", slot=slot))
        try:
            ench_id = _strict_int(ench["id"], "Verzauberungs-ID")
            ench_lvl = _strict_int(ench["lvl"], "Verzauberungslevel")
        except (KeyError, TypeError, ValueError):
            raise ValueError(t("Ungültige Verzauberung in Slot {slot}.", slot=slot)) from None
        if ench_id in seen_enchantment_ids:
            raise ValueError(f"Doppelte Verzauberung in Slot {slot}: {ench_id}")
        seen_enchantment_ids.add(ench_id)
        if ench_id not in enchantments_db:
            raise ValueError(f"Unbekannte Verzauberung in Slot {slot}: {ench_id}")
        max_lvl = int(enchantments_db[ench_id][2])
        if not (1 <= ench_lvl <= max_lvl):
            raise ValueError(t("Ungültiges Verzauberungslevel in Slot {slot}: {level}", slot=slot, level=ench_lvl))
        enchantments.append({"id": ench_id, "lvl": ench_lvl})

    return {
        "slot": slot,
        "source_slot": source_slot,
        "source_player_key": source_player_key,
        "source_container": source_container,
        "source_world_path": source_world_path,
        "name": name,
        "count": count,
        "damage": damage,
        "display_name": display_name,
        "lore": lore,
        "enchantments": enchantments,
        "entity_variant_edit": _validated_entity_variant_edit(item_data, name, slot),
        "claims_protected_nbt": bool(item_data.get("has_protected_nbt")),
        "claims_preserved_nbt": bool(item_data.get("has_preserved_nbt")),
        "claims_unknown_enchantments": bool(item_data.get("has_unknown_enchantments")),
    }


def _original_display_fields(item) -> tuple[str, list[str]]:
    """Return the display name and Lore exactly as :func:`_parse_item_slot` reads them."""

    tag_compound = item.get("tag") if hasattr(item, "get") else None
    if not _is_compound_tag(tag_compound):
        return "", []
    display_comp = tag_compound.get("display")
    if not _is_compound_tag(display_comp):
        return "", []
    lore_tag = display_comp.get("Lore")
    lore = [str(get_tag_value(line, "")) for line in lore_tag] if _is_list_tag(lore_tag) else []
    return str(get_tag_value(display_comp.get("Name"), "")), lore


def item_payload_matches_original(base_item_tag, validated_item, enchantments_db=None) -> bool:
    """Return whether a payload item still equals the original it resolved to.

    The visible form owns Count, the damage/data value, the display name, Lore
    and known enchantments. While all of those still match the source item, this
    slot carries no user edit -- the browser always echoes the complete container
    (see docs/save_contract.md), so most entries of a normal save are untouched.
    Such an item must survive byte-for-byte, including enchantment list order and
    empty standard containers like ``display: {}`` or ``ench: []``.
    """

    if base_item_tag is None or not _is_compound_tag(base_item_tag):
        return False
    if validated_item.get("entity_variant_edit") is not None:
        return False
    name = validated_item["name"]
    if not _tag_item_name_matches(base_item_tag, name):
        return False
    if _integer_tag_value_from_compound(base_item_tag, "Count") != validated_item["count"]:
        return False
    if _read_editable_item_damage(base_item_tag, name) != validated_item["damage"]:
        return False
    original_name, original_lore = _original_display_fields(base_item_tag)
    if original_name != validated_item["display_name"] or original_lore != validated_item["lore"]:
        return False
    return _item_known_enchantments(base_item_tag, enchantments_db or ENCHANTMENTS) == validated_item["enchantments"]


OPAQUE_ENCHANTMENT_TAG_ERROR = "Verzauberungen können nicht bearbeitet werden, weil vorhandene Enchantment-Tags einen unbekannten NBT-Typ verwenden."


def _default_enchantment_list_name(tag_comp, original_known_ids_by_list, list_is_editable) -> str | None:
    editable_existing_lists = [name for name in ("ench", "enchantments") if name in tag_comp and _is_list_tag(tag_comp[name])]
    for name in editable_existing_lists:
        if original_known_ids_by_list[name]:
            return name
    if editable_existing_lists:
        return editable_existing_lists[0]
    if list_is_editable["ench"]:
        return "ench"
    if list_is_editable["enchantments"]:
        return "enchantments"
    return None


def apply_editable_item_tags(item_compound, item_data, enchantments_db=None):
    enchantments_db = enchantments_db or ENCHANTMENTS
    display_name = item_data["display_name"]
    lore = item_data["lore"]
    enchantments = item_data["enchantments"]

    # An empty container that was already there is not something the user removed.
    # Cleaning it up during an unrelated edit would change an untouched structure.
    tag_started_empty = _is_compound_tag(item_compound.get("tag") if hasattr(item_compound, "get") else None) and len(item_compound["tag"]) == 0
    if (display_name or lore or enchantments) and "tag" not in item_compound:
        item_compound["tag"] = nbt.CompoundTag({})
    if "tag" not in item_compound:
        return

    tag_comp = item_compound["tag"]
    if not _is_compound_tag(tag_comp):
        # Future/add-on data may use a shape the editor does not understand.
        # A normal save with no visible tag edits preserves it verbatim. Visible
        # metadata cannot be merged into this shape safely, so reject instead of
        # replacing protected data.
        if not (display_name or lore or enchantments):
            return
        raise ValueError(t("Item-Metadaten können nicht bearbeitet werden, weil der vorhandene Item-tag einen unbekannten NBT-Typ verwendet."))

    display_tag = tag_comp.get("display") if hasattr(tag_comp, "get") else None
    if (display_name or lore) and display_tag is not None and not _is_compound_tag(display_tag):
        # Name/Lore can only be merged into a compound. Replacing an opaque
        # display child would discard data the editor cannot represent.
        raise ValueError(t("Item-Metadaten können nicht bearbeitet werden, weil der vorhandene Item-tag einen unbekannten NBT-Typ verwendet."))
    if display_name or lore or _is_compound_tag(display_tag):
        display_started_empty = _is_compound_tag(display_tag) and len(display_tag) == 0
        if display_tag is None:
            tag_comp["display"] = nbt.CompoundTag({})
        disp_comp = tag_comp["display"]

        # Only mutate the fields the editor owns.  Some Bedrock items can carry
        # additional display metadata or future tag types; deleting or normalizing
        # those fields during unrelated saves would be silent data loss.
        original_name_tag = disp_comp.get("Name") if hasattr(disp_comp, "get") else None
        original_name_value = str(get_tag_value(original_name_tag, ""))
        if display_name:
            if original_name_tag is not None and not isinstance(original_name_tag, nbt.StringTag) and original_name_value == display_name:
                pass
            else:
                disp_comp["Name"] = nbt.StringTag(display_name)
        elif original_name_value and "Name" in disp_comp and isinstance(disp_comp["Name"], nbt.StringTag):
            # Only a real removal cleans up. An already-empty Name stays as it was.
            del disp_comp["Name"]

        original_lore_tag = disp_comp.get("Lore") if hasattr(disp_comp, "get") else None
        original_lore_values = []
        original_lore_has_opaque_entries = False
        if _is_list_tag(original_lore_tag):
            original_lore_values = [str(get_tag_value(line, "")) for line in original_lore_tag]
            original_lore_has_opaque_entries = any(not isinstance(line, nbt.StringTag) for line in original_lore_tag)
        if lore:
            if original_lore_has_opaque_entries and original_lore_values == lore:
                pass
            else:
                disp_comp["Lore"] = nbt.ListTag([nbt.StringTag(x) for x in lore])
        # A non-empty original means the user really removed the lore. Opaque entries
        # stay: the editor cannot show them faithfully, so it must not delete them.
        elif original_lore_values and not original_lore_has_opaque_entries:
            del disp_comp["Lore"]

        if len(disp_comp) == 0 and not display_started_empty:
            del tag_comp["display"]

    original_enchantment_tags = {}
    original_enchantment_list_for_id = {}
    original_enchantment_levels = {}
    original_known_ids_by_list = {"ench": set(), "enchantments": set()}
    preserved_by_list = {"ench": [], "enchantments": []}
    # Position-by-position record of each original list, so a rebuild can put every
    # surviving entry back where it was instead of sorting edited entries to the front.
    original_layout_by_list = {"ench": [], "enchantments": []}
    seen_original_known_ids = set()
    for list_name in ("ench", "enchantments"):
        if list_name not in tag_comp or not _is_list_tag(tag_comp[list_name]):
            continue
        for original_ench in tag_comp[list_name]:
            editable_values = _editable_known_enchantment_values(original_ench, enchantments_db)
            if editable_values is None:
                preserved_entry = original_ench.copy()
                preserved_by_list[list_name].append(preserved_entry)
                original_layout_by_list[list_name].append(("preserved", preserved_entry))
                continue
            ench_id, ench_level = editable_values
            if ench_id in seen_original_known_ids:
                # Duplicate known IDs cannot be represented independently in the
                # editor. Preserve every additional original entry verbatim.
                preserved_entry = original_ench.copy()
                preserved_by_list[list_name].append(preserved_entry)
                original_layout_by_list[list_name].append(("preserved", preserved_entry))
                continue
            seen_original_known_ids.add(ench_id)
            original_known_ids_by_list[list_name].add(ench_id)
            original_enchantment_tags[ench_id] = original_ench
            original_enchantment_list_for_id[ench_id] = list_name
            original_enchantment_levels[ench_id] = ench_level
            original_layout_by_list[list_name].append(("known", ench_id))

    # Preserve unknown, malformed, and duplicate enchantment entries in the same
    # list tag family they came from. Preserve editable known enchantments in their
    # original family as well;
    # older versions of the editor could move a known entry from ``enchantments``
    # to ``ench`` merely because both lists existed. That is not direct data loss,
    # but it is an unnecessary NBT shape change for a UI that only edits id/lvl.
    list_is_editable = {list_name: (list_name not in tag_comp or _is_list_tag(tag_comp[list_name])) for list_name in ("ench", "enchantments")}

    default_list_name = _default_enchantment_list_name(tag_comp, original_known_ids_by_list, list_is_editable)
    edited_by_list = {"ench": [], "enchantments": []}
    edited_tag_for_id = {}
    added_by_list = {"ench": [], "enchantments": []}
    family_changed = {"ench": False, "enchantments": False}
    for ench in enchantments:
        list_name = original_enchantment_list_for_id.get(ench["id"], default_list_name)
        if list_name is None:
            raise ValueError(OPAQUE_ENCHANTMENT_TAG_ERROR)
        ench_tag = _copy_enchantment_tag_with_level(original_enchantment_tags.get(ench["id"]), ench["id"], ench["lvl"])
        edited_by_list[list_name].append(ench_tag)
        if ench["id"] in original_enchantment_list_for_id:
            edited_tag_for_id[ench["id"]] = ench_tag
            if original_enchantment_levels[ench["id"]] != ench["lvl"]:
                family_changed[list_name] = True
        else:
            added_by_list[list_name].append(ench_tag)
            family_changed[list_name] = True

    for list_name in ("ench", "enchantments"):
        original_list = tag_comp.get(list_name) if hasattr(tag_comp, "get") else None
        # Entries are collected from list-typed tags only, and the default list
        # name is always an editable family, so a non-editable one cannot receive
        # entries. This stays as a fail-closed net: an opaque tag must never be
        # replaced by a rebuilt standard list.
        if not list_is_editable[list_name] and (edited_by_list[list_name] or preserved_by_list[list_name]):
            raise ValueError(OPAQUE_ENCHANTMENT_TAG_ERROR)
        items_for_list = []
        for kind, value in original_layout_by_list[list_name]:
            if kind == "preserved":
                items_for_list.append(value)
            elif value in edited_tag_for_id:
                items_for_list.append(edited_tag_for_id[value])
            else:
                # A known entry the payload no longer lists: the user removed it.
                family_changed[list_name] = True
        items_for_list.extend(added_by_list[list_name])
        if not family_changed[list_name] and _is_list_tag(original_list):
            # No level changed and nothing was added or removed. Keeping the original
            # tag avoids rebuilding it, which resets the declared element type of an
            # empty list and fails outright for a list that mixes entry types.
            continue
        if items_for_list:
            try:
                tag_comp[list_name] = nbt.ListTag(items_for_list)
            except (TypeError, ValueError) as exc:
                # A list mixing compound and non-compound entries cannot be
                # rebuilt. Reject instead of letting it surface as an HTTP 500.
                raise ValueError(OPAQUE_ENCHANTMENT_TAG_ERROR) from exc
        elif list_name in tag_comp and _is_list_tag(tag_comp[list_name]):
            del tag_comp[list_name]

    if len(tag_comp) == 0 and not tag_started_empty:
        del item_compound["tag"]


def _set_numeric_tag_preserving_type(compound, key: str, value, default_factory):
    original_tag = compound.get(key) if hasattr(compound, "get") else None
    if isinstance(original_tag, NUMERIC_TAG_TYPES):
        tag = _numeric_tag_for_type(type(original_tag), value)
        if tag is not None:
            compound[key] = tag
            return
    tag = _numeric_tag_for_type(default_factory, value)
    if tag is None:
        raise ValueError(t("{key} außerhalb des gültigen NBT-Zahlenbereichs.", key=key))
    compound[key] = tag


def _entity_variant_primary_compound(item_compound):
    candidates = _entity_data_candidate_compounds(item_compound)
    identity_keys = {"ActorIdentifier", "identifier", "Identifier", "id"}
    state_keys = {
        "Variant",
        "MarkVariant",
        "Color",
        "Color2",
        "ColorID",
        "Color2ID",
        "BodyID",
        "IsBaby",
        "Baby",
        "Age",
    }
    for compound in reversed(candidates):
        if any(key in compound for key in identity_keys | state_keys):
            return compound
    return candidates[-1]


def _ensure_item_tag_compound(item_compound):
    tag_compound = _compound_child(item_compound, "tag")
    if tag_compound is not None:
        return tag_compound
    if "tag" in item_compound:
        raise ValueError(t("Item-Metadaten können nicht bearbeitet werden, weil der vorhandene Item-tag einen unbekannten NBT-Typ verwendet."))
    tag_compound = nbt.CompoundTag({})
    item_compound["tag"] = tag_compound
    return tag_compound


def _set_existing_numeric_variant_fields(compounds, values: dict[str, int]) -> bool:
    changed_any = False
    for compound in compounds:
        for key, value in values.items():
            original = compound.get(key) if hasattr(compound, "get") else None
            if not isinstance(original, INTEGER_TAG_TYPES):
                continue
            _set_numeric_tag_preserving_type(compound, key, value, type(original))
            changed_any = True
    return changed_any


def _entity_variant_unknown_tag_type_error():
    return ValueError(t("Item-Metadaten können nicht bearbeitet werden, weil der vorhandene Item-tag einen unbekannten NBT-Typ verwendet."))


def _set_entity_variant_display_string(compound, key: str, value: str, *, numeric_is_state: bool = False) -> None:
    original = compound.get(key) if hasattr(compound, "get") else None
    if original is None or isinstance(original, nbt.StringTag):
        compound[key] = nbt.StringTag(value)
        return
    if numeric_is_state and isinstance(original, INTEGER_TAG_TYPES):
        return
    raise _entity_variant_unknown_tag_type_error()


def _set_append_custom_name(compound) -> None:
    original = compound.get("AppendCustomName") if hasattr(compound, "get") else None
    if original is not None and not isinstance(original, INTEGER_TAG_TYPES):
        raise _entity_variant_unknown_tag_type_error()
    _set_numeric_tag_preserving_type(compound, "AppendCustomName", 1, nbt.ByteTag)


def _update_axolotl_definition_markers(compounds, variant_key: str, is_baby: bool) -> None:
    color_markers = {f"+axolotl_{key}" for key in ("lucy", "cyan", "gold", "wild", "blue")}
    age_markers = {"+axolotl_adult", "+axolotl_baby"}
    replacement_color = f"+axolotl_{variant_key}"
    replacement_age = f"+axolotl_{'baby' if is_baby else 'adult'}"

    for compound in compounds:
        if "definitions" not in compound:
            continue
        definitions = compound["definitions"]
        if not _is_list_tag(definitions) or any(not isinstance(entry, nbt.StringTag) for entry in definitions):
            raise _entity_variant_unknown_tag_type_error()
        for index, entry in enumerate(definitions):
            marker = str(get_tag_value(entry, "")).strip()
            if marker in color_markers:
                definitions[index] = nbt.StringTag(replacement_color)
            elif marker in age_markers:
                definitions[index] = nbt.StringTag(replacement_age)


def _apply_axolotl_variant_edit(item_compound, edit):
    tag_compound = _ensure_item_tag_compound(item_compound)
    compounds = _entity_data_candidate_compounds(item_compound)
    primary = _entity_variant_primary_compound(item_compound)
    variant = edit["variant"]
    is_baby = edit["is_baby"]

    # Preserve every known representation already present. Bedrock versions
    # have used both numeric entity state and language-key display fields.
    numeric_variant_seen = _set_existing_numeric_variant_fields(compounds, {"Variant": variant})
    for compound in compounds:
        for key in ("ColorID", "BodyID"):
            variant_tag = compound.get(key) if hasattr(compound, "get") else None
            if isinstance(variant_tag, INTEGER_TAG_TYPES):
                _set_numeric_tag_preserving_type(compound, key, variant, type(variant_tag))
                numeric_variant_seen = True
        color_tag = compound.get("ColorID") if hasattr(compound, "get") else None
        if isinstance(color_tag, nbt.StringTag):
            compound["ColorID"] = nbt.StringTag(AXOLOTL_COLOR_LANG_KEY_BY_VARIANT[variant])

    if numeric_variant_seen:
        # A numeric entity payload is authoritative; make it internally
        # complete without changing the surrounding entity compound.
        _set_numeric_tag_preserving_type(primary, "Variant", variant, nbt.IntTag)

    age_seen = False
    for compound in compounds:
        for key in ("IsBaby", "Baby"):
            original = compound.get(key) if hasattr(compound, "get") else None
            if isinstance(original, INTEGER_TAG_TYPES):
                _set_numeric_tag_preserving_type(compound, key, int(is_baby), type(original))
                age_seen = True
        original_age = compound.get("Age") if hasattr(compound, "get") else None
        if isinstance(original_age, INTEGER_TAG_TYPES):
            current_age = _integer_tag_value_from_compound(compound, "Age") or 0
            # Preserve a running baby timer. An adult Age=0 needs the full
            # Vanilla growth duration; -1 would mature on the next tick.
            next_age = _edited_axolotl_age(current_age, is_baby)
            _set_numeric_tag_preserving_type(compound, "Age", next_age, type(original_age))
            age_seen = True
        body_tag = compound.get("BodyID") if hasattr(compound, "get") else None
        if isinstance(body_tag, nbt.StringTag):
            compound["BodyID"] = nbt.StringTag(f"item.axolotl{'Baby' if is_baby else 'Adult'}BodySingle.name")

    if not age_seen:
        _set_numeric_tag_preserving_type(primary, "IsBaby", int(is_baby), nbt.ByteTag)

    # These fields drive the bucket's localized name. They do not replace or
    # discard the complete saved entity payload.
    _set_entity_variant_display_string(
        tag_compound,
        "ColorID",
        AXOLOTL_COLOR_LANG_KEY_BY_VARIANT[variant],
        numeric_is_state=True,
    )
    _set_entity_variant_display_string(
        tag_compound,
        "BodyID",
        f"item.axolotl{'Baby' if is_baby else 'Adult'}BodySingle.name",
        numeric_is_state=True,
    )
    _update_axolotl_definition_markers(compounds, AXOLOTL_VARIANTS[variant]["key"], is_baby)
    _set_append_custom_name(tag_compound)


def _apply_tropical_fish_variant_edit(item_compound, edit):
    tag_compound = _ensure_item_tag_compound(item_compound)
    compounds = _entity_data_candidate_compounds(item_compound)
    primary = _entity_variant_primary_compound(item_compound)
    numeric_values = {
        "Variant": edit["variant"],
        "MarkVariant": edit["mark_variant"],
        "Color": edit["color"],
        "Color2": edit["color2"],
    }
    if _set_existing_numeric_variant_fields(compounds, numeric_values):
        # If this bucket contains a numeric saved-entity representation, keep
        # the four correlated fields together in that same compound.
        for key, value in numeric_values.items():
            _set_numeric_tag_preserving_type(primary, key, value, nbt.IntTag)

    pattern_token, _label_de, _label_en = TROPICAL_FISH_PATTERN_BY_VALUES[(edit["variant"], edit["mark_variant"])]
    name_shape = "Single" if edit["color"] == edit["color2"] else "Multi"
    display_values = {
        "BodyID": f"item.tropicalBody{pattern_token}{name_shape}.name",
        "ColorID": f"item.tropicalColor{TROPICAL_FISH_COLOR_TOKEN_BY_VALUE[edit['color']]}.name",
        "Color2ID": f"item.tropicalColor{TROPICAL_FISH_COLOR_TOKEN_BY_VALUE[edit['color2']]}.name",
    }
    preset_key = TROPICAL_FISH_PRESET_KEY_BY_VALUES.get((edit["variant"], edit["mark_variant"], edit["color"], edit["color2"]))
    preset_group_name = f"item.tropicalSchool{TROPICAL_FISH_GROUP_LANG_TOKEN_BY_KEY[preset_key]}.name" if preset_key is not None else ""
    for compound in compounds:
        for key, value in display_values.items():
            if isinstance(compound.get(key), nbt.StringTag):
                compound[key] = nbt.StringTag(value)
        group_tag = compound.get("GroupName")
        if isinstance(group_tag, nbt.StringTag) and _tropical_group_token(str(get_tag_value(group_tag, ""))):
            if preset_group_name:
                compound["GroupName"] = nbt.StringTag(preset_group_name)
            else:
                del compound["GroupName"]
    tag_group = tag_compound.get("GroupName")
    if preset_group_name and (tag_group is None or isinstance(tag_group, nbt.StringTag) and _tropical_group_token(str(get_tag_value(tag_group, "")))):
        tag_compound["GroupName"] = nbt.StringTag(preset_group_name)
    for key, value in display_values.items():
        _set_entity_variant_display_string(tag_compound, key, value, numeric_is_state=True)
    _set_append_custom_name(tag_compound)


def _apply_entity_variant_edit(item_compound, validated_item, base_item_tag, duplicate_label: str):
    edit = validated_item.get("entity_variant_edit")
    if edit is None:
        return
    slot = validated_item["slot"]
    existing_variant = _item_entity_variant(base_item_tag) if base_item_tag is not None else None
    if not existing_variant or not existing_variant.get("can_edit"):
        raise ValueError(
            t(
                "{label}-Slot {slot}: Die Tier-Variante kann nur an einem auflösbaren Originalitem mit vorhandenen Entity-Daten geändert werden.",
                label=duplicate_label,
                slot=slot,
            )
        )
    expected_entity = AXOLOTL_ENTITY_ID if edit["kind"] == "axolotl" else "minecraft:tropical_fish"
    if _normalize_entity_identifier(existing_variant.get("entity_id", "")) != expected_entity:
        raise ValueError(
            t(
                "{label}-Slot {slot}: Die vorhandenen Entity-Daten passen nicht zur angeforderten Variante.",
                label=duplicate_label,
                slot=slot,
            )
        )
    if edit["kind"] == "axolotl":
        _apply_axolotl_variant_edit(item_compound, edit)
    else:
        _apply_tropical_fish_variant_edit(item_compound, edit)


def _protected_only_item_slots(original_sequence, valid_slots) -> set[int]:
    original_editable_slots = set()
    original_protected_slots = set()
    for original_item in original_sequence:
        original_slot = _read_item_slot(original_item)
        if original_slot in valid_slots:
            if _item_entry_has_editable_shape(original_item):
                original_editable_slots.add(original_slot)
            elif _item_entry_is_empty_placeholder(original_item):
                # Safe empty placeholder; it may be preserved or replaced by a real item.
                continue
            else:
                original_protected_slots.add(original_slot)
    return original_protected_slots - original_editable_slots


def _check_item_enchantment_compatibility(name, validated_item, base_item_tag, enchantments_db, duplicate_label, slot):
    incompatible_enchantments = [ench for ench in validated_item["enchantments"] if not is_enchantment_compatible_with_item(ench["id"], name)]
    if validated_item["enchantments"] and not is_enchantable_item_id(name):
        if base_item_tag is None or not _enchantments_match_original(base_item_tag, validated_item["enchantments"], enchantments_db):
            raise ValueError(
                f"{duplicate_label}-Slot {slot}: {name} ist nach den Editor-Regeln nicht verzauberbar. "
                "Vorhandene ungewöhnliche Enchantment-NBT wird nur unverändert erhalten."
            )
    elif incompatible_enchantments and (
        base_item_tag is None or not _enchantments_match_original(base_item_tag, validated_item["enchantments"], enchantments_db)
    ):
        incompatible_ids = ", ".join(str(ench["id"]) for ench in incompatible_enchantments)
        raise ValueError(
            f"{duplicate_label}-Slot {slot}: Verzauberung(en) {incompatible_ids} passen nicht zu {name}. "
            "Vorhandene ungewöhnliche Enchantment-NBT wird nur unverändert erhalten."
        )


def reject_non_addable_new_item(name: str, base_item_tag, duplicate_label: str, slot: int) -> None:
    """Block new synthetic items outside Mojang's positive item registry.

    A resolvable original remains editable/movable even when it is a legacy,
    future, or add-on item. This keeps round-trip preservation independent from
    the much narrower catalog used for creating new Vanilla items.
    """
    if base_item_tag is None and not is_addable_item_id(name):
        raise ValueError(
            f"{duplicate_label}-Slot {slot}: '{name}' ist kein von Mojang registriertes Inventaritem "
            "und kann nicht neu erzeugt werden. Vorhandene Sonder- oder Add-on-Items werden weiterhin erhalten."
        )


def validate_item_stack_count(name: str, count: int, base_item_tag, duplicate_label: str, slot: int) -> None:
    """Enforce Vanilla stack limits without making existing worlds unsavable."""
    max_stack = get_max_stack(name) if is_known_item_id(name) else MAX_BEDROCK_STACK_COUNT
    if count <= max_stack:
        return
    original_count = None
    if base_item_tag is not None:
        count_tag = base_item_tag.get("Count") if hasattr(base_item_tag, "get") else None
        if isinstance(count_tag, INTEGER_TAG_TYPES):
            original_count = _integer_tag_value_from_compound(base_item_tag, "Count")
    if original_count == count:
        return
    raise ValueError(
        t(
            "{label}-Slot {slot}: Menge {count} überschreitet das Vanilla-Stacklimit {max} für {name}. "
            "Ein vorhandener übergroßer Stack wird nur unverändert erhalten.",
            label=duplicate_label,
            slot=slot,
            count=count,
            max=max_stack,
            name=name,
        )
    )


def validate_item_original_bounds(validated_item, base_item_tag, duplicate_label: str, slot: int) -> None:
    """Allow an existing out-of-limit value, reject a new or changed one.

    The counterpart to :func:`validate_item_stack_count` for damage, display name
    and lore. Each bound is checked on its own: an untouched oversized lore must
    not also let a newly overlong display name through on the same item.

    Without a resolvable original every comparison fails, so the strict limit
    applies -- a new item can never be created outside the editor's bounds.
    """

    name = validated_item["name"]
    has_original = base_item_tag is not None and _is_compound_tag(base_item_tag)

    damage = validated_item["damage"]
    item_max_damage = get_max_damage(name)
    damage_out_of_bounds = not (0 <= damage <= item_max_damage)
    if damage_out_of_bounds and (not has_original or _read_editable_item_damage(base_item_tag, name) != damage):
        raise ValueError(
            t(
                "{label}-Slot {slot}: Damage-Wert {damage} liegt außerhalb von 0 bis {max} für {name}. "
                "Ein vorhandener abweichender Wert wird nur unverändert erhalten.",
                label=duplicate_label,
                slot=slot,
                damage=damage,
                max=item_max_damage,
                name=name,
            )
        )

    original_name, original_lore = _original_display_fields(base_item_tag) if has_original else ("", [])

    display_name = validated_item["display_name"]
    if len(display_name) > MAX_TEXT_LENGTH and (not has_original or original_name != display_name):
        raise ValueError(
            t(
                "{label}-Slot {slot}: Anzeigename ist zu lang. Ein vorhandener zu langer Name wird nur unverändert erhalten.",
                label=duplicate_label,
                slot=slot,
            )
        )

    lore = validated_item["lore"]
    lore_too_long = len(lore) > MAX_LORE_LINES or any(len(line) > MAX_TEXT_LENGTH for line in lore)
    if lore_too_long and (not has_original or original_lore != lore):
        raise ValueError(
            t(
                "{label}-Slot {slot}: Lore ist zu lang. Eine vorhandene zu lange Lore wird nur unverändert erhalten.",
                label=duplicate_label,
                slot=slot,
            )
        )


def validate_item_data_value_variant(name: str, damage: int, base_item_tag, duplicate_label: str, slot: int) -> None:
    allowed_values = DATA_VALUE_VARIANT_DAMAGE_VALUES.get(name)
    if not allowed_values or damage in allowed_values:
        return
    # Unknown/future values already present in a world remain round-trip safe.
    # They may not be synthesized or changed into another unsupported value.
    if base_item_tag is not None and _read_editable_item_damage(base_item_tag, name) == damage:
        return
    allowed_label = ", ".join(str(value) for value in sorted(allowed_values))
    raise ValueError(
        t(
            "{label}-Slot {slot}: Datenwert {damage} ist für {name} keine unterstützte Variante. "
            "Erlaubt: {allowed}. Ein vorhandener unbekannter Wert wird nur unverändert erhalten.",
            label=duplicate_label,
            slot=slot,
            damage=damage,
            name=name,
            allowed=allowed_label,
        )
    )


def _build_item_compound(base_item_tag, validated_item, duplicate_label, is_ender_chest, *, unchanged=False):
    slot = validated_item["slot"]
    name = validated_item["name"]
    count = validated_item["count"]
    damage = validated_item["damage"]
    if base_item_tag is not None:
        # amulet_nbt's CompoundTag.copy() is shallow. Editable nested tags must
        # be detached from the loaded player snapshot before they are mutated,
        # otherwise validation/rollback code can observe an already-modified
        # "original" in memory.
        item_compound = _deep_clone_tag(base_item_tag)
        if unchanged:
            # Nothing the visible form owns has changed. Only a real slot move
            # may touch this compound; rewriting Count/Damage here would add a
            # root Damage tag that a damageable original never carried.
            if _read_item_slot(base_item_tag) != slot:
                _set_numeric_tag_preserving_type(item_compound, "Slot", slot, nbt.ByteTag)
            return item_compound
        # Some other visible field changed, but that is no reason to rewrite these.
        # _set_editable_item_damage would add a root Damage tag to an item that never
        # carried one, because a missing Damage reads back as the same value 0.
        if _read_item_slot(base_item_tag) != slot:
            _set_numeric_tag_preserving_type(item_compound, "Slot", slot, nbt.ByteTag)
        if _integer_tag_value_from_compound(base_item_tag, "Count") != count:
            _set_numeric_tag_preserving_type(item_compound, "Count", count, nbt.ByteTag)
        if _read_editable_item_damage(base_item_tag, name) != damage:
            _set_editable_item_damage(item_compound, name, damage)
        return item_compound

    if validated_item.get("claims_protected_nbt") or validated_item.get("claims_preserved_nbt") or validated_item.get("claims_unknown_enchantments"):
        raise ValueError(
            t(
                "{label}-Slot {slot} enthält laut Browser erhaltene Item-NBT-Daten, "
                "aber die sichere Originalquelle konnte nicht aufgelöst werden. "
                "Bitte Spieler neu laden und die Änderung erneut vornehmen.",
                label=duplicate_label,
                slot=slot,
            )
        )
    fields = {
        "Slot": nbt.ByteTag(slot),
        "Name": nbt.StringTag(name),
        "Count": nbt.ByteTag(count),
        "Damage": nbt.ShortTag(0 if _item_is_damageable(name) else damage),
    }
    if not is_ender_chest:
        fields["WasPickedUp"] = nbt.ByteTag(0)
    item_compound = nbt.CompoundTag(fields)
    _set_editable_item_damage(item_compound, name, damage)
    return item_compound


def _merge_items_into_original_sequence(original_sequence, valid_slots, new_items_by_slot):
    result_items = []
    emitted_slots = set()
    for original_item in original_sequence:
        slot = _read_item_slot(original_item)
        if slot in valid_slots:
            if _item_entry_is_empty_placeholder(original_item):
                if slot in new_items_by_slot and slot not in emitted_slots:
                    result_items.append(new_items_by_slot[slot])
                    emitted_slots.add(slot)
                elif slot not in new_items_by_slot:
                    # Preserve empty fixed-list placeholders to avoid normalizing
                    # Bedrock's inventory shape when the user did not touch them.
                    result_items.append(original_item.copy())
                continue
            if not _item_entry_has_editable_shape(original_item):
                # The UI cannot show this valid-slot entry safely. Preserve it
                # like an unknown/future slot instead of interpreting omission
                # from the JSON payload as an intentional clear operation. Do
                # this even when a normal editable item with the same duplicate
                # slot is also present; otherwise the protected duplicate would
                # be silently lost.
                result_items.append(original_item.copy())
                continue
            if slot in emitted_slots:
                # Duplicate editable slots cannot be represented safely in the UI.
                # Emit at most one item for each editable slot instead of cloning
                # the replacement into every duplicate occurrence.
                continue
            if slot in new_items_by_slot:
                result_items.append(new_items_by_slot[slot])
                emitted_slots.add(slot)
            # Editable valid slots omitted by the UI are intentionally cleared.
            continue
        # Unknown/non-editable slots are kept verbatim to avoid silent data loss
        # and to let users save normal UI edits even if newer Bedrock versions add
        # inventory slots this editor does not know yet.
        result_items.append(original_item.copy())

    for slot in sorted(new_items_by_slot):
        if slot not in emitted_slots:
            result_items.append(new_items_by_slot[slot])
    return result_items


def _effect_id_from_tag(effect_tag):
    if not hasattr(effect_tag, "get"):
        return -1
    raw_id = _finite_int(get_tag_value(effect_tag.get("Id"), 0), 0)
    return _signed_byte_to_unsigned(raw_id)


def _set_effect_control_tag_if_changed(effect_compound, key: str, candidate) -> None:
    existing = effect_compound.get(key)
    if existing is None:
        default_tag = _numeric_tag_for_type(type(candidate), EFFECT_CONTROL_DEFAULTS[key])
        if default_tag is not None and get_tag_value(default_tag) == get_tag_value(candidate):
            # Absent and still at the displayed default: writing it would only
            # add a control tag this effect entry never carried.
            return
    elif type(existing) is type(candidate) and get_tag_value(existing) == get_tag_value(candidate):
        return
    effect_compound[key] = candidate


def _build_effect_compound(eff, original_effect):
    control_tags = (
        ("Id", nbt.ByteTag(_unsigned_to_signed_byte(eff["id"]))),
        ("Amplifier", nbt.ByteTag(_unsigned_to_signed_byte(eff["amplifier"]))),
        ("Duration", nbt.IntTag(eff["duration"])),
        ("Ambient", nbt.ByteTag(eff["ambient"])),
        ("ShowParticles", nbt.ByteTag(eff["show_particles"])),
        ("ShowIcon", nbt.ByteTag(eff["show_icon"])),
    )
    if original_effect is None:
        # A newly added effect gets Bedrock's complete canonical control shape.
        return nbt.CompoundTag(dict(control_tags))
    effect_compound = original_effect.copy()
    for key, candidate in control_tags:
        _set_effect_control_tag_if_changed(effect_compound, key, candidate)
    return effect_compound


def apply_effects(player_tag, effects_list):
    if effects_list is None:
        return
    if not isinstance(effects_list, list):
        raise ValueError("Effekt-Daten müssen eine Liste sein.")

    original_known_effects = {}
    original_protected_known_effects = []
    original_protected_known_effect_ids = set()
    original_unknown_effects = []
    original_unknown_effect_ids = set()
    seen_original_editable_effect_ids = set()
    active_effects_tag = player_tag.get("ActiveEffects")
    if active_effects_tag is not None and not _is_list_tag(active_effects_tag):
        # Opaque/future shape: a normal save should not replace it with an empty
        # standard list just because the browser could not render it.
        if effects_list:
            raise ValueError("ActiveEffects hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren.")
        return
    if _is_list_tag(active_effects_tag):
        for original_effect in active_effects_tag:
            effect_id = _effect_id_from_tag(original_effect)
            if effect_id in EFFECTS and hasattr(original_effect, "get"):
                if _effect_control_fields_opaque(original_effect) or effect_id in seen_original_editable_effect_ids:
                    original_protected_known_effects.append(original_effect)
                    original_protected_known_effect_ids.add(effect_id)
                else:
                    original_known_effects[effect_id] = original_effect
                    seen_original_editable_effect_ids.add(effect_id)
            else:
                original_unknown_effects.append(original_effect)
                original_unknown_effect_ids.add(effect_id)

    validated = []
    seen_effect_ids = set()
    for eff in effects_list:
        # Same reason as in validate_inventory_item: a non-object list entry must
        # fail as a clean client error, not as an unhandled TypeError.
        if not isinstance(eff, Mapping):
            raise ValueError("Ungültige Effekt-Daten empfangen.")
        try:
            effect_id = _strict_int(eff["id"], "Effekt-ID")
        except (KeyError, TypeError, ValueError):
            raise ValueError("Ungültige Effekt-Daten empfangen.") from None
        if eff.get("opaque") is True and effect_id in original_protected_known_effect_ids:
            # This known effect exists in the original data, but at least one of
            # its entries is ambiguous or uses a non-standard/future NBT type.
            # Only payload rows explicitly marked opaque represent those protected
            # originals; a normal row with the same ID remains independently
            # editable.
            continue
        if effect_id not in EFFECTS:
            if effect_id in original_unknown_effect_ids:
                # The server always preserves original unknown effects below.
                # Do not rewrite them from lossy JSON/UI data. Multiple opaque
                # entries can collapse to the same placeholder ID (for example -1),
                # so they must not trip duplicate checks for editable effects.
                continue
            raise ValueError(f"Unbekannter Effekt-ID: {effect_id}")
        if effect_id in seen_effect_ids:
            raise ValueError(f"Doppelter Effekt empfangen: {effect_id}")
        seen_effect_ids.add(effect_id)
        validated.append(validate_effect(eff))

    edited_by_id = {eff["id"]: _build_effect_compound(eff, original_known_effects.get(eff["id"])) for eff in validated}

    # Emit in the original NBT order. The browser echoes the complete effect list
    # whenever any effect changes, so rebuilding edited entries first would move
    # untouched protected and future entries on an unrelated edit.
    #
    # Future/add-on effects are not understood by this editor. Preserve every
    # original unknown effect verbatim, even when the browser payload omits it or
    # sends an empty list. This keeps normal saves and "clear known effects" from
    # silently deleting data the UI cannot safely explain.
    nbt_list = []
    emitted_effect_ids = set()
    if _is_list_tag(active_effects_tag):
        for original_effect in active_effects_tag:
            effect_id = _effect_id_from_tag(original_effect)
            if original_known_effects.get(effect_id) is not original_effect:
                # Protected duplicate or unknown/future entry: keep it verbatim.
                nbt_list.append(original_effect.copy())
                continue
            if effect_id in edited_by_id:
                nbt_list.append(edited_by_id[effect_id])
                emitted_effect_ids.add(effect_id)
            # else: the user removed this editable effect.
    nbt_list.extend(compound for effect_id, compound in edited_by_id.items() if effect_id not in emitted_effect_ids)

    if nbt_list:
        player_tag["ActiveEffects"] = nbt.ListTag(nbt_list)
    elif _is_list_tag(active_effects_tag) and len(active_effects_tag) == 0:
        # Already empty before the save: an identical round trip must not drop
        # the tag. Only removing the last real effect may clean up the shape.
        pass
    elif "ActiveEffects" in player_tag:
        del player_tag["ActiveEffects"]


def _reject_if_ability_field_opaque(player_tag, field_name: str):
    if _is_ability_field_opaque(player_tag, field_name):
        spec = _ability_tag_spec(field_name)
        tag_name = spec[0] if spec else field_name
        raise ValueError(t("Fähigkeit '{name}' hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren.", name=tag_name))


def _position_tag_opaque(player_tag) -> bool:
    try:
        pos_tag = player_tag.get("Pos")
    except AttributeError:
        return False
    if pos_tag is None:
        return False
    if not _is_list_tag(pos_tag):
        return True
    try:
        entries = list(pos_tag)
    except (AttributeError, TypeError):
        return True
    if len(entries) < 3:
        return True
    position_tag_type = type(entries[0])
    if position_tag_type not in (nbt.FloatTag, nbt.DoubleTag):
        return True
    for entry in entries:
        # Player records normally use DoubleTags, while Bedrock entity-shaped
        # records and some compatible player data use FloatTags. Both are safe
        # when the homogeneous source type is kept. Integer/future shapes remain
        # protected because normalizing them could lose precision.
        if type(entry) is not position_tag_type:
            return True
        value = get_tag_value(entry, None)
        try:
            if not math.isfinite(float(value)):
                return True
        except (OverflowError, TypeError, ValueError):
            return True
    return False


def _dimension_id_tag_opaque(player_tag) -> bool:
    try:
        dimension_tag = player_tag.get("DimensionId")
    except AttributeError:
        return False
    if dimension_tag is None:
        return False
    if not isinstance(dimension_tag, nbt.IntTag):
        return True
    value = get_tag_value(dimension_tag, None)
    return isinstance(value, bool) or not isinstance(value, int) or value not in VANILLA_PLAYER_DIMENSION_IDS


def _reject_if_stat_field_opaque(player_tag, field_name: str):
    if field_name == "pos":
        if "Pos" not in player_tag:
            raise ValueError(t("Pos-Tag fehlt; die Spielerposition wird sicherheitshalber nicht neu erzeugt."))
        if _position_tag_opaque(player_tag):
            raise ValueError("Position hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren.")
        return
    spec = SCALAR_STAT_TAGS.get(field_name)
    if not spec:
        return
    tag_name = field_name
    for candidate_name, _expected_types in _iter_scalar_stat_specs(field_name) or ():
        try:
            if candidate_name in player_tag:
                tag_name = candidate_name
                break
        except (AttributeError, TypeError):
            continue
    if _is_scalar_stat_field_opaque(player_tag, field_name):
        raise ValueError(f"Statistik '{tag_name}' hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren.")
    opaque_attribute = _attribute_stat_field_opaque(player_tag, field_name)
    if opaque_attribute:
        raise ValueError(
            f"Statistik-Attribut '{opaque_attribute}' hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren."
        )


def apply_abilities(player_tag, abilities_dict):
    if abilities_dict is None:
        return
    if not isinstance(abilities_dict, dict):
        raise ValueError("Fähigkeiten-Daten müssen ein Objekt sein.")
    if not abilities_dict:
        return
    ab_tag = player_tag.get("abilities")
    if ab_tag is not None and not _is_compound_tag(ab_tag):
        # Preserve opaque/future ability data on normal saves.  Replacing it with
        # the standard compound from default checkboxes would be silent data loss.
        if abilities_dict:
            raise ValueError("abilities hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren.")
        return
    compound_is_new = ab_tag is None
    if compound_is_new:
        ab_tag = nbt.CompoundTag()
        player_tag["abilities"] = ab_tag
    # Ability fields are read type-tolerantly, but explicit edits normalize the
    # editor-owned values to the vanilla tag classes used by Bedrock.
    if "fly_speed" in abilities_dict:
        _reject_if_ability_field_opaque(player_tag, "fly_speed")
        val = _finite_float(abilities_dict["fly_speed"], -1.0)
        if not (0.0 <= val <= 1.0):
            raise ValueError(t("Fluggeschwindigkeit außerhalb des Bereichs (0.0-1.0): {value}", value=val))
        _set_ability_tag_if_changed(ab_tag, "fly_speed", nbt.FloatTag(val), compound_is_new=compound_is_new)
    if "walk_speed" in abilities_dict:
        _reject_if_ability_field_opaque(player_tag, "walk_speed")
        val = _finite_float(abilities_dict["walk_speed"], -1.0)
        if not (0.0 <= val <= 1.0):
            raise ValueError(t("Laufgeschwindigkeit außerhalb des Bereichs (0.0-1.0): {value}", value=val))
        _set_ability_tag_if_changed(ab_tag, "walk_speed", nbt.FloatTag(val), compound_is_new=compound_is_new)
    for field_name, default in (("mayfly", False), ("flying", False), ("invulnerable", False), ("maybuild", True), ("instabuild", False)):
        if field_name not in abilities_dict:
            continue
        _reject_if_ability_field_opaque(player_tag, field_name)
        _set_ability_tag_if_changed(ab_tag, field_name, nbt.ByteTag(_parse_bool_input(abilities_dict[field_name], default)), compound_is_new=compound_is_new)


def _set_ability_tag_if_changed(ab_tag, field_name: str, candidate, *, compound_is_new: bool = False) -> None:
    """Write one ability tag only when it really differs from the stored state.

    ``parse_abilities`` reports a full ability set even for a compound that only
    carries some of the fields, and the browser echoes that set back whenever any
    single ability is touched. Writing every echoed key would synthesize fields
    the player never had -- the same NBT shape change that creating the whole
    ``abilities`` compound requires an explicit confirmation for.

    A compound this save just created is the exception: it gets the complete
    requested shape, exactly like a newly added effect entry.
    """

    spec = _ability_tag_spec(field_name)
    if not spec:
        return
    tag_name, _expected_types, aliases = spec
    for existing_name in (tag_name, *aliases):
        try:
            existing = ab_tag.get(existing_name)
        except AttributeError:
            existing = None
        if existing is None:
            continue
        if type(existing) is type(candidate) and get_tag_value(existing) == get_tag_value(candidate):
            # Unchanged: keep the original tag, including a legacy alias name.
            return
        break
    else:
        default_tag = _numeric_tag_for_type(type(candidate), ABILITY_DEFAULTS[field_name])
        if not compound_is_new and default_tag is not None and get_tag_value(default_tag) == get_tag_value(candidate):
            # Absent in an existing compound and still at the value the editor
            # displays for a missing tag: writing it would only grow the shape.
            return
    ab_tag[tag_name] = candidate
    for alias in aliases:
        if alias != tag_name and alias in ab_tag and isinstance(ab_tag[alias], type(candidate)):
            del ab_tag[alias]


def _build_player_position_update(player_tag, new_position):
    _reject_if_stat_field_opaque(player_tag, "pos")
    if not isinstance(new_position, list | tuple) or len(new_position) != 3:
        raise ValueError("Position muss aus exakt drei Werten bestehen.")
    position_values = []
    for index, value in enumerate(new_position):
        try:
            position_values.append(_strict_float(value, f"Positionswert bei Index {index}"))
        except ValueError:
            raise ValueError(t("Ungültiger Positionswert bei Index {index}: {value}", index=index, value=value)) from None

    try:
        original_position = list(player_tag["Pos"])
        position_tag_type = type(original_position[0])
        original_position_tail = [tag.copy() for tag in original_position[3:]]
        rewritten_head = [position_tag_type(value) for value in position_values]
    except (OverflowError, TypeError, AttributeError, ValueError):
        raise ValueError("Position hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren.") from None
    if any(not math.isfinite(float(get_tag_value(tag, math.nan))) for tag in rewritten_head):
        raise ValueError(t("Position liegt außerhalb des Zahlenbereichs des vorhandenen Pos-NBT-Typs."))
    return nbt.ListTag([*rewritten_head, *original_position_tail])


def _build_player_dimension_update(player_tag, new_dimension_id):
    if "DimensionId" not in player_tag:
        raise ValueError(t("DimensionId fehlt; die Spielerdimension wird sicherheitshalber nicht neu erzeugt."))
    if _dimension_id_tag_opaque(player_tag):
        raise ValueError(t("DimensionId hat einen unbekannten Wert oder NBT-Typ und wird geschützt erhalten."))
    dimension_id = _strict_int(new_dimension_id, "DimensionId")
    if dimension_id not in VANILLA_PLAYER_DIMENSION_IDS:
        raise ValueError(t("Unbekannte Spielerdimension: {value}", value=dimension_id))
    return nbt.IntTag(dimension_id)


def apply_player_stats(player_tag, new_stats):
    if new_stats is None:
        return
    if not isinstance(new_stats, dict):
        raise ValueError("Spieler-Statistiken müssen ein Objekt sein.")
    if not new_stats:
        return

    # Position and dimension form one location. A dimension switch must always
    # carry an explicitly validated position so both fields are committed by the
    # same player-record write. Build both tags before mutating the NBT tree.
    if "dimension_id" in new_stats and "pos" not in new_stats:
        raise ValueError(t("Ein Dimensionswechsel muss zusammen mit einer vollständigen Spielerposition gespeichert werden."))
    pending_position = _build_player_position_update(player_tag, new_stats["pos"]) if "pos" in new_stats else None
    pending_dimension = _build_player_dimension_update(player_tag, new_stats["dimension_id"]) if "dimension_id" in new_stats else None
    if pending_position is not None:
        player_tag["Pos"] = pending_position
    if pending_dimension is not None:
        player_tag["DimensionId"] = pending_dimension

    # Other player stats are read type-tolerantly. When the user edits a field,
    # the editor-owned value is normalized to Bedrock's canonical tag class;
    # known legacy field names are preserved where Bedrock has aliases.
    if "health" in new_stats:
        _reject_if_stat_field_opaque(player_tag, "health")
        h_val = _strict_float(new_stats["health"], "Health-Wert")
        if not (0 <= h_val <= 1024):
            raise ValueError(t("Health außerhalb des gültigen Bereichs (0-1024): {value}", value=h_val))
        player_tag["Health"] = nbt.FloatTag(h_val)
        _sync_attribute_stat(player_tag, "health", h_val)
    if "gamemode" in new_stats:
        raise ValueError("Spielmodus wird vom Editor nur angezeigt und nicht verändert. Welt-/Servermodus kann abweichen.")
    if "xp_level" in new_stats:
        _reject_if_stat_field_opaque(player_tag, "xp_level")
        xl = _strict_int(new_stats["xp_level"], "XP-Level")
        if not (0 <= xl <= 24791):
            raise ValueError(t("XP-Level außerhalb des gültigen Bereichs (0-24791): {value}", value=xl))
        _set_scalar_stat_value(player_tag, "xp_level", nbt.IntTag, xl)
        _sync_attribute_stat(player_tag, "xp_level", xl)
    if "xp_progress" in new_stats:
        _reject_if_stat_field_opaque(player_tag, "xp_progress")
        xp = _strict_float(new_stats["xp_progress"], "XP-Fortschritt")
        if not (0.0 <= xp < 1.0):
            raise ValueError(t("XP-Fortschritt ungültig (muss mindestens 0.0 und kleiner als 1.0 sein): {value}", value=xp))
        _set_scalar_stat_value(player_tag, "xp_progress", nbt.FloatTag, xp)
        _sync_attribute_stat(player_tag, "xp_progress", xp)
    if "food_level" in new_stats:
        _reject_if_stat_field_opaque(player_tag, "food_level")
        fl = _strict_int(new_stats["food_level"], "Food-Level")
        if not (0 <= fl <= 20):
            raise ValueError(t("Food-Level außerhalb des gültigen Bereichs (0-20): {value}", value=fl))
        player_tag["foodLevel"] = nbt.IntTag(fl)
        _sync_attribute_stat(player_tag, "food_level", fl)
    if "food_saturation" in new_stats:
        _reject_if_stat_field_opaque(player_tag, "food_saturation")
        fs = _strict_float(new_stats["food_saturation"], "Food-Sättigung")
        if not (0.0 <= fs <= 20.0):
            raise ValueError(t("Food-Sättigung ungültig (muss 0.0-20.0 sein): {value}", value=fs))
        player_tag["foodSaturationLevel"] = nbt.FloatTag(fs)
        _sync_attribute_stat(player_tag, "food_saturation", fs)
