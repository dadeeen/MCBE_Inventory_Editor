# Architecture

MCBE Inventory Editor is a modular monolith with one Python application and a
shared web frontend that requires no build step.

The optional [Windows desktop host](desktop.md) wraps the same application in a
WebView2 window. Its isolated PyInstaller build bundles Python; browser and
Docker deployments keep their existing entry points and dependencies.

## Backend dependency direction

```text
main.py
  -> *_api_routes.py / *_page_routes.py
       -> services.py and focused domain modules
            -> NBT, LevelDB, backup, filesystem, and runtime adapters
```

- `main.py` is the composition and security root. It creates the Flask app,
  owns authentication, CSRF, rate limiting, write gates, runtime state, and
  route registration. Route functions in this file should stay thin.
- Route modules own request orchestration, public error mapping, audit calls,
  and the order in which security gates are applied. Their frozen `*RouteDeps`
  dataclasses make external dependencies explicit and allow isolated tests.
- `services.py` owns multi-step application workflows such as player save,
  transfer, import, backup, validation, and rollback. Ordered transaction
  phases may remain together when splitting them would obscure commit status or
  cleanup guarantees.
- Focused domain modules own data rules and transformations. For example,
  `inventory.py` is the stable inventory facade, `mounts.py` builds mount
  previews, and `mount_placement.py` refines and evaluates placement candidates.
- Adapter modules such as `db.py`, `leveldb_readonly.py`, `bedrock_nbt.py`, and
  `backup.py` isolate external formats and side effects.

Dependencies point downward. Domain and adapter modules must not import
`main.py`, and domain helpers must not depend on Flask request or response
objects. Cross-cutting policy enters route and service code through explicit
dependencies or small shared modules.

`desktop.py` and `mcbe_editor/desktop_app.py` are entry-point composition code
above this dependency graph: they start the application from `main.py` and own
the native window lifecycle. `desktop_navigation.py` contains the Windows-only
document-origin policy and external-link adapter. They do not add a second editing service.

## Write boundary

Player and workspace writes follow [save_contract.md](save_contract.md).
Mount-specific rules are in
[experimental_mount_creation_status.md](experimental_mount_creation_status.md).

The important ordering is:

1. validate the request, loaded revision, source data, and server guard;
2. prepare the complete write without mutating LevelDB;
3. create and verify one backup;
4. repeat the final write gate and stale-data checks;
5. perform the atomic record or batch write;
6. validate the committed state and report commit status accurately;
7. preserve a usable backup whenever rollback or manual recovery may be needed.

Code extraction must preserve that visible sequence. A shorter function is not
an improvement if it hides whether a failure happened before or after commit.

The strict mypy entry points include the complete backup adapter, shared source
consistency checks, backup settings/result contracts, and `write_transaction.py`.
The latter owns immutable binary write plans and the attempted/committed boundary
used by player saves, workspace batches, direct mount creation, imports, and
migration. Backup path results retain their runtime string compatibility through
`BackupPath`; listing and restore-token shapes are explicit `TypedDict`s.

Run `python -m mypy` for this scope. The remaining orchestration in
`services.py`, `mount_write.py`, `main.py` and dynamic NBT transformations in
`_inventory_core.py` are outside strict coverage. Keep existing entry points
strict when extending it.

## Villager read snapshots

`VillagerDirectory` caches raw resident bytes and serialized list data by
database `content_token()` and locale. Its process-local LRU holds at most eight
entries, 32 MiB of accounted payload and 10,000 residents per entry. Oversized
snapshots and readers without a token bypass the cache.

Cache hits return list data or decode one resident, including its exact legacy
root; misses run full discovery. The token covers metadata, WAL content and
immutable table identities. A scan is exposed for later browsing only after
the service validates its world revision before and after reading. Its binding
includes the world path, revision and locale, within the same LRU limits.

Details use the retained scan bytes without reopening the live database. Older
scans remain available until eviction, with a shared read-only notice when the
server runs or the world changes. After eviction, a disk read must still match
the original world revision; a newer state cannot replace it. Preview and save
planning always run fresh discovery with global duplicate-ID and chunk-index
checks.

`/api/villagers/map_players` reads saved positions when the map opens, validating
the current world revision before and after reading. Positions may come from a
newer revision than the villager list; `snapshot_stale` marks the list read-only
in that case or while the server runs. Loaded positions remain visible until a
rescan or a switch to another world. Closing the map, changing worlds or
rescanning cancels pending requests; late responses cannot replace another
snapshot. Loading and retry states leave the list usable.
Arriving markers update dimension choices and fit an untouched map. Manual zoom
and pan remain until an explicit fit or a change of world, rows, filters or map
selection. **Find player** centers the selected player in their saved dimension.

## Frontend composition

`templates/index.html` declares the browser-module load order. Feature files
publish one `window.MCBE...` namespace and normally expose pure helpers or a
controller factory. `static/app.js` is the frontend composition root: it owns
the current editor session and wires controllers through getter, setter, and
callback dependencies.

The frontend uses no bundler or application framework. Keep these rules:

- feature logic stays in its feature module instead of growing `app.js`;
- controllers receive state access and side effects through their dependency
  object rather than copying session state into another global;
- reusable validation and payload rules stay DOM-independent where practical;
- a new namespace is loaded before `app.js` and covered by the script-order and
  namespace consistency tests;
- persistence behavior is tested across form logic, payload construction, and
  backend application whenever an invariant crosses those boundaries.

## State and compatibility rules

Minecraft NBT is not a closed schema. Unknown, unsupported, wrong-typed, and
newer-version fields are data that must normally be preserved, not normalized
away. Editing code therefore distinguishes between:

- a field the editor owns and may create;
- a supported existing field that may be changed;
- an unchanged legacy value that may be outside the UI's supported range;
- opaque data that must be carried through untouched;
- a requested edit that cannot be represented safely and must be rejected.

These distinctions belong in the shared save contract and regression tests,
not only in a frontend control or a single NBT writer.

## Known hotspots

- `main.py`: composition, global runtime state, and the publication of a
  prepared item catalog after an item-database update. Feature code reads
  catalog data through `item_data`; do not reload modules at runtime.
- `services.py`: transactional workflows. Extract pure preparation or
  validation only when the before/after-commit ordering remains obvious.
- `_inventory_core.py`: broad NBT domain implementation behind the stable
  `inventory.py` facade. Split only along a stable domain seam, such as item
  metadata or player effects, and keep the facade compatible.
- `static/app.js`: frontend session state and controller wiring. New feature
  behavior belongs in a module; small delegating wrappers are acceptable.
- `templates/index.html` and `static/style.css`: large view assets. Split them
  only when a cohesive UI area can move without introducing template or CSS
  indirection for its own sake.

## Change checklist

For a change that reads or writes player/world data:

1. identify the owning route, workflow, domain module, and documented contract;
2. decide how absent, unchanged, opaque, invalid, and newly created data behave;
3. verify descriptor, database, lock, and backup ownership on every exit path;
4. add the narrow unit regression and, for cross-boundary behavior, a payload or
   route/service regression;
5. run the relevant focused tests, then the repository's full check round.

Prefer a direct function and a tested data structure over a generic repository,
event bus, dependency-injection container, or speculative abstraction.
