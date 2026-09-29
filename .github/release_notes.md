Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.6.1

- **World in use: the reason once:** when Minecraft, a Bedrock server or another editor instance has the world open, a refused save, import, player migration or mount creation shows the reason once. Before, the message repeated its error prefix ("Error while saving: Error saving the player: …"), and the editor logged the refusal as an internal server error.
- **Mount coordinates in the save overview:** the save overview shows the position of a mount to be created with two decimals, as the mount panel does, instead of values such as `101.30000305175781 / 64 / -5.699999809265137`.

Validation includes the complete Python suite, the browser tests, a test that refuses a save because the world is in use, and a test for the coordinates in the save overview. The write path and the database format are unchanged, and no new in-game validation was performed. See the [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.1/docs/save_contract.md) for validation boundaries.

This release adds no dependencies. Python 3.12–3.14 remain supported, and existing installations start without running `setup.bat` again. **If upgrading from v0.5.21 or earlier:** run `setup.bat` once before `start.bat` to install the Waitress server the editor uses since v0.5.22. When skipping several versions, the notes of the skipped [releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases) describe their changes, including the switch to the editor's own database code in v0.6.0.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
