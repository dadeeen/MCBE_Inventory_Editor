# NBT codec performance

The Windows benchmark for editor v0.5.21 compares the project codec below with
Amulet-NBT 2.1.8 and NumPy 1.26.4. Timings cover parsing and serialization;
LevelDB, backups, HTTP and browser rendering are excluded.

Measured `mcbe_editor/nbt.py` SHA-256:
`b7a79d3d298d1bb8f7fc10743928ba24af0edac5406ada9ced31d2968a2b5356`.

## Method

- Both codecs use CPython 3.12.14 for the direct comparison, with identical
  uncompressed little-endian input and explicit Bedrock escape UTF-8 settings.
- Real records come from disposable copies of private fixtures: 30 saved
  animals and two complete player records containing an inventory. Large
  integer and byte arrays were synthetic stress cases, not observed player
  record sizes.
- Both implementations must reproduce every input byte for byte before timing.
  Inputs are in memory. Save timings use decoded objects; roundtrip timings
  include parsing and serialization.
- Each result is the median of seven warmed `timeit` samples. A seeded shuffle
  alternates codec order; GC is disabled during batches, which target 60 ms
  unless stated otherwise.
- Memory measurements use fresh subprocesses and Windows process counters after
  retaining decoded records and collecting garbage. Working-set increases
  include Python and native allocations, so they are approximate process costs.
- Source worlds remain unchanged; records, scripts and logs stay in ignored
  private or temporary paths.

## Same-runtime timing results

All times are milliseconds per complete row workload. The animal row is the
whole batch of 30 animals, not one animal.

| Input | Bytes | Amulet load | Project load | Amulet save | Project save | Amulet roundtrip | Project roundtrip |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30 animals | 85,951 | 0.879 | 16.444 | 1.632 | 5.169 | 2.487 | 21.446 |
| Smaller player | 8,581 | 0.093 | 1.778 | 0.177 | 0.596 | 0.271 | 2.459 |
| Larger player | 78,342 | 0.455 | 9.218 | 0.884 | 2.660 | 1.362 | 12.188 |
| 100,000 integer array elements | 400,007 | 0.029 | 27.061 | 0.028 | 15.574 | 0.099 | 47.827 |
| 250,000 byte array elements | 250,007 | 0.012 | 64.031 | 0.011 | 44.337 | 0.048 | 116.267 |

For these real records, the project codec was approximately 19–20 times slower
to load and 3 times slower to save; complete roundtrips were about 9 times
slower. Large packed arrays show a much greater relative difference because
NumPy/native bulk conversion is replaced by Python element-by-element work.
The project codec also has no compiled Cython parser, so these differences
cannot be attributed to NumPy alone.

## Memory results on Python 3.12

Approximate additional resident working set after retaining decoded objects:

| Retained workload | Amulet increase, MiB | Project increase, MiB |
| --- | ---: | ---: |
| 600 animals (20 copies of the 30-record batch) | 15.7 | 34.1 |
| 200 smaller players | 16.5 | 34.1 |
| 50 larger players | 23.2 | 46.6 |
| 10 arrays of 100,000 integers | 4.6 | 40.1 |
| 10 arrays of 250,000 bytes | 2.9 | 56.4 |

The measured subprocess baseline was lower for the project codec: approximately 22 MiB
resident versus 38 MiB after importing Amulet/NumPy. This does not imply lower
total editor memory for every workload: retained project objects grow faster.

## Python 3.14 and interpretation

On CPython 3.14.4, roundtrip medians for the project codec are approximately
3.0 ms and 14.0 ms for the two player records, 43.8 ms for the integer array and 105.4 ms
for the byte array. The 30-animal workload measures 39.4 ms with a 60 ms batch
target (32.4–59.8 ms sample range), and 27.2 ms with a 150 ms target and at least
five iterations per sample. This sensitivity to sampling settings limits
precise comparisons between Python 3.12 and 3.14.

Repeated parsing and large arrays can dominate codec costs. Measure complete
application operations separately to include database and backup work; these
codec ratios do not predict total load or save times.

## Player load path

Loading a player parses its stored record once for classification, inventory,
ender chest and compatibility analysis. The analysis runs before item origins
and equipment fallbacks are added. Saving parses a fresh record under the write
lock and validates the serialized result before writing.

String decoding tries strict UTF-8 first. Only strings with bytes that are not
valid UTF-8 take the escape path, which yields the same text for every input.

## Villager discovery projection

Entity discovery validates every actor's NBT. A byte prefilter selects likely
villagers for full decoding. Other actors retain only the five identifier fields
and `UniqueID`; discarded fields still undergo structural and resource-limit
validation. Decoded identifiers determine membership, and any projected match
is decoded in full. Legacy roots always use full decoding.

The scan traverses the whole database to detect duplicate IDs across entity
types and validate chunk indexes. Repeated reads use the
[villager snapshot cache](architecture.md#villager-read-snapshots); write planning
performs a fresh scan.

## Equine-template prefilter

`find_equine_template` checks for the literal UTF-8 bytes of its three accepted
identifiers before decoding an actor record. Possible matches undergo full NBT
decoding, identifier validation and the priority selection. Incidental strings
and malformed records cannot become templates through the prefilter. Regression
tests cover false positives and all five supported identifier field names for
horses, donkeys and mules.

The v0.5.21 benchmark uses CPython 3.14.4 and a disposable copy of a 247 MB
private world. Each timing includes adapter creation, full database iteration,
template selection and close. The table reports medians of three samples per
mode in alternating order. Both paths use the project codec; only the prefilter
differs. The native adapter is v0.5.21's Amulet-LevelDB write adapter, built
locally. The second row uses the reader from the project's
[Python storage implementation](leveldb-writer.md).

| Template-scan adapter | Without prefilter, seconds | With prefilter, seconds | Speedup |
| --- | ---: | ---: | ---: |
| Native adapter (v0.5.21 `LevelDbAdapter`) | 9.753 | 5.790 | 1.68× |
| `ReadonlyLevelDbAdapter` | 6.446 | 2.857 | 2.26× |

Both adapters decode **6,821 records without the prefilter and 78 with it** and
select identical template bytes and identifiers. Native sample ranges are
9.383–9.779 seconds without and 5.780–5.926 seconds with the prefilter. These
results apply to the horse `auto`/template scan, excluding HTTP, saves and backups.
