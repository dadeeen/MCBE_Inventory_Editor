## What's changed in v0.8.6

- Update the item database even when official translations are missing, with clear notices for fallback names.
- Preserve existing data when a source section cannot be validated; explain partial updates and keep previews consistent with applied changes.
- Handle slow world loads with progress, cancellation and clear timeout messages; cancel outdated comparison and copy requests.
- Strengthen validation of world-loading requests and keep internal error details out of public responses.

## Updating

Windows: close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder. Browser runtime: run `setup.bat` before `start.bat`.

Download `_windows_x64.zip` (WebView2 required, unsigned) or `_runtime.zip`, with the matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing. Mount creation remains experimental.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.6/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.6/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.8.6/SECURITY.md)
