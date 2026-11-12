"""A bounded recipe oracle from BDS files or explicit Mojang samples.

This checks recipe sides, amounts, tiers, group selection and known item
metadata. It does not reproduce Minecraft's random enchantment algorithm or
prove that an exploration map points at the advertised structure in the world.
Those coverage limits are part of every successful result.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from copy import deepcopy
from pathlib import Path

from .extended import ENCHANTMENT_NAMES, POTION_DATA_VALUES
from .protocol import ProbeError

_PACK = re.compile(r"vanilla(?:_(\d+(?:\.\d+){1,3}))?\Z")
_ITEM = re.compile(r"(minecraft:[a-z0-9_]+)(?::([0-9]+))?\Z")
_TABLE = re.compile(r"trading/economy_trades/[a-z_]+_trades\.json\Z")
_LIMIT = 2 * 1024 * 1024
_ARCHIVE_LIMIT = 64 * 1024 * 1024
# These acquisition-only enchantments are not librarian trade-book candidates.
# This is a narrow exclusion, not a reproduction of the book-selection engine.
_NON_TRADING_ENCHANTMENTS = {"soul_speed", "swift_sneak", "wind_burst"}
_FUNCTION_KEYS = {
    "enchant_with_levels": {"function", "treasure", "levels"},
    "enchant_book_for_trading": {"function", "base_cost", "base_random_cost", "per_level_random_cost", "per_level_cost"},
    "exploration_map": {"function", "destination"},
    "random_aux_value": {"function", "values"},
    "random_dye": {"function"},
    "set_potion": {"function", "id"},
}
# Mojang bedrock-samples v1.26.60.5, resource_pack/textures/item_texture.json:
# map_filled texture indices identify the map type, not its world destination.
_MAP_DESTINATIONS = {
    "monument": 3,
    "mansion": 4,
    "trial_chambers": 14,
    "swamp_hut": 13,
    "jungle_temple": 12,
    "village_taiga": 8,
    "village_snowy": 7,
    "village_savanna": 10,
    "village_plains": 9,
    "village_desert": 11,
}
# These legacy table spellings coexist with flattened native item identifiers.
# Auxiliary values stay explicit; an unrelated modern item is never accepted.
_ALIASES = {
    ("minecraft:dye", 0): ("minecraft:ink_sac", 0),
    ("minecraft:dye", 4): ("minecraft:lapis_lazuli", 0),
    ("minecraft:bucket", 2): ("minecraft:cod_bucket", 0),
    ("minecraft:bucket", 10): ("minecraft:lava_bucket", 0),
    ("minecraft:horsearmorleather", 0): ("minecraft:leather_horse_armor", 0),
    ("minecraft:map", 0): ("minecraft:filled_map", 0),
    ("minecraft:speckled_melon", 0): ("minecraft:glistering_melon_slice", 0),
    ("minecraft:fish", 0): ("minecraft:cod", 0),
    ("minecraft:cooked_fish", 0): ("minecraft:cooked_cod", 0),
    ("minecraft:clownfish", 0): ("minecraft:tropical_fish", 0),
    ("minecraft:turtle_shell_piece", 0): ("minecraft:turtle_scute", 0),
    ("minecraft:muttonraw", 0): ("minecraft:mutton", 0),
}


def _require(value: bool, message: str) -> None:
    if not value:
        raise ProbeError(message)


def _integer(value, minimum=0, maximum=65535) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _range(value, *, default=1) -> tuple[int, int]:
    if value is None:
        value = default
    if _integer(value):
        return value, value
    _require(isinstance(value, dict) and set(value) == {"min", "max"}, "Unknown Vanilla trade range")
    _require(_integer(value["min"]) and _integer(value["max"]) and value["min"] <= value["max"], "Invalid Vanilla trade range")
    return value["min"], value["max"]


def _read_json(path: Path, server: Path) -> tuple[dict, str]:
    _require(
        path.is_relative_to(server)
        and path.resolve().is_relative_to(server)
        and all(not parent.is_symlink() and not parent.is_junction() for parent in (path, *path.parents) if parent.is_relative_to(server)),
        "Linked or escaped Vanilla trade reference",
    )
    try:
        with path.open("rb") as source:
            raw = source.read(_LIMIT + 1)
    except OSError as exc:
        raise ProbeError("Unreadable Vanilla trade reference: " + str(path)) from exc
    return _parse_json(raw, str(path))


def _parse_json(raw: bytes, source: str) -> tuple[dict, str]:
    _require(len(raw) <= _LIMIT, "Oversized Vanilla trade reference")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "Duplicate Vanilla JSON key")
            result[key] = value
        return result

    try:
        text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/', lambda match: match[0] if match[0].startswith('"') else " ", raw.decode("utf-8-sig"))
        value = json.loads(text, object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProbeError("Unreadable Vanilla trade reference: " + source) from exc
    _require(isinstance(value, dict), "Vanilla trade reference is not an object")
    return value, hashlib.sha256(raw).hexdigest()


def _samples_bytes(archive: Path, expected_hash: str) -> bytes:
    _require(isinstance(expected_hash, str) and bool(re.fullmatch(r"[a-fA-F0-9]{64}", expected_hash)), "Samples archive SHA-256 is required")
    _require(not archive.is_symlink() and not archive.is_junction(), "Linked samples archive")
    with archive.open("rb") as source:
        raw = source.read(_ARCHIVE_LIMIT + 1)
    _require(len(raw) <= _ARCHIVE_LIMIT, "Samples archive exceeds 64 MiB; use the text-only min release")
    _require(hashlib.sha256(raw).hexdigest() == expected_hash.lower(), "Samples archive SHA-256 mismatch")
    return raw


def stage_samples(run_dir: Path, archive: Path, expected_hash: str, version: str) -> dict:
    _require(isinstance(version, str) and bool(re.fullmatch(r"v\d+\.\d+\.\d+\.\d+", version)), "A stable Mojang samples release version is required")
    raw = _samples_bytes(archive, expected_hash)
    (run_dir / "vanilla-samples.zip").write_bytes(raw)
    return {"version": version, "sha256": expected_hash.lower()}


def load_run_trade_tables(run_dir: Path, report: dict) -> dict[str, dict]:
    reference = report.get("trade_reference")
    if reference is None:
        return load_trade_tables(run_dir / "server")
    _require(isinstance(reference, dict) and set(reference) == {"version", "sha256"}, "Malformed samples reference")
    _require(isinstance(reference["version"], str) and bool(re.fullmatch(r"v\d+\.\d+\.\d+\.\d+", reference["version"])), "Missing samples release")
    return load_trade_tables(run_dir / "server", samples=run_dir / "vanilla-samples.zip", expected_hash=reference["sha256"])


def load_trade_tables(server: Path, *, samples: Path | None = None, expected_hash: str = "") -> dict[str, dict]:
    """Read explicit hash-bound samples, or loose base/numbered BDS overlays."""
    if samples is not None:
        raw = _samples_bytes(samples, expected_hash)
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = archive.infolist()
                _require(len(members) <= 50000, "Too many samples archive members")
                roots = [
                    info.filename.removesuffix("entities/villager_v2.json")
                    for info in members
                    if re.fullmatch(r"(?:[^/]+/)?behavior_pack/entities/villager_v2\.json", info.filename)
                ]
                _require(len(roots) == 1, "Samples archive must contain one Vanilla behavior_pack")

                def resource(relative):
                    name = roots[0] + relative
                    matches = [info for info in members if info.filename == name]
                    _require(len(matches) == 1, "Missing or duplicate samples resource: " + relative)
                    info = matches[0]
                    _require(info.file_size <= _LIMIT and not info.is_dir() and not info.flag_bits & 1, "Invalid samples resource")
                    _require((info.external_attr >> 16) & 0o170000 != 0o120000, "Linked samples resource")
                    with archive.open(info) as source:
                        data = source.read(_LIMIT + 1)
                    parsed, digest = _parse_json(data, name)
                    return parsed, digest, "samples:" + name

                return _load_tables(resource)
        except ProbeError:
            raise
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ProbeError("Unreadable samples ZIP archive") from exc
    server = server.resolve()
    packs = []
    for path in (server / "behavior_packs").glob("vanilla*"):
        match = _PACK.fullmatch(path.name)
        if match and path.is_dir():
            packs.append((tuple(map(int, (match[1] or "0.0").split("."))), path))
    packs.sort()
    _require(bool(packs), "BDS archive contains no supported Vanilla behavior packs")

    def resource(relative):
        paths = [pack / relative for _version, pack in packs if (pack / relative).is_file()]
        _require(bool(paths), "BDS has no loose Vanilla reference: " + relative + "; supply --vanilla-samples with its release and SHA-256")
        path = paths[-1]
        parsed, digest = _read_json(path, server)
        return parsed, digest, path.relative_to(server).as_posix()

    return _load_tables(resource)


def _load_tables(resource) -> dict[str, dict]:
    entity, entity_hash, entity_source = resource("entities/villager_v2.json")
    groups = entity.get("minecraft:entity", {}).get("component_groups")
    _require(isinstance(groups, dict), "Vanilla villager lacks component groups")
    result = {}
    for profession, group in groups.items():
        table = group.get("minecraft:economy_trade_table") if isinstance(group, dict) else None
        if not isinstance(table, dict) or not table.get("table"):
            continue
        relative = table["table"]
        _require(isinstance(relative, str) and bool(_TABLE.fullmatch(relative)), "Unknown Vanilla villager trade path")
        variant = group.get("minecraft:variant", {}).get("value")
        _require(_integer(variant, 1, 13) and table.get("persist_trades") is True, "Unsupported Vanilla villager trade component")
        data, digest, source = resource(relative)
        _require(set(data) <= {"tiers", "format_version"} and "tiers" in data, "Unknown Vanilla trade-table fields")
        _require(data.get("format_version") in {None, "1.18.10", "1.26.10"}, "Unsupported Vanilla trade-table format version")
        result[profession] = {
            "tiers": data["tiers"],
            "path": relative,
            "variant": variant,
            "source": source,
            "sha256": digest,
            "entity_source": entity_source,
            "entity_sha256": entity_hash,
        }
        _validate_table(result[profession])
    _require(
        len(result) == 13 and {table["variant"] for table in result.values()} == set(range(1, 14)),
        "Vanilla reference must identify all thirteen working professions",
    )
    return result


def _filter(value, mark_variant: int, dimension: int) -> bool:
    if value is None:
        return True
    _require(isinstance(value, dict), "Unknown Vanilla trade filter")
    if set(value) in ({"all_of"}, {"any_of"}):
        key = next(iter(value))
        _require(isinstance(value[key], list) and 1 <= len(value[key]) <= 32, "Malformed Vanilla trade filter group")
        results = [_filter(child, mark_variant, dimension) for child in value[key]]
        return all(results) if key == "all_of" else any(results)
    _require(
        set(value) == {"test", "subject", "value", "operator"} and value["subject"] == "self" and value["operator"] == "=", "Unsupported Vanilla trade filter"
    )
    if value["test"] == "is_mark_variant":
        _require(_integer(value["value"], 0, 6), "Unknown Vanilla villager biome filter")
        return mark_variant == value["value"]
    _require(value["test"] == "in_overworld" and type(value["value"]) is bool, "Unknown Vanilla trade filter test")
    return (dimension == 0) == value["value"]


def trade_enchantment_items(tables: dict) -> list[str]:
    """Collect gear requiring a native canAddEnchantment reference in this run."""
    items = set()

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            if any(function.get("function") == "enchant_with_levels" for function in value.get("functions", [])):
                match = _ITEM.fullmatch(value["item"])
                items.add(match[1])
            for child in value.values():
                visit(child)

    for table in tables.values():
        _validate_table(table)
        visit(table["tiers"])
    return sorted(items)


def _item_options(value: dict, mark_variant: int, dimension: int) -> list[dict]:
    _require(isinstance(value, dict), "Invalid Vanilla trade item")
    if "choice" in value:
        _require(set(value) == {"choice"} and isinstance(value["choice"], list) and 1 <= len(value["choice"]) <= 128, "Unknown Vanilla trade item choice")
        return [option for child in value["choice"] for option in _item_options(child, mark_variant, dimension)]
    _require(
        set(value) <= {"item", "quantity", "price_multiplier", "functions", "filters"}
        and isinstance(value.get("item"), str)
        and bool(_ITEM.fullmatch(value["item"])),
        "Unknown Vanilla trade item fields",
    )
    _range(value.get("quantity"))
    if "price_multiplier" in value:
        _require(type(value["price_multiplier"]) in (int, float) and 0 <= value["price_multiplier"] <= 1, "Invalid Vanilla price multiplier")
    functions = value.get("functions", [])
    _require(isinstance(functions, list) and len(functions) <= 1, "Unsupported Vanilla item function combination")
    for function in functions:
        _require(
            isinstance(function, dict) and function.get("function") in _FUNCTION_KEYS and set(function) == _FUNCTION_KEYS[function["function"]],
            "Unknown Vanilla trade item function",
        )
        name = function["function"]
        if name in {"enchant_with_levels", "random_aux_value"}:
            _range(function["levels" if name == "enchant_with_levels" else "values"])
        if name == "enchant_with_levels":
            _require(function["treasure"] is False, "Unsupported treasure-enchantment trade table")
        if name == "enchant_book_for_trading":
            _require(all(_integer(function[key], 0, 64) for key in set(function) - {"function"}), "Invalid enchanted-book price function")
        if name == "exploration_map":
            _require(function["destination"] in _MAP_DESTINATIONS, "Unknown exploration-map destination")
        if name == "set_potion":
            _require("minecraft:" + function["id"] in POTION_DATA_VALUES, "Unknown Vanilla trade potion")
    allowed = _filter(value.get("filters"), mark_variant, dimension)
    return [value] if allowed else []


def _groups(table: dict, mark_variant: int, dimension: int) -> list[list[tuple[int, list[dict]]]]:
    tiers = table.get("tiers")
    _require(isinstance(tiers, list) and len(tiers) == 5, "Vanilla trade reference must contain five tiers")
    result = []
    for tier in tiers:
        _require(
            isinstance(tier, dict)
            and set(tier) <= {"total_exp_required", "groups", "trades"}
            and _integer(tier.get("total_exp_required"))
            and (("groups" in tier) != ("trades" in tier)),
            "Unsupported Vanilla tier",
        )
        groups = tier.get("groups", [{"num_to_select": -1, "trades": tier.get("trades")}])
        _require(isinstance(groups, list) and 1 <= len(groups) <= 16, "Invalid Vanilla trade groups")
        planned = []
        for group in groups:
            _require(
                isinstance(group, dict)
                and set(group) <= {"num_to_select", "trades"}
                and isinstance(group.get("trades"), list)
                and 1 <= len(group["trades"]) <= 128,
                "Unsupported Vanilla trade group",
            )
            candidates = []
            for trade in group["trades"]:
                _require(isinstance(trade, dict) and set(trade) <= {"wants", "gives", "trader_exp", "max_uses", "reward_exp"}, "Unknown Vanilla trade fields")
                _require(
                    _integer(trade.get("trader_exp", 1)) and _integer(trade.get("max_uses"), 1) and type(trade.get("reward_exp", True)) is bool,
                    "Invalid Vanilla trade counters",
                )
                for side, minimum, maximum in (("wants", 1, 2), ("gives", 1, 1)):
                    _require(isinstance(trade.get(side), list) and minimum <= len(trade[side]) <= maximum, "Unsupported Vanilla trade sides")
                options = {side: [_item_options(item, mark_variant, dimension) for item in trade[side]] for side in ("wants", "gives")}
                if all(options_for_item for options_for_side in options.values() for options_for_item in options_for_side):
                    candidates.append({**trade, "options": options})
            # Mojang's generated TradeGroup schema defaults to zero. The
            # current tables use omitted/negative counts to retain all choices.
            count = group.get("num_to_select", 0)
            _require(type(count) is int and -1 <= count <= len(group["trades"]), "Invalid Vanilla group selection count")
            planned.append((len(candidates) if count <= 0 else min(count, len(candidates)), candidates))
        result.append(planned)
    return result


def _validate_table(table: dict) -> None:
    # Inspect *all* branches, including biome-specific items not selected in this
    # world. Unknown schemas/functions cannot be hidden in an unchosen branch.
    for variant in range(7):
        _groups(table, variant, 0)
    thresholds = [tier["total_exp_required"] for tier in table["tiers"]]
    _require(thresholds[0] == 0 and all(a < b for a, b in zip(thresholds, thresholds[1:], strict=False)), "Invalid Vanilla experience thresholds")


def _stack(value) -> dict | None:
    from mcbe_editor import nbt

    if value is None or (isinstance(value, nbt.CompoundTag) and not value):
        return None
    _require(isinstance(value, nbt.CompoundTag), "Malformed native trade stack")
    _require(
        isinstance(value.get("Name"), nbt.StringTag) and isinstance(value.get("Count"), nbt.ByteTag) and isinstance(value.get("Damage"), nbt.ShortTag),
        "Wrong native trade item scalar type",
    )
    name, count, damage = (value[key].py_data for key in ("Name", "Count", "Damage"))
    if name in {"", "minecraft:air"} and count == 0:
        return None
    _require(bool(re.fullmatch(r"minecraft:[a-z0-9_]+", name)) and 1 <= count <= 64 and damage >= 0, "Invalid native trade item")
    metadata = value.get("tag", nbt.CompoundTag())
    _require(isinstance(metadata, nbt.CompoundTag), "Malformed native trade item metadata")
    return {"name": name, "count": count, "damage": damage, "tag": metadata}


def _enchantments(stack: dict, limits: dict | None) -> list[tuple[str, int]]:
    from mcbe_editor import nbt

    _require(isinstance(limits, dict) and bool(limits), "Native enchantment registry is required for trade metadata checks")
    entries = stack["tag"].get("ench")
    _require(isinstance(entries, nbt.ListTag) and 1 <= len(entries) <= len(ENCHANTMENT_NAMES), "Missing native trade enchantments")
    found = []
    for entry in entries:
        _require(
            isinstance(entry, nbt.CompoundTag)
            and set(entry) == {"id", "lvl"}
            and isinstance(entry["id"], nbt.ShortTag)
            and isinstance(entry["lvl"], nbt.ShortTag),
            "Malformed native trade enchantment",
        )
        identifier, level = entry["id"].py_data, entry["lvl"].py_data
        _require(0 <= identifier < len(ENCHANTMENT_NAMES), "Unknown native trade enchantment ID")
        name = ENCHANTMENT_NAMES[identifier]
        maximum = limits.get(name, limits.get("minecraft:" + name))
        _require(_integer(maximum, 1, 255) and 1 <= level <= maximum and name not in dict(found), "Invalid native trade enchantment level or duplicate")
        found.append((name, level))
    return found


def _matches_item(
    stack: dict | None, expected: dict, limits: dict | None, compatibility: dict | None, *, book_price=False, input_side=False, price_levels=None
) -> bool:
    from mcbe_editor import nbt

    if stack is None:
        return False
    match = _ITEM.fullmatch(expected["item"])
    name, damage = match[1], int(match[2] or 0)
    functions = expected.get("functions", [])
    function = functions[0] if functions else {}
    kind = function.get("function")
    identities = {(name, damage), _ALIASES.get((name, damage), (name, damage))}
    # Native wanted stacks may use the wildcard auxiliary value when the table
    # leaves it unspecified. It does not apply to output items or explicit data.
    if input_side and match[2] is None and not functions:
        identities |= {(identifier, 32767) for identifier, _damage in identities}
    if kind == "enchant_book_for_trading":
        identities = {("minecraft:enchanted_book", 0)}
    if kind == "random_aux_value":
        minimum, maximum = _range(function["values"])
        identities = {(name, value) for value in range(minimum, maximum + 1)}
    if kind == "set_potion":
        _require(name == "minecraft:arrow", "Only native tipped-arrow trade functions are supported")
        identities = {(name, POTION_DATA_VALUES["minecraft:" + function["id"]] + 1)}
    if kind == "exploration_map":
        identities = {("minecraft:filled_map", _MAP_DESTINATIONS[function["destination"]])}
    if (stack["name"], stack["damage"]) not in identities:
        return False
    minimum, maximum = (1, 64) if book_price and name == "minecraft:emerald" else _range(expected.get("quantity"))
    if price_levels is not None and name == "minecraft:emerald":
        # BDS 1.26.61.1 adds the selected enchantment level to the base price.
        # Bound that contribution; reproducing the random choice is out of scope.
        minimum, maximum = min(64, minimum + price_levels[0]), min(64, maximum + price_levels[1])
    if not minimum <= stack["count"] <= maximum:
        return False
    tag = stack["tag"]
    allowed_metadata = {"Damage", "RepairCost", "ench"}
    if name == "minecraft:banner":
        allowed_metadata.add("Type")
    if kind == "random_dye":
        allowed_metadata.add("customColor")
    elif kind == "exploration_map":
        allowed_metadata.update({"map_uuid", "map_display_players", "map_name_index", "map_is_init", "map_regenerate", "display"})
    if set(tag) - allowed_metadata:
        return False
    if "Type" in tag and (not isinstance(tag["Type"], nbt.IntTag) or tag["Type"].py_data != 0):
        return False
    if any(field in tag and (not isinstance(tag[field], nbt.IntTag) or tag[field].py_data != 0) for field in ("Damage", "RepairCost")):
        return False
    if kind in {"enchant_book_for_trading", "enchant_with_levels"}:
        found = _enchantments(stack, limits)
        if kind == "enchant_book_for_trading" and (len(found) != 1 or found[0][0] in _NON_TRADING_ENCHANTMENTS):
            return False
        if kind == "enchant_with_levels":
            _require(isinstance(compatibility, dict) and isinstance(compatibility.get(stack["name"]), list), "Native item enchantability reference is required")
            allowed = compatibility[stack["name"]]
            _require(all(isinstance(name, str) for name in allowed), "Malformed native item enchantability reference")
            allowed = {name.removeprefix("minecraft:") for name in allowed}
            if any(name not in allowed or name in {"frost_walker", "mending", "binding", "vanishing"} | _NON_TRADING_ENCHANTMENTS for name, _level in found):
                return False
    elif "ench" in tag and (not isinstance(tag["ench"], nbt.ListTag) or len(tag["ench"]) != 0):
        return False
    if kind == "random_dye":
        color = tag.get("customColor")
        if not isinstance(color, nbt.IntTag) or not -16777216 <= color.py_data <= 0xFFFFFF:
            return False
    elif "customColor" in tag:
        return False
    if kind == "exploration_map":
        if not isinstance(tag.get("map_uuid"), nbt.LongTag):
            return False
        if any(
            field in tag and (not isinstance(tag[field], nbt.ByteTag) or tag[field].py_data not in (0, 1))
            for field in ("map_display_players", "map_is_init", "map_regenerate")
        ):
            return False
    elif "map_uuid" in tag:
        return False
    return True


def _matches_recipe(actual: dict, template: dict, limits: dict | None, compatibility: dict | None) -> bool:
    if actual["maxUses"] != template["max_uses"] or actual["traderExp"] != template.get("trader_exp", 1):
        return False
    options = template["options"]
    if len(options["wants"]) == 1 and actual["buyB"] is not None:
        return False
    for sold in options["gives"][0]:
        if not _matches_item(actual["sell"], sold, limits, compatibility):
            continue
        function = (sold.get("functions") or [{}])[0]
        book_price = function.get("function") == "enchant_book_for_trading"
        price_levels = _range(function["levels"]) if function.get("function") == "enchant_with_levels" else None
        # Price adjustments belong to the matched output, not another option.
        if all(
            any(
                _matches_item(
                    actual[field],
                    choice,
                    limits,
                    compatibility,
                    input_side=True,
                    book_price=book_price and index == 0,
                    price_levels=price_levels if index == 0 else None,
                )
                for choice in choices
            )
            for index, (field, choices) in enumerate(zip(("buyA", "buyB"), options["wants"], strict=False))
        ):
            return True
    return False


def _assign(recipes: list[dict], groups: list[tuple[int, list[dict]]], limits: dict | None, compatibility: dict | None) -> None:
    _require(len(recipes) == sum(count for count, _trades in groups), "Native recipe count differs from Vanilla group selection")
    edges = [
        [
            (group_index, trade_index)
            for group_index, (_count, trades) in enumerate(groups)
            for trade_index, trade in enumerate(trades)
            if _matches_recipe(recipe, trade, limits, compatibility)
        ]
        for recipe in recipes
    ]
    _require(all(edges), "Native trade item, amount, metadata or recipe side does not match its Vanilla tier")
    capacities = [count for count, _trades in groups]
    ordered = sorted(edges, key=len)
    attempts = 0

    def choose(index: int, used: set[tuple[int, int]]) -> bool:
        nonlocal attempts
        attempts += 1
        _require(attempts <= 10000, "Ambiguous Vanilla trade assignment exceeds the bounded oracle")
        if index == len(ordered):
            return True
        for key in ordered[index]:
            group_index = key[0]
            if key not in used and capacities[group_index] > 0:
                capacities[group_index] -= 1
                if choose(index + 1, used | {key}):
                    return True
                capacities[group_index] += 1
        return False

    _require(choose(0, set()), "Native trades duplicate a choice or violate Vanilla group counts")


def _critical_field(recipe, field: str) -> str | None:
    """Hash validated recipe content across observed BDS default normalization."""
    from mcbe_editor import nbt

    value = recipe.get(field)
    if value is None:
        return None
    if field in {"buyA", "buyB", "sell"}:
        value = deepcopy(value)
        if field != "sell" and value.get("Damage") == nbt.ShortTag(32767):
            value["Damage"] = nbt.ShortTag(0)
        tag = value.get("tag")
        if isinstance(tag, nbt.CompoundTag):
            if tag.get("Damage") == nbt.IntTag(0):
                del tag["Damage"]
            if value.get("Name") == nbt.StringTag("minecraft:banner") and tag.get("Type") == nbt.IntTag(0):
                del tag["Type"]
            if not tag:
                del value["tag"]
    return hashlib.sha256(value.save_to()).hexdigest()


def validate_offers(
    root,
    profession: str,
    tables: dict,
    *,
    dimension: int = 0,
    enchantment_limits: dict | None = None,
    enchantment_compatibility: dict | None = None,
) -> dict:
    """Validate engine-generated Offers; never manufacture replacement recipes."""
    from mcbe_editor import nbt

    _require(profession in tables, "Missing independent Vanilla profession reference")
    table = tables[profession]
    _validate_table(table)
    for field, expected in (("Variant", table["variant"]), ("TradeTablePath", table["path"])):
        kind = nbt.IntTag if type(expected) is int else nbt.StringTag
        _require(isinstance(root.get(field), kind) and root[field].py_data == expected, "Native profession/table differs from the BDS reference")
    mark = root.get("MarkVariant", nbt.IntTag(0))
    _require(isinstance(mark, nbt.IntTag) and 0 <= mark.py_data <= 6 and _integer(dimension, 0, 2), "Unknown native biome/dimension")
    groups = _groups(table, mark.py_data, dimension)
    offers = root.get("Offers")
    _require(isinstance(offers, nbt.CompoundTag) and isinstance(offers.get("Recipes"), nbt.ListTag), "Engine did not generate native trade offers")
    thresholds = offers.get("TierExpRequirements")
    _require(isinstance(thresholds, nbt.ListTag) and len(thresholds) == 5, "Incomplete native trade thresholds")
    for index, entry in enumerate(thresholds):
        _require(
            isinstance(entry, nbt.CompoundTag)
            and set(entry) == {str(index)}
            and isinstance(entry[str(index)], nbt.IntTag)
            and entry[str(index)].py_data == table["tiers"][index]["total_exp_required"],
            "Native trade thresholds differ from Vanilla",
        )
    recipes = [[] for _ in range(5)]
    for recipe in offers["Recipes"]:
        _require(isinstance(recipe, nbt.CompoundTag), "Malformed native recipe")
        for field in ("tier", "traderExp", "maxUses", "uses"):
            _require(isinstance(recipe.get(field), nbt.IntTag), "Wrong native recipe scalar type: " + field)
        tier = recipe["tier"].py_data
        _require(0 <= tier <= 4 and 0 <= recipe["uses"].py_data <= recipe["maxUses"].py_data, "Invalid native recipe tier/use count")
        actual = {field: recipe[field].py_data for field in ("traderExp", "maxUses")}
        actual.update({field: _stack(recipe.get(field)) for field in ("buyA", "buyB", "sell")})
        _require(actual["buyA"] is not None and actual["sell"] is not None, "Native recipe is missing a required item side")
        recipes[tier].append(actual)
    for tier, planned in enumerate(groups):
        try:
            _assign(recipes[tier], planned, enchantment_limits, enchantment_compatibility)
        except ProbeError as exc:
            raise ProbeError(f"{profession}, tier {tier + 1}: {exc}") from exc
    signatures = [
        {
            "tier": recipe["tier"].py_data,
            **{field: _critical_field(recipe, field) for field in ("buyA", "buyB", "sell", "maxUses", "traderExp")},
        }
        for recipe in offers["Recipes"]
    ]
    serialized = json.dumps(sorted(signatures, key=lambda value: json.dumps(value, sort_keys=True)), sort_keys=True).encode()
    return {
        "status": "pass",
        "recipe_structure": "pass",
        "metadata": "partial",
        "recipes": sum(map(len, recipes)),
        "tiers": 5,
        "critical_signature": hashlib.sha256(serialized).hexdigest(),
        "limitations": [
            "Random enchantment selection, combinations and cost are not reproduced; "
            "native IDs, maximum levels, item applicability and known trade exclusions are checked.",
            "Exploration-map item identity and map UUID are checked; target coordinates and generated destination structures are not checked.",
            "Random-dye metadata is bounded to native color values; the exact random color selection is not reproduced.",
        ],
    }
