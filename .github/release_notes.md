## Unreleased

- Speed up villager lists and details with a database-state cache, and load saved player positions only when the map opens.
- Reduce allocation during entity scans while preserving NBT validation and global duplicate-ID checks.
- Support compact villager health attributes without inventing missing defaults, and preserve unchanged records byte for byte.
- Add a Docker/BDS villager suite covering health and supplies through production saves and four engine reloads.
- Add an opt-in natural village profile with real client trades and food pickup, offline health and supply edits, and required server and chunk reloads.
- Stage villager health and supplies for the central Save tab, with one backup and atomic save alongside player and mount changes, including worlds without a loaded player. Cover this path in the permanent Bedrock engine checks.
- Preserve staged world changes when refreshing or changing players, and clear them after a confirmed, successful world reload, including the same world path.
- Remove redundant explanatory text from villager details and the save review.
- Edit and remove actual Minecraft villager names through the central Save tab. Keep editor aliases in More settings and cover name persistence in the Docker/BDS suite.

## What's changed in v0.8.8

- Speed up world database checksum verification on Windows x64 and in Docker.
- Include the SSL runtime required for HTTPS updates in the Windows desktop app.
- Preserve keyboard focus in the backup restore confirmation dialog.

## Updating

Close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder into it.

The unsigned Windows app (`_windows_x64.zip`) requires WebView2. For the browser runtime (`_runtime.zip`), run `setup.bat` before `start.bat`. Each ZIP has a matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.8/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.8/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.8/SECURITY.md)
