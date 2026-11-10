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
from .world_locks import lock_key

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

    def result(self) -> dict:
        return {**json.loads(self.metadata), "villagers": [json.loads(resident.row) for resident in self.residents.values()]}


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
        self._scans = OrderedDict()
        self._bytes = 0
        self._guard = threading.Lock()

    def snapshot(self, db) -> _Snapshot:
        token_of = getattr(db, "content_token", None)
        try:
            token = token_of() if callable(token_of) else None
        except OSError:
            LOGGER.warning("Villager cache token unavailable; reading without cache.", exc_info=True)
            token = None
        key = (token, request_locale()) if token is not None else None
        with self._guard:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                checkpoint("cached")
                return cached

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
                    self._bytes -= previous.size
                self._entries[key] = snapshot
                self._bytes += size
                while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                    evicted, old = self._entries.popitem(last=False)
                    self._bytes -= old.size
                    for scan_key in [scan_key for scan_key, entry_key in self._scans.items() if entry_key == evicted]:
                        del self._scans[scan_key]
        return snapshot

    def scan(self, db) -> dict:
        return self.snapshot(db).result()

    def remember_scan(self, world_path: str, revision: str, snapshot: _Snapshot) -> None:
        """Expose a retained snapshot only after the world read has been validated."""
        scan_key = (lock_key(world_path), revision, request_locale())
        with self._guard:
            key = next((key for key, entry in self._entries.items() if entry is snapshot), None)
            if key is None:
                return
            self._scans[scan_key] = key
            self._scans.move_to_end(scan_key)
            while len(self._scans) > self._max_entries:
                self._scans.popitem(last=False)

    def scanned_detail(self, world_path: str, world_revision: str, identifier: str, revision: str) -> dict | None:
        scan_key = (lock_key(world_path), world_revision, request_locale())
        with self._guard:
            key = self._scans.get(scan_key)
            snapshot = self._entries.get(key)
            if snapshot is None:
                return None
            self._entries.move_to_end(key)
            self._scans.move_to_end(scan_key)
        checkpoint("cached")
        return self._detail(snapshot, identifier, revision)

    def detail(self, db, identifier: str, revision: str) -> dict:
        return self._detail(self.snapshot(db), identifier, revision)

    @staticmethod
    def _detail(snapshot: _Snapshot, identifier: str, revision: str) -> dict:
        resident = snapshot.residents.get(identifier)
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
