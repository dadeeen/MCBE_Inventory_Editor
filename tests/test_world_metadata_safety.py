"""World discovery treats names and timestamps as optional display metadata."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcbe_editor.world import get_world_name, scan_minecraft_worlds_with_meta


def _world(tmp_path):
    root = tmp_path / "worlds"
    world = root / "SavedWorld"
    (world / "db").mkdir(parents=True)
    return root, world


def _names(root, world):
    worlds = scan_minecraft_worlds_with_meta(paths=[str(root)])["worlds"]
    assert len(worlds) == 1
    return get_world_name(str(world)), worlds[0]["name"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  Grünes Dorf 🏡\r\n".encode(), "Grünes Dorf 🏡"),
        (b"Readable\xff name", "Readable name"),
        (b" \r\n\t", "SavedWorld"),
        (b"A" * 4096, "A" * 4096),
    ],
    ids=["unicode", "invalid-utf8", "blank", "size-limit"],
)
def test_regular_names_keep_utf8_whitespace_and_existing_decode_behavior(tmp_path, raw, expected):
    root, world = _world(tmp_path)
    (world / "levelname.txt").write_bytes(raw)
    assert _names(root, world) == (expected, expected)


def test_world_names_never_follow_a_file_link_outside_the_scan_root(tmp_path):
    root, world = _world(tmp_path)
    outside = tmp_path / "unrelated.txt"
    outside.write_text("Unrelated private fixture content", encoding="utf-8")
    try:
        (world / "levelname.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("File symlinks require Windows developer mode or privileges")
    assert _names(root, world) == ("SavedWorld", "SavedWorld")


@pytest.mark.parametrize("raw", [b"X" * 4097, ("Dorf 🏡" * 2000).encode()], ids=["over-limit", "multibyte"])
def test_oversized_names_fall_back_without_returning_a_partial_or_huge_label(tmp_path, raw):
    root, world = _world(tmp_path)
    (world / "levelname.txt").write_bytes(raw)
    assert _names(root, world) == ("SavedWorld", "SavedWorld")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes are a POSIX filesystem case")
def test_fifo_name_cannot_block_discovery_or_direct_world_name_reads(tmp_path):
    root, world = _world(tmp_path)
    os.mkfifo(world / "levelname.txt")
    # A subprocess makes a regression fail instead of hanging the test runner.
    code = "\n".join(
        (
            "import json, sys",
            "from mcbe_editor.world import get_world_name, scan_minecraft_worlds_with_meta",
            "worlds = scan_minecraft_worlds_with_meta(paths=[sys.argv[1]])['worlds']",
            "print(json.dumps([worlds[0]['name'], get_world_name(sys.argv[2])]))",
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(root), str(world)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert json.loads(result.stdout) == ["SavedWorld", "SavedWorld"]


def test_a_name_that_grows_after_the_initial_stat_is_still_bounded(tmp_path, monkeypatch):
    root, world = _world(tmp_path)
    name_path = world / "levelname.txt"
    name_path.write_text("Original name", encoding="utf-8")
    original_stat = Path.lstat

    def grow_after_stat(path):
        info = original_stat(path)
        if path == name_path:
            name_path.write_bytes(b"X" * 8192)
        return info

    monkeypatch.setattr(Path, "lstat", grow_after_stat)
    assert _names(root, world) == ("SavedWorld", "SavedWorld")


@pytest.mark.parametrize("timestamp", [-62135596801, 253402300800, 1e20])
def test_unrepresentable_directory_date_does_not_hide_the_world(tmp_path, monkeypatch, timestamp):
    root, world = _world(tmp_path)
    original_stat = Path.stat

    def unusual_timestamp(path, *args, **kwargs):
        info = original_stat(path, *args, **kwargs)
        if path == world:
            fields = list(info)
            fields[8] = timestamp
            return os.stat_result(fields)
        return info

    # This filesystem clamps extreme mtimes, so inject only the platform stat
    # result. The real datetime conversion must fail without aborting discovery.
    monkeypatch.setattr(Path, "stat", unusual_timestamp)
    result = scan_minecraft_worlds_with_meta(paths=[str(root)])
    assert len(result["worlds"]) == 1
    assert result["worlds"][0]["name"] == "SavedWorld"
    assert result["worlds"][0]["modified_iso"] == ""
    assert result["worlds"][0]["modified_ts"] is None
