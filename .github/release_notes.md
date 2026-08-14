Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.14

- Item DB and vanilla-icon updates now check Mojang's latest Bedrock sample release automatically and reuse a download only when its release identity, size, and ZIP validation match.
- Applying an Item DB dry run now replays the exact reviewed Mojang archive and Microsoft Learn item snapshot against the reviewed database state and scope.
- If any reviewed source or starting file changes before apply, the update stops and asks for a new dry run instead of silently processing different data.
- The misleading manual cache controls were removed from the web interface; safe cache reuse is automatic.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
