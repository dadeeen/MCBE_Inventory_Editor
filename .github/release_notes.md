Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.25

- **Download progress for item data and icons:** the setup and update dialogs show real percentages and downloaded megabytes, followed by separate verification, processing and finishing stages. "Done" appears only after processing succeeds. Updates continue if progress reporting is unavailable.
- **Recovery for interrupted restores:** a new operator command recovers restores that were interrupted while the server status was unknown. Recovery requires explicit confirmation that the server is stopped; a detected online server, read-only mode and ambiguous world copies remain blocked. Interrupted restores are now also found when the configured world folder is temporarily missing. See the [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.25/README.md#data-safety-and-privacy) for usage.
- **Safer backups and restores:** symlinks, Windows junctions and other reparse points in worlds are rejected instead of being silently omitted from backups. Restores reject unsafe ZIP member names and filenames that collide on Windows, including 8.3 short names, before the world is replaced.
- **Setup and login hardening:** first-run setup decisions are atomic across concurrent requests, and access stays locked if saving the setup decision fails. An empty `--host` no longer binds to all network interfaces; startup safety checks apply to the effective host. Login and setup pages stay alive and are no longer cached.
- **Import and mount checks:** player import archives are limited to 64 MiB, abandoned import copies are cleaned up after one day, and invalid item source slots are rejected instead of silently replaced. Direct mount creation is bound to the player state shown in the preview and aborts if that player changed in the meantime.
- **Icon discovery:** an unreadable resource-pack subdirectory no longer stops scanning the remaining icon source.

Validation includes the complete Python suite, 38 Chromium browser tests, native Windows junction and 8.3 short-name regressions, restore-recovery integration tests and five integration tests using disposable copies of private worlds. Those integration tests cover scanning, save, backup restore, import/export and player transfer. The NBT codec is unchanged in this release; the byte-identical NBT backend comparison on private worlds was not repeated. No new in-game validation was performed for these changes. See the [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.25/docs/save_contract.md) and [engine-check scope](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.25/docs/engine-checks.md) for validation boundaries.

> **Worlds behind symlinks or junctions:** world folders and their contents must be ordinary directories and files. If a world or its `db` folder is reached through a symlink or Windows junction, move or copy it to a regular folder before upgrading.

> **Multiple server processes:** first-run setup and session signing keys are kept per process. Complete setup with a single process, then restart all processes. The bundled Docker configuration uses one process and is unaffected.

Backups continue to contain the complete world. Configured size limits and retention policies are unchanged.

This release adds no dependencies. Python 3.12–3.14 remain supported. **If upgrading from v0.5.21 or earlier:** run `setup.bat` once before `start.bat` to install the hash-pinned Waitress dependency introduced in v0.5.22. Flask and Werkzeug remain required.

> **If upgrading directly from v0.5.18 or earlier:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the resolver corrected in v0.5.19. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
