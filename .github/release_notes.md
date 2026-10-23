## What's changed in v0.8.1

- Apply valid slot edits immediately; write to the world only on Save.
- Fix undo history, repeated edits and preservation of item data.
- Recover interrupted database updates and cached banner and axolotl previews.
- Improve request timeouts, presence polling and write guards; update dependencies.

## Updating

Windows: close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder. Browser runtime: run `setup.bat` before `start.bat`.

Download `_windows_x64.zip` (WebView2 required, unsigned) or `_runtime.zip`, with the matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing. Mount creation remains experimental.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.1/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.1/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.1/SECURITY.md)
