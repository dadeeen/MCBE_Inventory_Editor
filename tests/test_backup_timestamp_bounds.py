"""ZIP timestamp limits must not prevent backing up otherwise valid worlds."""

import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mcbe_editor.backup import create_backup, safe_extract_zip
from mcbe_editor.backup_consistency import source_snapshot


@pytest.mark.parametrize("year, archived_year", [(1975, 1980), (2000, 2000), (2108, 2107)])
@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_backup_clamps_out_of_range_entry_times_without_changing_source(tmp_path, monkeypatch, year, archived_year, entry_kind):
    world = tmp_path / "world"
    db = world / "db"
    db.mkdir(parents=True)
    member = db / "CURRENT"
    content = b"MANIFEST-000001\n"
    member.write_bytes(content)
    timed_entry = member if entry_kind == "file" else db
    timestamp = datetime(year, 6, 15, tzinfo=UTC).timestamp()
    try:
        os.utime(timed_entry, (timestamp, timestamp))
    except (OSError, OverflowError) as exc:
        pytest.skip(f"Filesystem cannot represent test timestamp: {exc}")
    if abs(timed_entry.stat().st_mtime - timestamp) > 1:
        pytest.skip("Filesystem did not preserve test timestamp")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    before = source_snapshot(str(world))

    archive_path = create_backup(str(world), prune_after=False)

    assert source_snapshot(str(world)) == before
    with zipfile.ZipFile(archive_path) as archive:
        entry_name = "db/CURRENT" if entry_kind == "file" else "db/"
        assert archive.getinfo(entry_name).date_time[0] == archived_year
        assert archive.read("db/CURRENT") == content
        assert archive.testzip() is None
        restored = tmp_path / "restored"
        safe_extract_zip(archive, str(restored))
    assert (restored / "db" / "CURRENT").read_bytes() == content
    assert Path(archive_path).is_file()
