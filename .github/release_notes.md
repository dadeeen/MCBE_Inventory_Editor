Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.30

- **Walking speed that takes effect:** the previous walking speed field edited `walkSpeed` in the player's abilities. In Bedrock that value only sets the field of view: a higher value zoomed the view, but the player did not walk faster. The new **Walking speed** field edits the `minecraft:movement` attribute, which Bedrock uses for the actual speed; sprinting still adds to it. It also sets `walkSpeed` to the same value, so the field of view stays normal. `walkSpeed` remains available as **Walking field of view**, with a note on what it does. The walking speed is read-only while the attribute is missing, carries modifiers (for example from sprinting or an effect at the moment the world was saved) or has an unexpected structure; the reason is shown below the fields.
- **Vertical flying speed:** a new field edits `verticalFlySpeed` (0–20, vanilla 1), the speed of climbing and descending while flying. The flying speed field (`flySpeed`) is labelled as horizontal flight. Player migration copies `verticalFlySpeed` together with the other speeds.
- **Checkboxes without effect are gone:** Minecraft recalculates flying, floating, invulnerability, instant block breaking and build permission from the game mode and the player permission level when a player loads, so edits to these checkboxes were lost in the game. The "Place blocks" checkbox also wrote the Java tag name `mayBuild`, which Bedrock ignores and removes on its next save. The editor no longer shows or writes these values; change them through the game mode and player permissions in Minecraft. Values already stored in a world stay untouched.

Validation includes the complete Python suite, the browser tests, byte-for-byte comparisons of the new speed writes against an independent NBT implementation on synthetic data and on copies of real worlds, and in-game checks with the Minecraft client 1.26.52 on Windows: walking speed with and without sprinting, horizontal and vertical flying speed, and flying, instant block breaking and build permission following the game mode. See the [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.30/docs/save_contract.md) for validation boundaries.

> **If upgrading directly from v0.5.25 or earlier:** since v0.5.26 the server check also detects running NetherNet servers (`transport=nethernet`). For that, the editor needs TCP access to the server port (`MCBE_SERVER_PORT`, usually 19132). In Docker, publish it as `19132/tcp` or run the editor in the server's Docker network; otherwise the status stays unknown and saving asks for confirmation. See [Docker and trusted LANs](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.30/README.md#docker-and-trusted-lans).

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
