"""Conservative villager projections and lossless, narrowly scoped write plans."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from . import nbt
from .bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS, literal_string_tag
from .entities import EntityRecord, EntityScan, entity_position, issue, scalar_integer, scan_entities
from .i18n import t
from .inventory import ITEM_ID_RE, nbt_view_value
from .read_operation import checkpoint
from .villager_career import career_state, career_summary, normalize_career_changes, patch_career
from .villager_inventory import inventory_state, normalize_inventory_changes, patch_inventory

VILLAGER_IDENTIFIERS = frozenset({"minecraft:villager_v2", "minecraft:villager"})
MAX_HEALTH = 2048.0
MAX_SELECTION = 1000
MAX_DETAIL_ITEMS = 80
MAX_NAME_LENGTH = 80

# Mojang's vanilla component groups define Variant, not Profession. Legacy
# villagers use broader Variant groups and cannot share the v2 numeric mapping.
# https://github.com/Mojang/bedrock-samples/blob/main/behavior_pack/entities/villager_v2.json
# https://github.com/Mojang/bedrock-samples/blob/main/behavior_pack/entities/villager.json
_PROFESSIONS = (
    ("unemployed", "Arbeitslos"),
    ("farmer", "Farmer"),
    ("fisherman", "Fischer"),
    ("shepherd", "Schäfer"),
    ("fletcher", "Pfeilmacher"),
    ("librarian", "Bibliothekar"),
    ("cartographer", "Kartograf"),
    ("cleric", "Geistlicher"),
    ("armorer", "Rüstungsschmied"),
    ("weaponsmith", "Waffenschmied"),
    ("toolsmith", "Werkzeugschmied"),
    ("butcher", "Metzger"),
    ("leatherworker", "Gerber"),
    ("mason", "Steinmetz"),
    ("nitwit", "Nichtsnutz"),
)
_LEGACY_PROFESSIONS = {
    0: ("farmer", "fisherman", "shepherd", "fletcher"),
    1: ("librarian", "cartographer"),
    2: ("cleric",),
    3: ("armorer", "weaponsmith", "toolsmith"),
    4: ("butcher", "leatherworker"),
    5: ("nitwit",),
}
_TIERS = ("Neuling", "Lehrling", "Geselle", "Experte", "Meister")
_VILLAGE_KEY = re.compile(r"VILLAGE_(?:(?P<dimension>[A-Za-z]+)_)?(?P<id>[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})_DWELLERS")
_REVISION = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class HealthChangePlan:
    writes: dict[bytes, bytes]
    before_records: dict[bytes, bytes]
    rows: list[dict[str, Any]]
    changes: dict[str, Any]
    summary: dict[str, int]


def _active_definitions(tag: nbt.CompoundTag) -> set[str]:
    definitions = tag.get("definitions")
    active: set[str] = set()
    if isinstance(definitions, nbt.ListTag):
        for value in definitions:
            if not isinstance(value, nbt.StringTag) or not value.py_data.startswith(("+", "-")):
                continue
            operation, name = value.py_data[0], value.py_data[1:]
            name = name.removeprefix("minecraft:")
            if operation == "+":
                active.add(name)
            else:
                active.discard(name)
    return active


def _profession(record: EntityRecord) -> dict[str, Any]:
    variant = scalar_integer(record.tag.get("Variant"))
    if record.identifier == "minecraft:villager_v2" and "Variant" not in record.tag and "unskilled" in _active_definitions(record.tag):
        variant = 0
    if record.identifier == "minecraft:villager_v2" and variant is not None and 0 <= variant < len(_PROFESSIONS):
        identity, label = _PROFESSIONS[variant]
        return {"id": identity, "label": t(label), "source": "Variant", "variant": variant}
    if record.identifier == "minecraft:villager" and variant in _LEGACY_PROFESSIONS:
        allowed = _LEGACY_PROFESSIONS[variant]
        definitions = set(allowed).intersection(_active_definitions(record.tag))
        if len(allowed) == 1 or len(definitions) == 1:
            identity = next(iter(definitions)) if definitions else allowed[0]
            label = dict(_PROFESSIONS)[identity]
            return {"id": identity, "label": t(label), "source": "definitions" if definitions else "legacy_variant", "variant": variant}
        return {
            "id": f"legacy_{variant}",
            "label": " / ".join(t(dict(_PROFESSIONS)[identity]) for identity in allowed),
            "source": "legacy_group",
            "variant": variant,
        }
    return {"id": "unknown", "label": t("Unbekannt"), "source": "unknown", "variant": variant}


def _is_baby(tag: nbt.CompoundTag) -> bool | None:
    flag = tag.get("IsBaby")
    if flag is not None:
        return bool(flag.py_data) if isinstance(flag, nbt.ByteTag) and flag.py_data in (0, 1) else None
    age = scalar_integer(tag.get("Age"))
    if age is not None:
        return age < 0
    definitions = _active_definitions(tag)
    if "baby" in definitions and "adult" not in definitions:
        return True
    if "adult" in definitions and "baby" not in definitions:
        return False
    return None


def _number(tag: Any) -> float | None:
    if not isinstance(tag, (nbt.ByteTag, nbt.ShortTag, nbt.IntTag, nbt.LongTag, nbt.FloatTag, nbt.DoubleTag)):
        return None
    value = float(tag.py_data)
    return value if math.isfinite(value) else None


def _health_attribute(tag: nbt.CompoundTag) -> nbt.CompoundTag | None:
    attributes = tag.get("Attributes")
    if not isinstance(attributes, nbt.ListTag):
        return None
    matches = [
        value
        for value in attributes
        if isinstance(value, nbt.CompoundTag) and isinstance(value.get("Name"), nbt.StringTag) and value["Name"].py_data == "minecraft:health"
    ]
    return matches[0] if len(matches) == 1 else None


def _modifier_present(value: Any) -> bool:
    return value is not None and (not isinstance(value, (nbt.ListTag, nbt.CompoundTag)) or len(value) != 0)


def _health_value_tag(attribute: nbt.CompoundTag, name: str, default_name: str) -> Any:
    # BDS omits Current when it equals Base, and Max when it equals DefaultMax.
    # Only absence enables this fallback: an explicit malformed value must not
    # disappear behind a valid default. Callers still validate the source tag.
    return attribute[name] if name in attribute else attribute.get(default_name)


def _health_state(tag: nbt.CompoundTag) -> dict[str, Any]:
    attribute = _health_attribute(tag)
    if attribute is None:
        return {
            "current": None,
            "max": None,
            "editable": False,
            "max_editable": False,
            "reason": t("Ein eindeutiges Gesundheitsattribut fehlt oder ist nicht lesbar."),
        }
    current_tag = _health_value_tag(attribute, "Current", "Base")
    maximum_tag = _health_value_tag(attribute, "Max", "DefaultMax")
    current, maximum = _number(current_tag), _number(maximum_tag)
    result = {"current": current, "max": maximum, "editable": True, "max_editable": True, "reason": None}
    reason = None
    if any(not isinstance(value, nbt.FloatTag) for value in (current_tag, maximum_tag)):
        reason = t("Der gespeicherte Gesundheitstyp wird nur angezeigt; unterstützt werden Float-Attribute.")
    elif current is None or maximum is None or not 0 < current <= maximum <= MAX_HEALTH:
        reason = t("Die gespeicherten Lebenspunkte sind ungültig, außerhalb des unterstützten Bereichs oder gehören zu einer toten Kreatur.")
    for name in ("Min", "Base", "DefaultMin", "DefaultMax"):
        if name in attribute and (not isinstance(attribute[name], nbt.FloatTag) or _number(attribute[name]) is None):
            reason = t("Zusätzliche Gesundheitsgrenzen sind nicht eindeutig lesbar.")
    minimum = _number(attribute.get("Min")) if "Min" in attribute else 0.0
    base = _number(attribute.get("Base"))
    default_minimum = _number(attribute.get("DefaultMin"))
    default_maximum = _number(attribute.get("DefaultMax"))
    if (
        minimum is not None
        and maximum is not None
        and current is not None
        and (minimum < 0 or minimum > current or minimum > maximum or (base is not None and not minimum <= base <= maximum))
    ):
        reason = t("Die Gesundheitsgrenzen und der gespeicherte Basiswert sind nicht konsistent.")
    if default_minimum is not None and (
        default_minimum < 0
        or (current is not None and current < default_minimum)
        or (maximum is not None and maximum < default_minimum)
        or (base is not None and base < default_minimum)
        or (default_maximum is not None and default_maximum < default_minimum)
    ):
        reason = t("Die Gesundheitsgrenzen und der gespeicherte Basiswert sind nicht konsistent.")
    if default_maximum is not None and (default_maximum <= 0 or (minimum is not None and default_maximum < minimum)):
        reason = t("Die Gesundheitsgrenzen und der gespeicherte Basiswert sind nicht konsistent.")
    if any(_modifier_present(attribute.get(name)) for name in ("Modifiers", "AttributeModifiers")) or _modifier_present(tag.get("AttributeModifiers")):
        reason = t("Gesundheitsmodifikatoren verhindern eine sichere direkte Bearbeitung.")
    effects = tag.get("ActiveEffects")
    if effects is not None and not isinstance(effects, nbt.ListTag):
        reason = t("Gesundheitsmodifikatoren verhindern eine sichere direkte Bearbeitung.")
    elif isinstance(effects, nbt.ListTag):
        for effect in effects:
            if not isinstance(effect, nbt.CompoundTag) or scalar_integer(effect.get("Id")) in (None, 21):
                reason = t("Gesundheitsmodifikatoren verhindern eine sichere direkte Bearbeitung.")
    if "Health" in tag:
        reason = t("Der Datensatz enthält zusätzliche Gesundheitsfelder und wird vorsichtshalber nur angezeigt.")
    for name in ("Dead", "DeathTime"):
        if name in tag and scalar_integer(tag[name]) != 0:
            reason = t("Tote oder sterbende Kreaturen werden nicht verändert.")
    if reason:
        result.update(editable=False, max_editable=False, reason=reason)
    elif "DefaultMax" in attribute and _number(attribute["DefaultMax"]) != maximum:
        result.update(
            max_editable=False,
            max_reason=t("Die gespeicherte Standardobergrenze weicht vom Maximum ab; nur aktuelle Lebenspunkte sind bearbeitbar."),
        )
    return result


def _trade_recipes(tag: nbt.CompoundTag) -> nbt.ListTag | None:
    offers = tag.get("Offers")
    recipes = offers.get("Recipes") if isinstance(offers, nbt.CompoundTag) else None
    return recipes if isinstance(recipes, nbt.ListTag) else None


def _item_summary(item: Any, *, empty_as_none: bool = False) -> dict[str, Any] | None:
    if not isinstance(item, nbt.CompoundTag):
        return None
    name_tag = item.get("Name")
    name = name_tag.py_data if isinstance(name_tag, nbt.StringTag) else None
    count_tag = item.get("Count")
    count = scalar_integer(count_tag)
    if count is not None and isinstance(count_tag, nbt.ByteTag):
        count &= 0xFF
    if empty_as_none and (not item or (name in {"", "air", "minecraft:air"} and isinstance(count_tag, nbt.ByteTag) and count == 0)):
        return None
    return {"name": name, "count": count, "damage": scalar_integer(item.get("Damage"))}


def _equipment_slot_state(item: Any, summary: dict[str, Any] | None) -> str:
    if summary is None or summary["name"] is None or summary["count"] is None:
        return "unknown"
    name, count = summary["name"], summary["count"]
    if name not in ("", "air", "minecraft:air"):
        # Presence does not require the item to be vanilla, wearable, or known
        # to the editor's catalog. No equipment edit permission follows from it.
        return "occupied" if count > 0 and ITEM_ID_RE.fullmatch(name if ":" in name else f"minecraft:{name}") else "unknown"
    if count != 0 or not isinstance(item.get("Count"), nbt.ByteTag) or set(item) - {"Name", "Count", "Damage", "Slot", "WasPickedUp"}:
        return "unknown"
    if "Damage" in item and scalar_integer(item["Damage"]) != 0:
        return "unknown"
    if "Slot" in item and scalar_integer(item["Slot"]) is None:
        return "unknown"
    if "WasPickedUp" in item and (not isinstance(item["WasPickedUp"], nbt.ByteTag) or item["WasPickedUp"].py_data not in (0, 1)):
        return "unknown"
    return "empty"


def _equipment_state(tag: nbt.CompoundTag, *, include_slots: bool = True) -> dict[str, Any]:
    slots, containers, unknown_containers = [], [], []
    total = occupied_count = unknown_count = 0
    for name in ("Armor", "Mainhand", "Offhand"):
        equipment = tag.get(name)
        group = {"container": name, "present": name in tag, "total": 0, "occupied_count": 0, "unknown_count": 0, "truncated": False}
        if equipment is None:
            containers.append(group)
            continue
        if not isinstance(equipment, nbt.ListTag):
            group["total"] = None
            unknown_containers.append(name)
            containers.append(group)
            continue
        if equipment.list_data_type != nbt.CompoundTag.tag_id:
            unknown_containers.append(name)
        group["total"] = len(equipment)
        group["truncated"] = len(equipment) > MAX_DETAIL_ITEMS
        total += len(equipment)
        for index, item in enumerate(equipment):
            summary = _item_summary(item)
            state = _equipment_slot_state(item, summary)
            if state == "occupied":
                occupied_count += 1
                group["occupied_count"] += 1
            elif state == "unknown":
                unknown_count += 1
                group["unknown_count"] += 1
            if include_slots and index < MAX_DETAIL_ITEMS:
                slots.append({"slot": f"{name}[{index}]", "container": name, "index": index, "state": state, "item": summary})
        containers.append(group)
    return {
        "slots": slots,
        "containers": containers,
        "total": total,
        "occupied_count": occupied_count,
        "unknown_count": unknown_count,
        "unknown_containers": unknown_containers,
        "truncated": any(group["truncated"] for group in containers),
    }


def _village_dwellers(root: nbt.NamedTag) -> tuple[set[str], bool]:
    """Keep readable IDs as ambiguity evidence even in a partial record."""
    tag = root.tag
    if isinstance(tag, nbt.ListTag) and root.name == "Dwellers":
        groups = tag
    elif isinstance(tag, nbt.CompoundTag):
        groups = tag.get("Dwellers")
        if isinstance(groups, nbt.CompoundTag):
            groups = groups.get("Dwellers")
    else:
        return set(), False
    if not isinstance(groups, nbt.ListTag):
        return set(), False
    identities: set[str] = set()
    complete = True
    for group in groups:
        actors = group.get("actors") if isinstance(group, nbt.CompoundTag) else None
        if not isinstance(actors, nbt.ListTag):
            complete = False
            continue
        for actor in actors:
            identity = actor.get("ID") if isinstance(actor, nbt.CompoundTag) else None
            if not isinstance(identity, nbt.LongTag):
                complete = False
                continue
            identities.add(str(identity.py_data))
    return identities, complete


def _village_dimension(key_dimension: str | None, info: bytes | None) -> int | None:
    # Overworld is evidenced in Mojang's original MCPE-176528 report. Do not
    # guess dimension names in other formats or silently default old keys to 0.
    dimension = 0 if key_dimension == "Overworld" else None
    if info is None:
        return dimension
    try:
        root = nbt.load(info, **LOAD_KWARGS).tag
    except (nbt.NBTError, TypeError, OverflowError):
        return None
    if not isinstance(root, nbt.CompoundTag):
        return None
    info_tags = [root]
    if "data" in root:
        if not isinstance(root["data"], nbt.CompoundTag):
            return None
        info_tags.append(root["data"])
    # Both layouts are supported; neither may hide conflicting evidence from
    # the other when a saved record happens to contain both.
    fields = [info_tag[name] for info_tag in info_tags for name in ("Dimension", "DimensionId") if name in info_tag]
    if fields:
        dimensions = {scalar_integer(value) for value in fields}
        if None in dimensions or len(dimensions) != 1:
            return None
        explicit = next(iter(dimensions))
        if dimension is not None and explicit != dimension:
            return None
        return explicit
    return dimension


def _village_assignments(scan: EntityScan) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    assignments: dict[str, list[dict[str, Any]]] = {}
    ambiguous_ids: set[str] = set()
    for key, value in scan.village_records.items():
        if not key.endswith(b"_DWELLERS"):
            continue
        checkpoint()
        inhabitants: set[str] = set()
        try:
            root = nbt.load(value, **LOAD_KWARGS)
            inhabitants, complete = _village_dwellers(root)
            match = _VILLAGE_KEY.fullmatch(key.decode("ascii"))
            if match is None:
                raise ValueError("Unknown village key")
            if not complete:
                raise ValueError("Unknown dwellers structure")
        except (ValueError, TypeError, OverflowError):
            ambiguous_ids.update(inhabitants)
            scan.diagnose(issue("unsupported_village_record", "Ein Dorfdatensatz hat ein unbekanntes Format; daraus wird keine Dorfzugehörigkeit abgeleitet."))
            continue
        info = scan.village_records.get(key.removesuffix(b"_DWELLERS") + b"_INFO")
        dimension = _village_dimension(match["dimension"], info)
        if dimension is None:
            ambiguous_ids.update(inhabitants)
            scan.diagnose(
                issue("unknown_village_dimension", "Die Dimension eines gespeicherten Dorfes ist nicht eindeutig; seine Zuordnungen bleiben ungeprüft.")
            )
            continue
        village = {"id": match["id"].lower(), "dimension": dimension, "source": "DWELLERS", "label": t("Dorf {id}", id=match["id"][:8])}
        for identity in inhabitants:
            assignments.setdefault(identity, []).append(village)
    return assignments, ambiguous_ids


def _alias_key(record: EntityRecord) -> str | None:
    if record.storage != "legacy":
        return record.id
    # A legacy row ID addresses a slot in a chunk's entity list. Movement or
    # removal can give that same slot to another villager, so persistent aliases
    # must instead follow a correctly typed, globally unambiguous UniqueID.
    if not isinstance(record.tag.get("UniqueID"), nbt.LongTag) or any(item["code"] in {"missing_unique_id", "duplicate_unique_id"} for item in record.issues):
        return None
    return f"legacy-uid:{record.unique_id}"


def _project(record: EntityRecord, assignments: dict[str, list[dict[str, Any]]], ambiguous_village_ids: set[str]) -> dict[str, Any]:
    tag = record.tag
    custom_name = tag.get("CustomName")
    health = _health_state(tag)
    if record.issues:
        health.update(editable=False, max_editable=False, reason=record.issues[0]["message"])
    raw_tier = scalar_integer(tag.get("TradeTier"))
    tier = raw_tier if raw_tier is not None and 0 <= raw_tier < len(_TIERS) else None
    profession = _profession(record)
    no_trade_tier = profession["id"] in {"unemployed", "nitwit"}
    if no_trade_tier:
        tier = None
    career = _career_state(record)
    equipment = _equipment_state(tag, include_slots=False)
    recipes = _trade_recipes(tag)
    candidate_villages = assignments.get(record.unique_id, [])
    village = None
    village_status = "unassigned"
    if candidate_villages or record.unique_id in ambiguous_village_ids:
        if (
            len(candidate_villages) == 1
            and candidate_villages[0]["dimension"] == record.dimension
            and record.unique_id not in ambiguous_village_ids
            # Numeric IDs from unsupported tag types still participate in
            # duplicate detection, but cannot prove a village membership.
            # Likewise, a chunk index cannot override a conflicting actor
            # dimension merely because it matches the village record.
            and not any(i["code"] in {"duplicate_unique_id", "missing_unique_id", "dimension_mismatch"} for i in record.issues)
        ):
            village = candidate_villages[0]
            village_status = "verified"
        else:
            village_status = "ambiguous"
    return {
        "id": record.id,
        "alias_key": _alias_key(record),
        "revision": record.revision,
        "unique_id": record.unique_id,
        "identifier": record.identifier,
        "name": custom_name.py_data if isinstance(custom_name, nbt.StringTag) else "",
        "name_editable": _name_reason(record) is None,
        "name_reason": _name_reason(record),
        "profession": profession,
        "trade_tier": tier,
        "trade_tier_label": t("Keine Handelsstufe") if no_trade_tier else t(_TIERS[tier]) if tier is not None else t("Unbekannt"),
        "trade_experience": scalar_integer(tag.get("TradeExperience")),
        "career": career,
        "career_editable": career["editable"],
        "health": health,
        "position": entity_position(tag),
        "dimension": record.dimension,
        "is_baby": _is_baby(tag),
        "storage": record.storage,
        "village": village,
        "village_status": village_status,
        "village_reason": None if village else t("Keine eindeutige Dorfzugehörigkeit aus gespeicherten Bewohner-IDs und passender Dimension nachgewiesen."),
        "editable": bool(health["editable"]),
        "inventory_editable": _inventory_state(record)["editable"],
        "issues": list(record.issues),
        "trade_count": len(recipes) if recipes is not None else 0,
        "equipment_count": equipment["occupied_count"],
    }


def _scan(db: Any) -> tuple[EntityScan, dict[str, dict[str, Any]]]:
    scan = scan_entities(db, identifiers=VILLAGER_IDENTIFIERS)
    assignments, ambiguous = _village_assignments(scan)
    rows = {identity: _project(record, assignments, ambiguous) for identity, record in scan.records.items()}
    return scan, rows


def scan_villagers(db: Any) -> dict[str, Any]:
    scan, rows = _scan(db)
    return scan_result(scan, rows)


def scan_result(scan: EntityScan, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the public list from one validated entity snapshot."""
    villagers = list(rows.values())
    return {
        "villagers": villagers,
        "diagnostics": scan.diagnostics,
        "summary": {
            "total": len(villagers),
            "injured": sum(
                row["health"]["current"] is not None and row["health"]["max"] is not None and 0 < row["health"]["current"] < row["health"]["max"]
                for row in villagers
            ),
            "editable": sum(row["editable"] or row["inventory_editable"] or row["name_editable"] or row["career_editable"] for row in villagers),
            "villages": len({(row["village"]["dimension"], row["village"]["id"]) for row in villagers if row["village"]}),
            "diagnostic_count": scan.diagnostic_count,
            "diagnostics_truncated": scan.diagnostic_count > len(scan.diagnostics),
            "scanned_entities": scan.scanned_entities,
            "scanned_records": scan.scanned_records,
            "legacy_records": scan.legacy_records,
        },
    }


def _read_details(record: EntityRecord, projection: dict[str, Any]) -> dict[str, Any]:
    tag = record.tag
    recipes = _trade_recipes(tag)
    offers = []
    if recipes is not None:
        for index in range(min(len(recipes), MAX_DETAIL_ITEMS)):
            recipe = recipes[index]
            if not isinstance(recipe, nbt.CompoundTag):
                offers.append({"index": index, "unsupported": True})
                continue
            offers.append(
                {
                    "index": index,
                    "buy_a": _item_summary(recipe.get("buyA")),
                    "buy_b": _item_summary(recipe.get("buyB"), empty_as_none=True),
                    "sell": _item_summary(recipe.get("sell")),
                    "uses": scalar_integer(recipe.get("uses")),
                    "max_uses": scalar_integer(recipe.get("maxUses")),
                    "tier": scalar_integer(recipe.get("tier")),
                    "trader_experience": scalar_integer(recipe.get("traderExp")),
                }
            )
    equipment = _equipment_state(tag)
    return {
        **projection,
        "career": _career_state(record, include_options=True),
        "inventory": _inventory_state(record),
        "trades": {
            "offers": offers,
            "total": len(recipes) if recipes is not None else 0,
            "truncated": recipes is not None and len(recipes) > MAX_DETAIL_ITEMS,
            "raw": nbt_view_value(tag["Offers"]) if "Offers" in tag else None,
        },
        "equipment": {
            **equipment,
            "raw": nbt_view_value(nbt.CompoundTag({key: tag[key] for key in ("Armor", "Mainhand", "Offhand") if key in tag})),
        },
        "nbt": nbt_view_value(tag),
    }


def load_villager_detail(db: Any, identifier: str, revision: str | None = None) -> dict[str, Any]:
    scan, rows = _scan(db)
    if not isinstance(identifier, str) or identifier not in rows:
        raise ValueError(t("Der ausgewählte Dorfbewohner ist nicht mehr vorhanden. Bitte neu scannen."))
    if revision is not None and revision != rows[identifier]["revision"]:
        raise ValueError(t("Der Dorfbewohner wurde seit dem Scan verändert. Bitte neu scannen."))
    return _read_details(scan.records[identifier], rows[identifier])


def normalize_health_changes(changes: Any) -> dict[str, float | bool]:
    if not isinstance(changes, dict) or set(changes) - {"max_health", "current_health", "heal"}:
        raise ValueError(t("Ungültige Gesundheitsänderung. Erlaubt sind aktuelle Lebenspunkte, Maximum und vollständiges Heilen."))
    normalized: dict[str, float | bool] = {}
    for name in ("max_health", "current_health"):
        if name not in changes:
            continue
        value = changes[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(t("Lebenspunkte müssen als endliche Zahl zwischen 1 und 2048 angegeben werden."))
        try:
            value = float(value)
        except (ValueError, OverflowError) as exc:
            raise ValueError(t("Lebenspunkte müssen als endliche Zahl zwischen 1 und 2048 angegeben werden.")) from exc
        if not math.isfinite(value) or not 1 <= value <= MAX_HEALTH:
            raise ValueError(t("Lebenspunkte müssen als endliche Zahl zwischen 1 und 2048 angegeben werden."))
        normalized[name] = float(nbt.FloatTag(value).py_data)
    if "heal" in changes:
        if not isinstance(changes["heal"], bool):
            raise ValueError(t("Vollständiges Heilen muss als Boolean angegeben werden."))
        if changes["heal"]:
            if "current_health" in normalized:
                raise ValueError(t("Aktuelle Lebenspunkte und vollständiges Heilen dürfen nicht gleichzeitig gesetzt werden."))
            normalized["heal"] = True
    if not normalized:
        raise ValueError(t("Es wurde keine Gesundheitsänderung angegeben."))
    if "current_health" in normalized and "max_health" in normalized and normalized["current_health"] > normalized["max_health"]:
        raise ValueError(t("Die aktuellen Lebenspunkte dürfen das neue Maximum nicht überschreiten."))
    return normalized


def _selection(selection: Any) -> list[dict[str, str]]:
    if not isinstance(selection, list) or not 1 <= len(selection) <= MAX_SELECTION:
        raise ValueError(t("Wähle zwischen 1 und 1000 Dorfbewohnern für eine Änderung aus."))
    result = []
    seen = set()
    for item in selection:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "revision"}
            or not isinstance(item.get("id"), str)
            or not 1 <= len(item["id"]) <= 512
            or not isinstance(item.get("revision"), str)
            or not _REVISION.fullmatch(item["revision"])
        ):
            raise ValueError(t("Die Auswahl enthält keine gültige Bewohner-ID und Datensatzrevision."))
        if item["id"] in seen:
            raise ValueError(t("Ein Dorfbewohner darf in einer Änderung nur einmal ausgewählt werden."))
        seen.add(item["id"])
        result.append({"id": item["id"], "revision": item["revision"]})
    return result


def _patch_health(record: EntityRecord, row: dict[str, Any], changes: dict[str, float | bool]) -> tuple[bytes | None, dict[str, float] | None, str | None]:
    if not row["editable"]:
        return None, None, row["health"]["reason"]
    root = nbt.load(record.value, **LOAD_KWARGS)
    if root.save_to(**SAVE_KWARGS) != record.value:
        return None, None, t("Der Datensatz lässt sich nicht verlustfrei zurückschreiben und bleibt unverändert.")
    attribute = _health_attribute(root.tag)
    if attribute is None:
        raise ValueError(t("Das Gesundheitsattribut konnte nicht erneut eindeutig gelesen werden."))
    old_maximum = row["health"]["max"]
    maximum = changes.get("max_health", old_maximum)
    current = maximum if changes.get("heal") else changes.get("current_health", min(row["health"]["current"], maximum))
    if current > maximum:
        return None, None, t("Die gewünschten aktuellen Lebenspunkte würden das gespeicherte Maximum überschreiten.")
    minimum = _number(attribute.get("Min")) if "Min" in attribute else 0.0
    base = _number(attribute.get("Base"))
    default_minimum = _number(attribute.get("DefaultMin"))
    if (
        (minimum is not None and (current < minimum or maximum < minimum))
        or (base is not None and maximum < base)
        or (default_minimum is not None and (current < default_minimum or maximum < default_minimum))
    ):
        return None, None, t("Die Änderung würde vorhandene Gesundheitsgrenzen oder den Basiswert unterschreiten.")
    if maximum != old_maximum and not row["health"]["max_editable"]:
        return None, None, row["health"].get("max_reason")
    # Materialize omitted defaults only for an actual change. Base, every
    # unrelated NBT field, names, trades and all actor indexes stay untouched.
    if current != row["health"]["current"]:
        attribute["Current"] = nbt.FloatTag(current)
    if maximum != old_maximum:
        attribute["Max"] = nbt.FloatTag(maximum)
        if "DefaultMax" in attribute:
            attribute["DefaultMax"] = nbt.FloatTag(maximum)
    return root.save_to(**SAVE_KWARGS), {"current": float(current), "max": float(maximum)}, None


def prepare_health_changes(db: Any, selection: Any, changes: Any, *, _snapshot: tuple[EntityScan, dict[str, dict[str, Any]]] | None = None) -> HealthChangePlan:
    normalized = normalize_health_changes(changes)
    selected = _selection(selection)
    scan, projections = _scan(db) if _snapshot is None else _snapshot
    # A stale/deleted selection aborts the entire request, before preparing any
    # writes. Deliberate read-only skips are distinct from a lost revision.
    for item in selected:
        current = projections.get(item["id"])
        if current is None or current["revision"] != item["revision"]:
            raise ValueError(t("Mindestens ein ausgewählter Dorfbewohner fehlt oder wurde seit dem Scan verändert. Bitte neu scannen."))
    writes: dict[bytes, bytes] = {}
    before_records: dict[bytes, bytes] = {}
    rows: list[dict[str, Any]] = []
    summary = {"selected": len(selected), "changed": 0, "skipped": 0, "unchanged": 0}
    for item in selected:
        checkpoint()
        record = scan.records[item["id"]]
        projection = projections[item["id"]]
        before_records[record.key] = record.value
        for reference in record.references:
            if reference.key in scan.index_records:
                before_records[reference.key] = scan.index_records[reference.key]
        raw, after, reason = _patch_health(record, projection, normalized)
        status = "skipped" if raw is None else "unchanged" if raw == record.value else "changed"
        summary[status] += 1
        if status == "changed":
            writes[record.key] = raw
        before = {"current": projection["health"]["current"], "max": projection["health"]["max"]}
        rows.append(
            {
                "id": record.id,
                "name": projection["name"],
                "revision": record.revision,
                "status": status,
                "before": before,
                "after": after if after is not None else before.copy(),
                "reason": reason,
            }
        )
    return HealthChangePlan(writes, before_records, rows, normalized, summary)


def _entity_write_reason(record: EntityRecord) -> str | None:
    reason = None
    if record.issues:
        reason = record.issues[0]["message"]
    elif record.storage != "actor" or record.identifier != "minecraft:villager_v2":
        reason = t("Nur eindeutig gespeicherte moderne Dorfbewohner können bearbeitet werden.")
    elif any(name in record.tag and scalar_integer(record.tag[name]) != 0 for name in ("Dead", "DeathTime")):
        reason = t("Tote oder sterbende Kreaturen werden nicht verändert.")
    else:
        health = _health_attribute(record.tag)
        current = _number(_health_value_tag(health, "Current", "Base")) if health is not None else None
        if current is not None and current <= 0:
            reason = t("Tote oder sterbende Kreaturen werden nicht verändert.")
    return reason


def _inventory_state(record: EntityRecord) -> dict[str, Any]:
    return inventory_state(record.tag, blocked_reason=_entity_write_reason(record))


def _career_state(record: EntityRecord, *, include_options: bool = False) -> dict[str, Any]:
    state = career_state(record.tag, blocked_reason=_entity_write_reason(record), is_baby=_is_baby(record.tag), include_options=include_options)
    # Read-only legacy/ambiguous actors must not acquire a modern profession
    # merely because their Variant happens to have the same numeric value.
    if record.identifier != "minecraft:villager_v2":
        state["profession"] = _profession(record)["id"]
        raw_tier = scalar_integer(record.tag.get("TradeTier"))
        state["trade_tier"] = raw_tier if raw_tier is not None and 0 <= raw_tier < len(_TIERS) and state["profession"] not in {"unemployed", "nitwit"} else None
    return state


def _name_reason(record: EntityRecord) -> str | None:
    reason = _entity_write_reason(record)
    if reason:
        return reason
    if "CustomName" in record.tag and not isinstance(record.tag["CustomName"], nbt.StringTag):
        return t("Der gespeicherte Name hat ein unbekanntes Format und bleibt geschützt.")
    return None


def normalize_name_changes(changes: Any) -> dict[str, str]:
    if not isinstance(changes, dict) or set(changes) != {"name"} or not isinstance(changes["name"], str):
        raise ValueError(t("Für eine Namensänderung ist genau ein Textwert erforderlich."))
    name = changes["name"]
    # Reject controls before trimming; never silently turn malformed input into
    # a removal. Format characters (e.g. emoji joiners) remain valid Unicode.
    if any(unicodedata.category(char) in {"Cc", "Cs"} or char in "\u2028\u2029" for char in name):
        raise ValueError(t("Der Name darf keine Zeilenumbrüche oder Steuerzeichen enthalten."))
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(t("Der Name darf höchstens 80 Zeichen enthalten."))
    return {"name": name}


def _prepare_name_changes(db: Any, selection: Any, changes: Any, *, _snapshot: tuple[EntityScan, dict[str, dict[str, Any]]] | None = None) -> HealthChangePlan:
    normalized = normalize_name_changes(changes)
    selected = _selection(selection)
    if len(selected) != 1:
        raise ValueError(t("Namen können nur für einen Dorfbewohner gleichzeitig geändert werden."))
    scan, projections = _scan(db) if _snapshot is None else _snapshot
    chosen = selected[0]
    projection = projections.get(chosen["id"])
    if projection is None or projection["revision"] != chosen["revision"]:
        raise ValueError(t("Der Dorfbewohner wurde seit dem Scan verändert. Bitte neu scannen."))
    record = scan.records[chosen["id"]]
    before = {"name": projection["name"]}
    after = before.copy()
    reason = _name_reason(record)
    raw = None
    if reason is None:
        root = nbt.load(record.value, **LOAD_KWARGS)
        if root.save_to(**SAVE_KWARGS) != record.value:
            reason = t("Der Datensatz lässt sich nicht verlustfrei zurückschreiben und bleibt unverändert.")
        else:
            if normalized != before:
                if normalized["name"]:
                    root.tag["CustomName"] = literal_string_tag(normalized["name"])
                elif "CustomName" in root.tag:
                    del root.tag["CustomName"]
            raw = root.save_to(**SAVE_KWARGS)
            after = normalized.copy()
    status = "skipped" if raw is None else "unchanged" if raw == record.value else "changed"
    before_records = {record.key: record.value}
    before_records.update({reference.key: scan.index_records[reference.key] for reference in record.references if reference.key in scan.index_records})
    row = {
        "id": record.id,
        "name": projection["name"],
        "revision": record.revision,
        "kind": "name",
        "status": status,
        "before": before,
        "after": after,
        "reason": reason,
    }
    return HealthChangePlan(
        {record.key: raw} if raw is not None and raw != record.value else {},
        before_records,
        [row],
        normalized,
        {"selected": 1, "changed": int(status == "changed"), "skipped": int(status == "skipped"), "unchanged": int(status == "unchanged")},
    )


def _prepare_inventory_changes(
    db: Any, selection: Any, changes: Any, *, _snapshot: tuple[EntityScan, dict[str, dict[str, Any]]] | None = None
) -> HealthChangePlan:
    normalized = normalize_inventory_changes(changes)
    selected = _selection(selection)
    if len(selected) != 1:
        raise ValueError(t("Vorräte können nur für einen Dorfbewohner gleichzeitig geändert werden."))
    scan, projections = _scan(db) if _snapshot is None else _snapshot
    chosen = selected[0]
    projection = projections.get(chosen["id"])
    if projection is None or projection["revision"] != chosen["revision"]:
        raise ValueError(t("Der Dorfbewohner wurde seit dem Scan verändert. Bitte neu scannen."))
    record = scan.records[chosen["id"]]
    state = _inventory_state(record)
    slots = [{"slot": patch["slot"], "item": state["slots"][patch["slot"]]["item"]} for patch in normalized["inventory"]]
    before = {"slots": slots}
    reason = state["reason"]
    if not state["editable"]:
        reason = reason or t("Das Vorratsinventar kann nicht sicher bearbeitet werden.")
    for patch in normalized["inventory"]:
        if not state["slots"][patch["slot"]]["editable"]:
            reason = reason or state["slots"][patch["slot"]]["reason"]
    raw, after = None, before
    if reason is None:
        root = nbt.load(record.value, **LOAD_KWARGS)
        if root.save_to(**SAVE_KWARGS) != record.value:
            reason = t("Der Datensatz lässt sich nicht verlustfrei zurückschreiben und bleibt unverändert.")
        else:
            patch_inventory(root.tag, normalized["inventory"])
            raw = root.save_to(**SAVE_KWARGS)
            result = inventory_state(root.tag)
            after = {"slots": [{"slot": patch["slot"], "item": result["slots"][patch["slot"]]["item"]} for patch in normalized["inventory"]]}
    status = "skipped" if raw is None else "unchanged" if raw == record.value else "changed"
    before_records = {record.key: record.value}
    before_records.update({reference.key: scan.index_records[reference.key] for reference in record.references if reference.key in scan.index_records})
    row = {
        "id": record.id,
        "name": projection["name"],
        "revision": record.revision,
        "kind": "inventory",
        "status": status,
        "before": before,
        "after": after,
        "reason": reason,
    }
    return HealthChangePlan(
        {record.key: raw} if raw is not None and raw != record.value else {},
        before_records,
        [row],
        normalized,
        {"selected": 1, "changed": int(status == "changed"), "skipped": int(status == "skipped"), "unchanged": int(status == "unchanged")},
    )


def _prepare_career_changes(
    db: Any, selection: Any, changes: Any, *, _snapshot: tuple[EntityScan, dict[str, dict[str, Any]]] | None = None
) -> HealthChangePlan:
    normalized = normalize_career_changes(changes)
    selected = _selection(selection)
    scan, projections = _scan(db) if _snapshot is None else _snapshot
    for item in selected:
        current = projections.get(item["id"])
        if current is None or current["revision"] != item["revision"]:
            raise ValueError(t("Mindestens ein ausgewählter Dorfbewohner fehlt oder wurde seit dem Scan verändert. Bitte neu scannen."))
    writes, before_records, rows = {}, {}, []
    summary = {"selected": len(selected), "changed": 0, "skipped": 0, "unchanged": 0}
    for item in selected:
        checkpoint()
        record, projection = scan.records[item["id"]], projections[item["id"]]
        state = projection["career"]
        before = career_summary(state)
        if record.identifier != "minecraft:villager_v2":
            before.update(profession=projection["profession"]["id"], profession_label=projection["profession"]["label"])
        after, warnings, raw, reason = before.copy(), [], None, state["reason"]
        if reason is None:
            root = nbt.load(record.value, **LOAD_KWARGS)
            if root.save_to(**SAVE_KWARGS) != record.value:
                reason = t("Der Datensatz lässt sich nicht verlustfrei zurückschreiben und bleibt unverändert.")
            else:
                after, warnings, reason = patch_career(root.tag, normalized["career"], state)
                if reason is None:
                    raw = root.save_to(**SAVE_KWARGS)
        status = "skipped" if raw is None else "unchanged" if raw == record.value else "changed"
        summary[status] += 1
        if status == "changed":
            writes[record.key] = raw
        before_records[record.key] = record.value
        before_records.update({reference.key: scan.index_records[reference.key] for reference in record.references if reference.key in scan.index_records})
        rows.append(
            {
                "id": record.id,
                "name": projection["name"],
                "revision": record.revision,
                "kind": "career",
                "status": status,
                "before": before,
                "after": after,
                "reason": reason,
                "warnings": warnings,
            }
        )
    return HealthChangePlan(writes, before_records, rows, normalized, summary)


def prepare_villager_changes(
    db: Any, selection: Any, changes: Any, *, _snapshot: tuple[EntityScan, dict[str, dict[str, Any]]] | None = None
) -> HealthChangePlan:
    # A workspace may share its one fresh scan across disjoint field plans.
    # Retained UI snapshots must never be supplied for write authorization.
    if isinstance(changes, dict) and "career" in changes:
        return _prepare_career_changes(db, selection, changes, _snapshot=_snapshot)
    if isinstance(changes, dict) and "name" in changes:
        return _prepare_name_changes(db, selection, changes, _snapshot=_snapshot)
    if isinstance(changes, dict) and "inventory" in changes:
        return _prepare_inventory_changes(db, selection, changes, _snapshot=_snapshot)
    return prepare_health_changes(db, selection, changes, _snapshot=_snapshot)
