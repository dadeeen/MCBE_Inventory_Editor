# Fixture worlds

This folder is only a local safety marker, not a second user manual.

Place local example worlds containing real players, XUIDs, inventories, or other personal Minecraft data exclusively under `fixtures/private/`. That folder is ignored by Git, excluded from Docker builds, and rejected by release checks.

Public, non-playable scanner fixtures belong in `tests/fixtures/` and are created like this:

```bash
python scripts/fixture_world.py make-scanner-fixture --world-zip /path/to/Sample-World.zip --output tests/fixtures/public_scanner_world.zip
```

The scanner fixture removes the original LevelDB files and binary world metadata such as `level.dat`. It is not playable and is intended only for scanner, ZIP hygiene, and restore preview tests.

The full workflow is described in [docs/development.md](../docs/development.md) under "Test fixtures and private worlds". The security and privacy reasons are in [SECURITY.md](../SECURITY.md).
