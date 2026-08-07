"""Public inventory API and write orchestration.

The implementation helpers live in :mod:`._inventory_core`. This module keeps
one stable import surface for the application while defining the NBT source
selection policy directly, without runtime monkey-patching or dynamic
``globals()`` mutation.
"""

from __future__ import annotations

import hashlib as _hashlib
import hmac as _hmac
import importlib as _importlib
import json as _json
import math as _math

from . import _inventory_core as _core
from ._inventory_core import (
    ABILITY_TAG_FIELDS,
    ATTRIBUTE_STAT_TAGS,
    AXOLOTL_ENTITY_ID,
    AXOLOTL_ITEM_IDS,
    AXOLOTL_VARIANTS,
    DYE_COLOR_LABELS,
    EFFECT_CONTROL_TAGS,
    EFFECTS,
    ENCHANTMENTS,
    ENDER_CHEST_SLOTS,
    INTEGER_TAG_RANGES,
    INTEGER_TAG_TYPES,
    ITEM_ID_RE,
    KNOWN_PRESERVED_ITEM_TAG_KEYS,
    MAX_BEDROCK_STACK_COUNT,
    MAX_DAMAGE,
    MAX_LORE_LINES,
    MAX_NBT_VIEW_DEPTH,
    MAX_NBT_VIEW_ITEMS,
    MAX_NBT_VIEW_STRING,
    MAX_TEXT_LENGTH,
    NUMERIC_TAG_TYPES,
    ROOT_ITEM_LIST_TAGS,
    SCALAR_STAT_TAGS,
    TROPICAL_FISH_BUCKET_ITEM_IDS,
    TROPICAL_FISH_COLOR_LABELS,
    TROPICAL_FISH_ENTITY_IDS,
    TROPICAL_FISH_GROUP_LABELS,
    VALID_INVENTORY_SLOTS,
    EnchantmentEntry,
    EntityVariantField,
    EntityVariantInfo,
    ParsedItemSlot,
    PlayerStats,
    apply_abilities,
    apply_editable_item_tags,
    apply_effects,
    apply_player_stats,
    count_hidden_unknown_slots,
    extract_player_stats,
    get_max_damage,
    get_max_stack,
    get_tag_value,
    is_addable_item_id,
    is_enchantable_item_id,
    is_enchantment_compatible_with_item,
    is_known_item_id,
    item_payload_matches_original,
    items_by_slot_for_origin,
    parse_abilities,
    parse_effects,
    protected_player_nbt_flags,
    reject_non_addable_new_item,
    validate_effect,
    validate_inventory_item,
    validate_item_original_bounds,
    validate_item_stack_count,
)

# Private compatibility exports used by existing internal callers and tests.
_apply_entity_variant_edit = _core._apply_entity_variant_edit
_build_item_compound = _core._build_item_compound
_check_item_enchantment_compatibility = _core._check_item_enchantment_compatibility
_is_compound_tag = _core._is_compound_tag
_is_list_tag = _core._is_list_tag
_item_control_field_type_issues = _core._item_control_field_type_issues
_parse_item_slot = _core._parse_item_slot
_read_item_slot = _core._read_item_slot
_set_numeric_tag_preserving_type = _core._set_numeric_tag_preserving_type
validate_item_data_value_variant = _core.validate_item_data_value_variant


def _reload_inventory_core_data():
    """Refresh item-data-bound defaults before this public facade is reloaded."""

    return _importlib.reload(_core)


__all__ = (
    "ABILITY_TAG_FIELDS",
    "ATTRIBUTE_STAT_TAGS",
    "AXOLOTL_ENTITY_ID",
    "AXOLOTL_ITEM_IDS",
    "AXOLOTL_VARIANTS",
    "DYE_COLOR_LABELS",
    "EFFECT_CONTROL_TAGS",
    "EFFECTS",
    "ENCHANTMENTS",
    "ENDER_CHEST_SLOTS",
    "INTEGER_TAG_RANGES",
    "INTEGER_TAG_TYPES",
    "ITEM_ID_RE",
    "KNOWN_PRESERVED_ITEM_TAG_KEYS",
    "MAX_BEDROCK_STACK_COUNT",
    "MAX_DAMAGE",
    "MAX_LORE_LINES",
    "MAX_NBT_VIEW_DEPTH",
    "MAX_NBT_VIEW_ITEMS",
    "MAX_NBT_VIEW_STRING",
    "MAX_TEXT_LENGTH",
    "NUMERIC_TAG_TYPES",
    "ROOT_ITEM_LIST_TAGS",
    "SCALAR_STAT_TAGS",
    "TROPICAL_FISH_BUCKET_ITEM_IDS",
    "TROPICAL_FISH_COLOR_LABELS",
    "TROPICAL_FISH_ENTITY_IDS",
    "TROPICAL_FISH_GROUP_LABELS",
    "VALID_INVENTORY_SLOTS",
    "EnchantmentEntry",
    "EntityVariantField",
    "EntityVariantInfo",
    "ParsedItemSlot",
    "PlayerStats",
    "apply_abilities",
    "apply_editable_item_tags",
    "apply_effects",
    "apply_player_stats",
    "build_ender_chest_nbt",
    "build_inventory_nbt",
    "count_hidden_unknown_slots",
    "extract_player_stats",
    "get_max_damage",
    "get_max_stack",
    "get_tag_value",
    "is_addable_item_id",
    "is_enchantable_item_id",
    "is_enchantment_compatible_with_item",
    "is_known_item_id",
    "item_payload_matches_original",
    "items_by_slot_for_origin",
    "nbt_to_json",
    "parse_abilities",
    "parse_effects",
    "parse_ender_chest",
    "protected_player_nbt_flags",
    "reject_non_addable_new_item",
    "validate_effect",
    "validate_inventory_item",
    "validate_item_original_bounds",
    "validate_item_stack_count",
)


def _json_safe_value(value):
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (bytes, bytearray)):
        return {"bytes": list(value)}
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, float) and not _math.isfinite(value):
        return {"float": repr(value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _canonical_nbt(tag):
    if _core._is_compound_tag(tag):
        entries = [[str(key), _canonical_nbt(tag[key])] for key in sorted(tag.keys(), key=str)]
        return [type(tag).__name__, entries]
    if _core._is_list_tag(tag):
        return [type(tag).__name__, [_canonical_nbt(entry) for entry in tag]]
    return [type(tag).__name__, _json_safe_value(_core.get_tag_value(tag))]


def _canonical_preserved_enchantments(list_tag):
    entries = []
    if not _core._is_list_tag(list_tag):
        return _canonical_nbt(list_tag)
    for enchantment in list_tag:
        if not _core._is_compound_tag(enchantment):
            entries.append(_canonical_nbt(enchantment))
            continue
        enchantment_id = _core._enchantment_id_from_tag(enchantment)
        if enchantment_id not in ENCHANTMENTS:
            entries.append(_canonical_nbt(enchantment))
            continue
        extra_keys = sorted((key for key in enchantment if str(key) not in {"id", "lvl"}), key=str)
        id_tag = enchantment.get("id")
        level_tag = enchantment.get("lvl")
        entries.append(
            [
                "known-shape",
                enchantment_id,
                type(id_tag).__name__ if isinstance(id_tag, NUMERIC_TAG_TYPES) else "ShortTag",
                type(level_tag).__name__ if isinstance(level_tag, NUMERIC_TAG_TYPES) else "ShortTag",
                [[str(key), _canonical_nbt(enchantment[key])] for key in extra_keys],
            ]
        )
    return [type(list_tag).__name__, entries]


def _canonical_preserved_item_tag(tag_compound, item_name: str):
    if not _core._is_compound_tag(tag_compound):
        return _canonical_nbt(tag_compound)
    entries = []
    for key in sorted(tag_compound.keys(), key=str):
        key_name = str(key)
        value = tag_compound[key]
        if key_name == "Damage" and _core._item_is_damageable(item_name) and isinstance(value, INTEGER_TAG_TYPES):
            # The value is editable for damageable items, but its NBT type and
            # presence are preserved by the write path and therefore belong to
            # the provenance fingerprint.
            entries.append([key_name, ["editable-numeric", type(value).__name__]])
            continue
        if key_name == "display" and _core._is_compound_tag(value):
            preserved_keys = []
            for entry in value:
                entry_name = str(entry)
                entry_value = value[entry]
                if entry_name == "Name" and isinstance(entry_value, _core.nbt.StringTag):
                    continue
                if entry_name == "Lore" and _core._is_string_list_tag(entry_value):
                    continue
                preserved_keys.append(entry)
            preserved_keys.sort(key=str)
            if preserved_keys:
                entries.append(
                    [
                        key_name,
                        [type(value).__name__, [[str(entry), _canonical_nbt(value[entry])] for entry in preserved_keys]],
                    ]
                )
            continue
        if key_name in {"ench", "enchantments"}:
            preserved = _canonical_preserved_enchantments(value)
            if not _core._is_list_tag(value) or preserved[1]:
                entries.append([key_name, preserved])
            continue
        entries.append([key_name, _canonical_nbt(value)])
    return [type(tag_compound).__name__, entries]


def _canonical_preserved_item(item):
    if not _core._is_compound_tag(item):
        return ["item-preserved-v1", _canonical_nbt(item)]
    entries = []
    item_name = _core._item_name_from_tag(item)
    for key in sorted(item.keys(), key=str):
        key_name = str(key)
        if key_name == "Name":
            continue
        value = item[key]
        if key_name in {"Slot", "Count", "Damage"}:
            if key_name == "Damage" and _core._item_is_damageable(item_name) and _core._item_tag_damage_tag(item) is not None:
                # With modern durability stored in tag.Damage, the legacy root
                # Damage field is no longer edited and must match exactly.
                entries.append([key_name, ["preserved-root-damage", _canonical_nbt(value)]])
            elif isinstance(value, NUMERIC_TAG_TYPES):
                # Slot/count and the active damage value are editable, while
                # their concrete NBT number type is inherited from the source.
                entries.append([key_name, ["editable-numeric", type(value).__name__]])
            else:
                entries.append([key_name, _canonical_nbt(value)])
            continue
        if key_name == "tag":
            preserved = _canonical_preserved_item_tag(value, item_name)
            if not _core._is_compound_tag(value) or preserved[1]:
                entries.append([key_name, preserved])
            continue
        entries.append([key_name, _canonical_nbt(value)])
    return ["item-preserved-v1", entries]


def _item_source_digest(item) -> str:
    canonical = _canonical_preserved_item(item)
    encoded = _json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _hashlib.sha256(encoded).hexdigest()


def _item_source_matches(item, expected_name: str, expected_digest: str) -> bool:
    return bool(item and _core._tag_item_name_matches(item, expected_name) and _hmac.compare_digest(_item_source_digest(item), expected_digest))


def _annotate_item_source_digests(items_by_slot, original_items):
    for slot, item_data in items_by_slot.items():
        source_item = original_items.get(slot)
        if source_item is not None:
            item_data["source_item_digest"] = _item_source_digest(source_item)
    return items_by_slot


def nbt_to_json(player_tag):
    inventory_data, original_items = _core.nbt_to_json(player_tag)
    return _annotate_item_source_digests(inventory_data, original_items), original_items


def parse_ender_chest(player_tag):
    chest_data = _core.parse_ender_chest(player_tag)
    list_tag = player_tag.get("EnderChestInventory") if hasattr(player_tag, "get") else None
    original_items = _core.items_by_slot_for_origin(list_tag) if _core._is_list_tag(list_tag) else {}
    return _annotate_item_source_digests(chest_data, original_items)


def _claims_original_item_nbt(validated_item) -> bool:
    return bool(validated_item.get("claims_preserved_nbt") or validated_item.get("claims_protected_nbt") or validated_item.get("claims_unknown_enchantments"))


def _unresolved_item_origin_error(validated_item) -> ValueError:
    return ValueError(
        _core.t(
            "Slot {slot} benötigt eine sichere Originalquelle, um erhaltene Item-NBT-Daten oder ein nicht neu erzeugbares Item zu bewahren, "
            "aber diese Quelle konnte nicht aufgelöst werden. "
            "Bitte Spieler neu laden und das Item erneut kopieren oder verschieben.",
            slot=validated_item["slot"],
        )
    )


def _normalized_source_item_digest(item_data, slot: int) -> str | None:
    raw_digest = item_data.get("source_item_digest")
    if raw_digest is None:
        return None
    if not isinstance(raw_digest, str):
        raise ValueError(_core.t("Ungültiger Herkunfts-Digest in Slot {slot}.", slot=slot))
    digest = raw_digest.strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(_core.t("Ungültiger Herkunfts-Digest in Slot {slot}.", slot=slot))
    return digest


def _resolve_base_item_tag(
    validated_item,
    original_items,
    source_item_maps,
    target_player_key,
    expected_source_container,
    used_external_source_checks=None,
):
    """Return the exact original item compound used as the editable NBT base.

    Provenance is an immutable source reference, not a target-location hint. A
    resolvable moved or external source is preserved for every item so standard
    but non-editable fields such as ``WasPickedUp`` do not get normalized away.
    Cross-player sources additionally carry a digest over preservation-relevant
    NBT. A changed or replaced source therefore fails closed instead of copying
    different same-name NBT. The occupied target slot is never used as fallback.
    """

    slot = validated_item["slot"]
    name = validated_item["name"]
    source_slot = validated_item.get("source_slot", slot)
    source_player_key = validated_item.get("source_player_key")
    source_container = validated_item.get("source_container")
    source_item_digest = validated_item.get("source_item_digest")
    original_target_tag = original_items.get(slot)
    requires_original = _claims_original_item_nbt(validated_item)
    requires_source = requires_original or not _core.is_addable_item_id(name)

    if source_container and source_container not in {"inventory", "ender_chest"}:
        raise _unresolved_item_origin_error(validated_item)

    if validated_item.get("replace_original_nbt") is True:
        if requires_source:
            raise _unresolved_item_origin_error(validated_item)
        return None

    source_identity_complete = bool(source_player_key) and source_container in {"inventory", "ender_chest"}
    source_claims_external = bool(
        (source_player_key and source_player_key != target_player_key) or (source_container and source_container != expected_source_container)
    )
    source_needs_lookup = source_slot != slot or source_claims_external

    if source_claims_external and not source_identity_complete:
        raise _unresolved_item_origin_error(validated_item)
    if requires_source and source_needs_lookup and not source_identity_complete:
        raise _unresolved_item_origin_error(validated_item)

    explicit_source = bool(source_identity_complete and (source_player_key != target_player_key or source_container != expected_source_container))

    if explicit_source:
        source_items = source_item_maps.get((source_player_key, source_container), {})
        source_item_tag = source_items.get(source_slot)
        source_matches = bool(source_item_tag and _core._tag_item_name_matches(source_item_tag, name))
        is_cross_player = source_player_key != target_player_key
        if is_cross_player and source_item_digest is None:
            raise _unresolved_item_origin_error(validated_item)
        if source_matches and source_item_digest is not None:
            source_matches = _hmac.compare_digest(_item_source_digest(source_item_tag), source_item_digest)
        if (is_cross_player or source_item_digest is not None) and not source_matches:
            raise _unresolved_item_origin_error(validated_item)
        if source_matches:
            if is_cross_player and used_external_source_checks is not None:
                used_external_source_checks.add(
                    (
                        source_player_key,
                        source_container,
                        source_slot,
                        name,
                        source_item_digest,
                    )
                )
            return source_item_tag
        if requires_source:
            raise _unresolved_item_origin_error(validated_item)
        return None

    if source_slot != slot:
        source_item_tag = original_items.get(source_slot)
        source_matches = bool(source_item_tag and _core._tag_item_name_matches(source_item_tag, name))
        if source_matches and source_item_digest is not None:
            source_matches = _hmac.compare_digest(_item_source_digest(source_item_tag), source_item_digest)
        if source_matches:
            return source_item_tag
        if requires_source or source_item_digest is not None:
            raise _unresolved_item_origin_error(validated_item)
        return None

    target_matches = _core._tag_item_name_matches(original_target_tag, name)
    if target_matches and source_item_digest is not None:
        target_matches = _hmac.compare_digest(_item_source_digest(original_target_tag), source_item_digest)
    if target_matches:
        return original_target_tag
    if requires_original or source_item_digest is not None:
        raise _unresolved_item_origin_error(validated_item)
    return None


def _build_item_nbt_list(
    player_tag,
    tag_name,
    inventory_list,
    enchantments_db,
    valid_slots,
    duplicate_label,
    is_ender_chest=False,
    source_item_maps=None,
    target_player_key=None,
    extra_original_items=None,
    used_external_source_checks=None,
):
    if not isinstance(inventory_list, list):
        raise ValueError(_core.t("{label}-Daten müssen eine Liste sein.", label=duplicate_label))

    original_tag = player_tag.get(tag_name)
    if original_tag is not None and not _core._is_list_tag(original_tag):
        if inventory_list:
            raise ValueError(f"{duplicate_label}-Tag hat einen unbekannten NBT-Typ und kann nicht bearbeitet werden, ohne Datenverlust zu riskieren.")
        return original_tag.copy()
    original_sequence = list(original_tag or [])
    original_items = dict(extra_original_items or {})
    original_items.update(_core._original_items_by_slot(player_tag, tag_name))
    protected_only_slots = _core._protected_only_item_slots(original_sequence, valid_slots)
    source_item_maps = source_item_maps or {}
    expected_source_container = "ender_chest" if is_ender_chest else "inventory"
    new_items_by_slot = {}
    seen_slots = set()

    for item_data in inventory_list:
        validated_item = _core.validate_inventory_item(
            item_data,
            enchantments_db,
            is_ender_chest=is_ender_chest,
            defer_stack_limit=True,
            defer_original_bounds=True,
        )
        if validated_item is None:
            continue
        validated_item["replace_original_nbt"] = item_data.get("replace_original_nbt") is True
        validated_item["source_item_digest"] = _normalized_source_item_digest(item_data, validated_item["slot"])

        slot = validated_item["slot"]
        if slot in protected_only_slots:
            raise ValueError(
                _core.t(
                    "{label}-Slot {slot} enthält einen geschützten nicht darstellbaren Originaleintrag. "
                    "Der Slot kann nicht bearbeitet oder überschrieben werden, ohne unbekannte NBT-Daten zu riskieren.",
                    label=duplicate_label,
                    slot=slot,
                )
            )
        if slot in seen_slots:
            raise ValueError(_core.t("Doppelter {label}-Slot empfangen: {slot}", label=duplicate_label, slot=slot))
        seen_slots.add(slot)
        name = validated_item["name"]
        base_item_tag = _resolve_base_item_tag(
            validated_item,
            original_items,
            source_item_maps,
            target_player_key,
            expected_source_container,
            used_external_source_checks,
        )
        _core._check_item_enchantment_compatibility(name, validated_item, base_item_tag, enchantments_db, duplicate_label, slot)
        _core.reject_non_addable_new_item(name, base_item_tag, duplicate_label, slot)
        _core.validate_item_stack_count(name, validated_item["count"], base_item_tag, duplicate_label, slot)
        _core.validate_item_original_bounds(validated_item, base_item_tag, duplicate_label, slot)
        _core.validate_item_data_value_variant(name, validated_item["damage"], base_item_tag, duplicate_label, slot)
        # The payload always carries the complete container, so most entries of a
        # normal save are untouched echoes. Those must not be rebuilt: the tag
        # writers normalize enchantment order and drop empty standard containers,
        # which would silently reshape slots the user never opened.
        unchanged = _core.item_payload_matches_original(base_item_tag, validated_item, enchantments_db)
        item_compound = _core._build_item_compound(base_item_tag, validated_item, duplicate_label, is_ender_chest, unchanged=unchanged)
        if not unchanged:
            _core.apply_editable_item_tags(item_compound, validated_item, enchantments_db)
            _core._apply_entity_variant_edit(item_compound, validated_item, base_item_tag, duplicate_label)
        new_items_by_slot[slot] = item_compound

    return _core.nbt.ListTag(_core._merge_items_into_original_sequence(original_sequence, valid_slots, new_items_by_slot))


def build_inventory_nbt(
    player_tag,
    inventory_list,
    enchantments_db,
    source_item_maps=None,
    target_player_key=None,
    extra_original_items=None,
    used_external_source_checks=None,
):
    return _build_item_nbt_list(
        player_tag,
        "Inventory",
        inventory_list,
        enchantments_db,
        _core.VALID_INVENTORY_SLOTS,
        "Inventar",
        is_ender_chest=False,
        source_item_maps=source_item_maps,
        target_player_key=target_player_key,
        extra_original_items=extra_original_items,
        used_external_source_checks=used_external_source_checks,
    )


def build_ender_chest_nbt(
    player_tag,
    inventory_list,
    enchantments_db,
    source_item_maps=None,
    target_player_key=None,
    used_external_source_checks=None,
):
    return _build_item_nbt_list(
        player_tag,
        "EnderChestInventory",
        inventory_list,
        enchantments_db,
        _core.ENDER_CHEST_SLOTS,
        "Enderchest",
        is_ender_chest=True,
        source_item_maps=source_item_maps,
        target_player_key=target_player_key,
        used_external_source_checks=used_external_source_checks,
    )
