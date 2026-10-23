"""Disposable, non-playable browser fixture and independent disk inspection.

Only generated NBT is used. There are no chunks, level.dat or account records.
This helper is run outside the web server so assertions read actual disk bytes.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter
from mcbe_editor.leveldb_writer import LevelDbWriter


def create_world(world: Path) -> None:
    (world / "db").mkdir(parents=True, exist_ok=False)
    (world / "levelname.txt").write_text("Synthetic Browser World", encoding="utf-8")
    item = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(0)})
    player = save_player_nbt(
        nbt.NamedTag(
            nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag([item], 10),
                    "PlayerGameType": nbt.IntTag(0),
                    "XPLevel": nbt.IntTag(17),
                    "Health": nbt.FloatTag(20),
                    "Pos": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(64), nbt.FloatTag(0)], 5),
                    "SyntheticPreserved": nbt.StringTag("preserve-me"),
                }
            )
        )
    )
    writer = LevelDbWriter(str(world / "db"))
    try:
        writer.put_batch({b"~local_player": player, b"synthetic-unrelated": b"preserve-unrelated-record"})
    finally:
        writer.close()


def inspect(root: Path) -> dict:
    world = root / "worlds" / "SyntheticBrowserWorld"
    reader = ReadonlyLevelDbAdapter(str(world / "db"))
    try:
        values = dict(reader.iter_items())
    finally:
        reader.close()
    player = load_player_nbt(values[b"~local_player"]).tag
    backups = {}
    for archive in sorted((root / "backups").rglob("*.zip")):
        with zipfile.ZipFile(archive) as zipped:
            if zipped.testzip() is not None:
                raise AssertionError("Corrupt backup archive")
            backups[archive.name] = {name: hashlib.sha256(zipped.read(name)).hexdigest() for name in zipped.namelist() if not name.endswith("/")}
    return {
        "records": {key.hex(): value.hex() for key, value in sorted(values.items())},
        "files": {
            str(path.relative_to(world)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in world.rglob("*") if path.is_file()
        },
        "count": int(player["Inventory"][0]["Count"].py_data),
        "preserved": str(player["SyntheticPreserved"].py_data),
        "backups": backups,
    }


if __name__ == "__main__":
    print(json.dumps(inspect(Path(sys.argv[1]))))
