# Test Fixtures

Small synthetic fixtures and reviewed, non-playable reference data may live here. Private Bedrock worlds do not belong in this directory.

`public_scanner_world.zip` is a generated scanner fixture without the original LevelDB files. Review generated files before committing them. Isolated entity NBT records have a separate [fixture contract](../data/README.md) under `tests/data/`.

`mount_reference.json` contains manually reviewed, distilled mount evidence. The exporter omits known custom-name tags and records known coordinate and identity tags by name only. Matching observed values become comparison candidates; single-specimen values remain in an unconfirmed section. This process does not provide general anonymization: unknown scalar values, definitions, attribute names, tag names and the supplied label can contain world-specific or user-authored content. Review the complete output before sharing or committing it, and remove names, XUIDs, account/server/device identifiers, local paths and any other personal or private data. Keep unreviewed exports under `fixtures/private/`.

Private worlds belong under `fixtures/private/`; that folder is ignored locally and excluded from releases.

The fixture workflow is described in [docs/development.md](../../docs/development.md) under "Test fixtures and private worlds". The security and privacy reasons are in [SECURITY.md](../../SECURITY.md).
