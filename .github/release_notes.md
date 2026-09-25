Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.26

- **Running NetherNet servers block writes again:** servers with `transport=nethernet`, the value in the `server.properties` template of current Bedrock server releases, do not answer the RakNet ping that the server check used. Such a running server was reported as "status unknown", so saving only asked for confirmation instead of being blocked. The check now also asks the server port over TCP (`GET /v1/join`) and reports a running NetherNet server as reachable. RakNet servers, including existing `server.properties` files without a `transport` line, are detected as before. A reverse proxy answering for a stopped server is not taken for a running one.

Validation includes the complete Python suite and manual checks against Bedrock Dedicated Server 1.26.51.1 in Docker: a running NetherNet or RakNet server blocks writes, and a stopped server still requires confirmation. No new in-game validation was performed for these changes. See the [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.26/docs/save_contract.md) and [engine-check scope](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.26/docs/engine-checks.md) for validation boundaries.

> **NetherNet servers:** the editor needs TCP access to the server port (`MCBE_SERVER_PORT`, usually 19132). In Docker, publish it as `19132/tcp` or run the editor in the server's Docker network; otherwise the status stays unknown and saving asks for confirmation as before. See [Docker and trusted LANs](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.26/README.md#docker-and-trusted-lans).

> **If upgrading directly from v0.5.24 or earlier:** the world folder, its `db` folder and everything inside the world must be ordinary directories and files. Since v0.5.25, backups, and therefore saves, stop at symlinks, Windows junctions and other reparse points. Before editing, replace such links with regular copies, for example resource or behavior packs linked into a world. First-run setup and session signing keys are kept per process: complete setup with a single process, then restart all processes. The bundled Docker configuration uses one process and is unaffected.

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
