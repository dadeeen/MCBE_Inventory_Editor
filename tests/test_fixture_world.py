from __future__ import annotations

import zipfile
from pathlib import Path

from scripts.fixture_world import inspect_world_zip, make_private_metadata_copy, make_scanner_fixture


def _write_sample_world_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("abc123=/levelname.txt", "Sample Private World\n")
        zf.writestr("abc123=/level.dat", b"leveldat")
        zf.writestr("abc123=/level.dat_old", b"leveldat_old")
        zf.writestr("abc123=/db/000003.log", b"hello ~local_player player_123 minecraft:player")
        zf.writestr("abc123=/db/CURRENT", b"CURRENT")
        zf.writestr("abc123=/world_icon.jpeg", b"not really jpeg")


def test_fixture_inspect_redacts_levelname_by_default(tmp_path: Path):
    world_zip = tmp_path / "Sample-World.zip"
    _write_sample_world_zip(world_zip)

    report = inspect_world_zip(world_zip)

    assert report["format"] == "mcbe-private-world-fixture-report"
    assert report["zip"]["common_root"] == "abc123="
    assert report["world_shape"]["has_db_dir"] is True
    assert report["privacy"]["contains_player_markers"] is True
    assert report["privacy"]["safe_to_commit"] is False
    assert "text" not in report["levelname"]


def test_make_scanner_fixture_drops_private_leveldb(tmp_path: Path):
    world_zip = tmp_path / "Sample-World.zip"
    output_zip = tmp_path / "public_scanner_world.zip"
    _write_sample_world_zip(world_zip)

    result = make_scanner_fixture(world_zip, output_zip, level_name="Public Fixture")

    assert result["safe_to_commit"] is True
    assert result["dropped_leveldb_files"] == 2
    with zipfile.ZipFile(output_zip) as zf:
        names = set(zf.namelist())
        assert "public_scanner_fixture/levelname.txt" in names
        assert "public_scanner_fixture/db/.placeholder" in names
        assert "public_scanner_fixture/PUBLIC_SCANNER_FIXTURE.txt" in names
        assert "public_scanner_fixture/db/000003.log" not in names
        assert "public_scanner_fixture/level.dat" not in names
        assert "public_scanner_fixture/level.dat_old" not in names
        assert zf.read("public_scanner_fixture/levelname.txt") == b"Public Fixture\n"


def test_make_private_metadata_copy_warns_not_safe_to_commit(tmp_path: Path):
    world_zip = tmp_path / "Sample-World.zip"
    output_zip = tmp_path / "private_copy.zip"
    _write_sample_world_zip(world_zip)

    result = make_private_metadata_copy(world_zip, output_zip, level_name="Private Fixture", strip_icon=True)

    assert result["safe_to_commit"] is False
    with zipfile.ZipFile(output_zip) as zf:
        names = set(zf.namelist())
        assert "private_fixture_world/levelname.txt" in names
        assert "private_fixture_world/db/000003.log" in names
        assert "private_fixture_world/world_icon.jpeg" not in names
        assert "private_fixture_world/SANITIZATION_NOTICE.txt" in names


def test_public_scanner_fixture_inspects_safe_to_commit(tmp_path: Path):
    world_zip = tmp_path / "Sample-World.zip"
    output_zip = tmp_path / "public_scanner_world.zip"
    _write_sample_world_zip(world_zip)
    make_scanner_fixture(world_zip, output_zip, level_name="Public Fixture")

    report = inspect_world_zip(output_zip)

    assert report["world_shape"]["public_scanner_fixture"] is True
    assert report["privacy"]["contains_leveldb"] is False
    assert report["privacy"]["contains_player_markers"] is False
    assert report["privacy"]["safe_to_commit"] is True
    assert "Public scanner fixture" in report["privacy"]["recommendation"]
