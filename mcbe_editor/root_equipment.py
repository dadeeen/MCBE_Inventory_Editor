from __future__ import annotations

from typing import Any

import amulet_nbt as nbt

from .i18n import t
from .inventory import (
    _apply_entity_variant_edit,
    _build_item_compound,
    _check_item_enchantment_compatibility,
    _is_compound_tag,
    _is_list_tag,
    _item_control_field_type_issues,
    _item_source_digest,
    _normalized_source_item_digest,
    _parse_item_slot,
    _read_item_slot,
    _resolve_base_item_tag,
    apply_editable_item_tags,
    get_tag_value,
    item_payload_matches_original,
    reject_non_addable_new_item,
    validate_inventory_item,
    validate_item_data_value_variant,
    validate_item_original_bounds,
    validate_item_stack_count,
)
from .item_data import item_wearable_slot

# In modernen Bedrock-Spielständen ist die Root-Armor-Liste eine dichte Liste
# ohne Slot-Keys; die Position ergibt sich aus dem Listenindex.  Anhand echter
# Referenzwelten verifiziert: Index 0 = Helm, 1 = Brustpanzer, 2 = Hose,
# 3 = Stiefel.  Index 4 (Body-Slot, z. B. Wolfsrüstung) hat keinen UI-Slot und
# wird unverändert erhalten.
ARMOR_ROOT_SLOT_BY_INDEX = (103, 102, 101, 100)
ARMOR_SLOTS = set(ARMOR_ROOT_SLOT_BY_INDEX)
OFFHAND_SLOT = -106
ROOT_EQUIPMENT_SLOTS = ARMOR_SLOTS | {OFFHAND_SLOT}
ARMOR_ROOT_INDEX_BY_SLOT = {slot: index for index, slot in enumerate(ARMOR_ROOT_SLOT_BY_INDEX)}
ROOT_EQUIPMENT_READ_ONLY_FLAG = "root_equipment_read_only"
ROOT_EQUIPMENT_SOURCE_CONTAINERS = {"armor", "offhand"}

HEAD_ITEM_NAMES = {
    "carved_pumpkin",
    "mob_head",
    "player_head",
    "skull",
    "turtle_helmet",
    "turtle_shell",
}
CHEST_ITEM_NAMES = {"elytra"}

# Bedrock erlaubt in der Schildhand nur eine feste Item-Auswahl (anders als
# Java). Quelle: Minecraft Wiki "Off-hand", Stand Juli 2026: Schild, Pfeile
# (inkl. getippte), Feuerwerksraketen, Totem, gefüllte Karten/Forscherkarten,
# Nautilusschale sowie die Wunderkerze der Education Edition.
OFFHAND_ITEM_NAMES = {
    "arrow",
    "filled_map",
    "firework_rocket",
    "nautilus_shell",
    "shield",
    "sparkler",
    "tipped_arrow",
    "totem",
    "totem_of_undying",
}

EQUIPMENT_SLOT_LABELS = {
    103: "Helm",
    102: "Brustpanzer",
    101: "Hose",
    100: "Stiefel",
    OFFHAND_SLOT: "Schildhand",
}
WEARABLE_COMPONENT_UI_SLOTS = {
    "slot.armor.head": 103,
    "slot.armor.chest": 102,
    "slot.armor.legs": 101,
    "slot.armor.feet": 100,
    "slot.weapon.offhand": OFFHAND_SLOT,
}


def _root_item_name(item) -> str:
    if not _is_compound_tag(item):
        return ""
    return str(get_tag_value(item.get("Name"), "")).strip().lower()


def _root_entry_may_contain_item(item) -> bool:
    if not _is_compound_tag(item):
        return item is not None
    try:
        if not set(item.keys()):
            return False
    except AttributeError:
        return True
    name = _root_item_name(item)
    if name and name not in {"air", "minecraft:air"}:
        return True
    try:
        if int(get_tag_value(item.get("Count"), 0)) > 0:
            return True
    except (OverflowError, TypeError, ValueError):
        return True
    return bool(_item_control_field_type_issues(item))


def _root_entry_is_visible_item(item) -> bool:
    if not _is_compound_tag(item):
        return False
    if _item_control_field_type_issues(item):
        return False
    name = _root_item_name(item)
    if not name or name in {"air", "minecraft:air"}:
        return False
    try:
        count = int(get_tag_value(item.get("Count"), 0))
    except (OverflowError, TypeError, ValueError):
        return False
    return count > 0


def _root_entry_is_empty_placeholder(item) -> bool:
    """Return True for empty root-list placeholders as written by the game.

    Beobachtete Form: ``{Count: 0b, Damage: 0s, Name: "", WasPickedUp: 0b}``
    ohne Slot-Key.  Nur Standardfelder ohne Payload sind sicher wiederverwendbar.
    """

    if not _is_compound_tag(item):
        return False
    try:
        keys = set(item.keys())
    except AttributeError:
        return False
    if keys - {"Name", "Count", "Damage", "WasPickedUp"}:
        return False
    if _item_control_field_type_issues(item):
        return False
    name = _root_item_name(item)
    if name not in {"", "air", "minecraft:air"}:
        return False
    try:
        count = int(get_tag_value(item.get("Count"), 0))
    except (OverflowError, TypeError, ValueError):
        return False
    return count <= 0


def _root_entry_is_writable(item) -> bool:
    """Return whether a root-list entry matches the known modern shape.

    Moderne Bedrock-Versionen schreiben dichte Armor/Offhand-Listen, deren
    Einträge keinen Slot-Key tragen (die Position ist der Listenindex).  Nur
    solche Einträge dürfen bearbeitet werden; alles andere bleibt read-only.
    """

    if not _is_compound_tag(item):
        return False
    try:
        keys = set(item.keys())
    except AttributeError:
        return False
    if "Slot" in keys:
        return False
    return _root_entry_is_empty_placeholder(item) or _root_entry_is_visible_item(item)


def _writable_root_list(player_tag, tag_name: str, ui_slot_count: int, expected_lengths: set[int]):
    """Return the root list when it matches the verified modern shape.

    Nur die in echten Spielständen beobachteten Listenlängen gelten als
    modern (Armor: 4 Slots plus optionaler Body-Eintrag, Offhand: 1).
    Abweichende Längen stammen aus Legacy-Versionen oder Fremdtools und
    bleiben read-only, weil dort die Index-Semantik nicht gesichert ist.
    """

    root_list = player_tag.get(tag_name) if hasattr(player_tag, "get") else None
    if not _is_list_tag(root_list):
        return None
    if len(root_list) not in expected_lengths:
        return None
    for index, item in enumerate(root_list):
        if index >= ui_slot_count:
            # Einträge jenseits der UI-Slots (z. B. Body-Rüstung bei Index 4)
            # werden unverändert erhalten und müssen nicht editierbar sein.
            break
        if not _root_entry_is_writable(item):
            return None
    return root_list


def root_equipment_writable_slots(player_tag) -> set[int]:
    """Return UI slots whose root-list entries can be edited safely."""

    writable: set[int] = set()
    if _writable_root_list(player_tag, "Armor", len(ARMOR_ROOT_SLOT_BY_INDEX), {4, 5}) is not None:
        writable.update(ARMOR_SLOTS)
    has_legacy_offhand = hasattr(player_tag, "get") and player_tag.get("OffHandItem") is not None
    if not has_legacy_offhand and _writable_root_list(player_tag, "Offhand", 1, {1}) is not None:
        writable.add(OFFHAND_SLOT)
    return writable


def _local_item_name(name: str) -> str:
    return name.split(":", 1)[-1]


def _infer_armor_slot_from_item_name(name: str) -> int | None:
    wearable_slot = item_wearable_slot(name)
    if wearable_slot is not None:
        # Für Rüstung ist die offizielle Komponente abschließend. Ein Item mit
        # bekanntem Nicht-Rüstungs-Slot (z. B. slot.armor.body für Wolfsrüstung)
        # darf nicht über ein irreführendes Namenssuffix doch noch in einem
        # Spieler-Rüstungsslot landen.
        official_slot = WEARABLE_COMPONENT_UI_SLOTS.get(wearable_slot)
        return official_slot if official_slot in ARMOR_SLOTS else None
    local = _local_item_name(name)
    if local.endswith("_helmet") or local.endswith("_head") or local.endswith("_skull") or local in HEAD_ITEM_NAMES:
        return 103
    if local.endswith("_chestplate") or local in CHEST_ITEM_NAMES:
        return 102
    if local.endswith("_leggings"):
        return 101
    if local.endswith("_boots"):
        return 100
    return None


def item_allowed_in_equipment_slot(slot: int, name: str) -> bool:
    """Return whether the item is actually wearable/holdable in the UI slot.

    Rüstungsslots akzeptieren nur Items, deren offizielle ``minecraft:wearable``
    Komponente auf den Slot zeigt; ohne Komponente greift die Suffix-Heuristik
    plus kuratierte Ausnahmen wie Kürbis/Köpfe/Elytra.

    Die Schildhand entscheidet bewusst anders: ``minecraft:wearable`` ist in
    Bedrock nicht das Prädikat für die Offhand-Erlaubnis (Totem, Pfeile oder
    Karten haben gar keine Wearable-Komponente). Die offizielle Angabe ergänzt
    deshalb nur die kuratierte Positivliste, statt sie zu ersetzen. So kann ein
    künftiges Item mit Nicht-Offhand-Wearable-Komponente nicht aus der
    Schildhand fallen, obwohl Bedrock es dort erlaubt.
    """

    normalized = str(name).strip().lower()
    if slot == OFFHAND_SLOT:
        official_slot = WEARABLE_COMPONENT_UI_SLOTS.get(item_wearable_slot(normalized) or "")
        return official_slot == OFFHAND_SLOT or _local_item_name(normalized) in OFFHAND_ITEM_NAMES
    if slot in ARMOR_SLOTS:
        return _infer_armor_slot_from_item_name(normalized) == slot
    return True


def equipment_slot_label(slot: int) -> str:
    return EQUIPMENT_SLOT_LABELS.get(slot, str(slot))


def _armor_slot_for_entry(index: int, item) -> int | None:
    explicit_slot = _read_item_slot(item)
    if explicit_slot in ARMOR_SLOTS:
        return explicit_slot
    inferred_slot = _infer_armor_slot_from_item_name(_root_item_name(item))
    if inferred_slot in ARMOR_SLOTS:
        return inferred_slot
    if 0 <= index < len(ARMOR_ROOT_SLOT_BY_INDEX):
        return ARMOR_ROOT_SLOT_BY_INDEX[index]
    return None


def _offhand_slot_for_entry(index: int, item) -> int | None:
    explicit_slot = _read_item_slot(item)
    if explicit_slot == OFFHAND_SLOT:
        return OFFHAND_SLOT
    if index == 0:
        return OFFHAND_SLOT
    return None


def _parse_root_equipment_item(
    item,
    slot: int,
    *,
    source_container: str,
    source_tag: str,
    source_index: int,
    encoded_player_key: str | None = None,
    world_path: str | None = None,
    editable: bool = False,
) -> dict[str, Any] | None:
    if not _root_entry_is_visible_item(item):
        return None
    item_for_parse = item.copy()
    item_for_parse["Slot"] = nbt.ByteTag(slot)
    try:
        parsed = dict(_parse_item_slot(item_for_parse))
    except (AttributeError, OverflowError, TypeError, ValueError):
        return None
    parsed["slot"] = slot
    parsed["source_slot"] = slot
    parsed["source_item_digest"] = _item_source_digest(item)
    parsed["root_equipment_source_tag"] = source_tag
    parsed["root_equipment_source_index"] = source_index
    if editable:
        # Bekanntes modernes Root-Listen-Shape: Der Eintrag wird wie ein
        # normales Inventar-Item behandelt; die Save-Pipeline schreibt ihn
        # NBT-erhaltend in die Root-Liste zurück.
        parsed["source_container"] = "inventory"
    else:
        parsed["source_container"] = source_container
        parsed[ROOT_EQUIPMENT_READ_ONLY_FLAG] = True
        parsed["has_preserved_nbt"] = True
        preserved_summary = list(parsed.get("preserved_nbt_summary") or [])
        preserved_summary.append(t("Separater {tag}-Root-Eintrag wird read-only angezeigt und unverändert erhalten.", tag=source_tag))
        parsed["preserved_nbt_summary"] = preserved_summary
    if encoded_player_key:
        parsed["source_player_key"] = encoded_player_key
    if world_path:
        parsed["source_world_path"] = world_path
    return parsed


def root_equipment_protected_slots(player_tag, occupied_slots=()) -> set[int]:
    protected: set[int] = set()
    occupied = {int(slot) for slot in occupied_slots}
    # Slots im bekannten modernen Root-Listen-Shape sind editierbar und
    # brauchen keinen Schreibschutz.
    occupied |= root_equipment_writable_slots(player_tag)

    armor = player_tag.get("Armor") if hasattr(player_tag, "get") else None
    if _is_list_tag(armor):
        for index, item in enumerate(armor):
            if not _root_entry_may_contain_item(item):
                continue
            slot = _armor_slot_for_entry(index, item)
            if slot is not None and slot not in occupied:
                protected.add(slot)

    offhand = player_tag.get("Offhand") if hasattr(player_tag, "get") else None
    if _is_list_tag(offhand):
        for index, item in enumerate(offhand):
            if not _root_entry_may_contain_item(item):
                continue
            slot = _offhand_slot_for_entry(index, item)
            if slot is not None and slot not in occupied:
                protected.add(slot)

    offhand_item = player_tag.get("OffHandItem") if hasattr(player_tag, "get") else None
    if offhand_item is not None and OFFHAND_SLOT not in occupied and _root_entry_may_contain_item(offhand_item):
        protected.add(OFFHAND_SLOT)

    return protected


def root_equipment_inventory_fallbacks(
    player_tag,
    occupied_slots=(),
    *,
    encoded_player_key: str | None = None,
    world_path: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Expose Bedrock root Armor/Offhand lists as UI inventory items.

    Some Bedrock player records store worn armor and offhand items in separate
    root lists instead of Inventory slots 100-103/-106.  The normal Inventory
    entries remain authoritative when both shapes exist.  Entries in the known
    modern shape (dense list, no Slot keys, index = position) are editable and
    written back into the root lists on save; anything else stays read-only.
    """

    result: dict[int, dict[str, Any]] = {}
    occupied = {int(slot) for slot in occupied_slots}
    writable_slots = root_equipment_writable_slots(player_tag)

    for tag_name, source_container, slot_for_entry in (
        ("Armor", "armor", _armor_slot_for_entry),
        ("Offhand", "offhand", _offhand_slot_for_entry),
    ):
        root_list = player_tag.get(tag_name) if hasattr(player_tag, "get") else None
        if not _is_list_tag(root_list):
            continue
        for index, item in enumerate(root_list):
            slot = slot_for_entry(index, item)
            if slot is None or slot in occupied or slot in result:
                continue
            editable = slot in writable_slots
            if editable:
                # Im verifizierten modernen Shape ist der Listenindex die
                # verbindliche Position; Namens-Heuristiken greifen nur für
                # Legacy-Shapes.
                if tag_name == "Armor":
                    if index >= len(ARMOR_ROOT_SLOT_BY_INDEX):
                        continue
                    slot = ARMOR_ROOT_SLOT_BY_INDEX[index]
                else:
                    if index != 0:
                        continue
                    slot = OFFHAND_SLOT
                if slot in occupied or slot in result:
                    continue
            parsed = _parse_root_equipment_item(
                item,
                slot,
                source_container=source_container,
                source_tag=tag_name,
                source_index=index,
                encoded_player_key=encoded_player_key,
                world_path=world_path,
                editable=editable,
            )
            if parsed is not None:
                result[slot] = parsed

    offhand_item = player_tag.get("OffHandItem") if hasattr(player_tag, "get") else None
    if OFFHAND_SLOT not in occupied and OFFHAND_SLOT not in result and _is_compound_tag(offhand_item):
        parsed = _parse_root_equipment_item(
            offhand_item,
            OFFHAND_SLOT,
            source_container="offhand",
            source_tag="OffHandItem",
            source_index=0,
            encoded_player_key=encoded_player_key,
            world_path=world_path,
        )
        if parsed is not None:
            result[OFFHAND_SLOT] = parsed

    return result


def root_equipment_fallback_slots(player_tag, occupied_slots=()) -> set[int]:
    return root_equipment_protected_slots(player_tag, occupied_slots)


def reject_root_equipment_fallback_slot_writes(player_tag, inventory_list, occupied_slots=()) -> None:
    if not isinstance(inventory_list, list):
        return
    protected_slots = root_equipment_fallback_slots(player_tag, occupied_slots)
    if not protected_slots:
        return
    attempted_slots: list[int] = []
    for item in inventory_list:
        if not isinstance(item, dict):
            continue
        try:
            slot = int(item.get("slot"))
        except (OverflowError, TypeError, ValueError):
            continue
        if slot in protected_slots:
            attempted_slots.append(slot)
    if attempted_slots:
        slots = ", ".join(str(slot) for slot in sorted(set(attempted_slots)))
        raise ValueError(
            "Speichern abgelehnt: Ausrüstung/Schildhand liegt in separaten Root-Listen "
            f"und ist in Slot(s) {slots} nur read-only darstellbar. "
            "Bitte diese Slots nicht bearbeiten; die Originaldaten werden unverändert erhalten."
        )


def merge_root_equipment_fallbacks(
    inventory_data: dict[int, dict[str, Any]],
    player_tag,
    *,
    encoded_player_key: str | None = None,
    world_path: str | None = None,
) -> list[int]:
    fallbacks = root_equipment_inventory_fallbacks(
        player_tag,
        inventory_data.keys(),
        encoded_player_key=encoded_player_key,
        world_path=world_path,
    )
    inventory_data.update(fallbacks)
    read_only_fallback_slots = {slot for slot, item in fallbacks.items() if item.get(ROOT_EQUIPMENT_READ_ONLY_FLAG) is True}
    protected_slots = root_equipment_protected_slots(player_tag, inventory_data.keys()) | read_only_fallback_slots
    return sorted(protected_slots)


def merge_root_equipment_protected_slots(hidden_unknown_slots: dict[str, Any], root_equipment_slots: list[int]) -> dict[str, Any]:
    if not root_equipment_slots:
        return hidden_unknown_slots
    merged = dict(hidden_unknown_slots or {})
    protected_slots = {
        int(slot)
        for slot in merged.get("inventory_protected_known_slots", [])
        if isinstance(slot, int) or isinstance(slot, str) and slot.removeprefix("-").isdigit()
    }
    protected_slots.update(int(slot) for slot in root_equipment_slots)
    merged["inventory_protected_known_slots"] = sorted(protected_slots)
    # Keep the numeric count for truly non-renderable protected entries.  Root
    # equipment fallbacks are visible but read-only, so adding them to the count
    # would produce misleading "nicht darstellbare" warnings and double-counting
    # in the inventory summary.  The slot list alone is what blocks UI edits.
    return merged


def _empty_root_entry() -> nbt.CompoundTag:
    # Platzhalter-Shape wie vom Spiel beobachtet (dichte Listen, kein Slot-Key).
    return nbt.CompoundTag(
        {
            "Count": nbt.ByteTag(0),
            "Damage": nbt.ShortTag(0),
            "Name": nbt.StringTag(""),
            "WasPickedUp": nbt.ByteTag(0),
        }
    )


def _root_list_entries_are_standard(player_tag, tag_name: str) -> bool:
    root_list = player_tag.get(tag_name) if hasattr(player_tag, "get") else None
    if not _is_list_tag(root_list):
        return False
    return all(_root_entry_is_writable(entry) for entry in root_list)


def filter_root_equipment_presence_flags(player_tag, protected_flags: dict) -> dict:
    """Drop supported root equipment lists from the protected-NBT presence flags.

    Armor/Offhand im verifizierten modernen Shape sind editierbare UI-Slots und
    keine "geschützten/future" Strukturen mehr. Mainhand ist im Standard-Shape
    nur der vom Spiel abgeleitete Spiegel des gehaltenen Items und wird ohnehin
    unverändert erhalten. Legacy-/unbekannte Shapes bleiben als Hinweis stehen.
    """

    present = dict(protected_flags.get("root_item_lists_present") or {})
    if not present:
        return protected_flags
    writable = root_equipment_writable_slots(player_tag)
    if ARMOR_SLOTS & writable:
        present.pop("Armor", None)
    if OFFHAND_SLOT in writable:
        present.pop("Offhand", None)
    if _root_list_entries_are_standard(player_tag, "Mainhand"):
        present.pop("Mainhand", None)
    return {**protected_flags, "root_item_lists_present": present}


def root_equipment_original_items_by_slot(player_tag) -> dict[int, Any]:
    """Return writable root equipment item tags keyed by their UI slot.

    Used to resolve preserved-NBT base items when equipment is edited or moved
    between root lists and normal inventory slots.
    """

    result: dict[int, Any] = {}
    writable = root_equipment_writable_slots(player_tag)
    if ARMOR_SLOTS & writable:
        armor = player_tag.get("Armor")
        for index, item in enumerate(armor):
            if index >= len(ARMOR_ROOT_SLOT_BY_INDEX):
                break
            if _root_entry_is_visible_item(item):
                result[ARMOR_ROOT_SLOT_BY_INDEX[index]] = item
    if OFFHAND_SLOT in writable:
        offhand = player_tag.get("Offhand")
        if len(offhand) > 0 and _root_entry_is_visible_item(offhand[0]):
            result[OFFHAND_SLOT] = offhand[0]
    return result


def split_root_equipment_writes(player_tag, inventory_list, original_inventory_slots=()):
    """Split payload items that must be written into the root equipment lists.

    Items in writable equipment slots that do not exist in the original
    Inventory tag belong to the root lists.  Slots that already live in the
    Inventory tag (legacy in-Inventory armor) keep using the Inventory path.
    """

    if not isinstance(inventory_list, list):
        return inventory_list, []
    writable = root_equipment_writable_slots(player_tag)
    if not writable:
        return inventory_list, []
    original_slots = {int(slot) for slot in original_inventory_slots}
    remaining: list[Any] = []
    equipment: list[Any] = []
    for item in inventory_list:
        slot = None
        if isinstance(item, dict):
            try:
                slot = int(item.get("slot"))
            except (OverflowError, TypeError, ValueError):
                slot = None
        if slot is not None and slot in writable and slot not in original_slots:
            equipment.append(item)
        else:
            remaining.append(item)
    return remaining, equipment


def apply_root_equipment_writes(
    player_tag,
    equipment_items,
    enchantments_db,
    *,
    source_item_maps=None,
    target_player_key=None,
    extra_original_items=None,
    allow_clears=False,
    used_external_source_checks=None,
) -> None:
    """Write UI equipment edits back into the root Armor/Offhand lists.

    Nur für Slots im verifizierten modernen Shape (siehe
    ``root_equipment_writable_slots``).  Vorhandene Einträge werden
    NBT-erhaltend mutiert, entfernte Items durch das beobachtete
    Platzhalter-Shape ersetzt.  Einträge jenseits der UI-Slots (Body-Rüstung)
    und nicht schreibbare Listen bleiben unverändert.
    """

    writable = root_equipment_writable_slots(player_tag)
    if not writable:
        if equipment_items:
            raise ValueError("Ausrüstungs-Slots sind bei diesem Spieler nicht bearbeitbar (unbekanntes Root-Listen-Format).")
        return

    original_items = dict(extra_original_items or {})
    original_items.update(root_equipment_original_items_by_slot(player_tag))
    source_item_maps = source_item_maps or {}

    new_items_by_slot: dict[int, Any] = {}
    for item_data in equipment_items or []:
        validated_item = validate_inventory_item(
            item_data,
            enchantments_db,
            is_ender_chest=False,
            defer_stack_limit=True,
            defer_original_bounds=True,
        )
        if validated_item is None:
            continue
        slot = validated_item["slot"]
        validated_item["replace_original_nbt"] = item_data.get("replace_original_nbt") is True
        validated_item["source_item_digest"] = _normalized_source_item_digest(item_data, slot)
        if slot not in writable:
            raise ValueError(t("Ausrüstungs-Slot {slot} ist bei diesem Spieler nicht bearbeitbar.", slot=slot))
        if slot in new_items_by_slot:
            raise ValueError(t("Doppelter Ausrüstungs-Slot empfangen: {slot}", slot=slot))
        name = validated_item["name"]
        if not item_allowed_in_equipment_slot(slot, name):
            raise ValueError(
                f"Speichern abgelehnt: '{name}' ist kein im {equipment_slot_label(slot)}-Slot tragbares Item. "
                "Bedrock akzeptiert dort nur passende Ausrüstung "
                "(Schildhand: Schild, Pfeile, Feuerwerksraketen, Totem, gefüllte Karten, Nautilusschale)."
            )
        base_item_tag = _resolve_base_item_tag(
            validated_item,
            original_items,
            source_item_maps,
            target_player_key,
            "inventory",
            used_external_source_checks,
        )
        _check_item_enchantment_compatibility(name, validated_item, base_item_tag, enchantments_db, "Ausrüstung", slot)
        reject_non_addable_new_item(name, base_item_tag, "Ausrüstung", slot)
        validate_item_stack_count(name, validated_item["count"], base_item_tag, "Ausrüstung", slot)
        validate_item_original_bounds(validated_item, base_item_tag, "Ausrüstung", slot)
        validate_item_data_value_variant(name, validated_item["damage"], base_item_tag, "Ausrüstung", slot)
        # Wie im Inventar: unberührte Echo-Items werden nicht neu gebaut, damit
        # eine fremde Änderung ihre NBT-Struktur nicht umschreibt.
        unchanged = item_payload_matches_original(base_item_tag, validated_item, enchantments_db)
        item_compound = _build_item_compound(base_item_tag, validated_item, "Ausrüstung", False, unchanged=unchanged)
        if not unchanged:
            apply_editable_item_tags(item_compound, validated_item, enchantments_db)
            _apply_entity_variant_edit(item_compound, validated_item, base_item_tag, "Ausrüstung")
        # Root-Listen-Einträge tragen keinen Slot-Key; die Position ist der Index.
        if "Slot" in item_compound:
            del item_compound["Slot"]
        new_items_by_slot[slot] = item_compound

    for tag_name, index_by_slot in (
        ("Armor", ARMOR_ROOT_INDEX_BY_SLOT),
        ("Offhand", {OFFHAND_SLOT: 0}),
    ):
        slots = set(index_by_slot) & writable
        if not slots:
            continue
        root_list = player_tag.get(tag_name)
        entries = [entry.copy() for entry in root_list]
        changed = False
        for slot, index in index_by_slot.items():
            if slot not in slots:
                continue
            while index >= len(entries):
                entries.append(_empty_root_entry())
                changed = True
            if slot in new_items_by_slot:
                entries[index] = new_items_by_slot[slot]
                changed = True
            elif allow_clears and _root_entry_is_visible_item(entries[index]):
                # Das Item war in der UI sichtbar und fehlt im Payload:
                # bewusst geleert. Ohne root_equipment_editable-Flag (stale
                # Client) bleiben vorhandene Items unangetastet.
                entries[index] = _empty_root_entry()
                changed = True
        if changed:
            player_tag[tag_name] = nbt.ListTag(entries)


def is_read_only_root_equipment_payload(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get(ROOT_EQUIPMENT_READ_ONLY_FLAG) is True:
        return True
    source_container = str(item.get("source_container") or "").strip()
    return source_container in ROOT_EQUIPMENT_SOURCE_CONTAINERS


def filter_read_only_root_equipment_payload(item_list):
    """Drop echoed read-only root equipment entries from a save payload.

    Only entries that still sit in their root equipment slots (100-103/-106)
    are silently dropped; that is the normal UI echo of the read-only
    fallbacks.  A root-equipment-marked item in any other slot is a stray
    copy (e.g. clipboard paste) that would lose its preserved root-list NBT
    on save, so it must fail loudly instead of vanishing silently.
    """

    if not isinstance(item_list, list):
        return item_list
    filtered = []
    stray_slots: list[str] = []
    for item in item_list:
        if not is_read_only_root_equipment_payload(item):
            filtered.append(item)
            continue
        try:
            slot = int(item.get("slot"))
        except (OverflowError, TypeError, ValueError):
            slot = None
        if slot in ROOT_EQUIPMENT_SLOTS:
            continue
        stray_slots.append("?" if slot is None else str(slot))
    if stray_slots:
        slots = ", ".join(stray_slots)
        raise ValueError(
            t(
                "Speichern abgelehnt: Slot(s) "
                "{slots} enthalten Kopien aus den read-only Root-Ausrüstungslisten (Armor/Offhand). "
                "Solche Kopien können nicht als normale Inventar-Items gespeichert werden, "
                "weil ihr vollständiges NBT nur in den Root-Listen erhalten bleibt. "
                "Bitte entferne die eingefügten Kopien und speichere erneut.",
                slots=slots,
            )
        )
    return filtered
