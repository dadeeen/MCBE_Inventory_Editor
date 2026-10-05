Runtime package for the Minecraft Bedrock Inventory Editor.

## Unreleased

- **Engine checks:** compare editor enchantment rules and conflict hints with measured Minecraft behavior, exercise combined equipment metadata and exact durability limits, and report changed enchantment facts. Player-service checks move and recreate equipment with multiple enchantments and custom metadata.
- **Backups:** corrupt ZIP data, encrypted members and unsupported compression formats do not interrupt listing or count as valid recovery copies. Invalid backup dates fall back to the file time.
- **World pack icons:** the world's resource and behavior pack lists select packs by UUID, version and priority. Static item icons follow their declared textures, including custom names and references between packs. Missing or ambiguous packs and unsupported rendering rules produce diagnostics; unresolved icons use standard icons or placeholders. Status and warning counts reflect these limitations, and cached diagnostics follow the selected language. An unreadable optional pack directory does not discard verified local packs.
- **Icon caching and world switching:** worlds with the same sources share an index, including Vanilla-only worlds. Loading a player reuses a valid index, while pack or item-catalog changes trigger validation and rebuilding when needed. Loading more worlds preserves existing index files. Late responses from earlier requests cannot replace the selected world's icons. Read-only mode uses prepared indexes.
- **Player discovery:** item-catalog updates preserve cached player lists for unchanged worlds, avoiding another full scan. Replaced database tables trigger fresh discovery even when their size and timestamps match the originals.
- **Loading and saving:** icon loading avoids duplicate JSON decoding and repeated archive metadata reads. Status and scan requests prepare their icon sources once. Saves reuse parsed source and validated output NBT while retaining output validation and write safeguards. Damaged compressed icon images return a handled error.

When upgrading an installation that uses additional packs, update Vanilla icons
once to prepare the base texture mappings. Rescanning alone cannot add these
mappings to an older Vanilla cache.

## What changed in v0.6.2

- **Loading while a server runs:** v0.6.1 could fail to load a world that a running Bedrock server was writing, with a message that a table file disappeared while reading. The editor holds a world's table files from the moment it opens them, shares one table budget across all readers and the writer, and reports a world that changed during reading instead of returning a mixed state.
- **Player changed outside the editor:** when Minecraft or a server changes the loaded player, the status area shows an error with a "Reload player" action until the player is reloaded. A stale action after a player switch reloads nothing.
- **Status overview:** the status overview under Tools follows the server status and write lock shown in the header. Before, it could show "All OK" while the server was online and writing was locked.
- **Error messages:** a failed action names its reason once, without a second generic prefix such as "Error while saving: Error saving the player: …". An unexpected error shows "internal error, details in the server log (request ID …)" instead of the exception text, which could contain local paths; an operating system error keeps its description, such as a full disk or a file in use. The log panel of the diagnostics shows why the logs are refused instead of an empty list.
- **Item catalog:** eight tooltip lines that the catalog listed as items, such as "Can break:" and "Unbreakable", are gone, and Banner Pattern and Smithing Template carry their names instead of "Field Masoned" and "Applies to:". Existing installations are corrected when the catalog loads; own names stay.
- **Keyboard focus and status colors:** after loading, saving and closing a dialog, the keyboard focus returns to where it was or lands at the start of the new view. Status entries keep readable colors in the dark and light themes.
- **Faster loading:** a player is parsed once per load, and the item browser computes its sort keys once per item.

Validation includes the complete Python suite and the browser tests, four large readers in a Linux container limited to 1,024 open files, and a Minecraft 1.26.52 client that deleted 48 table files while the editor held them open. The save steps and the database format are unchanged; the in-game check covered reading only. See the [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.2/docs/save_contract.md) for validation boundaries.

This release adds no dependencies. Python 3.12–3.14 remain supported, and existing installations start without running `setup.bat` again. **If upgrading from v0.5.21 or earlier:** run `setup.bat` once before `start.bat` to install the Waitress server the editor uses since v0.5.22. When skipping several versions, the notes of the skipped [releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases) describe their changes, including the switch to the editor's own database code in v0.6.0.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.
