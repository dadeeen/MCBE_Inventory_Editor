# Development, Tests, and Release Hygiene

This repository-only document is aimed at contributors and maintainers working in the full Git source tree. The public getting-started documentation is in the [README](../README.md). The project shape and dependency direction are summarized in the [architecture overview](architecture.md). Durable engineering contracts are documented in the [save contract](save_contract.md) and the [experimental mount specification](experimental_mount_creation_status.md).

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

Native Amulet packages have no Linux wheels for the supported versions. Their source archives remain covered by the normal requirement hashes; CI and Docker additionally install the complete build toolchain from `requirements/build.lock` using wheels and hashes, then disable pip build isolation. This prevents an isolated build subprocess from resolving untracked build dependencies. `requirements/build-constraints.txt` is an exact fallback constraint, not the primary security boundary.

Both Docker stages use the same multi-architecture digest for `python:3.12-slim`. During a deliberate dependency or release refresh, inspect the current official digest with `docker buildx imagetools inspect python:3.12-slim`, review the reported Python/Debian version, update the single `PYTHON_BASE_IMAGE` argument in `Dockerfile`, and run the complete Docker and release checks. A digest update is a reviewed dependency change, not an automatic side effect of an ordinary build.

## Frontend tests and Node.js

The frontend logic under `static/` is primarily tested without an npm build step: the `tests/test_frontend_*.py` files execute the browser modules directly via `node -e`, and `tests/test_frontend_syntax.py` syntax-checks every JS file with `node --check` (pure parsing, no execution).

In addition, there are Playwright browser smoke tests under `tests/browser/`. These use `package.json` and `package-lock.json`; locally, the dependencies are installed on demand with `npm ci --ignore-scripts`. The command `npm run test:browser` automatically re-launches through the repository's `.venv` when present, starts two local Flask test servers, runs Playwright, and shuts the servers down again afterwards. `node_modules/` is a local working artifact and is not committed.

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

`python -m scripts.update_db` regenerates `mcbe_editor/resources/item_db.json` from the `Mojang/bedrock-samples` release and the Microsoft Learn item listing. Identifiers, effects, and display names update from those sources. Enchantment **maximum levels** come from the reviewed table in `mcbe_editor/resources/enchantment_max_levels.json`.

That table is maintained by hand, so two situations need a maintainer:

- **Mojang adds an enchantment.** The update stops without writing and reports the missing identifiers. Add the reviewed levels to `enchantment_max_levels.json`, then run the update again.
- **Mojang changes the max level of an existing enchantment.** Mojang's metadata is used only for identifiers, so this is not detected automatically. `python -m scripts.update_db --check-wiki` compares the local table against the currently fetched Minecraft Wiki page and reports differences without changing a value. When the stable check reference changes, it records the wiki URL, revision id, content hash, fetch timestamp, and generation timestamp in `source_version.json` and the version history; the page content itself is never stored.

`--check-wiki` is a maintainer-only flag. The in-app update never passes it — `mcbe_editor/update_script_runner.py` builds only `--dry-run`, `--force`, `--cache`, and `--only` — so the running application never contacts `minecraft.wiki`.

A `wiki_*` stamp in `source_version.json` records a comparison made by that update. A later update without `--check-wiki` removes the stamp. The initial table values came from wiki revision 3648146; this is recorded in the table's `seeded_from` block.

Regression tests cover missing local values, table completeness, and wiki-only entries.

## Curated item-availability labels

`mcbe_editor/resources/item_availability.json` is the reviewed source for the availability badges shown by the item browser. It is deliberately separate from generated `item_db.json`: Mojang's registry establishes that an identifier exists, while availability in Survival, Creative, command tooling, Education features, generated world state, or legacy saves is a curated gameplay claim.

The file records its Bedrock sample release, review date, and references. Rules use explicit item identifiers; data-value-specific exceptions live under `variants`. `mcbe_editor/item_availability.py` validates the schema, the bundled-source release, category coverage, duplicate assignments, registry membership, and variant ranges before the server starts. The check intentionally targets the bundled snapshot rather than a newer persistent database created by the in-app updater, so an update cannot make the application unbootable before the next curated review. The client receives only that validated structure and maps stable category keys to localized labels and descriptions.

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
