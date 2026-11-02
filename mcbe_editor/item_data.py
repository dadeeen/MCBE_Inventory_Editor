from __future__ import annotations

import logging
import os
import re
import secrets
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcbe_editor.item_catalog_file import DEFAULT_MAX_STACK as DEFAULT_MAX_STACK
from mcbe_editor.item_catalog_file import InvalidItemDatabaseError, load_enchantment_compatibility, read_catalog_file
from mcbe_editor.item_name_policy import SUPERSEDED_ITEM_LABELS as SUPERSEDED_ITEM_LABELS
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON, atomic_seed_file
from mcbe_editor.world_locks import locked_operation

DEFAULT_MAX_DAMAGE = 1561
MAX_DATA_VALUE = 32767

LOGGER = logging.getLogger(__name__)


def _client_slot_map(raw: dict[str, set[str]]) -> dict[str, list[str]]:
    return {key: sorted(value) for key, value in raw.items()}


def _compatibility_globals(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ENCHANTMENT_COMPATIBILITY_SCHEMA_VERSION": data["schema_version"],
        "ENCHANTMENT_COMPATIBILITY_SOURCES": data["sources"],
        "ENCHANTMENT_COMPATIBILITY_SOURCE_PATH": data["source_path"],
        "ENCHANTMENT_COMPATIBLE_SLOTS": data["compatible_slots"],
        "ENCHANTMENT_SLOT_GROUPS": data["slot_groups"],
        "ENCHANTMENT_ITEM_SLOTS": data["item_slots"],
        "ENCHANTMENT_ITEM_SLOT_SUFFIXES": data["item_slot_suffixes"],
        "ENCHANTMENT_EXCLUSIVE_GROUPS": data["exclusive_groups"],
        "ENCHANTMENT_COMPATIBILITY": {
            "schema_version": data["schema_version"],
            "sources": data["sources"],
            "compatible_slots": {str(key): sorted(value) for key, value in data["compatible_slots"].items()},
            "slot_groups": _client_slot_map(data["slot_groups"]),
            "item_slots": _client_slot_map(data["item_slots"]),
            "official_item_slots": {},
            "item_slot_suffixes": [list(entry) for entry in data["item_slot_suffixes"]],
            "exclusive_groups": data["exclusive_groups"],
        },
    }


_ITEM_CATALOG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("item_catalog", default=None)
_CURRENT_ITEM_CATALOG: dict[str, Any] = {}


def current_item_catalog() -> dict[str, Any]:
    """Return the published data snapshot. Consumers must not mutate its contents."""

    return _CURRENT_ITEM_CATALOG


def catalog_values() -> dict[str, Any]:
    """Use a workflow's bound snapshot, or the public defaults for standalone callers."""

    catalog = _ITEM_CATALOG_CONTEXT.get()
    return globals() if catalog is None else catalog


@contextmanager
def use_item_catalog(catalog: dict[str, Any] | None) -> Iterator[None]:
    """Keep nested NBT helpers on one catalog without serializing concurrent readers."""

    if catalog is None:
        yield
        return
    token = _ITEM_CATALOG_CONTEXT.set(catalog)
    try:
        yield
    finally:
        _ITEM_CATALOG_CONTEXT.reset(token)


STACK_LIMITS: dict[str, int] = {}
DURABILITY: dict[str, int] = {}
# Nur Komponenten, die im Editor tatsächlich eine Entscheidung treffen:
# ``enchantable`` bestimmt die Verzauberungs-Kompatibilität, ``wearable`` die
# Rüstungsslots und ``allow_off_hand`` die Nebenhand. Weitere Komponenten werden nicht mitgeführt —
# unbenutzte Daten mit fail-closed-Validierung können nur schaden (eine
# unbekannte Formänderung quarantäniert die persistente DB des Nutzers).
ITEM_COMPONENTS: dict[str, dict[str, dict[str, Any]]] = {
    "enchantable": {},
    "wearable": {},
    "allow_off_hand": {},
}
ITEMS: dict[str, tuple[str, str]] = {}
EFFECTS: dict[int, tuple[str, str, str, str]] = {}
ENCHANTMENTS: dict[int, tuple[str, str, int, str] | tuple[str, str, int]] = {}
ITEM_DB_CONFLICTS: dict[str, dict[str, Any]] = {}
COMPAT_ITEM_ALIASES: dict[str, str] = {}
BLOCK_ONLY_ITEM_IDS: frozenset[str] = frozenset()
BLOCK_ITEM_IDS: frozenset[str] = frozenset()
ADDABLE_ITEM_IDS: frozenset[str] = frozenset()
UNREVIEWED_ITEM_IDS: frozenset[str] = frozenset()
ITEM_DB_SOURCE_PATH = str(BUNDLED_ITEM_DB_JSON)
ITEM_DB_SCHEMA_VERSION = 3


def resolve_item_db_json_path(path: str | os.PathLike | None = None) -> Path:
    candidate = Path(path or os.environ.get("MCBE_ITEM_DB_PATH") or BUNDLED_ITEM_DB_JSON).expanduser()
    if candidate.suffix.lower() != ".json":
        raise ValueError(f"Item-DB muss eine JSON-Datei sein: {candidate}")
    return candidate


def _load_item_database_file(item_db_path: Path) -> dict[str, Any]:
    return read_catalog_file(item_db_path, bundled_path=BUNDLED_ITEM_DB_JSON, slot_groups=catalog_values()["ENCHANTMENT_SLOT_GROUPS"])


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
        # Only unambiguous identities are editable. Empty lookup maps engage
        # the existing lossless unknown-NBT protection in readers and writers;
        # the original sections remain in the persistent database untouched.
        "EFFECTS": {} if "effects" in db["ITEM_DB_CONFLICTS"] else db["EFFECTS"],
        "ENCHANTMENTS": {} if "enchantments" in db["ITEM_DB_CONFLICTS"] else db["ENCHANTMENTS"],
        "ITEM_DB_CONFLICTS": db["ITEM_DB_CONFLICTS"],
        "COMPAT_ITEM_ALIASES": db["COMPAT_ITEM_ALIASES"],
        "BLOCK_ONLY_ITEM_IDS": db["BLOCK_ONLY_ITEM_IDS"],
        "BLOCK_ITEM_IDS": db["BLOCK_ITEM_IDS"],
        "ADDABLE_ITEM_IDS": db["ADDABLE_ITEM_IDS"],
        "UNREVIEWED_ITEM_IDS": db["UNREVIEWED_ITEM_IDS"],
        "ITEM_DB_SOURCE_PATH": db["SOURCE_PATH"],
        "ITEM_DB_SCHEMA_VERSION": db["SCHEMA_VERSION"],
    }


def prepare_item_catalog(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Load and validate all data, including derived rules, without changing live state."""

    catalog = _compatibility_globals(load_enchantment_compatibility())
    with use_item_catalog(catalog):
        catalog.update(database_as_module_globals(path))
    official_slots = _official_enchantment_slots(catalog["ITEM_COMPONENTS"])
    catalog["OFFICIAL_ENCHANTMENT_ITEM_SLOTS"] = official_slots
    catalog["ENCHANTMENT_COMPATIBILITY"]["official_item_slots"] = _client_slot_map(official_slots)
    return catalog


def publish_item_catalog(catalog: dict[str, Any]) -> None:
    """Publish a prepared catalog; previously bound workflows retain their data.

    The application serializes publication with its service/update guards.
    Public module attributes remain data snapshots for standalone callers;
    runtime consumers bind the complete catalog rather than importing defaults.
    """

    global _CURRENT_ITEM_CATALOG
    globals().update(catalog)
    _CURRENT_ITEM_CATALOG = catalog


def reload_item_database(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Reload data only. Failed preparation leaves every live value unchanged."""

    catalog = prepare_item_catalog(path)
    publish_item_catalog(catalog)
    return catalog


def canonical_item_id(item_name: str) -> str:
    normalized = str(item_name or "").strip().lower()
    return catalog_values()["COMPAT_ITEM_ALIASES"].get(normalized, normalized)


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

    source_items = catalog_values()["ITEMS"] if items is None else items
    source_addable = catalog_values()["ADDABLE_ITEM_IDS"] if addable_item_ids is None else addable_item_ids
    source_block_only = catalog_values()["BLOCK_ONLY_ITEM_IDS"] if block_only_item_ids is None else block_only_item_ids
    source_aliases = catalog_values()["COMPAT_ITEM_ALIASES"] if compat_item_aliases is None else compat_item_aliases
    result = dict(source_items)
    recognized_runtime_ids = {str(value or "").strip().lower() for collection in (source_addable, source_block_only) for value in collection}
    for item_id in sorted(recognized_runtime_ids):
        if not item_id or item_id in result:
            continue
        alias_target = source_aliases.get(item_id)
        result[item_id] = result.get(alias_target) or fallback_item_display_names(item_id)
    return result


def is_known_item_id(item_name: str) -> bool:
    normalized = str(item_name or "").strip().lower()
    catalog = catalog_values()
    return any(normalized in catalog[name] for name in ("ITEMS", "COMPAT_ITEM_ALIASES", "ADDABLE_ITEM_IDS", "BLOCK_ONLY_ITEM_IDS"))


def is_block_only_item_id(item_name: str) -> bool:
    """True für Katalog-IDs, die nur als technische Blockzustände nutzbar sind."""
    return str(item_name or "").strip().lower() in catalog_values()["BLOCK_ONLY_ITEM_IDS"]


def is_block_item_id(item_name: str) -> bool:
    """True für registry-abgeleitete, im Browser als Block geeignete Items."""
    return str(item_name or "").strip().lower() in catalog_values()["BLOCK_ITEM_IDS"]


def is_addable_item_id(item_name: str) -> bool:
    """True nur für nichttechnische IDs aus Mojangs positiver Item-Registry.

    Das ist absichtlich enger als ``is_known_item_id``: bekannte Legacy-,
    Block- und Add-on-IDs werden weiterhin gelesen und erhalten, aber nicht als
    neue Vanilla-Items angeboten oder frei erzeugt.
    """
    return str(item_name or "").strip().lower() in catalog_values()["ADDABLE_ITEM_IDS"]


def get_max_damage(item_name: str, durability: dict[str, int] | None = None) -> int:
    limits = durability or catalog_values()["DURABILITY"]
    normalized = str(item_name or "").strip().lower()
    return limits.get(normalized, limits.get(canonical_item_id(normalized), catalog_values()["MAX_DATA_VALUE"]))


def has_verified_stack_limit(item_name: str, stack_limits: dict[str, int] | None = None) -> bool:
    limits = catalog_values()["STACK_LIMITS"] if stack_limits is None else stack_limits
    normalized = str(item_name or "").strip().lower()
    return normalized in limits or canonical_item_id(normalized) in limits


def get_max_stack(item_name: str, stack_limits: dict[str, int] | None = None) -> int:
    """Return a recorded limit, or the safe creation bound for an unknown one."""
    limits = catalog_values()["STACK_LIMITS"] if stack_limits is None else stack_limits
    normalized = str(item_name or "").strip().lower()
    return limits.get(canonical_item_id(normalized), limits.get(normalized, catalog_values()["DEFAULT_MAX_STACK"]))


def item_component(item_name: str, component_name: str) -> dict[str, Any] | None:
    normalized = canonical_item_id(item_name)
    component_map = catalog_values()["ITEM_COMPONENTS"].get(str(component_name or "").strip().lower(), {})
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
    if normalized in catalog_values()["OFFICIAL_ENCHANTMENT_ITEM_SLOTS"]:
        return _expand_enchantment_slot_groups(catalog_values()["OFFICIAL_ENCHANTMENT_ITEM_SLOTS"][normalized])
    exact_slots = catalog_values()["ENCHANTMENT_ITEM_SLOTS"].get(normalized)
    if exact_slots:
        return _expand_enchantment_slot_groups(exact_slots)
    short = normalized.removeprefix("minecraft:")
    for suffix, slot in catalog_values()["ENCHANTMENT_ITEM_SLOT_SUFFIXES"]:
        if short.endswith(suffix):
            return _expand_enchantment_slot_groups({slot})
    return set()


def is_enchantable_item_id(item_name: str) -> bool:
    return bool(enchantment_slots_for_item(item_name))


def _expand_enchantment_slot_groups(slots: set[str]) -> set[str]:
    expanded = set()
    for slot in slots:
        expanded.update(catalog_values()["ENCHANTMENT_SLOT_GROUPS"].get(slot, {slot}))
    return expanded


def is_enchantment_compatible_with_item(enchantment_id: int, item_name: str) -> bool:
    item_slots = enchantment_slots_for_item(item_name)
    if not item_slots:
        return False
    compatible_slots = catalog_values()["ENCHANTMENT_COMPATIBLE_SLOTS"].get(int(enchantment_id))
    if not compatible_slots:
        return False
    return bool(item_slots & _expand_enchantment_slot_groups(compatible_slots))


def _official_enchantment_slots(item_components: dict[str, Any]) -> dict[str, set[str]]:
    official_slots: dict[str, set[str]] = {}
    for item_id, component in item_components.get("enchantable", {}).items():
        slot = str(component.get("slot", "") if isinstance(component, dict) else "").strip()
        if slot == "none":
            official_slots[item_id] = set()
        elif slot:
            official_slots[item_id] = {slot}
    return official_slots


reload_item_database()
