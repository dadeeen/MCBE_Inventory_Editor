## What's changed in v0.8.8

- Speed up world database checksum verification on Windows x64 and in Docker.
- Include the SSL runtime required for HTTPS updates in the Windows desktop app.
- Preserve keyboard focus in the backup restore confirmation dialog.

## Updating

Close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder into it.

The unsigned Windows app (`_windows_x64.zip`) requires WebView2. For the browser runtime (`_runtime.zip`), run `setup.bat` before `start.bat`. Each ZIP has a matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.8/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.8/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.8/SECURITY.md)
