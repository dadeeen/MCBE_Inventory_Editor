import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import item_db_verification as verification
from scripts import update_db


def _coverage_quality():
    return {
        "schema": 1,
        "sections": {
            "effects": {
                "status": "checked",
                "release": "v1",
                "attempted_release": "v1",
                "locales": {"de": {"total": 1, "official": 0, "fallbacks": [{"id": "freezing", "source": "curated"}]}},
            }
        },
    }


def test_receipt_binds_name_coverage_and_survives_metadata_reload(tmp_path):
    import json

    database = tmp_path / "item_db.json"
    database.write_text("{}", encoding="utf-8")
    metadata = verification.attach_item_db_verification({"update_quality": _coverage_quality()}, database, verified_at="checked")
    reloaded = json.loads(json.dumps(metadata))
    assert verification.item_db_verification_snapshot(reloaded, database)["verified"]
    reloaded["update_quality"]["sections"]["effects"]["locales"]["de"]["official"] = 1
    assert verification.item_db_verification_snapshot(reloaded, database)["reason"] == "source-changed"


def test_blocked_or_malformed_quality_cannot_obtain_a_full_receipt(tmp_path):
    database = tmp_path / "item_db.json"
    database.write_text("{}", encoding="utf-8")
    blocked = _coverage_quality()
    blocked["sections"]["effects"]["status"] = "blocked"
    for quality in (blocked, {"schema": True, "sections": {}}, {"schema": 99, "sections": {}}):
        with pytest.raises(ValueError, match="Prüfbeleg"):
            verification.attach_item_db_verification({"update_quality": quality}, database, verified_at="checked")


def test_previous_contract_requires_a_fresh_check(tmp_path):
    database = tmp_path / "item_db.json"
    database.write_text("{}", encoding="utf-8")
    metadata = verification.attach_item_db_verification({}, database, verified_at="checked")
    metadata[verification.VERIFICATION_FIELD]["updater_contract_version"] = verification.UPDATER_CONTRACT_VERSION - 1
    assert verification.item_db_verification_snapshot(metadata, database)["reason"] == "updater-contract-mismatch"


def test_online_listing_identity_uses_parsed_items_instead_of_page_html(monkeypatch):
    rows = [f"<tr><td>test_item_{index}</td><td>{index}</td></tr>" for index in range(1000)]
    pages = iter(
        [
            "<header>First page layout</header><table>" + "".join(rows) + "</table>",
            "<header>Different page layout</header><table>" + "".join(reversed(rows)) + "</table>",
            "<table>" + "".join(rows).replace("test_item_999<", "another_item<") + "</table>",
        ]
    )

    class Response(io.BytesIO):
        def geturl(self):
            return update_db.MICROSOFT_ITEM_LISTINGS_URL

    opener = SimpleNamespace(open=lambda *_args, **_kwargs: Response(next(pages).encode()))
    monkeypatch.setattr(update_db, "_build_validating_opener", lambda *_args, **_kwargs: opener)
    first_items, first = update_db.fetch_microsoft_item_listing_snapshot()
    same_items, same = update_db.fetch_microsoft_item_listing_snapshot()
    changed_items, changed = update_db.fetch_microsoft_item_listing_snapshot()

    assert first_items == same_items
    assert first["microsoft_item_listing_content_hash"] != same["microsoft_item_listing_content_hash"]
    assert first["microsoft_item_listing_items_hash"] == same["microsoft_item_listing_items_hash"]
    assert verification.source_identity_from_metadata(first) == verification.source_identity_from_metadata(same)
    assert len(first_items) == len(changed_items)
    assert verification.source_identity_from_metadata(first) != verification.source_identity_from_metadata(changed)


def test_normalized_listing_identity_migrates_once_and_preserves_legacy_receipts(tmp_path):
    database = tmp_path / "item_db.json"
    database.write_text("{}", encoding="utf-8")
    legacy = {
        "microsoft_item_listing_url": update_db.MICROSOFT_ITEM_LISTINGS_URL,
        "microsoft_item_listing_content_hash": "a" * 64,
        "microsoft_item_listing_count": 1000,
    }
    verified_legacy = verification.attach_item_db_verification(legacy, database, verified_at="checked")
    assert verification.item_db_verification_snapshot(verified_legacy, database)["verified"]
    assert "microsoft_item_listing_items_hash" not in verification.source_identity_from_metadata(legacy)
    normalized = update_db.merge_source_metadata(legacy, item_listing_snapshot={**legacy, "microsoft_item_listing_items_hash": "b" * 64})
    assert verification.source_identity_from_metadata(legacy) != verification.source_identity_from_metadata(normalized)
    verified = verification.attach_item_db_verification(normalized, database, verified_at="checked")
    html_only = {**verified, "microsoft_item_listing_content_hash": "c" * 64}
    assert verification.item_db_verification_snapshot(html_only, database)["verified"]
    changed_items = {**verified, "microsoft_item_listing_items_hash": "d" * 64}
    assert verification.item_db_verification_snapshot(changed_items, database)["reason"] == "source-changed"
    # Partial updates retain the normalized fingerprint; legacy input must not
    # reuse a fingerprint belonging to a different source snapshot.
    assert update_db.merge_source_metadata(normalized)["microsoft_item_listing_items_hash"] == "b" * 64
    assert "microsoft_item_listing_items_hash" not in update_db.merge_source_metadata(normalized, item_listing_snapshot=legacy)


@pytest.mark.parametrize(
    "field,value",
    [("microsoft_item_listing_count", 1001), ("microsoft_item_listing_url", "https://example.test/items"), ("resource_pack_release", "different")],
)
def test_normalized_identity_still_detects_other_source_changes(field, value):
    metadata = {"microsoft_item_listing_items_hash": "b" * 64, "microsoft_item_listing_count": 1000}
    assert verification.source_identity_from_metadata(metadata) != verification.source_identity_from_metadata({**metadata, field: value})


def test_cache_rejects_a_fingerprint_for_different_items():
    items = {f"test_item_{index}": f"Test Item {index}" for index in range(1000)}
    metadata = {
        "microsoft_item_listing_url": update_db.MICROSOFT_ITEM_LISTINGS_URL,
        "microsoft_item_listing_fetched_at": "checked",
        "microsoft_item_listing_content_hash": "a" * 64,
        "microsoft_item_listing_items_hash": "b" * 64,
        "microsoft_item_listing_count": len(items),
    }
    with pytest.raises(verification.UpdateReviewError, match="wurde verändert"):
        verification.build_item_listing_cache_payload(items, metadata)


@pytest.mark.parametrize("value", [None, False, 123, "", "bad", "g" * 64])
def test_source_metadata_rejects_invalid_item_fingerprints(value):
    assert not update_db._valid_source_metadata({"microsoft_item_listing_items_hash": value})


def test_review_listing_reads_at_most_the_input_limit_plus_one_byte(monkeypatch):
    reads = []

    class Source(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(verification, "MAX_ITEM_LISTING_CACHE_BYTES", 32)
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: Source(b"x" * 64))
    with pytest.raises(verification.UpdateReviewError, match="Größe"):
        verification._review_item_listing_state(Path("listing.json"))
    assert reads == [33]


@pytest.mark.parametrize("content", [b"", b"{broken", b"\xff"])
def test_review_identity_accepts_invalid_optional_bytes_but_consumption_still_rejects(tmp_path, content):
    path = tmp_path / "listing.json"
    path.write_bytes(content)
    state, source_hash = verification._review_item_listing_state(path)
    assert state["exists"] is True
    assert state["size"] == len(content)
    assert source_hash is None
    with pytest.raises(verification.UpdateReviewError):
        verification.read_item_listing_cache(path)


def test_unreadable_optional_listing_cannot_obtain_a_receipt(monkeypatch, tmp_path):
    def fail_read(*_args, **_kwargs):
        raise PermissionError("synthetic permission failure")

    monkeypatch.setattr(Path, "open", fail_read)
    with pytest.raises(verification.UpdateReviewError, match="nicht gelesen"):
        verification._review_item_listing_state(tmp_path / "listing.json")
