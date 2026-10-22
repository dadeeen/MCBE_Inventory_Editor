# Development, Tests, and Release Hygiene

This document is for contributors and maintainers working in the full Git source tree. User installation and operation are in the [README](../README.md).

| Topic | Detailed documentation |
| --- | --- |
| Structure and dependencies | [Architecture](architecture.md), [dependency portability](dependency-portability-assessment.md), [lockfiles](../requirements/README.md) |
| Windows EXE | [Desktop architecture, build and validation](desktop.md) |
| Saving and storage | [Save contract](save_contract.md), [LevelDB writer](leveldb-writer.md) |
| Item catalog | [Names and source comparisons](item-localization.md), [stack limits](item-stack-limits.md), [icons](icon-resolution.md) |
| Experimental mounts | [Creation contract](experimental_mount_creation_status.md), [in-game validation](mount-game-validation.md) |
| Compatibility evidence | [Bedrock engine checks](engine-checks.md), [NBT source comparison](nbt-source-comparison.md), [NBT performance](nbt-performance.md) |

## HTTP servers

`python main.py` uses Waitress (four worker threads), including `--debug`; debug
mode does not enable an interactive debugger or reloader. The local server binds
to loopback by default. `mcbe_editor.local_server` integrates the pinned Waitress
dispatcher and socket loop with graceful shutdown. Browser startup leaves the
server running until the console is stopped. `MCBE_LOCAL_HEARTBEAT_SHUTDOWN=true`
explicitly enables the legacy timeout; suspended background tabs can trigger it.
The frontend sends heartbeats only with this local opt-in, including setup/login.
Desktop forces the option off and follows its native window lifecycle. During
shutdown, the local server stops accepting new work,
keeps I/O running until active handlers finish, then allows up to five seconds to
flush buffered response bytes. A response whose full buffer
blocks a worker is disconnected after five seconds; application work such as a
save is still awaited. A stuck application handler can therefore delay shutdown;
a second Ctrl+C interrupts the wait. Recheck this integration when upgrading
Waitress. HTTP tests in `tests/test_local_server_cli.py` cover keep-alive,
concurrent requests, shutdown, port conflicts, upload limits and proxy policy.

Flask enforces the exact 10 MiB decoded request-body limit. Waitress limits the
buffered transfer to that limit plus 64 KiB for chunk framing and its exclusive
upper bound. Requests exceeding the transport limit receive Waitress's HTTP 413
response before reaching Flask's JSON error handler. Proxy header trust remains
controlled by the existing application
configuration and ProxyFix. Docker keeps Gunicorn with `--no-control-socket`:
the app does not use its management socket and the container root stays read-only.

The bundled Docker command uses one worker process and four threads. First-run
setup state and session signing keys are held in each process; live setup changes
are not synchronized across custom multi-worker deployments. Complete setup with
one worker, then restart all workers so they load the saved decision and signing
key together. Interprocess write locks prevent concurrent world writes but do not
provide authentication-state synchronization.

Docker CI loads the runtime image and runs `scripts/docker/smoke_image.sh` before
publication. The probe uses a read-only root, temporary data/world mounts and no
external network or host ports. It checks HTTP readiness, absence of the unused
Gunicorn control socket, and graceful termination; its own container is removed
on exit. This check also runs on ordinary Docker build jobs.

## Python portability

Python 3.12, 3.13 and 3.14 are supported. CI runs the application suite on all
three versions on Windows and Linux without Amulet libraries. Docker uses a
pinned Python 3.12 base image. Python 3.15 is not enabled implicitly.

The project-owned NBT codec and Bedrock LevelDB reader/writer use only the standard
library. Runtime and ordinary dev installs contain no Amulet, NumPy or Cython.
A separate Windows Python 3.12 CI job installs `requirements/leveldb-reference.lock`
and `requirements/nbt-reference.lock` from published wheels into an isolated virtual
environment and runs the full suite with `--require-references`. Lockfile and
dependency audits use that same environment, excluding packages preinstalled on
the runner. Missing or unloadable references fail that job before
optional tests can silently skip. The reference engine has no Linux wheels, so a
macOS Python 3.12 job runs the LevelDB suites against it to cover the POSIX `fcntl`
lock and recovery. Release packaging and Docker publication depend on both jobs as
well as the application matrix and fresh runtime setup checks.

Generate normal locks with Python 3.12 on Windows or Linux. To also regenerate or
check the reference locks, use Windows Python 3.12 and add `--include-references`;
no source build tools are needed. See [requirements](../requirements/README.md)
and [the validation record](dependency-portability-assessment.md).

For codec changes, run the standard suite on every supported interpreter and,
from an isolated Python 3.12 reference environment on Windows, where the pinned
Amulet binary packages are available (CI uses its dedicated reference job):

```bash
python -m pip install --only-binary=:all: --require-hashes -r requirements/leveldb-reference.lock -r requirements/nbt-reference.lock
python scripts/test_full.py --require-references -q
# For a focused codec comparison after the full suite:
python -m pytest tests/test_nbt_reference.py tests/test_nbt_reference_write_path.py tests/test_nbt_reference_workflows.py tests/test_nbt_codec.py -q
```

`tests/test_nbt_reference_write_path.py` compares player edits through the real
service in separate project-codec and Amulet-NBT processes.
`tests/test_nbt_reference_workflows.py` extends that comparison to mount creation,
state transfer and all codec pairings for export/import. Intended writes must
succeed; equal failures or unexpected no-ops cannot pass. Resulting NBT must match
byte for byte, and untouched data is independently compared with the original.
Only path-dependent tokens, backup filenames, export timestamps and ZIP metadata
are excluded. See [reference coverage](dependency-portability-assessment.md#executable-validation)
for scope and limits.

Synthetic cases run in the reference CI job. The two
[private-world opt-ins](#test-fixtures-and-private-worlds) also enable these
comparisons on temporary copies, limited by `MCBE_PRIVATE_WORLD_MAX_WORLDS`
(default 3). Worlds without editable players are ineligible; failed eligible
operations fail the test. Allow several times the largest selected world's size
for copies and backups. Source fixtures stay unchanged and private payloads
remain outside the repository.

When running multiple local interpreter suites concurrently, give each process
its own `MCBE_DATA_ROOT` before Python starts. Some tests import the app during
collection, before session fixtures can isolate persisted server-guard state.

### Windows runtime installation

`setup.bat` retains a supported existing `.venv`. For a new environment it selects
the newest installed standard CPython 3.12–3.14. `scripts/windows_setup.py`
restricts installation to the project's `.venv`, installs the pinned pip and
runtime wheels with hashes, runs `pip check`, and verifies imports in a fresh
process. Setup uses published wheels without source builds or LevelDB bundles.

CI creates a runtime ZIP, extracts it, and installs it in a fresh environment on
each supported Python version. It checks that Amulet, NumPy and Cython are absent
and that the app imports with an intact release manifest. Repeat using an extracted
runtime ZIP or a separate clean checkout:

```powershell
py -3.14 -m venv .venv
.venv/Scripts/python.exe scripts/windows_setup.py install
```

Setup never uninstalls development or reference packages from an existing
environment. Use a fresh project copy and `.venv` to
verify the minimal runtime. Preserve runtime data separately when replacing an
installation. Check release downloads against their published ZIP checksums.

## Local check round

Optional version-specific checks against the real Bedrock engine are documented
in [Engine checks](engine-checks.md). The reusable runner and script-only probe
are public developer tools; server binaries, generated worlds and local reports
remain ignored. They are excluded from the application runtime bundle.

Recommended local check round on Windows:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes -r requirements/bootstrap.lock
.venv/Scripts/python -m pip install --only-binary=:all: --require-hashes -r requirements/dev.lock
.venv/Scripts/python scripts/smoke_check.py
.venv/Scripts/python -m pytest tests -q
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m pip check
.venv/Scripts/python scripts/release_check.py --path .
```

For release/CI runs, use `scripts/test_full.py`. The regular suite requires the project modules; the separate reference job additionally passes `--require-references`:

```bash
python scripts/test_full.py -v
```

CI runs the full validation, including a Docker build, on pull requests, `main`, version tags, a weekly schedule and manual **Actions → CI → Run workflow** requests. Only version tags may publish; see [release hygiene](#release-hygiene). External actions are pinned to full commit SHAs with their release tag in a comment.

The `Lint` job requires both `ruff check .` and `ruff format --check .` to pass.
Package and release jobs depend on it. Apply formatting locally with
`python -m ruff format .` using the Ruff version from the locked development
requirements. `pyproject.toml` defines the shared style, including LF line endings
consistent with `.gitattributes`. Keep broad formatting changes separate from
functional changes so reviews remain focused.

Docker uses a wheel-download stage with hash verification and installs those wheels offline in the runtime stage. The pinned pip bootstrap is shared with setup and CI. The runtime uses the project's Python storage implementation and contains neither native compilers nor LevelDB-specific system packages. Independent reference libraries stay outside this image.

Both Docker stages use the same multi-architecture digest for `python:3.12-slim`. During a deliberate dependency or release refresh, inspect the current official digest with `docker buildx imagetools inspect python:3.12-slim`, review the reported Python/Debian version, update the single `PYTHON_BASE_IMAGE` argument in `Dockerfile`, and run the complete Docker and release checks. A digest update is a reviewed dependency change, not an automatic side effect of an ordinary build.

## Frontend tests and Node.js

The frontend logic under `static/` is primarily tested without an npm build step: the `tests/test_frontend_*.py` files and a few backend test modules execute the browser modules directly through `run_node` from `tests/node_runner.py`. It starts one `node -e` process per script from the repository root, so scripts share no module state, fails the test on a non-zero exit with Node's output, and stops a script after 60 seconds unless the test passes its own `timeout`. `tests/test_frontend_syntax.py` syntax-checks every JS file with `node --check` (pure parsing, no execution).

In addition, there are Playwright browser smoke tests under `tests/browser/`. These use `package.json` and `package-lock.json`; locally, the dependencies are installed on demand with `npm ci --ignore-scripts`. The command `npm run test:browser` automatically re-launches through the repository's `.venv` when present, starts two local Flask test servers, runs Playwright, and shuts the servers down again afterwards. `node_modules/` is a local working artifact and is not committed.

The managed test servers bind to loopback and use the normal application with a larger read-request quota, because many independent browser sessions share the same test IP within one minute. Mutation and authentication quotas remain active. Production entry points use the standard limits; dedicated Python tests verify rate limiting independently of browser-suite traffic.

On Windows, `playwright.config.mjs` disables `TcpPortRandomizationWin` only in the test browser. Chromium 143 can encounter outgoing loopback port collisions (`WSAEADDRINUSE`, Windows error 10048) during repeated page loads, causing scripts to fail to load. The workaround preserves Playwright's other default Chromium flags and does not add retries or change application/OS networking settings. It reads the pinned Playwright runtime's internal switch list; review this integration and whether the workaround is still needed when upgrading Playwright/Chromium. Other platforms use the default launch options.

The authoritative Python, coverage, and managed browser runners keep per-run data under the operating system's temporary directory (`mcbe-inventory-editor-tests`) instead of the checkout. Set `MCBE_TEST_ARTIFACT_ROOT` to another external directory when required. Successful runs remove their unique runtime directories immediately; failed runs retain them for diagnosis and print their location. At runner startup, expired directories with a recognized project-generated name are removed after seven days, except when their owning process is still active. Unknown entries, links, junctions, and the current run directory are never pruned.

This requires a Playwright-supported **Node.js** version in the local `PATH`; CI uses Node.js 22. Additional JavaScript dependencies should not be introduced without prior discussion.

## Internationalization (i18n)

The UI is bilingual (German/English). German is the source language: user-facing strings appear in the code as German literals and are translated at runtime.

- Frontend: `static/i18n.js` provides `t(text, params)` plus the only supported locale-sensitive helpers: `localizedPair`, `compare`, `formatNumber`, `formatDate`, and `tp` (plural selection). Feature modules must use these helpers instead of reading `MCBEI18n.locale` directly. The English catalog lives in `static/i18n/en.json` and maps the exact German source string to its English translation. Placeholders use the `{name}` syntax and are substituted after catalog lookup.
- Templates: visible text and translatable attributes use Jinja `t()`. CSS-generated labels use translated `data-*` attributes, never hard-coded text. The server selects the locale from `mcbe_locale`, falling back to `Accept-Language`, so pages render in the selected language.
- Fallback: a missing catalog entry falls back to the German source string. When adding or changing a user-facing string, update `static/i18n/en.json` in the same change.
- Backend messages: `mcbe_editor/i18n.py` provides a request-aware `t(text, **params)` that resolves the locale of the active Flask request (outside a request it falls back to German, the source language). API failures use `mcbe_editor/api_errors.py` and return stable `code`, `params`, `message_key`, and localized `message`; the legacy `error` alias remains during migration. The frontend localizes `message_key` again at the display boundary, so a stale or separately negotiated API locale cannot leak into the active page language. A specific backend message already names the failed action and is shown as it is; the page puts its own context (for example `Fehler beim Speichern: {error}`) only in front of a technical reason: an unreadable answer, an error answer without a message, a bare `error`, or a generic handler message such as `Interner Serverfehler` (`errorMessageInContext` in `static/api_client.js`). Because a refusal is such a specific message, the save routes put `Speichern abgelehnt:` in front of one that names only its reason, such as `Welt-Ordner existiert nicht.` (`save_refusal_payload` in `mcbe_editor/api_errors.py`). Localized responses include `Vary: Accept-Language, Cookie`.
- Tests: the pytest suite pins the Flask test client to German via `tests/conftest.py` (`Accept-Language: de` in `environ_base`), because assertions use the German source strings. Translation itself is covered by `tests/test_backend_i18n.py`; tests that exercise English send their own `Accept-Language` header, which overrides the pin. `tests/test_i18n_catalog.py` checks unique keys, placeholders, referenced literals, and rejects raw translatable template text; `tests/test_frontend_i18n.py` prevents feature modules from reintroducing raw locale checks or a DOM-translation fallback.
- Operator-facing console output, CLI help, batch scripts and internal logs are outside the request-locale translation contract. Their language varies by tool; do not assume that all console output is English.

Documentation languages: `README.md` and `SECURITY.md` are English with maintained German counterparts (`README.de.md`, `SECURITY.de.md`). Developer documentation under `docs/` is English only and is deliberately not translated, to avoid drift in security-relevant contracts.

## Bundled item database and enchantment max levels

`python -m scripts.update_db` regenerates `mcbe_editor/resources/item_db.json` from the `Mojang/bedrock-samples` release and the Microsoft Learn item listing. Identifiers, effects, and display names update from those sources. Normal runs always query the current release metadata first and reuse the cached ZIP only when release identity, size, and ZIP validation match. Enchantment **maximum levels** come from the reviewed table in `mcbe_editor/resources/enchantment_max_levels.json`.

Before processing, the updater validates the exact registries and the canonical
English/German language files required by the selected scope. Missing, duplicate,
empty or malformed required sections stop the update before a write or a new
verification receipt. Effect and enchantment labels must cover their source
registry in both languages; `fatal_poison` is the documented exception because
Mojang supplies no dedicated label. Item localization retains its existing alias,
preservation and fallback rules. The locale parsers accept Mojang's `potion.*`
effect labels and `enchantment.*` names, including their source aliases, while
excluding potion item names, levels, durations and description text. Legacy
`effect.*` and `enchant.*` names remain supported. These validation semantics use
updater contract version 3, so older receipts require a fresh check.

That table is maintained by hand, so two situations need a maintainer:

- **Mojang adds an enchantment.** The update stops without writing and reports the missing identifiers. Add the reviewed levels to `enchantment_max_levels.json`, then run the update again.
- **Mojang changes the max level of an existing enchantment.** Mojang's metadata is used only for identifiers, so this is not detected automatically. `python -m scripts.update_db --check-wiki` compares the local table against the currently fetched Minecraft Wiki page and reports differences without changing a value. When the stable check reference changes, it records the wiki URL, revision id, content hash, fetch timestamp, and generation timestamp in `source_version.json` and the version history; the page content itself is never stored.

`--check-wiki` is a maintainer-only flag and the in-app update never passes it, so the running application never contacts `minecraft.wiki`. The web UI does not expose a cache switch. `--cache` / `--reuse-cached-release` is an internal replay mode that deliberately skips the online source lookups. After a successful dry run, the API may use it only after validating a scope-bound receipt covering the exact Mojang archive, the normalized Microsoft Learn item-list snapshot when items are in scope, and the starting item database and source-version files. The updater subprocess validates the same receipt again before processing. The icon updater follows the same automatic latest-release lookup and matching-cache reuse policy, but does not use the Item DB dry-run receipt.

A `wiki_*` stamp in `source_version.json` records a comparison made by that update. A later update without `--check-wiki` removes the stamp. The initial table values came from wiki revision 3648146; this is recorded in the table's `seeded_from` block.

The updater emits a structured report separately from the localized console log.
It compares saved and checked sources, item-data changes and validation findings.
A confirmed atomic write emits `applied: true`; the reader uses the last report.
The API reloads confirmed writes even if skipped sections cause a nonzero exit,
and the UI retains the partial-failure warning.

A preview leaves persistent data unchanged. Applying uses the confirmed scope
and matching review receipt; a failed request discards that receipt. A current
result disables applying that scope until another check or scope change, while
explicit repair workflows may request a verification write. Change details list
actual changes and unresolved findings; deliberately preserved names appear in
the separate technical log. See [Item names and source comparisons](item-localization.md).

Each update replaces the browser's technical output. Successful source changes append metadata to `source_version_history.json`; unchanged sources do not extend this history. A full apply can refresh the verification timestamp without rewriting the item database. The Item-DB download keeps one replaceable archive and item-list snapshot; the icon updater keeps its current managed release ZIP. Progress snapshots are removed when requests finish; a later tracked request removes crash leftovers older than 24 hours.

The Microsoft Learn source identity uses `microsoft_item_listing_items_hash`, a canonical hash of the parsed item mapping. The full HTML hash remains provenance; page-layout changes and fetch timestamps do not establish a different item-source identity. Metadata without the normalized fingerprint retains its original verification semantics and requires one source-metadata update to persist that fingerprint. Cached listings already contain a verified normalized mapping and supply the same fingerprint as an online fetch. Review receipts bind the complete cache files and starting files, including HTML provenance, so changed inputs still invalidate an outstanding apply receipt.

Regression tests cover missing local values, table completeness, and wiki-only entries.

Item names use Mojang's `de_DE`/`en_US` files plus reviewed distinctions for legacy IDs and variants. Both runtime loading and the updater apply the exact-match migration policy in `mcbe_editor/item_name_policy.py`, preserving custom names. When refreshing the bundled snapshot, compare it with the chosen release and review obsolete label pairs; see [Item names and source comparisons](item-localization.md). Tooltip-only language keys are excluded through `NON_ITEM_LANG_KEY_IDS` in `mcbe_editor/item_registry_policy.py`.

Inventory icon binding, preview limitations, and before/after verification are
documented in [Inventory icon resolution](icon-resolution.md).

## Curated item-availability labels

`mcbe_editor/resources/item_availability.json` is the reviewed source for the availability badges shown by the item browser. It is deliberately separate from generated `item_db.json`: Mojang's registry establishes that an identifier exists, while availability in Survival, Creative, command tooling, Education features, generated world state, or legacy saves is a curated gameplay claim.

The file records its Bedrock sample release, review date, and references. Rules use explicit item identifiers; data-value-specific exceptions live under `variants`. `mcbe_editor/item_availability.py` validates the schema, the bundled-source release, category coverage, duplicate assignments, registry membership, and variant ranges before the server starts. The check intentionally targets the bundled snapshot rather than a newer persistent database created by the in-app updater, so an update cannot make the application unbootable before the next curated review. When the persistent database has a newer versioned Mojang source and an explicit positive item registry, that exact registry becomes the effective addable set; same-release, older, unversioned, and legacy copies without an explicit registry use the bundled reviewed set. IDs newly added since the bundled snapshot receive a derived, non-blocking `unreviewed` badge until the bundled data catches up. This derived category is added only to the client payload and does not change either persisted schema. If an official registry ID arrives before Mojang's public language catalogs contain its display name, the runtime catalog exposes a readable identifier-derived fallback in both locales; the fallback is not persisted and is replaced automatically once an official localization becomes available. Missing stack limits are explicitly unverified: new stacks use the safe creation bound of 1 while recorded original amounts remain preserved. Explicit 64s are stored per item, so registry additions cannot accidentally inherit a blanket 64. See [Item stack limits](item-stack-limits.md) for source precedence, validation, and the reviewed snapshot. Durability editing requires an explicit item limit; a runtime fallback is not evidence that an item is damageable.

The updater reports missing display names for valid official registry IDs as warnings, allowing that runtime fallback to take effect after an update. Malformed registry identifiers, invalid existing name entries, and invalid limits remain blocking audit errors. The integration test exercises the dry run, persisted update, and runtime catalog with a registry addition that neither public localization source names yet.

One shared technical-ID policy is applied while generating the database, loading an existing persistent copy, and selecting icon targets. These block-only patterns override temporary exposure in Mojang's positive item registry. In particular, double-slab block states remain recognizable for lossless handling of existing worlds but are excluded from new-item creation and icon targets. Missing icons remain non-fatal and use the normal fallback behavior.

After refreshing the bundled item database, review this file against the linked Minecraft Wiki pages before shipping. In particular, check every new spawn egg, newly exposed Creative-only block, Education-gated identifier, and removed legacy identifier. Do not infer Creative-only status merely because an item is difficult or non-renewable in Survival.

## Slot and container item fields

`static/slot_detail_logic.js` owns `itemDamageEditorModel` and `itemFormModel` for both the normal slot editor and container children. Durability uses explicit catalog entries; known data variants use the catalog's named choices. Other items have no editable raw data field. An unchanged value from the same source item remains valid even when unknown, negative, or outside a known range. Container children carry `source_index`; they do not need an inventory-level digest just to display and retain their original value. Only the backend validates the actual source NBT and its provenance.

The selected container slot is fixed in the UI, item builder, and `withChild` update. Existing bundle capacity, stack, and nesting rules remain in the shared container model and writer. UI drafts and final world saves continue to be separate steps.

The common backend validator enforces the same damage policy for every write entry point, including bulk edits. Without documented durability or variants it permits `0` or the unchanged original value. Changing another field does not normalize unknown data or replace untouched NBT tags. The three potion item IDs reuse the existing 0–46 table, which matches [Microsoft's documented Bedrock potion values](https://learn.microsoft.com/en-us/minecraft/creator/documents/create-custom-potions?view=minecraft-bedrock-stable) (documented version 1.21.111) and the project's existing engine-check definitions. Display/icon compatibility for `tipped_arrow` does not establish editable variants.

Regression coverage is in `tests/test_item_damage_policy.py`, the catalog/slot-detail/container frontend tests, and the `item damage policy` DE/EN browser cases. The writer tests compare untouched NBT values and types, including unusual originals; browser tests cover visible controls, variant round trips, fixed slots, adjacent items, and undo.

## Dependency and security checks

Dependency security findings appear in CI in the `Dependency audit` step. Locally they can be checked with:

```bash
python scripts/security_check.py --require-pip-audit
docker build --target dependency-audit .
```

These checks do not change dependencies automatically. Security updates are applied deliberately, after which lockfiles are regenerated and the tests are run again.

## Private player diagnostics

The browser runtime ZIP and source checkout include `scripts/export_player_raws.py`. The portable EXE does not expose this Python CLI. Stop Minecraft or the server before inspecting a world, and run from the installation directory using its virtual environment:

```powershell
.venv/Scripts/python.exe scripts/export_player_raws.py list --world "C:/PATH/TO/WORLD"
.venv/Scripts/python.exe scripts/export_player_raws.py export --world "C:/PATH/TO/WORLD" --all --bundle-zip
```

On Linux/macOS, use `.venv/bin/python`. Exports contain raw, non-anonymized NBT; keep them private and out of commits, releases and public issues. For interrupted world restores, use the separate [recovery instructions](../SECURITY.md#interrupted-restores).

## Test fixtures and private worlds

Real Bedrock worlds and player data are private data. Place them only under `fixtures/private/`; that folder is ignored, excluded from Docker builds, and protected by release checks.

Private worlds do not belong in `tests/fixtures/` and not in a release archive.

Most tests need no world at all: `tests/nbt_fixtures.py` builds synthetic player records (`make_minimal_player_tag`, `make_full_player_tag`, `make_player_bytes`) from `mcbe_editor.nbt` alone, so any test can use them without loading Flask or the service. `tests/conftest.py` holds only the automatic fixtures: isolated runtime storage, the German test client, the rate-limit reset, and the read factory for `tests/test_service.py`.

A private example world can be inspected without printing private values with:

```bash
python scripts/fixture_world.py inspect --world-zip /path/to/Sample-World.zip
```

Public fixtures must be synthetic or individually reviewed, anonymized and non-playable. The scanner-fixture generator removes original LevelDB files and binary world metadata from a world copy:

```bash
python scripts/fixture_world.py make-scanner-fixture --world-zip /path/to/Sample-World.zip --output tests/fixtures/public_scanner_world.zip
```

These generated scanner fixtures serve scanner, ZIP hygiene and restore preview tests. Anonymization and manual review remain required before any world-derived fixture is committed. Isolated entity NBT records belong under `tests/data/` only after individual review under its [fixture contract](../tests/data/README.md).

`tests/fixtures/mount_reference.json` is a separate kind of public fixture: distilled evidence rather than world data. The mount writer's per-type constants are claims about what Minecraft itself writes, and `tests/test_mount_writer_matches_game_reference.py` checks those claims on every run without needing a private world. Regenerate it from a reference world after a relevant Bedrock update:

```bash
python scripts/export_mount_reference.py --world "fixtures/private/<reference world>" --output tests/fixtures/mount_reference.json
```

A useful reference world holds at least two adult specimens of every rideable type, spawned and left untouched. Two are the minimum because a single specimen cannot separate a type-invariant value from a per-specimen roll; the exporter refuses to record values for such a type and says so. Only type-invariant evidence is written: coordinates, entity ids and owner ids are recorded by tag name only, and custom names are dropped entirely.

Optional integration tests against locally stored private worlds run only after explicit opt-in. Without the flag they are skipped; write tests operate exclusively on temporary copies:

```powershell
$env:MCBE_RUN_PRIVATE_WORLD_TESTS = "1"
python -m pytest tests/test_private_world_integration.py -m private_world -q

$env:MCBE_RUN_PRIVATE_WORLD_TESTS = "1"
$env:MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS = "1"
python -m pytest tests/test_private_world_integration.py -m "private_world and destructive" -q
```

The scope can be limited for large private worlds:

```powershell
$env:MCBE_PRIVATE_WORLD_MAX_WORLDS = "1"
$env:MCBE_PRIVATE_WORLD_MAX_PLAYERS = "2"
```

## Release hygiene

Normal work in the source tree does not require a constantly rebuilt runtime package. Only before a state is handed over or published must it be committed, unambiguously versioned, verified, and packaged.

For the browser runtime ZIP on Windows, a double-click workflow bundles the full check round, browser smoke tests, dependency audit, package build, and final archive verification:

```bat
scripts\release_windows.bat
```

The script aborts on a dirty Git working tree and does not overwrite an existing archive by default. Before the version has been tagged or published, an obsolete local archive can be replaced explicitly:

```bat
scripts\release_windows.bat --replace-existing --no-pause
```

The replacement is built under a temporary name and validated completely before it atomically replaces the old ZIP. The option refuses replacement when the matching local version tag already exists. Never replace an artifact for a published version; bump the version instead. Playwright is not shipped; if `node_modules/` is missing, `npm.cmd ci --ignore-scripts` must be run once.

The portable EXE has a separate Windows x64/Python 3.12 build described in [Desktop build](desktop.md#build). `release_windows.bat` does not build it. CI's `desktop` job creates its ZIP and checksum and runs the packaged startup probe.

The corresponding individual browser-runtime packaging steps remain available for Linux and CI:

```bash
python scripts/release_check.py --path .
python scripts/make_release_zip.py --output dist/mcbe_inventory_editor_vX_runtime.zip
python scripts/release_check.py --archive dist/mcbe_inventory_editor_vX_runtime.zip
```

Pushing a tag named `v<project-version>` is the official release path. CI compares it exactly with the version from `pyproject.toml` before anything is published.

| Trigger | Docker result | GitHub Release |
| --- | --- | --- |
| Pull request, `main`, schedule, or manual run | Build and validation only | None |
| Stable tag `vX.Y.Z` | `X.Y.Z`, `X.Y`, `sha-...`, and `latest` | Stable release |
| Pre-release tag | Full version and `sha-...`; no minor tag or `latest` | Pre-release |

A tagged GitHub Release attaches four build assets:

- `mcbe_inventory_editor_v<version>_runtime.zip` and its `.sha256` file;
- `mcbe_inventory_editor_<version>_windows_x64.zip` and its `.sha256` file.

GitHub also supplies its own source snapshots. The two README screenshots are inside both application ZIPs, not separate release assets. The GitHub Release job waits for `package`, `docker-publish` and `desktop`; failure in any required job prevents that release. GHCR publication depends on `package` and its own Docker checks, not on `desktop`, so it can finish before a later desktop failure.

Exclude development environments, Git metadata, caches, coverage reports and
previous build outputs. Runtime `data/`, `.env*`, private fixtures, real worlds,
backups and player exports must never enter a release.

`RELEASE_MANIFEST.json` is generated during each package build and belongs in both application archives. A copy lying in the local working tree is only an ignored build/check artifact and should not be committed.

The runtime archive uses an explicit allowlist. It contains the readable application code, static files, templates, required lockfiles, user-facing README and security policy, screenshots, and supported operational tools. Internal contracts, contributor documentation, tests, CI configuration, npm/Playwright, fixtures, the release builder, and remaining maintainer tools stay exclusively in the Git source tree. This keeps the package auditable without becoming a second development checkout.

The archive check validates physical ZIP entries before looking up manifest files.
Duplicate or case-colliding names, noncanonical or unsafe paths, links and special
files fail the check. Each manifest path must be unique and its recorded size and
SHA-256 must match the archive bytes. A manifest hash does not establish trust in
the source; it establishes the exact contents of an unambiguous package.

The desktop archive follows its own build allowlist: EXE, `_internal`, manifest, licenses and user documentation. It contains no BAT setup, Compose files or general Python CLI; developer instructions must not imply that it is a source checkout.

The project root deliberately contains only tool-conventional configuration and direct entry points such as `pyproject.toml`, `Dockerfile`, Compose examples, `setup.bat`, and `start.bat`. Development, diagnostic, and release helpers live under `scripts/`; generated caches, runtime data, and build outputs remain ignored and are hard-excluded by release and Docker rules.
