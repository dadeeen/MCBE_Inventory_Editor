"""Read saved Bedrock actors without inventing identities or changing indexes.

Modern actors are stored separately from their chunk indexes. Legacy chunks
contain concatenated named NBT roots. Both representations are scanned, but
ambiguous identity, storage and index evidence always remains read-only.
"""

from __future__ import annotations

import base64
import hashlib
import math
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import nbt
from .bedrock_nbt import LOAD_KWARGS
from .i18n import t
from .read_operation import checkpoint

ACTOR_PREFIX = b"actorprefix"
DIGP_PREFIX = b"digp"
LEGACY_ENTITY_TAG = 0x32
MAX_ENTITY_RECORDS = 250_000
MAX_INDEX_REFERENCES = 2_000_000
MAX_DIAGNOSTICS = 200
_IDENTIFIER_FIELDS = ("identifier", "Identifier", "EntityIdentifier", "id", "Id")
_INTEGER_TAGS = (nbt.ByteTag, nbt.ShortTag, nbt.IntTag, nbt.LongTag)


def issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": t(message), **details}


def scalar_integer(tag: Any) -> int | None:
    return int(tag.py_data) if isinstance(tag, _INTEGER_TAGS) else None


def entity_identifier(tag: nbt.CompoundTag) -> str | None:
    # A readable alias cannot overrule another saved alias with an unknown
    # representation. Keep such actors visible, but never infer a write-safe
    # identity by silently dropping the conflicting evidence.
    if any(key in tag and not isinstance(tag[key], nbt.StringTag) for key in _IDENTIFIER_FIELDS):
        return None
    values = {str(tag[key].py_data) for key in _IDENTIFIER_FIELDS if isinstance(tag.get(key), nbt.StringTag)}
    return next(iter(values)) if len(values) == 1 else None


def entity_position(tag: nbt.CompoundTag) -> dict[str, float] | None:
    pos = tag.get("Pos")
    if not isinstance(pos, nbt.ListTag) or len(pos) != 3:
        return None
    if any(not isinstance(value, (nbt.FloatTag, nbt.DoubleTag)) or not math.isfinite(value.py_data) for value in pos):
        return None
    return dict(zip(("x", "y", "z"), (float(value.py_data) for value in pos), strict=True))


def entity_id(key: bytes, legacy_index: int | None = None) -> str:
    encoded = base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")
    return f"actor:{encoded}" if legacy_index is None else f"legacy:{encoded}:{legacy_index}"


def _chunk_key(key: bytes, *, prefix: bytes = b"", suffix: bytes = b"") -> tuple[int, int, int] | None:
    if prefix and not key.startswith(prefix):
        return None
    if suffix and not key.endswith(suffix):
        return None
    end = len(key) - len(suffix) if suffix else len(key)
    raw = key[len(prefix) : end]
    if len(raw) == 8:
        return (*struct.unpack("<ii", raw), 0)
    if len(raw) == 12:
        return struct.unpack("<iii", raw)
    return None


@dataclass(frozen=True)
class ChunkReference:
    key: bytes
    x: int
    z: int
    dimension: int


@dataclass
class EntityRecord:
    id: str
    key: bytes
    value: bytes
    named_tag: nbt.NamedTag
    storage: str
    identifier: str | None
    unique_id: str | None
    legacy_index: int | None = None
    dimension: int | None = None
    references: list[ChunkReference] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tag(self) -> nbt.CompoundTag:
        return self.named_tag.tag

    @property
    def revision(self) -> str:
        return hashlib.sha256(self.value).hexdigest()


@dataclass
class EntityScan:
    records: dict[str, EntityRecord] = field(default_factory=dict)
    index_records: dict[bytes, bytes] = field(default_factory=dict)
    village_records: dict[bytes, bytes] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    diagnostic_count: int = 0
    scanned_entities: int = 0
    scanned_records: int = 0
    legacy_records: int = 0

    def diagnose(self, diagnostic: dict[str, Any]) -> None:
        self.diagnostic_count += 1
        if len(self.diagnostics) < MAX_DIAGNOSTICS:
            self.diagnostics.append(diagnostic)


def _legacy_roots(value: bytes):
    for root in nbt.iter_bedrock_roots(value):
        checkpoint()
        if not isinstance(root.tag, nbt.CompoundTag):
            raise nbt.NBTError("Entity root must be a compound")
        yield root


def _storage_key_issue(tag: nbt.CompoundTag, suffix: bytes) -> dict[str, Any] | None:
    components = tag.get("internalComponents")
    if components is None:
        return None
    if not isinstance(components, nbt.CompoundTag):
        return issue("invalid_storage_key", "Der gespeicherte Actor-Speicherschlüssel ist nicht eindeutig lesbar.")
    component = components.get("EntityStorageKeyComponent")
    if component is None:
        return None
    storage_key = component.get("StorageKey") if isinstance(component, nbt.CompoundTag) else None
    if not isinstance(storage_key, nbt.StringTag):
        return issue("invalid_storage_key", "Der gespeicherte Actor-Speicherschlüssel ist nicht eindeutig lesbar.")
    if nbt.string_bytes(storage_key) != suffix:
        return issue("storage_key_mismatch", "Actor-Datensatz und gespeicherter Speicherschlüssel passen nicht zusammen.")
    return None


def _finalize_actor(record: EntityRecord, references: list[ChunkReference], bad_references: set[bytes]) -> None:
    suffix = record.key[len(ACTOR_PREFIX) :]
    record.references = list(references)
    if len(suffix) != 8:
        record.issues.append(issue("invalid_actor_key", "Der Actor-Datenbankschlüssel hat ein unbekanntes Format."))
    if suffix in bad_references:
        record.issues.append(issue("invalid_actor_index", "Ein Chunk-Index für diesen Bewohner ist beschädigt oder mehrdeutig."))
    if not references:
        record.issues.append(issue("orphan_actor", "Chunk-Zuordnung fehlt. Der gespeicherte Bewohner wird nur angezeigt und bleibt schreibgeschützt."))
    elif len(references) != 1:
        record.issues.append(issue("duplicate_actor_reference", "Der Actor-Datensatz ist mehrfach in Chunk-Indizes eingetragen."))
    dimensions = {reference.dimension for reference in references}
    if len(dimensions) == 1:
        record.dimension = next(iter(dimensions))
    elif dimensions:
        record.issues.append(issue("ambiguous_dimension", "Die gespeicherten Chunk-Indizes nennen unterschiedliche Dimensionen."))
    if storage_issue := _storage_key_issue(record.tag, suffix):
        record.issues.append(storage_issue)


def _finalize_identity(record: EntityRecord, unique_ids: dict[str, list[str]]) -> None:
    if not isinstance(record.tag.get("UniqueID"), nbt.LongTag):
        record.issues.append(issue("missing_unique_id", "Eine eindeutige gespeicherte UniqueID fehlt oder hat einen unbekannten Typ."))
    elif len(unique_ids[record.unique_id]) != 1:
        record.issues.append(issue("duplicate_unique_id", "Diese UniqueID kommt in mehreren gespeicherten Kreaturen vor."))
    if record.identifier is None:
        record.issues.append(issue("ambiguous_identifier", "Der Kreaturentyp konnte nicht eindeutig gelesen werden."))
    position = entity_position(record.tag)
    if position is None:
        record.issues.append(issue("invalid_position", "Die gespeicherte Position ist unvollständig oder ungültig."))
    elif record.references:
        chunk = (math.floor(position["x"] / 16), math.floor(position["z"] / 16))
        if any((reference.x, reference.z) != chunk for reference in record.references):
            record.issues.append(issue("position_index_mismatch", "Position und gespeicherter Chunk-Index passen nicht zusammen."))
    stored_dimensions = {scalar_integer(record.tag.get(key)) for key in ("DimensionId", "dimension_id", "dimension") if key in record.tag}
    if stored_dimensions and (None in stored_dimensions or len(stored_dimensions) != 1 or record.dimension not in stored_dimensions):
        record.issues.append(issue("dimension_mismatch", "Dimension im Kreaturdatensatz und Chunk-Index passen nicht zusammen."))


def scan_entities(db: Any, *, identifiers: frozenset[str] | None = None) -> EntityScan:
    """Scan a single open database view, retaining only requested entity types.

    All actor identities are checked, including creatures outside the filter,
    so a duplicated UniqueID cannot hide behind the villager-only view. The
    caller supplies the world lock, read consistency checks and DB lifetime.
    """
    result = EntityScan()
    references: dict[bytes, list[ChunkReference]] = defaultdict(list)
    bad_references: set[bytes] = set()
    actor_suffixes: set[bytes] = set()
    unique_ids: dict[str, list[str]] = defaultdict(list)
    seen_keys: set[bytes] = set()
    reference_count = 0
    identifier_bytes = tuple(identifier.encode("utf-8") for identifier in identifiers or ())
    identity_fields = frozenset((*_IDENTIFIER_FIELDS, "UniqueID"))
    checkpoint("entities", current=0)

    def add_root(key: bytes, value: bytes, root: nbt.NamedTag, storage: str, index: int | None = None, chunk=None) -> None:
        result.scanned_entities += 1
        if result.scanned_entities > MAX_ENTITY_RECORDS:
            raise ValueError(t("Die Welt enthält zu viele Kreaturdatensätze für einen vollständigen Scan. Es wurde keine unvollständige Liste übernommen."))
        tag = root.tag
        if not isinstance(tag, nbt.CompoundTag):
            raise nbt.NBTError("Entity root must be a compound")
        identifier = entity_identifier(tag)
        unique_value = scalar_integer(tag.get("UniqueID"))
        unique_id = str(unique_value) if unique_value is not None else None
        record_id = entity_id(key, index)
        if unique_id is not None:
            unique_ids[unique_id].append(record_id)
        # Conflicting identifier fields still surface when any of them names a
        # requested type; they are never silently turned into a different mob.
        possible = {str(tag[field].py_data) for field in _IDENTIFIER_FIELDS if isinstance(tag.get(field), nbt.StringTag)}
        if identifiers is not None and not possible.intersection(identifiers):
            return
        record = EntityRecord(record_id, key, value, root, storage, identifier, unique_id, legacy_index=index)
        if chunk is not None:
            record.dimension = chunk[2]
            record.references = [ChunkReference(key, *chunk)]
        if storage == "legacy":
            record.issues.append(issue("legacy_read_only", "Dieses ältere Chunk-Entity-Format wird vollständig gelesen, aber noch nicht verändert."))
        result.records[record_id] = record

    for key, value in db.iter_items():
        result.scanned_records += 1
        if result.scanned_records % 128 == 0:
            checkpoint(current=result.scanned_records)
        if not isinstance(key, bytes) or not isinstance(value, bytes):
            raise ValueError(t("Die Welt-Datenbank liefert einen unbekannten Datensatztyp."))
        is_actor = key.startswith(ACTOR_PREFIX)
        is_index = key.startswith(DIGP_PREFIX)
        is_village = key.startswith(b"VILLAGE_") and key.endswith((b"_DWELLERS", b"_INFO"))
        legacy_chunk = _chunk_key(key, suffix=b"\x32") if len(key) in (9, 13) and key[-1] == LEGACY_ENTITY_TAG else None
        if not is_actor and not is_index and legacy_chunk is None and not is_village:
            continue
        if key in seen_keys:
            raise ValueError(t("Die Datenbank enthält mehrdeutige doppelte Datensätze. Der Scan wurde abgebrochen."))
        seen_keys.add(key)
        if is_village:
            result.village_records[key] = value
            continue
        if is_index:
            result.index_records[key] = value
            chunk = _chunk_key(key, prefix=DIGP_PREFIX)
            malformed = chunk is None or len(value) % 8 != 0
            if malformed:
                result.diagnose(issue("invalid_actor_index", "Ein Chunk-Index ist beschädigt oder hat ein unbekanntes Format.", record=key.hex()))
            for offset in range(0, len(value) - 7, 8):
                reference_count += 1
                if reference_count > MAX_INDEX_REFERENCES:
                    raise ValueError(t("Die Welt enthält zu viele Actor-Referenzen für einen vollständigen Scan."))
                suffix = value[offset : offset + 8]
                if malformed:
                    bad_references.add(suffix)
                if chunk is not None:
                    references[suffix].append(ChunkReference(key, *chunk))
            continue
        if is_actor:
            actor_suffixes.add(key[len(ACTOR_PREFIX) :])
            try:
                # The byte prefilter only chooses allocation cost. Membership
                # and global duplicate IDs still come from fully validated NBT.
                project = identifiers is not None and not any(marker in value for marker in identifier_bytes)
                root = nbt.load(value, root_fields=identity_fields if project else None, **LOAD_KWARGS)
                if (
                    project
                    and isinstance(root.tag, nbt.CompoundTag)
                    and any(isinstance(root.tag.get(field), nbt.StringTag) and root.tag[field].py_data in identifiers for field in _IDENTIFIER_FIELDS)
                ):
                    root = nbt.load(value, **LOAD_KWARGS)
                add_root(key, value, root, "actor")
            except (nbt.NBTError, TypeError, OverflowError):
                result.diagnose(issue("unreadable_actor", "Ein gespeicherter Kreaturdatensatz konnte nicht gelesen werden.", record=key.hex()))
            continue
        result.legacy_records += 1
        try:
            for index, root in enumerate(_legacy_roots(value)):
                add_root(key, value, root, "legacy", index, legacy_chunk)
        except (nbt.NBTError, TypeError, OverflowError):
            result.diagnose(
                issue("unreadable_legacy_entities", "Ein älterer Chunk-Entity-Datensatz konnte nicht vollständig gelesen werden.", record=key.hex())
            )

    for suffix in references:
        checkpoint()
        if suffix not in actor_suffixes:
            result.diagnose(issue("missing_actor", "Ein Chunk-Index verweist auf einen fehlenden Kreaturdatensatz.", actor=suffix.hex()))
    for record in result.records.values():
        checkpoint()
        if record.storage == "actor":
            _finalize_actor(record, references.get(record.key[len(ACTOR_PREFIX) :], []), bad_references)
        _finalize_identity(record, unique_ids)
        for diagnostic in record.issues:
            result.diagnose({**diagnostic, "id": record.id})
    return result
