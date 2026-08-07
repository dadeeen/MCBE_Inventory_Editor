from __future__ import annotations

import copy
import json

import pytest

from mcbe_editor.item_availability import (
    BUNDLED_ITEM_DB_SOURCE_RELEASE,
    ITEM_AVAILABILITY,
    ITEM_AVAILABILITY_CATEGORIES,
    InvalidItemAvailabilityError,
    load_item_availability,
)
from mcbe_editor.item_data import ADDABLE_ITEM_IDS


def _write_payload(tmp_path, payload: dict) -> str:
    path = tmp_path / "item_availability.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_bundled_item_availability_has_reviewed_complete_classification() -> None:
    classifications = ITEM_AVAILABILITY["classifications"]

    assert {category: len(classifications[category]) for category in ITEM_AVAILABILITY_CATEGORIES} == {
        "technical": 24,
        "command_only": 2,
        "education": 3,
        "generated_state": 1,
        "legacy": 1,
        "creative": 106,
    }
    assert ITEM_AVAILABILITY["source_release"] == BUNDLED_ITEM_DB_SOURCE_RELEASE
    assert sum(map(len, classifications.values())) == 137

    regular_spawn_eggs = {
        item_id for item_id in classifications["creative"] if item_id.endswith("_spawn_egg")
    }
    command_spawn_eggs = set(classifications["command_only"])
    all_addable_spawn_eggs = {item_id for item_id in ADDABLE_ITEM_IDS if item_id.endswith("_spawn_egg")}
    assert len(regular_spawn_eggs) == 86
    assert regular_spawn_eggs | command_spawn_eggs == all_addable_spawn_eggs

    assert set(ITEM_AVAILABILITY["variants"]) == {
        "minecraft:lingering_potion",
        "minecraft:potion",
        "minecraft:splash_potion",
    }
    assert all(values == {"36": "creative"} for values in ITEM_AVAILABILITY["variants"].values())
    assert "minecraft:tipped_arrow" not in ITEM_AVAILABILITY["variants"]


def test_bundled_item_availability_covers_every_category_with_a_reference() -> None:
    referenced = {
        category
        for reference in ITEM_AVAILABILITY["references"]
        for category in reference["categories"]
    }

    assert referenced == set(ITEM_AVAILABILITY_CATEGORIES)
    assert all(reference["url"].startswith("https://") for reference in ITEM_AVAILABILITY["references"])


def test_item_availability_rejects_duplicate_primary_classification(tmp_path) -> None:
    payload = copy.deepcopy(ITEM_AVAILABILITY)
    payload["classifications"]["creative"].append("minecraft:barrier")

    with pytest.raises(InvalidItemAvailabilityError, match="doppelt klassifiziert"):
        load_item_availability(_write_payload(tmp_path, payload))


def test_item_availability_rejects_unknown_item_id(tmp_path) -> None:
    payload = copy.deepcopy(ITEM_AVAILABILITY)
    payload["classifications"]["technical"][0] = "minecraft:not_in_the_registry"

    with pytest.raises(InvalidItemAvailabilityError, match="ADDABLE_ITEM_IDS"):
        load_item_availability(_write_payload(tmp_path, payload))


def test_item_availability_rejects_primary_and_variant_rule_for_same_item(tmp_path) -> None:
    payload = copy.deepcopy(ITEM_AVAILABILITY)
    payload["classifications"]["creative"].append("minecraft:potion")

    with pytest.raises(InvalidItemAvailabilityError, match="zugleich vollständig und variantenspezifisch"):
        load_item_availability(_write_payload(tmp_path, payload))


def test_item_availability_rejects_mismatched_source_release(tmp_path) -> None:
    payload = copy.deepcopy(ITEM_AVAILABILITY)
    payload["source_release"] = "v0.0.0"

    with pytest.raises(InvalidItemAvailabilityError, match="passt nicht zur Item-Datenbank"):
        load_item_availability(_write_payload(tmp_path, payload))


@pytest.mark.parametrize("reviewed_at", ["20260803", "2026-W32-1"])
def test_item_availability_rejects_noncanonical_review_date(tmp_path, reviewed_at: str) -> None:
    payload = copy.deepcopy(ITEM_AVAILABILITY)
    payload["reviewed_at"] = reviewed_at

    with pytest.raises(InvalidItemAvailabilityError, match="YYYY-MM-DD"):
        load_item_availability(_write_payload(tmp_path, payload))
