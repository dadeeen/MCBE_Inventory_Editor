## What's changed in v0.10.1

- Reduce overhead when reading worlds and displaying villager lists.
- Preserve player stats and selected items when number inputs are empty or incomplete; reject oversized mount values before saving.
- Keep scan-path toggles consistent during refreshes and show scan warnings in the status center.
- Handle invalid world names and timestamps safely, preserve audit events during concurrent writes, and prevent fixture reports from overwriting ZIPs.
- Fix diagonal opacity seams in translucent block and model icons.
- Correct the German mangrove hanging sign item label, including unchanged labels in existing catalogs.

## Updating

Close the editor, extract the new ZIP into a fresh folder and copy your existing `data` folder into it.

The unsigned Windows app (`_windows_x64.zip`) requires WebView2. For the browser runtime (`_runtime.zip`), run `setup.bat` before `start.bat`. Each ZIP has a matching `.sha256` file.

Back up your world and stop Minecraft or the Bedrock server before editing.

[README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.10.1/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.10.1/README.de.md) · [Security](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.10.1/SECURITY.md)
