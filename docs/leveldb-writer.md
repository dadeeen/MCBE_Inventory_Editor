# Pure-Python LevelDB write path

Status: experimental branch. The editor writes Bedrock world databases without
the native `amulet-leveldb` engine. `mcbe_editor.leveldb_writer` provides the
write session; `mcbe_editor.db.LevelDbAdapter` wraps it with the app's final
write gates and error translation. Reads use
`mcbe_editor.leveldb_readonly`, which the writer extends.

## Design: append a write-ahead log, never rewrite

A write session never modifies an existing database file. Each batch becomes
one logical record in a new write-ahead log (`NNNNNN.log`); tables, MANIFEST
and CURRENT stay byte-identical. Minecraft's LevelDB engine (Mojang's fork)
integrates that log itself the next time it opens the world, the same way it
recovers after an unclean shutdown:

- `DBImpl::Recover` lists the directory and replays every log numbered at or
  above the MANIFEST log number (or equal to the previous log number), sorted
  by number. It explicitly accepts logs that no MANIFEST record mentions.
  Mojang's fork (`leveldb-mcpe`, as bundled by amulet-leveldb 1.0.6) keeps this
  upstream behavior.
- A batch uses sequence numbers after the newest sequence of the MANIFEST and of
  every replayed log. Its values and deletions therefore shadow all older
  versions, wherever they are stored. Before writing, the session also checks
  each written key's stored versions and refuses if one is already newer (only
  possible with an inconsistent MANIFEST).
- The new log gets the number `max(next_file_number, highest file number + 1)`.
  Recovery marks that number as used. A table the engine creates during recovery
  may reuse the number with a different extension, which native LevelDB
  already handles after crashes.
- Recovery writes the replayed data to level-0 tables, starts a new log, writes
  a new MANIFEST and deletes the obsolete logs. The editor never compacts.

Batches are encoded and framed exactly like `WriteBatch` and
`log::Writer::AddRecord`: fixed 32 KiB blocks, 7-byte headers, masked CRC32C,
zero trailers below 7 bytes, and FIRST/MIDDLE/LAST fragments. A test compares
the resulting bytes with the native engine's own log for identical batches.

## Atomicity and durability

- One batch is one logical record. A crash can only leave an incomplete record
  at the end of the new log. Recovery (native and `leveldb_readonly`) ignores
  it, so a batch is applied completely or not at all.
- Every append is followed by `fsync`. On POSIX the directory is synced after
  the log is created.
- After each append, the session rereads its log strictly and compares every
  record. If an append or that check fails, the log is truncated to its last
  verified length and the session accepts no further writes. The caller treats
  such a batch as attempted but not committed and keeps the backup.
- Opening a world, reading it and closing it without writing changes no file.
  The only exception is a missing `LOCK` file, which is created empty, as the
  native engine does.
- A blank `db` directory (only `LOCK`/`LOG` files) is initialized like
  `DBImpl::NewDB`: `MANIFEST-000001` and `CURRENT`. A directory with other
  files but no `CURRENT` is refused. The native engine would create a new
  database there and later delete the unknown files.

## Exclusive access

The writable adapter must fail while Minecraft, a Bedrock server or another
editor process has the world open. On Linux this holds only for processes that
lock `LOCK`; a running Bedrock server is not detected there.

- POSIX: an exclusive `fcntl` lock on `LOCK` (`F_SETLK`, whole file), the lock
  LevelDB's POSIX environment uses. A process-wide registry refuses a second
  session in the same process, because `fcntl` locks are per process. This
  excludes other editor processes and native LevelDB engines such as
  `amulet-leveldb`. Bedrock Dedicated Server 1.26.51.1 on Linux creates no
  `LOCK` file and holds no lock (`/proc/locks` stays empty); it only keeps its
  MANIFEST, log and tables open, which this advisory lock cannot detect. Against
  a running Linux server, the server-status gate is therefore the only protection.
- Windows: Mojang's Windows environment (`util/env_win.cc`) only calls
  `LockFileEx` when `LOCK` is not empty, and LevelDB creates it empty. A running
  engine is excluded by share modes instead: it keeps write handles on
  `CURRENT`, its MANIFEST and its log, and it reads files without write sharing.
  The writer therefore holds `CURRENT` with write access and read-only sharing
  for the whole session. That handle fails if an engine already holds `CURRENT`,
  and a starting engine fails on it before recovery. Before writing, it also
  opens the MANIFEST and the replayed logs without write sharing; this fails if
  another process is writing to them. An exclusive `LockFileEx` over the whole
  `LOCK` file additionally excludes engines that lock that file. This also
  excludes BDS 1.26.51.1 through Docker Desktop's Windows bind mount while its
  database write handles are open.
- "In use" is reported as `LevelDbInUseError`, never as a permission problem.

These checks complement the app's server-status gate and interprocess world
lock; they do not replace them.

## Refusals

The session refuses to write, without changing any file, if:

- the newest log ends in a damaged or incomplete record. Placing a new log
  after it would hide the damage from later strict recovery checks. Loading
  the world once in Minecraft or on the server recovers it
  (`LevelDbUncleanLogError`);
- the MANIFEST names a comparator other than `leveldb.BytewiseComparator`, or
  lacks the file-number or sequence counters the native engine requires;
- a stored version of a written key is newer than the continuation sequence;
- the log would exceed the reader's 256 MiB MANIFEST/WAL budget.

## Validation

- `tests/test_leveldb_writer.py`: framing at every block position, batch
  encoding, session semantics, refusals (including a stored version with the
  batch's own sequence), rollback after an I/O failure or a failed read-back,
  lock behavior across threads and processes, files another program keeps open
  for writing (Windows), and truncation at every critical offset of a
  multi-block batch (old state or new state, never partial).
- Native reference tests (skipped without amulet-leveldb): byte-identical logs
  for identical batches, randomized sessions alternating between the native
  engine and the writer against a model, native reading of torn batches,
  and mutual exclusion in both directions. CI runs them on Windows and, for the
  POSIX `fcntl` lock, on macOS.
- The regular suite (service saves, imports, mount creation, backups and
  rollbacks) runs against the pure-Python writer.
- Private worlds (manual, temporary copies): each world is written by the
  writer, then compared key by key with the native engine. Existing files must
  stay byte-identical, and the native engine must fold the new log into its
  own tables.
- Bedrock Dedicated Server engine checks (`python -m scripts.engine_checks
  --suite all`): the item, extended, service and add-on suites write through the
  pure-Python adapter. BDS then loads, verifies and saves the world across
  reload cycles.

### Bedrock engine evidence and acceptance boundary

The engine reference is the official BDS **1.26.51.1** archive with SHA-256
`ad91d3b824e51ea50b5bb601c295cbd8f543a29b14315c2ad89ff27311e2d860`.
With CPython 3.12.14 and no Amulet runtime, the extended profile covers
13,037 cases across 1,623 item IDs in 502 carriers. The service profile covers
37 cases and ten backed-up saves on two synthetic player records; the add-on
profile covers twelve cases across six item IDs. All three profiles pass two
engine save/reload cycles.

These carriers and synthetic players do not establish real-player login,
Minecraft client saving, Ender Chest persistence after login, or mount gameplay.
The separate [Minecraft client experiment](mount-game-validation.md) describes
v0.5.21 with the native backend. Acceptance of this writer requires its own
client load/join, inventory/Ender Chest/equipment/effects/abilities checks,
mount interactions, save/exit/reload and backup restoration on disposable copies.
Run the complete CI matrix for the candidate revision before promotion.

## Dependency separation

Runtime and normal development environments use the project reader/writer without
Amulet-LevelDB. The independent native oracle is pinned in
`requirements/leveldb-reference.lock`, separately from `requirements/nbt-reference.lock`.
A required Windows Python 3.12 CI job installs both from wheels and runs the full
suite with `--require-references`; missing or unloadable imports fail the job.
Amulet-LevelDB 1.0.6 publishes no Linux wheels, so a required macOS Python 3.12
job runs the LevelDB suites against it for the POSIX lock path. The regular
Windows/Linux Python 3.12–3.14 matrix runs without either reference.

Windows setup, Docker and the runtime ZIP use the project's Python storage code.
Installation relies on hash-locked pip bootstrapping, offline Docker wheel
installation and release manifests. Setup leaves existing developer environments
unchanged; validate minimal installations in a fresh `.venv`. See [development.md](development.md).
