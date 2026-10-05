# Pure-Python LevelDB write path

The editor reads and writes Bedrock world databases with the Python standard
library. `mcbe_editor.leveldb_writer` provides the write session and extends the
reader in `mcbe_editor.leveldb_readonly`; `mcbe_editor.db.LevelDbAdapter` wraps
it with the app's final write gates and error translation.

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

- One batch is one logical record. For a torn append that leaves an incomplete
  record at EOF, recovery (native and `leveldb_readonly`) ignores that record:
  the batch is applied completely or not at all. The truncation tests cover this
  failure model, not arbitrary storage corruption or every power-loss scenario.
- Every append is followed by `fsync`. On POSIX the directory is synced after
  the log is created; filesystems that report directory sync as unsupported
  (`EINVAL`, `ENOSYS`, `ENOTSUP`) continue, as backups do, while other I/O errors
  fail. Native LevelDB does not sync the directory for a new log at all. Windows
  has no directory flush in this implementation; durability also depends on the
  operating system, filesystem and storage device.
- After each append, the session rereads its log strictly and compares every
  record. If an append or that check fails, it attempts to truncate the log to
  its last verified length and accepts no further writes. Rollback I/O can also
  fail, so an error does not prove that no bytes were persisted.
- `last_write_reached_log()` tells whether the calling thread's last
  `put`/`put_batch` began appending its batch. `False` proves that none of its bytes were written:
  type, size and sequence checks, log creation and directory sync all come
  first. Only a failed call that reached the log counts as an unknown outcome;
  the [save contract](save_contract.md) describes the resulting API and UI
  behavior.
- Errors during log creation, directory synchronization or in-memory commit
  bookkeeping also end the write session; only the last of these can follow a
  durable batch. Close and reopen to read the actual state instead of retrying
  with a stale sequence counter.
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
  Like an unclean log, it is a refusal before any write: the API returns its
  message unchanged with HTTP 400, not as a server error.

These checks complement the app's server-status gate and interprocess world
lock; they do not replace them.

## Refusals

The session refuses to write, without changing existing database contents, if
any of the following checks fail. Acquiring access can, however, create an
empty `LOCK` file:

- the newest log ends in a damaged or incomplete record. Placing a new log
  after it would hide the damage from later strict recovery checks. Loading
  the world once in Minecraft or on the server recovers it
  (`LevelDbUncleanLogError`);
- the MANIFEST names a comparator other than `leveldb.BytewiseComparator`, or
  lacks the log-number, next-file or sequence counters;
- its next-file counter is not greater than its current/previous log number.
  Otherwise a new log could fall below recovery's cutoff and a successful write
  disappear after reopening;
- a referenced table is absent or is not a regular file, even when none of the
  batch's keys would read that table;
- a stored version of a written key is newer than the continuation sequence;
- allocating a new log would exhaust the native unsigned 64-bit file numbers;
- the log would exceed the reader's 256 MiB MANIFEST/WAL budget.

Oversized batch payloads are rejected before encoding copies and checksum work;
the final size check also accounts for physical record framing.

## Writer block cache

Each write session shares one LRU cache between all of its table readers: at
most 64 MiB of decompressed block data and 4,096 entries per active writer,
independent of the number of table files. Blocks larger than the budget are read
without being retained, and an allocation failure clears the cache and returns
the validated read. Only checked and decompressed immutable table blocks enter
the cache, keyed by table instance, offset and stored length, so matching
filenames in different worlds cannot alias. Cached blocks pass through the same
internal-key and version processing as uncached ones; WAL values and deletions
keep their precedence. Closing the database clears the cache. Readonly sessions
read blocks afresh because they can inspect a running world. Cache reuse assumes
exclusive offline access; it does not replace the server-status gate and does not
affect WAL synchronization or read-back.

The cache avoids repeated block reads, CRC checks and decompression while a
batch of nearby keys is validated. With CPython 3.12.14, validating and writing
1,000 scattered keys in a synthetic database of 60,000 records of about 1 KiB
takes a median of 984 ms without the cache and 406 ms with the 64 MiB limit;
smaller limits gain less on that workload. Single writes show no comparable
benefit, and a cold full-world scan and WAL replay remain separate costs.

## Player list after saves

`content_token()` returns `None` on a writer, so a write session never feeds the
reader-token player list cache. Instead, `committed_change()` reports the last
committed batch as `CommittedDbChange`: its original reader token, the expected
resulting token and the written entries. The resulting token is derived from the
original metadata and table identities and the digest of the new WAL bytes
already checked by read-back, never from a later observed world state. Failed
appends produce no receipt, and failing to allocate one does not fail a
committed write.

The service's `PlayerDirectory` uses this receipt to keep a discovered player
list across an ordinary save of one existing player; the
[save contract](save_contract.md) describes when it applies. The list is only an
optimization: selected records, revisions, write gates and backups stay
authoritative. With CPython 3.12.14 and worlds of 777,893 records, reloading after
a save takes 0.1–0.2 seconds with the kept list instead of 14–17 seconds for a new
discovery; the save itself, including its backup, takes the same 1.4–1.7 seconds
either way.

## Architectural boundary

This is a narrow offline editor backend, not a general-purpose LevelDB engine.
Minecraft stays responsible for recovery and compaction; the editor never
compacts, repairs or rewrites existing files. The benefit is a portable runtime
without native builds and a write path that leaves existing tables and metadata
untouched. The cost is owning format compatibility, corruption handling and the
reference tests; Python alone does not make storage safer.

Each write session adds a log until Minecraft next opens the world, and every
session replays the existing logs. The 256 MiB limit applies to the combined
MANIFEST/WAL input, not to the world size; table blocks have a separate 64 MiB
stored/decompressed limit. Python objects and temporary buffers can use
substantially more RAM. Exceeding a limit is an explicit refusal, not a silent
partial read.

A second production backend, a persistent player index or a custom compactor
needs a measured reason. If replaying large logs becomes the dominant cost,
profile that workload and compare a native prototype against the same
correctness tests. A maintained Bedrock-compatible native engine is an
alternative when its distribution and opening behavior fit. The Amulet-LevelDB
1.0.6 constructor can invoke automatic repair after corruption, so writing with
it requires an explicit repair policy and a backup boundary.

Changes to the log format, locking or recovery assumptions need the native
reference tests, the BDS engine checks and a Minecraft client load, save and
reload on a disposable world copy. Tests reduce risk but cannot certify every
future Bedrock format.

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
  The writer's positive recovery comparisons reject a native `lost/` repair
  archive: [Amulet 1.0.6 automatically calls `RepairDB` on corruption](https://github.com/Amulet-Team/Amulet-LevelDB/blob/1.0.6/src/leveldb/_leveldb.pyx).
  Merely opening successfully is not sufficient evidence. A deliberately
  damaged control proves that this test guard detects automatic repair.
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

### Bedrock Dedicated Server evidence

The [engine-check profiles](engine-checks.md) exercise the production
pure-Python writer against an explicitly selected official BDS build. They
cover item records in generated carriers, two synthetic player formats and
an owned conformance add-on through two engine save/reload cycles. The separate
real-client profile covers actual Inventory and Ender Chest persistence.
Server versions, case counts and archive/source hashes are maintained in
[Verified builds](engine-checks.md#verified-builds).

### Minecraft client evidence

Manual acceptance coverage uses Minecraft client **1.26.52** on Windows and
the editor on CPython **3.12.14**, with a fresh creative world and a copy of an
existing survival world. The verified behavior includes:

- Saves are refused as "in use" while Minecraft has the world open and succeed
  after the world is closed.
- Minecraft incorporates editor logs when opening the world and writes its own
  MANIFEST and tables. Editor changes take precedence over an older log left by
  Minecraft after closing the world.
- Inventory items, Ender Chest contents, an effect and an editor-created horse
  appear in the game as written. The horse supports taming and riding, and
  Minecraft saves that state.
- Each editor batch contains only the intended records. Unchanged player
  fields and untouched slots remain byte-identical, and the native reference
  reads the same records as the editor.
- Restoring an editor backup reproduces the world's files byte for byte, and
  Minecraft loads the restored state.

This client coverage includes a horse. The
[mount acceptance experiment](mount-game-validation.md) covers all supported
mount types with v0.5.21 and the native backend.

## Dependency separation

Runtime, Docker and normal development environments use the project
reader/writer without Amulet-LevelDB. The independent native oracle is pinned
separately in `requirements/leveldb-reference.lock`; the
[requirements README](../requirements/README.md) describes its installation and
the Windows and macOS CI jobs that require it. The regular Windows/Linux
Python 3.12–3.14 matrix runs without it.
