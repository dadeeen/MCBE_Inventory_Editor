"""Non-ASCII world names must not exceed filesystem filename limits."""

from pathlib import Path
import zipfile

import pytest

from mcbe_editor import backup


@pytest.mark.parametrize("kind", [backup.BACKUP_KIND_AUTOMATIC, backup.BACKUP_KIND_MANUAL, backup.BACKUP_KIND_PRE_RESTORE])
def test_long_unicode_world_name_can_be_backed_up_and_restored(tmp_path, monkeypatch, kind):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    original = b"original world data"
    (world / "db" / "data.bin").write_bytes(original)
    name = "界" * 80
    (world / "levelname.txt").write_text(name, encoding="utf-8")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))

    archive_path = Path(backup.create_backup(str(world), backup_kind=kind))

    assert len(archive_path.name.encode("utf-8")) <= backup.MAX_BACKUP_FILENAME_LENGTH
    assert archive_path.name.startswith("界")
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("levelname.txt").decode("utf-8") == name
        assert archive.read("db/data.bin") == original
    assert backup.preview_backup(str(world), archive_path.name)["backup"]["kind"] == kind

    (world / "db" / "data.bin").write_bytes(b"changed")
    backup.restore_backup(str(world), archive_path.name)
    assert (world / "db" / "data.bin").read_bytes() == original
    assert (world / "levelname.txt").read_text(encoding="utf-8") == name
