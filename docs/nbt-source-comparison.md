# Direct comparison with Amulet-NBT 2.1.8

Reviewed on 2026-09-13 against the actual Cython source, in addition to the
earlier behavioral comparisons described in
[the portability assessment](dependency-portability-assessment.md).

## Reference and scope

The upstream source distribution `amulet_nbt-2.1.8.tar.gz` has SHA-256
`c1a2c7b456bf872149cc070fce5615563818df15cc5c63cb6a6daa05a526c0b3`, matching
`requirements/nbt-reference.txt`. All 14 extracted Cython files were checked
against the archive as part of the review. No upstream code was vendored into the
application and no new runtime dependency was added.

The review examined the relevant reading, writing, copying and mutation paths
in `_load_nbt.pyx`, `_util.pyx`, `_value.pyx`, `_named_tag.pyx`, `_int.pyx`,
`_float.pyx`, `_array.pyx`, `_string.pyx`, `_list.pyx` and `_compound.pyx`.
It does not claim complete compatibility with the entire upstream public API.

## Reproduced and corrected differences

| Operation | Amulet-NBT 2.1.8 | Project codec before this review | Correction |
| --- | --- | --- | --- |
| List/compound `py_data` and legacy `value` | Returns a shallow container copy | Exposed internal storage | Return a shallow copy; child tags remain shared |
| `copy.copy()` of a list/compound | Separates outer storage | Shared the original list/dictionary | Delegate to the existing `.copy()` implementation |
| `value in ListTag` | Requires an NBT tag with the declared element type | Inherited membership accepted equal numbers of another tag type, or plain integers | Check the NBT tag type before comparing values |

The first two differences could let callers unintentionally change the original
container through an apparent copy. These were demonstrated with small in-memory
examples; the review did not establish an existing corrupted player or animal.
Seven regression cases failed before correction and passed afterward. Probes
against the installed upstream extension confirmed the corrected semantics.

## Deliberate differences retained

| Area | Project behavior and reason |
| --- | --- |
| Defaults and supported formats | Uncompressed, little-endian Bedrock NBT with the escape UTF-8 codec. Upstream defaults to compressed, big-endian NBT and modified UTF-8. Application I/O explicitly specifies its Bedrock options. |
| Loading and saving | One complete record from bytes-like input; serialization returns bytes. Filesystem writes remain in guarded application storage APIs. Upstream also supports files, streams, multiple roots and read offsets. |
| Malformed data | Duplicate decoded keys, negative lengths, invalid list types and trailing bytes are rejected. Upstream can overwrite duplicate keys or accept some incomplete/extra container information. |
| Resource limits | Explicit byte, depth and aggregate element limits bound work and memory use. Very large records accepted upstream can intentionally be rejected here. |
| Preservation | Original string/name bytes and floating-point payload bits are retained. Empty list types survive shallow and deep copying; upstream generic copying can reset an empty list's type. |
| String escape edge cases | Only hexadecimal escapes are interpreted. Upstream's broader regular expression can attempt to parse non-hexadecimal text and raise an error. |
| Additional APIs | SNBT, NumPy array operations, convenience getters and most scalar operators are not reproduced. Searches found no use of the omitted named APIs in application or diagnostic code. Arrays use standard-library containers; this is not a NumPy replacement API. |
| Constructors | The project requires actual strings for `StringTag`; upstream converts arbitrary objects with `str()`. The editor supplies strings. |

Signed integer widths, integer wrapping, byte order, unsigned 16-bit string
lengths and signed 32-bit container lengths agree in the reviewed binary paths.
The independent reference tests remain the executable check for supported data.

## Validation

Executable reference tests are described in the portability assessment.
The scope is compatibility of the editor's required binary data and operations,
not a drop-in replacement for every Amulet-NBT feature. The earlier Minecraft
acceptance results remain separate evidence for actual game behavior.
