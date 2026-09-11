Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.20

- Item autocomplete now makes every matching item reachable through additional result pages instead of silently stopping after ten matches. Suggestions support keyboard selection, Escape, and predictable focus, with readable colors across all themes and narrow layouts.
- Editing, including undo and redo shortcuts, is locked throughout save review and the save request. This prevents the submitted data and the editor's clean state from diverging. Editing is restored after completion or cancellation, and rejected saves keep unsaved changes.
- Switching worlds clears the previous player's inventory and revision before loading a player from the new world. A failed player load no longer leaves old data attached to the new world or reports a successful switch.
- Reloading or unloading a player correctly discards pending mount creations and resets the editor's dirty state.
- Environment-configured passwords containing umlauts or other Unicode characters now authenticate correctly. Incorrect Unicode passwords are rejected without an internal server error.

> **If upgrading directly from v0.5.18 or earlier:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the resolver corrected in v0.5.19. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
