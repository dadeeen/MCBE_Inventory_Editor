"""Independent source locales and conservative cross-key name resolution."""

from __future__ import annotations

import pytest

from tests.test_update_db import update_db
from tests.test_update_source_quality import _members, updater as source_updater_fixture

updater = source_updater_fixture


@pytest.mark.parametrize("locale", ["de", "en"])
def test_single_locale_direct_names_survive_full_update_and_keep_honest_coverage(updater, locale):
    db = updater.read_db()
    db["items"] = {}
    updater.write_db(db)
    members = _members(labels=False)
    source_name = "Quellenstein" if locale == "de" else "Source Stone"
    source_file = "de_DE" if locale == "de" else "en_US"
    members[f"resource_pack/texts/{source_file}.lang"] += f"item.stone.name={source_name}\n"
    updater.write_source(members)

    code, report = updater.run()

    assert code == 0
    assert updater.read_db()["items"]["minecraft:stone"][0 if locale == "de" else 1] == source_name
    coverage = report["quality"]["sections"]["items"]["locales"]
    assert coverage[locale] == {"total": 1, "official": 1, "fallbacks": []}
    other = "en" if locale == "de" else "de"
    assert coverage[other]["official"] == 0
    assert coverage[other]["fallbacks"] == [{"id": "minecraft:stone", "source": "curated"}]
    assert updater.run()[1]["status"] == "current"


@pytest.mark.parametrize("locale", ["de", "en"])
def test_locale_union_does_not_turn_tooltips_or_dotted_keys_into_direct_item_ids(tmp_path, locale):
    paths = {lang: tmp_path / f"{lang}.lang" for lang in ("de", "en")}
    for lang, path in paths.items():
        path.write_text(
            "menu.play=Play\n"
            + ("item.probe.name=Source Name\nitem.canBreak=Tooltip\nitem.boat.probe.name=Probe Boat\nitem.probe.desc=Description\n" if lang == locale else ""),
            encoding="utf-8",
        )
    localizations = update_db.parse_lang_item_localizations(paths["en"], paths["de"])
    en_items, de_items = update_db.parse_lang_items(paths["en"], paths["de"])
    assert (de_items if locale == "de" else en_items) == {"probe": "Source Name"}
    assert (en_items if locale == "de" else de_items) == {}
    assert localizations["boat.probe"] == (("Probe Boat", "") if locale == "de" else ("", "Probe Boat"))
    assert "probe.desc" not in localizations


@pytest.mark.parametrize("locale", ["de", "en"])
@pytest.mark.parametrize(
    "identifier,key",
    [("bed", "bed.white"), ("acacia_chest_boat", "chest_boat.acacia"), ("probe_spawn_egg", "spawn_egg.entity.probe")],
)
def test_single_locale_structural_names_use_source_label_and_report_only_available_locale(locale, identifier, key):
    full_id = f"minecraft:{identifier}"
    source_name = "Quellenname" if locale == "de" else "Source Name"
    localizations = {key: (source_name, "") if locale == "de" else ("", source_name)}
    # The canonical identity is already known independently of either label.
    aliases = {identifier: "missing_legacy_key"}
    merged = update_db.merge_items({}, {}, {}, {}, aliases, localizations)
    assert merged[full_id][0 if locale == "de" else 1] == source_name
    assert all(merged[full_id])
    assert key not in {item_id.removeprefix("minecraft:") for item_id in merged}
    coverage = update_db.item_label_quality([full_id], merged, {}, {}, {}, aliases, localizations)
    assert coverage[locale] == {"total": 1, "official": 1, "fallbacks": []}
    assert coverage["en" if locale == "de" else "de"]["official"] == 0
    assert update_db.merge_items(merged, {}, {}, {}, aliases, localizations) == merged


@pytest.mark.parametrize("locale", ["de", "en"])
def test_placeholder_in_one_structural_locale_does_not_discard_the_other(locale):
    names = ("Quellenbett", "%unresolved") if locale == "de" else ("%unresolved", "Source Bed")
    localizations = {"bed.white": names}
    merged = update_db.merge_items({}, {}, {}, {"bed": "Black Bed"}, {}, localizations)
    coverage = update_db.item_label_quality(["minecraft:bed"], merged, {}, {}, {}, {}, localizations, {"bed": "Black Bed"})
    assert merged["minecraft:bed"][0 if locale == "de" else 1] == names[0 if locale == "de" else 1]
    assert coverage[locale]["official"] == 1
    assert coverage["en" if locale == "de" else "de"]["official"] == 0
    assert "%" not in " ".join(merged["minecraft:bed"])


@pytest.mark.parametrize("locale", ["de", "en"])
@pytest.mark.parametrize("identifier,key", [("bed", "bed.white"), ("probe_boat", "boat.probe")])
def test_one_sided_structural_sources_preserve_existing_custom_names(locale, identifier, key):
    full_id = f"minecraft:{identifier}"
    original = {full_id: ("Mein Anzeigename", "My display name")}
    pair = ("Quellenname", "") if locale == "de" else ("", "Source Name")
    assert update_db.merge_items(original, {}, {}, {}, {identifier: "missing_legacy_key"}, {key: pair}) == original


def test_single_locale_sources_do_not_relax_ambiguous_label_bridges():
    localizations = {
        "stone.a": ("Stein A", "Same Name"),
        "stone.b": ("Stein B", "Same Name"),
        "other.de_only": ("Same Name", ""),
    }
    index = update_db.build_item_localization_label_index(localizations)
    assert index == {}
    merged = update_db.merge_items({}, {}, {}, {"probe": "Same Name"}, {}, localizations)
    assert merged["minecraft:probe"] == ("Same Name", "Same Name")


@pytest.mark.parametrize("unavailable", ["", "%unresolved"])
def test_untranslated_competing_key_cannot_make_a_label_bridge_look_unambiguous(unavailable):
    localizations = {"source.a": ("Quelle A", "Same Name"), "source.b": (unavailable, "Same Name")}
    assert update_db.build_item_localization_label_index(localizations) == {}


def test_incomplete_variant_pair_does_not_authorize_replacing_an_existing_name():
    original = {"minecraft:probe": ("Variantenname", "Variant Name")}
    localizations = {
        "probe": ("Basisname", "Base Name"),
        "probe.variant": original["minecraft:probe"],
        "probe.untranslated": ("Andere Variante", ""),
    }
    assert update_db.merge_items(original, {"probe": "Base Name"}, {"probe": "Basisname"}, {}, {}, localizations) == original
