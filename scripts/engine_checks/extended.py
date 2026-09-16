"""Explicit coverage domains for the extended, stable-API Vanilla suite."""

from __future__ import annotations

from itertools import combinations, product

from .cases import append_case
from .protocol import ITEM_ID, ProbeError

# Bedrock's numeric enchantment IDs, independently checked by engine-created
# reference items and their disk NBT. Never infer IDs from translated labels.
ENCHANTMENT_NAMES = (
    "protection", "fire_protection", "feather_falling", "blast_protection", "projectile_protection", "thorns",
    "respiration", "depth_strider", "aqua_affinity", "sharpness", "smite", "bane_of_arthropods", "knockback",
    "fire_aspect", "looting", "efficiency", "silk_touch", "unbreaking", "fortune", "power", "punch", "flame",
    "infinity", "luck_of_the_sea", "lure", "frost_walker", "mending", "binding", "vanishing", "impaling",
    "riptide", "loyalty", "channeling", "multishot", "piercing", "quick_charge", "soul_speed", "swift_sneak",
    "wind_burst", "density", "breach", "lunge",
)
ENCHANTMENT_IDS = {name: index for index, name in enumerate(ENCHANTMENT_NAMES)}
DATA_VARIANTS = {
    "minecraft:bed": list(range(16)), "minecraft:banner": list(range(16)), "minecraft:goat_horn": list(range(8)),
    "minecraft:ominous_bottle": list(range(5)), "minecraft:suspicious_stew": list(range(13)), "minecraft:empty_map": [0, 2],
}
POTION_EFFECTS = (
    "water", "mundane", "long_mundane", "thick", "awkward", "nightvision", "long_nightvision", "invisibility",
    "long_invisibility", "leaping", "long_leaping", "strong_leaping", "fire_resistance", "long_fire_resistance",
    "swiftness", "long_swiftness", "strong_swiftness", "slowness", "long_slowness", "water_breathing",
    "long_water_breathing", "healing", "strong_healing", "harming", "strong_harming", "poison", "long_poison",
    "strong_poison", "regeneration", "long_regeneration", "strong_regeneration", "strength", "long_strength",
    "strong_strength", "weakness", "long_weakness", "wither", "turtle_master", "long_turtle_master",
    "strong_turtle_master", "slow_falling", "long_slow_falling", "strong_slowness", "wind_charged", "weaving", "oozing", "infested",
)
POTION_DATA_VALUES = {"minecraft:" + effect: value for value, effect in enumerate(POTION_EFFECTS)}
POTION_ITEMS = {"Consume": "minecraft:potion", "ThrownSplash": "minecraft:splash_potion", "ThrownLingering": "minecraft:lingering_potion"}


def matrix_result(events: list[dict], expected_ids: list[str], db: dict) -> dict:
    registries = [event for event in events if event["kind"] == "matrix_registry"]
    if len(registries) != 1:
        raise ProbeError("Missing or duplicate extended registry")
    registry = registries[0]
    enchantments = registry.get("enchantments")
    if not isinstance(enchantments, dict) or set(enchantments) != set(ENCHANTMENT_NAMES):
        raise ProbeError("Unreviewed or incomplete enchantment registry")
    for name, maximum in enchantments.items():
        recorded = db["enchantments"].get(str(ENCHANTMENT_IDS[name]))
        if type(maximum) is not int or not 1 <= maximum <= 255 or not recorded or maximum != recorded[2]:
            raise ProbeError(f"Engine enchantment limit disagrees with the editor: {name}")
    for field in ("effects", "deliveries"):
        values = registry.get(field)
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values):
            raise ProbeError("Invalid potion registry")
        if len(set(values)) != len(values):
            raise ProbeError("Duplicate potion registry entry")
    if set(registry["effects"]) != set(POTION_DATA_VALUES) or set(registry["deliveries"]) != set(POTION_ITEMS):
        raise ProbeError("Unreviewed or incomplete potion registry")
    items, potions = {}, {}
    for event in events:
        if event["kind"] == "enchantability":
            item_id, allowed, pairs = event.get("id"), event.get("allowed"), event.get("pairs")
            if item_id not in expected_ids or item_id in items or not isinstance(allowed, list) or not isinstance(pairs, list):
                raise ProbeError("Invalid or duplicate enchantment applicability observation")
            if any(name not in enchantments for name in allowed) or sorted(set(allowed)) != allowed:
                raise ProbeError("Invalid accepted enchantment list")
            expected_pairs = list(combinations(allowed, 2))
            if len(pairs) != len(expected_pairs):
                raise ProbeError("Missing enchantment pair observations")
            for pair, (left, right) in zip(pairs, expected_pairs, strict=True):
                if (not isinstance(pair, dict) or pair.get("left") != left or pair.get("right") != right
                        or type(pair.get("forward")) is not bool or type(pair.get("reverse")) is not bool):
                    raise ProbeError("Invalid enchantment pair observation")
                for direction in ("forward", "reverse"):
                    reason = pair.get(direction + "_error")
                    if reason is not None and (pair[direction] or reason not in {"EnchantmentLevelOutOfBoundsError", "EnchantmentTypeNotCompatibleError"}):
                        raise ProbeError("Unclassified enchantment pair error")
            items[item_id] = {"allowed": allowed, "pairs": pairs}
        elif event["kind"] == "potion":
            key = (event.get("effect"), event.get("delivery"))
            if key not in set(product(registry["effects"], registry["deliveries"])) or key in potions:
                raise ProbeError("Unexpected or duplicate potion observation")
            if not isinstance(event.get("id"), str) or not ITEM_ID.fullmatch(event["id"]) or event["id"] != POTION_ITEMS[event["delivery"]]:
                raise ProbeError("Invalid potion item ID")
            potions[key] = {key: event[key] for key in ("effect", "delivery", "id")}
    if set(items) != set(expected_ids) or set(potions) != set(product(registry["effects"], registry["deliveries"])):
        raise ProbeError("Extended probe omitted required observations")
    return {"status": "pass", "enchantments": enchantments, "items": items, "potions": list(potions.values()),
            "item_enchantment_checks": len(items) * len(enchantments),
            "ordered_pair_checks": 2 * sum(len(item["pairs"]) for item in items.values()),
            "rejected_pair_checks": sum(not pair[direction] for item in items.values() for pair in item["pairs"] for direction in ("forward", "reverse"))}


def extend_cases(cases: list[dict], observations: dict, matrix: dict) -> dict:
    counts = {"enchantment_levels": 0, "enchantment_pairs": 0, "enchantment_references": 0,
              "data_variants": 0, "potion_variants": 0, "durability_boundaries": 0, "merge_pairs": 0}

    def add(item_id, mode="create", amount=1, **extra):
        append_case(cases, observations, item_id, mode, amount, **extra)
        return cases[-1]["case_id"]

    for item_id, item in sorted(matrix["items"].items()):
        for name in item["allowed"]:
            maximum = matrix["enchantments"][name]
            # The editor deliberately offers enchanted_book for new enchanted
            # books. Script API also permits an ordinary book carrying ench NBT;
            # retain those originals without treating them as an editor feature.
            if item_id != "minecraft:book":
                for level in range(1, maximum + 1):
                    add(item_id, enchantments=[{"id": name, "level": level}], coverage="enchantment-level")
                    counts["enchantment_levels"] += 1
            add(item_id, "preserve", enchantments=[{"id": name, "level": maximum}], seeded_metadata=True,
                coverage="enchantment-reference")
            counts["enchantment_references"] += 1
        for pair in item["pairs"]:
            if pair["forward"] and pair["reverse"] and item_id != "minecraft:book":
                values = [{"id": name, "level": matrix["enchantments"][name]} for name in (pair["left"], pair["right"])]
                add(item_id, enchantments=values, coverage="enchantment-pair")
                counts["enchantment_pairs"] += 1
        maximum_damage = observations[item_id].get("max_durability")
        if maximum_damage:
            for damage in sorted({0, 1, maximum_damage // 2, maximum_damage - 1}):
                add(item_id, damage=damage, coverage="durability-boundary")
                counts["durability_boundaries"] += 1
    for item_id, values in DATA_VARIANTS.items():
        if item_id not in observations:
            raise ProbeError(f"A reviewed variant family is missing: {item_id}")
        for value in values:
            for mode in ("create", "preserve"):
                add(item_id, mode, damage=value, data_value=value, seeded_metadata=mode == "preserve", coverage="data-variant")
                counts["data_variants"] += 1
    for potion in matrix["potions"]:
        # These are engine-created references. The editor changes their display
        # fields without reconstructing a potion from guessed numeric values.
        for mode in ("preserve", "decorate"):
            add(potion["id"], mode, potion={key: potion[key] for key in ("effect", "delivery")}, seeded_metadata=True,
                damage=POTION_DATA_VALUES[potion["effect"]], data_value=POTION_DATA_VALUES[potion["effect"]],
                name="" if mode == "preserve" else "§bGeprüfter Trank", coverage="potion-variant")
            counts["potion_variants"] += 1
    merges = []
    for item_id in sorted(observations):
        case = next((case for case in cases if case["id"] == item_id and case["mode"] == "create" and case["amount"] == 1), None)
        if case:
            merges.append({"id": f"merge_{len(merges):05d}", "left": case["case_id"], "right": case["case_id"]})
    for item_id in ("minecraft:stone", "minecraft:oak_sign", "minecraft:red_cushion", "minecraft:diamond_pickaxe"):
        descriptors = [({}, {}), ({"name": "gleich"}, {"name": "gleich"}), ({"name": "links"}, {"name": "rechts"}),
                       ({"lore": ["gleich"]}, {"lore": ["gleich"]}), ({"lore": ["links"]}, {"lore": ["rechts"]}),
                       ({"name": "gleich", "lore": ["links"]}, {"name": "gleich", "lore": ["rechts"]})]
        if observations[item_id].get("max_durability"):
            descriptors.append(({"damage": 1}, {"damage": 2}))
        for left, right in descriptors:
            left_id = add(item_id, **left, coverage="merge-metadata")
            right_id = add(item_id, **right, coverage="merge-metadata")
            merges.append({"id": f"merge_{len(merges):05d}", "left": left_id, "right": right_id})
    counts["merge_pairs"] = len(merges)
    gameplay = []
    for source in (next(case for case in cases if case.get("name") and case["id"] == "minecraft:stone"),
                   next(case for case in cases if case.get("coverage") == "enchantment-level"),
                   next(case for case in cases if case.get("potion", {}).get("effect") == "minecraft:healing")):
        for action in ("hopper", "drop"):
            gameplay.append({"id": f"gameplay_{len(gameplay):03d}", "source": source["case_id"], "action": action})
    counts["gameplay_cases"] = len(gameplay)
    return {"counts": counts, "merges": merges, "gameplay": gameplay}


def validate_behavior_events(events: list[dict], plan: dict) -> dict:
    expected = {case["id"] for case in plan["merges"] + plan["gameplay"]}
    observed = {}
    for event in events:
        if event["kind"] == "behavior":
            key = event.get("id")
            if key not in expected or key in observed or event.get("passed") is not True:
                raise ProbeError("Unexpected, duplicate or failed behavior observation")
            observed[key] = event
    if set(observed) != expected:
        raise ProbeError("Behavior probe omitted planned cases")
    return {"status": "pass", "merge_pairs": len(plan["merges"]), "gameplay_cases": len(plan["gameplay"])}
