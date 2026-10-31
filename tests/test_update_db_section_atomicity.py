"""Section planning uses recovered inputs and publishes only complete candidates."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from unittest.mock import Mock

import pytest

from tests.test_update_db import update_db
from tests.test_update_source_quality import _members
from tests.test_update_source_quality import updater as updater


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("intermediate_metadata", ["wrong-generation", "invalid-json"])
def test_cli_recovers_before_reading_any_base_metadata(updater, dry_run, intermediate_metadata):
    assert updater.run()[0] == 0
    before = updater.snapshot()
    previous = updater.read_metadata()
    targets = update_db.item_db_transaction.configured_targets(update_db.ITEM_DB_PATH, update_db.SOURCE_VERSION_JSON, update_db.SOURCE_VERSION_HISTORY)
    entries = []
    for target in targets:
        content = target.read_bytes() if target.exists() else None
        entries.append(
            {
                "path": str(target),
                "old": base64.b64encode(content).decode("ascii") if content is not None else None,
                "old_sha256": hashlib.sha256(content).hexdigest() if content is not None else None,
            }
        )
    update_db.item_db_transaction._save_journal(update_db.item_db_transaction.journal_path(targets), {"version": 1, "phase": "prepared", "entries": entries})
    interrupted = copy.deepcopy(previous)
    interrupted["resource_pack_release"] = "v-uncommitted"
    interrupted["update_quality"]["sections"]["items"]["release"] = "v-uncommitted"
    update_db.SOURCE_VERSION_JSON.write_text(json.dumps(interrupted) if intermediate_metadata == "wrong-generation" else "{interrupted", encoding="utf-8")
    options = ("--only", "effects", "--dry-run") if dry_run else ("--only", "effects")
    code, report = updater.run(*options)
    assert code == 0
    assert report["previous_release"] == previous["resource_pack_release"]
    assert report["quality"]["sections"]["items"] == previous["update_quality"]["sections"]["items"]
    assert updater.snapshot() == before
    assert not update_db.item_db_transaction.journal_path(targets).exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_damaged_item_components_preserve_all_item_fields_and_skip_unused_listing(updater, monkeypatch, dry_run):
    original = updater.read_db()
    original["effects"] = {}
    updater.write_db(original)
    members = _members()
    members["behavior_pack/items/probe.json"] = "{broken JSON"
    updater.write_source(members)
    listing = Mock(side_effect=AssertionError("Damaged item sources cannot consume Learn data"))
    monkeypatch.setattr(update_db, "resolve_microsoft_item_listing_snapshot", listing)
    code, report = updater.run(*(("--dry-run",) if dry_run else ()))
    assert code == 1 and report["applied"] is not dry_run
    assert report["quality"]["sections"]["items"]["status"] == "blocked"
    assert report["quality"]["sections"]["effects"]["status"] == "checked"
    assert "probe.json" in report["blocked"][0]["reason"]
    listing.assert_not_called()
    result = updater.read_db()
    for key in original.keys() - {"effects", "enchantments", "schema_version"}:
        assert result[key] == original[key], key
    assert ("38" in result["effects"]) is not dry_run
    if not dry_run:
        assert "verification" not in updater.read_metadata()
        updater.write_source(_members())
        monkeypatch.setattr(update_db, "resolve_microsoft_item_listing_snapshot", lambda **kwargs: ({}, {}))
        assert updater.run()[0] == 0
        assert update_db.item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]


@pytest.mark.parametrize("failure", ["late-source", "audit"])
def test_rejected_complete_item_candidate_cannot_leak_names_limits_or_source_metadata(updater, monkeypatch, failure):
    assert updater.run()[0] == 0
    original = updater.read_db()
    original["effects"] = {}
    updater.write_db(original)
    metadata = updater.read_metadata()
    members = _members()
    members["resource_pack/texts/en_US.lang"] += "item.future_probe.name=Future Probe\n"
    members["resource_pack/texts/de_DE.lang"] += "item.future_probe.name=Quellenname\n"
    updater.write_source(members)
    monkeypatch.setattr(update_db, "merge_item_limits", lambda *args, **kwargs: ({"minecraft:future_probe": 0 if failure == "audit" else 16}, {}))
    if failure == "late-source":
        monkeypatch.setattr(update_db, "compute_block_item_ids", Mock(side_effect=RuntimeError("Synthetic late item source failure")))
    code, report = updater.run()
    assert code == 1 and report["applied"] is True
    assert report["quality"]["sections"]["items"]["status"] == "blocked"
    assert report["sections"]["items"] == {"added": 0, "removed": 0, "changed": 0}
    result = updater.read_db()
    for key in original.keys() - {"effects", "enchantments", "schema_version"}:
        assert result[key] == original[key], key
    assert "38" in result["effects"]
    assert updater.read_metadata()["update_quality"]["sections"]["items"]["locales"] == metadata["update_quality"]["sections"]["items"]["locales"]


@pytest.mark.parametrize("scope", ["items", "effects", "enchants"])
def test_scoped_update_preserves_unselected_legacy_sections_without_normalizing(updater, scope):
    original = updater.read_db()
    # Older installations omit optional descriptions and component fields.
    original["effects"] = {"1": ["Eigene Geschwindigkeit", "Custom speed"]}
    original["enchantments"] = {"17": ["Eigene Haltbarkeit", "Custom durability", 3]}
    original["items"] = {"minecraft:stone": ["Eigener Stein", "Custom stone"]}
    original.pop("item_components", None)
    updater.write_db(original)

    code, report = updater.run("--only", scope)

    assert code == 0 and report["applied"] is True
    result = updater.read_db()
    updated_keys = {"items": {"items"}, "effects": {"effects"}, "enchants": {"enchantments"}}[scope]
    for key in {"items", "effects", "enchantments"} - updated_keys:
        assert result[key] == original[key]
    if scope != "items":
        assert "item_components" not in result
        for key in original.keys() - {"schema_version", "effects", "enchantments"}:
            assert result[key] == original[key], key
