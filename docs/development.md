# Development, Tests, and Release Hygiene

This repository-only document is aimed at contributors and maintainers working in the full Git source tree. The public getting-started documentation is in the [README](../README.md). The project shape and dependency direction are summarized in the [architecture overview](architecture.md). Durable engineering contracts are documented in the [save contract](save_contract.md) and the [experimental mount specification](experimental_mount_creation_status.md).

## HTTP servers

`python main.py` uses Waitress (four worker threads), including `--debug`; debug
mode does not enable an interactive debugger or reloader. The local server binds
to loopback by default. `mcbe_editor.local_server` integrates the pinned Waitress
dispatcher and socket loop with heartbeat shutdown. It stops accepting new work,
keeps I/O running until active handlers finish, then allows up to five seconds to
flush buffered response bytes. During shutdown, a response whose full buffer
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

Docker CI loads the runtime image and runs `scripts/docker/smoke_image.sh` before
publication. The probe uses a read-only root, temporary data/world mounts and no
external network or host ports. It checks HTTP readiness, absence of the unused
Gunicorn control socket, and graceful termination; its own container is removed
on exit. This check also runs on ordinary Docker build jobs.

## Python portability

Python 3.12, 3.13 and 3.14 are supported. CI runs the complete application suite on
all three versions on Windows and Linux. Docker intentionally retains its pinned
3.12 base image. Runtime release ZIPs include Windows x64 LevelDB wheels for
3.13/3.14, built and tested by CI. A source checkout without those wheels first
prefers an installed Python 3.12 with a published wheel. A local 3.13/3.14 source
build requires Microsoft C++ Build Tools, the Windows SDK, and Cython 3.2.4
from the hash-locked build requirements. Python 3.15 is not enabled implicitly.

The project-owned `mcbe_editor.nbt` codec uses only the standard library.
Amulet-NBT, Amulet-MUTF8 and NumPy are absent from runtime and build requirements.
The separate `requirements/nbt-reference.lock` keeps Amulet-NBT as an independent
oracle for explicit tests on Python 3.12; do not install it in runtime environments.
Generate shared locks with Python 3.12, then validate installations on all supported
interpreters. See [the validation record](dependency-portability-assessment.md).

For codec changes, run the standard suite on every supported interpreter and,
from an isolated Python 3.12 reference environment on Windows, where the pinned
Amulet binary packages are available (CI uses its Windows Python 3.12 job):

```bash
python -m pip install --only-binary=:all: --require-hashes -r requirements/nbt-reference.lock
python -c "import amulet_nbt"
python -m pytest tests/test_nbt_reference.py tests/test_nbt_reference_write_path.py tests/test_nbt_reference_workflows.py tests/test_nbt_codec.py -q
```

`tests/test_nbt_reference_write_path.py` is the write-path differential: the same
player edit runs through the real service layer in two separate processes, once
with the project codec and once with Amulet-NBT installed as `mcbe_editor.nbt`
(the pre-migration binding), and the resulting logical database records must be
byte-identical. Each editable player must complete the requested edit; shared
save errors, unsuccessful results and unexpected no-op results fail instead of
becoming skips. An independent Amulet-based comparison also
checks untouched player NBT against the original, excluding only the worker's
explicitly edited slots and fields. Regression cases inject common data loss
and a change from negative to positive floating zero into both backends.
Its always-on case in the reference environment uses a synthetic world. With `MCBE_RUN_PRIVATE_WORLD_TESTS=1`
and `MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS=1` it repeats the comparison on temporary
copies of the git-ignored `fixtures/private` worlds (limited by
`MCBE_PRIVATE_WORLD_MAX_WORLDS`, default 3); no private data is part of the test.

`tests/test_nbt_reference_workflows.py` extends the service differential to mount
creation (all supported types and tame states, automatic fallback, and explicit
or automatic template cloning), player-state transfer in both directions, and
player export/import. Both codecs export local and server players; all four
exporter/importer combinations overwrite an existing player and create a new
record. The exported and imported `player.nbt` must equal the original bytes.
Mount actor NBT, chunk `digp` references and transferred player NBT must match
between backends. Every untouched database key/value is checked against the
original, and independent fixture expectations cover transferred gameplay,
preserved target identity, unknown nested data and template data. Service
failures, missing writes, missing backups and failed post-write validation fail
the comparison. Only path-dependent tokens, backup filenames, export timestamps
and ZIP container metadata are excluded; NBT bytes are never normalized.
These synthetic native-database cases run in the Python 3.12 oracle CI step.
The same two private-world flags and world limit enable an additional workflow
case on temporary copies of each selected world: transfer a real player into a
synthetic counterpart, export with both backends and import all four combinations,
then create a synthetic horse. Private worlds without editable players are not
eligible; failed eligible operations fail the test. Copies and real backup ZIPs
need temporary disk space (several times the largest selected world); completed
stages and import copies are removed before proceeding. Source fixtures remain
unchanged and no private payload is checked into the repository.
They compare current services using the old NBT binding, not an entire historical
application checkout, and do not replace Minecraft gameplay validation.

When running multiple local interpreter suites concurrently, give each process
its own `MCBE_DATA_ROOT` before Python starts. Some tests import the app during
collection, before session fixtures can isolate persisted server-guard state.

### Windows wheel bundles

`setup.bat` retains a supported existing `.venv`. For a new environment it checks
installed versions in descending order for a bundled or published wheel before
considering source builds. `scripts/windows_setup.py` checks the compiler and
SDK before installing anything when a source build is necessary. Its `--no-build`
option rejects source builds explicitly; installation is restricted to the
project's `.venv`.

The native wheel still dynamically links the Microsoft C++ runtime
(`MSVCP140.dll`). Setup checks that DLL before invoking pip and verifies a
real LevelDB import after installation. If the runtime is missing or outdated,
install or repair the current Microsoft Visual C++ Redistributable for the
Python architecture. No compiler is needed for this. A clean virtual
environment on a build machine does not prove deployment on a clean Windows
installation; keep that distinction in validation reports.

CI builds unchanged, hash-verified `amulet-leveldb==1.0.6` source separately on
standard CPython 3.13 and 3.14 for Windows x64. The build Python must contain
the exact tools from `requirements/build.lock`. For each version, use an
isolated build environment and run:

```powershell
python -m pip install --require-hashes -r requirements/bootstrap.lock
python -m pip install --only-binary=:all: --require-hashes -r requirements/build.lock
# Use cp313 when running the corresponding Python 3.13 interpreter.
python scripts/build_windows_wheel.py --output wheels/cp314
```

The builder optionally accepts `--source <locked-sdist.tar.gz>` for a cached
source archive; it still verifies its hash. `wheels/` is ignored by Git and
excluded from Docker. Each bundle contains the wheel, a provenance manifest,
and the upstream Amulet-LevelDB, LevelDB and zlib license notices. Provenance
records the source hash, build lock hash, tool versions, Python, wheel and
notice hashes, and CI identifiers when available. The upstream source archive
already includes a precompiled Windows zlib static library; the manifest
records this fact. These are traceable builds, not a claim of bit-for-bit
reproducibility or a cryptographic attestation of the build host.

CI installs each resulting wheel in a fresh `.venv` with source builds disabled,
then runs the complete application suite before making it available to the
runtime packaging job. To repeat the installation test, use a separate source
copy or extracted runtime ZIP that contains the appropriate `wheels/` bundle:

```powershell
py -3.14 -m venv .venv
.venv/Scripts/python.exe scripts/windows_setup.py install --no-build
```

`make_release_zip.py` validates every present bundle and includes it in
`RELEASE_MANIFEST.json`. The installer verifies provenance, metadata and hashes
before using a bundle, then installs the wheel by an exact local file URL with
pip hash checking. Other dependencies retain the canonical runtime lock.
Release downloads must still be checked against the separately published ZIP
checksum. Local runtime packaging includes bundles only when they have been
built; without them its source-build/Python-3.12 fallback applies. A deliberate
LevelDB upgrade must update the locks, the wheel-version constant, both builds,
license notices, and the installation/native-database checks together.

## Local check round

Recommended local check round on Windows:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes -r requirements/bootstrap.lock
.venv/Scripts/python -m pip install --only-binary=:all: --require-hashes -r requirements/build.lock
.venv/Scripts/python -m pip install --no-build-isolation --require-hashes -r requirements/dev.lock
.venv/Scripts/python scripts/smoke_check.py
.venv/Scripts/python -m pytest tests -q
.venv/Scripts/python -m ruff check
.venv/Scripts/python -m pip check
.venv/Scripts/python scripts/release_check.py --path .
```

For release/CI runs, `scripts/test_full.py` is authoritative because it hard-fails on missing native core dependencies:

```bash
python scripts/test_full.py -v
```

The GitHub Actions workflow runs on pull requests, pushes to `main`, version tags, a weekly schedule, and manually via **Actions → CI → Run workflow**. Pull requests, `main`, scheduled runs, and manual runs execute the full validation including a Docker build, but never publish. Only a version-tag push may publish the Docker image and create a GitHub Release; a separate publish workflow without tests does not exist. External actions are immutably pinned to full commit SHAs, with the corresponding release tag documented as a comment.

The remaining native Amulet-LevelDB dependency has no Linux wheels for the supported versions. Its source archives remain covered by the normal requirement hashes; CI and Docker additionally install the complete build toolchain from `requirements/build.lock` using wheels and hashes, then disable pip build isolation. This prevents an isolated build subprocess from resolving untracked build dependencies. `requirements/build-constraints.txt` is an exact fallback constraint, not the primary security boundary.

Both Docker stages use the same multi-architecture digest for `python:3.12-slim`. During a deliberate dependency or release refresh, inspect the current official digest with `docker buildx imagetools inspect python:3.12-slim`, review the reported Python/Debian version, update the single `PYTHON_BASE_IMAGE` argument in `Dockerfile`, and run the complete Docker and release checks. A digest update is a reviewed dependency change, not an automatic side effect of an ordinary build.

## Frontend tests and Node.js

The frontend logic under `static/` is primarily tested without an npm build step: the `tests/test_frontend_*.py` files execute the browser modules directly via `node -e`, and `tests/test_frontend_syntax.py` syntax-checks every JS file with `node --check` (pure parsing, no execution).

In addition, there are Playwright browser smoke tests under `tests/browser/`. These use `package.json` and `package-lock.json`; locally, the dependencies are installed on demand with `npm ci --ignore-scripts`. The command `npm run test:browser` automatically re-launches through the repository's `.venv` when present, starts two local Flask test servers, runs Playwright, and shuts the servers down again afterwards. `node_modules/` is a local working artifact and is not committed.

On Windows, `playwright.config.mjs` disables `TcpPortRandomizationWin` only in the test browser. Chromium 143 can encounter outgoing loopback port collisions (`WSAEADDRINUSE`, Windows error 10048) during repeated page loads, causing scripts to fail to load. The workaround preserves Playwright's other default Chromium flags and does not add retries or change application/OS networking settings. It reads the pinned Playwright runtime's internal switch list; review this integration and whether the workaround is still needed when upgrading Playwright/Chromium. Other platforms use the default launch options.

The authoritative Python, coverage, and managed browser runners keep per-run data under the operating system's temporary directory (`mcbe-inventory-editor-tests`) instead of the checkout. Set `MCBE_TEST_ARTIFACT_ROOT` to another external directory when required. Successful runs remove their unique runtime directories immediately; failed runs retain them for diagnosis and print their location. At runner startup, expired directories with a recognized project-generated name are removed after seven days, except when their owning process is still active. Unknown entries, links, junctions, and the current run directory are never pruned.

This requires a Playwright-supported **Node.js** version in the local `PATH`; CI uses Node.js 22. Additional JavaScript dependencies should not be introduced without prior discussion.

## Internationalization (i18n)

The UI is bilingual (German/English). German is the source language: user-facing strings appear in the code as German literals and are translated at runtime.

- Frontend: `static/i18n.js` provides `t(text, params)` plus the only supported locale-sensitive helpers: `localizedPair`, `compare`, `formatNumber`, `formatDate`, and `tp` (plural selection). Feature modules must use these helpers instead of reading `MCBEI18n.locale` directly. The English catalog lives in `static/i18n/en.json` and maps the exact German source string to its English translation. Placeholders use the `{name}` syntax and are substituted after catalog lookup.
- Templates: Jinja templates use the same `t()` via a template global; the active locale is decided server-side (cookie `mcbe_locale`, falling back to the `Accept-Language` header) so pages render without a flash of untranslated text.
- Fallback: a missing catalog entry falls back to the German source string. When adding or changing a user-facing string, update `static/i18n/en.json` in the same change.
- Templates: visible text and translatable attributes use Jinja `t()` explicitly. CSS-generated labels receive their localized values through translated `data-*` attributes; styles must not hard-code user-facing text.
- Backend messages: `mcbe_editor/i18n.py` provides a request-aware `t(text, **params)` that resolves the locale of the active Flask request (outside a request it falls back to German, the source language). API failures use `mcbe_editor/api_errors.py` and return stable `code`, `params`, `message_key`, and localized `message`; the legacy `error` alias remains during migration. The frontend localizes `message_key` again at the display boundary, so a stale or separately negotiated API locale cannot leak into the active page language. Localized responses include `Vary: Accept-Language, Cookie`.
- Tests: the pytest suite pins the Flask test client to German via `tests/conftest.py` (`Accept-Language: de` in `environ_base`), because assertions use the German source strings. Translation itself is covered by `tests/test_backend_i18n.py`; tests that exercise English send their own `Accept-Language` header, which overrides the pin. `tests/test_i18n_catalog.py` checks unique keys, placeholders, referenced literals, and rejects raw translatable template text; `tests/test_frontend_i18n.py` prevents feature modules from reintroducing raw locale checks or a DOM-translation fallback.
- Deliberately not translated: operator-facing console output (startup errors, CLI help, batch scripts) is English only; log messages and internal data-validation errors for the bundled item DB (`mcbe_editor/item_data.py`) stay in the source language.

Documentation languages: `README.md` and `SECURITY.md` are English with maintained German counterparts (`README.de.md`, `SECURITY.de.md`). Developer documentation under `docs/` is English only and is deliberately not translated, to avoid drift in security-relevant contracts.

## Bundled item database and enchantment max levels

`python -m scripts.update_db` regenerates `mcbe_editor/resources/item_db.json` from the `Mojang/bedrock-samples` release and the Microsoft Learn item listing. Identifiers, effects, and display names update from those sources. Normal runs always query the current release metadata first and reuse the cached ZIP only when release identity, size, and ZIP validation match. Enchantment **maximum levels** come from the reviewed table in `mcbe_editor/resources/enchantment_max_levels.json`.

That table is maintained by hand, so two situations need a maintainer:

- **Mojang adds an enchantment.** The update stops without writing and reports the missing identifiers. Add the reviewed levels to `enchantment_max_levels.json`, then run the update again.
- **Mojang changes the max level of an existing enchantment.** Mojang's metadata is used only for identifiers, so this is not detected automatically. `python -m scripts.update_db --check-wiki` compares the local table against the currently fetched Minecraft Wiki page and reports differences without changing a value. When the stable check reference changes, it records the wiki URL, revision id, content hash, fetch timestamp, and generation timestamp in `source_version.json` and the version history; the page content itself is never stored.

`--check-wiki` is a maintainer-only flag and the in-app update never passes it, so the running application never contacts `minecraft.wiki`. The web UI does not expose a cache switch. `--cache` / `--reuse-cached-release` is an internal replay mode that deliberately skips the online source lookups. After a successful dry run, the API may use it only after validating a scope-bound receipt covering the exact Mojang archive, the normalized Microsoft Learn item-list snapshot when items are in scope, and the starting item database and source-version files. The updater subprocess validates the same receipt again before processing. The icon updater follows the same automatic latest-release lookup and matching-cache reuse policy, but does not use the Item DB dry-run receipt.

A `wiki_*` stamp in `source_version.json` records a comparison made by that update. A later update without `--check-wiki` removes the stamp. The initial table values came from wiki revision 3648146; this is recorded in the table's `seeded_from` block.

Regression tests cover missing local values, table completeness, and wiki-only entries.

Inventory icon binding, preview limitations, and before/after verification are
documented in [Inventory icon resolution](icon-resolution.md).

## Curated item-availability labels

`mcbe_editor/resources/item_availability.json` is the reviewed source for the availability badges shown by the item browser. It is deliberately separate from generated `item_db.json`: Mojang's registry establishes that an identifier exists, while availability in Survival, Creative, command tooling, Education features, generated world state, or legacy saves is a curated gameplay claim.

The file records its Bedrock sample release, review date, and references. Rules use explicit item identifiers; data-value-specific exceptions live under `variants`. `mcbe_editor/item_availability.py` validates the schema, the bundled-source release, category coverage, duplicate assignments, registry membership, and variant ranges before the server starts. The check intentionally targets the bundled snapshot rather than a newer persistent database created by the in-app updater, so an update cannot make the application unbootable before the next curated review. When the persistent database has a newer versioned Mojang source and an explicit positive item registry, that exact registry becomes the effective addable set; same-release, older, unversioned, and legacy copies without an explicit registry continue to use the bundled reviewed set. IDs newly added since the bundled snapshot receive a derived, non-blocking `unreviewed` badge until the bundled data catches up. This derived category is added only to the client payload and does not change either persisted schema. If an official registry ID arrives before Mojang's public language catalogs contain its display name, the runtime catalog exposes a readable identifier-derived fallback in both locales; the fallback is not persisted and is replaced automatically once an official localization becomes available. Missing stack limits are explicitly unverified: new stacks use the safe creation bound of 1 while recorded original amounts remain preserved. Explicit 64s are stored per item, so registry additions cannot accidentally inherit a blanket 64. See [Item stack limits](item-stack-limits.md) for source precedence, validation, and the reviewed snapshot. Durability/data-value handling retains its existing runtime defaults.

One shared technical-ID policy is applied while generating the database, loading an existing persistent copy, and selecting icon targets. These block-only patterns override temporary exposure in Mojang's positive item registry. In particular, double-slab block states remain recognizable for lossless handling of existing worlds but are excluded from new-item creation and icon targets. Missing icons remain non-fatal and use the normal fallback behavior.

After refreshing the bundled item database, review this file against the linked Minecraft Wiki pages before shipping. In particular, check every new spawn egg, newly exposed Creative-only block, Education-gated identifier, and removed legacy identifier. Do not infer Creative-only status merely because an item is difficult or non-renewable in Survival.

## Dependency and security checks

Dependency security findings appear in CI in the `Dependency audit` step. Locally they can be checked with:

```bash
python scripts/security_check.py --require-pip-audit
docker build --target dependency-audit .
```

These checks do not change dependencies automatically. Security updates are applied deliberately, after which lockfiles are regenerated and the tests are run again.

## Test fixtures and private worlds

Real Bedrock worlds and player data are private data. Place them only under `fixtures/private/`; that folder is ignored, excluded from Docker builds, and protected by release checks.

Private worlds do not belong in `tests/fixtures/` and not in a release archive.

A private example world can be inspected without printing private values with:

```bash
python scripts/fixture_world.py inspect --world-zip /path/to/Sample-World.zip
```

Public test fixtures under `tests/fixtures/` may only contain non-playable scanner fixtures. They are created from a world copy and remove the original LevelDB files as well as binary world metadata:

```bash
python scripts/fixture_world.py make-scanner-fixture --world-zip /path/to/Sample-World.zip --output tests/fixtures/public_scanner_world.zip
```

These public fixtures are intended only for scanner, ZIP hygiene, and restore preview tests. A real world only counts as publishable once it has been anonymized with a LevelDB/NBT-aware procedure and manually reviewed afterwards.

`tests/fixtures/mount_reference.json` is the second kind of public fixture: distilled evidence rather than world data. The mount writer's per-type constants are claims about what Minecraft itself writes, and `tests/test_mount_writer_matches_game_reference.py` checks those claims on every run without needing a private world. Regenerate it from a reference world after a relevant Bedrock update:

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

On Windows, a single double-click workflow bundles the full check round, browser smoke tests, dependency audit, package build, and final archive verification:

```bat
scripts\release_windows.bat
```

The script aborts on a dirty Git working tree and does not overwrite an existing archive by default. Before the version has been tagged or published, an obsolete local archive can be replaced explicitly:

```bat
scripts\release_windows.bat --replace-existing --no-pause
```

The replacement is built under a temporary name and validated completely before it atomically replaces the old ZIP. The option refuses replacement when the matching local version tag already exists. Never replace an artifact for a published version; bump the version instead. Playwright is not shipped; if `node_modules/` is missing, `npm.cmd ci --ignore-scripts` must be run once.

The corresponding individual steps remain available for Linux and CI:

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

The runtime ZIP receives a version-specific file name and a separate SHA-256 checksum file. A failed check or Docker step prevents the release.

Among the things that do not belong in a release:

```text
.venv/
.git/
__pycache__/
.pytest_cache/
.pip-tools-cache/
.ruff_cache/
.mypy_cache/
.lockcheck/
.coverage*
htmlcov/
data/
dist/
fixtures/private/
.env
.env.*
player_exports/
*.mcbe-player.zip
RELEASE_MANIFEST.json as a local source artifact
real Bedrock worlds
```

`RELEASE_MANIFEST.json` is generated during the package build and belongs in the runtime archive. A copy lying in the local working tree is only an ignored build/check artifact and should not be committed.

The runtime archive uses an explicit allowlist. It contains the readable application code, static files, templates, required lockfiles, user-facing README and security policy, screenshots, and supported operational tools. Internal contracts, contributor documentation, tests, CI configuration, npm/Playwright, fixtures, the release builder, and remaining maintainer tools stay exclusively in the Git source tree. This keeps the package auditable without becoming a second development checkout.

The project root deliberately contains only tool-conventional configuration and direct entry points such as `pyproject.toml`, `Dockerfile`, Compose examples, `setup.bat`, and `start.bat`. Development, diagnostic, and release helpers live under `scripts/`; generated caches, runtime data, and build outputs remain ignored and are hard-excluded by release and Docker rules.

A release history only begins with the first published release via Git tags, GitHub Releases, or a comparable release channel. Until then, Git is the authoritative change history.
