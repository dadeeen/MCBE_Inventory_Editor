"""Reviewed bilingual labels, exact migrations and honest English provenance."""

import json
from pathlib import Path

import pytest

from mcbe_editor.item_data import load_item_database
from mcbe_editor.item_name_policy import (
    DOCUMENTED_ENGLISH_ITEM_IDS,
    EDITORIAL_ITEM_IDS_BY_LOCALE,
    ENGLISH_LABEL_MIGRATIONS,
    REVIEWED_MOJANG_ENGLISH_KEYS,
    SUPERSEDED_ITEM_LABELS,
    reviewed_variant_name_overrides,
)
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON
from mcbe_editor.update_db_report import quality_has_warnings, snapshot_update_quality
from tests.test_update_db import update_db
from tests.test_update_source_quality import _members
from tests.test_update_source_quality import updater as updater

REFERENCE = json.loads((Path(__file__).parent / "fixtures/reviewed_english_item_names.json").read_text(encoding="utf-8"))
NAMES = REFERENCE["labels"]


@pytest.mark.parametrize("entry", NAMES, ids=lambda entry: entry["id"])
def test_reviewed_english_labels_keep_german_and_classify_evidence(entry):
    bundled = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
    identifier = entry["id"]
    assert bundled["items"][identifier] == entry["after"]
    assert entry["after"][0] == entry["before"][0]
    assert entry["after"][1] != entry["before"][1]
    assert ENGLISH_LABEL_MIGRATIONS[identifier] == tuple(entry["before"])
    assert (identifier in EDITORIAL_ITEM_IDS_BY_LOCALE["en"]) == (entry["origin"] == "editorial_name")
    assert (identifier in DOCUMENTED_ENGLISH_ITEM_IDS) == (entry["origin"] == "documented_mojang_name")
    if entry["origin"] == "official_source_label":
        assert REVIEWED_MOJANG_ENGLISH_KEYS[identifier] == entry["source_key"]


@pytest.mark.parametrize("custom", [None, "de", "en", "both"])
@pytest.mark.parametrize("catalog", ["shipped", "reviewed_german"])
def test_english_migrations_agree_in_runtime_and_updater_and_protect_custom_pairs(tmp_path, custom, catalog):
    old = {entry["id"]: tuple(entry["before"]) if catalog == "reviewed_german" else SUPERSEDED_ITEM_LABELS[entry["id"]] for entry in NAMES}
    if custom:
        old = {
            identifier: ("Mein Name/A_B" if custom in {"de", "both"} else pair[0], "My Name/A_B" if custom in {"en", "both"} else pair[1])
            for identifier, pair in old.items()
        }
    expected = old if custom else {entry["id"]: tuple(entry["after"]) for entry in NAMES}
    file = tmp_path / "item_db.json"
    file.write_text(json.dumps({"schema_version": 3, "items": old}), encoding="utf-8")
    previous = file.read_bytes()
    runtime = load_item_database(file)["ITEMS"]
    assert {identifier: runtime[identifier] for identifier in old} == expected
    assert file.read_bytes() == previous
    merged = update_db.merge_items(old, {}, {}, registry_ids=list(old))
    assert merged == expected
    assert update_db.merge_items(merged, {}, {}, registry_ids=list(old)) == expected


@pytest.mark.parametrize("entry", NAMES, ids=lambda entry: entry["id"])
def test_english_provenance_describes_actual_names_and_not_only_available_sources(entry):
    identifier = entry["id"]
    current = {identifier: tuple(entry["after"])}
    # Documentation is evidence for a reviewed name, not language-file coverage.
    quality = update_db.item_label_quality([identifier], current, current, {}, {}, {}, {})
    fallback = quality["en"]["fallbacks"]
    reason = {"editorial_name": {"reason": "editorial"}, "documented_mojang_name": {"reason": "documented"}}.get(entry["origin"], {})
    assert quality["en"]["official"] == 0
    assert fallback == [{"id": identifier, "source": "curated", **reason}]
    source = {identifier.removeprefix("minecraft:"): {"official": {"en": entry["after"][1]}}}
    available = update_db.item_label_quality([identifier], current, current, {}, {}, {}, {}, source_labels=source)
    assert available["en"] == {"total": 1, "official": 1, "fallbacks": []}
    custom = {identifier: (entry["after"][0], "My custom name")}
    preserved = update_db.item_label_quality([identifier], custom, custom, {}, {}, {}, {}, source_labels=source)
    assert preserved["en"] == {"total": 1, "official": 1, "fallbacks": [], "retained": [{"id": identifier, "source": "existing"}]}
    report = {"schema": 1, "sections": {"items": {"status": "checked", "release": "test", "attempted_release": "test", "locales": quality}}}
    assert snapshot_update_quality(report) == report
    assert not quality_has_warnings(report)


@pytest.mark.parametrize(
    "official", [{"en": "Official Heat Block"}, {"de": "Offizieller Hitzeblock"}, {"de": "Offizieller Hitzeblock", "en": "Official Heat Block"}]
)
@pytest.mark.parametrize("custom", [None, "de", "en", "both"])
def test_later_official_locales_can_replace_documented_fallbacks_without_touching_custom_names(official, custom):
    identifier = "minecraft:chemical_heat"
    before = ["Hitzeblock", "Heat Block"]
    if custom in {"de", "both"}:
        before[0] = "Meine Wärmequelle"
    if custom in {"en", "both"}:
        before[1] = "My heat source"
    current = {identifier: tuple(before)}
    source = {"chemical_heat": {"official": official}}
    merged = update_db.merge_items(current, {}, {}, registry_ids=[identifier], source_labels=source)
    expected = tuple(before[i] if custom in {locale, "both"} else official.get(locale, before[i]) for i, locale in enumerate(("de", "en")))
    assert merged == {identifier: expected}
    assert update_db.merge_items(merged, {}, {}, registry_ids=[identifier], source_labels=source) == merged


@pytest.mark.parametrize(
    "identifier, generic",
    [
        ("underwater_tnt", ("TNT", "TNT")),
        ("colored_torch_bp", ("Gefärbte Fackel", "Colored Torch")),
        ("colored_torch_rg", ("Gefärbte Fackel", "Colored Torch")),
        ("stone_block_slab2", ("Steinstufe", "Stone Slab")),
        ("brick_double_slab", ("Ziegelstufe", "Brick Slab")),
        ("petrified_oak_double_slab", ("Holzstufe", "Wooden Slab")),
    ],
)
@pytest.mark.parametrize("locales", [("de",), ("en",), ("de", "en")])
@pytest.mark.parametrize("catalog_entry", ["reviewed", "missing", "custom_de", "custom_en"])
def test_specific_variant_names_survive_generic_source_labels(identifier, generic, locales, catalog_entry):
    full_id = "minecraft:" + identifier
    pair = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))["items"][full_id]
    if catalog_entry == "custom_de":
        pair[0] = "Meine Variante"
    if catalog_entry == "custom_en":
        pair[1] = "My variant"
    current = {} if catalog_entry == "missing" else {full_id: tuple(pair)}
    source = {identifier: {"official": {locale: generic[i] for i, locale in enumerate(("de", "en")) if locale in locales}}}
    merged = update_db.merge_items(current, {}, {}, registry_ids=[full_id], source_labels=source)
    assert merged == {full_id: tuple(pair)}
    assert update_db.merge_items(merged, {}, {}, registry_ids=[full_id], source_labels=source) == merged
    quality = update_db.item_label_quality([full_id], merged, current, {}, {}, {}, {}, source_labels=source)
    for locale in locales:
        assert quality[locale]["official"] == 1
        assert quality[locale]["retained"][0]["source"] == ("existing" if catalog_entry == "custom_" + locale else "curated")


@pytest.mark.parametrize("scope", [[], ["--only", "items"]])
@pytest.mark.parametrize("partial", ["current_en", "legacy_en", "legacy_de"])
def test_technical_placeholders_and_recognizable_translations_reconcile_in_one_apply(updater, scope, partial):
    members = _members()
    entries = {
        "chemical_heat": (["Heat Block", "minecraft:chemical_heat"], ["Hitzeblock", "Heat Block"]),
        "axolotl_bucket": (["Bucket of Axolotl", "minecraft:axolotl_bucket"], ["Axolotleimer", "Bucket of Axolotl"]),
        "stone": (["minecraft:stone", "My stone"], ["Stein", "My stone"]),
        "colored_torch_rg": (["Meine Fackel", "minecraft:colored_torch_rg"], ["Meine Fackel", "Colored Torch (Red/Green)"]),
    }
    if partial != "current_en":
        for item, legacy in (("chemical_heat", "Chemical Heat"), ("axolotl_bucket", "Axolotl Bucket")):
            placeholder = "minecraft:" + item
            entries[item] = ([placeholder, legacy] if partial == "legacy_en" else [legacy, placeholder], entries[item][1])
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": item} for item in entries]})
    members["resource_pack/texts/de_DE.lang"] += "item.bucketAxolotl.name=Axolotleimer\n"
    members["resource_pack/texts/en_US.lang"] += "item.bucketAxolotl.name=Bucket of Axolotl\n"
    updater.write_source(members)
    db = updater.read_db()
    db["items"].update({"minecraft:" + item: old for item, (old, _expected) in entries.items()})
    updater.write_db(db)
    before = updater.snapshot()
    code, preview = updater.run("--dry-run", *scope)
    assert code == 0 and updater.snapshot() == before
    code, applied = updater.run(*scope)
    assert code == 0 and preview["quality"] == applied["quality"]
    runtime = load_item_database(update_db.ITEM_DB_PATH)["ITEMS"]
    persisted = updater.read_db()["items"]
    for item, (_old, expected) in entries.items():
        assert persisted["minecraft:" + item] == expected
        assert runtime["minecraft:" + item] == tuple(expected)
    code, retry = updater.run("--dry-run", *scope)
    assert code == 0 and retry["status"] == "current" and retry["quality"] == applied["quality"]


def test_reviewed_color_families_and_legacy_groups_are_complete():
    names = {entry["id"]: entry["after"][1] for entry in NAMES}
    colors = (
        "White",
        "Orange",
        "Magenta",
        "Light Blue",
        "Yellow",
        "Lime",
        "Pink",
        "Gray",
        "Light Gray",
        "Cyan",
        "Purple",
        "Blue",
        "Brown",
        "Green",
        "Red",
        "Black",
    )
    for color in colors:
        for suffix in ("", "_pane"):
            identifier = "minecraft:hard_" + color.lower().replace(" ", "_") + "_stained_glass" + suffix
            assert names[identifier] == "Hardened " + color + " Stained Glass" + (" Pane" if suffix else "")
    for family, label in (("stone_block_slab", "Stone Slab"), ("double_stone_block_slab", "Stone Double Slab")):
        for n in range(1, 5):
            assert names["minecraft:" + family + (str(n) if n > 1 else "")] == f"{label} (Legacy, Type {n})"


@pytest.mark.parametrize("mode", ["all", "items", "partial"])
@pytest.mark.parametrize("custom", [False, True])
def test_english_labels_preview_apply_repeat_and_partial_sections(updater, mode, custom):
    members = _members()
    entries = [{"name": entry["id"], **({"serialization_id": entry["source_key"]} if "source_key" in entry else {})} for entry in NAMES]
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": entries})
    members["resource_pack/texts/en_US.lang"] += "\n".join(f"{entry['source_key']}={entry['after'][1]}" for entry in NAMES if "source_key" in entry)
    if mode == "partial":
        members["metadata/vanilladata_modules/mojang-effects.json"] = json.dumps({"data_items": "damaged"})
    updater.write_source(members)
    db = updater.read_db()
    for i, entry in enumerate(NAMES):
        pair = list(entry["before"])
        if custom:
            pair[i % 2] = "Mein Name/A_B" if i % 2 == 0 else "My Name/A_B"
        db["items"][entry["id"]] = pair
    updater.write_db(db)
    before = updater.snapshot()
    options = ("--only", "items") if mode == "items" else ()
    code, preview = updater.run("--dry-run", *options)
    assert code == int(mode == "partial")
    assert updater.snapshot() == before
    code, applied = updater.run(*options)
    assert code == int(mode == "partial") and applied["applied"]
    assert applied["quality"] == preview["quality"]
    after = updater.read_db()
    for entry in NAMES:
        assert after["items"][entry["id"]] == (db["items"][entry["id"]] if custom else entry["after"])
    if mode in {"items", "partial"}:
        assert after["effects"] == db["effects"]
    assert updater.read_metadata()["update_quality"] == applied["quality"]
    _, retry = updater.run(*options)
    assert updater.read_db() == after
    assert retry["quality"] == applied["quality"]
    assert retry["status"] == ("incomplete" if mode == "partial" else "current")


@pytest.mark.parametrize("locales", [("de",), ("en",), ("de", "en")])
@pytest.mark.parametrize(
    "identifier, generic, expected",
    [
        *[(f"light_block_{level}", ("Hell", "Light"), (f"Lichtblock {level}", f"Light Block {level}")) for level in range(16)],
        ("petrified_oak_slab", ("Holzstufe", "Wooden Slab"), ("Versteinerte Eichenstufe", "Petrified Oak Slab")),
        ("undyed_shulker_box", ("Shulker-Kiste", "Shulker Box"), ("Shulker-Kiste (ungefärbt)", "Undyed Shulker Box")),
        ("underwater_tnt", ("TNT", "TNT"), ("Unterwasser-TNT", "Underwater TNT")),
    ],
)
def test_missing_catalog_entry_keeps_reviewed_variant_in_each_available_source_locale(locales, identifier, generic, expected):
    full_id = "minecraft:" + identifier
    official = {locale: generic[index] for index, locale in enumerate(("de", "en")) if locale in locales}
    source = {identifier: {"official": official}}
    merged = update_db.merge_items({}, {}, {}, registry_ids=[full_id], source_labels=source)
    assert merged == {full_id: expected}
    quality = update_db.item_label_quality([full_id], merged, {}, {}, {}, {}, {}, source_labels=source)
    for locale in locales:
        assert quality[locale]["official"] == 1
        assert quality[locale]["retained"][0]["source"] == "curated"
    assert update_db.merge_items(merged, {}, {}, registry_ids=[full_id], source_labels=source) == merged


def test_variant_name_overrides_require_exact_reviewed_names_and_sources():
    item_id = "minecraft:petrified_oak_slab"
    catalog = {item_id: ("Versteinerte Eichenstufe", "Petrified Oak Slab")}
    assert reviewed_variant_name_overrides(item_id, catalog, {"en": "Changed source"}) == {}
    assert reviewed_variant_name_overrides(item_id, {item_id: ("My slab", "My slab")}, {"en": "Wooden Slab"}) == {}
    assert reviewed_variant_name_overrides("minecraft:other_slab", catalog, {"en": "Wooden Slab"}) == {}


@pytest.mark.parametrize("existing", [False, True])
def test_specific_official_variant_names_replace_reviewed_defaults(existing):
    item_id = "minecraft:colored_torch_rg"
    old = {item_id: ("Gefärbte Fackel (rot/grün)", "Colored Torch (Red/Green)")} if existing else {}
    labels = {"colored_torch_rg": {"official": {"de": "Neue Rot-Grün-Fackel", "en": "New Red/Green Torch"}}}
    assert update_db.merge_items(old, {}, {}, registry_ids=[item_id], source_labels=labels)[item_id] == ("Neue Rot-Grün-Fackel", "New Red/Green Torch")


def test_current_source_can_reuse_a_historic_spelling_in_persistent_and_runtime_catalogs(updater):
    pairs = {
        "chemical_heat": ["Hitzeblock", "Chemical Heat"],
        "oak_chest_boat": ["Eichenholz-Truhenboot", "Oak Chest Boat"],
        "mace": ["Mace", "Mace"],
        "axolotl_bucket": ["Axolotl Bucket", "Axolotl Bucket"],
    }
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": item} for item in pairs]})
    db = updater.read_db()
    for item, (de, en) in pairs.items():
        members["resource_pack/texts/en_US.lang"] += f"item.{item}.name={en}\n"
        if item in {"mace", "axolotl_bucket"}:
            db["items"].pop("minecraft:" + item, None)
            members["resource_pack/texts/de_DE.lang"] += f"item.{item}.name={de}\n"
    updater.write_db(db)
    updater.write_source(members)
    before = updater.snapshot()
    code, preview = updater.run("--dry-run")
    assert code == 0 and before == updater.snapshot()
    code, result = updater.run()
    assert code == 0 and result["quality"] == preview["quality"]
    expected = {"minecraft:" + item: pair for item, pair in pairs.items()}
    db = updater.read_db()
    assert db["confirmed_item_labels"] == expected
    runtime = load_item_database(update_db.ITEM_DB_PATH)["ITEMS"]
    for item, pair in expected.items():
        assert db["items"][item] == pair and runtime[item] == tuple(pair)
    assert updater.run("--dry-run")[1]["status"] == "current"
    assert updater.run("--only", "effects")[0] == 0
    assert updater.read_db()["confirmed_item_labels"] == expected
    registry = "metadata/vanilladata_modules/mojang-items.json"
    updater.write_source({**members, registry: "{}"})
    assert updater.run()[0] == 1 and updater.read_db()["confirmed_item_labels"] == expected
    other_ids = json.dumps({"data_items": [{"name": item} for item in pairs if item != "mace"]})
    language = "resource_pack/texts/de_DE.lang"
    updater.write_source({**members, registry: other_ids, language: members[language].replace("=Mace\n", "=Unrelated label\n")})
    assert updater.run()[0] == 0
    assert updater.read_db()["confirmed_item_labels"] == expected
    assert updater.read_db()["items"]["minecraft:mace"] == expected["minecraft:mace"]
    db = updater.read_db()
    db["items"]["minecraft:chemical_heat"][0] = "Meine Wärmequelle"
    updater.write_db(db)
    members["resource_pack/texts/en_US.lang"] = members["resource_pack/texts/en_US.lang"].replace("=Chemical Heat\n", "=Heat Block\n")
    members["resource_pack/texts/en_US.lang"] = members["resource_pack/texts/en_US.lang"].replace("=Mace\n", "=Battle Mace\n")
    members["resource_pack/texts/de_DE.lang"] = members["resource_pack/texts/de_DE.lang"].replace("=Mace\n", "=Neue Keule\n")
    updater.write_source(members)
    assert updater.run()[0] == 0
    after = updater.read_db()
    assert after["confirmed_item_labels"]["minecraft:chemical_heat"] == ["Hitzeblock", "Heat Block"]
    assert after["items"]["minecraft:chemical_heat"] == ["Meine Wärmequelle", "Heat Block"]
    assert after["confirmed_item_labels"]["minecraft:mace"] == ["Neue Keule", "Battle Mace"]
    assert after["items"]["minecraft:mace"] == ["Neue Keule", "Battle Mace"]
    assert load_item_database(update_db.ITEM_DB_PATH)["ITEMS"]["minecraft:mace"] == ("Neue Keule", "Battle Mace")
    assert updater.run("--dry-run")[1]["status"] == "current"


@pytest.mark.parametrize("custom_locale", [None, 0, 1])
def test_successive_official_names_keep_missing_locales_and_detect_custom_edits(updater, custom_locale):
    ids = ["minecraft:chemical_heat", "minecraft:future_source_item"]
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": key} for key in ids]})

    def source(de, en, *, blocked=False):
        data = dict(members)
        for locale, value in (("de_DE", de), ("en_US", en)):
            if value:
                data[f"resource_pack/texts/{locale}.lang"] += "".join(f"item.{key.removeprefix('minecraft:')}.name={value}\n" for key in ids)
        if blocked:
            data["metadata/vanilladata_modules/mojang-effects.json"] = "{}"
        updater.write_source(data)

    source("Erste Benennung", "First label")
    assert updater.run()[0] == 0
    initial = ["Erste Benennung", "First label"]
    db = updater.read_db()
    assert db["confirmed_item_labels"] == dict.fromkeys(ids, initial)
    if custom_locale is not None:
        initial[custom_locale] = initial[1 - custom_locale]
        for key in ids:
            db["items"][key] = list(initial)
        updater.write_db(db)
        runtime = load_item_database(update_db.ITEM_DB_PATH)["ITEMS"]
        assert all(runtime[key] == tuple(initial) for key in ids)
    source(None, "Second label", blocked=True)
    assert updater.run("--only", "enchants")[0] == 0
    before = updater.snapshot()
    code, preview = updater.run("--dry-run")
    assert code == 1 and updater.snapshot() == before
    code, applied = updater.run()
    assert code == 1 and applied["applied"] and applied["quality"] == preview["quality"]
    expected = list(initial)
    if custom_locale != 1:
        expected[1] = "Second label"
    for key in ids:
        assert updater.read_db()["items"][key] == expected
    source(None, None)
    assert updater.run("--only", "items")[0] == 0
    gap = updater.read_db()
    for key in ids:
        assert gap["items"][key] == expected
        assert gap["confirmed_item_labels"][key] == ["Erste Benennung", "First label" if custom_locale == 1 else "Second label"]
    source("Dritte Benennung", "Third label")
    assert updater.run()[0] == 0
    expected = [initial[i] if custom_locale == i else value for i, value in enumerate(("Dritte Benennung", "Third label"))]
    persisted = updater.read_db()
    runtime = load_item_database(update_db.ITEM_DB_PATH)["ITEMS"]
    for key in ids:
        assert persisted["items"][key] == expected
        assert runtime[key] == tuple(expected)
    assert updater.run("--dry-run")[1]["status"] == "current"


@pytest.mark.parametrize("legacy", [False, True])
def test_official_locales_replace_learn_titles_independently_in_existing_installations(updater, monkeypatch, legacy):
    ids = ["future_probe", "custom_probe", "local_probe", "mangrove_hanging_sign"]
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": key} for key in ids]})
    learn = update_db.parse_microsoft_item_listing(
        "<table><tr><td>future_probe</td><td>42</td></tr><tr><td>custom_probe</td><td>43</td></tr><tr><td>local_probe</td><td>44</td></tr></table>"
    )
    monkeypatch.setattr(update_db, "resolve_microsoft_item_listing_snapshot", lambda **_kwargs: (learn, {}))
    de, en = "resource_pack/texts/de_DE.lang", "resource_pack/texts/en_US.lang"
    members[de] += "item.mangrove_hanging_sign.name=Mangrovenhängeschild\n"
    members[de] += "item.local_probe.name=Erstes Gerät\n"
    members[en] += "item.mangrove_hanging_sign.name=Mangrove Hanging Sign\n"
    sign = "minecraft:mangrove_hanging_sign"
    updater.write_source(members)
    assert updater.run()[0] == 0
    db = updater.read_db()
    assert db["items"]["minecraft:future_probe"] == ["Future Probe", "Future Probe"]
    assert db["items"][sign] == ["Mangrovenhängeschild", "Mangrove Hanging Sign"]
    if legacy:
        db.pop("confirmed_item_labels")
    db["items"]["minecraft:custom_probe"][1] = "my own name"
    db["items"]["minecraft:local_probe"][0] = "Local Probe"
    db["items"][sign][0] = db["items"][sign][1]
    updater.write_db(db)
    assert load_item_database(update_db.ITEM_DB_PATH)["ITEMS"][sign] == ("Mangrove Hanging Sign", "Mangrove Hanging Sign")

    members[de] = members[de].replace("item.local_probe.name=Erstes Gerät\n", "")
    for key in learn:
        members[de] += f"item.{key}.name=Vermesser\n"
        members[en] += f"item.{key}.name=Surveyor\n"
    updater.write_source(members)
    before = updater.snapshot()
    code, preview = updater.run("--dry-run")
    assert code == 0 and updater.snapshot() == before
    code, apply = updater.run()
    assert code == 0 and preview["quality"] == apply["quality"]
    expected = {
        sign: ["Mangrove Hanging Sign", "Mangrove Hanging Sign"],
        "minecraft:future_probe": ["Vermesser", "Surveyor"],
        "minecraft:custom_probe": ["Vermesser", "my own name"],
        "minecraft:local_probe": ["Local Probe", "Surveyor"],
    }
    saved = updater.read_db()["items"]
    runtime = load_item_database(update_db.ITEM_DB_PATH)["ITEMS"]
    for key, pair in expected.items():
        assert saved[key] == pair and runtime[key] == tuple(pair)
    locales = apply["quality"]["sections"]["items"]["locales"]
    assert locales["de"]["retained"] == [{"id": "minecraft:local_probe", "source": "existing"}, {"id": sign, "source": "existing"}]
    assert locales["en"]["retained"] == [{"id": "minecraft:custom_probe", "source": "existing"}]
    assert updater.run("--dry-run")[1]["status"] == "current"


def test_generated_learn_titles_follow_direct_and_composed_sources_without_granting_addability(updater, monkeypatch):
    learn = {"learn_only": "Learn Only", "music_disc_probe": "Music Disc Probe"}
    monkeypatch.setattr(update_db, "resolve_microsoft_item_listing_snapshot", lambda **_kwargs: (learn, {}))
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps(
        {"data_items": [{"name": "music_disc_probe", "serialization_id": "item.record_probe"}]}
    )
    updater.write_source(members)
    assert updater.run()[0] == 0
    for filename, name, base in (("de_DE", "Vermesser", "Schallplatte"), ("en_US", "Surveyor", "Music Disc")):
        members[f"resource_pack/texts/{filename}.lang"] += (
            f"tile.learn_only.name=Block\nitem.learn_only.name={name}\nitem.record.name={base}\nitem.record_probe.desc=Song A\n"
        )
    updater.write_source(members)
    code, report = updater.run()
    assert code == 0
    db = updater.read_db()
    assert db["items"]["minecraft:learn_only"] == ["Vermesser", "Surveyor"] and "minecraft:learn_only" not in db["addable_items"]
    assert db["items"]["minecraft:music_disc_probe"] == ["Schallplatte – Song A", "Music Disc – Song A"]
    for coverage in report["quality"]["sections"]["items"]["locales"].values():
        assert {"id": "minecraft:music_disc_probe", "source": "composed", "reason": "composed"} in coverage["fallbacks"]
    assert updater.run("--dry-run")[1]["status"] == "current"


@pytest.mark.parametrize("edited", [False, True])
def test_legacy_copied_translation_requires_its_unchanged_catalog_and_report(updater, edited):
    from mcbe_editor import item_db_verification as verification

    key = "minecraft:future_probe"
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": key}]})
    members["resource_pack/texts/en_US.lang"] += "item.future_probe.name=First\n"
    updater.write_source(members)
    assert updater.run()[0] == 0
    db = updater.read_db()
    db.pop("confirmed_item_labels")
    updater.write_db(db)
    metadata = verification.attach_item_db_verification(updater.read_metadata(), update_db.ITEM_DB_PATH, verified_at="previous")
    metadata[verification.VERIFICATION_FIELD]["updater_contract_version"] = 5
    update_db.SOURCE_VERSION_JSON.write_text(json.dumps(metadata), encoding="utf-8")
    assert not verification.item_db_verification_snapshot(metadata, update_db.ITEM_DB_PATH)["verified"]
    if edited:
        db["items"][key] = ["Own", "Own"]
        updater.write_db(db)
    members["resource_pack/texts/en_US.lang"] = members["resource_pack/texts/en_US.lang"].replace("=First\n", "=Second\n")
    members["resource_pack/texts/de_DE.lang"] += "item.future_probe.name=Zweite Benennung\n"
    updater.write_source(members)
    assert updater.run()[0] == 0
    assert updater.read_db()["items"][key] == (["Own", "Own"] if edited else ["Zweite Benennung", "Second"])
    assert updater.run("--dry-run")[1]["status"] == "current"


def test_existing_equal_name_does_not_become_an_automatic_fallback_during_a_source_gap(updater):
    key = "minecraft:future_probe"
    members = _members()
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": key}]})
    members["resource_pack/texts/en_US.lang"] += "item.future_probe.name=First English\n"
    de = members["resource_pack/texts/de_DE.lang"]
    members["resource_pack/texts/de_DE.lang"] = de + "item.future_probe.name=Alter deutscher Name\n"
    updater.write_source(members)
    assert updater.run()[0] == 0
    db = updater.read_db()
    db.pop("confirmed_item_labels")
    db["items"][key][0] = "First English"
    updater.write_db(db)
    members["resource_pack/texts/de_DE.lang"] = de
    updater.write_source(members)
    assert updater.run()[0] == 0
    assert updater.run("--dry-run")[1]["status"] == "current"
    members["resource_pack/texts/de_DE.lang"] += "item.future_probe.name=Neuer deutscher Name\n"
    members["resource_pack/texts/en_US.lang"] = members["resource_pack/texts/en_US.lang"].replace("=First English", "=New English")
    updater.write_source(members)
    assert updater.run()[0] == 0
    assert updater.read_db()["items"][key] == ["First English", "New English"]
    assert updater.run("--dry-run")[1]["status"] == "current"


@pytest.mark.parametrize("source_locale", ["de", "en"])
def test_source_rename_distinguishes_an_actual_same_language_name_from_a_copied_fallback(updater, source_locale):
    other = "en" if source_locale == "de" else "de"
    locales = {"de": "de_DE", "en": "en_US"}
    ids = ["minecraft:proper_probe", "minecraft:copied_probe"]
    for step, title in enumerate(("First", "Second", None, "Third")):
        if step == 1:
            updater.write_source(_members())  # The next release omits both registry identities.
            assert updater.run()[0] == 0
            stored = updater.read_db()["confirmed_item_labels"]
            assert stored[ids[0]] == ["First", "First"]
            assert stored[ids[1]] == {"names": ["First", "First"], "borrowed": other}
            assert all(
                row["id"] not in ids
                for coverage in updater.read_metadata()["update_quality"]["sections"]["items"]["locales"].values()
                for row in coverage["fallbacks"]
            )
        members = _members()
        members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps({"data_items": [{"name": key} for key in ids]})
        if title:
            members[f"resource_pack/texts/{locales[source_locale]}.lang"] += "".join(f"item.{key.removeprefix('minecraft:')}.name={title}\n" for key in ids)
        if not step:
            members[f"resource_pack/texts/{locales[other]}.lang"] += "item.proper_probe.name=First\n"
        updater.write_source(members)
        code, report = updater.run()
        assert code == 0 and report["quality"] == updater.run("--dry-run")[1]["quality"]
        names = updater.read_db()["items"]
        current = title or "Second"
        assert names[ids[0]] == ([current, "First"] if source_locale == "de" else ["First", current])
        assert names[ids[1]] == [current, current]
        quality = report["quality"]["sections"]["items"]["locales"]
        origins = {entry["id"]: entry["source"] for entry in quality[other]["fallbacks"]}
        assert origins.get(ids[0]) == ("existing" if step else None)
        assert origins[ids[1]] == "other_language"
        if not title:
            assert quality[source_locale]["fallbacks"] == [{"id": key, "source": "existing"} for key in sorted(ids)]


@pytest.mark.parametrize("locales", [("de",), ("en",), ("de", "en")])
def test_existing_installation_repairs_missing_variant_entries_through_preview_apply_and_runtime(updater, locales):
    reference = json.loads((Path(__file__).parent / "fixtures/item_localization_reference.json").read_text(encoding="utf-8"))
    expected = {
        "minecraft:light_block_7": ["Lichtblock 7", "Light Block 7"],
        "minecraft:petrified_oak_slab": ["Versteinerte Eichenstufe", "Petrified Oak Slab"],
        "minecraft:undyed_shulker_box": ["Shulker-Kiste (ungefärbt)", "Undyed Shulker Box"],
    }
    cases = [row for row in reference["cases"] if row["id"] in expected]
    members = _members()
    for kind, field in (("items", "item_ref"), ("blocks", "block_ref")):
        members[f"metadata/vanilladata_modules/mojang-{kind}.json"] = json.dumps(
            {"data_items": [{"name": row["id"], "serialization_id": row[field]} for row in cases]}
        )
    for locale, filename in (("de", "de_DE"), ("en", "en_US")):
        if locale in locales:
            members[f"resource_pack/texts/{filename}.lang"] += "\n".join(f"{key}={value}" for key, value in reference["languages"][locale].items())
    updater.write_source(members)
    db = updater.read_db()
    for identifier in expected:
        db["items"].pop(identifier, None)
    updater.write_db(db)
    before = updater.snapshot()
    code, preview = updater.run("--only", "items", "--dry-run")
    assert code == 0 and updater.snapshot() == before
    code, applied = updater.run("--only", "items")
    assert code == 0 and applied["quality"] == preview["quality"]
    after = updater.read_db()
    runtime = load_item_database(update_db.ITEM_DB_PATH)["ITEMS"]
    for identifier, pair in expected.items():
        assert after["items"][identifier] == pair
        assert runtime[identifier] == tuple(pair)
    for locale in locales:
        quality = applied["quality"]["sections"]["items"]["locales"][locale]
        assert quality["official"] == 3
        assert {row["id"] for row in quality["retained"]} == set(expected)
    assert updater.run("--only", "items")[1]["status"] == "current"
