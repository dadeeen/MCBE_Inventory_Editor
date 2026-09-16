Runtime package for the Minecraft Bedrock Inventory Editor.

## What changed in v0.5.23

- **Updated item catalog:** includes 105 additions from Bedrock 26.50 and reviewed stack limits for all 1,623 registered IDs, including corrections for boats, signs, minecarts, entity buckets and shulker boxes.
- **Safer stack limits:** unverified limits no longer imply 64. New stacks are limited to 1 and Max-Stack is disabled until a limit is confirmed; existing amounts remain unchanged. The editor and update log identify unverified limits.
- **Corrected item properties:** updated durability for fishing rods, carrots on sticks and chainmail helmets, plus enchantment compatibility for lodestone compasses and maces.
- **More consistent backups:** automatic, manual and pre-restore backups share source-consistency checks. Detected source changes or storage synchronization failures stop dependent writes or restores.
- **Stronger write handling:** immutable write plans, expanded type checking and regression tests improve handling of interrupted backups and uncertain write outcomes.
- **Engine verification tools:** optional developer checks exercise item NBT, stack boundaries, enchantments, selected variants, player saves and controlled add-ons against an explicitly selected official Bedrock server. Server binaries, generated worlds and raw reports are excluded from the repository and runtime packages.

Validation includes 13,037 item cases across two engine save/reload cycles on BDS 1.26.51.1, plus a separate real-client Inventory/Ender Chest persistence test. Coverage is specific to the tested version and profiles; it does not certify arbitrary add-ons, every metadata combination, singleplayer persistence or all gameplay. See [engine-check scope](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/v0.5.23/docs/engine-checks.md) for details.

Backups continue to contain the complete world. Configured size limits and retention policies are unchanged. Metadata checks do not create an atomic snapshot of a running world; directory synchronization is unavailable on Windows and some filesystems, so these changes do not guarantee protection against every power loss.

**Updating from v0.5.22:** this release adds no dependencies. Python 3.12–3.14 remain supported. **If upgrading from v0.5.21 or earlier:** run `setup.bat` once before `start.bat` to install the hash-pinned Waitress dependency introduced in v0.5.22. Flask and Werkzeug remain required.

> **If upgrading directly from v0.5.18 or earlier:** open **Tools & settings → Icons** and select **Load Vanilla icons** (**Werkzeuge & Einstellungen → Icons → Vanilla-Icons laden**) to rebuild existing PNGs with the resolver corrected in v0.5.19. Rescanning sources alone does not regenerate cached images.

> **If upgrading directly from v0.5.14 or earlier:** the Item DB may show **Verification pending** even when its data has not changed. This is expected because the verification rules changed in v0.5.15; it does not mean that the database is damaged. If the setup dialog opens, select **Load now** for **Load item database**. Otherwise, open **Tools & settings → Item DB**, run a dry run, and then select **Apply update**. An apply with no data changes only refreshes the local verification record.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

Download the asset ending in `_runtime.zip` together with its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.

- Installation, Docker and LAN setup: [README](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/README.de.md)
- Supported security boundary and vulnerability reporting: [SECURITY](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.md) · [Deutsch](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/SECURITY.de.md)

Docker images are published to `ghcr.io/dadeeen/mcbe-inventory-editor`. Prefer the exact version tag for deployments; `latest` and minor tags are intentionally mutable.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.
