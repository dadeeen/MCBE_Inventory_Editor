"""Validated registry identities share one name plan with locale coverage."""

from __future__ import annotations

import json

import pytest

from mcbe_editor import item_data, item_db_verification
from tests.test_update_db import update_db
from tests.test_update_source_quality import _members
from tests.test_update_source_quality import updater as updater


@pytest.mark.parametrize(
    "identifier,key",
    [
        ("minecraft:future_probe_spawn_egg", "spawn_egg.entity.future_probe"),
        ("minecraft:future_probe_boat", "boat.future_probe"),
        ("minecraft:future_probe_chest_boat", "chest_boat.future_probe"),
    ],
)
@pytest.mark.parametrize("locales", [("de", "en"), ("de",), ("en",)])
def test_registry_only_identity_resolves_derived_names_and_honest_coverage(identifier, key, locales):
    names = {"de": "Quellenname", "en": "Source Name"}
    localizations = {key: tuple(names[locale] if locale in locales else "" for locale in ("de", "en"))}
    registry = [identifier]

    merged = update_db.merge_items({}, {}, {}, item_localizations=localizations, registry_ids=registry)
    quality = update_db.item_label_quality(registry, merged, {}, {}, {}, {}, localizations)

    expected = tuple(names[locale if locale in locales else locales[0]] for locale in ("de", "en"))
    assert merged == {identifier: expected}
    for locale in ("de", "en"):
        assert quality[locale]["official"] == int(locale in locales)
        assert quality[locale]["fallbacks"] == ([] if locale in locales else [{"id": identifier, "source": "other_language"}])
    assert update_db.merge_items(merged, {}, {}, item_localizations=localizations, registry_ids=registry) == merged


@pytest.mark.parametrize("labels", [("", ""), ("%s", "%s")])
def test_registry_identity_without_usable_names_keeps_only_runtime_fallback(labels):
    identifier = "minecraft:future_probe_spawn_egg"
    localizations = {"spawn_egg.entity.future_probe": labels}

    merged = update_db.merge_items({}, {}, {}, item_localizations=localizations, registry_ids=[identifier])
    quality = update_db.item_label_quality([identifier], merged, {}, {}, {}, {}, localizations)

    assert identifier not in merged
    assert all(quality[locale] == {"total": 1, "official": 0, "fallbacks": [{"id": identifier, "source": "identifier"}]} for locale in ("de", "en"))


@pytest.mark.parametrize("existing", [None, ("minecraft:future_probe", "minecraft:future_probe"), ("Eigener Name", "Custom Name")])
def test_alias_without_usable_labels_does_not_persist_new_fallback_names(existing):
    identifier = "minecraft:future_probe"
    old = {identifier: existing} if existing else {}
    merged = update_db.merge_items(old, {}, {}, serialization_aliases={"future_probe": "legacy_probe"}, registry_ids=[identifier])
    assert merged == old


@pytest.mark.parametrize("locales", [("de", "en"), ("de",), ("en",), ()])
@pytest.mark.parametrize("custom", [False, True])
def test_registry_only_names_survive_preview_token_apply_runtime_and_retry(updater, locales, custom):
    identifier = "minecraft:future_probe_spawn_egg"
    names = {"de": "Quellenwesen-Spawn-Ei", "en": "Source Creature Egg"}
    own_names = ["Eigenes Spawn-Ei", "Custom Egg"]
    assert updater.run()[0] == 0
    database = updater.read_db()
    assert identifier not in database["items"]
    if custom:
        database["items"][identifier] = own_names
        updater.write_db(database)
    members = _members()
    registry = json.loads(members["metadata/vanilladata_modules/mojang-items.json"])
    registry["data_items"].append(
        {"name": identifier, "command_name": identifier, "serialization_name": identifier, "serialization_id": "item.future_probe_spawn_egg"}
    )
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps(registry)
    for locale in locales:
        filename = "de_DE" if locale == "de" else "en_US"
        members[f"resource_pack/texts/{filename}.lang"] += f"item.spawn_egg.entity.future_probe.name={names[locale]}\n"
    updater.write_source(members)
    before = updater.snapshot()

    code, preview = updater.run("--dry-run")
    assert code == 0 and updater.snapshot() == before
    token = item_db_verification.update_review_snapshot(
        update_cache_dir=update_db.CACHE_DIR,
        item_db_path=update_db.ITEM_DB_PATH,
        source_version_path=update_db.SOURCE_VERSION_JSON,
        source_version_history_path=update_db.SOURCE_VERSION_HISTORY,
        scope=None,
    )["token"]
    code, applied = updater.run("--expected-review-token", token)
    assert code == 0 and applied["applied"] and not applied["blocked"]
    assert applied["quality"] == preview["quality"] == updater.read_metadata()["update_quality"]
    saved = updater.read_db()
    assert identifier in saved["addable_items"]
    expected = own_names if custom else [names[locale if locale in locales else locales[0]] for locale in ("de", "en")] if locales else None
    assert saved["items"].get(identifier) == expected
    with item_data.use_item_catalog(item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)):
        assert item_data.selectable_item_catalog()[identifier] == tuple(expected or ["Future Probe Spawn Egg"] * 2)
    quality = applied["quality"]["sections"]["items"]["locales"]
    for locale in ("de", "en"):
        fallbacks = [entry for entry in quality[locale]["fallbacks"] if entry["id"] == identifier]
        assert quality[locale]["official"] == 1 + int(locale in locales)
        assert fallbacks == (
            [] if locale in locales else [{"id": identifier, "source": "existing" if custom else "other_language" if locales else "identifier"}]
        )
    assert item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]
    assert updater.run()[1]["status"] == "current"
