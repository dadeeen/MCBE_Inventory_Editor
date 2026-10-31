"""A reviewed apply preserves the preview's permissions as well as its inputs."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from unittest.mock import Mock, patch

import pytest

from mcbe_editor import item_db_api_routes, item_db_verification as verification
from tests.test_item_db_api_routes import _deps, _record_review_plan, _review_deps, _write_release_cache
from tests.test_update_db import update_db
from tests.test_update_source_quality import updater as updater


_RESOLVE_LISTING = update_db.resolve_microsoft_item_listing_snapshot


@pytest.fixture
def online_updater(updater, monkeypatch):
    """Keep CLI/API orchestration real; replace only the two network sources."""
    cache = update_db.CACHE_DIR
    listing_path = cache / verification.ITEM_LISTING_CACHE_FILENAME
    monkeypatch.setattr(update_db, "ITEM_LISTING_CACHE_PATH", listing_path)
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", cache / verification.RESOURCE_PACK_METADATA_FILENAME)
    monkeypatch.setattr(update_db, "resolve_microsoft_item_listing_snapshot", _RESOLVE_LISTING)
    listing = {f"test_item_{index}": f"Test Item {index}" for index in range(1_000)}
    listing["stone"] = "Stone"
    metadata = {
        "microsoft_item_listing_url": update_db.MICROSOFT_ITEM_LISTINGS_URL,
        "microsoft_item_listing_fetched_at": "fixture",
        "microsoft_item_listing_content_hash": hashlib.sha256(b"fixture").hexdigest(),
        "microsoft_item_listing_count": len(listing),
    }
    update_db.write_microsoft_item_listing_cache(listing, metadata)
    fetch_listing = Mock(side_effect=RuntimeError("Synthetic Learn timeout"))
    release_lookup = Mock(side_effect=lambda: update_db.read_release_metadata())
    monkeypatch.setattr(update_db, "fetch_microsoft_item_listing_snapshot", fetch_listing)
    monkeypatch.setattr(update_db, "get_latest_release_info", release_lookup)
    calls = []

    def run_update_db(**kwargs):
        calls.append(kwargs)
        argv = ["update_db.py", "--json-summary"]
        for key, flag in (("dry_run", "--dry-run"), ("force", "--force"), ("use_cache", "--cache")):
            if kwargs[key]:
                argv.append(flag)
        if kwargs["only"]:
            argv.extend(("--only", kwargs["only"]))
        if kwargs["expected_review_token"]:
            argv.extend(("--expected-review-token", kwargs["expected_review_token"]))
        output = io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
            code = update_db.main()
        update_db.item_db_transaction.recover_item_db(
            update_db.item_db_transaction.configured_targets(update_db.ITEM_DB_PATH, update_db.SOURCE_VERSION_JSON, update_db.SOURCE_VERSION_HISTORY)
        )
        return code, output.getvalue()

    deps = _deps(
        item_db_path=str(update_db.ITEM_DB_PATH),
        source_version_path=str(update_db.SOURCE_VERSION_JSON),
        source_version_history_path=str(update_db.SOURCE_VERSION_HISTORY),
        update_cache_dir=str(cache),
        run_update_db=run_update_db,
    )
    return deps, fetch_listing, release_lookup, calls, (listing, metadata)


def test_online_partial_preview_cannot_promote_blocked_items_from_an_older_cache(updater, online_updater):
    deps, fetch_listing, release_lookup, calls, fresh_listing = online_updater
    database = updater.read_db()
    database["items"].pop("minecraft:stone", None)
    database["effects"] = {}
    updater.write_db(database)
    before = updater.snapshot()
    preview = item_db_api_routes.update_db({"dry_run": True}, deps)[1]
    assert calls[-1]["use_cache"] is False
    release_lookup.assert_called_once()
    fetch_listing.assert_called_once()
    assert updater.snapshot() == before
    assert preview["summary"]["sections"]["items"] == {"added": 0, "removed": 0, "changed": 0}
    token = preview["update_review_token"]

    applied = item_db_api_routes.update_db({"dry_run": False, "force": True, "expected_update_review_token": token}, deps)[1]

    assert calls[-1]["use_cache"] is True
    assert applied["outcome"] == "partial"
    assert applied["summary"]["blocked"] == preview["summary"]["blocked"]
    assert applied["summary"]["sections"]["items"] == preview["summary"]["sections"]["items"]
    assert updater.read_db()["items"] == database["items"]
    assert "38" in updater.read_db()["effects"]
    assert "verification" not in updater.read_metadata()
    release_lookup.assert_called_once()
    fetch_listing.assert_called_once()

    # Only a fresh successful preview can approve that section again.
    fetch_listing.side_effect = None
    fetch_listing.return_value = fresh_listing
    refreshed = item_db_api_routes.update_db({"dry_run": True}, deps)[1]
    assert refreshed["success"] is True
    assert refreshed["summary"]["sections"]["items"]["added"] > 0
    completed = item_db_api_routes.update_db({"dry_run": False, "force": True, "expected_update_review_token": refreshed["update_review_token"]}, deps)[1]
    assert completed["success"] is True
    assert "minecraft:stone" in updater.read_db()["items"]
    assert verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]


def test_failed_new_preview_invalidates_the_previous_plan(updater, online_updater):
    deps, fetch_listing, _release_lookup, _calls, fresh_listing = online_updater
    fetch_listing.side_effect = None
    fetch_listing.return_value = fresh_listing
    first = item_db_api_routes.update_db({"dry_run": True}, deps)[1]
    assert first["update_review_token"]
    # A new attempt fails without changing either the source bytes or base data.
    fetch_listing.side_effect = RuntimeError("Synthetic Learn timeout")
    failed = item_db_api_routes.update_db({"dry_run": True, "only": "items"}, deps)[1]
    assert failed["success"] is False
    assert "update_review_token" not in failed
    assert not (update_db.CACHE_DIR / verification.UPDATE_REVIEW_PLAN_FILENAME).exists()
    rejected = item_db_api_routes.update_db({"dry_run": False, "force": True, "expected_update_review_token": first["update_review_token"]}, deps)
    assert rejected[0] == "error"


@pytest.mark.parametrize("change", ["promote", "scope", "delete", "malformed", "oversized"])
def test_changed_or_unreadable_plan_cannot_apply_the_old_token(tmp_path, change):
    cache = _write_release_cache(tmp_path)
    _record_review_plan(cache, blocked={"items": "Learn timeout"})
    deps = _review_deps(cache, run_update_db=Mock())
    token = item_db_api_routes.update_review_snapshot(deps, None)["token"]
    path = cache.cache_dir / verification.UPDATE_REVIEW_PLAN_FILENAME
    plan = json.loads(path.read_bytes())
    if change == "promote":
        plan["blocked"] = {}
    elif change == "scope":
        plan["scope"] = "effects"
    if change in {"promote", "scope"}:
        path.write_text(json.dumps(plan), encoding="utf-8")
    elif change == "delete":
        path.unlink()
    else:
        path.write_bytes(b"x" * (64 * 1024 + 1) if change == "oversized" else b"{broken")
    result = item_db_api_routes.update_db({"dry_run": False, "force": True, "expected_update_review_token": token}, deps)
    assert result[0] == "error"
    deps.run_update_db.assert_not_called()


def test_all_blocked_sections_cannot_create_an_applicable_plan(tmp_path):
    cache = _write_release_cache(tmp_path)
    with pytest.raises(verification.UpdateReviewError, match="Bereiche"):
        _record_review_plan(cache, blocked={section: "Unavailable" for section in ("items", "effects", "enchants")})
