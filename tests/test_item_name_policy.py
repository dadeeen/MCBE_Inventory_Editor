import json

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
