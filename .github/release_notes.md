Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.7.0

- **Three layouts:** Classic keeps the familiar interface and remains the default. Studio adds a grouped sidebar and persistent inspector; Focus offers a compact editing workspace. Layout, color theme and language are separate preferences saved in the browser. Switching layouts preserves pending edits.
- **Clearer, responsive controls:** world selection, player context and save review avoid duplicate cards and unnecessary scrolling. Layout, theme and language menus use consistent sizing. Item icons scale with the available slot space; equipment numbers have their own space above the icons, including compact Focus slots. Equipment captions and the Enderchest heading have clear spacing from their frames. Dialogs fit narrow and short windows, with readable text and reachable actions. Status feedback is quieter while write locks, errors and important warnings remain visible. Light mode improves the contrast of slot numbers, buttons, fields and diagnostic messages.
- **Mount configuration and preview:** a rotatable model previews each supported mount type and horse colors and markings. Models use more of the preview area while remaining visible through a full turn; a centered-view icon identifies the reset action. Placement details show the collision footprint and expandable block data. Staged mounts remain visible and use the existing review/save workflow. Technical and duplicate hints are reduced without removing placement warnings or write safeguards.
- **More precise placement checks:** checks cover the mount's full collision footprint and body height at the position that will actually be stored. Missing chunks, unfinished generation, unsupported data and probe errors have distinct explanations. Known obstructions take precedence over unchecked areas. A nearby chunk is not assumed safe merely because the player can see it in Minecraft.
- **More reliable navigation:** rescanning worlds preserves keyboard focus and list position; failed searches clear obsolete results. Stale player and mount responses cannot replace the current editing context. World-folder actions report the handoff to the file manager.
- **Dependency security:** the runtime requires Werkzeug 3.1.9 or later; the runtime, Docker and development lockfiles pin the reviewed update. The new layouts and model preview introduce no additional runtime libraries.
- **Docker packaging:** recursive build-context exclusions keep local Python caches, logs and private artifacts out of copied source directories. The container smoke test also rejects non-runtime artifacts and verifies the release manifest.

## Validation

Release preparation checks the full Python suite, backend branch coverage,
browser flows, JavaScript regressions, seven layout and mount smoke scripts,
dependency audits, runtime-package contents and integrity, and Docker startup
and graceful shutdown with a read-only root filesystem. Visual checks cover
desktop and emulated narrow screens, including the light theme.

These checks use synthetic fixtures and do not establish compatibility with
every Minecraft version, gameplay action or add-on. Version-specific engine
evidence and its limitations are documented in the
[engine checks](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.0/docs/engine-checks.md)
and [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.0/docs/save_contract.md).
Mount creation remains experimental; verify edited world copies in Minecraft.

## Upgrading

Python **3.12–3.14** remain supported. Run **`setup.bat` once before `start.bat`**
to install the updated, hash-pinned runtime dependencies. Preserve worlds,
backups and runtime data separately when replacing an installation.

An installation without a saved layout preference opens in **Classic**.
Existing layout, theme and language preferences remain selected.

**For installations with additional packs upgrading from before v0.6.3:**
update Vanilla icons once to prepare the base texture mappings. Rescanning alone
cannot add these mappings to an older Vanilla cache. When skipping several
versions, consult the notes of the skipped
[releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file.
The automatically generated **Source code** archives are repository snapshots,
not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.0/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.0/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.0/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.0/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the
exact version tag `0.7.0` for deployments; `latest` and minor tags are intentionally
mutable.
