# Minecraft Bedrock Inventory Editor

**🇬🇧 English** | [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml/badge.svg)](https://github.com/dadeeen/MCBE_Inventory_Editor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12–3.14](https://img.shields.io/badge/Python-3.12%E2%80%933.14-blue.svg)](#local-windows-setup)

A local web editor for selected Minecraft Bedrock player data: inventory, ender chest, effects, abilities, player values, and experimental mounts.

The interface is available in English and German. A switcher in the header changes it at any time; browsers requesting German get the German interface automatically.

This is an unofficial community project. It is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.

> **Before every edit:** stop Minecraft or the Bedrock server and create a complete, independent copy of the world. Keep that copy until the edited world has been verified in Minecraft. App-created backups are an additional safeguard, not a replacement.

The editor is intended for local use and trusted home networks. Do not expose it directly to the public internet.

Studio layout with example data, an English interface, and built-in placeholder icons:

[![World selection and safety status](docs/assets/editor-overview.png)](docs/assets/editor-overview.png)

[![Example inventory](docs/assets/editor-inventory.png)](docs/assets/editor-inventory.png)

## Download → backup → start

Choose the edition that fits your setup:

| Edition | Start with | Requirements |
| --- | --- | --- |
| [Portable Windows app](#portable-windows-app) | `_windows_x64.zip` → `MCBEInventoryEditor.exe` | Windows x64 and WebView2; Python is included |
| [Browser on Windows](#local-windows-setup) | `_runtime.zip` → `setup.bat`, then `start.bat` | Python 3.12–3.14 |
| [Docker / LAN](#docker-and-trusted-lans) | Published GHCR image and Compose | Docker with access to the stopped worlds |

All editions use the same editor. Download ZIPs and their matching `.sha256` files from [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).

### Browser edition on Windows

1. Open [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases).
2. Download the asset ending in `_runtime.zip` and its `.sha256` file. The automatically generated **Source code** archives are repository snapshots, not ready-to-run packages.
3. Verify the checksum if desired:
   - Windows: `Get-FileHash <runtime.zip> -Algorithm SHA256`
   - Linux: `sha256sum <runtime.zip>`
4. Stop Minecraft or the server and copy the complete world folder to an independent location.
5. Install [Python for Windows](https://www.python.org/downloads/windows/) if needed. For Windows x64 we recommend **Python 3.14**; 3.12 and 3.13 are also supported. Enable the Python launcher or **Add Python to PATH**. Runtime ZIPs and source checkouts use the same installation without a compiler. Python 3.15 is not approved yet.
6. Extract the runtime ZIP, run `setup.bat` once, then start the editor with `start.bat`.
7. On first start, follow the setup dialog and load **Item DB** and **Vanilla icons**. You can postpone this and return through the setup notice or **Tools** later. The editor ships with a bundled item snapshot and no icons, so without this step items from newer Minecraft versions are missing and every slot shows a placeholder symbol.
8. Keep the command-line window opened by `start.bat` open while using the editor. Closing it stops the local editor process; an open browser tab then loses its connection and cannot load or save data.

An item or icon update also checks and processes the downloaded files. Wait for the completion message before closing the editor.

## Why this exists

The editor was written for a private Bedrock server. Small corrections to a player's inventory or values meant copying world files to a Windows machine every time — far more effort than a routine fix deserves.

The goal was to make those adjustments possible from any device on the same network. The Docker deployment runs alongside the server and the browser interface works from a laptop, tablet, or phone, with no Windows machine and no local copy of the world involved.

That origin explains the scope: a reviewed set of player fields, edited with the world stopped and a backup in place, rather than a general-purpose world editor.

## What it supports

| Area | Scope |
|---|---|
| Inventory | Hotbar, backpack, armor, offhand, moving, copying, and bulk actions |
| Ender chest | Viewing and editing, including transfers between visible areas |
| Player values | Health, game mode, XP, hunger, saturation, position, effects, and walking and flying speeds |
| Safety | Pre-write backups, restore checks, revision checks, write gates, and world locks |
| Player transfer | Versioned local ↔ multiplayer migration and complete `.mcbe-player.zip` import/export |
| Icons | Shared Vanilla icons, active world packs, `.mcpack`, `.zip`, and custom icon folders |
| Mounts | Experimental creation of horses, donkeys, mules, skeleton horses, and camels |
| Diagnostics | World status, runtime checks, reports, and private raw-player export |

The app is not a public hosting service, server administration panel, or unrestricted raw NBT editor.

Icons follow active world packs, their versions and priority. Explicitly added editor sources apply globally; Vanilla icons share a local cache. Missing packs or unsupported textures use standard icons or placeholders. Custom block models, dynamic rendering and the Minecraft client's global pack settings are outside this support. See [icon resolution](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/icon-resolution.md) for supported formats and cache behavior.

## Three layouts

Choose between **Classic**, **Studio** and **Focus**, independently of the light or dark theme. Switch layouts without losing in-progress edits.

## Portable Windows app

Extract the **entire** release archive ending in `_windows_x64.zip` into a writable directory and double-click `MCBEInventoryEditor.exe`. Python, Node.js, BAT files and administrator privileges are not required. Keep the EXE and its accompanying `_internal` folder together.

The window uses the same interface and storage services as the browser and Docker editions. It requires **Microsoft Edge WebView2 Runtime**, normally present on Windows 11. If it is missing, install the [official Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). The EXE does not install system components itself. The target is Windows x64; the build bundles CPython 3.12.

Settings, icons, backups and the window profile live in the `data` directory created beside the EXE on first start. The local service binds exclusively to `127.0.0.1`, using port `5001` by default; browser startup keeps port `5000`. One desktop window runs per data directory. Closing checks for unsaved edits and finishes active writes. Startup errors are recorded in `data/desktop.log`.

The window stays on the local editor; clicked external HTTP(S) links open in the default browser. If the editing state cannot be checked, closing requires confirmation. Recovery after an interrupted restore is available through `--recover`, without installing Python; see [recovery instructions](SECURITY.md#interrupted-restores).

To update, close the editor. You can keep the installation directory: replace the EXE, the **entire** `_internal` directory and the remaining package files, including `RELEASE_MANIFEST.json`, with the matching new version while retaining `data`. Replacing only the EXE is insufficient; remove the old `_internal` directory before copying the new one. Alternatively, extract into a new directory and copy `data` into it to keep the old installation available until the new one is verified.

The initial item-database/icon download and the requirements to stop and back up the world also apply here. Browser installation and Docker do not require desktop dependencies. The [desktop build](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/desktop.md) describes architecture, validation and maintenance.

## Local Windows setup

This setup is for the browser edition. It supports **Python 3.12–3.14** and uses the same commands in a source checkout or extracted runtime ZIP:

```bat
setup.bat
start.bat
```

`setup.bat` keeps a supported existing `.venv` or creates one using the newest installed supported Python. It installs hash-checked wheels inside that environment, with no compiler or global Python packages. The editor opens at `http://127.0.0.1:5000`; app data lives under `data/`.

Keep the console open while editing. Closing a browser tab leaves the local service running; save your edits, then stop it with **Ctrl+C** in the console. The portable EXE shuts down through its own window.

Administrator rights should not normally be needed. If a safely stopped world cannot be saved because of Windows permissions, running `start.bat` as administrator can be used as a diagnostic test. It does not make editing a running world safe.

## Docker and trusted LANs

For a straightforward setup, use `latest` to pull the current stable image:

```bash
docker pull ghcr.io/dadeeen/mcbe-inventory-editor:latest
```

Stable releases update `latest`; pre-releases do not. To keep a specific version, replace `latest` with the version shown on the [Releases page](https://github.com/dadeeen/MCBE_Inventory_Editor/releases), without the leading `v`. This lets you choose each version change explicitly.

Save this example as `compose.yaml` or use it as a stack. Replace `/PATH/TO/BEDROCK/WORLDS` with the existing host directory containing your worlds. Set `MCBE_SERVER_HOST` to your Bedrock server's address as reachable from the container, and adjust its port if needed:

```yaml
services:
  mcbe-editor:
    image: ghcr.io/dadeeen/mcbe-inventory-editor:latest
    restart: unless-stopped
    ports:
      - "8088:8080"
    environment:
      MCBE_SERVER_HOST: "192.168.1.100"
      MCBE_SERVER_PORT: "19132"
    volumes:
      - /PATH/TO/BEDROCK/WORLDS:/worlds:rw
      - mcbe-editor-data:/data:rw

volumes:
  mcbe-editor-data:
```

From the directory containing `compose.yaml`, pull the image and start the editor in the background:

```bash
docker compose pull
docker compose up -d
```

Use the same commands to update after finishing your edits. `latest` does not update a running container automatically; pulling and recreating it applies the downloaded image while keeping the named data volume. In a stack manager, pull the image and redeploy the stack.

The [Compose example on GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docker-compose.example.yml) uses the same published image and adds comments, log rotation and container restrictions. Copy it to `compose.yaml`, adjust the world path and server address, and use the commands above.

On first open, set a password or explicitly confirm passwordless use on a trusted network. Protect the port with host firewall rules and never add public ingress or a public tunnel.

Important Docker behavior:

- Worlds are read from `/worlds`; persistent app data and backups are stored under `/data`.
- `MCBE_REQUIRE_SERVER_OFFLINE=true` is the default. A reachable configured Bedrock server blocks writes; unknown status requires confirmation. The check recognizes both server transports on `MCBE_SERVER_PORT`: RakNet by its UDP ping and NetherNet (`transport=nethernet`) by an HTTP request to `/v1/join` over TCP. For NetherNet, the editor must be able to reach that TCP port; otherwise the status stays unknown.
- `MCBE_READ_ONLY=true` switches the app into read-only viewer mode. For a real viewer deployment, also mount `/worlds:ro`; Docker's `read_only: true` alone does not protect mounted worlds.
- For write-enabled deployments, mount the common parent directory of the worlds at `/worlds`, not one individual world. Restore staging and rollback need access to sibling paths.
- The container runs as non-root UID/GID `10001`; the host directory must grant the required access. A `:rw` mount alone is not enough — set this up **before** the first save, see [Write permissions for Docker worlds](#write-permissions-for-docker-worlds).
- The first-start setup notice applies here too: **Item DB** and **Vanilla icons** are stored under `/data`, so keep that volume persistent and allow outbound HTTPS from the container.
- A successful full Item DB update stores a verification receipt beside the database under `/data`. It is bound to the exact database file and its source metadata: changing browsers keeps the verified state, while deleting or replacing `/data` intentionally requires one new full Item DB update.

### Write permissions for Docker worlds

The host filesystem must grant UID/GID `10001` access before the first save. Expand the instructions if permissions need adjusting.

<details>
<summary>Configure and diagnose Docker world permissions</summary>

A `:rw` mount alone does not give the process inside the container write permission. The editor deliberately runs as non-root UID/GID `10001`. An error such as

```text
IO error: /worlds/MyWorld/db/LOCK: Permission denied
```

means that UID `10001` cannot write the LevelDB directory or create the `LOCK` file there. This can be true even when `LOCK` does not exist yet.

Stop the Bedrock server before making any of the following changes and first resolve the actual mounted host path:

```bash
docker inspect mcbe-editor --format \
  '{{range .Mounts}}{{println .Source "->" .Destination "Mode:" .Mode}}{{end}}'
```

Replace `mcbe-editor` with your container name when necessary.

#### Recommended: targeted ACL for UID 10001

This keeps the server files' existing owner and group while granting only the editor additional access. On Debian/Ubuntu, install the `acl` package first when needed (use the corresponding package manager on other distributions), then set `WORLDS_ROOT` to the host path mounted at `/worlds`:

```bash
sudo apt-get install -y acl

WORLDS_ROOT=/var/lib/docker/volumes/MY_VOLUME/_data/worlds

sudo setfacl -R -m u:10001:rwX "$WORLDS_ROOT"
sudo find "$WORLDS_ROOT" -type d -exec setfacl -m d:u:10001:rwX {} +
```

The default ACL on each directory lets newly created files and subdirectories inherit editor access. Mount the common worlds directory rather than one individual world so restore and rollback can create their safe temporary sibling paths.

Verify the actual world directory afterwards. `ls /worlds` prints the real folder names, so set `WORLD` to one of them rather than leaving the placeholder in place:

```bash
docker exec mcbe-editor sh -lc '
id
ls /worlds
WORLD=/worlds/MyWorld/db
if [ ! -d "$WORLD" ]; then
  echo "Path not found: $WORLD"
elif [ -w "$WORLD" ]; then
  echo "World database is writable"
else
  echo "World database is NOT writable"
fi
'
```

#### Compatibility mode: shared group or shared UID

If ACLs are not reliably available on the host filesystem, the Bedrock server and editor can deliberately use a dedicated shared group. Example with GID `12000`:

```yaml
services:
  mcbe-editor:
    group_add:
      - "12000"
```

On the host, the world files must belong to that group, be group-writable, and make new subdirectories inherit the group:

```bash
WORLDS_ROOT=/var/lib/docker/volumes/MY_VOLUME/_data/worlds

sudo chgrp -R 12000 "$WORLDS_ROOT"
sudo chmod -R g+rwX "$WORLDS_ROOT"
sudo find "$WORLDS_ROOT" -type d -exec chmod g+s {} +
```

The Bedrock server process needs the same supplemental group. Both processes must create new files as group-writable, typically with `umask 0002`; without that shared umask, group mode is not reliable for files created later.

For maximum compatibility, both containers can instead deliberately run under the same **unprivileged** UID/GID:

```yaml
services:
  mcbe-editor:
    user: "1234:1234"  # Example: the same UID/GID as the Bedrock server
    volumes:
      - /srv/bedrock/worlds:/worlds:rw
      - /srv/mcbe-editor-data:/data:rw
```

Before startup, `/srv/bedrock/worlds` and `/srv/mcbe-editor-data` must be writable by that identity. Never use UID `0` here. This shared identity is more reliable with restrictive umasks, but reduces isolation further: from the kernel's perspective, the editor and server have identical file permissions.

Both compatibility variants reduce isolation. Every process and user in the shared group or using the shared UID can modify the worlds. Use a dedicated group or unprivileged service UID, never a broadly shared system group.

Unsupported shortcuts:

- do not run `chmod -R 777` on world or data directories;
- do not add `privileged: true` or run the editor as root to bypass filesystem permissions;
- do not delete LevelDB's `db/LOCK` file or disable locking to bypass a running server.

Those measures do not fix the ownership and permission cause, or they remove important isolation and concurrent-access safeguards.

</details>

The [viewer example](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docker-compose.viewer.example.yml) configures read-only access. Local build helpers are in `scripts/docker/` in the source checkout or runtime ZIP. To build an image, run `docker build -t mcbe-inventory-editor:local .` from the checkout or runtime package root and set `image: mcbe-inventory-editor:local` in Compose.

## Safe workflow

1. Stop Minecraft or the Bedrock server.
2. Create an independent copy of the complete world.
3. Select the world and player in the editor.
4. Make and review the changes.
5. Save. An actual write creates a backup first.
6. Close the editor, open the world in Minecraft, and verify the result.
7. Keep the independent copy until verification is complete.

The editor does not stop or start Minecraft or a Bedrock server itself.

## Player migration and import

**Local ↔ multiplayer migration** transfers an explicit allowlist of gameplay state while preserving the destination player identity and unknown destination fields. This includes reviewed vanilla attributes, the last death location, sleep/phantom state, and recipe unlocks. Recipes are merged without loss: missing source recipes are added while existing target recipes are preserved. The destination multiplayer player must already have joined the world once. The source record is not deleted, and pet ownership is not reassigned.

A complete `.mcbe-player.zip` import is different: it writes the exported player record as a whole. Both operations create a verified backup, validate the write, and attempt rollback on failure. Always verify the resulting player in Minecraft.

Player exports contain raw, non-anonymized NBT data. Treat them as private and do not attach them to public issues or commit them to a repository.

For command-line raw exports, see [private player diagnostics](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#private-player-diagnostics). These tools require the browser runtime or a source checkout; the desktop EXE does not provide a general Python CLI.

## Experimental mounts

The Mounts view can stage horses, donkeys, mules, skeleton horses, and camels near the player in the Overworld. Placement is checked against decoded terrain:

- green candidates are accepted;
- yellow candidates could not be proved safe and require explicit confirmation;
- red candidates are rejected server-side.

Staging does not write to the world. The confirmed workspace save creates one backup and writes player and mount records together. Terrain, dimensions, add-ons, and future Bedrock versions are not fully covered, so test this feature on expendable world copies first.

## Data safety and privacy

The editor deliberately leaves unsupported Bedrock and add-on data untouched instead of behaving like a full raw NBT editor. Unknown formats can still invalidate assumptions, and no backup or validation can guarantee semantic correctness for every world or future Minecraft version.

Practical safeguards and limits:

- Editing works offline. **Item DB** and **Vanilla icons** updates need outbound HTTPS; the optional startup network check also contacts their allowlisted hosts.
- Writes check the loaded player revision, world lock and server status. Each actual write requires a verified full-world backup; an unchanged save writes nothing and creates no backup.
- Restore checks the archive and creates a pre-restore backup. If a restore is interrupted or its outcome is uncertain, keep the backup and recovery files and follow [recovery instructions](SECURITY.md#interrupted-restores) before editing further.
- World folders must contain ordinary files and directories. Symlinks, Windows junctions and other reparse points are unsupported.
- Backups and restores default to **1 GiB uncompressed** and at most **50,000 entries** per archive. Adjust the size under **Tools → Backup Manager**. An explicit `MCBE_BACKUP_MAX_UNCOMPRESSED_MIB` setting overrides the saved value. Keep enough free disk space for backup and restore copies.
- Worlds, backups, exports, diagnostics and audit logs can contain identifying information. Keep them private and outside repositories and release archives. Local app data lives in `data/`; Docker uses `/data`, including `/data/backups`.

The [security policy](SECURITY.md) covers deployment, recovery and vulnerability reports. The [save contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md#backups-and-restore) describes backup limits and validation in detail.

## Compatibility and limitations

- Linux Bedrock servers can keep a world open without taking LevelDB's `LOCK`; file locks alone do not prove that the server is stopped. Keep the server-status guard configured and stop the actual server before editing.
- Missing or inconsistent database files and exceeded [reader limits](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/leveldb-writer.md) block writes. The editor does not repair damaged databases.
- Bedrock updates, add-ons, opaque NBT, and unusual LevelDB structures can fall outside what the editor is designed to handle.
- Experimental mount placement is not full Minecraft collision physics.
- Release ZIPs have a SHA-256 checksum and an internal file manifest, but no independent cryptographic signature.

## Development and license

Bug reports and contributions are welcome. Use synthetic data and sanitized logs; never attach real worlds, backups, player exports, audit exports, player names, private paths, or credentials.

Contributor instructions, tests, fixtures, and release hygiene are in [docs/development.md on GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md). Internal save invariants are documented in [docs/save_contract.md](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md).

Optional [Bedrock engine checks](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/engine-checks.md) document tested versions, scope and remaining gaps. Their developer tools, Mojang server binaries and generated test worlds are excluded from runtime packages.

The project's own code is licensed under the [MIT license](LICENSE). Runtime dependencies are subject to their respective upstream licenses. Amulet-LevelDB, Amulet-NBT and their dependencies are used only in the separately installed Python 3.12 reference-test environment and are not shipped with the runtime; their upstream license terms apply to that test environment.

Minecraft content is not covered by this project's license. The repository includes an item-data snapshot generated from `Mojang/bedrock-samples` and Microsoft Learn; vanilla icons are downloaded only on request and are not shipped. The origin of the locally maintained enchantment maximum levels is documented in [docs/development.md on GitHub](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#bundled-item-database-and-enchantment-max-levels). Minecraft and its content belong to Mojang Studios/Microsoft and remain subject to their terms.

Key upstream projects include [Amulet Team](https://github.com/Amulet-Team), Flask and the Pallets team, and the [Minecraft Wiki](https://minecraft.wiki/) as a reference for manually verified gameplay mechanics.
