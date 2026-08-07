"""Safe state transfer between existing local and multiplayer player records.

The destination record is never replaced wholesale.  Only explicitly reviewed
game-state fields are mirrored from the source, while the destination key and
all destination-owned identity or unknown root fields remain untouched.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import amulet_nbt as nbt

from .bedrock_nbt import load_player_nbt, save_player_nbt
from .i18n import t

PLAYER_STATE_TRANSFER_SCHEMA_VERSION = 4

# Keep this policy deliberately explicit.  Unknown root fields may belong to an
# add-on or to a newer Bedrock release and therefore stay with the destination.
PLAYER_STATE_GROUPS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "inventory": (
        "Inventar und Ausrüstung",
        (
            "Inventory",
            "EnderChestInventory",
            "Armor",
            "Mainhand",
            "Offhand",
            "PlayerUIItems",
            "SelectedInventorySlot",
        ),
    ),
    "location": (
        "Position, Spawnpunkt und letzter Todesort",
        (
            "Pos",
            "Rotation",
            "Motion",
            "DimensionId",
            "FallDistance",
            "OnGround",
            "PortalCooldown",
            "SpawnX",
            "SpawnY",
            "SpawnZ",
            "SpawnBlockPositionX",
            "SpawnBlockPositionY",
            "SpawnBlockPositionZ",
            "SpawnDimension",
            "Sleeping",
            "SleepTimer",
            "HasDiedBefore",
            "DeathDimension",
            "DeathPositionX",
            "DeathPositionY",
            "DeathPositionZ",
        ),
    ),
    "vitals": (
        "Gesundheit, Hunger, Erschöpfung und Effekte",
        (
            "Health",
            "Air",
            "foodLevel",
            "foodSaturationLevel",
            "Attributes",
            "ActiveEffects",
            "HurtTime",
            "DeathTime",
            "Dead",
            "IsGliding",
            "IsSwimming",
            "Sneaking",
            "TimeSinceRest",
        ),
    ),
    "progress": (
        "Erfahrung, Fortschritt und Rezepte",
        (
            "PlayerLevel",
            "PlayerLevelProgress",
            "XPLevel",
            "XPProgress",
            "EnchantmentSeed",
            "HasSeenCredits",
            "recipe_unlocking",
        ),
    ),
    "gameplay": (
        "Spielmodus und Fähigkeiten",
        (
            "abilities",
            "PlayerGameMode",
            "PlayerGameType",
        ),
    ),
}

TRANSFERABLE_PLAYER_STATE_FIELD_ORDER = tuple(key for _group_label, group_keys in PLAYER_STATE_GROUPS.values() for key in group_keys)
TRANSFERABLE_PLAYER_STATE_KEYS = frozenset(TRANSFERABLE_PLAYER_STATE_FIELD_ORDER)

# These names are informational guardrails.  The allowlist above already keeps
# every unlisted root field, including future identity fields, on the target.
PLAYER_IDENTITY_ROOT_KEYS = frozenset(
    {
        "UniqueID",
        "MsaId",
        "SelfSignedId",
        "ServerId",
        "PlatformOnlineId",
        "OwnerNew",
        "LeasherID",
        "SkinID",
        "UUID",
    }
)

# Structured containers need a second allowlist level. Replacing these roots
# wholesale would silently drop target-owned add-on data and copy unreviewed
# source fields. Item/effect containers intentionally remain complete gameplay
# state because their nested metadata belongs to the transferred item/effect.
TRANSFERABLE_ABILITY_FIELD_ORDER = (
    "flySpeed",
    "walkSpeed",
    "mayfly",
    "flying",
    "invulnerable",
    "mayBuild",
    "maybuild",
    "instabuild",
)
TRANSFERABLE_ABILITY_KEYS = frozenset(TRANSFERABLE_ABILITY_FIELD_ORDER)
TRANSFERABLE_ATTRIBUTE_NAMES = frozenset(
    {
        "minecraft:health",
        "minecraft:follow_range",
        "minecraft:knockback_resistance",
        "minecraft:movement",
        "minecraft:underwater_movement",
        "minecraft:lava_movement",
        "minecraft:attack_damage",
        "minecraft:absorption",
        "minecraft:luck",
        "minecraft:friction_modifier",
        "minecraft:bounciness",
        "minecraft:air_drag_modifier",
        "minecraft:player.level",
        "minecraft:player.experience",
        "minecraft:player.hunger",
        "minecraft:player.saturation",
        "minecraft:player.exhaustion",
    }
)
TRANSFERABLE_RECIPE_UNLOCKING_KEYS = frozenset({"unlocked_recipes", "used_contexts"})
STRUCTURED_TRANSFER_FIELDS = frozenset({"abilities", "Attributes", "recipe_unlocking"})
PLAYER_DEATH_LOCATION_FIELDS = (
    "HasDiedBefore",
    "DeathDimension",
    "DeathPositionX",
    "DeathPositionY",
    "DeathPositionZ",
)
PLAYER_DEATH_COORDINATE_FIELD_ORDER = PLAYER_DEATH_LOCATION_FIELDS[1:]
PLAYER_DEATH_COORDINATE_FIELDS = frozenset(PLAYER_DEATH_COORDINATE_FIELD_ORDER)


def _compound_keys(tag: nbt.CompoundTag) -> set[str]:
    return {str(key) for key in tag}


def _tag_bytes(value) -> bytes:
    # Amulet's Java default uses MUTF-8 (including CESU-8 surrogate pairs),
    # while the matching loader expects Bedrock UTF-8. Keep cloning on the
    # shared Bedrock codec so NUL and non-BMP characters remain intact.
    wrapper = nbt.NamedTag(nbt.CompoundTag({"value": value}))
    return save_player_nbt(wrapper)


def _clone_tag(value):
    """Clone an NBT tag without losing the encoded type of empty ListTags."""

    return load_player_nbt(_tag_bytes(value)).tag["value"]


def _optional_compound(root: nbt.CompoundTag, field: str) -> nbt.CompoundTag | None:
    if field not in root:
        return None
    value = root[field]
    if not isinstance(value, nbt.CompoundTag):
        raise ValueError(t("Zustandsübertragung abgelehnt: {field} hat einen unbekannten NBT-Typ.", field=field))
    return value


def _optional_list(root: nbt.CompoundTag, field: str) -> nbt.ListTag | None:
    if field not in root:
        return None
    value = root[field]
    if not isinstance(value, nbt.ListTag):
        raise ValueError(t("Zustandsübertragung abgelehnt: {field} hat einen unbekannten NBT-Typ.", field=field))
    if field == "Attributes" and any(not isinstance(entry, nbt.CompoundTag) for entry in value):
        raise ValueError(t("Zustandsübertragung abgelehnt: Attributes enthält einen unbekannten Eintragstyp."))
    return value


def _optional_recipe_unlocking(root: nbt.CompoundTag) -> nbt.CompoundTag | None:
    recipe_unlocking = _optional_compound(root, "recipe_unlocking")
    if recipe_unlocking is None:
        return None
    if "unlocked_recipes" in recipe_unlocking:
        unlocked_recipes = recipe_unlocking["unlocked_recipes"]
        if not isinstance(unlocked_recipes, nbt.ListTag):
            raise ValueError(t("Zustandsübertragung abgelehnt: recipe_unlocking.unlocked_recipes hat einen unbekannten NBT-Typ."))
        if any(not isinstance(entry, nbt.StringTag) for entry in unlocked_recipes):
            raise ValueError(t("Zustandsübertragung abgelehnt: recipe_unlocking.unlocked_recipes enthält einen unbekannten Eintragstyp."))
    if "used_contexts" in recipe_unlocking and not isinstance(recipe_unlocking["used_contexts"], nbt.IntTag):
        raise ValueError(t("Zustandsübertragung abgelehnt: recipe_unlocking.used_contexts hat einen unbekannten NBT-Typ."))
    return recipe_unlocking


def _validate_reviewed_root_state(root: nbt.CompoundTag) -> None:
    if "TimeSinceRest" in root and not isinstance(root["TimeSinceRest"], nbt.IntTag):
        raise ValueError(t("Zustandsübertragung abgelehnt: TimeSinceRest hat einen unbekannten NBT-Typ."))

    if "HasDiedBefore" in root and not isinstance(root["HasDiedBefore"], nbt.ByteTag):
        raise ValueError(t("Zustandsübertragung abgelehnt: HasDiedBefore hat einen unbekannten NBT-Typ."))
    present_death_coordinates = {field for field in PLAYER_DEATH_COORDINATE_FIELDS if field in root}
    for field in PLAYER_DEATH_COORDINATE_FIELD_ORDER:
        if field not in present_death_coordinates:
            continue
        if not isinstance(root[field], nbt.IntTag):
            raise ValueError(t("Zustandsübertragung abgelehnt: {field} hat einen unbekannten NBT-Typ.", field=field))
    if present_death_coordinates and present_death_coordinates != PLAYER_DEATH_COORDINATE_FIELDS:
        raise ValueError(t("Zustandsübertragung abgelehnt: Der letzte Todesort ist unvollständig."))
    if present_death_coordinates and "HasDiedBefore" not in root:
        raise ValueError(t("Zustandsübertragung abgelehnt: Der letzte Todesort besitzt keinen HasDiedBefore-Status."))


def _recipe_ids(recipe_unlocking: nbt.CompoundTag | None) -> list[str]:
    if recipe_unlocking is None or "unlocked_recipes" not in recipe_unlocking:
        return []
    return [entry.py_data for entry in recipe_unlocking["unlocked_recipes"]]


def _attribute_name(value) -> str | None:
    if not isinstance(value, nbt.CompoundTag) or "Name" not in value:
        return None
    name = getattr(value["Name"], "py_data", None)
    return name if isinstance(name, str) and name else None


def _nested_entry_labels(values, *, field: str, allowed_names: frozenset[str], include_allowed: bool) -> list[str]:
    labels = []
    for index, value in enumerate(values or ()):
        name = _attribute_name(value)
        is_allowed = name in allowed_names
        if is_allowed != include_allowed:
            continue
        labels.append(f"{field}[{name or f'#{index}'}]")
    return labels


def _structured_transfer_plan(source_tag: nbt.CompoundTag, target_tag: nbt.CompoundTag) -> dict:
    source_abilities = _optional_compound(source_tag, "abilities")
    target_abilities = _optional_compound(target_tag, "abilities")
    source_ability_keys = _compound_keys(source_abilities) if source_abilities is not None else set()
    target_ability_keys = _compound_keys(target_abilities) if target_abilities is not None else set()
    copied_ability_keys = source_ability_keys & TRANSFERABLE_ABILITY_KEYS
    cleared_ability_keys = (target_ability_keys & TRANSFERABLE_ABILITY_KEYS) - source_ability_keys
    changed_ability_keys = {
        field
        for field in copied_ability_keys
        if target_abilities is None or field not in target_abilities or _tag_bytes(source_abilities[field]) != _tag_bytes(target_abilities[field])
    }

    source_attributes = _optional_list(source_tag, "Attributes")
    target_attributes = _optional_list(target_tag, "Attributes")
    source_attribute_names = {name for value in source_attributes or () if (name := _attribute_name(value)) in TRANSFERABLE_ATTRIBUTE_NAMES}
    target_attribute_names = {name for value in target_attributes or () if (name := _attribute_name(value)) in TRANSFERABLE_ATTRIBUTE_NAMES}
    copied_attributes = _nested_entry_labels(
        source_attributes,
        field="Attributes",
        allowed_names=TRANSFERABLE_ATTRIBUTE_NAMES,
        include_allowed=True,
    )
    preserved_attributes = _nested_entry_labels(
        target_attributes,
        field="Attributes",
        allowed_names=TRANSFERABLE_ATTRIBUTE_NAMES,
        include_allowed=False,
    )
    skipped_attributes = _nested_entry_labels(
        source_attributes,
        field="Attributes",
        allowed_names=TRANSFERABLE_ATTRIBUTE_NAMES,
        include_allowed=False,
    )
    cleared_attributes = [f"Attributes[{name}]" for name in sorted(target_attribute_names - source_attribute_names)]
    changed_attribute_names = {
        name
        for name in source_attribute_names
        if _tag_bytes(nbt.ListTag([_clone_tag(value) for value in source_attributes or () if _attribute_name(value) == name]))
        != _tag_bytes(nbt.ListTag([_clone_tag(value) for value in target_attributes or () if _attribute_name(value) == name]))
    }

    source_recipes = _optional_recipe_unlocking(source_tag)
    target_recipes = _optional_recipe_unlocking(target_tag)
    source_recipe_keys = _compound_keys(source_recipes) if source_recipes is not None else set()
    target_recipe_keys = _compound_keys(target_recipes) if target_recipes is not None else set()
    source_recipe_ids = _recipe_ids(source_recipes)
    target_recipe_ids = _recipe_ids(target_recipes)
    target_recipe_id_set = set(target_recipe_ids)
    added_recipe_ids = []
    seen_recipe_ids = set(target_recipe_id_set)
    for recipe_id in source_recipe_ids:
        if recipe_id in seen_recipe_ids:
            continue
        seen_recipe_ids.add(recipe_id)
        added_recipe_ids.append(recipe_id)

    changed_recipe_fields = []
    source_has_unlocked_recipes = source_recipes is not None and "unlocked_recipes" in source_recipes
    target_has_unlocked_recipes = target_recipes is not None and "unlocked_recipes" in target_recipes
    if source_has_unlocked_recipes and (not target_has_unlocked_recipes or added_recipe_ids):
        changed_recipe_fields.append("unlocked_recipes")

    source_has_used_contexts = source_recipes is not None and "used_contexts" in source_recipes
    target_has_used_contexts = target_recipes is not None and "used_contexts" in target_recipes
    source_used_contexts = source_recipes["used_contexts"].py_data if source_has_used_contexts else 0
    target_used_contexts = target_recipes["used_contexts"].py_data if target_has_used_contexts else 0
    resulting_used_contexts = source_used_contexts | target_used_contexts
    if source_has_used_contexts and (not target_has_used_contexts or resulting_used_contexts != target_used_contexts):
        changed_recipe_fields.append("used_contexts")

    return {
        "abilities": {
            "copied_fields": sorted(copied_ability_keys),
            "cleared_fields": sorted(cleared_ability_keys),
            "preserved_target_fields": sorted(target_ability_keys - TRANSFERABLE_ABILITY_KEYS),
            "skipped_source_fields": sorted(source_ability_keys - TRANSFERABLE_ABILITY_KEYS),
            "change_count": len(changed_ability_keys) + len(cleared_ability_keys),
        },
        "attributes": {
            "copied_fields": copied_attributes,
            "cleared_fields": cleared_attributes,
            "preserved_target_fields": preserved_attributes,
            "skipped_source_fields": skipped_attributes,
            "change_count": len(changed_attribute_names) + len(cleared_attributes),
        },
        "recipe_unlocking": {
            "copied_fields": sorted(changed_recipe_fields),
            "cleared_fields": [],
            "preserved_target_fields": sorted(target_recipe_keys - TRANSFERABLE_RECIPE_UNLOCKING_KEYS),
            "skipped_source_fields": sorted(source_recipe_keys - TRANSFERABLE_RECIPE_UNLOCKING_KEYS),
            "change_count": len(changed_recipe_fields),
            "source_present": source_recipes is not None,
            "target_present": target_recipes is not None,
            "source_recipe_count": len(source_recipe_ids),
            "target_recipe_count": len(target_recipe_id_set),
            "added_recipe_count": len(added_recipe_ids),
            "result_recipe_count": len(target_recipe_id_set) + len(added_recipe_ids),
        },
    }


def _merge_abilities(source_tag: nbt.CompoundTag, target_tag: nbt.CompoundTag) -> None:
    source = _optional_compound(source_tag, "abilities")
    target = _optional_compound(target_tag, "abilities")
    merged = _clone_tag(target) if target is not None else nbt.CompoundTag()
    for field in TRANSFERABLE_ABILITY_FIELD_ORDER:
        if source is not None and field in source:
            merged[field] = _clone_tag(source[field])
        elif field in merged:
            del merged[field]
    if len(merged) > 0 or (target is not None and len(target) == 0):
        target_tag["abilities"] = merged
    elif "abilities" in target_tag:
        del target_tag["abilities"]


def _merge_attributes(source_tag: nbt.CompoundTag, target_tag: nbt.CompoundTag) -> None:
    source = _optional_list(source_tag, "Attributes")
    target = _optional_list(target_tag, "Attributes")
    source_by_name: dict[str, list] = {}
    for value in source or ():
        name = _attribute_name(value)
        if name in TRANSFERABLE_ATTRIBUTE_NAMES:
            source_by_name.setdefault(name, []).append(value)

    merged_values = []
    inserted_names = set()
    for value in target or ():
        name = _attribute_name(value)
        if name in TRANSFERABLE_ATTRIBUTE_NAMES:
            if name not in inserted_names:
                merged_values.extend(_clone_tag(entry) for entry in source_by_name.get(name, ()))
                inserted_names.add(name)
            continue
        merged_values.append(_clone_tag(value))
    for value in source or ():
        name = _attribute_name(value)
        if name in TRANSFERABLE_ATTRIBUTE_NAMES and name not in inserted_names:
            merged_values.extend(_clone_tag(entry) for entry in source_by_name.get(name, ()))
            inserted_names.add(name)

    if merged_values:
        target_tag["Attributes"] = nbt.ListTag(merged_values)
    elif target is not None and len(target) == 0:
        # Keep the existing empty ListTag byte-exact, including its encoded
        # element type. Amulet defaults newly constructed empty lists to byte.
        return
    elif "Attributes" in target_tag:
        del target_tag["Attributes"]


def _merge_recipe_unlocking(source_tag: nbt.CompoundTag, target_tag: nbt.CompoundTag) -> None:
    source = _optional_recipe_unlocking(source_tag)
    target = _optional_recipe_unlocking(target_tag)
    merged = _clone_tag(target) if target is not None else nbt.CompoundTag()

    if source is not None and "unlocked_recipes" in source:
        target_entries = list(target["unlocked_recipes"]) if target is not None and "unlocked_recipes" in target else []
        merged_entries = [_clone_tag(entry) for entry in target_entries]
        seen_recipe_ids = {entry.py_data for entry in target_entries}
        added_recipe = False
        for entry in source["unlocked_recipes"]:
            if entry.py_data in seen_recipe_ids:
                continue
            merged_entries.append(_clone_tag(entry))
            seen_recipe_ids.add(entry.py_data)
            added_recipe = True
        if target is None or "unlocked_recipes" not in target:
            merged["unlocked_recipes"] = nbt.ListTag(merged_entries) if merged_entries else _clone_tag(source["unlocked_recipes"])
        elif added_recipe:
            merged["unlocked_recipes"] = nbt.ListTag(merged_entries)

    if source is not None and "used_contexts" in source:
        source_used_contexts = source["used_contexts"].py_data
        target_used_contexts = target["used_contexts"].py_data if target is not None and "used_contexts" in target else 0
        merged["used_contexts"] = nbt.IntTag(source_used_contexts | target_used_contexts)

    if len(merged) > 0 or target is not None:
        target_tag["recipe_unlocking"] = merged


def _apply_transferable_state(source_tag: nbt.CompoundTag, target_tag: nbt.CompoundTag) -> None:
    for field in TRANSFERABLE_PLAYER_STATE_FIELD_ORDER:
        if field == "abilities":
            _merge_abilities(source_tag, target_tag)
        elif field == "Attributes":
            _merge_attributes(source_tag, target_tag)
        elif field == "recipe_unlocking":
            _merge_recipe_unlocking(source_tag, target_tag)
        elif field in source_tag:
            if field not in target_tag or _tag_bytes(source_tag[field]) != _tag_bytes(target_tag[field]):
                target_tag[field] = _clone_tag(source_tag[field])
        elif field in target_tag:
            del target_tag[field]


def transfer_policy_id() -> str:
    payload = {
        "schema_version": PLAYER_STATE_TRANSFER_SCHEMA_VERSION,
        "groups": {group: list(keys) for group, (_label, keys) in PLAYER_STATE_GROUPS.items()},
        "ability_fields": list(TRANSFERABLE_ABILITY_FIELD_ORDER),
        "attribute_names": sorted(TRANSFERABLE_ATTRIBUTE_NAMES),
        "recipe_unlocking_fields": sorted(TRANSFERABLE_RECIPE_UNLOCKING_KEYS),
        "recipe_unlocking_strategy": "union",
        "death_location_fields": list(PLAYER_DEATH_LOCATION_FIELDS),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_player_state_transfer_plan(source_tag: nbt.CompoundTag, target_tag: nbt.CompoundTag) -> dict:
    if not isinstance(source_tag, nbt.CompoundTag) or not isinstance(target_tag, nbt.CompoundTag):
        raise ValueError(t("Zustandsübertragung abgelehnt: Quelle und Ziel benötigen Player-NBT mit Compound-Root."))
    _validate_reviewed_root_state(source_tag)
    _validate_reviewed_root_state(target_tag)

    source_keys = _compound_keys(source_tag)
    target_keys = _compound_keys(target_tag)
    groups = []
    transferred_fields: list[str] = []
    cleared_fields: list[str] = []
    structured_fields = _structured_transfer_plan(source_tag, target_tag)
    for group_id, (label, fields) in PLAYER_STATE_GROUPS.items():
        root_fields = tuple(field for field in fields if field not in STRUCTURED_TRANSFER_FIELDS)
        copied = sorted(field for field in root_fields if field in source_keys)
        cleared = sorted(field for field in root_fields if field not in source_keys and field in target_keys)
        transferred_fields.extend(copied)
        cleared_fields.extend(cleared)
        copied_change_count = sum(1 for field in copied if field not in target_tag or _tag_bytes(source_tag[field]) != _tag_bytes(target_tag[field]))
        structured_change_count = 0
        for field in fields:
            if field not in STRUCTURED_TRANSFER_FIELDS:
                continue
            structured_plan = structured_fields[field.lower()]
            structured_change_count += structured_plan["change_count"]
        groups.append(
            {
                "id": group_id,
                "label": label,
                "copied_fields": copied,
                "cleared_fields": cleared,
                "change_count": copied_change_count + len(cleared) + structured_change_count,
            }
        )

    preserved_target_fields = sorted(target_keys - TRANSFERABLE_PLAYER_STATE_KEYS)
    skipped_source_fields = sorted(source_keys - TRANSFERABLE_PLAYER_STATE_KEYS)
    nested_preserved_target_fields = (
        [f"abilities.{field}" for field in structured_fields["abilities"]["preserved_target_fields"]]
        + structured_fields["attributes"]["preserved_target_fields"]
        + [f"recipe_unlocking.{field}" for field in structured_fields["recipe_unlocking"]["preserved_target_fields"]]
    )
    nested_skipped_source_fields = (
        [f"abilities.{field}" for field in structured_fields["abilities"]["skipped_source_fields"]]
        + structured_fields["attributes"]["skipped_source_fields"]
        + [f"recipe_unlocking.{field}" for field in structured_fields["recipe_unlocking"]["skipped_source_fields"]]
    )
    return {
        "schema_version": PLAYER_STATE_TRANSFER_SCHEMA_VERSION,
        "policy_id": transfer_policy_id(),
        "groups": groups,
        "transferred_fields": sorted(transferred_fields),
        "cleared_fields": sorted(cleared_fields),
        "preserved_target_fields": preserved_target_fields,
        "preserved_identity_fields": sorted(target_keys & PLAYER_IDENTITY_ROOT_KEYS),
        "skipped_source_fields": skipped_source_fields,
        "nested_preserved_target_fields": sorted(nested_preserved_target_fields),
        "nested_skipped_source_fields": sorted(nested_skipped_source_fields),
        "structured_fields": structured_fields,
        "source_field_count": len(source_keys),
        "target_field_count": len(target_keys),
    }


def merge_player_state(source_raw: bytes, target_raw: bytes) -> tuple[bytes, dict]:
    source_named = load_player_nbt(source_raw)
    target_named = load_player_nbt(target_raw)
    source_tag = source_named.tag
    target_tag = target_named.tag
    plan = build_player_state_transfer_plan(source_tag, target_tag)

    _apply_transferable_state(source_tag, target_tag)

    merged_raw = save_player_nbt(target_named)
    validate_player_state_transfer(
        source_raw,
        target_raw,
        merged_raw,
        source_after_raw=save_player_nbt(source_named),
        expected_plan=plan,
    )
    return merged_raw, plan


def validate_player_state_transfer(
    source_raw: bytes,
    target_before_raw: bytes,
    target_after_raw: bytes,
    *,
    source_after_raw: bytes,
    expected_plan: dict | None = None,
) -> dict:
    source_unchanged = source_after_raw == source_raw
    if not source_unchanged:
        raise ValueError(t("Nachvalidierung fehlgeschlagen: Der Quelldatensatz wurde verändert."))

    source_tag = load_player_nbt(source_raw).tag
    target_before_tag = load_player_nbt(target_before_raw).tag
    target_after_tag = load_player_nbt(target_after_raw).tag
    plan = build_player_state_transfer_plan(source_tag, target_before_tag)
    if expected_plan is not None and (expected_plan.get("schema_version") != plan["schema_version"] or expected_plan.get("policy_id") != plan["policy_id"]):
        raise ValueError(t("Zustandsübertragung abgelehnt: Die Feldrichtlinie hat sich seit der Vorschau geändert."))

    expected_after_tag = _clone_tag(target_before_tag)
    _apply_transferable_state(source_tag, expected_after_tag)
    for field in TRANSFERABLE_PLAYER_STATE_FIELD_ORDER:
        source_has = field in expected_after_tag
        target_after_has = field in target_after_tag
        if source_has != target_after_has:
            raise ValueError(t("Nachvalidierung fehlgeschlagen: Zustand von {field} stimmt nicht mit der Übertragungsrichtlinie überein.", field=field))
        if source_has and _tag_bytes(expected_after_tag[field]) != _tag_bytes(target_after_tag[field]):
            raise ValueError(t("Nachvalidierung fehlgeschlagen: Zustand von {field} stimmt nicht mit der Übertragungsrichtlinie überein.", field=field))

    target_before_keys = _compound_keys(target_before_tag)
    target_after_keys = _compound_keys(target_after_tag)
    identity_fields = target_before_keys & PLAYER_IDENTITY_ROOT_KEYS
    target_identity_preserved = all(
        field in target_after_tag and _tag_bytes(target_before_tag[field]) == _tag_bytes(target_after_tag[field]) for field in identity_fields
    )
    if not target_identity_preserved:
        changed_field = next(
            field
            for field in sorted(identity_fields)
            if field not in target_after_tag or _tag_bytes(target_before_tag[field]) != _tag_bytes(target_after_tag[field])
        )
        raise ValueError(t("Nachvalidierung fehlgeschlagen: Zielfeld {field} wurde verändert.", field=changed_field))

    preserved_fields = target_before_keys - TRANSFERABLE_PLAYER_STATE_KEYS
    if target_after_keys - TRANSFERABLE_PLAYER_STATE_KEYS != preserved_fields:
        raise ValueError(t("Nachvalidierung fehlgeschlagen: Zielgebundene oder unbekannte Root-Felder wurden verändert."))
    for field in preserved_fields:
        if _tag_bytes(target_before_tag[field]) != _tag_bytes(target_after_tag[field]):
            raise ValueError(t("Nachvalidierung fehlgeschlagen: Zielfeld {field} wurde verändert.", field=field))

    structured_plan = plan["structured_fields"]
    structured_transferred_count = sum(len(details["copied_fields"]) for details in structured_plan.values())
    structured_cleared_count = sum(len(details["cleared_fields"]) for details in structured_plan.values())
    structured_preserved_count = sum(len(details["preserved_target_fields"]) for details in structured_plan.values())
    return {
        "valid": True,
        "policy_id": plan["policy_id"],
        "transferred_field_count": len(plan["transferred_fields"]) + structured_transferred_count,
        "cleared_field_count": len(plan["cleared_fields"]) + structured_cleared_count,
        "preserved_target_field_count": len(plan["preserved_target_fields"]) + structured_preserved_count,
        "source_unchanged": source_unchanged,
        "target_identity_preserved": target_identity_preserved,
    }
