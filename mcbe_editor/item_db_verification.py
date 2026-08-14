"""Verification and dry-run receipts for persistent item database updates.

Persisted receipts bind a successful full update to its resulting database and
source identity.  Ephemeral dry-run receipts bind a later apply to the reviewed
source snapshots, scope, and starting database metadata.
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

UPDATE_REVIEW_SCHEMA_VERSION = 1
ITEM_LISTING_CACHE_SCHEMA_VERSION = 1
ITEM_LISTING_CACHE_FILENAME = "microsoft_item_listing_snapshot.json"
RESOURCE_PACK_CACHE_FILENAME = "bedrock_resource_pack.zip"
RESOURCE_PACK_METADATA_FILENAME = "release_metadata.json"
MAX_ITEM_LISTING_CACHE_BYTES = 8 * 1024 * 1024
MAX_REVIEW_RESOURCE_PACK_BYTES = 200 * 1024 * 1024
_ITEM_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_]+$")
_UPDATE_SCOPES = {"all", "items", "effects", "enchants"}


class UpdateReviewError(ValueError):
    """A cached dry-run input is absent, malformed, or no longer current."""


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_item_listing(items: object) -> dict[str, str]:
    if not isinstance(items, dict) or not 1_000 <= len(items) <= 10_000:
        raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot hat eine unerwartete Anzahl Einträge.")
    normalized: dict[str, str] = {}
    for identifier, name in items.items():
        if not isinstance(identifier, str) or not _ITEM_IDENTIFIER_PATTERN.fullmatch(identifier) or len(identifier) > 128:
            raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot enthält eine ungültige Item-ID.")
        if not isinstance(name, str) or not name.strip() or len(name) > 512:
            raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot enthält einen ungültigen Anzeigenamen.")
        normalized[identifier] = name
    return dict(sorted(normalized.items()))


def build_item_listing_cache_payload(items: Mapping[str, str], metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Build a self-verifying cache payload from the normalized Learn listing."""

    normalized = _validated_item_listing(dict(items))
    url = metadata.get("microsoft_item_listing_url")
    fetched_at = metadata.get("microsoft_item_listing_fetched_at")
    content_hash = metadata.get("microsoft_item_listing_content_hash")
    count = metadata.get("microsoft_item_listing_count")
    if not isinstance(url, str) or not url:
        raise UpdateReviewError("Dem Microsoft-Itemlisten-Snapshot fehlt die Quell-URL.")
    if not isinstance(fetched_at, str) or not fetched_at:
        raise UpdateReviewError("Dem Microsoft-Itemlisten-Snapshot fehlt der Abrufzeitpunkt.")
    if not isinstance(content_hash, str) or not _SHA256_PATTERN.fullmatch(content_hash):
        raise UpdateReviewError("Der Inhalts-Hash des Microsoft-Itemlisten-Snapshots ist ungültig.")
    if type(count) is not int or count != len(normalized):
        raise UpdateReviewError("Die Eintragszahl des Microsoft-Itemlisten-Snapshots ist inkonsistent.")
    return {
        "schema_version": ITEM_LISTING_CACHE_SCHEMA_VERSION,
        "microsoft_item_listing_url": url,
        "microsoft_item_listing_fetched_at": fetched_at,
        "microsoft_item_listing_content_hash": content_hash,
        "microsoft_item_listing_count": count,
        "microsoft_item_listing_items_hash": _canonical_sha256(normalized),
        "items": normalized,
    }


def parse_item_listing_cache_payload(payload: object) -> tuple[dict[str, str], dict[str, Any]]:
    """Validate and unpack a normalized Microsoft Learn item-list snapshot."""

    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != ITEM_LISTING_CACHE_SCHEMA_VERSION
    ):
        raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot hat ein unbekanntes Format.")
    items = _validated_item_listing(payload.get("items"))
    expected_items_hash = payload.get("microsoft_item_listing_items_hash")
    if not isinstance(expected_items_hash, str) or not _SHA256_PATTERN.fullmatch(expected_items_hash):
        raise UpdateReviewError("Der Item-Hash des Microsoft-Itemlisten-Snapshots ist ungültig.")
    if not hmac.compare_digest(expected_items_hash, _canonical_sha256(items)):
        raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot wurde verändert.")
    metadata = {
        "microsoft_item_listing_url": payload.get("microsoft_item_listing_url"),
        "microsoft_item_listing_fetched_at": payload.get("microsoft_item_listing_fetched_at"),
        "microsoft_item_listing_content_hash": payload.get("microsoft_item_listing_content_hash"),
        "microsoft_item_listing_count": payload.get("microsoft_item_listing_count"),
    }
    # Reuse the same metadata validation as the writer and ensure the count is
    # tied to the exact normalized mapping that the updater will consume.
    build_item_listing_cache_payload(items, metadata)
    return items, metadata


def read_item_listing_cache(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Read a bounded, validated normalized Microsoft Learn item snapshot."""

    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_ITEM_LISTING_CACHE_BYTES:
            raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot hat eine unerwartete Größe.")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot kann nicht gelesen werden.") from exc
    return parse_item_listing_cache_payload(payload)


def _review_file_state(path: Path, *, required: bool) -> dict[str, Any]:
    try:
        if not path.is_file():
            if required:
                raise UpdateReviewError(f"Erforderliche Dry-Run-Ausgangsdatei fehlt: {path.name}")
            return {"exists": False}
        stat_info = path.stat()
        return {
            "exists": True,
            "size": stat_info.st_size,
            "sha256": file_sha256(path),
        }
    except OSError as exc:
        raise UpdateReviewError(f"Dry-Run-Ausgangsdatei kann nicht geprüft werden: {path.name}") from exc


def update_review_snapshot(
    *,
    update_cache_dir: Path,
    item_db_path: Path,
    source_version_path: Path,
    source_version_history_path: Path,
    scope: str | None,
) -> dict[str, Any]:
    """Bind a dry run to all mutable source and base files used by an apply."""

    normalized_scope = scope or "all"
    if normalized_scope not in _UPDATE_SCOPES:
        raise UpdateReviewError("Der Dry-Run-Bereich ist ungültig.")

    metadata_path = update_cache_dir / RESOURCE_PACK_METADATA_FILENAME
    archive_path = update_cache_dir / RESOURCE_PACK_CACHE_FILENAME
    try:
        metadata_size = metadata_path.stat().st_size
        if metadata_size <= 0 or metadata_size > 64 * 1024:
            raise UpdateReviewError("Die Resource-Pack-Metadaten haben eine unerwartete Größe.")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise UpdateReviewError("Die Resource-Pack-Metadaten können nicht gelesen werden.") from exc
    if not isinstance(metadata, dict):
        raise UpdateReviewError("Die Resource-Pack-Metadaten haben ein ungültiges Format.")

    resource_identity = {field: metadata.get(field) for field in RESOURCE_PACK_SOURCE_FIELDS}
    release_name = resource_identity["resource_pack_release"]
    asset_name = resource_identity["resource_pack_asset"]
    resource_pack_url = resource_identity["resource_pack_url"]
    if (
        not isinstance(release_name, str)
        or not release_name
        or not isinstance(asset_name, str)
        or not asset_name
        or not isinstance(resource_pack_url, str)
        or not resource_pack_url
    ):
        raise UpdateReviewError("Die Resource-Pack-Metadaten sind unvollständig.")
    if Path(asset_name).name != asset_name or any(separator in asset_name for separator in ("/", "\\")):
        raise UpdateReviewError("Der Resource-Pack-Assetname ist ungültig.")
    if not resource_pack_url.startswith("https://"):
        raise UpdateReviewError("Die Resource-Pack-URL ist ungültig.")
    expected_size = resource_identity["resource_pack_asset_size"]
    if type(expected_size) is not int or not 0 < expected_size <= MAX_REVIEW_RESOURCE_PACK_BYTES:
        raise UpdateReviewError("Die Resource-Pack-Größe ist ungültig.")
    try:
        if not archive_path.is_file() or archive_path.stat().st_size != expected_size:
            raise UpdateReviewError("Das im Dry-Run verwendete Resource-Pack fehlt oder wurde verändert.")
        archive_hash = file_sha256(archive_path)
    except OSError as exc:
        raise UpdateReviewError("Das im Dry-Run verwendete Resource-Pack kann nicht geprüft werden.") from exc

    item_listing: dict[str, Any] | None = None
    if normalized_scope in {"all", "items"}:
        listing_path = update_cache_dir / ITEM_LISTING_CACHE_FILENAME
        _, listing_metadata = read_item_listing_cache(listing_path)
        try:
            item_listing = {
                **{field: listing_metadata[field] for field in ITEM_LISTING_SOURCE_FIELDS},
                "snapshot_sha256": file_sha256(listing_path),
            }
        except OSError as exc:
            raise UpdateReviewError("Der Microsoft-Itemlisten-Snapshot kann nicht geprüft werden.") from exc

    token_payload = {
        "schema_version": UPDATE_REVIEW_SCHEMA_VERSION,
        "updater_contract_version": UPDATER_CONTRACT_VERSION,
        "scope": normalized_scope,
        "resource_pack": {**resource_identity, "archive_sha256": archive_hash},
        "microsoft_item_listing": item_listing,
        "base_files": {
            "item_db": _review_file_state(item_db_path, required=True),
            "source_version": _review_file_state(source_version_path, required=False),
            "source_version_history": _review_file_state(source_version_history_path, required=False),
        },
    }
    return {
        "token": _canonical_sha256(token_payload),
        "scope": normalized_scope,
        "resource_pack_release": resource_identity["resource_pack_release"],
        "resource_pack_asset": resource_identity["resource_pack_asset"],
        "microsoft_item_listing_content_hash": (
            item_listing["microsoft_item_listing_content_hash"] if item_listing is not None else None
        ),
    }


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
