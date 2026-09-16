Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.23

- The bundled item registry now includes the 105 additions from Bedrock 26.50. Incorrect default stack sizes for 142 older items, including boats, signs, minecarts, entity buckets, and shulker boxes, are corrected.
- Stack limits now require an explicit per-item value. The updater accepts both documented Mojang component forms and rejects invalid or conflicting values. Missing values no longer imply 64: new stacks are limited to 1, Max-Stack is disabled, and existing amounts remain preserved unchanged. Unverified limits are visible in the editor and update log; this includes the new 26.50 items whose public definitions omit their limits.
- Automatic, manual, and pre-restore backups now share source-consistency checks. World metadata must remain unchanged through ZIP creation, verification, synchronization, and publication. A detected change aborts the backup and any dependent write or restore.
- The source is checked before the ZIP receives its regular backup filename, so a detected mixed archive cannot become visible if the process stops or cleanup fails. A final check also catches changes during publication. Failed cleanup of a published backup remains visible in the error response.
- Completed ZIPs are explicitly synchronized to storage before publication, including the hard-link path. The copy fallback also synchronizes its target; directory entries are synchronized where supported. Actual synchronization errors stop dependent writes, and a later close error cannot hide the original failure.
- Strict type checking now covers the backup adapter, shared consistency checks, settings, result contracts, and immutable write plans. Saves, workspace batches, mount creation, imports, and migration explicitly distinguish attempted writes from confirmed commits. Regression tests cover source changes, interrupted publication, synchronization failures, and backup retention after failed writes.

Backups continue to contain the complete world. Configured size limits and retention policies are unchanged. Metadata checks do not create an atomic snapshot of a running world; directory synchronization is unavailable on Windows and some filesystems, so these changes do not guarantee protection against every power loss.

**Updating from v0.5.22:** this release adds no dependencies. Python 3.12–3.14 remain supported. **If upgrading from v0.5.21 or earlier:** run `setup.bat` once before `start.bat` to install the hash-pinned Waitress dependency introduced in v0.5.22. Flask and Werkzeug remain required.

> **If upgrading directly from v0.5.18 or earlier:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the resolver corrected in v0.5.19. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
