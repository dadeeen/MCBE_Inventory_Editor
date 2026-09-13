"""Project-owned binary NBT types and codec, using only the standard library.

This is a Bedrock codec, not an implementation of Java SNBT or modified UTF-8.
Unknown fields, empty list types, raw string bytes and floating-point bit patterns
survive a read/write cycle. Parsing is bounded and ambiguous compounds are
rejected rather than silently discarding duplicate keys.
"""

from __future__ import annotations

import copy
import re
import struct
from collections.abc import Callable, MutableMapping, MutableSequence

MAX_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 128
MAX_NODES = 1_000_000
_ESCAPE = re.compile("\u241bx([0-9a-fA-F]{2})")


class NBTError(ValueError):
    """Invalid, ambiguous or excessively large binary NBT."""


def utf8_escape_decoder(value: bytes) -> str:
    text = value.decode("utf-8", errors="surrogateescape")
    return "".join(f"\u241bx{ord(char) - 0xDC00:02x}" if 0xDC80 <= ord(char) <= 0xDCFF else char for char in text)


def utf8_escape_encoder(value: str) -> bytes:
    parts = []
    start = 0
    for match in _ESCAPE.finditer(value):
        parts.extend((value[start:match.start()].encode("utf-8"), bytes([int(match[1], 16)])))
        start = match.end()
    parts.append(value[start:].encode("utf-8"))
    return b"".join(parts)


class BaseTag:
    tag_id: int

    @property
    def py_data(self):
        return self._value

    @property
    def value(self):
        return self.py_data

    def copy(self):
        return copy.copy(self)

    def __repr__(self):
        return f"{type(self).__name__}({self.py_data!r})"

    def __eq__(self, other):
        return self.py_data == (other.py_data if isinstance(other, BaseTag) else other)

    def __bool__(self):
        return bool(self._value)

    def save_to(self, *args, **kwargs):
        return NamedTag(self).save_to(*args, **kwargs)


class _IntegerTag(BaseTag):
    bits: int

    def __init__(self, value=0):
        # Match the existing signed fixed-width constructors. Application edit
        # validation separately rejects values outside their allowed ranges.
        value = int(value)
        self._value = (value + (1 << (self.bits - 1))) % (1 << self.bits) - (1 << (self.bits - 1))

    def __int__(self):
        return self._value

    def __float__(self):
        return float(self._value)

    def __str__(self):
        return str(self._value)


class ByteTag(_IntegerTag):
    tag_id, bits = 1, 8


class ShortTag(_IntegerTag):
    tag_id, bits = 2, 16


class IntTag(_IntegerTag):
    tag_id, bits = 3, 32


class LongTag(_IntegerTag):
    tag_id, bits = 4, 64


class _FloatingTag(BaseTag):

    def __init__(self, value=0.0):
        value = float(value)
        try:
            self._raw = struct.pack("<" + self._format, value)
        except OverflowError:
            self._raw = struct.pack("<" + self._format, float("-inf") if value < 0 else float("inf"))
        self._value = struct.unpack("<" + self._format, self._raw)[0]

    def __float__(self):
        return self._value

    def __int__(self):
        return int(self._value)

    def __str__(self):
        return str(self._value)


class FloatTag(_FloatingTag):
    tag_id = 5
    _format = "f"


class DoubleTag(_FloatingTag):
    tag_id = 6
    _format = "d"


class StringTag(BaseTag):
    tag_id = 8

    def __init__(self, value=""):
        if not isinstance(value, str):
            raise TypeError("StringTag requires a string")
        self._value = value
        self._raw = None

    def __str__(self):
        return self._value


def _require_tag(value):
    if not isinstance(value, BaseTag):
        raise TypeError("NBT containers require NBT tags")


class CompoundTag(BaseTag, MutableMapping):
    tag_id = 10

    def __init__(self, value=None):
        self._value = {}
        self._raw_names = {}
        self.update({} if value is None else value)

    @property
    def py_data(self):
        return self._value.copy()

    def __getitem__(self, key):
        return self._value[key]

    def __setitem__(self, key, value):
        if not isinstance(key, str):
            raise TypeError("NBT names must be strings")
        _require_tag(value)
        self._value[key] = value

    def __delitem__(self, key):
        del self._value[key]
        self._raw_names.pop(key, None)

    def __len__(self):
        return len(self._value)

    def __iter__(self):
        return iter(self._value)

    def copy(self):
        result = CompoundTag(self._value)
        result._raw_names = self._raw_names.copy()
        return result

    def __copy__(self):
        return self.copy()


class ListTag(BaseTag, MutableSequence):
    tag_id = 9

    def __init__(self, value=(), list_data_type=1):
        self._value = list(value)
        self.list_data_type = self._value[0].tag_id if self._value else list_data_type
        if not isinstance(self.list_data_type, int) or not 0 <= self.list_data_type <= 12:
            raise TypeError("Invalid NBT list element type")
        for entry in self._value:
            self._check(entry)

    @property
    def py_data(self):
        return self._value.copy()

    def _check(self, value):
        _require_tag(value)
        if value.tag_id != self.list_data_type:
            raise TypeError("NBT lists must contain tags of one type")

    def __getitem__(self, key):
        return self._value[key]

    def __setitem__(self, key, value):
        values = list(value) if isinstance(key, slice) else [value]
        element_type = self.list_data_type
        if not self._value and values and isinstance(key, slice):
            _require_tag(values[0])
            element_type = values[0].tag_id
        for entry in values:
            _require_tag(entry)
            if entry.tag_id != element_type:
                raise TypeError("NBT lists must contain tags of one type")
        self._value[key] = values if isinstance(key, slice) else value
        self.list_data_type = element_type

    def __delitem__(self, key):
        del self._value[key]

    def __len__(self):
        return len(self._value)

    def __contains__(self, value):
        return isinstance(value, BaseTag) and value.tag_id == self.list_data_type and value in self._value

    def insert(self, index, value):
        if not self._value:
            _require_tag(value)
            self.list_data_type = value.tag_id
        self._check(value)
        self._value.insert(index, value)

    def copy(self):
        return ListTag(self._value, self.list_data_type)

    def __copy__(self):
        return self.copy()


class _ArrayData(list):
    def tolist(self):
        return list(self)


class ByteArrayTag(BaseTag):
    tag_id = 7
    _element = ByteTag

    def __init__(self, value=()):
        self._value = _ArrayData(self._element(v).py_data for v in value)

    def __iter__(self):
        return iter(self._value)

    def __len__(self):
        return len(self._value)

    def __getitem__(self, key):
        return self._value[key]

    def copy(self):
        return type(self)(self._value)


class IntArrayTag(ByteArrayTag):
    tag_id = 11
    _element = IntTag


class LongArrayTag(ByteArrayTag):
    tag_id = 12
    _element = LongTag


_TYPES = {cls.tag_id: cls for cls in (ByteTag, ShortTag, IntTag, LongTag, FloatTag, DoubleTag,
                                    ByteArrayTag, StringTag, ListTag, CompoundTag, IntArrayTag, LongArrayTag)}
_FORMATS = {1: "b", 2: "h", 3: "i", 4: "q", 5: "f", 6: "d", 7: "b", 11: "i", 12: "q"}


class _Reader:
    def __init__(self, data, little_endian, decoder):
        view = memoryview(data)
        if view.nbytes > MAX_BYTES:
            raise NBTError("NBT exceeds size limit")
        # Offsets and limits are bytes, even for typed or multidimensional views.
        # Only non-contiguous views require a copy, after checking their size.
        self.data = view.cast("B") if view.c_contiguous else memoryview(view.tobytes())
        self.pos = 0
        self.endian = "<" if little_endian else ">"
        self.decoder = decoder
        self.nodes = 0

    def take(self, size):
        if size < 0 or size > len(self.data) - self.pos:
            raise NBTError("Truncated NBT")
        start = self.pos
        self.pos += size
        return bytes(self.data[start:self.pos])

    def number(self, fmt):
        return struct.unpack(self.endian + fmt, self.take(struct.calcsize(fmt)))[0]

    def string(self):
        raw = self.take(self.number("H"))
        return self.decoder(raw), raw

    def tag(self, tag_id, depth=0):
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise NBTError("NBT exceeds complexity limit")
        cls = _TYPES.get(tag_id)
        if cls is None:
            raise NBTError(f"Invalid NBT tag ID: {tag_id}")
        if tag_id <= 6:
            fmt = _FORMATS[tag_id]
            raw = self.take(struct.calcsize(fmt))
            tag = cls(struct.unpack(self.endian + fmt, raw)[0])
            if tag_id in (5, 6):
                tag._raw = raw if self.endian == "<" else raw[::-1]
            return tag
        if tag_id == 8:
            value, raw = self.string()
            tag = StringTag(value)
            tag._raw = raw
            return tag
        if tag_id == 10:
            tag = CompoundTag()
            while child_id := self.number("B"):
                name, raw = self.string()
                if name in tag:
                    raise NBTError("Duplicate or ambiguously decoded NBT name")
                tag[name] = self.tag(child_id, depth + 1)
                tag._raw_names[name] = raw
            return tag
        child_id = self.number("B") if tag_id == 9 else None
        length = self.number("i")
        if length < 0:
            raise NBTError("Negative NBT container length")
        if length > MAX_NODES:
            raise NBTError("NBT container exceeds element limit")
        if tag_id == 9:
            if child_id not in range(13) or (length and child_id == 0):
                raise NBTError("Invalid NBT list element type")
            if length > MAX_NODES - self.nodes or length > len(self.data) - self.pos:
                raise NBTError("NBT list exceeds available data or complexity limit")
            return ListTag([self.tag(child_id, depth + 1) for _ in range(length)], child_id)
        fmt = _FORMATS[tag_id]
        size = struct.calcsize(fmt)
        if length > MAX_NODES - self.nodes:
            raise NBTError("NBT exceeds complexity limit")
        self.nodes += length
        raw = self.take(length * size)
        return cls(v[0] for v in struct.iter_unpack(self.endian + fmt, raw))


class _Writer:
    def __init__(self, little_endian, encoder):
        self.data = bytearray()
        self.endian = "<" if little_endian else ">"
        self.encoder = encoder
        self.nodes = 0

    def add(self, value):
        if len(self.data) + len(value) > MAX_BYTES:
            raise NBTError("NBT exceeds size limit")
        self.data.extend(value)

    def number(self, fmt, value):
        self.add(struct.pack(self.endian + fmt, value))

    def string(self, value, raw=None):
        # Preserve original bytes with the Bedrock codec, but honor an explicit
        # alternative encoder for both loaded names and string payloads.
        raw = self.encoder(value) if raw is None or self.encoder is not utf8_escape_encoder else raw
        if len(raw) > 65535:
            raise NBTError("NBT string exceeds unsigned 16-bit length")
        self.number("H", len(raw))
        self.add(raw)

    def tag(self, tag, depth=0):
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise NBTError("NBT exceeds complexity limit")
        _require_tag(tag)
        tag_id = tag.tag_id
        if tag_id in (5, 6):
            self.add(tag._raw if self.endian == "<" else tag._raw[::-1])
        elif tag_id <= 4:
            self.number(_FORMATS[tag_id], tag.py_data)
        elif tag_id == 8:
            self.string(tag.py_data, tag._raw)
        elif tag_id == 10:
            for name, value in tag.items():
                self.number("B", value.tag_id)
                self.string(name, tag._raw_names.get(name))
                self.tag(value, depth + 1)
            self.number("B", 0)
        elif tag_id == 9:
            self.number("B", tag.list_data_type)
            self.number("i", len(tag))
            for value in tag:
                tag._check(value)
                self.tag(value, depth + 1)
        else:
            if len(tag) > MAX_NODES - self.nodes:
                raise NBTError("NBT exceeds complexity limit")
            self.nodes += len(tag)
            self.number("i", len(tag))
            for value in tag:
                self.number(_FORMATS[tag_id], value)


class NamedTag:
    def __init__(self, tag, name=""):
        _require_tag(tag)
        self.tag = tag
        self.name = name
        self._original_name = name
        self._raw_name = None

    def save_to(self, filepath=None, *, compressed=False, little_endian=True, string_encoder=utf8_escape_encoder):
        if compressed:
            raise NBTError("Compressed/Java NBT is not supported by the Bedrock codec")
        writer = _Writer(little_endian, string_encoder)
        writer.number("B", self.tag.tag_id)
        writer.string(self.name, self._raw_name if self.name == self._original_name else None)
        writer.tag(self.tag)
        raw = bytes(writer.data)
        if filepath is not None:
            # Application writes pass serialized bytes to guarded storage APIs.
            # Keep the codec itself free of filesystem side effects.
            raise TypeError("Serialize to bytes and use the guarded storage API")
        return raw


def load(
    data: bytes | bytearray | memoryview,
    *,
    compressed: bool = False,
    little_endian: bool = True,
    string_decoder: Callable[[bytes], str] = utf8_escape_decoder,
) -> NamedTag:
    if compressed:
        raise NBTError("Compressed/Java NBT is not supported by the Bedrock codec")
    if not isinstance(data, bytes | bytearray | memoryview):
        raise TypeError("NBT input must be bytes")
    reader = _Reader(data, little_endian, string_decoder)
    tag_id = reader.number("B")
    name, raw_name = reader.string()
    result = NamedTag(reader.tag(tag_id), name)
    result._raw_name = raw_name
    if reader.pos != len(reader.data):
        raise NBTError("Trailing bytes after NBT root")
    return result
