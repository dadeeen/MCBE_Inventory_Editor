"""Read the effective item database without publishing or recovering application state."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .item_name_policy import confirmed_item_label_pair, reviewed_item_label_repairs
from .item_registry_policy import apply_reviewed_registry, catalog_registry, is_non_item_lang_key_id, release_version_key, validated_behavior_item_source
from .numeric_catalog_policy import NumericCatalogConflictError, reconcile_numeric_catalog

LOGGER = logging.getLogger(__name__)
# Safe creation bound when no per-item evidence is available.
DEFAULT_MAX_STACK = 1
BUNDLED_ENCHANTMENT_COMPATIBILITY_JSON = Path(__file__).with_name("enchantment_compatibility.json")


class InvalidItemDatabaseError(ValueError):
    """The item database exists but cannot be parsed or validated safely."""


def _slot_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Enchantment-Kompatibilität {label} muss eine nichtleere Liste sein.")
    result: list[str] = []
    for entry in value:
        slot = str(entry or "").strip()
        if not slot:
            raise ValueError(f"Enchantment-Kompatibilität {label} enthält einen leeren Slot.")
        result.append(slot)
    return result


def _slot_set_map(raw: Any, *, label: str) -> dict[str, set[str]]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"Enchantment-Kompatibilität {label} muss ein Objekt sein.")
    return {str(key): set(_slot_list(value, label=f"{label}.{key}")) for key, value in raw.items()}


def _compatible_slot_map(raw: Any) -> dict[int, set[str]]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Enchantment-Kompatibilität compatible_slots muss ein Objekt sein.")
    return {int(key): set(_slot_list(value, label=f"compatible_slots.{key}")) for key, value in raw.items()}


def _item_slot_suffixes(raw: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        raise ValueError("Enchantment-Kompatibilität item_slot_suffixes muss eine Liste sein.")
    result: list[tuple[str, str]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError(f"Enchantment-Kompatibilität item_slot_suffixes[{index}] muss [suffix, slot] sein.")
        suffix = str(entry[0] or "").strip()
        slot = str(entry[1] or "").strip()
        if not suffix or not slot:
            raise ValueError(f"Enchantment-Kompatibilität item_slot_suffixes[{index}] enthält leere Werte.")
        result.append((suffix, slot))
    return tuple(result)


def load_enchantment_compatibility(path: str | os.PathLike | None = None) -> dict[str, Any]:
    source_path = Path(path or os.environ.get("MCBE_ENCHANTMENT_COMPATIBILITY_PATH") or BUNDLED_ENCHANTMENT_COMPATIBILITY_JSON).expanduser()
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Enchantment-Kompatibilität JSON ist ungültig: {source_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Enchantment-Kompatibilität JSON muss ein Objekt sein.")

    slot_groups = _slot_set_map(raw.get("slot_groups"), label="slot_groups")
    item_slots = _slot_set_map(raw.get("item_slots", {}), label="item_slots")
    compatible_slots = _compatible_slot_map(raw.get("compatible_slots"))
    item_slot_suffixes = _item_slot_suffixes(raw.get("item_slot_suffixes", []))
    known_slots = set(slot_groups)
    for values in slot_groups.values():
        known_slots.update(values)
    referenced_slot_sets = [
        ("compatible_slots", {slot for values in compatible_slots.values() for slot in values}),
        ("item_slots", {slot for values in item_slots.values() for slot in values}),
    ]
    for label, slots in referenced_slot_sets:
        unknown = sorted(slots - known_slots)
        if unknown:
            raise ValueError(f"Enchantment-Kompatibilität {label} referenziert unbekannte Slots: {', '.join(unknown)}")
    suffix_unknown = sorted({slot for _suffix, slot in item_slot_suffixes} - known_slots)
    if suffix_unknown:
        raise ValueError(f"Enchantment-Kompatibilität item_slot_suffixes referenziert unbekannte Slots: {', '.join(suffix_unknown)}")

    # Vanilla-Ausschlussgruppen (Amboss/Zaubertisch-Regeln, Minecraft Wiki):
    # rein informativ für UI-Hinweise; NBT-Kombinationen bleiben speicherbar.
    exclusive_groups: list[list[int]] = []
    for group in raw.get("exclusive_groups", []):
        if not isinstance(group, list) or len(group) < 2:
            raise ValueError("Enchantment-Kompatibilität exclusive_groups braucht Listen mit mindestens 2 IDs.")
        try:
            ids = sorted({int(value) for value in group})
        except (TypeError, ValueError) as exc:
            raise ValueError("Enchantment-Kompatibilität exclusive_groups enthält ungültige IDs.") from exc
        unknown_ids = sorted(set(ids) - set(compatible_slots))
        if unknown_ids:
            raise ValueError(f"Enchantment-Kompatibilität exclusive_groups referenziert unbekannte Verzauberungs-IDs: {unknown_ids}")
        exclusive_groups.append(ids)

    return {
        "schema_version": int(raw.get("schema_version", 1)),
        "sources": [str(value) for value in raw.get("sources", [])],
        "compatible_slots": compatible_slots,
        "slot_groups": slot_groups,
        "item_slots": item_slots,
        "item_slot_suffixes": item_slot_suffixes,
        "exclusive_groups": exclusive_groups,
        "source_path": str(source_path),
    }


def _as_text_pair(value: Any, *, key: str) -> tuple[str, str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"Ungültiger Item-DB-Eintrag für {key}: erwartet [de, en].")
    return (str(value[0] or ""), str(value[1] or ""))


def _as_effect(value: Any, *, key: str) -> tuple[str, str, str, str]:
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        raise ValueError(f"Ungültiger Effekt-DB-Eintrag für {key}: erwartet [de, en, description_de?, description_en].")
    de_name = str(value[0] or "")
    en_name = str(value[1] or "")
    if len(value) == 3:
        # Schema 1 enthielt nur eine englische Beschreibung.
        return (de_name, en_name, "", str(value[2] or ""))
    return (de_name, en_name, str(value[2] or ""), str(value[3] or ""))


def _validated_item_components(raw: Any, slot_groups: dict[str, set[str]]) -> dict[str, dict[str, dict[str, Any]]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Item-DB-Abschnitt item_components muss ein Objekt sein.")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for component_name in ("enchantable", "wearable", "allow_off_hand"):
        component_map = raw.get(component_name, {})
        if not isinstance(component_map, dict):
            raise ValueError(f"Item-DB-Abschnitt item_components.{component_name} muss ein Objekt sein.")
        normalized: dict[str, dict[str, Any]] = {}
        for raw_item_id, raw_component in component_map.items():
            item_id = str(raw_item_id or "").strip().lower()
            if not item_id or ":" not in item_id or not isinstance(raw_component, dict):
                raise ValueError(f"Ungültiger Item-Komponenten-Eintrag: item_components.{component_name}.{raw_item_id}")
            component = dict(raw_component)
            label = f"item_components.{component_name}.{item_id}"
            if component_name == "enchantable":
                slot = str(component.get("slot", "")).strip()
                known_slots = {"none", *slot_groups}
                for slots in slot_groups.values():
                    known_slots.update(slots)
                if slot not in known_slots or type(component.get("value")) is not int:
                    raise ValueError(f"Ungültige Verzauberbarkeits-Komponente: {label}")
            elif component_name == "allow_off_hand":
                if type(component.get("value")) is not bool:
                    raise ValueError(f"Ungültige Nebenhand-Komponente: {label}")
            elif component_name == "wearable":
                if str(component.get("slot", "")).strip() not in {
                    "slot.armor.body",
                    "slot.armor.chest",
                    "slot.armor.feet",
                    "slot.armor.head",
                    "slot.armor.legs",
                    "slot.weapon.mainhand",
                    "slot.weapon.offhand",
                }:
                    raise ValueError(f"Ungültige Tragbar-Komponente: {label}")
            normalized[item_id] = component
        result[component_name] = normalized
    return result


def _merge_versioned_limits(
    persistent_values: dict[str, int],
    persistent_source_ids: frozenset[str],
    bundled_values: dict[str, int],
    bundled_source_ids: frozenset[str],
    *,
    use_persistent_source: bool,
) -> dict[str, int]:
    persistent_manual = {item_id: value for item_id, value in persistent_values.items() if item_id not in persistent_source_ids}
    bundled_curated = {item_id: value for item_id, value in bundled_values.items() if item_id not in bundled_source_ids}
    selected_values = persistent_values if use_persistent_source else bundled_values
    selected_ids = persistent_source_ids if use_persistent_source else bundled_source_ids
    selected_source = {item_id: selected_values[item_id] for item_id in selected_ids if item_id in selected_values}
    return {**persistent_manual, **bundled_curated, **selected_source}


def _as_enchantment(value: Any, *, key: str) -> tuple[str, str, int, str] | tuple[str, str, int]:
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        raise ValueError(f"Ungültiger Verzauberungs-DB-Eintrag für {key}: erwartet [de, en, max_level, description?].")
    de = str(value[0] or "")
    en = str(value[1] or "")
    level = int(value[2])
    if len(value) == 4 and value[3]:
        return (de, en, level, str(value[3]))
    return (de, en, level)


def _int_keyed_dict(raw: Any, converter) -> dict[int, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Item-DB-Abschnitt muss ein Objekt sein.")
    result: dict[int, Any] = {}
    for key, value in raw.items():
        result[int(key)] = converter(value, key=str(key))
    return result


def _str_int_dict(raw: Any, *, label: str) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError(f"Item-DB-Abschnitt {label} muss ein Objekt sein.")
    result: dict[str, int] = {}
    for key, value in raw.items():
        if label == "stack_limits" and (type(value) is not int or not 1 <= value <= 127):
            raise ValueError(f"Ungültiges Stacklimit für {key}: erwartet Ganzzahl zwischen 1 und 127.")
        result[str(key)] = int(value)
    return result


def _str_str_dict(raw: Any, *, label: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"Item-DB-Abschnitt {label} muss ein Objekt sein.")
    result: dict[str, str] = {}
    for key, value in raw.items():
        source = str(key).strip().lower()
        target = str(value).strip().lower()
        if source and target:
            result[source] = target
    return result


def _looks_like_fallback_pair(pair: tuple[str, str]) -> bool:
    de, en = (str(pair[0] or "").strip(), str(pair[1] or "").strip())
    return not de or de == en


def _apply_bundled_curation(
    db: dict[str, Any],
    bundled: dict[str, Any],
    *,
    has_explicit_addable_items: bool,
    confirmed_labels: dict | None = None,
) -> None:
    """Übernimmt kuratierte Korrekturen der gebündelten Item-DB in eine geladene Kopie.

    Ältere persistente Kopien können Pseudo-IDs wie minecraft:glazedterracottablack
    (Lokalisierungsschlüssel, keine gültigen Bedrock-Item-IDs) enthalten.
    Beim Laden gilt deshalb:
    gebündelte Aliasse gewinnen, wegkuratierte Items werden ausgeblendet,
    fehlende gebündelte Items ergänzt und Fallback-Labels (de == en) sowie
    exakt bekannte Fehl-Labels durch gebündelte Übersetzungen ersetzt.
    Kuratierte Stackgrenzen gelten ebenfalls
    für persistente Altstände, damit der Editor keine in Vanilla unzulässigen
    Stacks erzeugt. Dasselbe gilt für Haltbarkeitswerte, weil fehlende Einträge
    normales tag.Damage sonst fälschlich als geschützte Zusatz-NBT einstufen.
    Kuratierte Effektbeschreibungen ersetzen außerdem die nicht lokalisierten
    Texte aus Schema 1, ohne lokal aktualisierte Effektnamen zurückzusetzen.
    Geprüfte numerische Verzauberungs-IDs werden übernommen, während lokal
    aktuellere Namen und Beschreibungen erhalten bleiben.
    """
    bundled_items = bundled["ITEMS"]
    aliases = {**db["COMPAT_ITEM_ALIASES"], **bundled["COMPAT_ITEM_ALIASES"]}
    items: dict[str, tuple[str, str]] = db["ITEMS"]
    for source in aliases:
        if source in items and source not in bundled_items:
            del items[source]
    repairs = reviewed_item_label_repairs(items, bundled_items)
    for item_id, bundled_pair in bundled_items.items():
        current = items.get(item_id)
        if current and confirmed_labels and confirmed_item_label_pair(confirmed_labels.get(item_id)):
            continue
        if (
            item_id in repairs
            or current is None
            or (
                not has_explicit_addable_items
                and _looks_like_fallback_pair(current)
                and current[1] == bundled_pair[1]
                and not _looks_like_fallback_pair(bundled_pair)
            )
        ):
            items[item_id] = bundled_pair
    for section in ("effects", "enchantments"):
        try:
            db[section.upper()] = reconcile_numeric_catalog(db[section.upper()], bundled[section.upper()], kind=section)
        except NumericCatalogConflictError as exc:
            # Keep the original section and file intact. A semantic conflict
            # must not invoke whole-file corruption recovery or block its peers.
            db["ITEM_DB_CONFLICTS"][section] = exc.details()
            LOGGER.warning("Item-DB-Bereich %s gesperrt: %s IDs: %s", section, exc, exc.ids)
    bundled_behavior_source = bundled["BEHAVIOR_ITEM_SOURCE"]
    persistent_behavior_source = db["BEHAVIOR_ITEM_SOURCE"]
    persistent_release = release_version_key(persistent_behavior_source["resource_pack_release"])
    bundled_release = release_version_key(bundled_behavior_source["resource_pack_release"])
    use_persistent_source = persistent_release > bundled_release
    db["COMPAT_ITEM_ALIASES"] = aliases
    db["STACK_LIMITS"] = _merge_versioned_limits(
        db["STACK_LIMITS"],
        persistent_behavior_source["stack_limit_items"],
        bundled["STACK_LIMITS"],
        bundled_behavior_source["stack_limit_items"],
        use_persistent_source=use_persistent_source,
    )
    db["DURABILITY"] = _merge_versioned_limits(
        db["DURABILITY"],
        persistent_behavior_source["durability_items"],
        bundled["DURABILITY"],
        bundled_behavior_source["durability_items"],
        use_persistent_source=use_persistent_source,
    )
    if use_persistent_source:
        db["BEHAVIOR_ITEM_SOURCE"] = persistent_behavior_source
    elif persistent_release and bundled_release:
        db["ITEM_COMPONENTS"] = bundled["ITEM_COMPONENTS"]
        db["BEHAVIOR_ITEM_SOURCE"] = bundled_behavior_source
    else:
        # Unversionierte externe Datenbanken bleiben migrationsfreundlich:
        # gebündelte Korrekturen gewinnen, unbekannte lokale Ergänzungen bleiben.
        db["ITEM_COMPONENTS"] = {
            component: {
                **db["ITEM_COMPONENTS"].get(component, {}),
                **bundled["ITEM_COMPONENTS"].get(component, {}),
            }
            for component in ("enchantable", "wearable", "allow_off_hand")
        }
        db["BEHAVIOR_ITEM_SOURCE"] = bundled_behavior_source
    apply_reviewed_registry(db, bundled, newer_positive_registry=use_persistent_source and has_explicit_addable_items)
    db["SCHEMA_VERSION"] = max(int(db["SCHEMA_VERSION"]), bundled["SCHEMA_VERSION"])


def _parse_catalog_file(path: Path, slot_groups: dict[str, set[str]], *, allow_legacy_fallback: bool) -> tuple[dict[str, Any], dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise InvalidItemDatabaseError("Item-DB JSON muss ein Objekt sein.")

        defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
        items_raw = raw.get("items")
        if not isinstance(items_raw, dict):
            raise InvalidItemDatabaseError("Item-DB-Abschnitt items muss ein Objekt sein.")

        # The updater only adds entries, so tooltip keys that older catalogs
        # took for items leave persistent copies only here.
        items = {str(key): _as_text_pair(value, key=str(key)) for key, value in items_raw.items() if not is_non_item_lang_key_id(str(key))}
        db = {
            # Old databases advertise a blanket 64. A missing per-item value
            # must never regain that assumption through a persistent copy.
            "DEFAULT_MAX_STACK": DEFAULT_MAX_STACK,
            "DEFAULT_MAX_DAMAGE": int(defaults.get("max_damage", 1561)),
            "MAX_DATA_VALUE": int(defaults.get("max_data_value", 32767)),
            "STACK_LIMITS": _str_int_dict(raw.get("stack_limits", {}), label="stack_limits"),
            "DURABILITY": _str_int_dict(raw.get("durability", {}), label="durability"),
            "ITEM_COMPONENTS": _validated_item_components(raw.get("item_components", {}), slot_groups),
            "BEHAVIOR_ITEM_SOURCE": validated_behavior_item_source(raw.get("behavior_item_source", {})),
            "ITEMS": items,
            "COMPAT_ITEM_ALIASES": _str_str_dict(raw.get("compat_item_aliases", {}), label="compat_item_aliases"),
            **catalog_registry(raw, allow_legacy_fallback=allow_legacy_fallback),
            "EFFECTS": _int_keyed_dict(raw.get("effects", {}), _as_effect),
            "ENCHANTMENTS": _int_keyed_dict(raw.get("enchantments", {}), _as_enchantment),
            "ITEM_DB_CONFLICTS": {},
            "SOURCE_PATH": str(path),
            "SCHEMA_VERSION": int(raw.get("schema_version", 1)),
        }
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, InvalidItemDatabaseError):
            raise
        raise InvalidItemDatabaseError(f"Item-DB JSON ist ungültig: {path}") from exc

    return db, raw


def read_catalog_file(path: Path, *, bundled_path: Path, slot_groups: dict[str, set[str]] | None = None) -> dict[str, Any]:
    """Validate the requested file and apply bundled curation to that same snapshot."""
    if slot_groups is None:
        slot_groups = load_enchantment_compatibility()["slot_groups"]
    db, raw = _parse_catalog_file(path, slot_groups, allow_legacy_fallback=True)
    if path.resolve() != bundled_path.resolve():
        bundled, _ = _parse_catalog_file(bundled_path, slot_groups, allow_legacy_fallback=False)
        _apply_bundled_curation(
            db,
            bundled,
            has_explicit_addable_items="addable_items" in raw,
            confirmed_labels=raw.get("confirmed_item_labels") if isinstance(raw.get("confirmed_item_labels"), dict) else None,
        )
    return db
