Release packages for the Minecraft Bedrock Inventory Editor.

## Unreleased

- **Portable Windows app:** A separate x64 ZIP starts `MCBEInventoryEditor.exe` in a WebView2 window with bundled Python, native file dialogs and an unsaved-change guard. WebView2 Runtime is required. The window stays on the editor's local origin, and guarded restore recovery works without installing Python separately.
- **Local lifecycle:** Browser servers run until explicitly stopped; heartbeat shutdown is opt-in. The desktop closes with its window after active writes finish.
- **Startup recovery:** A persistent notice offers a reload if the interface fails to initialize. Repeated local launches reopen an identified editor instance; unrelated port conflicts remain explicit errors.
- **Item inspector:** A read-only dialog provides a draft overview, searchable typed NBT tree and JSON view. It distinguishes loaded originals from edits and supports keyboard, touch and copying on narrow screens.
- **Special item editors:** Edit shulker and bundle contents, books, fireworks and banners. Contained items share inventory validation and the existing item browser. The picker explains shulker nesting and bundle capacity restrictions. Banner previews use Bedrock textures and work offline after downloading them.
- **Item preservation:** Repeated and nested edits preserve unknown metadata and unchanged values. Cancelling retains the parent draft; replacing an item cannot restore old hidden contents. Unsupported special-data formats remain read-only.
- **Controls and history:** Item menus, search results and dialogs support keyboard navigation and focus recovery. Accepted edits form distinct undo steps; unchanged edits add none. The session history describes moves, swaps and copies, and clearing it preserves drafts and undo steps.
- **Item database updates:** The preview distinguishes pending changes, current data and partial writes. It explains source-version differences, stack limits and description changes, with compact technical details. Unrelated Microsoft Learn page changes do not trigger recurring updates.
- **Restore permissions:** Restores preserve POSIX ownership, permissions and ACLs. Metadata-copy failures stop before replacing the world. The Docker instructions explain the shared UID/GID configuration needed to retain server ownership.
- **Other fixes:** More reliable local startup through configured HTTP proxies, stale-response handling and update history. The System theme follows OS changes, dialogs adapt to narrow screens, and mount placement avoids wither roses.

Desktop dependencies are pinned separately. Browser/Docker runtime dependencies, the world format and saved preferences remain unchanged.

## What changed in v0.7.2

- **Layouts and workflows:** Refreshed Classic, Studio and Focus layouts, effect editing, equipment handling and feedback for updates and file operations.
- **Write safety:** Uncertain saves, imports and restores require a reload before further writes. Context changes and confirmation retries preserve these guards.
- **Catalog and input validation:** Updates report source and item-data differences. Conflicting catalog identities and malformed requests produce controlled failures while preserving player data.
- **Backups and paths:** Backups handle filesystem dates outside the ZIP timestamp range. File dialogs and updater paths preserve Unicode; the NBT inspector displays large integers and non-finite values.

## Validation

Release checks cover Python and browser tests, dependency audits, package contents and desktop/Docker startup. See the [desktop validation guide](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/desktop.md#validation-and-maintenance) and [engine checks](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/engine-checks.md) for scope and manual checks. Mount creation remains experimental; verify edited world copies in Minecraft.

## Upgrading

Python **3.12–3.14** remain supported for the browser runtime. Run **`setup.bat` once before `start.bat`** to verify its hash-pinned dependencies. The portable Windows app includes Python: close the editor, extract the complete new ZIP into a fresh folder and copy your existing `data` folder before starting the EXE. Preserve worlds and backups separately; keep the old installation available for rollback.

An installation without a saved layout preference opens in **Classic**. Existing layout, theme and language preferences remain selected.

**For installations with additional packs upgrading from before v0.6.3:** update Vanilla icons once to prepare the base texture mappings. Rescanning alone cannot add these mappings to an older Vanilla cache. When skipping several versions, consult the notes of the skipped [releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download `_windows_x64.zip` for the portable Windows app or `_runtime.zip` for the browser runtime. The matching `.sha256` file lets you verify the download. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact tag of the chosen release for deployments; `latest` and minor tags are intentionally mutable.
