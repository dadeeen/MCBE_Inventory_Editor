# Python dependency portability

The editor supports standard CPython **3.12, 3.13 and 3.14**. Python 3.15,
free-threaded CPython and alternative interpreters require separate validation.

## Runtime design

- `mcbe_editor/nbt.py` implements the binary NBT types and operations used by
  the editor with the Python standard library. Amulet-NBT, NumPy and
  Amulet-MUTF8 are no longer runtime dependencies.
- **Amulet-LevelDB 1.0.6** remains the Bedrock-compatible native storage engine.
  Its unchanged source builds on Python 3.13/3.14 with the locked Cython 3.2.4
  toolchain. Existing write locks, backups, atomic batches and rollback checks
  continue to surround native database writes.
- Windows x64 runtime packages include separately built and tested LevelDB
  wheels for Python 3.13/3.14. Setup validates their provenance, source/build
  hashes and license notices before installation. Existing supported virtual
  environments are retained. See [development.md](development.md) for the
  supported source-build and release procedures.
- Requirement sources and hash-locked outputs remain under `requirements/`.
  Canonical lock generation uses Python 3.12. Docker retains its pinned
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
mutation semantics, native database writes/reopens, cross-process locking and
process-exit recovery. The optional Amulet-NBT 2.1.8 reference environment is
restricted to Python 3.12 and is installed from `requirements/nbt-reference.lock`.

Reference comparisons cover:

- Generated trees in both byte orders, every empty list type, raw strings and
  floating-point bit patterns.
- Player editing through the actual service layer, with typed views and raw
  player records compared before and after saving.
- All supported mount types, profiles and applicable tame states, valid template
  cloning and synthetic fallback. Actor bytes, identifiers, stored positions,
  owner references and `digp` entries are independently checked.
- Player transfer in both directions, including target identity preservation.
- Export/import across all old/new codec combinations, with original player NBT
  bytes, manifests, previews and service rereads checked independently.

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
