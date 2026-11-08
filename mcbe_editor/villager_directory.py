"""Bounded read snapshots; write planning always uses fresh entity discovery."""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from itertools import islice

from . import nbt, villagers
from .bedrock_nbt import LOAD_KWARGS
from .entities import EntityRecord, _legacy_roots
from .i18n import request_locale, t
from .leveldb_readonly import WorldChangedWhileReadingError
from .read_operation import checkpoint

LOGGER = logging.getLogger(__name__)


def _encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


@dataclass(frozen=True)
class _Resident:
    key: bytes
    value: bytes
    legacy_index: int | None
    row: bytes


@dataclass(frozen=True)
class _Snapshot:
    metadata: bytes
    residents: dict[str, _Resident]
    size: int


class VillagerDirectory:
    """Keep raw resident bytes and JSON, never readers or mutable NBT trees.

    The LRU bounds worlds/locales, resident count and retained payload bytes.
    content_token binds each entry to the reader's actual metadata and tables;
    time-based expiry is not a substitute for validating that token.
    """

    def __init__(self, *, max_entries=8, max_bytes=32 * 1024 * 1024, max_residents=10_000):
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_residents = max_residents
        self._entries = OrderedDict()
        self._bytes = 0
        self._guard = threading.Lock()

    def _snapshot(self, db) -> _Snapshot:
        token_of = getattr(db, "content_token", None)
        try:
            token = token_of() if callable(token_of) else None
        except OSError:
            LOGGER.warning("Villager cache token unavailable; reading without cache.", exc_info=True)
            token = None
        key = (token[0], request_locale()) if token is not None else None
        with self._guard:
            cached = self._entries.get(key)
            if cached is not None:
                if cached[0] == token:
                    self._entries.move_to_end(key)
                    checkpoint("cached")
                    return cached[1]
                self._bytes -= self._entries.pop(key)[1].size

        scan, rows = villagers._scan(db)
        result = villagers.scan_result(scan, rows)
        del result["villagers"]
        metadata = _encode(result)
        residents = {
            identifier: _Resident(record.key, record.value, record.legacy_index, _encode(rows[identifier])) for identifier, record in scan.records.items()
        }
        size = len(metadata) + sum(len(row.key) + len(row.value) + len(row.row) + len(identifier) + 256 for identifier, row in residents.items())
        snapshot = _Snapshot(metadata, residents, size)
        if token is not None:
            try:
                if token_of() != token:
                    raise WorldChangedWhileReadingError(token[0])
            except OSError:
                token = None
        if token is not None and self._max_entries > 0 and size <= self._max_bytes and len(residents) <= self._max_residents:
            with self._guard:
                previous = self._entries.pop(key, None)
                if previous is not None:
                    self._bytes -= previous[1].size
                self._entries[key] = (token, snapshot)
                self._bytes += size
                while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                    self._bytes -= self._entries.popitem(last=False)[1][1].size
        return snapshot

    def scan(self, db) -> dict:
        snapshot = self._snapshot(db)
        return {**json.loads(snapshot.metadata), "villagers": [json.loads(resident.row) for resident in snapshot.residents.values()]}

    def detail(self, db, identifier: str, revision: str) -> dict:
        resident = self._snapshot(db).residents.get(identifier)
        if resident is None:
            raise ValueError(t("Der ausgewählte Dorfbewohner ist nicht mehr vorhanden. Bitte neu scannen."))
        row = json.loads(resident.row)
        if revision != row["revision"]:
            raise ValueError(t("Der Dorfbewohner wurde seit dem Scan verändert. Bitte neu scannen."))
        # Decode only this resident (or its root inside a legacy chunk). The
        # snapshot already contains the global identity and index evidence.
        root = (
            nbt.load(resident.value, **LOAD_KWARGS)
            if resident.legacy_index is None
            else next(islice(_legacy_roots(resident.value), resident.legacy_index, None))
        )
        record = EntityRecord(
            identifier,
            resident.key,
            resident.value,
            root,
            row["storage"],
            row["identifier"],
            row["unique_id"],
            legacy_index=resident.legacy_index,
            dimension=row["dimension"],
            issues=row["issues"],
        )
        return villagers._read_details(record, row)
