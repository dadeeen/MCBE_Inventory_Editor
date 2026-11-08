from __future__ import annotations

import json

import pytest

from mcbe_editor.villager_preferences import VillagerPreferences, VillagerPreferencesStaleError, normalize_preferences


def _region(**updates):
    return {"id": "region-a", "name": "Hauptdorf", "dimension": 0, "min_x": -20, "max_x": 20, "min_z": 0, "max_z": 40, **updates}


def test_preferences_are_world_scoped_atomic_and_do_not_touch_world(tmp_path):
    world = tmp_path / "world"
    world.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    store = VillagerPreferences(tmp_path / "app" / "villagers")
    before = store.read(str(world))
    result = store.save(str(world), revision=before["revision"], aliases={"actor:abc": "Rüdiger"}, regions=[_region()])
    assert store.read(str(world / ".")) == result
    assert store.read(str(other)) == before
    assert result["revision"] != before["revision"]
    assert result["aliases"] == {"actor:abc": "Rüdiger"}
    assert list(world.iterdir()) == []
    assert len(list((tmp_path / "app" / "villagers").glob("*.json"))) == 1


def test_concurrent_preferences_edit_is_not_silently_overwritten(tmp_path):
    store = VillagerPreferences(tmp_path / "app")
    revision = store.read("world")["revision"]
    original = store.save("world", revision=revision, aliases={}, regions=[_region()])
    with pytest.raises(VillagerPreferencesStaleError):
        store.save("world", revision=revision, aliases={}, regions=[])
    assert store.read("world") == original


@pytest.mark.parametrize(
    "updates",
    [
        {"dimension": True},
        {"dimension": "0"},
        {"min_x": float("nan")},
        {"max_x": float("inf")},
        {"min_x": 21},
        {"min_y": 12},
        {"min_y": 12, "max_y": 10},
        {"name": ""},
        {"min_x": 10**400},
        {"name": "x\nname"},
        {"id": "../../escape"},
        {"other": 1},
    ],
)
def test_regions_reject_invalid_bounds_and_identifiers(updates):
    with pytest.raises(ValueError):
        normalize_preferences({}, [_region(**updates)])


def test_regions_require_unique_ids_but_allow_explicit_overlaps():
    with pytest.raises(ValueError):
        normalize_preferences({}, [_region(), _region()])
    result = normalize_preferences({}, [_region(), _region(id="second")])
    assert len(result["regions"]) == 2


@pytest.mark.parametrize("aliases", [{"__proto__": "x"}, {"actor:abc": "x" * 81}, {"../file": "x"}, {"actor:abc": 4}, {"actor:abc": "\ud800"}])
def test_aliases_validate_identifiers_and_plain_text(aliases):
    with pytest.raises(ValueError):
        normalize_preferences(aliases, [])


def test_corrupt_preferences_cannot_be_overwritten_as_empty(tmp_path):
    store = VillagerPreferences(tmp_path / "app")
    revision = store.read("world")["revision"]
    store.save("world", revision=revision, aliases={}, regions=[])
    path = next((tmp_path / "app").glob("*.json"))
    path.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(ValueError, match="beschädigt"):
        store.save("world", revision=revision, aliases={}, regions=[])
    assert json.loads(path.read_text())["version"] == 999
