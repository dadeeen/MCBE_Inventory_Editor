Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.6.3

- **World pack icons:** icons follow the world's active resource and behavior packs, selected by UUID, version and priority. Static item textures support custom names and references between packs. Missing or ambiguous packs and unsupported rendering rules produce diagnostics; unresolved icons use standard icons or placeholders. Diagnostics follow the selected language. An unreadable optional pack directory does not discard verified local packs.
- **Icon caching and world switching:** worlds with the same icon sources share an index, including Vanilla-only worlds. Player loads reuse valid indexes, while pack or item-catalog changes trigger validation and rebuilding when needed. Loading more worlds preserves existing index files. Late responses from an earlier world cannot replace the selected world's icons. Read-only mode uses prepared indexes.
- **Item-catalog updates:** an update prepares and validates a complete catalog before replacing the active one. Running operations keep a consistent catalog, and a failed reload leaves the last valid catalog available with an error in the status view. Updates preserve cached player lists for unchanged worlds. Replaced database tables trigger fresh discovery even when their size and timestamps match the originals.
- **Editing:** undo keeps separate effect edits in the correct order, including when returning to a previously edited field. Repair all respects protected slots. Applying a converted position allows the next dimension conversion without reopening the form.
- **Backups and restore:** corrupt ZIP data, encrypted members and unsupported compression formats do not interrupt listing or count as valid recovery copies. Invalid backup dates fall back to the file time. If a restore leaves the world's state uncertain, the editor clears the loaded player and shows recovery guidance instead of allowing edits against the previous state.
- **Loading and saving:** saves reuse parsed source and validated output NBT while retaining output validation and write safeguards. Icon handling avoids duplicate decoding, archive metadata reads and source preparation. Damaged compressed icon images return a handled error.
- **Developer checks:** the Bedrock engine harness compares editor enchantment rules and conflict hints with measured behavior, checks combined equipment metadata and exact durability limits, and reports enchantment registry changes. Service and client profiles move and recreate equipment with multiple enchantments and custom metadata. CI and the local release workflow enforce consistent Python formatting.

## Validation

Validation includes the full Python suite, browser tests and runtime-package
checks. The documented BDS **1.26.52.3** reference covers all **1,623** measured
item identifiers, **13,153** item cases, enchantment applicability and conflict
comparisons, and engine save/reload cycles. A separate real-client profile covers
**45** cases across Inventory and Ender Chest. These checks exercise selected
item and save behavior; they do not simulate every gameplay action or add-on.
The exact measured source revision, hashes and limitations are recorded in the
[engine checks](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.3/docs/engine-checks.md)
and [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.3/docs/save_contract.md).

## Upgrading

This release adds no dependencies. Python **3.12–3.14** remain supported, and
existing installations start without running `setup.bat` again.

**For installations with additional packs:** update Vanilla icons once to
prepare the base texture mappings. Rescanning alone cannot add these mappings
to an older Vanilla cache.

**If upgrading from v0.5.21 or earlier:** run `setup.bat` once before `start.bat`
to install Waitress. When skipping several versions, consult the notes of the
skipped [releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file.
The automatically generated **Source code** archives are repository snapshots,
not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.3/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.3/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.3/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.6.3/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the
exact version tag `0.6.3` for deployments; `latest` and minor tags are intentionally
mutable.
