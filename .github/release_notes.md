Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.19

- Vanilla icon generation now resolves item sprites and block materials in separate namespaces, using explicit item and carried-block definitions before compatibility rules. Brick blocks now appear as blocks instead of individual brick ingredients.
- Block previews use declared face materials where supported. Dedicated inventory sprites remain available for placeable items, and anvil previews no longer develop transparent gaps from unused texture regions.
- Additional icon sources consistently prefer item sprites over same-named block materials, regardless of directory or archive order. Block materials no longer stand in for known non-block ingredients.
- Icon manifests record resolution strategies and unresolved conditions. Developer comparisons check source changes and PNG contents; model and state approximations remain documented rather than being treated as exact game renders.

> **After upgrading:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the corrected resolver. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
