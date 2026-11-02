"""Reviewed source references, not updater-generated expectations."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from mcbe_editor import item_localization as names
from mcbe_editor.item_db_verification import update_review_snapshot
from mcbe_editor.update_db_report import quality_has_warnings, update_outcome
from tests.test_update_db import update_db
from tests.test_update_source_quality import _members
from tests.test_update_source_quality import updater as updater

REFERENCE = json.loads((Path(__file__).parent / "fixtures/item_localization_reference.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("disc", [False, True])
@pytest.mark.parametrize("shared_en", [False, True])
def test_multiple_registry_references_require_agreement_for_each_language(disc, shared_en):
    item = "music_disc_probe" if disc else "probe"
    first, second = ("item.record_a", "item.record_b") if disc else ("item.saddle", "item.diamond_sword")
    suffix = ".desc" if disc else ".name"
    registry = {"data_items": [{"name": item, "serialization_id": key} for key in (first, second)]}
    languages = {
        "de": names.parse_source_labels(f"{first}{suffix}=Sattel\nitem.record.name=Schallplatte"),
        "en": names.parse_source_labels(f"{second}{suffix}=Diamond Sword\nitem.record.name=Music Disc"),
    }
    if shared_en:
        languages["en"][first + suffix] = "Diamond Sword"
    result = names.registry_item_labels([item], registry, {}, languages, {item: "Diamond Sword"})[item]
    assert result["reasons"] == ({"de": "ambiguous"} if shared_en else {"de": "ambiguous", "en": "ambiguous"})
    assert result["official"] == ({"en": "Diamond Sword"} if shared_en and not disc else {})
    assert result["composed"] == ({"en": "Music Disc – Diamond Sword"} if shared_en and disc else {})


def test_incomplete_or_non_name_references_do_not_publish_false_official_translations(updater):
    member = _members()
    refs = {"split_probe": ("item.saddle", "item.diamond_sword"), "message_probe": ("tile.respawn_anchor.respawnSet",), "bundle_probe": ("item.bundle",)}
    member["metadata/vanilladata_modules/mojang-items.json"] = json.dumps(
        {"data_items": [{"name": identifier, "serialization_id": key} for identifier, keys in refs.items() for key in keys]}
    )
    member["resource_pack/texts/de_DE.lang"] += "item.saddle.name=Sattel\ntile.respawn_anchor.respawnSet=Wiederbeleben-Punkt festgelegt\nitem.bundle=Bündel\n"
    member["resource_pack/texts/en_US.lang"] += "item.diamond_sword.name=Diamond Sword\ntile.respawn_anchor.respawnSet=Respawn point set\nitem.bundle=Bundle\n"
    updater.write_source(member)
    before = updater.snapshot()
    code, preview = updater.run("--dry-run")
    assert code == 0 and before == updater.snapshot()
    code, applied = updater.run()
    assert code == 0 and applied["quality"] == preview["quality"]
    items = updater.read_db()["items"]
    assert items["minecraft:bundle_probe"] == ["Bündel", "Bundle"]
    assert "minecraft:split_probe" not in items and "minecraft:message_probe" not in items
    for coverage in applied["quality"]["sections"]["items"]["locales"].values():
        assert coverage["official"] == 1 and coverage["total"] == 3
        assert {"id": "minecraft:split_probe", "source": "identifier", "reason": "ambiguous"} in coverage["fallbacks"]
    assert updater.run()[1]["status"] == "current"


def reference_inputs():
    registries = {
        kind: {"data_items": [{"name": row["id"], "serialization_id": row[field]} for row in REFERENCE["cases"] if row[field]]}
        for kind, field in (("items", "item_ref"), ("blocks", "block_ref"))
    }
    languages = {
        locale: names.parse_source_labels("\n".join(f"{key}={value}" for key, value in labels.items())) for locale, labels in REFERENCE["languages"].items()
    }
    return registries, languages


@pytest.mark.parametrize("bad_key", ["item.canBreak", "item.canPlace", "item.customProperties", "item.dyed", "item.unbreakable", "item.unknownTooltip"])
def test_bare_messages_are_excluded_from_both_registry_lookup_and_english_bridge(bad_key):
    registry = {
        "data_items": [{"name": "direct", "serialization_id": bad_key}, {"name": "bridged"}, {"name": "renamed_bundle", "serialization_id": "item.red_bundle"}]
    }
    languages = {locale: names.parse_source_labels(f"{bad_key}=Tooltip\nitem.red_bundle=Bundle") for locale in ("de", "en")}
    source = names.registry_item_labels(["direct", "bridged", "renamed_bundle"], registry, {}, languages, {"bridged": "Tooltip"})
    assert source["direct"]["official"] == source["bridged"]["official"] == {}
    assert source["renamed_bundle"]["official"] == {"de": "Bundle", "en": "Bundle"}


def test_language_keys_can_label_existing_and_registered_ids_without_creating_tooltip_items(updater):
    members = _members()
    members["metadata/vanilladata_modules/mojang-blocks.json"] = json.dumps({"data_items": [{"name": "source_block"}]})
    db = updater.read_db()
    db["items"]["minecraft:legacy_probe"] = ["Mein Altbestand", "My legacy item"]
    updater.write_db(db)
    for filename in ("de_DE", "en_US"):
        members[f"resource_pack/texts/{filename}.lang"] += (
            "item.unknownTooltip=Use an item\nitem.message_probe.name=A status message\ntile.source_block.name=Source Block\nitem.legacy_probe=Legacy Probe\n"
        )
    updater.write_source(members)
    before = updater.snapshot()
    code, preview = updater.run("--dry-run")
    assert code == 0 and updater.snapshot() == before
    code, applied = updater.run()
    assert code == 0 and preview["sections"] == applied["sections"]
    items = updater.read_db()["items"]
    assert items.keys() - db["items"].keys() == {"minecraft:source_block"}
    assert items["minecraft:legacy_probe"] == db["items"]["minecraft:legacy_probe"]
    assert items["minecraft:source_block"] == ["Source Block", "Source Block"]
    assert updater.run("--dry-run")[1]["status"] == "current"


@pytest.mark.parametrize("invalid", ["item.other.desc", "not-a-language-reference", None])
def test_competing_unusable_registry_row_cannot_license_a_label_or_disc_title(invalid):
    for item, first in (("probe", "item.saddle"), ("music_disc_probe", "item.record_a")):
        registry = {"data_items": [{"name": item, "serialization_id": ref} for ref in (first, invalid)]}
        languages = {"en": names.parse_source_labels("item.saddle.name=Saddle\nitem.record.name=Music Disc\nitem.record_a.desc=Song A\nitem.other.desc=Song B")}
        result = names.registry_item_labels([item], registry, {}, languages, {item: "Saddle"})[item]
        assert result["official"] == result["composed"] == {}
        assert result["reasons"] == {"en": "ambiguous"}


@pytest.mark.parametrize("case", REFERENCE["cases"], ids=lambda case: case["id"])
def test_complete_reviewed_source_mapping(case):
    registries, languages = reference_inputs()
    result = names.registry_item_labels([case["id"]], registries["items"], registries["blocks"], languages)[case["id"].removeprefix("minecraft:")]
    assert result["reasons"] == {}
    expected = dict(zip(("de", "en"), case["names"], strict=True))
    assert result["official"] == (expected if case["kind"] == "official" else {})
    assert result["composed"] == (expected if case["kind"] == "composed" else {})


@pytest.mark.parametrize("custom", [False, True])
def test_source_reference_preview_apply_existing_names_and_repeat(updater, custom):
    registries, _languages = reference_inputs()
    members = _members()
    for kind, registry in registries.items():
        members[f"metadata/vanilladata_modules/mojang-{kind}.json"] = json.dumps(registry)
    for locale, file in (("de", "de_DE"), ("en", "en_US")):
        members[f"resource_pack/texts/{file}.lang"] += "\n".join(f"{key}={value}" for key, value in REFERENCE["languages"][locale].items())
    updater.write_source(members)
    before = updater.read_db()
    if custom:
        for identifier in ("stone", "axolotl_bucket", "music_disc_11", "light_block_0", "petrified_oak_slab"):
            before["items"][f"minecraft:{identifier}"] = [f"Eigener {identifier}", f"Custom {identifier}"]
        before["items"]["minecraft:filled_map"][0] = "Meine Karte"
        before["items"]["minecraft:cod_bucket"][1] = "My fish bucket"
        updater.write_db(before)
    code, preview = updater.run("--dry-run")
    assert code == 0 and updater.read_db() == before
    token = update_review_snapshot(
        update_cache_dir=update_db.CACHE_DIR,
        item_db_path=update_db.ITEM_DB_PATH,
        source_version_path=update_db.SOURCE_VERSION_JSON,
        source_version_history_path=update_db.SOURCE_VERSION_HISTORY,
        scope=None,
    )["token"]
    code, applied = updater.run("--expected-review-token", token)
    assert code == 0 and applied["quality"] == preview["quality"]
    for locale, coverage in applied["quality"]["sections"]["items"]["locales"].items():
        assert coverage["total"] == 78 and coverage["official"] == 49
        assert Counter(row.get("reason", "unresolved") for row in coverage["fallbacks"]) == {
            "composed": 22,
            "category": 3,
            "editorial" if locale == "de" else "unresolved": 4,
        }
        assert next(row for row in coverage["fallbacks"] if row["id"] == "minecraft:music_disc_11")["source"] == ("existing" if custom else "curated")
    after = updater.read_db()
    for case in REFERENCE["cases"]:
        if case["id"] in before["items"]:
            assert after["items"][case["id"]] == before["items"][case["id"]]
        else:
            assert case["kind"] == "missing" and case["id"] not in after["items"]
    assert updater.read_metadata()["update_quality"] == applied["quality"]
    assert updater.run()[1]["status"] == "current"


@pytest.mark.parametrize("locale", ["de", "en"])
def test_exact_key_reference_works_with_one_locale_and_never_creates_pseudo_ids(locale):
    source = names.registry_item_labels(
        ["minecraft:probe"],
        {"data_items": [{"name": "probe", "serialization_id": "tile.family.variant"}]},
        {},
        {locale: names.parse_source_labels("tile.family.variant.name=Source\nitem.family.variant.name=Unrelated")},
    )
    merged = update_db.merge_items({}, {}, {}, registry_ids=["minecraft:probe"], source_labels=source)
    assert merged == {"minecraft:probe": ("Source", "Source")}
    quality = update_db.item_label_quality(["minecraft:probe"], merged, {}, {}, {}, {}, {}, source_labels=source)
    assert quality[locale]["official"] == 1
    assert quality["en" if locale == "de" else "de"]["official"] == 0


@pytest.mark.parametrize("damage", ["duplicate_label", "duplicate_registry"])
def test_conflicting_references_cannot_fall_through_to_learn_or_block_name(damage):
    entries = [{"name": "probe", "serialization_id": "item.probe"}]
    text = "item.probe.name=First\ntile.probe.name=Block\nitem.elsewhere.name=First"
    if damage == "duplicate_label":
        text += "\nitem.probe.name=Second"
    else:
        entries.append({"name": "probe", "serialization_id": "item.other"})
        text += "\nitem.other.name=Second"
    source = names.registry_item_labels(
        ["minecraft:probe"],
        {"data_items": entries},
        {"data_items": [{"name": "probe", "serialization_id": "tile.probe"}]},
        {"en": names.parse_source_labels(text)},
    )
    assert source["probe"]["official"] == {} and source["probe"]["reasons"] == {"en": "ambiguous"}
    quality = update_db.item_label_quality(
        ["minecraft:probe"],
        {},
        {},
        {"probe": "First"},
        {},
        {},
        {"elsewhere": ("Erster", "First")},
        {"probe": "First"},
        source,
    )
    assert quality["en"]["official"] == 0
    assert quality["de"]["official"] == 0
    assert quality["en"]["fallbacks"][0]["reason"] == "ambiguous"


def test_crop_block_collision_and_unknown_registry_identity_do_not_supply_item_names():
    result = names.registry_item_labels(
        ["minecraft:wheat", "minecraft:beetroot", "minecraft:unrelated"],
        {},
        {"data_items": [{"name": item, "serialization_id": f"tile.{item}"} for item in ("wheat", "beetroot", "probe")]},
        {"en": names.parse_source_labels("tile.wheat.name=Crop\ntile.beetroot.name=Crop\ntile.probe.name=Unrelated")},
    )
    assert all(record == {"official": {}, "composed": {}, "reasons": {}} for record in result.values())


@pytest.mark.parametrize("item,reference,unrelated", [("probe", "tile.family.variant", "tile.family.name"), ("wheat", "item.wheat", "tile.wheat.name")])
def test_unresolved_exact_reference_cannot_be_replaced_by_truncated_or_wrong_namespace_name(item, reference, unrelated, tmp_path):
    paths = {locale: tmp_path / (locale + ".lang") for locale in ("de", "en")}
    for path in paths.values():
        path.write_text(unrelated + "=Wrong Source", encoding="utf-8")
    en_names, de_names = update_db.parse_lang_items(paths["en"], paths["de"])
    localizations = update_db.parse_lang_item_localizations(paths["en"], paths["de"])
    source = names.registry_item_labels(
        ["minecraft:" + item],
        {"data_items": [{"name": item, "serialization_id": reference}]},
        {},
        {locale: names.parse_source_labels(path.read_text(encoding="utf-8")) for locale, path in paths.items()},
    )
    aliases = {item: update_db._serialization_lang_key(reference)}
    merged = update_db.merge_items({}, en_names, de_names, {}, aliases, localizations, ["minecraft:" + item], source)
    quality = update_db.item_label_quality(["minecraft:" + item], merged, {}, en_names, de_names, aliases, localizations, {}, source)
    assert all(coverage["official"] == 0 for coverage in quality.values())
    assert "Wrong Source" not in merged.get("minecraft:" + item, ())


@pytest.mark.parametrize("origin", ["existing", "learn"])
def test_old_language_alias_cannot_supply_an_unrelated_existing_or_learn_name(origin):
    source = names.registry_item_labels(
        ["minecraft:probe"], {"data_items": [{"name": "probe", "serialization_id": "item.family.variant"}]}, {}, {"en": {}, "de": {}}
    )
    old = {"minecraft:family": ("Familie", "Family")} if origin == "existing" else {}
    listing = {"family": "Family"} if origin == "learn" else {}
    merged = update_db.merge_items(old, {}, {}, listing, {"probe": "family"}, registry_ids=["minecraft:probe"], source_labels=source)
    assert "minecraft:probe" not in merged


def test_other_namespace_cannot_fill_missing_reference_locale(tmp_path):
    files = {"en": "item.family.variant.name=First", "de": "tile.family.variant.name=Unrelated German"}
    for locale, content in files.items():
        (tmp_path / (locale + ".lang")).write_text(content, encoding="utf-8")
    localizations = update_db.parse_lang_item_localizations(tmp_path / "en.lang", tmp_path / "de.lang")
    source = names.registry_item_labels(
        ["minecraft:probe"],
        {"data_items": [{"name": "probe", "serialization_id": "item.family.variant"}]},
        {},
        {locale: names.parse_source_labels(text) for locale, text in files.items()},
    )
    merged = update_db.merge_items({}, {}, {}, item_localizations=localizations, registry_ids=["minecraft:probe"], source_labels=source)
    assert merged["minecraft:probe"] == ("First", "First")
    quality = update_db.item_label_quality(["minecraft:probe"], merged, {}, {}, {}, {}, localizations, source_labels=source)
    assert quality["en"]["official"] == 1 and quality["de"]["official"] == 0


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "german,expected,reason",
    [
        ("item.bucketWater.name=Wassereimer\ntile.container.name=Wassereimer", "Wassereimer", None),
        ("item.bucketWater.name=Wassereimer\ntile.container.name=Wasserbehälter", None, "ambiguous"),
        ("item.bucketWater.name=Wassereimer\nitem.bucketWater.name=Wasserbehälter", None, "ambiguous"),
        ("", None, None),
        ("item.bucketWater.name=Wassereimer", None, None),
    ],
)
def test_label_bridge_keeps_english_and_reports_german_conflicts_per_locale(reverse, german, expected, reason):
    english = ["item.bucketWater.name=Water Bucket", "tile.container.name=Water Bucket"]
    if reverse:
        english.reverse()
    result = names.registry_item_labels(
        ["minecraft:water_bucket"],
        {"data_items": [{"name": "water_bucket", "serialization_id": "item.water_bucket"}]},
        {},
        {"de": names.parse_source_labels(german), "en": names.parse_source_labels("\n".join(english))},
        {"water_bucket": "Water Bucket"},
    )["water_bucket"]
    assert result["official"] == {"en": "Water Bucket", **({"de": expected} if expected else {})}
    assert result["reasons"] == ({"de": reason} if reason else {})


@pytest.mark.parametrize("direct_locale", ["de", "en", "both"])
def test_direct_registry_names_outrank_bridge_conflicts_in_the_same_locale(direct_locale):
    english = "item.bucketWater.name=Water Bucket\ntile.container.name=Water Bucket"
    german = "item.bucketWater.name=Wassereimer\ntile.container.name=Wasserbehälter"
    if direct_locale in {"en", "both"}:
        english += "\nitem.water_bucket.name=Water Bucket"
    if direct_locale in {"de", "both"}:
        german += "\nitem.water_bucket.name=Direkter Wassereimer"
    result = names.registry_item_labels(
        ["minecraft:water_bucket"],
        {"data_items": [{"name": "water_bucket", "serialization_id": "item.water_bucket"}]},
        {},
        {"de": names.parse_source_labels(german), "en": names.parse_source_labels(english)},
        {"water_bucket": "Water Bucket"},
    )["water_bucket"]
    assert result["official"]["en"] == "Water Bucket"
    if direct_locale in {"de", "both"}:
        assert result["official"]["de"] == "Direkter Wassereimer"
        assert result["reasons"] == {}
    else:
        assert result["reasons"] == {"de": "ambiguous"}


@pytest.mark.parametrize("custom_locale", [None, "de", "en", "both"])
def test_bridge_conflict_preview_apply_repeat_and_source_repair_preserve_names(updater, monkeypatch, custom_locale):
    monkeypatch.setattr(update_db, "resolve_microsoft_item_listing_snapshot", lambda **_kwargs: ({"water_bucket": "Water Bucket"}, {}))
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps(
        {"data_items": [{"name": "minecraft:water_bucket", "serialization_id": "item.water_bucket"}]}
    )
    members["resource_pack/texts/en_US.lang"] += "item.bucketWater.name=Water Bucket\ntile.container.name=Water Bucket\n"
    german_base = members["resource_pack/texts/de_DE.lang"] + "item.bucketWater.name=Wassereimer\n"
    db = updater.read_db()
    expected_names = ["Mein Eimer" if custom_locale in {"de", "both"} else "Wassereimer", "My bucket" if custom_locale in {"en", "both"} else "Water Bucket"]
    db["items"]["minecraft:water_bucket"] = expected_names
    updater.write_db(db)
    for conflict in (True, False):
        members["resource_pack/texts/de_DE.lang"] = german_base + "tile.container.name=" + ("Wasserbehälter" if conflict else "Wassereimer") + "\n"
        updater.write_source(members)
        before = updater.snapshot()
        code, preview = updater.run("--dry-run")
        assert code == 0 and updater.snapshot() == before
        token = update_review_snapshot(
            update_cache_dir=update_db.CACHE_DIR,
            item_db_path=update_db.ITEM_DB_PATH,
            source_version_path=update_db.SOURCE_VERSION_JSON,
            source_version_history_path=update_db.SOURCE_VERSION_HISTORY,
            scope=None,
        )["token"]
        code, applied = updater.run("--expected-review-token", token)
        assert code == 0 and applied["applied"] is True
        assert preview["quality"] == applied["quality"] == updater.read_metadata()["update_quality"]
        assert updater.read_db()["items"]["minecraft:water_bucket"] == expected_names
        locales = applied["quality"]["sections"]["items"]["locales"]
        assert locales["en"]["total"] == locales["en"]["official"] == locales["de"]["total"] == 1
        assert locales["de"]["official"] == int(not conflict)
        if conflict:
            assert locales["de"]["fallbacks"] == [
                {"id": "minecraft:water_bucket", "source": "existing" if custom_locale in {"de", "both"} else "curated", "reason": "ambiguous"}
            ]
        else:
            assert locales["de"]["fallbacks"] == []
        assert quality_has_warnings(applied["quality"]) is conflict
        assert update_outcome(success=True, committed=True, report=applied) == ("updated_with_warnings" if conflict else "updated")
        code, retry = updater.run()
        assert code == 0 and retry["status"] == "current" and retry["quality"] == applied["quality"]
        assert quality_has_warnings(retry["quality"]) is conflict


@pytest.mark.parametrize("locale", ["de", "en"])
def test_white_bed_variant_does_not_borrow_missing_locale_from_generic_or_black_bed(locale, tmp_path):
    text = {
        "de": "item.bed.name=Bett\nitem.bed.black.name=Schwarzes Bett\n",
        "en": "item.bed.name=Bed\nitem.bed.black.name=Black Bed\n",
    }
    text[locale] += "item.bed.white.name=" + ("Weißes Bett" if locale == "de" else "White Bed")
    for language, content in text.items():
        (tmp_path / (language + ".lang")).write_text(content, encoding="utf-8")
    source = names.registry_item_labels(
        ["minecraft:bed"],
        {"data_items": [{"name": "bed", "serialization_id": "item.bed"}]},
        {},
        {language: names.parse_source_labels(content) for language, content in text.items()},
        {"bed": "Black Bed"},
    )
    en_names, de_names = update_db.parse_lang_items(tmp_path / "en.lang", tmp_path / "de.lang")
    localizations = update_db.parse_lang_item_localizations(tmp_path / "en.lang", tmp_path / "de.lang")
    old = {"minecraft:bed": ("Schwarzes Bett", "Black Bed")}
    merged = update_db.merge_items(old, en_names, de_names, {"bed": "Black Bed"}, {}, localizations, ["minecraft:bed"], source)
    assert merged["minecraft:bed"] == ("Weißes Bett", "White Bed")
    quality = update_db.item_label_quality(["minecraft:bed"], merged, old, en_names, de_names, {}, localizations, {"bed": "Black Bed"}, source)
    assert quality[locale]["official"] == 1
    assert quality["en" if locale == "de" else "de"]["official"] == 0


@pytest.mark.parametrize("identifier", ["probe", "bed"])
def test_conflicting_source_cannot_authorize_variant_name_migration(updater, identifier):
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": identifier, "serialization_id": f"item.{identifier}"}]})
    members["metadata/vanilladata_modules/mojang-blocks.json"] = json.dumps({"data_items": [{"name": identifier, "serialization_id": f"tile.{identifier}"}]})
    db = updater.read_db()
    db["items"][f"minecraft:{identifier}"] = ["Eins", "One"]
    updater.write_db(db)
    for locale, labels in (("de_DE", ("Eins", "Erste Basis", "Zweite Basis")), ("en_US", ("One", "First Base", "Second Base"))):
        one, first, second = labels
        members[f"resource_pack/texts/{locale}.lang"] += (
            f"tile.{identifier}.name={first}\ntile.{identifier}.name={second}\n"
            f"tile.{identifier}.one.name={one}\ntile.{identifier}.two.name=Two\n"
            + (f"item.bed.white.name={first}\nitem.bed.white.name={second}\nitem.bed.black.name={one}\n" if identifier == "bed" else "")
        )
    updater.write_source(members)
    assert updater.run()[0] == 0
    assert updater.read_db()["items"][f"minecraft:{identifier}"] == ["Eins", "One"]
    for locale in updater.read_metadata()["update_quality"]["sections"]["items"]["locales"].values():
        assert locale["official"] == 0 and locale["fallbacks"][0]["reason"] == "ambiguous"


@pytest.mark.parametrize("custom_locale", [0, 1])
def test_potion_category_classification_does_not_couple_custom_locales(custom_locale):
    current = list(update_db._bundled_limits["items"]["minecraft:potion"])
    current[custom_locale] = "Personal label"
    quality = update_db.item_label_quality(["minecraft:potion"], {"minecraft:potion": current}, {"minecraft:potion": current}, {}, {}, {}, {})
    for index, locale in enumerate(("de", "en")):
        entry = quality[locale]["fallbacks"][0]
        assert entry.get("reason") == (None if index == custom_locale else "category")


def test_arbitrary_subtitle_never_becomes_official_item_name():
    result = names.registry_item_labels(
        ["minecraft:probe"],
        {"data_items": [{"name": "probe", "serialization_id": "item.probe.desc"}]},
        {},
        {"en": names.parse_source_labels("item.probe.desc=Tooltip")},
    )
    assert result["probe"]["official"] == result["probe"]["composed"] == {}


@pytest.mark.parametrize("identifier,reference,learn", [("music_disc_probe", "item.record_probe", "Music Disc"), ("potion", "item.potion", "Water Bottle")])
def test_learn_wording_cannot_remove_disc_titles_or_select_a_potion_variant(identifier, reference, learn):
    source = names.registry_item_labels(
        ["minecraft:" + identifier],
        {"data_items": [{"name": identifier, "serialization_id": reference}]},
        {},
        {
            "en": names.parse_source_labels("item.record.name=Music Disc\nitem.record_probe.desc=Composer - Song\nitem.potion.water.name=Water Bottle"),
            "de": names.parse_source_labels("item.record.name=Schallplatte\nitem.record_probe.desc=Komponist - Lied\nitem.potion.water.name=Wasserflasche"),
        },
        {identifier: learn},
    )
    assert source[identifier]["official"] == {}
    merged = update_db.merge_items({}, {}, {}, {identifier: learn}, registry_ids=["minecraft:" + identifier], source_labels=source)
    assert merged["minecraft:" + identifier] == (
        ("Schallplatte – Komponist - Lied", "Music Disc – Composer - Song") if identifier.startswith("music_disc_") else ("Trank", "Potion")
    )


@pytest.mark.parametrize("missing", ["base", "title"])
def test_disc_composition_requires_both_same_locale_parts_and_exact_registry_identity(missing):
    english = "item.record.name=Music Disc\nitem.record_probe.desc=Composer - Song"
    german = "item.record.name=Schallplatte" if missing == "title" else "item.record_probe.desc=Komponist - Lied"
    result = names.registry_item_labels(
        ["minecraft:music_disc_probe", "minecraft:probe"],
        {"data_items": [{"name": "music_disc_probe", "serialization_id": "item.record_probe"}, {"name": "probe", "serialization_id": "item.record_probe"}]},
        {},
        {"de": names.parse_source_labels(german), "en": names.parse_source_labels(english)},
    )
    assert result["music_disc_probe"]["composed"] == {"en": "Music Disc – Composer - Song"}
    assert result["probe"]["official"] == result["probe"]["composed"] == {}
    merged = update_db.merge_items({}, {}, {}, registry_ids=["minecraft:music_disc_probe"], source_labels=result)
    assert merged["minecraft:music_disc_probe"] == ("Music Disc – Composer - Song", "Music Disc – Composer - Song")
