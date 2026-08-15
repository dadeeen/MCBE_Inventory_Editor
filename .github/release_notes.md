Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.15

- Items that Mojang adds in a newer Bedrock release now show up in the item browser as soon as the Item DB is updated, marked **New · not yet reviewed** until the bundled curated classification catches up.
- Identifiers that Mojang exposes only as technical block states, such as double slabs and sign states, are no longer offered as new inventory items. Existing worlds that contain them stay readable and are saved unchanged.
- Registry items whose display name has not reached Mojang's public language files yet stay visible under a readable name derived from their identifier instead of dropping out of the browser.
- Identifiers that Mojang removes from its item registry are no longer offered for new items, while worlds that already contain them keep them intact.

> **After upgrading:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
