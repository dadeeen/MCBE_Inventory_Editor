Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.7.2

- **Visual refresh:** Reworked Classic, Studio and Focus layouts with clearer navigation, reorganized controls and better use of screen space. Studio keeps the inventory grid and inspector aligned on wide screens.
- **Write-outcome safety:** Import, migration and restore keep further writes blocked after an uncertain response or an explicit reload requirement. Resetting a view or refreshing only the player list cannot release that protection; a successful player or explicit world load can.
- **Restore refresh and context changes:** A completed restore with a failed follow-up reload remains protected. Switching players in the same restored world preserves the newer view but requires reloading it before further writes; switching to another world leaves that world untouched.
- **Confirmation lifecycle:** Unknown-server confirmation is limited to the current operation and its matching presence-conflict retry. A possibly completed write or a response requiring reload must not trigger another automatic attempt.
- **Editor workflows:** Improved effect editing, equipment handling and feedback for updates and file operations.
- **Catalog validation:** Item updates report changes and validation results, including localized names, stack limits and durability. Conflicting effect or enchantment identities block the affected editor section while preserving existing player data.
- **Runtime and input handling:** Explicit session secrets take precedence over saved setup state. Log access requires authentication for Docker and LAN exposure. Malformed redirects, guard tokens, setup values and player archives produce controlled failures.
- **Backups and desktop paths:** Backups accept filesystem dates outside the ZIP timestamp range. Folder dialogs and updater output preserve Unicode text, and updater subprocesses resolve data paths before changing directories. The NBT inspector preserves large integers and non-finite values in its display.

This patch adds no dependencies and does not change the on-disk world format or saved layout preferences.

## Validation

Release preparation checks the full Python suite, backend branch coverage, browser flows, JavaScript regressions, seven layout and mount smoke scripts, dependency audits, runtime-package contents and integrity, and Docker startup and graceful shutdown with a read-only root filesystem. Visual checks cover desktop and emulated narrow screens, including the light theme.

These checks use synthetic fixtures and do not establish compatibility with every Minecraft version, gameplay action or add-on. Version-specific engine evidence and its limitations are documented in the [engine checks](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.2/docs/engine-checks.md) and [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.2/docs/save_contract.md). Mount creation remains experimental; verify edited world copies in Minecraft.

## Upgrading

Python **3.12–3.14** remain supported. Run **`setup.bat` once before `start.bat`** to verify the hash-pinned runtime dependencies. Preserve worlds, backups and runtime data separately when replacing an installation.

An installation without a saved layout preference opens in **Classic**. Existing layout, theme and language preferences remain selected.

**For installations with additional packs upgrading from before v0.6.3:** update Vanilla icons once to prepare the base texture mappings. Rescanning alone cannot add these mappings to an older Vanilla cache. When skipping several versions, consult the notes of the skipped [releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.2/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.2/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.2/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.2/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag `0.7.2` for deployments; `latest` and minor tags are intentionally mutable.
