# NBT codec compatibility

[`mcbe_editor/nbt.py`](../mcbe_editor/nbt.py) provides the binary NBT types and
operations used by the editor. Its compatibility reference is **Amulet-NBT
2.1.8**, with explicit Bedrock byte-order and string-encoding options. This
contract covers the editor's required operations, rather than the entire
Amulet-NBT public API.

## Reference and scope

The upstream source distribution `amulet_nbt-2.1.8.tar.gz` has SHA-256
`c1a2c7b456bf872149cc070fce5615563818df15cc5c63cb6a6daa05a526c0b3`, matching
[`requirements/nbt-reference.txt`](../requirements/nbt-reference.txt).
Amulet-NBT is an optional test dependency in a separate Python 3.12 reference
environment; it is not required by the application. Setup and workflow
comparisons are described in [Python dependency portability](dependency-portability-assessment.md).

The relevant upstream reading, writing, copying and mutation implementations
are in `_load_nbt.pyx`, `_util.pyx`, `_value.pyx`, `_named_tag.pyx`, `_int.pyx`,
`_float.pyx`, `_array.pyx`, `_string.pyx`, `_list.pyx` and `_compound.pyx`.

## Shared behavior

| Operation | Required behavior |
| --- | --- |
| List/compound `py_data` and legacy `value` | Return a shallow copy of the outer container; child tags remain shared. |
| `copy.copy()` and `.copy()` of a list/compound | Return a new tag with separate outer storage; child tags remain shared. |
| `value in ListTag` | Require an NBT tag with the list's declared element type before comparing values; a plain integer or differently typed numeric tag does not match. |

Changing a copied container's entries must not change the original container.
Changing a shared child tag can affect both; use `copy.deepcopy()` when nested
tags must be independent.

Signed integer widths, integer wrapping, byte order, unsigned 16-bit string
lengths and signed 32-bit container lengths follow the reference binary format.

## Intentional differences

| Area | Project behavior and reason |
| --- | --- |
| Defaults and supported formats | Uncompressed, little-endian Bedrock NBT with the escape UTF-8 codec. Upstream defaults to compressed, big-endian NBT and modified UTF-8. Application I/O explicitly specifies its Bedrock options. |
| Loading and saving | One complete record from bytes-like input; serialization returns bytes. Filesystem writes remain in guarded application storage APIs. Upstream also supports files, streams, multiple roots and read offsets. |
| Malformed data | Duplicate decoded keys, negative lengths, invalid list types and trailing bytes are rejected. Upstream can overwrite duplicate keys or accept some incomplete/extra container information. |
| Resource limits | Explicit byte, depth and aggregate element limits bound work and memory use. Very large records accepted upstream can intentionally be rejected here. |
| Preservation | Original string/name bytes and floating-point payload bits are retained. Empty list types survive shallow and deep copying; upstream generic copying can reset an empty list's type. |
| String escape edge cases | Only hexadecimal escapes are interpreted. Upstream's broader regular expression can attempt to parse non-hexadecimal text and raise an error. |
| Additional APIs | SNBT, NumPy array operations, convenience getters and most scalar operators are outside the supported API. Arrays use standard-library containers. |
| Constructors | The project requires actual strings for `StringTag`; upstream converts arbitrary objects with `str()`. The editor supplies strings. |

## Verification

- [`tests/test_nbt_codec.py`](../tests/test_nbt_codec.py) checks preservation,
  malformed inputs, resource limits, container copies and typed membership.
- [`tests/test_nbt_reference.py`](../tests/test_nbt_reference.py) compares both
  codecs using generated trees, every empty-list type and the reviewed entity
  records. It requires the separate reference environment and skips when
  Amulet-NBT is unavailable.

Run these checks when changing the codec:

```bash
python -m pytest tests/test_nbt_codec.py tests/test_nbt_reference.py -q
```

Binary compatibility does not establish Minecraft gameplay behavior. That
requires separate [Minecraft acceptance validation](mount-game-validation.md).
