## What's changed in v0.8.4

- Support the measured Freezing potion variants and effect from Bedrock 26.60, with experimental labels and preserved unknown values.
- Retain reviewed effects when updating from older Mojang sample data; require a fresh update preview after upgrading.
- Use the stable Script API for the optional real-client Ender Chest checks.
- Validate the automated inventory, specialized-item, player-service and add-on profiles against BDS 1.26.60.6.
- Update the development-only msgpack dependency to 1.2.4 to address CVE-2026-114613.

## Updating

Windows: close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder. Browser runtime: run `setup.bat` before `start.bat`.

Download `_windows_x64.zip` (WebView2 required, unsigned) or `_runtime.zip`, with the matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing. Mount creation remains experimental.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.4/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.4/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.4/SECURITY.md)
