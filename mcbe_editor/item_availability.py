"""Load and validate the curated item-availability classification."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Collection
from datetime import date
from pathlib import Path
from typing import Any

from mcbe_editor.item_data import MAX_DATA_VALUE
from mcbe_editor.item_registry_policy import is_technical_block_only_item_id
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON

BUNDLED_ITEM_AVAILABILITY_JSON = Path(__file__).resolve().parent / "resources" / "item_availability.json"
ITEM_AVAILABILITY_SCHEMA_VERSION = 1
ITEM_AVAILABILITY_CATEGORIES = (
    "technical",
    "command_only",
    "education",
    "generated_state",
    "legacy",
    "creative",
)
_ITEM_ID_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")


class InvalidItemAvailabilityError(ValueError):
    """Raised when the curated availability resource violates its schema."""


def _bundled_item_db_metadata() -> tuple[str, frozenset[str]]:
    try:
        raw = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
        source = raw.get("behavior_item_source", {})
        release = source.get("resource_pack_release", "") if isinstance(source, dict) else ""
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InvalidItemAvailabilityError(f"Gebündelte Item-Datenbank ist nicht lesbar: {BUNDLED_ITEM_DB_JSON}") from exc
    if not isinstance(release, str) or not release.strip():
        raise InvalidItemAvailabilityError("Gebündelte Item-Datenbank enthält keine resource_pack_release.")
    addable_items = raw.get("addable_items")
    if not isinstance(addable_items, list) or not all(isinstance(item_id, str) for item_id in addable_items):
        raise InvalidItemAvailabilityError("Gebündelte Item-Datenbank enthält keine gültige addable_items-Liste.")
    return release.strip(), frozenset(
        item_id for item_id in addable_items if not is_technical_block_only_item_id(item_id)
    )


BUNDLED_ITEM_DB_SOURCE_RELEASE, BUNDLED_ADDABLE_ITEM_IDS = _bundled_item_db_metadata()


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidItemAvailabilityError(f"{label} muss ein JSON-Objekt sein.")
    return value


def _require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidItemAvailabilityError(f"{label} muss eine nicht leere Zeichenfolge sein.")
    if value != value.strip():
        raise InvalidItemAvailabilityError(f"{label} darf keine äußeren Leerzeichen enthalten.")
    return value


def _item_id(value: Any, *, label: str) -> str:
    item_id = _require_text(value, label=label)
    if item_id != item_id.lower() or not _ITEM_ID_RE.fullmatch(item_id):
        raise InvalidItemAvailabilityError(f"{label} enthält keine normalisierte namespaced Item-ID: {item_id!r}")
    return item_id


def _references(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise InvalidItemAvailabilityError("references muss eine nicht leere Liste sein.")
    normalized: list[dict[str, Any]] = []
    covered_categories: set[str] = set()
    for index, raw_reference in enumerate(value):
        reference = _require_object(raw_reference, label=f"references[{index}]")
        unknown_keys = set(reference) - {"categories", "title", "url"}
        if unknown_keys:
            raise InvalidItemAvailabilityError(f"references[{index}] enthält unbekannte Schlüssel: {sorted(unknown_keys)}")
        categories = reference.get("categories")
        if not isinstance(categories, list) or not categories:
            raise InvalidItemAvailabilityError(f"references[{index}].categories muss eine nicht leere Liste sein.")
        normalized_categories: list[str] = []
        for category in categories:
            category_name = _require_text(category, label=f"references[{index}].categories")
            if category_name not in ITEM_AVAILABILITY_CATEGORIES:
                raise InvalidItemAvailabilityError(f"Unbekannte Verfügbarkeitskategorie in references[{index}]: {category_name}")
            if category_name in normalized_categories:
                raise InvalidItemAvailabilityError(f"Doppelte Kategorie in references[{index}]: {category_name}")
            normalized_categories.append(category_name)
        title = _require_text(reference.get("title"), label=f"references[{index}].title")
        url = _require_text(reference.get("url"), label=f"references[{index}].url")
        if not url.startswith("https://"):
            raise InvalidItemAvailabilityError(f"references[{index}].url muss eine HTTPS-URL sein.")
        normalized.append({"categories": normalized_categories, "title": title, "url": url})
        covered_categories.update(normalized_categories)

    missing_references = set(ITEM_AVAILABILITY_CATEGORIES) - covered_categories
    if missing_references:
        raise InvalidItemAvailabilityError(f"Kategorien ohne Quellenangabe: {sorted(missing_references)}")
    return normalized


def load_item_availability(
    path: str | Path = BUNDLED_ITEM_AVAILABILITY_JSON,
    *,
    known_item_ids: Collection[str] = BUNDLED_ADDABLE_ITEM_IDS,
    expected_source_release: str = BUNDLED_ITEM_DB_SOURCE_RELEASE,
    max_data_value: int = MAX_DATA_VALUE,
) -> dict[str, Any]:
    """Return a validated, JSON-safe availability payload."""

    source_path = Path(path)
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InvalidItemAvailabilityError(f"Item-Verfügbarkeitsdatei ist nicht lesbar: {source_path}") from exc

    root = _require_object(raw, label="Item-Verfügbarkeitsdatei")
    expected_keys = {"schema_version", "source_release", "reviewed_at", "references", "classifications", "variants"}
    unknown_keys = set(root) - expected_keys
    missing_keys = expected_keys - set(root)
    if unknown_keys or missing_keys:
        raise InvalidItemAvailabilityError(
            f"Ungültige Top-Level-Schlüssel (fehlend={sorted(missing_keys)}, unbekannt={sorted(unknown_keys)})."
        )
    if root.get("schema_version") != ITEM_AVAILABILITY_SCHEMA_VERSION:
        raise InvalidItemAvailabilityError(
            f"schema_version muss {ITEM_AVAILABILITY_SCHEMA_VERSION} sein."
        )

    source_release = _require_text(root.get("source_release"), label="source_release")
    if expected_source_release and source_release != expected_source_release:
        raise InvalidItemAvailabilityError(
            f"source_release {source_release!r} passt nicht zur Item-Datenbank {expected_source_release!r}."
        )
    reviewed_at = _require_text(root.get("reviewed_at"), label="reviewed_at")
    try:
        reviewed_date = date.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise InvalidItemAvailabilityError("reviewed_at muss ein ISO-Datum im Format YYYY-MM-DD sein.") from exc
    if reviewed_date.isoformat() != reviewed_at:
        raise InvalidItemAvailabilityError("reviewed_at muss ein ISO-Datum im Format YYYY-MM-DD sein.")

    references = _references(root.get("references"))
    classifications_raw = _require_object(root.get("classifications"), label="classifications")
    category_keys = set(classifications_raw)
    expected_categories = set(ITEM_AVAILABILITY_CATEGORIES)
    if category_keys != expected_categories:
        raise InvalidItemAvailabilityError(
            f"classifications muss exakt diese Kategorien enthalten: {sorted(expected_categories)}"
        )

    known_ids = set(known_item_ids)
    classified_ids: dict[str, str] = {}
    classifications: dict[str, list[str]] = {}
    for category in ITEM_AVAILABILITY_CATEGORIES:
        raw_items = classifications_raw[category]
        if not isinstance(raw_items, list) or not raw_items:
            raise InvalidItemAvailabilityError(f"classifications.{category} muss eine nicht leere Liste sein.")
        items: list[str] = []
        for index, raw_item_id in enumerate(raw_items):
            item_id = _item_id(raw_item_id, label=f"classifications.{category}[{index}]")
            previous_category = classified_ids.get(item_id)
            if previous_category is not None:
                raise InvalidItemAvailabilityError(
                    f"Item-ID {item_id!r} ist doppelt klassifiziert ({previous_category}, {category})."
                )
            if item_id not in known_ids:
                raise InvalidItemAvailabilityError(f"Klassifizierte Item-ID fehlt in ADDABLE_ITEM_IDS: {item_id}")
            classified_ids[item_id] = category
            items.append(item_id)
        classifications[category] = items

    variants_raw = _require_object(root.get("variants"), label="variants")
    variants: dict[str, dict[str, str]] = {}
    for raw_item_id, raw_data_values in variants_raw.items():
        item_id = _item_id(raw_item_id, label="variants-Schlüssel")
        if item_id in classified_ids:
            raise InvalidItemAvailabilityError(f"Item-ID {item_id!r} darf nicht zugleich vollständig und variantenspezifisch klassifiziert sein.")
        if item_id not in known_ids:
            raise InvalidItemAvailabilityError(f"Variantenspezifische Item-ID fehlt in ADDABLE_ITEM_IDS: {item_id}")
        data_values = _require_object(raw_data_values, label=f"variants.{item_id}")
        if not data_values:
            raise InvalidItemAvailabilityError(f"variants.{item_id} darf nicht leer sein.")
        normalized_values: dict[str, str] = {}
        for raw_damage, raw_category in data_values.items():
            try:
                damage = int(raw_damage)
            except (TypeError, ValueError) as exc:
                raise InvalidItemAvailabilityError(f"Ungültiger Datenwert für {item_id}: {raw_damage!r}") from exc
            if str(damage) != raw_damage or not 0 <= damage <= max_data_value:
                raise InvalidItemAvailabilityError(f"Ungültiger Datenwert für {item_id}: {raw_damage!r}")
            category = _require_text(raw_category, label=f"variants.{item_id}.{raw_damage}")
            if category not in ITEM_AVAILABILITY_CATEGORIES:
                raise InvalidItemAvailabilityError(f"Unbekannte Verfügbarkeitskategorie: {category}")
            normalized_values[raw_damage] = category
        variants[item_id] = normalized_values

    return {
        "schema_version": ITEM_AVAILABILITY_SCHEMA_VERSION,
        "source_release": source_release,
        "reviewed_at": reviewed_at,
        "references": references,
        "classifications": classifications,
        "variants": variants,
    }


ITEM_AVAILABILITY = load_item_availability()


def item_availability_client_payload() -> dict[str, Any]:
    """Return curated classifications plus current, unreviewed registry additions."""

    from mcbe_editor import item_data

    payload = copy.deepcopy(ITEM_AVAILABILITY)
    classifications = payload["classifications"]
    curated_item_ids = {
        item_id
        for item_ids in classifications.values()
        for item_id in item_ids
    } | set(payload["variants"])
    classifications["unreviewed"] = sorted(
        item_data.UNREVIEWED_ITEM_IDS - curated_item_ids
    )
    return payload
