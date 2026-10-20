# Security Policy

**🇬🇧 English** | [🇩🇪 Deutsch](SECURITY.de.md)

The Minecraft Bedrock Inventory Editor is intended for local use and trusted LAN environments with worlds you control. It is not designed as a public internet service.

## Supported versions

| Version | Support |
|---|---|
| Latest published [GitHub Release](https://github.com/dadeeen/MCBE_Inventory_Editor/releases) | Supported |
| Current `main` branch | Best effort; development state |
| Older releases and commits | Not supported |

## Reporting a vulnerability

Report suspected vulnerabilities privately through GitHub's [Report a vulnerability](https://github.com/dadeeen/MCBE_Inventory_Editor/security/advisories/new) form.

Do not disclose an unpatched vulnerability in a public issue. Use synthetic examples; never attach real worlds, backups, raw player data, credentials or unreviewed logs. See [Private data and diagnostics](#private-data-and-diagnostics).

Include only what is needed:

- affected version or commit and operating mode;
- security impact and required attack conditions;
- minimal reproduction steps using synthetic data;
- sanitized logs or request metadata.

If private reporting is unavailable, open a minimal public issue asking for a private contact channel without disclosing the vulnerability.

We aim to acknowledge reports within three business days and provide an initial assessment within seven business days. Resolution time depends on severity and complexity. Please allow time for a coordinated fix and release before public disclosure.

Ordinary bugs belong in the issue tracker. Use the private channel for data-loss risks, authentication or authorization bypasses, unsafe path handling, secret or private-data exposure, and remotely triggerable writes.

## Security boundary

The editor modifies Bedrock NBT and LevelDB directly. Its safeguards cannot guarantee compatibility with every Bedrock version, add-on or unusual world structure.

The supported boundary is:

- Local Mode bound to `127.0.0.1`; or
- an authenticated instance reachable only from a trusted LAN or private network;
- fully stopped worlds with independent backups.

Public hosting, untrusted multi-user access, broad host filesystem mounts, and direct internet ingress are outside the supported boundary. A reverse proxy does not change this boundary.

Before every edit, stop Minecraft or the server and create a complete copy outside the mounted world folder and `MCBE_BACKUP_ROOT`. Keep it until the result has been verified in Minecraft.

Editor-created backups are an additional safeguard. Their consistency and archive checks cannot establish that a live world was captured atomically or that Minecraft can use it. Power-loss protection also depends on the operating system, filesystem and storage. See the [backup and restore contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/save_contract.md#backups-and-restore) for implementation limits.

## Deployment essentials

- Enable password protection for LAN use.
- Leave `MCBE_TRUST_PROXY_HEADERS=false` unless a trusted reverse proxy is the only route to the app.
- Loopback requests are restricted to local hostnames by default. For LAN/Docker or a trusted reverse proxy, set `MCBE_TRUSTED_HOSTS` to the expected hostnames (comma-separated, without URL scheme, path or port), or enforce them at the proxy. This is separate from `MCBE_ALLOWED_ORIGINS` and CSRF protection.
- Leave `MCBE_REQUIRE_SERVER_OFFLINE=true` for real server worlds and configure `MCBE_SERVER_HOST`. For a NetherNet server, the editor also needs TCP access to the server port.
- Treat `MCBE_REQUIRE_SERVER_OFFLINE=false` as an explicit unsafe override for stopped copies or archives only.
- For viewer deployments, use both `MCBE_READ_ONLY=true` and a `/worlds:ro` volume. Docker's `read_only: true` protects only the container root filesystem.
- Mount only the required worlds parent folder, never `/`, `/home`, or an entire NAS.
- Grant the unprivileged container process targeted access as UID `10001` or through a dedicated shared group. See [Write permissions for Docker worlds](README.md#write-permissions-for-docker-worlds) for the concrete ACL and group variants.
- Do not use `chmod 777`, `privileged: true`, root execution, or deletion/bypassing of LevelDB locks as a permission workaround.
- Keep `/data` private and persistent. It contains setup state, backups, and potentially audit data.
- Use `MCBE_FAIL_ON_INSECURE_CONFIG=true` when an unauthenticated wide bind must abort startup.

File locks alone do not prove that a Bedrock server is stopped. Keep the server-status guard configured: it checks again immediately before writing. Unknown status can require confirmation; a detected online server still blocks the write.

The editor refuses to write to incomplete or inconsistent databases and never repairs them. If a save reports an unknown outcome or a failed rollback, keep its backup and reload the world before editing further: data may already have been written.

## Private data and diagnostics

Real worlds, backups, `.mcbe-player.zip` files, raw NBT, diagnostic reports, and audit exports must be treated as private. Renaming a world or deleting its icon does not anonymize LevelDB records. Keep runtime `data`, including desktop profiles and logs, out of releases.

Audit logs can include IP addresses, usernames, world names, path and player-key hashes, truncated player keys, actions, outcomes and request/error details. Redaction, hashes and truncation do not anonymize these records. Review and sanitize any material before sharing it.

Unexpected exception details stay in the server log, referenced by the response's request ID (`X-Request-ID`); they may contain private paths. User-facing messages can also name affected files. On POSIX, newly created setup and audit files are restricted to their owner; on Windows, protect the containing directory with appropriate ACLs.

Private fixture worlds belong only under `fixtures/private/`, which is ignored and excluded from releases. Public fixtures require LevelDB/NBT-aware anonymization and manual review; see the [fixture rules](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/tests/fixtures/README.md) and [isolated entity-record contract](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/tests/data/README.md).

## Dependencies and verification

Dependencies are hash-pinned for Python 3.12–3.14; `pyproject.toml` and the lockfiles are authoritative. Windows browser setup and Docker require prebuilt dependencies without an automatic source-build fallback. The portable desktop bundles Python and uses the installed WebView2 Runtime. Build details belong in the [dependency guide](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/requirements/README.md) and [desktop guide](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/desktop.md).

Maintainers should update affected packages deliberately and run the [test and dependency checks](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/development.md#local-check-round) in the source checkout's development environment. Audits do not provide runtime protection; avoid broad automatic upgrades.

Normal editing and startup need no outbound internet access. Optional item-data and icon downloads use allowlisted HTTPS sources and size limits; configured server-status checks contact the server.

## Releases and recovery

Official browser and desktop ZIPs are published through the original repository's [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases); Docker images use `ghcr.io/dadeeen/mcbe-inventory-editor`. Each release ZIP has a separate SHA-256 checksum file and contains a file manifest. These detect transfer errors or modifications but are not an independent cryptographic signature.

Warranty and liability for the project's own code follow the [MIT license](LICENSE). Dependencies have their own license terms.

### Interrupted restores

Startup defers recovery while server status is unknown or online. Stop Minecraft and the Bedrock server. Keep the world, backup, restore journal and any staging/rollback directories; do not remove them to clear the warning.

Use the **browser runtime or source checkout** with its Python environment. From that installation's directory, inspect the world's parent folder:

```powershell
.venv/Scripts/python.exe -m mcbe_editor.restore_recovery "C:/PATH/TO/WORLDS"
```

On Linux/macOS, use `.venv/bin/python`. For a running Docker editor, use its container name and container paths:

```bash
docker exec mcbe-editor python -m mcbe_editor.restore_recovery /worlds
```

**Desktop EXE:** close the editor and use its bundled recovery command from PowerShell:

```powershell
.\MCBEInventoryEditor.exe --recover "C:/PATH/TO/WORLDS"
```

All three commands inspect pending recovery without applying it. Only after stopping the server and reviewing the reported paths, repeat the command with `--confirm-server-stopped`. Read-only mode or a detected online server still blocks changes. Ambiguous world/rollback copies remain untouched and require manual assessment.

Keep the server and read-only settings (`MCBE_SERVER_HOST`, `MCBE_SERVER_PORT`, `MCBE_READ_ONLY`). Preserve any `--data-dir` in the command offered by a desktop warning. Desktop results appear in that directory's `restore-recovery.txt` (normally `data/restore-recovery.txt`); keep reports private. Desktop recovery needs neither a separate Python installation nor WebView2. Additional options are in the [desktop command-line guide](https://github.com/dadeeen/MCBE_Inventory_Editor/blob/main/docs/desktop.md#command-line-limits).
