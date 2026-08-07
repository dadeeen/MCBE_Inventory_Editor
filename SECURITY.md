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

Do not open a public issue for an unpatched vulnerability. Never attach real worlds, backups, player or audit exports, raw NBT, player names, XUID-like identifiers, private paths, IP addresses, usernames, tokens, passwords, cookies, or session data.

Include only what is needed:

- affected version or commit and operating mode;
- security impact and required attack conditions;
- minimal reproduction steps using synthetic data;
- sanitized logs or request metadata.

If private reporting is unavailable, open a minimal public issue asking for a private contact channel without disclosing the vulnerability.

We aim to acknowledge reports within three business days and provide an initial assessment within seven business days. Resolution time depends on severity and complexity. Please allow time for a coordinated fix and release before public disclosure.

Ordinary bugs belong in the issue tracker. Use the private channel for data-loss risks, authentication or authorization bypasses, unsafe path handling, secret or private-data exposure, and remotely triggerable writes.

## Security boundary

The editor reads and modifies Bedrock NBT and LevelDB directly. Backups, validation, revisions, file locks, write gates, CSRF/Origin checks, and authentication reduce risk but cannot guarantee correctness for every Bedrock version, add-on, or unusual world structure.

The supported boundary is:

- Local Mode bound to `127.0.0.1`; or
- an authenticated instance reachable only from a trusted LAN or private network;
- worlds that are fully stopped before writing;
- complete, independent world copies kept outside editor-managed paths.

Public hosting, untrusted multi-user access, broad host filesystem mounts, and direct internet ingress are outside the supported boundary. A reverse proxy does not change this boundary.

Before every edit, stop Minecraft or the server and create a complete copy outside the mounted world folder and `MCBE_BACKUP_ROOT`. Keep it until the result has been verified in Minecraft.

## Deployment essentials

- Enable password protection for LAN use.
- Leave `MCBE_TRUST_PROXY_HEADERS=false` unless a trusted reverse proxy is the only route to the app.
- Leave `MCBE_REQUIRE_SERVER_OFFLINE=true` for real server worlds and configure `MCBE_SERVER_HOST`.
- Treat `MCBE_REQUIRE_SERVER_OFFLINE=false` as an explicit unsafe override for stopped copies or archives only.
- For viewer deployments, use both `MCBE_READ_ONLY=true` and a `/worlds:ro` volume. Docker's `read_only: true` protects only the container root filesystem.
- Mount only the required worlds parent folder, never `/`, `/home`, or an entire NAS.
- Grant the unprivileged container process targeted access as UID `10001` or through a dedicated shared group. See “Write permissions for Docker worlds” in `README.md` for the concrete ACL and group variants.
- Do not use `chmod 777`, `privileged: true`, root execution, or deletion/bypassing of LevelDB locks as a permission workaround.
- Keep `/data` private and persistent. It contains setup state, backups, and potentially audit data.
- Use `MCBE_FAIL_ON_INSECURE_CONFIG=true` when an unauthenticated wide bind must abort startup.

Write operations re-check the server guard immediately before the final filesystem or LevelDB action. Unknown status can require explicit confirmation; a server later detected as online still blocks the write.

## Private data and diagnostics

Real worlds, backups, `.mcbe-player.zip` files, raw NBT, diagnostic reports, and audit exports must be treated as private. Renaming a world or deleting its icon does not anonymize LevelDB records.

The optional audit log can contain:

- remote IP addresses and configured usernames;
- world folder names and stable hashes of normalized world paths;
- truncated player-key previews and player-key hashes;
- action names, outcomes, request identifiers, and sanitized error details.

Hashes and truncation are risk reductions, not anonymization. World names, IP addresses, usernames, request metadata, and stable hashes may still identify a person, device, or installation. Do not publish audit files or exports without manual review and purpose-specific sanitization.

Secrets, CSRF tokens, passwords, session values, and detected full paths are redacted or reduced before audit storage. This does not make the resulting log public data. On POSIX, the app restricts newly created setup and audit files to the owner; on Windows, the containing directory's ACLs remain authoritative.

Private fixture worlds belong only under `fixtures/private/`, which is ignored and excluded from releases. Public fixtures require LevelDB/NBT-aware anonymization plus manual review; the supported scanner-fixture generator removes the original LevelDB files.

## Dependencies and verification

Local and release environments use hash-pinned dependencies for Python 3.12. The authoritative versions are in `pyproject.toml` and the lockfiles rather than duplicated in this policy.

For a full local security check:

```bash
python -m pip install --require-hashes -r requirements/bootstrap.lock
python -m pip install --require-hashes -r requirements/dev.lock
python scripts/security_check.py --require-pip-audit
```

Dependency findings are release signals, not runtime protection. Update affected packages deliberately and rerun the complete test and release checks; do not apply broad automatic upgrades.

Normal editing requires no outbound internet access. The optional item-data updater uses allowlisted HTTPS sources and size limits. Missing network access does not prevent startup.

## Releases and recovery

Official runtime packages are published only through the original repository's [GitHub Releases](https://github.com/dadeeen/MCBE_Inventory_Editor/releases). Versioned runtime ZIPs include a SHA-256 checksum and a file manifest. These detect transfer errors or modifications but are not an independent cryptographic signature.

App-created backups are checked for archive readability before restore. That check cannot prove that a world is semantically valid or compatible with a particular Minecraft version. The independent world copy remains the final recovery boundary.

Warranty and liability are governed by the exact text of the [MIT license](LICENSE) for this project's own code. Bundled Amulet components have separate, more restrictive license terms.
