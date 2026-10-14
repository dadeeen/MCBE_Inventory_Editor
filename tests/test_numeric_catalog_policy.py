"""Exercise the updater/write/runtime boundary, including unsafe legacy IDs."""

import copy
import json

import pytest

from mcbe_editor.item_data import _load_item_database_file
from mcbe_editor.numeric_catalog_policy import NumericCatalogConflictError, reconcile_numeric_catalog
from scripts import update_db


def test_updater_and_runtime_agree_on_numeric_catalogs(tmp_path, monkeypatch):
    raw = json.loads(update_db.BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
    raw["effects"]["1"] = ["Eigenes Tempo", "Custom Speed", "alt", "old"]
    raw["effects"]["99"] = raw["effects"].pop("37")
    raw["effects"]["120"] = ["Zusatz", "Addon Effect", "Eigene Beschreibung", "Custom description"]
    raw["enchantments"]["17"] = ["Eigener Name", "Custom Enchantment", 2, "Custom description"]
    raw["enchantments"]["99"] = raw["enchantments"].pop("41")
    raw["enchantments"]["120"] = ["Zusatz", "Addon Enchantment", 9, "Custom description"]
    path = tmp_path / "item_db.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    runtime_before = _load_item_database_file(path)
    monkeypatch.setattr(update_db, "ITEM_DB_PATH", path)
    items, effects, enchantments = update_db.read_all_dicts()
    effect_ids = update_db.load_local_effect_numeric_ids()
    enchantment_ids = update_db.load_local_enchantment_numeric_ids()
    levels = update_db.load_local_enchantment_max_levels()
    merged_effects = update_db.merge_effects(effects, list(effect_ids), {}, {}, effect_ids)
    merged_enchantments = update_db.merge_enchantments(enchantments, [(name, 1) for name in enchantment_ids], {}, {}, levels, enchantment_ids)
    update_db.write_all_dicts(items, merged_effects, merged_enchantments)
    runtime_after = _load_item_database_file(path)

    def normalize(entries):
        return {key: (*value[:3], value[3] if len(value) > 3 else "") for key, value in entries.items()}

    assert merged_effects == runtime_before["EFFECTS"] == runtime_after["EFFECTS"]
    assert normalize(merged_enchantments) == normalize(runtime_before["ENCHANTMENTS"]) == normalize(runtime_after["ENCHANTMENTS"])
    assert merged_effects[1][:2] == tuple(raw["effects"]["1"][:2])
    assert all(merged_effects[1][2:])
    assert merged_enchantments[17] == ("Eigener Name", "Custom Enchantment", 3, "Custom description")
    assert merged_effects[120] == tuple(raw["effects"]["120"])
    assert merged_enchantments[120] == tuple(raw["enchantments"]["120"])
    assert 99 not in merged_effects and 99 not in merged_enchantments
    assert update_db.merge_effects(merged_effects, list(effect_ids), {}, {}, effect_ids) == merged_effects
    assert update_db.merge_enchantments(merged_enchantments, [(name, 1) for name in enchantment_ids], {}, {}, levels, enchantment_ids) == merged_enchantments


@pytest.mark.parametrize("kind", ["effects", "enchantments"])
def test_collision_is_rejected_without_mutating_inputs(kind):
    current = {99: ("Tempo", "Speed", 1, ""), 1: ("Eigener Eintrag", "Custom Entry", 1, "")}
    reviewed = {1: ("Tempo", "Speed", 2, "")}
    before = copy.deepcopy(current)
    with pytest.raises(NumericCatalogConflictError, match="Kollidierende") as error:
        reconcile_numeric_catalog(current, reviewed, kind=kind)
    assert error.value.section == kind
    assert error.value.ids == [1, 99]
    assert current == before


def test_runtime_isolates_effect_collision_and_updater_rejects_rewriting_it(tmp_path):
    raw = json.loads(update_db.BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
    raw["effects"]["99"] = raw["effects"]["1"]
    path = tmp_path / "item_db.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = _load_item_database_file(path)
    assert loaded["ITEM_DB_CONFLICTS"]["effects"]["ids"] == [1, 99]
    assert loaded["EFFECTS"][99] == tuple(raw["effects"]["99"])
    old = {int(key): tuple(value) for key, value in raw["effects"].items()}
    with pytest.raises(RuntimeError, match="Kollidierende"):
        update_db.merge_effects(old, ["speed"], {}, {}, {"speed": 1})


def test_effect_numeric_ids_cannot_be_reused():
    with pytest.raises(RuntimeError, match="doppelt"):
        update_db.merge_effects({}, ["speed", "slowness"], {}, {}, {"speed": 1, "slowness": 1})


def test_disagreeing_language_names_do_not_guess_an_id():
    with pytest.raises(RuntimeError, match="Widersprüchliche"):
        update_db.merge_effects({1: ("Slowness", "Speed", "", "")}, ["speed", "slowness"], {}, {}, {"speed": 1, "slowness": 2})
