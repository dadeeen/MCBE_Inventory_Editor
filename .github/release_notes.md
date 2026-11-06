## What's changed in v0.8.7

- Correct German and English item and variant names. Updates replace fallback names when Mojang provides a translation and keep custom names in each language.
- Keep installed icons if the item database is damaged. When block mappings change, the editor can recheck them using the cached resource pack.
- Show a short update result in setup and tools. Open **Show details** to see why an update failed or only some data was saved.
- Preserve the selected keyboard action in the backup restore confirmation dialog.

## Updating

Close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder into it.

The unsigned Windows app (`_windows_x64.zip`) requires WebView2. For the browser runtime (`_runtime.zip`), run `setup.bat` before `start.bat`. Each ZIP has a matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.7/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.7/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.7/SECURITY.md)
