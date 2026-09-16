"""Data contracts for backup results and restore previews."""

from datetime import datetime
from typing import NewType, NotRequired, TypedDict

# Runtime-compatible with existing path consumers. Only a completed, verified
# and synchronized backup is returned with this type.
BackupPath = NewType("BackupPath", str)


class BackupDescriptor(TypedDict):
    filename: str
    path: str
    size_bytes: int
    mtime: float
    created_at: datetime | None
    sort_timestamp: float
    kind: str
    kind_label: str
    retention_class: str
    restore_source: str | None
    schema_version: int


class BackupListEntry(TypedDict):
    filename: str
    size_mb: float
    date: str
    created_at: str | None
    modified_at: str | None
    kind: str
    kind_label: str
    retention_class: str
    restore_source: str | None
    sort_timestamp: NotRequired[float]


class BackupCreateResult(TypedDict):
    success: bool
    backup_file: str


class RestoreToken(TypedDict):
    version: int
    world_id: str
    filename: str
    size_bytes: int
    sha256: str
