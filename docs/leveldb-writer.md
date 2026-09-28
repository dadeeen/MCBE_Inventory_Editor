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
  fail, so the caller records an unconfirmed write and keeps the backup. Reopen
  and inspect the actual state before retrying; an error does not prove that no
  bytes were persisted.
- `last_write_reached_log()` tells whether the last `put`/`put_batch` began
  appending its batch. `False` proves that none of its bytes were written:
  type, size and sequence checks, log creation and directory sync all come
  first. The service/API reports only a raised call that reached the log as
  `write_outcome_unknown`, retaining its backup; the UI then requires reload
  before another write, including mount-only batches whose player revision has
  not changed. A final gate rejection and failures before the first append are
  ordinary rejections with their own cause, for example a permission error when
  the database folder does not allow a new log file. See the
  [save contract](save_contract.md) for the distinction from post-write failure.
- Errors during log creation, directory synchronization or in-memory commit
  bookkeeping also end the write session; only the last of these can follow a
  durable batch. A verified batch may already be durable even if updating the
  session's view failed; close and reopen to read the actual state instead of
  retrying with a stale sequence counter.
- Opening a world, reading it and closing it without writing changes no file.
  The only exception is a missing `LOCK` file, which is created empty, as the
  native engine does.
- A blank `db` directory (only `LOCK`/`LOG` files) is initialized like
  `DBImpl::NewDB`: `MANIFEST-000001` and `CURRENT`. A directory with other
  files but no `CURRENT` is refused. The native engine would create a new
  database there and later delete the unknown files.

## Writer block cache

Each writer session shares one LRU cache between all of its table readers.
It retains at most **64 MiB of decompressed block data** and at most 4,096
entries; Python bookkeeping adds some memory overhead. This is a lazy upper
bound, not a reservation. It is not multiplied by the number of table files.
Blocks larger than the cache budget are read normally without being retained.
Cache allocation failure clears retained entries and returns the validated read.

Only successfully checked/decompressed immutable table blocks enter the cache.
An entry uses its table instance's unique identity plus block offset and stored
length, so matching filenames in different worlds cannot alias. Cached blocks
pass through the same internal-key/version processing as uncached ones; WAL
values and deletions keep their precedence. Closing the database clears the
cache. Ordinary readonly sessions read blocks afresh because they can inspect
a running world. Writer cache reuse assumes exclusive offline access and does
not replace the server-status gate. The cache does not affect WAL
synchronization or read-back.

The main benefit is avoiding repeated block reads, CRC checks and decompression
while validating batches of nearby keys. A cold full-world player scan and WAL
replay remain separate costs.

The sizing comparison uses CPython 3.12.14 and Amulet-LevelDB 1.0.6 as the
independent recovery reference. Synthetic databases contain 20,000 or 60,000
roughly 1 KiB records. Each value is the median of three fresh copies, with
cache-size order shuffled between repetitions and full native comparison after
recovery. Timings describe these workloads, not a general latency guarantee.

| Cache limit | 1,000 adjacent keys / 20k records | 1,000 scattered keys / 20k records | 1,000 scattered keys / 60k records |
| --- | ---: | ---: | ---: |
| Disabled | 813 ms | 878 ms | 984 ms |
| 8 MiB | 150 ms | 588 ms | 885 ms |
| 16 MiB | 148 ms | 326 ms | 749 ms |
| 32 MiB | 151 ms | 231 ms | 574 ms |
| 64 MiB | 150 ms | 236 ms | 406 ms |

The largest workload retains about 54.5 MiB; adjacent keys retain about 1.1 MiB.
Single-write times of 4.3–4.9 ms show no comparable benefit. The 64 MiB limit
applies per active writer, so concurrent worlds can use multiples of that budget.

## Evidence for derived player metadata

`content_token()` returns `None` on a writer. Instead, `committed_change()`
optionally reports the last successfully committed batch as `CommittedDbChange`:
its original reader token, expected resulting token, and immutable byte entries.
The resulting token is derived from the original metadata/table identities and
the digest of the new WAL bytes already checked by read-back. It never adopts
an independently observed later world state. Failed appends offer no receipt;
failure to allocate optional evidence does not fail an otherwise committed write.

The service's separate `PlayerDirectory` can carry a discovered list forward
only when its token matches the receipt's original state and an ordinary save
updates one existing, recognizable player. It reclassifies that record and
retains unchanged entries, including unusual player keys. The next reader must
match the expected resulting token before using the list. External changes,
recovery, restore, unknown-key saves and combined writes trigger a new discovery.
Table tokens include file identity so replacing a table with preserved size and
timestamps cannot reuse a list from the previous file.

This metadata is only an optimization. Selected records are read and validated
directly; revisions, write gates, backups and locked pre-write comparisons remain
authoritative. Imports and multi-record operations do not promote the directory.
The cache is bounded to eight worlds per service process and is not persisted.

The service comparison uses CPython 3.12.14, three changed-stat saves per
temporary world copy, and a control that disables only directory promotion.
The OS page cache is retained. For 777,893-record worlds, median reload after
save is 13,770 ms versus 219 ms with WAL-heavy data and 17,283 ms versus 89 ms
with table-heavy data. The control performs one discovery scan after every save;
the maintained directory performs none. Save time including backup is about
1.4–1.7 seconds in both variants, without a consistent difference. Small-world reloads
measure 46 ms versus 20 ms. Complete directory contents and unrelated records
agree with fresh discovery and the Amulet-LevelDB 1.0.6 reference.

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

## Architectural boundary

This is a narrow offline editor backend, not a replacement for a general-purpose
LevelDB engine. Keep Minecraft responsible for recovery and compaction. The
benefit is a portable runtime and a write path that does not rewrite existing
tables or metadata. The cost is ownership of format compatibility, corruption
handling and regression tests; Python alone does not make storage safer.

A maintained Bedrock-compatible native engine is a reasonable alternative when
its distribution and opening behavior meet the product requirements. Performance
alone does not justify owning another writer. The Amulet-LevelDB 1.0.6 constructor
can invoke automatic repair after corruption, so using it requires an explicit
repair policy and a backup boundary. If independent reference tests and Minecraft
acceptance cannot be maintained, prefer a supported native writer with a narrower
runtime matrix over expanding this implementation's scope.

Keep the writer cache and state-checked player directory. They address repeated
block work and repeated whole-world discovery independently. Larger caches do
not remove first discovery, WAL replay or backup costs. Each session replays the
WAL, and each write session adds a log until Minecraft next recovers the world.
The 256 MiB limit applies to combined MANIFEST/WAL input, not total world size;
Python objects and temporary buffers can use substantially more RAM. Table blocks
have a separate 64 MiB stored/decompressed limit. These are explicit refusals,
not silent partial reads.

Do not add a second production backend, a persistent player index or a custom
compactor without measured need. If large-WAL replay remains the dominant cost,
profile that workload and compare an isolated native prototype using the same
correctness tests. Moving everything to C++ or C# would retain the format and
locking obligations while adding a new integration and distribution surface.

Before merging, require the full CI matrix, native comparisons and real BDS
reload tests; before release, repeat a Minecraft client load/save/reload on a
disposable copy. Tests reduce risk but cannot certify every future Bedrock format.

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
