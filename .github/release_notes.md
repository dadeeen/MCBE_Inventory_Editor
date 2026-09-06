Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.18

- The slot editor's item search now lists exact name and identifier matches first and otherwise follows the item browser's order. Searching for **Stone** previously filled the ten suggestions with **Blackstone** and similarly named blocks while the matching item itself stayed out of view.
- Enter now accepts a suggestion by its localized name or a legacy alias instead of requiring a complete item identifier. Ambiguous input such as **Wool**, where every match is a different item, still leaves the choice to the suggestion list.
- The suggestion list now closes after an item has been selected instead of reopening immediately.
- For item families that share one identifier, such as beds and banners, the bare identifier selects its first data value, and the remaining variants no longer displace other matches from the suggestions.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
