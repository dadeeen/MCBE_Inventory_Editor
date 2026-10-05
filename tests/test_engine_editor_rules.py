from __future__ import annotations

import pytest

from scripts.engine_checks.editor_rules import check_editor_rules
from scripts.engine_checks.extended import ENCHANTMENT_IDS
from scripts.engine_checks.protocol import ProbeError


@pytest.fixture
def rules_matrix():
    from mcbe_editor import item_data

    levels = {name: item_data.ENCHANTMENTS[numeric_id][2] for name, numeric_id in ENCHANTMENT_IDS.items()}
    matrix = {"enchantments": levels, "items": {
        "minecraft:stone": {"allowed": [], "pairs": []},
        "minecraft:book": {"allowed": sorted(levels), "pairs": []},
        "minecraft:enchanted_book": {"allowed": sorted(levels), "pairs": [
            {"left": "fortune", "right": "silk_touch", "forward": False, "reverse": False},
        ]},
        "minecraft:diamond_pickaxe": {
            "allowed": ["efficiency", "fortune", "mending", "silk_touch", "unbreaking", "vanishing"],
            "pairs": [
                {"left": "efficiency", "right": "unbreaking", "forward": True, "reverse": True},
                {"left": "fortune", "right": "silk_touch", "forward": False, "reverse": False},
            ],
        },
    }}
    observations = {item: {"max_durability": 1561 if item == "minecraft:diamond_pickaxe" else None} for item in matrix["items"]}
    return matrix, observations


def test_editor_rules_cover_rejections_and_deliberate_book_exceptions(rules_matrix):
    result = check_editor_rules(*rules_matrix)
    assert result["status"] == "pass"
    assert result["applicability_checks"] == 4 * 42
    assert result["pair_conflict_checks"] == 4
    assert result["enchantment_level_checks"] == 3 * 42
    assert result["durability_rejection_checks"] == 2
    assert result["incompatible_creation_checks"] >= 42
    assert result["intentional_exceptions"] == {
        "ordinary_book_preservation_only": 42, "enchanted_book_conflict_hints_omitted": 1,
    }


@pytest.mark.parametrize("item,name,allowed", [
    ("minecraft:stone", "sharpness", True),
    ("minecraft:diamond_pickaxe", "efficiency", False),
    ("minecraft:book", "mending", True),
])
def test_rule_comparison_detects_false_acceptance_and_false_rejection(rules_matrix, monkeypatch, item, name, allowed):
    from mcbe_editor import item_data

    original = item_data.is_enchantment_compatible_with_item
    monkeypatch.setattr(item_data, "is_enchantment_compatible_with_item", lambda number, current:
                        allowed if (number, current) == (ENCHANTMENT_IDS[name], item) else original(number, current))
    report = check_editor_rules(*rules_matrix)
    assert report["status"] == "fail"
    assert report["differences"]["applicability"] == [
        {"item": item, "enchantment": name, "engine": item != "minecraft:stone", "editor": allowed},
    ]


@pytest.mark.parametrize("extra", [False, True])
def test_rule_comparison_detects_missing_and_incorrect_conflict_hints(rules_matrix, monkeypatch, extra):
    from mcbe_editor import item_data

    catalog = dict(item_data.catalog_values())
    catalog["ENCHANTMENT_EXCLUSIVE_GROUPS"] = [[15, 17]] if extra else []
    monkeypatch.setattr(item_data, "catalog_values", lambda: catalog)
    result = check_editor_rules(*rules_matrix)
    assert result["status"] == "fail"
    pairs = result["differences"]["pair_conflicts"]
    assert any(pair["left"] == ("efficiency" if extra else "fortune") for pair in pairs)


def test_negative_checks_detect_a_builder_that_accepts_invalid_items(rules_matrix, monkeypatch):
    from mcbe_editor import inventory

    monkeypatch.setattr(inventory, "build_inventory_nbt", lambda original, *_args: original["Inventory"])
    report = check_editor_rules(*rules_matrix)
    assert report["status"] == "fail"
    assert {case["kind"] for case in report["differences"]["unexpected_creations"]} == {
        "incompatible_enchantment", "enchantment_level", "durability",
    }


def test_negative_checks_detect_input_mutation_even_on_rejection(rules_matrix, monkeypatch):
    from mcbe_editor import inventory, nbt

    def broken(original, *_args):
        original["unexpected"] = nbt.IntTag(1)
        raise ValueError("invalid item")

    monkeypatch.setattr(inventory, "build_inventory_nbt", broken)
    with pytest.raises(ProbeError, match="mutated"):
        check_editor_rules(*rules_matrix)


@pytest.mark.parametrize("mutation", ["phase", "hash"])
def test_rule_worker_requires_completed_and_unchanged_engine_evidence(tmp_path, mutation):
    from scripts.engine_checks.nbt_roundtrip import run
    from scripts.engine_checks.runner import sha256, write_json

    write_json(tmp_path / "matrix.json", {})
    write_json(tmp_path / "run.json", {
        "format": "mcbe-engine-check-v1", "phases": {"matrix": "observed" if mutation == "phase" else "pass"},
        "extended": {"matrix_sha256": "0" * 64 if mutation == "hash" else sha256(tmp_path / "matrix.json")},
    })
    with pytest.raises(ProbeError, match="complete, unchanged"):
        run(tmp_path, "rules")
