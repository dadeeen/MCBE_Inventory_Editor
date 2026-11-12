"""Scoped edits of vanilla Bedrock villager professions and trading progress.

Profession component groups and table paths follow Mojang's villager_v2.json;
all thirteen vanilla economy tables use the same five experience thresholds.
https://github.com/Mojang/bedrock-samples/tree/main/behavior_pack
"""

from __future__ import annotations

from typing import Any

from . import nbt
from .i18n import t
from .inventory import ITEM_ID_RE

CAREER_FIELDS = frozenset({"Variant", "PreferredProfession", "TradeTablePath", "TradeTier", "TradeExperience", "Offers", "definitions"})
TIER_EXPERIENCE = (0, 10, 70, 150, 250)
TIER_LABELS = ("Neuling", "Lehrling", "Geselle", "Experte", "Meister")
# Tuple position is the modern villager Variant. Nitwits are intentionally not
# a target: their inability to work is part of ordinary villager behavior.
PROFESSIONS = (
    ("unemployed", "Arbeitslos", "Kein Arbeitsplatz", ""),
    ("farmer", "Farmer", "Komposter", "farmer"),
    ("fisherman", "Fischer", "Fass", "fisherman"),
    ("shepherd", "Schäfer", "Webstuhl", "shepherd"),
    ("fletcher", "Pfeilmacher", "Bognertisch", "fletcher"),
    ("librarian", "Bibliothekar", "Lesepult", "librarian"),
    ("cartographer", "Kartograf", "Kartentisch", "cartographer"),
    ("cleric", "Geistlicher", "Braustand", "cleric"),
    ("armorer", "Rüstungsschmied", "Schmelzofen", "armorer"),
    ("weaponsmith", "Waffenschmied", "Schleifstein", "weapon_smith"),
    ("toolsmith", "Werkzeugschmied", "Schmiedetisch", "tool_smith"),
    ("butcher", "Metzger", "Räucherofen", "butcher"),
    ("leatherworker", "Gerber", "Kessel", "leather_worker"),
    ("mason", "Steinmetz", "Steinsäge", "stone_mason"),
)
_BY_ID = {entry[0]: (variant, *entry[1:]) for variant, entry in enumerate(PROFESSIONS)}
_PROFESSION_GROUPS = frozenset({"unskilled", "nitwit", *[entry[0] for entry in PROFESSIONS[1:]]})
_CAREER_GROUPS = _PROFESSION_GROUPS | {
    "behavior_peasant",
    "behavior_non_peasant",
    "basic_schedule",
    "jobless_schedule",
    "work_schedule",
    "farmer_schedule",
    "fisher_schedule",
    "librarian_schedule",
    "work_schedule_farmer",
    "work_schedule_fisher",
    "work_schedule_librarian",
    "work_schedule_villager",
    "job_specific_goals",
    "trade_components",
    "trade_resupply_component_group",
}
_VANILLA_GROUPS = _CAREER_GROUPS | {
    "villager_v2",
    "adult",
    "baby",
    "child_schedule",
    "make_and_receive_love",
    "become_witch",
    "become_zombie",
    "bed_schedule_villager",
    "gather_schedule_villager",
    "home_schedule_villager",
    "play_schedule_villager",
    "wander_schedule_villager",
    "desert_villager",
    "jungle_villager",
    "savanna_villager",
    "snow_villager",
    "swamp_villager",
    "taiga_villager",
    "celebrate",
    *{f"villager_skin_{index}" for index in range(6)},
}


def normalize_career_changes(changes: Any) -> dict[str, Any]:
    if not isinstance(changes, dict) or set(changes) != {"career"} or not isinstance(changes["career"], dict):
        raise ValueError(t("Für Beruf und Handelsstufe ist genau eine Berufsänderung erforderlich."))
    career = changes["career"]
    if not career or set(career) - {"profession", "trade_tier"}:
        raise ValueError(t("Wähle einen Beruf oder eine Handelsstufe aus."))
    if "profession" in career and (not isinstance(career["profession"], str) or career["profession"] not in _BY_ID):
        raise ValueError(t("Der ausgewählte Beruf wird nicht unterstützt."))
    if "trade_tier" in career and (type(career["trade_tier"]) is not int or not 0 <= career["trade_tier"] < len(TIER_EXPERIENCE)):
        raise ValueError(t("Die Handelsstufe muss zwischen Neuling und Meister liegen."))
    if career.get("profession") == "unemployed" and career.get("trade_tier", 0) != 0:
        raise ValueError(t("Arbeitslose Dorfbewohner haben keine Handelsstufe."))
    return {"career": dict(career)}


def _int_value(tag: nbt.CompoundTag, name: str, default: int) -> int | None:
    value = tag.get(name)
    return default if value is None else value.py_data if isinstance(value, nbt.IntTag) else None


def _active_groups(tag: nbt.CompoundTag) -> set[str] | None:
    definitions = tag.get("definitions")
    if not isinstance(definitions, nbt.ListTag) or not definitions:
        return None
    active: set[str] = set()
    for value in definitions:
        if not isinstance(value, nbt.StringTag) or not value.py_data.startswith(("+", "-")):
            return None
        operation, name = value.py_data[0], value.py_data[1:].removeprefix("minecraft:")
        if not name:
            continue
        if name not in _VANILLA_GROUPS:
            return None
        if operation == "+":
            active.add(name)
        else:
            active.discard(name)
    return active


def _table_path(profession: str) -> str:
    table = _BY_ID[profession][3]
    return f"trading/economy_trades/{table}_trades.json" if table else ""


def _trade_item_supported(item: Any, *, optional: bool = False) -> bool:
    """Check the saved stack envelope without rewriting variant or tag data.

    Native recipes may omit their second input or store an explicit empty
    stack. A positive tier and an XP threshold alone do not establish that an
    offer actually has something to buy and sell. This is a structure check,
    not proof that a saved recipe came from a particular Vanilla trade table.
    """
    if not isinstance(item, nbt.CompoundTag):
        return False
    if optional and not item:
        return True
    name, count = item.get("Name"), item.get("Count")
    if not isinstance(name, nbt.StringTag) or not isinstance(count, nbt.ByteTag):
        return False
    name, count = name.py_data, count.py_data & 0xFF
    if name in {"", "air", "minecraft:air"}:
        return optional and count == 0
    return count > 0 and bool(ITEM_ID_RE.fullmatch(name if ":" in name else f"minecraft:{name}"))


def _offers_state(tag: nbt.CompoundTag) -> tuple[int, bool, str | None]:
    offers = tag.get("Offers")
    if offers is None:
        return 0, False, None
    if not isinstance(offers, nbt.CompoundTag) or not isinstance(offers.get("Recipes"), nbt.ListTag):
        return 0, False, t("Die gespeicherten Handelsangebote haben ein unbekanntes Format.")
    recipes = offers["Recipes"]
    tiers: set[int] = set()
    for recipe in recipes:
        if not isinstance(recipe, nbt.CompoundTag) or not isinstance(recipe.get("tier"), nbt.IntTag) or not 0 <= recipe["tier"].py_data < 5:
            return len(recipes), False, t("Die gespeicherten Handelsangebote haben ein unbekanntes Format.")
        if (
            not _trade_item_supported(recipe.get("buyA"))
            or not _trade_item_supported(recipe.get("sell"))
            or ("buyB" in recipe and not _trade_item_supported(recipe["buyB"], optional=True))
        ):
            return len(recipes), False, t("Die gespeicherten Handelsangebote haben ein unbekanntes Format.")
        tiers.add(recipe["tier"].py_data)
    requirements = offers.get("TierExpRequirements")
    valid_requirements = (
        isinstance(requirements, nbt.ListTag)
        and len(requirements) == len(TIER_EXPERIENCE)
        and all(
            isinstance(entry, nbt.CompoundTag)
            and set(entry) == {str(index)}
            and isinstance(entry[str(index)], nbt.IntTag)
            and entry[str(index)].py_data == threshold
            for index, (entry, threshold) in enumerate(zip(requirements, TIER_EXPERIENCE, strict=True))
        )
    )
    if requirements is not None and not valid_requirements:
        return len(recipes), False, t("Die gespeicherten Stufengrenzen entsprechen nicht den unterstützten Vanilla-Handelstabellen.")
    return len(recipes), bool(valid_requirements and tiers == set(range(5))), None


def career_state(tag: nbt.CompoundTag, *, blocked_reason: str | None = None, is_baby: bool | None = None, include_options: bool = False) -> dict[str, Any]:
    variant = _int_value(tag, "Variant", 0)
    profession = PROFESSIONS[variant][0] if variant is not None and 0 <= variant < len(PROFESSIONS) else "nitwit" if variant == 14 else "unknown"
    tier, experience = _int_value(tag, "TradeTier", 0), _int_value(tag, "TradeExperience", 0)
    count, complete_offers, offers_reason = _offers_state(tag)
    active = _active_groups(tag)
    reason = blocked_reason
    if reason is None and is_baby is not False:
        reason = t("Nur eindeutig erwachsene Dorfbewohner können Beruf und Handelsstufe ändern.")
    if reason is None and "Age" in tag and (not isinstance(tag["Age"], nbt.IntTag) or tag["Age"].py_data < 0):
        reason = t("Die gespeicherten Altersangaben sind widersprüchlich oder nicht eindeutig lesbar.")
    if reason is None and profession == "nitwit":
        reason = t("Nichtsnutze erlernen im Originalspiel keinen Beruf und bleiben hier geschützt.")
    if reason is None and profession not in _BY_ID:
        reason = t("Der gespeicherte Beruf hat ein unbekanntes Format.")
    if reason is None and (tier is None or not 0 <= tier < 5 or experience is None or experience < 0):
        reason = t("Die gespeicherte Handelsstufe oder Handelserfahrung ist nicht eindeutig lesbar.")
    if reason is None and (
        experience < TIER_EXPERIENCE[tier]
        or (tier < 4 and experience >= TIER_EXPERIENCE[tier + 1])
        or (profession == "unemployed" and (tier != 0 or experience != 0))
    ):
        reason = t("Die gespeicherte Handelsstufe und Handelserfahrung passen nicht zusammen.")
    expected_group = "unskilled" if profession == "unemployed" else profession
    if reason is None and (
        active is None or active & _PROFESSION_GROUPS != {expected_group} or active & {"baby", "child_schedule", "become_witch", "become_zombie"}
    ):
        reason = t("Die gespeicherten Berufskomponenten sind unbekannt oder widersprüchlich.")
    for name in ("PreferredProfession", "TradeTablePath"):
        if reason is None and name in tag and not isinstance(tag[name], nbt.StringTag):
            reason = t("Die gespeicherte Berufsvorgabe oder Handelstabelle hat ein unbekanntes Format.")
    if (
        reason is None
        and "PreferredProfession" in tag
        and tag["PreferredProfession"].py_data not in {"", profession, "unskilled" if profession == "unemployed" else profession}
    ):
        reason = t("Die gespeicherte Berufsvorgabe passt nicht zum angezeigten Beruf.")
    if reason is None and "TradeTablePath" in tag and tag["TradeTablePath"].py_data != _table_path(profession):
        reason = t("Eigene oder abweichende Handelstabellen werden nur angezeigt und bleiben geschützt.")
    if reason is None and "Offers" in tag and profession != "unemployed" and "TradeTablePath" not in tag:
        reason = t("Die Herkunft der gespeicherten Handelsangebote ist nicht eindeutig.")
    reason = reason or offers_reason
    tier_reason = reason
    if tier_reason is None and profession == "unemployed":
        tier_reason = t("Wähle zuerst einen Beruf; arbeitslose Dorfbewohner handeln nicht.")
    if tier_reason is None and not complete_offers:
        tier_reason = t("Minecraft muss zunächst vollständige Handelsangebote für alle fünf Stufen erzeugen.")
    result = {
        "editable": reason is None,
        "reason": reason,
        "profession_editable": reason is None,
        "profession_reason": reason,
        "tier_editable": tier_reason is None,
        "tier_reason": tier_reason,
        "can_set_tier_on_profession_change": reason is None,
        "profession": profession,
        "trade_tier": tier,
        "trade_experience": experience,
        "trade_count": count,
        "traded": experience is not None and experience > 0,
    }
    if include_options:
        result["professions"] = [{"id": identity, "label": t(label), "job_site": t(site)} for identity, label, site, _table in PROFESSIONS]
        result["tiers"] = [{"value": value, "label": t(label), "minimum_experience": TIER_EXPERIENCE[value]} for value, label in enumerate(TIER_LABELS)]
    return result


def career_summary(state: dict[str, Any]) -> dict[str, Any]:
    profession, tier = state["profession"], state["trade_tier"]
    label = _BY_ID[profession][1] if profession in _BY_ID else "Nichtsnutz" if profession == "nitwit" else "Unbekannt"
    return {
        "profession": profession,
        "profession_label": t(label),
        "trade_tier": tier,
        "trade_tier_label": t("Keine Handelsstufe")
        if profession in {"unemployed", "nitwit"}
        else t(TIER_LABELS[tier])
        if tier is not None and 0 <= tier < 5
        else t("Unbekannt"),
        "trade_experience": state["trade_experience"],
        "trade_count": state["trade_count"],
    }


def _reset_definitions(tag: nbt.CompoundTag, profession: str) -> None:
    # Retain biome, skin, home/bed state and unrelated native groups in order.
    # A reload starts with the retained definitions, without any old profession
    # or profession-specific work goal. Follow vanilla become_* group choices.
    values = [value for value in tag["definitions"] if value.py_data[1:].removeprefix("minecraft:") not in _CAREER_GROUPS]
    group = "unskilled" if profession == "unemployed" else profession
    behavior = "behavior_peasant" if profession in {"unemployed", "farmer"} else "behavior_non_peasant"
    schedule = {"unemployed": "basic_schedule", "farmer": "farmer_schedule", "fisherman": "fisher_schedule", "librarian": "librarian_schedule"}.get(
        profession, "work_schedule"
    )
    active = _active_groups(tag) or set()
    values.extend(nbt.StringTag("+" + name) for name in ("adult", "make_and_receive_love") if name not in active)
    values.extend(nbt.StringTag("+" + name) for name in (group, behavior, schedule))
    tag["definitions"] = nbt.ListTag(values, nbt.StringTag.tag_id)


def patch_career(tag: nbt.CompoundTag, changes: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], list[str], str | None]:
    """Patch a separately decoded source root; callers enforce lossless roundtrip."""
    profession = changes.get("profession", state["profession"])
    switched = profession != state["profession"]
    tier = changes.get("trade_tier", 0 if switched else state["trade_tier"])
    if profession == "unemployed" and tier != 0:
        return career_summary(state), [], t("Arbeitslose Dorfbewohner haben keine Handelsstufe.")
    if state["reason"]:
        return career_summary(state), [], state["reason"]
    if not switched and tier == state["trade_tier"]:
        return career_summary(state), [], None
    reason = state["profession_reason"] if switched else state["tier_reason"]
    if reason:
        return career_summary(state), [], reason
    warnings: list[str] = []
    if switched:
        variant, _label, site, _table = _BY_ID[profession]
        tag["Variant"] = nbt.IntTag(variant)
        tag["PreferredProfession"] = nbt.StringTag("" if profession == "unemployed" else profession)
        tag["TradeTablePath"] = nbt.StringTag(_table_path(profession))
        if "Offers" in tag:
            del tag["Offers"]
        _reset_definitions(tag, profession)
        experience = TIER_EXPERIENCE[tier]
        warnings.append(t("Der Berufswechsel setzt Handelsangebote und Handelserfahrung zurück."))
        if profession != "unemployed":
            warnings.append(t("Arbeitsplatz im Spiel ersetzen: {job_site}.", job_site=t(site)))
        else:
            warnings.append(t("Den bisherigen Arbeitsplatz im Spiel entfernen."))
    else:
        experience = state["trade_experience"]
        if experience < TIER_EXPERIENCE[tier] or (tier < 4 and experience >= TIER_EXPERIENCE[tier + 1]):
            experience = max(TIER_EXPERIENCE[tier], 1 if tier == 0 and state["traded"] else 0)
        warnings.append(t("Die vorhandenen Handelsangebote bleiben erhalten."))
    tag["TradeTier"] = nbt.IntTag(tier)
    tag["TradeExperience"] = nbt.IntTag(experience)
    after = career_summary(
        {**state, "profession": profession, "trade_tier": tier, "trade_experience": experience, "trade_count": 0 if switched else state["trade_count"]}
    )
    return after, warnings, None
