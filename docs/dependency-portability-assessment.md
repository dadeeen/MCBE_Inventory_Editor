# Python dependency portability

The editor supports standard CPython **3.12, 3.13 and 3.14**. Python 3.15,
free-threaded CPython and alternative interpreters require separate validation.

## Runtime design

- `mcbe_editor/nbt.py` implements the binary NBT types and operations used by
  the editor with the Python standard library. Amulet-NBT, NumPy and
  Amulet-MUTF8 belong only to the optional reference-test environment.
- `mcbe_editor/leveldb_readonly.py` and `mcbe_editor/leveldb_writer.py` read
  and write Bedrock's LevelDB with the standard library. The writer appends
  atomic batches to a new write-ahead log, which Minecraft integrates when it
  next opens the world; see [the writer design](leveldb-writer.md). Write locks,
  backups and rollback checks surround database writes.
- **Amulet-LevelDB 1.0.6** is an optional, independent test reference in
  `requirements/leveldb-reference.lock`. Runtime and regular dev installations
  exclude it. Windows setup uses hash-checked wheels for the remaining packages;
  no LevelDB bundles, compiler detection or native source builds are needed.
  Existing supported virtual environments are retained. See
  [development.md](development.md) for fresh-install and reference-test procedures.
- Requirement sources and hash-locked outputs are under `requirements/`.
  Canonical lock generation uses Python 3.12. Docker uses a pinned
  Python 3.12 base image; CI checks Python 3.12–3.14 on Windows and Linux.

## Codec contract

The codec supports all twelve binary NBT payload types and explicit byte order.
Application I/O uses uncompressed little-endian Bedrock NBT with escape UTF-8.
Unknown fields, signed integer widths, empty list types, original string/name
bytes, signed zero and floating-point payload bits survive unchanged round trips.
Ambiguous duplicate names, invalid types, truncation, trailing bytes and inputs
exceeding the byte, depth or element budgets are rejected.

The API intentionally covers the editor's needs. It does not reproduce Java
compressed NBT, modified UTF-8, SNBT, NumPy operations or unused Amulet convenience
APIs. Serialization returns bytes; guarded storage services own filesystem writes.
See [the upstream comparison](nbt-source-comparison.md) for deliberate differences.

## Executable validation

The normal suite checks preservation, malformed inputs, boundaries, copy and
mutation semantics, database writes/reopens, cross-process locking and
process-exit recovery on all three Python versions on Windows and Linux.
A separate required CI job on Windows Python 3.12 installs the LevelDB and NBT
reference locks using published wheels. It runs `scripts/test_full.py
--require-references` so missing or unloadable references cannot silently skip.
That job covers independent native recovery and codec/workflow comparisons;
normal runtime tests explicitly verify the references are absent.

Reference comparisons cover:

- Generated trees in both byte orders, every empty list type, raw strings and
  floating-point bit patterns.
- Player editing through the actual service layer, with typed views and raw
  player records compared before and after saving.
- All supported mount types, profiles and applicable tame states, valid template
  cloning and synthetic fallback. Actor bytes, identifiers, stored positions,
  owner references and `digp` entries are independently checked.
- Player transfer in both directions, including target identity preservation.
- Export/import with every exporter/importer pairing of the two codecs, with
  original player NBT bytes, manifests, previews and service rereads checked
  independently.

The workflow worker selects the codec before importing application services.
It compares the current service layer under both codecs, not an entire historical
application revision. Both sides must successfully perform the intended write;
equal failures cannot pass. Unselected database values are checked against the
original, and mutation controls prove that shared data loss is detected.

Private-world tests are explicit opt-ins, read only from ignored
`fixtures/private/`, and work exclusively on temporary copies. No playable worlds,
private exports or local test reports are shipped. Instructions and environment
flags are documented in [development.md](development.md).

## Performance and limits

The standard-library codec is slower than the compiled Amulet implementation,
especially for large arrays. The [benchmark](nbt-performance.md) records the
method and measured workloads; it is not an application latency guarantee.
Template discovery filters impossible identifiers before full NBT decoding.

A separate [Minecraft acceptance experiment](mount-game-validation.md) checks
sampled game behavior. Byte agreement between codecs alone cannot establish all
Minecraft semantics. Finite tests do not prove every future world format,
multiplayer state, equipment combination or hardware failure scenario. Backups
and exclusive access remain necessary when editing worlds.
