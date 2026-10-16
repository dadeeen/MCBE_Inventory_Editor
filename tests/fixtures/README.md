# Test Fixtures

Small synthetic fixtures and reviewed, non-playable reference data may live here. Private Bedrock worlds do not belong in this directory.

`public_scanner_world.zip` is a generated scanner fixture without the original LevelDB files. `mount_reference.json` contains distilled type-invariant mount evidence, with instance identifiers and custom names excluded. Review generated files before committing them. Isolated entity NBT records have a separate [fixture contract](../data/README.md) under `tests/data/`.

Private worlds belong under `fixtures/private/`; that folder is ignored locally and excluded from releases.

The fixture workflow is described in [docs/development.md](../../docs/development.md) under "Test fixtures and private worlds". The security and privacy reasons are in [SECURITY.md](../../SECURITY.md).
