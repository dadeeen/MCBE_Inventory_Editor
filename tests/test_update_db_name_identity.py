"""Display fallback names cannot establish the identity of a source label."""

from __future__ import annotations

import json

import pytest

from mcbe_editor import item_data
from tests.test_update_db import update_db
from tests.test_update_source_quality import _members
from tests.test_update_source_quality import updater as updater


@pytest.mark.parametrize("origin", ["existing", "curated", "other_language", "identifier"])
def test_fallback_names_cannot_establish_an_official_label_bridge(monkeypatch, origin):
    identifier = "minecraft:future_probe"
    label = identifier if origin == "identifier" else "Diamond"
    old = {identifier: ("Diamond", "Diamond")} if origin == "existing" else {}
    if origin == "curated":
        monkeypatch.setitem(update_db._bundled_limits["items"], identifier, ("Diamond", "Diamond"))
    de_names = {"future_probe": label} if origin == "other_language" else {}
    localizations = {"unrelated.variant": ("Fremder Quellenname", label)}
    aliases = {"future_probe": "missing_legacy_key"}

    merged = update_db.merge_items(old, {}, de_names, {}, aliases, localizations)
    quality = update_db.item_label_quality([identifier], merged, old, {}, de_names, aliases, localizations)

    if origin == "identifier":
        assert identifier not in merged
    else:
        assert merged[identifier] == (label, label)
    assert quality["de"]["official"] == int(origin == "other_language")
    assert quality["en"]["official"] == 0
    assert quality["en"]["fallbacks"][0]["id"] == identifier
    assert update_db.merge_items(merged, {}, de_names, {}, aliases, localizations) == merged


def test_custom_name_cannot_override_the_identity_provided_by_learn():
    identifier = "minecraft:future_probe"
    old = {identifier: ("Diamond", "Diamond")}
    listing = {"future_probe": "Future Probe"}
    localizations = {"diamond": ("Diamant", "Diamond")}

    merged = update_db.merge_items(old, {}, {}, listing, {}, localizations)
    quality = update_db.item_label_quality([identifier], merged, old, {}, {}, {}, localizations, listing)

    assert merged == old
    assert all(quality[locale]["official"] == 0 for locale in ("de", "en"))


@pytest.mark.parametrize("source", ["direct", "learn", "alias", "alias_learn"])
def test_current_identity_bound_english_labels_can_bridge_to_unambiguous_localization(source):
    identifier = "minecraft:future_probe"
    en_names = {"future_probe": "Source Name"} if source == "direct" else {"legacy_probe": "Source Name"} if source == "alias" else {}
    listing = {"future_probe": "Source Name"} if source == "learn" else {"legacy_probe": "Source Name"} if source == "alias_learn" else {}
    aliases = {"future_probe": "legacy_probe"} if source.startswith("alias") else {}
    localizations = {"unrelated.variant": ("Quellenname", "Source Name")}

    merged = update_db.merge_items({}, en_names, {}, listing, aliases, localizations)
    quality = update_db.item_label_quality([identifier], merged, {}, en_names, {}, aliases, localizations, listing)

    assert merged[identifier] == ("Quellenname", "Source Name")
    assert all(quality[locale] == {"total": 1, "official": 1, "fallbacks": []} for locale in ("de", "en"))


@pytest.mark.parametrize("names", [("Mein Anzeigename", "Diamond"), ("Diamond", "Diamond")])
def test_update_persists_custom_names_and_honest_coverage_through_reload(updater, names):
    identifier = "minecraft:future_probe"
    database = updater.read_db()
    database["items"] = {identifier: list(names)}
    updater.write_db(database)
    members = _members(labels=False)
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": identifier}]})
    members["resource_pack/texts/en_US.lang"] += "item.diamond.name=Diamond\n"
    members["resource_pack/texts/de_DE.lang"] += "item.diamond.name=Diamant\n"
    updater.write_source(members)

    code, preview = updater.run("--dry-run")
    assert code == 0
    assert updater.read_db() == database
    assert updater.run()[0] == 0
    quality = updater.read_metadata()["update_quality"]["sections"]["items"]["locales"]
    assert quality == preview["quality"]["sections"]["items"]["locales"]
    assert all(quality[locale]["official"] == 0 for locale in ("de", "en"))
    assert updater.read_db()["items"][identifier] == list(names)
    assert item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)["ITEMS"][identifier] == names
    assert updater.run()[1]["status"] == "current"
