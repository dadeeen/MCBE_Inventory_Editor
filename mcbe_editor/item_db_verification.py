"""Verification receipts for persistent item database updates.

The receipt belongs to the server-side data artifact, not to a browser.  It
binds a successful full updater run to both the resulting ``item_db.json`` and
the stable source identity recorded in ``source_version.json``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

RESOURCE_PACK_SOURCE_FIELDS = (
    "resource_pack_release",
    "resource_pack_asset",
    "resource_pack_asset_size",
    "resource_pack_url",
)
ITEM_LISTING_SOURCE_FIELDS = (
    "microsoft_item_listing_url",
    "microsoft_item_listing_content_hash",
    "microsoft_item_listing_count",
)
WIKI_SOURCE_FIELDS = (
    "wiki_url",
    "wiki_revision_id",
    "wiki_content_hash",
)
SOURCE_IDENTITY_FIELDS = RESOURCE_PACK_SOURCE_FIELDS + ITEM_LISTING_SOURCE_FIELDS + WIKI_SOURCE_FIELDS
SOURCE_IDENTITY_DEFAULTS: dict[str, Any] = {
    "resource_pack_release": "",
    "resource_pack_asset": "",
    "resource_pack_asset_size": 0,
    "resource_pack_url": "",
    "microsoft_item_listing_url": "",
    "microsoft_item_listing_content_hash": "",
    "microsoft_item_listing_count": 0,
    "wiki_url": "",
    "wiki_revision_id": None,
    "wiki_content_hash": "",
}

VERIFICATION_FIELD = "verification"
VERIFICATION_SCHEMA_VERSION = 1
# Bump deliberately when updater semantics change enough that existing receipts
# must no longer count as a successful verification under the new code.
UPDATER_CONTRACT_VERSION = 1
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def source_identity_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable source identifiers without fetch timestamps."""

    return {field: metadata.get(field, SOURCE_IDENTITY_DEFAULTS[field]) for field in SOURCE_IDENTITY_FIELDS}


def source_identity_sha256(metadata: Mapping[str, Any]) -> str:
    identity = source_identity_from_metadata(metadata)
    canonical = json.dumps(identity, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def attach_item_db_verification(
    metadata: Mapping[str, Any],
    item_db_path: Path,
    *,
    verified_at: str,
) -> dict[str, Any]:
    """Return source metadata with a receipt for a successful full update."""

    if not isinstance(verified_at, str) or not verified_at.strip():
        raise ValueError("verified_at muss ein nichtleerer Zeitstempel sein.")
    result = dict(metadata)
    result[VERIFICATION_FIELD] = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "updater_contract_version": UPDATER_CONTRACT_VERSION,
        "verified_at": verified_at,
        "item_db_sha256": file_sha256(item_db_path),
        "source_identity_sha256": source_identity_sha256(metadata),
    }
    return result


def item_db_verification_snapshot(metadata: Mapping[str, Any], item_db_path: Path) -> dict[str, Any]:
    """Validate the persisted receipt against the current database and source."""

    receipt = metadata.get(VERIFICATION_FIELD)
    result: dict[str, Any] = {
        "verified": False,
        "reason": "missing",
        "verified_at": None,
        "schema_version": None,
        "updater_contract_version": None,
        "item_db_sha256": None,
        "source_identity_sha256": None,
    }
    if not isinstance(receipt, dict):
        return result

    schema_version = receipt.get("schema_version")
    contract_version = receipt.get("updater_contract_version")
    verified_at = receipt.get("verified_at")
    expected_db_sha256 = receipt.get("item_db_sha256")
    expected_source_sha256 = receipt.get("source_identity_sha256")
    result.update(
        {
            "verified_at": verified_at if isinstance(verified_at, str) else None,
            "schema_version": schema_version if type(schema_version) is int else None,
            "updater_contract_version": contract_version if type(contract_version) is int else None,
            "item_db_sha256": expected_db_sha256 if isinstance(expected_db_sha256, str) else None,
            "source_identity_sha256": expected_source_sha256 if isinstance(expected_source_sha256, str) else None,
        }
    )

    if type(schema_version) is not int or schema_version != VERIFICATION_SCHEMA_VERSION:
        result["reason"] = "schema-mismatch"
        return result
    if type(contract_version) is not int or contract_version != UPDATER_CONTRACT_VERSION:
        result["reason"] = "updater-contract-mismatch"
        return result
    if not isinstance(verified_at, str) or not verified_at.strip():
        result["reason"] = "invalid"
        return result
    if not isinstance(expected_db_sha256, str) or not _SHA256_PATTERN.fullmatch(expected_db_sha256):
        result["reason"] = "invalid"
        return result
    if not isinstance(expected_source_sha256, str) or not _SHA256_PATTERN.fullmatch(expected_source_sha256):
        result["reason"] = "invalid"
        return result

    try:
        current_db_sha256 = file_sha256(item_db_path)
    except OSError:
        result["reason"] = "item-db-missing"
        return result
    if not hmac.compare_digest(expected_db_sha256, current_db_sha256):
        result["reason"] = "item-db-changed"
        return result

    current_source_sha256 = source_identity_sha256(metadata)
    if not hmac.compare_digest(expected_source_sha256, current_source_sha256):
        result["reason"] = "source-changed"
        return result

    result["verified"] = True
    result["reason"] = "verified"
    return result
