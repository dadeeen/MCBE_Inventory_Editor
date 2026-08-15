from __future__ import annotations

import json
import logging
import os
import re
import secrets
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcbe_editor.item_registry_policy import is_technical_block_only_item_id
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON, atomic_seed_file
from mcbe_editor.world_locks import locked_operation

DEFAULT_MAX_STACK = 64
DEFAULT_MAX_DAMAGE = 1561
MAX_DATA_VALUE = 32767

BUNDLED_ENCHANTMENT_COMPATIBILITY_JSON = Path(__file__).with_name("enchantment_compatibility.json")
LOGGER = logging.getLogger(__name__)


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


def _client_slot_map(raw: dict[str, set[str]]) -> dict[str, list[str]]:
    return {key: sorted(value) for key, value in raw.items()}


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


_ENCHANTMENT_COMPATIBILITY_DATA = load_enchantment_compatibility()
ENCHANTMENT_COMPATIBILITY_SCHEMA_VERSION = _ENCHANTMENT_COMPATIBILITY_DATA["schema_version"]
ENCHANTMENT_COMPATIBILITY_SOURCES = _ENCHANTMENT_COMPATIBILITY_DATA["sources"]
ENCHANTMENT_COMPATIBILITY_SOURCE_PATH = _ENCHANTMENT_COMPATIBILITY_DATA["source_path"]
ENCHANTMENT_COMPATIBLE_SLOTS: dict[int, set[str]] = _ENCHANTMENT_COMPATIBILITY_DATA["compatible_slots"]
ENCHANTMENT_SLOT_GROUPS: dict[str, set[str]] = _ENCHANTMENT_COMPATIBILITY_DATA["slot_groups"]
ENCHANTMENT_ITEM_SLOTS: dict[str, set[str]] = _ENCHANTMENT_COMPATIBILITY_DATA["item_slots"]
ENCHANTMENT_ITEM_SLOT_SUFFIXES: tuple[tuple[str, str], ...] = _ENCHANTMENT_COMPATIBILITY_DATA["item_slot_suffixes"]
ENCHANTMENT_EXCLUSIVE_GROUPS: list[list[int]] = _ENCHANTMENT_COMPATIBILITY_DATA["exclusive_groups"]
OFFICIAL_ENCHANTMENT_ITEM_SLOTS: dict[str, set[str]] = {}
ENCHANTMENT_COMPATIBILITY: dict[str, Any] = {
    "schema_version": ENCHANTMENT_COMPATIBILITY_SCHEMA_VERSION,
    "sources": ENCHANTMENT_COMPATIBILITY_SOURCES,
    "compatible_slots": {str(key): sorted(value) for key, value in ENCHANTMENT_COMPATIBLE_SLOTS.items()},
    "slot_groups": _client_slot_map(ENCHANTMENT_SLOT_GROUPS),
    "item_slots": _client_slot_map(ENCHANTMENT_ITEM_SLOTS),
    "official_item_slots": {},
    "item_slot_suffixes": [list(entry) for entry in ENCHANTMENT_ITEM_SLOT_SUFFIXES],
    "exclusive_groups": ENCHANTMENT_EXCLUSIVE_GROUPS,
}

STACK_LIMITS: dict[str, int] = {}
DURABILITY: dict[str, int] = {}
# Nur Komponenten, die im Editor tatsächlich eine Entscheidung treffen:
# ``enchantable`` bestimmt die Verzauberungs-Kompatibilität, ``wearable`` die
# Rüstungsslots. Weitere Mojang-Komponenten werden bewusst nicht mitgeführt —
# unbenutzte Daten mit fail-closed-Validierung können nur schaden (eine
# unbekannte Formänderung quarantäniert die persistente DB des Nutzers).
ITEM_COMPONENTS: dict[str, dict[str, dict[str, Any]]] = {
    "enchantable": {},
    "wearable": {},
}
ITEMS: dict[str, tuple[str, str]] = {}
EFFECTS: dict[int, tuple[str, str, str, str]] = {}
ENCHANTMENTS: dict[int, tuple[str, str, int, str] | tuple[str, str, int]] = {}
COMPAT_ITEM_ALIASES: dict[str, str] = {}
BLOCK_ONLY_ITEM_IDS: frozenset[str] = frozenset()
BLOCK_ITEM_IDS: frozenset[str] = frozenset()
ADDABLE_ITEM_IDS: frozenset[str] = frozenset()
UNREVIEWED_ITEM_IDS: frozenset[str] = frozenset()
ITEM_DB_SOURCE_PATH = str(BUNDLED_ITEM_DB_JSON)
ITEM_DB_SCHEMA_VERSION = 3


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


def _validated_item_components(raw: Any) -> dict[str, dict[str, dict[str, Any]]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Item-DB-Abschnitt item_components muss ein Objekt sein.")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for component_name in ITEM_COMPONENTS:
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
                known_slots = {"none", *ENCHANTMENT_SLOT_GROUPS}
                for slots in ENCHANTMENT_SLOT_GROUPS.values():
                    known_slots.update(slots)
                if slot not in known_slots or type(component.get("value")) is not int:
                    raise ValueError(f"Ungültige Verzauberbarkeits-Komponente: {label}")
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


def _validated_behavior_item_source(raw: Any) -> dict[str, Any]:
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


def _release_version_key(value: Any) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)+)", str(value or "").strip(), flags=re.IGNORECASE)
    if not match:
        return ()
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


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
        result[str(key)] = int(value)
    return result


def _item_id_set(raw: Any) -> frozenset[str]:
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(entry).strip().lower() for entry in raw if str(entry or "").strip())


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


def resolve_item_db_json_path(path: str | os.PathLike | None = None) -> Path:
    candidate = Path(path or os.environ.get("MCBE_ITEM_DB_PATH") or BUNDLED_ITEM_DB_JSON).expanduser()
    if candidate.suffix.lower() != ".json":
        raise ValueError(f"Item-DB muss eine JSON-Datei sein: {candidate}")
    return candidate


# Persistente Kopien (z. B. data/item_db.json) bekommen vom Updater nur Ergänzungen,
# nie kuratierte Korrekturen. Für Labels, die früher falsch ausgeliefert wurden und
# nicht als Fallback (de == en) erkennbar sind, gilt: exakt bekannter Altstand -> Neuwert.
LEGACY_ITEM_LABEL_FIXES: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    # Der Legacy-Block minecraft:stonecutter war identisch zur funktionalen
    # minecraft:stonecutter_block beschriftet; im Spiel ist er ohne Funktion.
    "minecraft:stonecutter": (
        ("Steinsäge", "Stonecutter"),
        ("Steinsäge (alt, ohne Funktion)", "Stonecutter (Legacy, No Function)"),
    ),
}


def _looks_like_fallback_pair(pair: tuple[str, str]) -> bool:
    de, en = (str(pair[0] or "").strip(), str(pair[1] or "").strip())
    return not de or de == en


def _apply_bundled_curation(
    db: dict[str, Any],
    *,
    has_explicit_addable_items: bool,
) -> None:
    """Übernimmt kuratierte Korrekturen der gebündelten Item-DB in eine geladene Kopie.

    Der Updater ergänzt persistente Kopien nur (merge), entfernt aber nie Einträge
    und überschreibt keine Aliasse. Pseudo-IDs wie minecraft:glazedterracottablack
    (Lokalisierungsschlüssel, keine gültigen Bedrock-Item-IDs) blieben dadurch in
    Bestandsinstallationen dauerhaft im Katalog. Beim Laden gilt deshalb:
    gebündelte Aliasse gewinnen, wegkuratierte Items werden ausgeblendet,
    fehlende gebündelte Items ergänzt und Fallback-Labels (de == en) durch
    gebündelte Übersetzungen ersetzt. Kuratierte Stackgrenzen gelten ebenfalls
    für persistente Altstände, damit der Editor keine in Vanilla unzulässigen
    Stacks erzeugt. Dasselbe gilt für Haltbarkeitswerte, weil fehlende Einträge
    normales tag.Damage sonst fälschlich als geschützte Zusatz-NBT einstufen.
    Kuratierte Effektbeschreibungen ersetzen außerdem die nicht lokalisierten
    Texte aus Schema 1, ohne lokal aktualisierte Effektnamen zurückzusetzen.
    Geprüfte numerische Verzauberungs-IDs werden übernommen, während lokal
    aktuellere Namen und Beschreibungen erhalten bleiben.
    """
    try:
        bundled_raw = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
        bundled_items = {str(key): _as_text_pair(value, key=str(key)) for key, value in (bundled_raw.get("items") or {}).items()}
        bundled_effects = _int_keyed_dict(bundled_raw.get("effects", {}), _as_effect)
        bundled_enchantments = _int_keyed_dict(bundled_raw.get("enchantments", {}), _as_enchantment)
        bundled_stack_limits = _str_int_dict(bundled_raw.get("stack_limits", {}), label="stack_limits")
        bundled_durability = _str_int_dict(bundled_raw.get("durability", {}), label="durability")
        bundled_item_components = _validated_item_components(bundled_raw.get("item_components", {}))
        bundled_behavior_source = _validated_behavior_item_source(bundled_raw.get("behavior_item_source", {}))
        bundled_aliases = _str_str_dict(bundled_raw.get("compat_item_aliases", {}), label="compat_item_aliases")
        bundled_block_only = _item_id_set(bundled_raw.get("block_only_items"))
        bundled_block_items = _item_id_set(bundled_raw.get("block_items"))
        bundled_addable_items = _item_id_set(bundled_raw.get("addable_items"))
        bundled_technical_ids = frozenset(
            item_id for item_id in bundled_addable_items if is_technical_block_only_item_id(item_id)
        )
        bundled_block_only = frozenset(bundled_block_only | bundled_technical_ids)
        bundled_addable_items = frozenset(bundled_addable_items - bundled_technical_ids)
    except (OSError, ValueError):
        return

    aliases: dict[str, str] = {**db["COMPAT_ITEM_ALIASES"], **bundled_aliases}
    items: dict[str, tuple[str, str]] = db["ITEMS"]
    for source in aliases:
        if source in items and source not in bundled_items:
            del items[source]
    for item_id, bundled_pair in bundled_items.items():
        current = items.get(item_id)
        if current is None or (_looks_like_fallback_pair(current) and not _looks_like_fallback_pair(bundled_pair)):
            items[item_id] = bundled_pair
    for item_id, (old_pair, new_pair) in LEGACY_ITEM_LABEL_FIXES.items():
        if items.get(item_id) == old_pair:
            items[item_id] = new_pair
    effects: dict[int, tuple[str, str, str, str]] = db["EFFECTS"]
    current_effects_by_name = {str(values[1] or "").strip().casefold(): values for values in effects.values()}
    bundled_effect_names = {str(values[1] or "").strip().casefold(): effect_id for effect_id, values in bundled_effects.items()}
    for effect_id, values in list(effects.items()):
        reviewed_id = bundled_effect_names.get(str(values[1] or "").strip().casefold())
        if reviewed_id is not None and reviewed_id != effect_id:
            del effects[effect_id]
    for effect_id, bundled_effect in bundled_effects.items():
        name = str(bundled_effect[1] or "").strip().casefold()
        current = current_effects_by_name.get(name) or effects.get(effect_id)
        effects[effect_id] = (*current[:2], *bundled_effect[2:]) if current else bundled_effect
    enchantments: dict[int, tuple[str, str, int, str] | tuple[str, str, int]] = db["ENCHANTMENTS"]
    current_enchantments_by_name = {str(values[1] or "").strip().casefold(): values for values in enchantments.values()}
    bundled_enchantment_names = {str(values[1] or "").strip().casefold(): enchantment_id for enchantment_id, values in bundled_enchantments.items()}
    for enchantment_id, values in list(enchantments.items()):
        reviewed_id = bundled_enchantment_names.get(str(values[1] or "").strip().casefold())
        if reviewed_id is not None and reviewed_id != enchantment_id:
            del enchantments[enchantment_id]
    for enchantment_id, bundled_values in bundled_enchantments.items():
        name = str(bundled_values[1] or "").strip().casefold()
        enchantments[enchantment_id] = current_enchantments_by_name.get(name, bundled_values)
    persistent_behavior_source = db["BEHAVIOR_ITEM_SOURCE"]
    persistent_release = _release_version_key(persistent_behavior_source["resource_pack_release"])
    bundled_release = _release_version_key(bundled_behavior_source["resource_pack_release"])
    use_persistent_source = bool(persistent_release) and (not bundled_release or persistent_release > bundled_release)
    db["COMPAT_ITEM_ALIASES"] = aliases
    db["STACK_LIMITS"] = _merge_versioned_limits(
        db["STACK_LIMITS"],
        persistent_behavior_source["stack_limit_items"],
        bundled_stack_limits,
        bundled_behavior_source["stack_limit_items"],
        use_persistent_source=use_persistent_source,
    )
    db["DURABILITY"] = _merge_versioned_limits(
        db["DURABILITY"],
        persistent_behavior_source["durability_items"],
        bundled_durability,
        bundled_behavior_source["durability_items"],
        use_persistent_source=use_persistent_source,
    )
    if use_persistent_source:
        db["BEHAVIOR_ITEM_SOURCE"] = persistent_behavior_source
    elif persistent_release and bundled_release:
        db["ITEM_COMPONENTS"] = bundled_item_components
        db["BEHAVIOR_ITEM_SOURCE"] = bundled_behavior_source
    else:
        # Unversionierte externe Datenbanken bleiben migrationsfreundlich:
        # gebündelte Korrekturen gewinnen, unbekannte lokale Ergänzungen bleiben.
        db["ITEM_COMPONENTS"] = {
            component: {
                **db["ITEM_COMPONENTS"].get(component, {}),
                **bundled_item_components.get(component, {}),
            }
            for component in ITEM_COMPONENTS
        }
        db["BEHAVIOR_ITEM_SOURCE"] = bundled_behavior_source
    db["BLOCK_ONLY_ITEM_IDS"] = frozenset(db["BLOCK_ONLY_ITEM_IDS"] | bundled_block_only)
    db["BLOCK_ITEM_IDS"] = frozenset(db["BLOCK_ITEM_IDS"] | bundled_block_items)
    if bundled_addable_items:
        if use_persistent_source and has_explicit_addable_items:
            # Eine neuere offizielle Registry gewinnt vollständig. Eine Union
            # wäre falsch, weil Mojang IDs auch wieder entfernen kann.
            db["UNREVIEWED_ITEM_IDS"] = frozenset(db["ADDABLE_ITEM_IDS"] - bundled_addable_items)
        else:
            # Gleiche, ältere, unversionierte oder nur heuristisch abgeleitete
            # externe Daten bleiben auf dem geprüften Registry-Stand. Eine
            # Versionsangabe allein macht den Legacy-Fallback nicht autoritativ.
            db["ADDABLE_ITEM_IDS"] = bundled_addable_items
            db["UNREVIEWED_ITEM_IDS"] = frozenset()
    db["SCHEMA_VERSION"] = max(int(db["SCHEMA_VERSION"]), int(bundled_raw.get("schema_version", 1)))


def _load_item_database_file(item_db_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(item_db_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise InvalidItemDatabaseError("Item-DB JSON muss ein Objekt sein.")

        defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
        items_raw = raw.get("items", {})
        if not isinstance(items_raw, dict):
            raise InvalidItemDatabaseError("Item-DB-Abschnitt items muss ein Objekt sein.")

        items = {str(key): _as_text_pair(value, key=str(key)) for key, value in items_raw.items()}
        block_only_item_ids = _item_id_set(raw.get("block_only_items"))
        addable_items_raw = raw.get("addable_items")
        has_explicit_addable_items = isinstance(addable_items_raw, list)
        addable_item_ids = _item_id_set(addable_items_raw)
        if not has_explicit_addable_items:
            # Kompatibilitätsfallback für ältere externe Datenbanken. Die
            # gebündelte Kuration ersetzt ihn anschließend durch die offizielle
            # positive Registry, sofern eine persistente Kopie geladen wird.
            addable_item_ids = frozenset(set(items) - set(block_only_item_ids))
        technical_item_ids = frozenset(
            item_id for item_id in addable_item_ids if is_technical_block_only_item_id(item_id)
        )
        block_only_item_ids = frozenset(block_only_item_ids | technical_item_ids)
        addable_item_ids = frozenset(addable_item_ids - technical_item_ids)

        db = {
            "DEFAULT_MAX_STACK": int(defaults.get("max_stack", DEFAULT_MAX_STACK)),
            "DEFAULT_MAX_DAMAGE": int(defaults.get("max_damage", DEFAULT_MAX_DAMAGE)),
            "MAX_DATA_VALUE": int(defaults.get("max_data_value", MAX_DATA_VALUE)),
            "STACK_LIMITS": _str_int_dict(raw.get("stack_limits", {}), label="stack_limits"),
            "DURABILITY": _str_int_dict(raw.get("durability", {}), label="durability"),
            "ITEM_COMPONENTS": _validated_item_components(raw.get("item_components", {})),
            "BEHAVIOR_ITEM_SOURCE": _validated_behavior_item_source(raw.get("behavior_item_source", {})),
            "ITEMS": items,
            "COMPAT_ITEM_ALIASES": _str_str_dict(raw.get("compat_item_aliases", {}), label="compat_item_aliases"),
            "BLOCK_ONLY_ITEM_IDS": block_only_item_ids,
            "BLOCK_ITEM_IDS": _item_id_set(raw.get("block_items")),
            "ADDABLE_ITEM_IDS": addable_item_ids,
            "UNREVIEWED_ITEM_IDS": frozenset(),
            "EFFECTS": _int_keyed_dict(raw.get("effects", {}), _as_effect),
            "ENCHANTMENTS": _int_keyed_dict(raw.get("enchantments", {}), _as_enchantment),
            "SOURCE_PATH": str(item_db_path),
            "SCHEMA_VERSION": int(raw.get("schema_version", 1)),
        }
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, InvalidItemDatabaseError):
            raise
        raise InvalidItemDatabaseError(f"Item-DB JSON ist ungültig: {item_db_path}") from exc

    if item_db_path.resolve() != BUNDLED_ITEM_DB_JSON.resolve():
        _apply_bundled_curation(
            db,
            has_explicit_addable_items=has_explicit_addable_items,
        )
    return db


def _quarantine_path(item_db_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    token = secrets.token_hex(8)
    return item_db_path.with_name(f"{item_db_path.stem}.invalid-{timestamp}-{token}{item_db_path.suffix}")


def _recover_configured_item_database(item_db_path: Path) -> dict[str, Any]:
    # Validate the immutable fallback before touching the user's persistent file.
    _load_item_database_file(BUNDLED_ITEM_DB_JSON)
    with locked_operation("item-db-recovery", root=item_db_path.parent):
        try:
            return _load_item_database_file(item_db_path)
        except FileNotFoundError:
            atomic_seed_file(BUNDLED_ITEM_DB_JSON, item_db_path)
            return _load_item_database_file(item_db_path)
        except InvalidItemDatabaseError:
            quarantine = _quarantine_path(item_db_path)
            os.replace(item_db_path, quarantine)
            try:
                atomic_seed_file(BUNDLED_ITEM_DB_JSON, item_db_path)
                recovered = _load_item_database_file(item_db_path)
            except BaseException:
                item_db_path.unlink(missing_ok=True)
                os.replace(quarantine, item_db_path)
                raise
            LOGGER.warning(
                "Ungültige persistente Item-DB wurde gesichert und aus der gebündelten Datenbank neu erstellt: source=%s quarantine=%s",
                item_db_path,
                quarantine,
            )
            return recovered


def load_item_database(path: str | os.PathLike | None = None) -> dict[str, Any]:
    item_db_path = resolve_item_db_json_path(path)
    configured_recovery = path is None and bool(os.environ.get("MCBE_ITEM_DB_PATH"))
    is_persistent = item_db_path.resolve() != BUNDLED_ITEM_DB_JSON.resolve()
    if configured_recovery and is_persistent:
        # Keep existence checks and the initial read inside the same lock as
        # recovery. A concurrent recovery briefly moves the invalid file away;
        # observing that gap here must not fall back to the bundled DB.
        return _recover_configured_item_database(item_db_path)
    if not item_db_path.exists():
        item_db_path = BUNDLED_ITEM_DB_JSON
    try:
        return _load_item_database_file(item_db_path)
    except InvalidItemDatabaseError:
        if configured_recovery and is_persistent:
            return _recover_configured_item_database(item_db_path)
        raise


def database_as_module_globals(path: str | os.PathLike | None = None) -> dict[str, Any]:
    db = load_item_database(path)
    return {
        "DEFAULT_MAX_STACK": db["DEFAULT_MAX_STACK"],
        "DEFAULT_MAX_DAMAGE": db["DEFAULT_MAX_DAMAGE"],
        "MAX_DATA_VALUE": db["MAX_DATA_VALUE"],
        "STACK_LIMITS": db["STACK_LIMITS"],
        "DURABILITY": db["DURABILITY"],
        "ITEM_COMPONENTS": db["ITEM_COMPONENTS"],
        "ITEMS": db["ITEMS"],
        "EFFECTS": db["EFFECTS"],
        "ENCHANTMENTS": db["ENCHANTMENTS"],
        "COMPAT_ITEM_ALIASES": db["COMPAT_ITEM_ALIASES"],
        "BLOCK_ONLY_ITEM_IDS": db["BLOCK_ONLY_ITEM_IDS"],
        "BLOCK_ITEM_IDS": db["BLOCK_ITEM_IDS"],
        "ADDABLE_ITEM_IDS": db["ADDABLE_ITEM_IDS"],
        "UNREVIEWED_ITEM_IDS": db["UNREVIEWED_ITEM_IDS"],
        "ITEM_DB_SOURCE_PATH": db["SOURCE_PATH"],
        "ITEM_DB_SCHEMA_VERSION": db["SCHEMA_VERSION"],
    }


def reload_item_database(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Reload JSON item data into module globals and return the loaded DB.

    The application imports item data from this module directly. The updater only
    writes JSON and then calls this function/reloads dependent modules.
    """

    db_globals = database_as_module_globals(path)
    globals().update(db_globals)
    _refresh_component_derived_data()
    return db_globals


def canonical_item_id(item_name: str) -> str:
    normalized = str(item_name or "").strip().lower()
    return COMPAT_ITEM_ALIASES.get(normalized, normalized)


def fallback_item_display_names(item_name: str) -> tuple[str, str]:
    """Return a readable locale-neutral label for an official registry ID.

    Experimental registry additions can precede Mojang's public ``.lang`` and
    Microsoft Learn name catalogs.  The identifier is still authoritative for
    creating the item; a missing translation must not make it disappear from
    the browser.  Matching German and English fallback labels are intentional:
    a later official localization is allowed to replace such pairs.
    """

    normalized = str(item_name or "").strip().lower()
    short_name = normalized.partition(":")[2] or normalized
    label = re.sub(r"[_./-]+", " ", short_name).strip().title()
    label = label or normalized
    return (label, label)


def selectable_item_catalog(
    items: dict[str, tuple[str, str]] | None = None,
    *,
    addable_item_ids: Collection[str] | None = None,
    block_only_item_ids: Collection[str] | None = None,
    compat_item_aliases: dict[str, str] | None = None,
) -> dict[str, tuple[str, str]]:
    """Return readable entries for all recognized runtime item identifiers.

    ``ITEMS`` is the display-name catalog, while ``ADDABLE_ITEM_IDS`` is
    Mojang's positive item registry.  A newer registry may contain IDs whose
    translations have not reached the public language catalogs yet.  Runtime
    consumers need one complete view without changing item_db v3 or persisting
    guessed translations. Technical ``BLOCK_ONLY_ITEM_IDS`` are included so an
    existing item remains recognizable, but selection and new-item creation
    continue to be governed exclusively by ``ADDABLE_ITEM_IDS``.
    """

    source_items = ITEMS if items is None else items
    source_addable = ADDABLE_ITEM_IDS if addable_item_ids is None else addable_item_ids
    source_block_only = BLOCK_ONLY_ITEM_IDS if block_only_item_ids is None else block_only_item_ids
    source_aliases = COMPAT_ITEM_ALIASES if compat_item_aliases is None else compat_item_aliases
    result = dict(source_items)
    recognized_runtime_ids = {
        str(value or "").strip().lower()
        for collection in (source_addable, source_block_only)
        for value in collection
    }
    for item_id in sorted(recognized_runtime_ids):
        if not item_id or item_id in result:
            continue
        alias_target = source_aliases.get(item_id)
        result[item_id] = result.get(alias_target) or fallback_item_display_names(item_id)
    return result


def is_known_item_id(item_name: str) -> bool:
    normalized = str(item_name or "").strip().lower()
    return normalized in ITEMS or normalized in COMPAT_ITEM_ALIASES or normalized in ADDABLE_ITEM_IDS or normalized in BLOCK_ONLY_ITEM_IDS


def is_block_only_item_id(item_name: str) -> bool:
    """True für Katalog-IDs, die nur als technische Blockzustände nutzbar sind."""
    return str(item_name or "").strip().lower() in BLOCK_ONLY_ITEM_IDS


def is_block_item_id(item_name: str) -> bool:
    """True für registry-abgeleitete, im Browser als Block geeignete Items."""
    return str(item_name or "").strip().lower() in BLOCK_ITEM_IDS


def is_addable_item_id(item_name: str) -> bool:
    """True nur für nichttechnische IDs aus Mojangs positiver Item-Registry.

    Das ist absichtlich enger als ``is_known_item_id``: bekannte Legacy-,
    Block- und Add-on-IDs werden weiterhin gelesen und erhalten, aber nicht als
    neue Vanilla-Items angeboten oder frei erzeugt.
    """
    return str(item_name or "").strip().lower() in ADDABLE_ITEM_IDS


def get_max_damage(item_name: str, durability: dict[str, int] | None = None) -> int:
    limits = durability or DURABILITY
    normalized = str(item_name or "").strip().lower()
    return limits.get(normalized, limits.get(canonical_item_id(normalized), MAX_DATA_VALUE))


def get_max_stack(item_name: str, stack_limits: dict[str, int] | None = None) -> int:
    limits = stack_limits or STACK_LIMITS
    normalized = str(item_name or "").strip().lower()
    return limits.get(normalized, limits.get(canonical_item_id(normalized), DEFAULT_MAX_STACK))


def item_component(item_name: str, component_name: str) -> dict[str, Any] | None:
    normalized = canonical_item_id(item_name)
    component_map = ITEM_COMPONENTS.get(str(component_name or "").strip().lower(), {})
    component = component_map.get(normalized)
    return dict(component) if isinstance(component, dict) else None


def item_wearable_slot(item_name: str) -> str | None:
    component = item_component(item_name, "wearable")
    slot = str(component.get("slot", "") if component else "").strip()
    return slot or None


def enchantment_slots_for_item(item_name: str) -> set[str]:
    normalized = canonical_item_id(item_name)
    if not normalized:
        return set()
    if normalized in OFFICIAL_ENCHANTMENT_ITEM_SLOTS:
        return _expand_enchantment_slot_groups(OFFICIAL_ENCHANTMENT_ITEM_SLOTS[normalized])
    exact_slots = ENCHANTMENT_ITEM_SLOTS.get(normalized)
    if exact_slots:
        return _expand_enchantment_slot_groups(exact_slots)
    short = normalized.removeprefix("minecraft:")
    for suffix, slot in ENCHANTMENT_ITEM_SLOT_SUFFIXES:
        if short.endswith(suffix):
            return _expand_enchantment_slot_groups({slot})
    return set()


def is_enchantable_item_id(item_name: str) -> bool:
    return bool(enchantment_slots_for_item(item_name))


def _expand_enchantment_slot_groups(slots: set[str]) -> set[str]:
    expanded = set()
    for slot in slots:
        expanded.update(ENCHANTMENT_SLOT_GROUPS.get(slot, {slot}))
    return expanded


def is_enchantment_compatible_with_item(enchantment_id: int, item_name: str) -> bool:
    item_slots = enchantment_slots_for_item(item_name)
    if not item_slots:
        return False
    compatible_slots = ENCHANTMENT_COMPATIBLE_SLOTS.get(int(enchantment_id))
    if not compatible_slots:
        return False
    return bool(item_slots & _expand_enchantment_slot_groups(compatible_slots))


def _refresh_component_derived_data() -> None:
    official_slots: dict[str, set[str]] = {}
    for item_id, component in ITEM_COMPONENTS.get("enchantable", {}).items():
        slot = str(component.get("slot", "") if isinstance(component, dict) else "").strip()
        if slot == "none":
            official_slots[item_id] = set()
        elif slot:
            official_slots[item_id] = {slot}
    OFFICIAL_ENCHANTMENT_ITEM_SLOTS.clear()
    OFFICIAL_ENCHANTMENT_ITEM_SLOTS.update(official_slots)
    ENCHANTMENT_COMPATIBILITY["official_item_slots"] = _client_slot_map(OFFICIAL_ENCHANTMENT_ITEM_SLOTS)


reload_item_database()
