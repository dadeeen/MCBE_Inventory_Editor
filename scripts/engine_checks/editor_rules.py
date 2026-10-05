"""Compare the production editor's rules with independently measured Vanilla rules."""

from __future__ import annotations

from .extended import ENCHANTMENT_IDS
from .protocol import ProbeError


def check_editor_rules(matrix: dict, observations: dict) -> dict:
    # The standalone worker binds the measured catalog before this import.
    from mcbe_editor import item_data, nbt
    from mcbe_editor.inventory import build_inventory_nbt

    differences = {"applicability": [], "pair_conflicts": [], "unexpected_creations": []}
    counts = {"applicability_checks": 0, "pair_conflict_checks": 0, "incompatible_creation_checks": 0,
              "enchantment_level_checks": 0, "durability_rejection_checks": 0}
    exceptions = {"ordinary_book_preservation_only": 0, "enchanted_book_conflict_hints_omitted": 0}
    groups = item_data.catalog_values()["ENCHANTMENT_EXCLUSIVE_GROUPS"]
    negative_items = {}
    positive_items = {}
    for item_id, entry in sorted(matrix["items"].items()):
        allowed = set(entry["allowed"])
        for name, numeric_id in ENCHANTMENT_IDS.items():
            engine = name in allowed
            editor = item_data.is_enchantment_compatible_with_item(numeric_id, item_id)
            expected = engine
            if item_id == "minecraft:book":
                # Existing ordinary books retain their NBT; new enchanted books
                # use enchanted_book. This exception does not permit creation.
                expected = False
                exceptions["ordinary_book_preservation_only"] += 1
            if editor != expected:
                differences["applicability"].append({"item": item_id, "enchantment": name, "engine": engine, "editor": editor})
            counts["applicability_checks"] += 1
            if expected:
                positive_items.setdefault(name, item_id)
            else:
                # Check both the non-enchantable and incompatible-slot branches
                # of the actual builder without repeating 68k NBT constructions.
                negative_items.setdefault((name, bool(allowed)), item_id)
        for pair in entry["pairs"]:
            if item_id in {"minecraft:book", "minecraft:enchanted_book"}:
                if item_id == "minecraft:enchanted_book":
                    exceptions["enchanted_book_conflict_hints_omitted"] += 1
                continue
            identifiers = {ENCHANTMENT_IDS[pair["left"]], ENCHANTMENT_IDS[pair["right"]]}
            conflict = any(identifiers.issubset(group) for group in groups)
            for direction in ("forward", "reverse"):
                counts["pair_conflict_checks"] += 1
                if conflict != (not pair[direction]):
                    differences["pair_conflicts"].append({"item": item_id, "left": pair["left"], "right": pair["right"],
                                                          "order": direction, "engine_accepts": pair[direction], "editor_conflict": conflict})

    def must_reject(item_id, kind, *, damage=0, enchantments=None):
        empty = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        before = empty.save_to()
        try:
            build_inventory_nbt(empty, [{"slot": 0, "name": item_id, "count": 1, "damage": damage,
                                         "enchantments": enchantments or []}], item_data.ENCHANTMENTS)
        except ValueError:
            pass
        else:
            differences["unexpected_creations"].append({"item": item_id, "kind": kind, "damage": damage,
                                                       "enchantments": enchantments or []})
        if empty.save_to() != before:
            raise ProbeError("Rejected item validation mutated its input NBT")

    for (name, _has_component), item_id in sorted(negative_items.items()):
        must_reject(item_id, "incompatible_enchantment", enchantments=[{"id": ENCHANTMENT_IDS[name], "lvl": 1}])
        counts["incompatible_creation_checks"] += 1
    for name, item_id in sorted(positive_items.items()):
        for level in (-1, 0, matrix["enchantments"][name] + 1):
            must_reject(item_id, "enchantment_level", enchantments=[{"id": ENCHANTMENT_IDS[name], "lvl": level}])
            counts["enchantment_level_checks"] += 1
    for item_id, entry in sorted(observations.items()):
        maximum = entry.get("max_durability")
        if maximum is not None:
            for damage in (-1, maximum + 1):
                must_reject(item_id, "durability", damage=damage)
                counts["durability_rejection_checks"] += 1
    return {"status": "fail" if any(differences.values()) else "pass", **counts,
            "intentional_exceptions": exceptions, "differences": differences}
