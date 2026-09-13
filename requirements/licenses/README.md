# Windows LevelDB wheel notices

The wheel builder copies the Amulet Team License 1.0.0 and required notice
directly from `LICENSE` in the hash-locked Amulet-LevelDB 1.0.6 source archive.
It extracts the zlib notice from that archive's `zlib/zlib.h` header.

`leveldb.txt` is the LevelDB BSD license from the upstream
[Amulet-Team/leveldb-mcpe LICENSE](https://github.com/Amulet-Team/leveldb-mcpe/blob/master/LICENSE),
retrieved on 2026-09-13. The Amulet-LevelDB source archive contains the LevelDB
source headers referring to this license, but omits that separate license file.
Keep this reviewed copy alongside the build tooling and recheck it on an
upstream version change.

All three notices are distributed beside each Windows wheel and hashed in its
provenance manifest. The upstream archive's precompiled Windows zlib library
is disclosed in the same manifest. Building a wheel does not change any of
the upstream license terms.
