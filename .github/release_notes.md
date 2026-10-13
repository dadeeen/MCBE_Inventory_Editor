Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.7.1

- **Studio status layout:** long warnings and errors use the available header width instead of being squeezed into a narrow, tall box. On smaller screens, the server status and message can occupy separate rows. Routine messages remain compact. Authenticated mobile sessions keep the layout, theme and language menus aligned beneath the logout control.
- **Readable status details:** Classic keeps the expanded status history inside its panel on narrow screens. Focus anchors the status history and server details to the full header, giving messages useful reading space instead of the width of a small status label.
- **Keyboard interaction:** Escape closes an open status history and returns focus to its toggle without also clearing the selected inventory slot. Closing the details preserves active warnings and write locks.

This patch changes presentation and status-panel interaction. World editing, mount creation, placement checks and write safeguards retain their existing behavior. It adds no dependencies and does not change saved layout preferences.

## Validation

Release preparation checks the full Python suite, backend branch coverage, browser flows, JavaScript regressions, seven layout and mount smoke scripts, dependency audits, runtime-package contents and integrity, and Docker startup and graceful shutdown with a read-only root filesystem. Visual checks cover desktop and emulated narrow screens, including the light theme.

These checks use synthetic fixtures and do not establish compatibility with every Minecraft version, gameplay action or add-on. Version-specific engine evidence and its limitations are documented in the [engine checks](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.1/docs/engine-checks.md) and [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.1/docs/save_contract.md). Mount creation remains experimental; verify edited world copies in Minecraft.

## Upgrading

Python **3.12–3.14** remain supported. Run **`setup.bat` once before `start.bat`** to verify the hash-pinned runtime dependencies. Preserve worlds, backups and runtime data separately when replacing an installation.

An installation without a saved layout preference opens in **Classic**. Existing layout, theme and language preferences remain selected.

**For installations with additional packs upgrading from before v0.6.3:** update Vanilla icons once to prepare the base texture mappings. Rescanning alone cannot add these mappings to an older Vanilla cache. When skipping several versions, consult the notes of the skipped [releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.1/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.1/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.1/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.7.1/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag `0.7.1` for deployments; `latest` and minor tags are intentionally mutable.
