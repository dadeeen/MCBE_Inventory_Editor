from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.fixture_world import FixtureWorldError, inspect_world_zip, main, make_private_metadata_copy, make_scanner_fixture


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


def _file_alias(source: Path, destination: Path, alias: str) -> Path:
    if alias == "same_path":
        return source
    try:
        if alias == "symlink":
            destination.symlink_to(source)
        else:
            destination.hardlink_to(source)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Filesystem does not support {alias}: {exc}")
    return destination


@pytest.mark.parametrize("maker", [make_scanner_fixture, make_private_metadata_copy])
@pytest.mark.parametrize("alias", ["same_path", "symlink", "hardlink"])
def test_fixture_copy_rejects_source_as_destination_without_changing_it(tmp_path: Path, maker, alias: str):
    source = tmp_path / "source.zip"
    _write_sample_world_zip(source)
    before = source.read_bytes()
    destination = _file_alias(source, tmp_path / "alias.zip", alias)

    try:
        with pytest.raises(FixtureWorldError, match="different files"):
            maker(source, destination)
    finally:
        assert source.read_bytes() == before


@pytest.mark.parametrize("alias", ["same_path", "symlink", "hardlink"])
def test_inspect_rejects_source_as_report(tmp_path: Path, capsys, alias: str):
    source = tmp_path / "source.zip"
    _write_sample_world_zip(source)
    before = source.read_bytes()
    report = _file_alias(source, tmp_path / "report.json", alias)

    assert main(["inspect", "--world-zip", str(source), "--output", str(report)]) == 2
    assert "different files" in capsys.readouterr().err
    assert source.read_bytes() == before


@pytest.mark.parametrize("command", ["make-scanner-fixture", "make-private-metadata-copy"])
@pytest.mark.parametrize("report_target", ["source", "destination"])
@pytest.mark.parametrize("alias", ["same_path", "symlink", "hardlink"])
def test_copy_rejects_conflicting_report_before_writing_any_file(tmp_path: Path, capsys, command: str, report_target: str, alias: str):
    source = tmp_path / "source.zip"
    destination = tmp_path / "destination.zip"
    _write_sample_world_zip(source)
    destination.write_bytes(b"Existing destination must survive rejected arguments")
    before = {path: path.read_bytes() for path in (source, destination)}
    target = source if report_target == "source" else destination
    report = _file_alias(target, tmp_path / "report.json", alias)

    assert main([command, "--world-zip", str(source), "--output", str(destination), "--report-output", str(report)]) == 2
    assert "different files" in capsys.readouterr().err
    for path, content in before.items():
        assert path.read_bytes() == content


@pytest.mark.parametrize("command", ["make-scanner-fixture", "make-private-metadata-copy"])
def test_copy_rejects_shared_new_destination_and_report_before_creating_directory(tmp_path: Path, command: str):
    source = tmp_path / "source.zip"
    _write_sample_world_zip(source)
    before = source.read_bytes()
    destination = tmp_path / "new" / "output.zip"

    assert main([command, "--world-zip", str(source), "--output", str(destination), "--report-output", str(destination)]) == 2
    assert not destination.parent.exists()
    assert source.read_bytes() == before


@pytest.mark.parametrize("command", ["inspect", "make-scanner-fixture", "make-private-metadata-copy"])
def test_fixture_cli_writes_distinct_outputs_and_preserves_source(tmp_path: Path, command: str):
    source = tmp_path / "source.zip"
    destination = tmp_path / "output.zip"
    report = tmp_path / "report.json"
    _write_sample_world_zip(source)
    before = source.read_bytes()
    args = [command, "--world-zip", str(source)]
    if command == "inspect":
        args += ["--output", str(report)]
    else:
        args += ["--output", str(destination), "--report-output", str(report)]

    assert main(args) == 0
    assert source.read_bytes() == before
    result = json.loads(report.read_text(encoding="utf-8"))
    if command == "inspect":
        assert result["world_shape"]["has_db_dir"] is True
    else:
        assert zipfile.is_zipfile(destination)
        assert result["output"]["size"] == destination.stat().st_size
