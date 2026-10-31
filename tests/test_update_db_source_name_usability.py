"""Unusable source labels affect one locale, not a validated identity."""

from __future__ import annotations

import json

import pytest

from mcbe_editor import item_data, update_source_quality
from tests.test_update_db import update_db
from tests.test_update_source_quality import _members
from tests.test_update_source_quality import updater as updater


@pytest.mark.parametrize("path", ["direct", "alias", "derived"])
@pytest.mark.parametrize("unusable", ["de", "en"])
@pytest.mark.parametrize("placeholder", ["%s", "%1$s", "%entity.future_probe.name"])
def test_one_unusable_locale_preserves_the_other_source_name_and_coverage(path, unusable, placeholder):
    key = "future_probe_spawn_egg" if path == "derived" else "future_probe"
    identifier = "minecraft:" + key
    names = {locale: placeholder if locale == unusable else "Concrete Source Name" for locale in ("de", "en")}
    source_key = "legacy_probe" if path == "alias" else key
    en = {source_key: names["en"]} if path != "derived" else {}
    de = {source_key: names["de"]} if path != "derived" else {}
    aliases = {key: "legacy_probe"} if path != "direct" else {}
    localizations = {"spawn_egg.entity.future_probe": (names["de"], names["en"])} if path == "derived" else {}

    merged = update_db.merge_items({}, en, de, {}, aliases, localizations)
    quality = update_db.item_label_quality([identifier], merged, {}, en, de, aliases, localizations)

    assert merged[identifier] == ("Concrete Source Name", "Concrete Source Name")
    assert quality[unusable] == {"total": 1, "official": 0, "fallbacks": [{"id": identifier, "source": "other_language"}]}
    assert quality["en" if unusable == "de" else "de"] == {"total": 1, "official": 1, "fallbacks": []}
    assert update_db.merge_items(merged, en, de, {}, aliases, localizations) == merged


@pytest.mark.parametrize("section", ["items", "effects", "enchants"])
@pytest.mark.parametrize("unusable", ["de", "en"])
def test_cli_preview_apply_and_reload_use_the_same_source_name_rule(updater, section, unusable):
    identifier = "minecraft:future_probe"
    members = _members(labels=False)
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": identifier}]})
    label_key = {"items": "item.future_probe.name", "effects": "potion.moveSpeed", "enchants": "enchantment.durability"}[section]
    for locale, filename in (("de", "de_DE"), ("en", "en_US")):
        label = "%s" if locale == unusable else "Concrete Source Name"
        members[f"resource_pack/texts/{filename}.lang"] += f"{label_key}={label}\n"
    updater.write_source(members)
    database = updater.read_db()
    database[{"items": "items", "effects": "effects", "enchants": "enchantments"}[section]] = {}
    updater.write_db(database)

    code, preview = updater.run("--dry-run")
    assert code == 0 and updater.read_db() == database
    code, applied = updater.run()
    assert code == 0
    quality = applied["quality"]["sections"][section]["locales"]
    assert quality == preview["quality"]["sections"][section]["locales"]
    assert quality[unusable]["official"] == 0
    assert quality["en" if unusable == "de" else "de"]["official"] == 1
    runtime = item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)
    result = runtime[{"items": "ITEMS", "effects": "EFFECTS", "enchants": "ENCHANTMENTS"}[section]]
    names = result[{"items": identifier, "effects": 1, "enchants": 17}[section]][:2]
    assert names[0 if unusable == "en" else 1] == "Concrete Source Name"
    assert all("%" not in name for name in names)
    if section == "items":
        assert names == ("Concrete Source Name", "Concrete Source Name")
        assert not any(issue["code"] == f"name_differences_{unusable}" for issue in applied["audit"]["issues"])
    assert updater.read_metadata()["update_quality"] == applied["quality"]
    assert updater.run()[1]["status"] == "current"


@pytest.mark.parametrize("kind", ["existing", "curated", "alias"])
def test_percent_signs_in_display_fallbacks_are_preserved(monkeypatch, kind):
    identifier = "minecraft:future_probe"
    names = ("100% eigener Name", "100% custom name")
    old = {identifier: names} if kind == "existing" else {"minecraft:legacy_probe": names} if kind == "alias" else {}
    if kind == "curated":
        monkeypatch.setitem(update_db._bundled_limits["items"], identifier, names)
    aliases = {"future_probe": "legacy_probe"}

    merged = update_db.merge_items(old, {}, {}, {}, aliases)
    quality = update_db.item_label_quality([identifier], merged, old, {}, {}, aliases, {})

    assert merged[identifier] == names
    assert all(quality[locale]["official"] == 0 for locale in ("de", "en"))


def test_shared_resolution_and_coverage_reject_the_same_unusable_source_locale():
    official = {"de": "%s", "en": "Concrete Source Name"}
    names, sources = update_source_quality.resolve_names("minecraft:probe", official)
    quality = update_source_quality.coverage([("minecraft:probe", official, sources)])
    assert names == ("Concrete Source Name", "Concrete Source Name")
    assert sources == ("other_language", "official")
    assert quality["de"]["official"] == 0
    assert quality["en"]["official"] == 1


def test_unusable_secondary_source_cannot_claim_a_matching_custom_name():
    original = ("Eigener Name", "100% custom name")
    names, sources = update_source_quality.resolve_names("minecraft:probe", {}, existing=original, secondary={"en": original[1]})
    assert names == original
    assert sources == ("existing", "existing")


@pytest.mark.parametrize("section,key,extra", [("effects", "1", ["", ""]), ("enchantments", "17", [3, ""])])
def test_numeric_catalogs_preserve_custom_percent_names(updater, section, key, extra):
    original = ["100% eigener Name", "100% custom name", *extra]
    database = updater.read_db()
    database[section] = {key: original}
    updater.write_db(database)
    members = _members(labels=False)
    label_key = "potion.moveSpeed" if section == "effects" else "enchantment.durability"
    for locale in ("de_DE", "en_US"):
        members[f"resource_pack/texts/{locale}.lang"] += f"{label_key}=%s\n"
    updater.write_source(members)

    assert updater.run()[0] == 0
    assert updater.read_db()[section][key][:2] == original[:2]
    runtime = item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)
    assert runtime[section.upper()][int(key)][:2] == tuple(original[:2])


@pytest.mark.parametrize(
    "parser,content,expected",
    [
        (update_db.parse_lang_effects, "effect.speed=%s\npotion.moveSpeed=Speed\n", {"speed": "Speed"}),
        (update_db.parse_lang_enchantments, "enchant.unbreaking=%s\nenchantment.durability=Unbreaking\n", {"unbreaking": "Unbreaking"}),
    ],
)
def test_unusable_numeric_label_does_not_hide_a_later_usable_alias(parser, content, expected):
    assert parser(content) == expected
