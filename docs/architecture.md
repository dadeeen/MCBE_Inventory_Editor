# Architecture

MCBE Inventory Editor is a modular monolith. The application deliberately keeps
one deployable Python process and a browser frontend without a build step. The
goal is explicit ownership and testable boundaries, not a framework-heavy
layer model.

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

## Write boundary

Player and workspace writes are intentionally conservative. The durable rules
live in [save_contract.md](save_contract.md); the experimental mount guarantees
live in [experimental_mount_creation_status.md](experimental_mount_creation_status.md).

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

## Frontend composition

`templates/index.html` declares the browser-module load order. Feature files
publish one `window.MCBE...` namespace and normally expose pure helpers or a
controller factory. `static/app.js` is the frontend composition root: it owns
the current editor session and wires controllers through getter, setter, and
callback dependencies.

The frontend deliberately has no bundler or application framework. Keep these
rules:

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
- an unchanged legacy value that may be outside today's UI limits;
- opaque data that must be carried through untouched;
- a requested edit that cannot be represented safely and must be rejected.

These distinctions belong in the shared save contract and regression tests,
not only in a frontend control or a single NBT writer.

## Known hotspots

- `main.py`: composition, global runtime state, and the localized item-database
  module reload. Do not spread runtime reloads into feature modules.
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
