"""Every cache consumer rejects interrupted or mismatched archive generations."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import Mock

import pytest

from mcbe_editor import item_db_verification as verification
from tests.test_update_db import _zip_bytes, update_db
from tests.test_update_source_quality import updater as updater


_READ_RELEASE_METADATA = update_db.read_release_metadata
_WRITE_RELEASE_METADATA = update_db.write_release_metadata


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("damage", ["size", "hash", "invalid-hash", "pending"])
def test_direct_cache_replay_rejects_mixed_generation_before_any_publication(updater, monkeypatch, dry_run, damage):
    metadata_path = update_db.CACHE_DIR / verification.RESOURCE_PACK_METADATA_FILENAME
    archive = update_db.CACHE_DIR / verification.RESOURCE_PACK_CACHE_FILENAME
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", metadata_path)
    monkeypatch.setattr(update_db, "read_release_metadata", _READ_RELEASE_METADATA)
    metadata = json.loads(metadata_path.read_bytes())
    if damage == "size":
        metadata["resource_pack_release"] = "v-old"
        metadata["resource_pack_asset_size"] += 1
    elif damage in {"hash", "invalid-hash"}:
        metadata["resource_pack_archive_sha256"] = "0" * 64 if damage == "hash" else False
    else:
        verification.resource_pack_pending_path(archive).write_text("pending", encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    before = updater.snapshot()
    code, report = updater.run(*(("--dry-run",) if dry_run else ()))
    assert code == 1 and report["applied"] is False
    assert len(report["blocked"]) == 3
    assert updater.snapshot() == before
    with pytest.raises(verification.UpdateReviewError):
        verification.validate_resource_pack_archive(archive, metadata)


def test_legacy_valid_cache_remains_usable_without_a_hash(updater, monkeypatch):
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", update_db.CACHE_DIR / verification.RESOURCE_PACK_METADATA_FILENAME)
    monkeypatch.setattr(update_db, "read_release_metadata", _READ_RELEASE_METADATA)
    assert "resource_pack_archive_sha256" not in update_db.read_release_metadata()
    assert updater.run("--dry-run")[0] == 0
    assert updater.run()[0] == 0


@pytest.mark.parametrize("old_metadata_has_hash", [False, True])
def test_process_death_between_equal_size_zip_and_metadata_replacement_requires_refresh(updater, monkeypatch, old_metadata_has_hash):
    archive = update_db.CACHE_DIR / verification.RESOURCE_PACK_CACHE_FILENAME
    metadata_path = update_db.CACHE_DIR / verification.RESOURCE_PACK_METADATA_FILENAME
    old_bytes = _zip_bytes("probe.txt", b"old")
    new_bytes = _zip_bytes("probe.txt", b"new")
    assert len(old_bytes) == len(new_bytes)
    archive.write_bytes(old_bytes)
    old_metadata = {
        "resource_pack_release": "v1",
        "resource_pack_asset": "old.zip",
        "resource_pack_asset_size": len(old_bytes),
        "resource_pack_url": "https://github.com/Mojang/bedrock-samples/releases/download/v1/old.zip",
    }
    if old_metadata_has_hash:
        old_metadata["resource_pack_archive_sha256"] = hashlib.sha256(old_bytes).hexdigest()
    metadata_path.write_text(json.dumps(old_metadata), encoding="utf-8")
    new_metadata = {**old_metadata, "resource_pack_release": "v2", "resource_pack_asset": "new.zip"}
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", metadata_path)
    monkeypatch.setattr(update_db, "read_release_metadata", _READ_RELEASE_METADATA)
    monkeypatch.setattr(update_db, "download_with_progress", lambda _url, path, **_kwargs: path.write_bytes(new_bytes))
    monkeypatch.setattr(update_db, "write_release_metadata", Mock(side_effect=SystemExit("worker death")))
    before = updater.snapshot()

    # BaseException deliberately bypasses the normal in-process rollback.
    with pytest.raises(SystemExit, match="worker death"):
        update_db.download_latest_rp(archive, release_info=new_metadata)
    assert archive.read_bytes() == new_bytes
    assert json.loads(metadata_path.read_bytes()) == old_metadata
    assert update_db._matching_cached_release(archive, old_metadata) == {}
    code, report = updater.run()
    assert code == 1 and report["applied"] is False
    assert updater.snapshot() == before

    monkeypatch.setattr(update_db, "write_release_metadata", _WRITE_RELEASE_METADATA)
    monkeypatch.setattr(update_db, "get_latest_release_info", lambda: new_metadata)
    refreshed = update_db.resolve_latest_rp(archive)
    assert not verification.resource_pack_pending_path(archive).exists()
    assert refreshed["resource_pack_archive_sha256"] == hashlib.sha256(new_bytes).hexdigest()
    assert verification.validate_resource_pack_archive(archive, refreshed) == refreshed["resource_pack_archive_sha256"]


def test_new_download_hash_detects_equal_size_replacement(updater, monkeypatch):
    archive = update_db.CACHE_DIR / verification.RESOURCE_PACK_CACHE_FILENAME
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", update_db.CACHE_DIR / verification.RESOURCE_PACK_METADATA_FILENAME)
    original = _zip_bytes("probe.txt", b"one")
    replacement = _zip_bytes("probe.txt", b"two")
    assert len(original) == len(replacement)
    metadata = {**update_db.read_release_metadata(), "resource_pack_asset_size": len(original)}
    monkeypatch.setattr(update_db, "download_with_progress", lambda _url, path, **_kwargs: path.write_bytes(original))
    saved = update_db.download_latest_rp(archive, release_info=metadata)
    archive.write_bytes(replacement)
    update_db._validate_downloaded_zip(archive)  # Both ZIPs are independently valid.
    with pytest.raises(verification.UpdateReviewError, match="Release-Metadaten"):
        verification.validate_resource_pack_archive(archive, saved)
