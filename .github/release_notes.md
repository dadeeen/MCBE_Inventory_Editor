## What's changed in v0.8.1

- Recover interrupted item database updates and keep bundled source metadata consistent.
- Preserve unapplied slot inputs during catalog updates and retain usable icon caches after failed downloads.
- Apply valid slot edits immediately, with grouped undo and world writes only on Save.
- Strengthen database write guards and preserve Bedrock-specific item data.
- Add read timeouts and restore presence polling after browser navigation.
- Complete missing banner and axolotl previews from matching local archives, improve setup feedback and update dependencies.

## Updating

For the browser runtime, run `setup.bat` once before `start.bat`. For the portable Windows app, close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder. Keep worlds and backups separately.

Download `_windows_x64.zip` for the Windows app (WebView2 required) or `_runtime.zip` for the Python runtime. Matching `.sha256` files verify download integrity; the Windows app is unsigned. GitHub's source archives are not ready-to-run packages.

Stop Minecraft or the Bedrock server and keep an independent world backup before editing. Mount creation remains experimental.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.1/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.1/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.1/SECURITY.md)
