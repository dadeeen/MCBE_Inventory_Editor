import json

import pytest

from mcbe_editor.item_data import load_item_database
from mcbe_editor.item_name_policy import SUPERSEDED_ITEM_LABELS, reviewed_item_label_repairs
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON
from scripts import update_db


def test_updater_uses_the_shared_reviewed_labels_and_does_not_mutate_input():
    reviewed = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))["items"]
    original = dict(SUPERSEDED_ITEM_LABELS)
    merged = update_db.merge_items(original, {}, {})
    for item_id in original:
        assert merged[item_id] == tuple(reviewed[item_id]), item_id
    assert original == SUPERSEDED_ITEM_LABELS
    assert update_db.merge_items(merged, {}, {}) == merged


def test_exact_match_repair_preserves_custom_and_partially_renamed_pairs():
    reviewed = {"minecraft:fireworks": ["Feuerwerksrakete", "Firework Rocket"]}
    for names in [("Eigene Rakete", "Flight Duration:"), ("Flugdauer:", "My rocket"), ("Eigene Rakete", "My rocket")]:
        assert reviewed_item_label_repairs({"minecraft:fireworks": names}, reviewed) == {}
    assert reviewed_item_label_repairs({"minecraft:fireworks": ("Flugdauer:", "Flight Duration:")}, reviewed) == {
        "minecraft:fireworks": ("Feuerwerksrakete", "Firework Rocket"),
    }


def test_repair_requires_complete_reviewed_replacement():
    old = {"minecraft:fireworks": ("Flugdauer:", "Flight Duration:")}
    for replacement in (None, "Name", ["Rakete"], ["Rakete", ""], ["Rakete", 1]):
        assert reviewed_item_label_repairs(old, {"minecraft:fireworks": replacement}) == {}
    assert reviewed_item_label_repairs(old, {}) == {}


@pytest.mark.parametrize("rename", [None, "de", "en", "both"])
def test_runtime_and_update_preserve_custom_labels_while_repairing_shipped_pairs(tmp_path, rename):
    reviewed = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))["items"]
    current = dict(SUPERSEDED_ITEM_LABELS)
    current["minecraft:acacia_boat"] = ("Acacia Boat", "Acacia Boat")
    if rename:
        current = {
            item_id: (
                "Personal label" if rename in {"de", "both"} else names[0],
                "Personal label" if rename in {"en", "both"} else names[1],
            )
            for item_id, names in current.items()
        }
    expected = current if rename else {item_id: tuple(reviewed[item_id]) for item_id in current}
    path = tmp_path / "item_db.json"
    path.write_text(json.dumps({"schema_version": 3, "items": current}), encoding="utf-8")
    original = path.read_bytes()
    runtime = load_item_database(path)["ITEMS"]
    assert {item_id: runtime[item_id] for item_id in current} == expected
    assert path.read_bytes() == original

    en_items = {item_id.removeprefix("minecraft:"): reviewed[item_id][1] for item_id in current}
    de_items = {item_id.removeprefix("minecraft:"): reviewed[item_id][0] for item_id in current}
    merged = update_db.merge_items(current, en_items, de_items)
    assert merged == expected
    assert update_db.merge_items(merged, en_items, de_items) == merged


def test_reviewed_repairs_survive_partial_localization_during_update():
    merged = update_db.merge_items(
        {"minecraft:axolotl_bucket": ("Axolotl Bucket", "Axolotl Bucket")},
        {"axolotl_bucket": "Axolotl Bucket"},
        {"axolotl_bucket": "Axolotleimer"},
    )
    assert merged["minecraft:axolotl_bucket"] == ("Axolotleimer", "Bucket of Axolotl")


def test_freshly_generated_fallbacks_receive_reviewed_names():
    merged = update_db.merge_items(
        {},
        {"axolotl_bucket": "Axolotl Bucket", "light_block_7": "Light Block 7"},
        {},
    )
    assert merged == {
        "minecraft:axolotl_bucket": ("Axolotleimer", "Bucket of Axolotl"),
        "minecraft:light_block_7": ("Lichtblock 7", "Light Block 7"),
    }


def test_localization_bridge_and_reviewed_name_repair_complete_in_one_update():
    merged = update_db.merge_items(
        {"minecraft:poplar_standing_sign": ("Poplar Standing Sign", "Poplar Standing Sign")},
        {"poplar_standing_sign": "Poplar Sign"},
        {"poplar_standing_sign": "Pappelschild"},
    )
    assert merged["minecraft:poplar_standing_sign"] == ("Pappelschild", "Poplar Sign")


def test_intentional_catalog_names_are_preserved():
    current = {
        "minecraft:bed": ("Weißes Bett", "White Bed"),
        "minecraft:yellow_flower": ("Löwenzahn", "Dandelion"),
        "minecraft:stonecutter": ("Steinsäge (alt, ohne Funktion)", "Stonecutter (Legacy, No Function)"),
    }
    assert (
        update_db.merge_items(
            current,
            {"bed": "Bed", "yellow_flower": "Flower", "stonecutter": "Stonecutter"},
            {"bed": "Bett", "yellow_flower": "Blume", "stonecutter": "Steinsäge"},
        )
        == current
    )
