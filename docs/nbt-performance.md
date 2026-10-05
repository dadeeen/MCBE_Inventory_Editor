# NBT codec performance measurement

Measured on Windows for v0.5.21. This compares the project codec, identified by
the hash below, with Amulet-NBT 2.1.8 and NumPy 1.26.4; it does not measure
overall editor response time. LevelDB, backups, HTTP and browser rendering are
outside the timed region.

Measured `mcbe_editor/nbt.py` SHA-256:
`b7a79d3d298d1bb8f7fc10743928ba24af0edac5406ada9ced31d2968a2b5356`.

## Method

- Both codecs used CPython 3.12.14 for the direct comparison, with identical
  uncompressed little-endian input and explicit Bedrock escape UTF-8 settings.
- Real records came from disposable copies of private fixtures: 30 saved
  animals and two complete player records containing an inventory. Large
  integer and byte arrays were synthetic stress cases, not observed player
  record sizes.
- Before timing, both implementations had to read and write every input
  byte-for-byte. Inputs were already in memory. Save-only timings used already
  loaded objects; roundtrip timings included parsing and serialization together.
- Seven warmed `timeit` samples per operation; median reported. Codec order
  alternated using a seeded shuffle. GC was disabled during timed batches.
  Timing batches target 60 ms unless otherwise noted. These are microbenchmarks
  on a working desktop, not formal latency guarantees or application benchmarks.
- Memory was measured separately in fresh subprocesses using Windows process
  counters, after retaining a stated number of decoded records and collecting
  garbage. Working-set increases include native allocations as well as Python
  objects. They are approximate process measurements, not exact per-tag sizes.
- Source worlds were copied before access; input records and local scripts/logs
  stay under ignored private or temporary paths.

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

The project codec is therefore not performance-neutral. Individual measured
player roundtrips are in the low-millisecond range, but repeated parsing and
large arrays can make the difference significant. Actual UI impact requires
timing the relevant application operation; multiplying these ratios by total
save time would be incorrect because database and backup work do not depend on
the codec.

Codec optimizations should target bulk arrays and measured hot paths with
standard-library facilities and keep the preservation tests unchanged.

## Player load path

Loading a player parses its stored record once. Classification returns the
parsed NBT, and the inventory and ender chest views and the compatibility
analysis share it. The analysis runs before the views receive item origins and
root equipment fallbacks, so it describes the record as stored; a regression
test compares it with an analysis of a fresh parse and counts the parses of a
load. Saving does not reuse a loaded parse: it reads and parses the record under
the write lock and parses the serialized result again before writing.

String decoding tries strict UTF-8 first. Only strings with bytes that are not
valid UTF-8 take the escape path, which yields the same text for every input.

## Equine-template prefilter

`find_equine_template` checks for the literal UTF-8 bytes of its three accepted
identifiers before decoding an actor record. Possible matches undergo full NBT
decoding, identifier validation and the priority selection. Incidental strings
and malformed records cannot become templates through the prefilter. Regression
tests cover false positives and all five supported identifier field names for
horses, donkeys and mules.

The following measurements for v0.5.21 compare the project codec with and
without this prefilter, on standard CPython 3.14.4. They do not compare against
Amulet-NBT. Both paths used the same disposable copy of the approximately
247 MB private server world. Each timing includes adapter creation, complete database
iteration, template selection and close. Three samples per mode were taken in
alternating order; the table reports medians. Build/test processes were not
running during these measurements. The native adapter used a locally built
Amulet-LevelDB wheel; in v0.5.21 it was the application's write adapter. The
application reads and writes with the project's own
[Python implementation](leveldb-writer.md), whose reader is the second row.

| Template-scan adapter | Without prefilter, seconds | With prefilter, seconds | Speedup |
| --- | ---: | ---: | ---: |
| Native adapter (v0.5.21 `LevelDbAdapter`) | 9.753 | 5.790 | 1.68× |
| `ReadonlyLevelDbAdapter` | 6.446 | 2.857 | 2.26× |

Both adapters decoded **6,821 records without the prefilter and 78 with it**.
Every run selected the exact same identifier and raw template bytes. The native
timings ranged from 9.383–9.779 seconds without and 5.780–5.926 seconds with
the prefilter; timings depend
on the world and the machine. Native LevelDB opens can change database
bookkeeping, so these runs accessed only the disposable copy.

This reduces unnecessary parsing in the horse `auto`/template path. It does
not change codec array performance, cover the complete HTTP/save/backup
operation, or imply that every editor operation becomes 1.68× faster.
