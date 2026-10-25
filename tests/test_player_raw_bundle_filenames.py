"""Automatically named diagnostic bundles work with Unicode world titles."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import save_player_nbt
from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.world import LOCAL_PLAYER_KEY
from scripts.export_player_raws import export_players
from tests.nbt_fixtures import make_minimal_player_tag


@pytest.mark.parametrize("world_name", ["\U00010400" * 64, "界" * 64, "Welt ü"])
def test_auto_bundle_with_unicode_title_preserves_exported_player(tmp_path, world_name):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text(world_name, encoding="utf-8")
    original = save_player_nbt(nbt.NamedTag(make_minimal_player_tag()))
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put(LOCAL_PLAYER_KEY, original)
    finally:
        db.close()

    output = tmp_path / "exports"
    result = export_players(
        str(world),
        export_all=True,
        player_keys=None,
        output_dir=str(output),
        bundle_zip="auto",
        editable_only=False,
        include_private_paths=False,
    )
    assert result["success"] is True
    bundle = output / result["bundle_zip"]
    assert len(bundle.name.encode("utf-8")) <= 255
    with zipfile.ZipFile(bundle) as archive:
        index = json.loads(archive.read("index.json"))
        assert index["world"]["name"] == world_name
        assert index["export_count"] == 1
        member = "players/" + Path(index["exports"][0]["export_file"]).name
        with zipfile.ZipFile(io.BytesIO(archive.read(member))) as player_archive:
            assert player_archive.read("player.nbt") == original
