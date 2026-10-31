"""Source damage, optional display labels, and atomic partial updater outcomes."""

from __future__ import annotations

import copy
import io
import json
import sys
import zipfile

import pytest

from mcbe_editor import update_source_quality
from mcbe_editor.update_db_report import extract_report, snapshot_update_quality
from tests.test_update_db import update_db


def _members(*, labels=True):
    members = {
        f"metadata/vanilladata_modules/mojang-{module}.json": json.dumps({"data_items": [{"name": name} for name in names]})
        for module, names in (
            ("items", ["minecraft:stone"]),
            ("blocks", ["minecraft:stone"]),
            ("effects", ["minecraft:speed", "minecraft:freezing"]),
            ("enchantments", ["minecraft:unbreaking"]),
        )
    }
    members["resource_pack/texts/en_US.lang"] = "menu.play=Play\n" + (
        "item.stone.name=Stone\npotion.moveSpeed=Speed\nenchantment.durability=Unbreaking\n" if labels else ""
    )
    members["resource_pack/texts/de_DE.lang"] = "menu.play=Spielen\n" + (
        "item.stone.name=Stein\npotion.moveSpeed=Geschwindigkeit\nenchantment.durability=Haltbarkeit\n" if labels else ""
    )
    return members


def _write_zip(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


@pytest.fixture
def updater(monkeypatch, tmp_path, capsys):
    for name, filename in (
        ("ITEM_DB_PATH", "item_db.json"),
        ("SOURCE_VERSION_JSON", "source_version.json"),
        ("SOURCE_VERSION_HISTORY", "source_version_history.json"),
    ):
        monkeypatch.setattr(update_db, name, tmp_path / filename)
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(update_db, "CACHE_DIR", cache)
    monkeypatch.setattr(update_db, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update_db, "step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update_db, "resolve_microsoft_item_listing_snapshot", lambda **_kwargs: ({}, {}))
    release = {
        "resource_pack_release": "v999.0.0",
        "resource_pack_asset": "source.zip",
        "resource_pack_asset_size": 1,
        "resource_pack_url": "https://github.com/Mojang/bedrock-samples/releases/download/v999.0.0/source.zip",
    }
    monkeypatch.setattr(update_db, "read_release_metadata", lambda: release)
    update_db.ensure_data_paths()
    archive = cache / "bedrock_resource_pack.zip"

    class Updater:
        def write_source(self, members=None):
            _write_zip(archive, _members() if members is None else members)
            self.refresh_source_metadata()

        def refresh_source_metadata(self):
            release["resource_pack_asset_size"] = archive.stat().st_size
            (cache / "release_metadata.json").write_text(json.dumps(release), encoding="utf-8")

        def read_db(self):
            return json.loads(update_db.ITEM_DB_PATH.read_text(encoding="utf-8"))

        def write_db(self, db):
            update_db.ITEM_DB_PATH.write_text(json.dumps(db), encoding="utf-8")

        def read_metadata(self):
            return json.loads(update_db.SOURCE_VERSION_JSON.read_text(encoding="utf-8"))

        def snapshot(self):
            return {
                path.name: path.read_bytes() if path.exists() else None
                for path in (update_db.ITEM_DB_PATH, update_db.SOURCE_VERSION_JSON, update_db.SOURCE_VERSION_HISTORY)
            }

        def run(self, *options):
            monkeypatch.setattr(sys, "argv", ["update_db.py", "--cache", "--force", "--json-summary", *options])
            code = update_db.main()
            # The API parent acknowledges the committed generation after the
            # worker exits. This in-process CLI harness must do the same before
            # simulating a later edit to an existing installation.
            update_db.item_db_transaction.recover_item_db(
                update_db.item_db_transaction.configured_targets(update_db.ITEM_DB_PATH, update_db.SOURCE_VERSION_JSON, update_db.SOURCE_VERSION_HISTORY)
            )
            _, report = extract_report(capsys.readouterr().out)
            assert report is not None
            assert snapshot_update_quality(report["quality"]) == report["quality"]
            return code, report

    instance = Updater()
    instance.write_source()
    return instance


@pytest.mark.parametrize(
    ("official", "curated", "existing", "names", "sources"),
    [
        ({"de": "Quelle", "en": "Official"}, ("Kuratierter Name", "Curated"), ("Vorhanden", "Existing"), ("Quelle", "Official"), ("official", "official")),
        ({}, ("Gefrieren", "Freezing"), ("Alter Name", "Old name"), ("Gefrieren", "Freezing"), ("curated", "curated")),
        ({}, (), ("Vorhanden", "Existing"), ("Vorhanden", "Existing"), ("existing", "existing")),
        ({"en": "Official"}, (), (), ("Official", "Official"), ("other_language", "official")),
        ({"de": "Quelle"}, (), (), ("Quelle", "Quelle"), ("official", "other_language")),
        ({}, (), (), ("minecraft:future", "minecraft:future"), ("identifier", "identifier")),
    ],
)
def test_name_fallback_order_is_locale_specific(official, curated, existing, names, sources):
    assert update_source_quality.resolve_names("minecraft:future", official, curated, existing) == (names, sources)


@pytest.mark.parametrize("labels", [False, True])
@pytest.mark.parametrize("existing_custom", [False, True])
def test_missing_labels_apply_preview_and_persist_quality(updater, labels, existing_custom):
    db = updater.read_db()
    db["effects"] = {"38": ["Eigener Frost", "My frost", "", ""]} if existing_custom else {}
    db["enchantments"] = {"17": ["Eigene Haltbarkeit", "My durability", 3, "Custom details"]} if existing_custom else {}
    db["items"] = {"minecraft:stone": ["Mein Stein", "My stone"]} if existing_custom else {}
    updater.write_db(db)
    updater.write_source(_members(labels=labels))
    before = updater.snapshot()
    code, preview = updater.run("--dry-run")
    assert code == 0
    assert preview["applied"] is False
    assert updater.snapshot() == before
    effect_coverage = preview["quality"]["sections"]["effects"]["locales"]
    for locale in ("de", "en"):
        assert effect_coverage[locale]["total"] == 2
        assert effect_coverage[locale]["official"] == int(labels)
        assert {"id": "minecraft:freezing", "source": "existing" if existing_custom else "curated"} in effect_coverage[locale]["fallbacks"]
    code, report = updater.run()
    assert code == 0 and report["applied"] is True
    result = updater.read_db()
    assert result["effects"]["38"][:2] == (["Eigener Frost", "My frost"] if existing_custom else ["Gefrieren", "Freezing"])
    assert result["items"]["minecraft:stone"] == (["Mein Stein", "My stone"] if existing_custom else ["Stein", "Stone"])
    if existing_custom:
        assert result["enchantments"]["17"] == ["Eigene Haltbarkeit", "My durability", 3, "Custom details"]
    metadata = updater.read_metadata()
    assert metadata["update_quality"] == report["quality"] == preview["quality"]
    assert update_db.item_db_verification.item_db_verification_snapshot(metadata, update_db.ITEM_DB_PATH)["verified"] is True
    code, retry = updater.run()
    assert code == 0 and retry["status"] == "current", json.dumps(retry["sections"])
    assert retry["quality"] == report["quality"]


@pytest.mark.parametrize(
    "damage",
    [None, b"\xff", "", "# only comments\n", "menu.play=\n", "not a language file", "menu.play=Play\nmalformed", "menu.play=Play\0"],
)
@pytest.mark.parametrize("locale", ["de_DE", "en_US"])
def test_invalid_shared_locale_is_a_structured_failure_without_publication(updater, damage, locale):
    assert updater.run()[0] == 0
    before = updater.snapshot()
    members = _members()
    member = f"resource_pack/texts/{locale}.lang"
    if damage is None:
        members.pop(member)
    else:
        members[member] = damage
    updater.write_source(members)
    code, report = updater.run()
    assert code == 1 and report["applied"] is False
    assert report["status"] == "incomplete"
    assert len(report["blocked"]) == 3
    assert all(member in entry["reason"] for entry in report["blocked"])
    assert updater.snapshot() == before


def test_duplicate_language_member_and_invalid_archive_are_rejected(updater):
    assert updater.run()[0] == 0
    before = updater.snapshot()
    archive = update_db.CACHE_DIR / "bedrock_resource_pack.zip"
    with pytest.warns(UserWarning, match="Duplicate name"), zipfile.ZipFile(archive, "a") as source:
        source.writestr("resource_pack/texts/de_DE.lang", "menu.play=Spielen\n")
    updater.refresh_source_metadata()
    code, report = updater.run()
    assert code == 1 and "de_DE.lang" in report["blocked"][0]["reason"]
    assert updater.snapshot() == before
    archive.write_bytes(b"broken archive")
    updater.refresh_source_metadata()
    code, report = updater.run()
    assert code == 1 and "ZIP" in report["blocked"][0]["reason"]
    assert updater.snapshot() == before


@pytest.mark.parametrize(
    ("module", "section", "database_key"),
    [("items", "items", "items"), ("blocks", "items", "items"), ("effects", "effects", "effects"), ("enchantments", "enchants", "enchantments")],
)
@pytest.mark.parametrize(
    "damage", [None, b"\xff", "not JSON", "[]", '{"data_items": []}', '{"data_items": [{}]}', '{"data_items": [{"name": "../bad identifier"}]}']
)
def test_invalid_registry_preserves_its_section_and_updates_independent_sections(updater, module, section, database_key, damage):
    assert updater.run()[0] == 0
    before_db = updater.read_db()
    before_quality = updater.read_metadata()["update_quality"]
    members = _members()
    member = f"metadata/vanilladata_modules/mojang-{module}.json"
    if damage is None:
        members.pop(member)
    else:
        members[member] = damage
    updater.write_source(members)
    code, report = updater.run()
    assert code == 1 and report["applied"] is True
    assert len(report["blocked"]) == 1 and member in report["blocked"][0]["reason"]
    assert updater.read_db()[database_key] == before_db[database_key]
    metadata = updater.read_metadata()
    assert update_db.item_db_verification.VERIFICATION_FIELD not in metadata
    quality = metadata["update_quality"]["sections"]
    assert quality[section]["status"] == "blocked"
    assert quality[section]["release"] == before_quality["sections"][section]["release"]
    assert quality[section]["locales"] == before_quality["sections"][section]["locales"]
    assert all(value["status"] == "checked" for key, value in quality.items() if key != section)
    # Replaying the same blocked generation must preserve the receipt removal.
    assert updater.run()[0] == 1
    assert update_db.item_db_verification.VERIFICATION_FIELD not in updater.read_metadata()
    updater.write_source()
    code, repaired = updater.run()
    assert code == 0 and not repaired["blocked"]
    assert all(value["status"] == "checked" for value in updater.read_metadata()["update_quality"]["sections"].values())
    assert update_db.item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]


@pytest.mark.parametrize("section", ["effects", "enchants"])
def test_numeric_unknown_id_blocks_whole_section_even_with_known_fallback_names(updater, section):
    assert updater.run()[0] == 0
    previous = updater.read_db()
    members = _members()
    module = "effects" if section == "effects" else "enchantments"
    member = f"metadata/vanilladata_modules/mojang-{module}.json"
    registry = json.loads(members[member])
    registry["data_items"].append({"name": "minecraft:future_fact"})
    members[member] = json.dumps(registry)
    for locale in ("de_DE", "en_US"):
        prefix = "effect" if section == "effects" else "enchant"
        members[f"resource_pack/texts/{locale}.lang"] += f"{prefix}.future_fact=Speed\n"
    updater.write_source(members)
    code, report = updater.run()
    assert code == 1 and report["applied"] is True
    assert len(report["blocked"]) == 1 and "future_fact" in report["blocked"][0]["reason"]
    assert updater.read_db()[module] == previous[module]
    assert updater.read_metadata()["update_quality"]["sections"][section]["status"] == "blocked"


@pytest.mark.parametrize("section", ["effects", "enchants"])
def test_numeric_catalog_collision_preserves_old_section(updater, section):
    assert updater.run()[0] == 0
    before = updater.read_db()
    key, numeric_id = ("effects", "1") if section == "effects" else ("enchantments", "17")
    before[key]["999"] = before[key][numeric_id][:]
    updater.write_db(before)
    code, report = updater.run()
    assert code == 1 and report["applied"] is True
    assert len(report["blocked"]) == 1
    assert updater.read_db()[key] == before[key]


def test_partial_scope_retains_other_sections_quality(updater):
    assert updater.run()[0] == 0
    old = copy.deepcopy(updater.read_metadata()["update_quality"])
    updater.write_source(_members(labels=False))
    code, report = updater.run("--only", "effects")
    assert code == 0
    quality = updater.read_metadata()["update_quality"]
    assert quality == report["quality"]
    assert quality["sections"]["items"] == old["sections"]["items"]
    assert quality["sections"]["enchants"] == old["sections"]["enchants"]
    assert quality["sections"]["effects"]["locales"]["en"]["official"] == 0


@pytest.mark.parametrize("section", ["items", "effects", "enchants"])
def test_unchanged_selected_scope_preserves_complete_verification(updater, section):
    assert updater.run()[0] == 0
    before = updater.snapshot()
    code, report = updater.run("--only", section)
    assert code == 0 and report["status"] == "current"
    assert updater.snapshot() == before
    assert update_db.item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]


def test_partial_update_failure_rolls_back_names_quality_and_receipt_together(updater, monkeypatch):
    assert updater.run()[0] == 0
    before = updater.snapshot()
    members = _members(labels=False)
    members["metadata/vanilladata_modules/mojang-effects.json"] = "{}"
    updater.write_source(members)

    def fail_metadata(_metadata):
        raise OSError("metadata publication failed")

    with monkeypatch.context() as patch:
        patch.setattr(update_db, "write_source_version", fail_metadata)
        with pytest.raises(OSError, match="publication failed"):
            updater.run()
    assert updater.snapshot() == before
    code, report = updater.run()
    assert code == 1 and report["applied"] is True
    assert updater.read_metadata()["update_quality"]["sections"]["effects"]["status"] == "blocked"


def test_item_quality_uses_the_same_microsoft_name_resolution_as_the_catalog():
    full_id = "minecraft:future_probe"
    listing = {"future_probe": "Future Probe"}
    merged = update_db.merge_items({}, {}, {}, listing)
    assert merged[full_id] == ("Future Probe", "Future Probe")
    quality = update_db.item_label_quality([full_id], merged, {}, {}, {}, {}, {}, listing)
    assert quality["de"] == {"total": 1, "official": 0, "fallbacks": [{"id": full_id, "source": "other_language"}]}
    assert quality["en"] == {"total": 1, "official": 0, "fallbacks": [{"id": full_id, "source": "microsoft"}]}
    repeated = update_db.merge_items(merged, {}, {}, listing)
    assert update_db.item_label_quality([full_id], repeated, merged, {}, {}, {}, {}, listing) == quality


@pytest.mark.parametrize("custom", [None, "de", "en"])
def test_existing_technical_item_names_receive_later_official_labels_without_changing_custom_names(custom):
    full_id = "minecraft:future_probe"
    # Earlier catalogs can contain generated ID placeholders even though new
    # nameless identities only receive a runtime fallback.
    initial = {full_id: (full_id, full_id)}
    if custom:
        names = list(initial[full_id])
        names[0 if custom == "de" else 1] = "My custom label"
        initial[full_id] = tuple(names)
    resolved = update_db.merge_items(initial, {"future_probe": "Future Probe"}, {"future_probe": "Zukunft"})
    assert resolved[full_id] == ("My custom label" if custom == "de" else "Zukunft", "My custom label" if custom == "en" else "Future Probe")


@pytest.mark.parametrize("initial_locale", ["de", "en"])
def test_other_language_item_fallback_receives_later_translation(initial_locale):
    full_id = "minecraft:future_probe"
    en = {"future_probe": "Future Probe"} if initial_locale == "en" else {}
    de = {"future_probe": "Zukunft"} if initial_locale == "de" else {}
    initial = update_db.merge_items({}, en, de)
    initial_quality = update_db.item_label_quality([full_id], initial, {}, en, de, {}, {})
    assert update_db.item_label_quality([full_id], initial, initial, en, de, {}, {}) == initial_quality
    result = update_db.merge_items(initial, {"future_probe": "Future Probe"}, {"future_probe": "Zukunft"})
    assert result[full_id] == ("Zukunft", "Future Probe")


def test_blocked_section_without_previous_quality_has_no_claimed_release(updater):
    members = _members()
    members["metadata/vanilladata_modules/mojang-effects.json"] = "{}"
    updater.write_source(members)
    code, report = updater.run()
    assert code == 1
    blocked = report["quality"]["sections"]["effects"]
    assert blocked["release"] is None
    assert blocked["attempted_release"] == "v999.0.0"
    assert blocked["locales"] == {}


def test_duplicate_registry_member_blocks_only_its_section():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in _members().items():
            archive.writestr(name, content)
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("metadata/vanilladata_modules/mojang-effects.json", '{"data_items": [{"name": "speed"}]}')
    with zipfile.ZipFile(stream) as archive:
        assert set(update_db.validate_update_sources(archive, None, allow_partial=True)) == {"effects"}
