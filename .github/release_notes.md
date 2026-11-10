## Unreleased

- Keep retained villager details readable while the server runs or the world changes, with one notice for the read-only scan.
- Show invalid region selections directly at the region form.
- Keep saved player markers available while the server runs and add a map action to find the selected player across dimensions.
- Group matching scan diagnostics and identify the affected villagers or stored references.

## What's changed in v0.9.0

- Add a Villagers workspace with search, filters, regions and a map across all dimensions, plus read-only trade and NBT details.
- Edit villagers' Minecraft names, health and supplies, including health changes for up to 1,000 villagers at once. Review and stage edits in the central Save tab, then save them alongside player and mount changes with one backup.
- Speed up villager scans, cache lists and load details without repeating the full scan. Load saved player positions when the map opens.
- Preserve staged changes when refreshing or switching players. A confirmed world reload clears staged changes.
- Keep workflow navigation usable on narrow screens.

## Updating

Close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder into it.

The unsigned Windows app (`_windows_x64.zip`) requires WebView2. For the browser runtime (`_runtime.zip`), run `setup.bat` before `start.bat`. Each ZIP has a matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.9.0/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.9.0/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.9.0/SECURITY.md)
