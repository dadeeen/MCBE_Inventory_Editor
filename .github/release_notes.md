Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.22

- The Backup Manager now offers an installation-wide limit for the uncompressed contents of each backup. The default remains 1 GiB; operators can override it with `MCBE_BACKUP_MAX_UNCOMPRESSED_MIB`. Backup retention is unchanged.
- Backup creation and restore use the same size limits and check estimated free disk space before creating ZIPs, restore snapshots or staging directories. Limit errors link directly to the backup settings.
- The read-only LevelDB reader can recover intact records before an incomplete or CRC-damaged final record in the newest WAL. Discarded tail data is logged; other database corruption remains an error.
- The local Windows launcher uses Waitress with persistent HTTP connections and four worker threads. Shutdown waits for active application work and releases blocked response transfers. Request limits preserve valid uploads at the boundary.
- Docker disables Gunicorn's unused control socket, avoiding attempts to create `/app/.gunicorn` on the read-only filesystem. CI verifies startup, HTTP health and graceful shutdown in a container with a read-only root before publication.

**Updating an existing local installation:** run `setup.bat` once before `start.bat` to install the new hash-pinned Waitress dependency. Flask and Werkzeug remain required. Python 3.12–3.14 remain supported.

> **If upgrading directly from v0.5.18 or earlier:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the resolver corrected in v0.5.19. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
