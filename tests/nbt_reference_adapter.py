"""Test-only bridge for the shared Bedrock codec contract.

Amulet owns parsing and serialization here. It cannot distinguish literal
escape-looking UTF-8 from escaped invalid bytes; those project extensions use
fixed wire fixtures in test_nbt_codec instead of this reference.
"""

import struct

import amulet_nbt as reference

_LOAD = dict(compressed=False, little_endian=True, string_decoder=reference.utf8_escape_decoder)
_SAVE = dict(compressed=False, little_endian=True, string_encoder=reference.utf8_escape_encoder)


def string_bytes(tag):
    return reference.NamedTag(tag).save_to(**_SAVE)[5:]


def string_from_bytes(raw):
    tag = reference.load(b"\x08\x00\x00" + struct.pack("<H", len(raw)) + raw, **_LOAD).tag
    if string_bytes(tag) != raw:
        raise ValueError("Raw string is outside the shared Amulet reference contract")
    return tag


def name_bytes(compound, key):
    if key not in compound:
        raise KeyError(key)
    return reference.utf8_escape_encoder(key)


def select_compound_fields(compound, keys):
    return reference.CompoundTag({key: compound[key] for key in keys})


def install():
    """Extend only the worker's reference module with the small shared API."""
    for helper in (string_bytes, string_from_bytes, name_bytes, select_compound_fields):
        setattr(reference, helper.__name__, helper)
    return reference
