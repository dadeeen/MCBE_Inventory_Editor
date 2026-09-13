Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.21

- Python 3.12, 3.13 and 3.14 are supported. Windows x64 runtime packages include validated LevelDB wheels for 3.13/3.14, allowing setup without C++ Build Tools. Existing supported environments are retained.
- The editor uses a standard-library NBT codec, removing Amulet-NBT, NumPy and Amulet-MUTF8 from runtime requirements. The native Bedrock LevelDB engine remains in use. Preservation tests and an independent legacy-codec comparison cover player saves, mounts, transfers and export/import.
- Mount placement uses the actual stored Float32 coordinates consistently for terrain checks and chunk references. Template creation rejects unsuitable active or malformed state, and post-write checks verify position, ownership, links and equipment.
- The read-only database reader verifies SST checksums and rejects overflowing file references, varints and excessive decompression sizes. Terrain decoding and icon-context handling include additional format and consistency fixes.
- Save, import, restore and player-switch responses retain their original world/player context. Late responses and uncertain save results no longer incorrectly clear or overwrite a different editor view. Rollback rechecks the target before restoring it.
- Unknown inventory/effect data, legacy ability values, existing text and empty list types are preserved when unrelated fields are edited. Unicode CSRF tokens are rejected normally; foreign and stale drag payloads cannot rearrange inventory items.

> **If upgrading directly from v0.5.18 or earlier:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the resolver corrected in v0.5.19. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
