from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

from mcbe_editor.inventory import (
    count_hidden_unknown_slots,
    nbt_to_json,
    parse_ender_chest,
    protected_player_nbt_flags,
)
from mcbe_editor.item_data import is_known_item_id

from .bedrock_nbt import load_player_nbt
from .i18n import t
from .root_equipment import filter_root_equipment_presence_flags

KNOWN_PLAYER_ROOT_KEYS = {
    "ActiveEffects",
    "Air",
    "Armor",
    "Attributes",
    "BlastFurnaceFiltering",
    "BlastFurnaceLayout",
    "Chested",
    "Color",
    "Color2",
    "CraftingLayout",
    "Dead",
    "DeathTime",
    "DimensionId",
    "EnchantmentSeed",
    "EnderChestInventory",
    "FallDistance",
    "FurnaceFiltering",
    "FurnaceLayout",
    "HasSeenCredits",
    "Health",
    "HurtTime",
    "Inventory",
    "InventoryFiltering",
    "InventoryLayout",
    "Invulnerable",
    "IsAngry",
    "IsAutonomous",
    "IsBaby",
    "IsEating",
    "IsGliding",
    "IsGlobal",
    "IsIllagerCaptain",
    "IsOrphaned",
    "IsOutOfControl",
    "IsPregnant",
    "IsRoaring",
    "IsScared",
    "IsStunned",
    "IsSwimming",
    "IsTamed",
    "IsTrusting",
    "LeasherID",
    "LeftBlastFurnaceTabSelection",
    "LeftFurnaceTabSelection",
    "LeftInventoryTabSelection",
    "LeftSmokerTabSelection",
    "LootDropped",
    "Mainhand",
    "MapIndex",
    "MarkVariant",
    "NaturalSpawn",
    "Offhand",
    "OnGround",
    "OwnerNew",
    "PlayerGameMode",
    "PlayerGameType",
    "PlayerLevel",
    "PlayerLevelProgress",
    "PlayerUIItems",
    "PortalCooldown",
    "Pos",
    "RightInventoryTabSelection",
    "Rotation",
    "Saddled",
    "SelectedContainerId",
    "SelectedInventorySlot",
    "Sheared",
    "ShowBottom",
    "Sitting",
    "SkinID",
    "SleepTimer",
    "Sleeping",
    "SlotDropChances",
    "SmokerFiltering",
    "SmokerLayout",
    "Sneaking",
    "SpawnBlockPositionX",
    "SpawnBlockPositionY",
    "SpawnBlockPositionZ",
    "SpawnDimension",
    "SpawnX",
    "SpawnY",
    "SpawnZ",
    "XPLevel",
    "XPProgress",
    "abilities",
    "foodLevel",
    "foodSaturationLevel",
}

KNOWN_WORLD_FILES = {
    "behavior_packs",
    "db",
    "level.dat",
    "level.dat_old",
    "levelname.txt",
    "resource_packs",
    "structures",
    "texts",
    "valid_known_packs.json",
    "world_behavior_pack_history.json",
    "world_behavior_packs.json",
    "world_icon.jpeg",
    "world_icon.png",
    "world_resource_pack_history.json",
    "world_resource_packs.json",
    "world_template_icon.jpeg",
    "world_template_icon.png",
}

PROTECTED_PRESENCE_KEYS = {
    "has_inventory_tag",
    "has_ender_chest_tag",
    "has_active_effects_tag",
    "has_abilities_tag",
}


def _file_status(path: Path) -> dict[str, Any]:
    status = {"path": str(path), "exists": False, "readable": False, "size": None}
    try:
        status["exists"] = path.exists()
        if status["exists"] and path.is_file():
            status["size"] = path.stat().st_size
            with path.open("rb") as f:
                f.read(1)
            status["readable"] = True
        elif status["exists"] and path.is_dir():
            status["readable"] = os.access(path, os.R_OK)
    except OSError as exc:
        status["error"] = f"{exc.__class__.__name__}: {exc}"
    return status


def _level_dat_status(world_path: str | os.PathLike) -> dict[str, Any]:
    path = Path(world_path) / "level.dat"
    status = _file_status(path)
    status["kind"] = "level.dat"
    if not status["exists"]:
        status["severity"] = "warning"
        status["message"] = "level.dat wurde nicht gefunden. Spieler-Inventare können trotzdem lesbar sein, aber die Weltstruktur wirkt unvollständig."
    elif not status["readable"]:
        status["severity"] = "error"
        status["message"] = "level.dat existiert, ist aber nicht lesbar."
    else:
        status["severity"] = "ok"
        status["message"] = "level.dat ist vorhanden und lesbar."
    return status


def _world_pack_status(world_path: str | os.PathLike) -> list[dict[str, Any]]:
    root = Path(world_path)
    result = []
    for name, label in (
        ("world_resource_packs.json", "Welt-Resource-Packs"),
        ("world_behavior_packs.json", "Welt-Behavior-Packs"),
    ):
        status = _file_status(root / name)
        status["label"] = label
        status["severity"] = "ok" if status["exists"] and status["readable"] else "info"
        status["message"] = f"{label} vorhanden." if status["exists"] else f"Keine {label} referenziert."
        result.append(status)
    return result


def analyze_world_structure(world_path: str | os.PathLike) -> dict[str, Any]:
    """Return a conservative Bedrock compatibility report for a world folder.

    The report intentionally avoids rewriting or normalizing anything.  It is a
    health/compatibility signal for the UI and tests, not a full Bedrock version
    parser. Unknown files and future data are treated as acceptable and preserved.
    """

    root = Path(world_path)
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    notes: list[str] = []

    root_status = _file_status(root)
    root_check = {**root_status, "kind": "world-root"}
    if not root_status["exists"]:
        root_check.update(severity="error", message="Weltordner existiert nicht.")
        errors.append(root_check["message"])
    elif not root.is_dir():
        root_check.update(severity="error", message="Pfad ist kein Ordner.")
        errors.append(root_check["message"])
    elif not root_status["readable"]:
        root_check.update(severity="error", message="Weltordner ist nicht lesbar.")
        errors.append(root_check["message"])
    else:
        root_check.update(severity="ok", message="Weltordner ist vorhanden und lesbar.")
    checks.append(root_check)

    db_status = _file_status(root / "db")
    db_check = {**db_status, "kind": "leveldb"}
    if not db_status["exists"]:
        db_check.update(severity="error", message="LevelDB-Ordner db/ fehlt. Das ist wahrscheinlich kein direkter Weltordner.")
        errors.append(db_check["message"])
    elif not (root / "db").is_dir():
        db_check.update(severity="error", message="db existiert, ist aber kein Ordner.")
        errors.append(db_check["message"])
    elif not db_status["readable"]:
        db_check.update(severity="error", message="LevelDB-Ordner db/ ist nicht lesbar.")
        errors.append(db_check["message"])
    else:
        db_check.update(severity="ok", message="LevelDB-Ordner db/ ist vorhanden und lesbar.")
    checks.append(db_check)

    level_dat_check = _level_dat_status(root)
    checks.append(level_dat_check)
    if level_dat_check.get("severity") == "error":
        errors.append(level_dat_check["message"])
    elif level_dat_check.get("severity") == "warning":
        warnings.append(level_dat_check["message"])
    checks.extend(_world_pack_status(root))

    unknown_top_level_files: list[str] = []
    with contextlib.suppress(OSError):
        for child in root.iterdir():
            if child.name not in KNOWN_WORLD_FILES:
                unknown_top_level_files.append(child.name)
    if unknown_top_level_files:
        notes.append("Zusätzliche Weltdateien/-ordner vorhanden; sie werden nicht verändert.")

    status = "ok"
    if errors:
        status = "error"
    elif warnings:
        status = "warning"

    return {
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "notes": notes,
        "unknown_top_level_entries": sorted(unknown_top_level_files)[:50],
        "save_policy": {
            "preserve_unknown_world_files": True,
            "preserve_unknown_player_nbt": True,
            "write_only_selected_player_record": True,
            "backup_before_write": True,
        },
    }


def _iter_visible_item_dicts(items: Any):
    if isinstance(items, dict):
        return items.values()
    return items or []


def _item_unknown_count(items: Any) -> int:
    return sum(1 for item in _iter_visible_item_dicts(items) if isinstance(item, dict) and not is_known_item_id(str(item.get("name") or "")))


def _hidden_unknown_slots_has_issues(summary: dict[str, Any]) -> bool:
    return bool(
        summary.get("inventory")
        or summary.get("ender_chest")
        or summary.get("inventory_protected_known")
        or summary.get("ender_chest_protected_known")
        or summary.get("inventory_opaque")
        or summary.get("ender_chest_opaque")
    )


def _format_limited(values: list[str], *, limit: int = 12) -> str:
    shown = values[:limit]
    suffix = f" (+{len(values) - limit} weitere)" if len(values) > limit else ""
    return ", ".join(shown) + suffix


def _unknown_item_details(container_label: str, items: Any) -> list[str]:
    details: list[str] = []
    for item in _iter_visible_item_dicts(items):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("name") or "").strip()
        if not item_id or is_known_item_id(item_id):
            continue
        slot = item.get("slot", "?")
        count = item.get("count", "?")
        details.append(f"{container_label} {slot}: {item_id} (Menge {count})")
    return details


def _hidden_unknown_slot_details(summary: dict[str, Any]) -> list[str]:
    details: list[str] = []
    if summary.get("inventory_opaque"):
        details.append("Inventory ist kein ListTag")
    if summary.get("ender_chest_opaque"):
        details.append("EnderChestInventory ist kein ListTag")
    if summary.get("inventory"):
        details.append(t("Inventory enthält {count} versteckte Slot-ID(s) außerhalb des editierbaren Bereichs", count=summary["inventory"]))
    if summary.get("ender_chest"):
        details.append(t("EnderChestInventory enthält {count} versteckte Slot-ID(s) außerhalb des editierbaren Bereichs", count=summary["ender_chest"]))
    if summary.get("inventory_protected_known"):
        slots = summary.get("inventory_protected_known_slots") or []
        slot_text = t(" Slots {slots}", slots=", ".join(map(str, slots))) if slots else ""
        details.append(t("Inventory enthält {count} geschützte bekannte Slot(s){slots}", count=summary["inventory_protected_known"], slots=slot_text))
    if summary.get("ender_chest_protected_known"):
        slots = summary.get("ender_chest_protected_known_slots") or []
        slot_text = t(" Slots {slots}", slots=", ".join(map(str, slots))) if slots else ""
        details.append(
            t("EnderChestInventory enthält {count} geschützte bekannte Slot(s){slots}", count=summary["ender_chest_protected_known"], slots=slot_text)
        )
    return details


def _protected_nbt_issue_details(protected: dict[str, Any]) -> list[str]:
    details: list[str] = []
    opaque_labels = {
        "inventory_opaque": "Inventory ist kein ListTag",
        "ender_chest_opaque": "EnderChestInventory ist kein ListTag",
        "active_effects_opaque": "ActiveEffects ist kein ListTag",
        "abilities_opaque": "abilities ist kein CompoundTag",
        "pos_opaque": "Pos ist kein ListTag",
    }
    for key, label in opaque_labels.items():
        if protected.get(key):
            details.append(label)

    for field_name, tag_name in sorted((protected.get("ability_fields_opaque") or {}).items()):
        details.append(t("abilities.{tag} für {field} hat einen unerwarteten Typ", tag=tag_name, field=field_name))
    for field_name, tag_name in sorted((protected.get("stat_fields_opaque") or {}).items()):
        details.append(t("{tag} für {field} hat einen unerwarteten Typ", tag=tag_name, field=field_name))

    active_effect_entries = protected.get("active_effect_entries_opaque") or 0
    if active_effect_entries:
        details.append(t("ActiveEffects enthält {count} Effekt-Eintrag(e) mit unerwarteter Struktur", count=active_effect_entries))

    for tag_name, count in sorted((protected.get("root_item_lists_present") or {}).items()):
        details.append(t("{tag} enthält {count} zusätzliche Root-Item-Eintrag(e)", tag=tag_name, count=count))
    for tag_name in sorted((protected.get("root_item_lists_opaque") or {}).keys()):
        details.append(f"{tag_name} ist keine editierbare Item-Liste")
    return details


def _protected_nbt_has_issues(protected: dict[str, Any]) -> bool:
    return any(key not in PROTECTED_PRESENCE_KEYS and bool(value) for key, value in protected.items())


def analyze_player_compatibility(player_tag, *, serialized_before: bytes | None = None) -> dict[str, Any]:
    protected = filter_root_equipment_presence_flags(player_tag, protected_player_nbt_flags(player_tag))
    inventory, _ = nbt_to_json(player_tag)
    ender_chest = parse_ender_chest(player_tag)
    root_keys = set(player_tag.keys()) if hasattr(player_tag, "keys") else set()
    unknown_root_keys = sorted(root_keys - KNOWN_PLAYER_ROOT_KEYS)
    hidden_unknown_slots = count_hidden_unknown_slots(player_tag)

    warnings: list[str] = []
    notes: list[str] = []
    if unknown_root_keys:
        notes.append(t("Zusätzliche Root-Tags: {tags}. Diese werden erhalten und nicht normalisiert.", tags=_format_limited(unknown_root_keys)))

    protected_details = _protected_nbt_issue_details(protected)
    if protected_details:
        warnings.append(
            t("Geschützte/future NBT-Strukturen: {details}. Sichtbare Änderungen werden konservativ angewendet.", details=_format_limited(protected_details))
        )

    hidden_slot_details = _hidden_unknown_slot_details(hidden_unknown_slots)
    if hidden_slot_details:
        warnings.append(f"Nicht editierbare/unklare Inventar-Slots: {_format_limited(hidden_slot_details)}. Sie werden erhalten.")

    unknown_item_details = {
        "inventory": _unknown_item_details("Inventar", inventory),
        "ender_chest": _unknown_item_details("Endertruhe", ender_chest),
    }
    unknown_item_ids = {
        "inventory": len(unknown_item_details["inventory"]),
        "ender_chest": len(unknown_item_details["ender_chest"]),
    }
    all_unknown_item_details = unknown_item_details["inventory"] + unknown_item_details["ender_chest"]
    if all_unknown_item_details:
        warnings.append(f"Unbekannte Item-IDs: {_format_limited(all_unknown_item_details)}. Sie werden angezeigt und konservativ behandelt.")

    roundtrip_ok = None
    roundtrip_error = ""
    if serialized_before is not None:
        try:
            load_player_nbt(serialized_before)
            roundtrip_ok = True
        except Exception as exc:  # pragma: no cover - defensive signal for corrupt fixtures/runtime data
            roundtrip_ok = False
            roundtrip_error = f"{exc.__class__.__name__}: {exc}"
            warnings.append("Der Spieler-Datensatz konnte nicht stabil erneut gelesen werden.")

    return {
        "status": "warning" if warnings else "ok",
        "warnings": warnings,
        "notes": notes,
        "protected_nbt": protected,
        "hidden_unknown_slots": hidden_unknown_slots,
        "unknown_root_keys": unknown_root_keys[:100],
        "unknown_item_ids": unknown_item_ids,
        "unknown_item_details": unknown_item_details,
        "protected_nbt_details": protected_details,
        "hidden_unknown_slot_details": hidden_slot_details,
        "roundtrip": {
            "readable_before_edit": roundtrip_ok,
            "error": roundtrip_error,
        },
        "save_policy": {
            "preserve_unknown_tags": True,
            "preserve_unedited_opaque_fields": True,
            "controlled_fields_only": ["Slot", "Name", "Count", "Damage", "display.Name", "display.Lore", "enchantments"],
            "serialize_and_reload_before_write": True,
        },
    }


def assert_serialized_player_roundtrip(serialized_bytes: bytes) -> None:
    try:
        load_player_nbt(serialized_bytes)
    except Exception as exc:
        raise ValueError(f"Speichern abgelehnt: Der vorbereitete Spieler-Datensatz ist nicht wieder lesbar ({exc}).") from exc
