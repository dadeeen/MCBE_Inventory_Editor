Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.24

- **Preserved player data:** fixes cases where editing inventory, effects or abilities could overwrite protected or unchanged NBT. Hidden root equipment, unknown durability and bucket-variant fields, and protected enchantment entries retain their original data.
- **Reliable copying and player changes:** cross-player copies now work with root equipment, including sources without an Inventory tag. Diagnostic player selection asks before discarding edits; loading blocks new edits and restores the correct field protection and undo/redo state afterward. Save and import completions remain bound to their original player context.
- **Corrected read-only LevelDB reader:** selects the newest matching record across table boundaries and consistently rejects unsupported SST entry types. The external native `amulet-leveldb` dependency is unchanged.
- **Safer backup restore:** changes to the target world after the safety backup abort the restore before replacement. Invalid ZIP metadata no longer blocks backup listing or retention.
- **Mount creation checks:** tamed mounts require a valid player owner in both direct and workspace saves. Known obstructions remain blocked when neighboring terrain is unreadable or a placement search changes candidate IDs.

Validation includes the complete Python suite, 38 Chromium browser tests, native LevelDB save/backup regressions and six integration tests using disposable copies of twelve private worlds. Those integration tests cover save, restore, import/export, migration and byte-identical NBT backend comparisons. No new in-game validation was performed for these changes. See the [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.24/docs/save_contract.md) and [engine-check scope](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.24/docs/engine-checks.md) for validation boundaries.

Backups continue to contain the complete world. Configured size limits and retention policies are unchanged. Metadata checks do not create an atomic snapshot of a running world; directory synchronization is unavailable on Windows and some filesystems, so these changes do not guarantee protection against every power loss.

This release adds no dependencies. Python 3.12–3.14 remain supported. **If upgrading from v0.5.21 or earlier:** run `setup.bat` once before `start.bat` to install the hash-pinned Waitress dependency introduced in v0.5.22. Flask and Werkzeug remain required.

> **If upgrading directly from v0.5.18 or earlier:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the resolver corrected in v0.5.19. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
