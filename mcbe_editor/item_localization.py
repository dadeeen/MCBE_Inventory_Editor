"""Resolve item labels through exact registry references, independently per locale.

Item identity, block identity and language keys are separate namespaces. Keep
complete language keys here; never create item IDs from a language-file key.
"""

from __future__ import annotations

import re

from .item_registry_policy import is_non_item_lang_key_id
from .update_source_quality import usable_source_name

# These item IDs retain language keys that neither registry points to. Values
# are keys, not a second translation catalog. Banner data value zero is black.
LEGACY_ITEM_LANGUAGE_KEYS = {
    "axolotl_bucket": "item.bucketaxolotl.name",
    "cod_bucket": "item.bucketfish.name",
    "pufferfish_bucket": "item.bucketpuffer.name",
    "salmon_bucket": "item.bucketsalmon.name",
    "sulfur_cube_bucket": "item.bucketsulfurcube.name",
    "tadpole_bucket": "item.buckettadpole.name",
    "tropical_fish_bucket": "item.buckettropical.name",
    "disc_fragment_5": "item.disc_fragment.name",
    "seagrass": "tile.seagrass.seagrass.name",
    "banner": "item.banner.black.name",
}

# These inventory items share an ID with a different crop-block representation.
NON_ITEM_BLOCK_NAMES = frozenset({"wheat", "beetroot"})
CATEGORY_ITEM_NAMES = frozenset({"potion", "splash_potion", "lingering_potion"})
# These actual language keys can outlive the registry ID that originally used them.
LEGACY_BARE_NAMES = {
    "item.bundle",
    "item.black_bundle",
    "item.white_bundle",
    "item.red_bundle",
    "item.orange_bundle",
    "item.yellow_bundle",
    "item.green_bundle",
    "item.lime_bundle",
    "item.brown_bundle",
    "item.light_gray_bundle",
    "item.light_blue_bundle",
    "item.blue_bundle",
    "item.gray_bundle",
    "item.pink_bundle",
    "item.magenta_bundle",
    "item.purple_bundle",
    "item.cyan_bundle",
}


def variant_language_keys(identifier: str) -> list[str]:
    """Known language-key schemas, without inventing labels or item identities."""
    if identifier == "bed":
        return ["item.bed.white.name"]
    for suffix, prefix in (("_chest_boat", "chest_boat"), ("_chest_raft", "chest_boat"), ("_boat", "boat"), ("_raft", "boat")):
        if identifier.endswith(suffix):
            variant = identifier.removesuffix(suffix)
            return [f"item.{prefix}.{'big_oak' if variant == 'dark_oak' else variant}.name"]
    if identifier.endswith("_spawn_egg"):
        return [f"item.spawn_egg.entity.{identifier.removesuffix('_spawn_egg')}.name"]
    return []


def parse_source_labels(content: str) -> dict[str, str | None]:
    """Keep full item/tile keys, including disc subtitles, without rendering them."""
    labels: dict[str, str | None] = {}
    conflicts = set()
    for line in content.splitlines():
        key, separator, value = line.strip().partition("=")
        key = key.lower()
        if not separator or not re.fullmatch(r"(?:item|tile)\.[a-z0-9_.:/-]+", key):
            continue
        value = usable_source_name(value)
        if key in labels and labels[key] != value:
            conflicts.add(key)
        labels[key] = value
    for key in conflicts:
        labels[key] = None
    return labels


def _references(registry: dict, prefix: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for entry in registry.get("data_items", []):
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("command_name") or entry.get("name") or entry.get("serialization_name")
        if not isinstance(identifier, str):
            continue
        identifier = identifier.removeprefix("minecraft:")
        reference = entry.get("serialization_id")
        if not re.fullmatch(r"[a-z0-9_]+", identifier):
            continue
        # An absent reference uses the canonical key. Keep an explicitly
        # unusable reference as missing evidence if another row competes.
        if reference is None:
            reference = f"{prefix}.{identifier}"
        reference = reference.strip().lower() if isinstance(reference, str) else ""
        if not re.fullmatch(r"(?:item|tile)\.[a-z0-9_.:/-]+", reference) or reference.endswith(".desc"):
            reference = ""
        result.setdefault(identifier, set()).add(reference)
    return result


def _reference_name(reference: str, labels: dict[str, str | None], bare_keys: set[str]) -> str | None:
    # Legacy item keys such as item.bundle can be names without a suffix.
    # A dotted bare key can instead be a message, subtitle or tooltip.
    keys = (reference,) if reference.endswith(".name") else (reference + ".name",)
    if reference in bare_keys:
        keys += (reference,)
    for key in keys:
        if key in labels and labels[key] is None:
            return None
        if labels.get(key):
            return labels[key]
    return ""


def _unanimous(candidates):
    # Missing evidence from a competing registry reference matters: dropping it
    # can splice two unrelated keys together across the two languages.
    values = set(candidates)
    return next(iter(values), "") if len(values) <= 1 else None


def _label_bridge(languages, bare_keys):
    """Match current English labels without collapsing item/tile namespaces."""
    groups = {}
    for key, english in languages.get("en", {}).items():
        if not english or key.endswith(".desc"):
            continue
        if not key.endswith(".name") and key not in bare_keys:
            continue
        groups.setdefault(" ".join(english.casefold().split()), []).append((languages.get("de", {}).get(key, ""), english))
    result = {}
    for label, values in groups.items():
        # All candidates have this English name. Its availability does not
        # depend on a German translation being present or unambiguous.
        record = {"official": {"en": values[0][1]}, "reasons": {}}
        german = [de for de, _en in values]
        distinct = {" ".join(de.casefold().split()) for de in german if de}
        if None in german or len(distinct) > 1:
            record["reasons"]["de"] = "ambiguous"
        elif all(german):
            record["official"]["de"] = german[0]
        result[label] = record
    return result


def registry_item_labels(item_ids, item_registry, block_registry, languages, english_names=None):
    """Resolve only validated item IDs; conflicting references stay unresolved.

    The item reference has priority. A block reference is usable only for the
    same exact item ID. Disc names combine the generic item name and the title
    reached through that item's own registry reference, in the same language.
    """
    item_refs, block_refs = _references(item_registry, "item"), _references(block_registry, "tile")
    # Suffixless names require a real registry identity. Merely looking like
    # `item.bundle` does not distinguish `item.canBreak` or a future tooltip.
    bare_keys = LEGACY_BARE_NAMES | {f"item.{identifier}" for identifier in item_refs if not is_non_item_lang_key_id(identifier)}
    bridge = _label_bridge(languages, bare_keys)
    result = {}
    for full_id in item_ids:
        identifier = full_id.removeprefix("minecraft:")
        record = {"official": {}, "composed": {}, "reasons": {}}
        variants = set(variant_language_keys(identifier))
        explicit_variant = identifier == "bed" and any(_reference_name(key, labels, bare_keys) != "" for key in variants for labels in languages.values())
        for locale, labels in languages.items():
            priorities = [item_refs.get(identifier) or {f"item.{identifier}"}]
            if identifier not in NON_ITEM_BLOCK_NAMES and identifier in block_refs:
                priorities.append(block_refs[identifier] or {f"tile.{identifier}"})
            if identifier in LEGACY_ITEM_LANGUAGE_KEYS:
                priorities.append({LEGACY_ITEM_LANGUAGE_KEYS[identifier]})
            if explicit_variant:
                # A missing counterpart to the white data-value-zero label
                # cannot become the generic bed name or a different color.
                priorities = [variants]
            else:
                priorities.append(variants)
            for references in priorities:
                name = _unanimous(_reference_name(reference, labels, bare_keys) for reference in references)
                if name is None:
                    record["reasons"][locale] = "ambiguous"
                    break
                if name:
                    record["official"][locale] = name
                    break
            if locale in record["official"] or locale in record["reasons"]:
                continue
            if identifier.startswith("music_disc_"):
                title = _unanimous(
                    labels.get(reference.removesuffix(".name") + ".desc", "") if re.fullmatch(r"item\.record_[a-z0-9_]+(?:\.name)?", reference) else ""
                    for reference in item_refs.get(identifier, ())
                )
                base = labels.get("item.record.name", "")
                if title is None or base is None:
                    record["reasons"][locale] = "ambiguous"
                elif base and title:
                    record["composed"][locale] = base + " – " + title
        english = record["official"].get("en") or usable_source_name((english_names or {}).get(identifier))
        # Learn wording cannot identify a disc's subtitle or select a potion
        # variant for a category ID. Those families require their own sources.
        may_bridge = not explicit_variant and identifier not in CATEGORY_ITEM_NAMES and not identifier.startswith("music_disc_")
        if may_bridge and record["reasons"].get("en") != "ambiguous" and english:
            candidate = bridge.get(" ".join(english.casefold().split()), {})
            for locale in ("de", "en"):
                # A direct registry reference outranks unrelated bridge
                # candidates, including conflicts found only in those candidates.
                if locale in record["official"] or locale in record["reasons"]:
                    continue
                if reason := candidate.get("reasons", {}).get(locale):
                    record["reasons"][locale] = reason
                elif value := candidate.get("official", {}).get(locale):
                    record["official"][locale] = value
        result[identifier] = record
    # A Learn identifier licenses its own item label. It does not establish
    # that a block of the same name or a matching display title is this item.
    for identifier in (english_names or {}).keys() - result.keys():
        record = {"official": {}, "composed": {}, "reasons": {}}
        for locale, labels in languages.items():
            name = _reference_name(f"item.{identifier}", labels, bare_keys)
            if name is None:
                record["reasons"][locale] = "ambiguous"
            elif name:
                record["official"][locale] = name
        result[identifier] = record
    return result
