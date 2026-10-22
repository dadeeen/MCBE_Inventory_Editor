"""Bounded, preserving editors for Bedrock item metadata.

Only the fields owned by these editors are writable. Original compounds remain
the authority for unknown tags and row identities; browser NBT is never loaded.
Container items use the inventory builder through explicit callbacks.
"""

from __future__ import annotations

from copy import deepcopy

from . import nbt
from .banner_patterns import BANNER_PATTERN_TEXTURES
from .bedrock_nbt import literal_string_tag
from .i18n import t

COLORS = (
    "black",
    "red",
    "green",
    "brown",
    "blue",
    "purple",
    "cyan",
    "light_gray",
    "gray",
    "pink",
    "lime",
    "yellow",
    "light_blue",
    "magenta",
    "orange",
    "white",
)
DYE_RGB = (
    0x1D1D21,
    0xB02E26,
    0x5E7C16,
    0x835432,
    0x3C44AA,
    0x8932B8,
    0x169C9C,
    0x9D9D97,
    0x474F52,
    0xF38BAA,
    0x80C71F,
    0xFED83D,
    0x3AB3DA,
    0xC74EBD,
    0xF9801D,
    0xF0F0F0,
)
BANNER_PATTERNS = tuple(BANNER_PATTERN_TEXTURES)
ITEM_KINDS = {
    **{f"minecraft:{color}_bundle": "bundle" for color in COLORS},
    **{f"minecraft:{color}_shulker_box": "shulker" for color in COLORS},
    "minecraft:bundle": "bundle",
    "minecraft:shulker_box": "shulker",
    "minecraft:undyed_shulker_box": "shulker",
    "minecraft:writable_book": "book",
    "minecraft:written_book": "book",
    "minecraft:fireworks": "fireworks",
    "minecraft:firework_rocket": "fireworks",
    "minecraft:fireworkscharge": "firework_star",
    "minecraft:firework_star": "firework_star",
    "minecraft:banner": "banner",
}
LIMITS = {"depth": 8, "nodes": 256, "pages": 50, "page_length": 256, "title_length": 32, "author_length": 64, "explosions": 7, "patterns": 6}
PROTECTED_MESSAGE = "Diese Spezialdaten haben ein unbekanntes oder nicht sicher bearbeitbares Format. Sie bleiben unverändert erhalten."


def editor_schema() -> dict:
    return {"item_kinds": ITEM_KINDS, "limits": LIMITS, "patterns": BANNER_PATTERNS, "colors": COLORS, "color_hex": [f"#{color:06x}" for color in DYE_RGB]}


def kind_for_name(name: str) -> str | None:
    return ITEM_KINDS.get(name.strip().lower())


def kind_for_item(item) -> str | None:
    name = item.get("Name") if isinstance(item, nbt.CompoundTag) else None
    return kind_for_name(str(name.py_data)) if isinstance(name, nbt.StringTag) else None


def reject(message: str = PROTECTED_MESSAGE):
    raise ValueError(t(message))


def integer(value, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        reject("Ungültiger Zahlenwert im Spezialeditor.")
    return value


def text_value(value, limit: int) -> str:
    if not isinstance(value, str) or len(value.encode("utf-16-le", errors="surrogatepass")) // 2 > limit or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        reject("Der Text im Spezialeditor ist zu lang oder enthält ungültige Zeichen.")
    return value


def compound(parent, key: str):
    value = parent.get(key)
    if value is None:
        return nbt.CompoundTag()
    if not isinstance(value, nbt.CompoundTag):
        reject()
    return value


def compound_list(parent, key: str, maximum: int):
    value = parent.get(key)
    if value is None:
        return nbt.ListTag([], 10)
    if not isinstance(value, nbt.ListTag) or len(value) > maximum or (len(value) and value.list_data_type != 10):
        reject()
    return value


def scalar(parent, key: str, tag_type, default):
    value = parent.get(key)
    if value is None:
        return default
    if type(value) is not tag_type:
        reject()
    return value.py_data


def set_scalar(parent, key: str, value, tag_type, default=None):
    """Keep untouched bytes, absent defaults and noncanonical true bytes."""
    original = parent.get(key)
    if original is not None:
        if type(original) is not tag_type:
            reject()
        if original.py_data == value or (type(value) is bool and bool(original.py_data) == value):
            return
    elif value == default:
        return
    parent[key] = literal_string_tag(value) if tag_type is nbt.StringTag else tag_type(value)


def source_row(row, originals, seen):
    index = row.get("source_index")
    if index is None:
        return nbt.CompoundTag()
    integer(index, 0, len(originals) - 1)
    if index in seen:
        reject("Ein Originaleintrag wird im Spezialeditor mehrfach verwendet.")
    seen.add(index)
    return deepcopy(originals[index])


def rows(value, maximum: int) -> list:
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(row, dict) for row in value):
        reject("Ungültige Einträge im Spezialeditor.")
    return value


def exact_fields(value, required: set[str], optional: set[str] = frozenset()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        reject("Unbekannte oder fehlende Felder im Spezialeditor.")


def _colors(value, *, empty=False):
    if not isinstance(value, list) or not (0 if empty else 1) <= len(value) <= 16:
        reject("Wähle mindestens eine gültige Feuerwerksfarbe.")
    return [integer(color, 0, 15) for color in value]


def _read_explosion(entry, index):
    colors = entry.get("FireworkColor")
    fade = entry.get("FireworkFade")
    if type(colors) is not nbt.ByteArrayTag or (fade is not None and type(fade) is not nbt.ByteArrayTag):
        reject()
    return {
        "source_index": index,
        "shape": integer(scalar(entry, "FireworkType", nbt.ByteTag, 0), 0, 4),
        "colors": _colors(list(colors)),
        "fade": _colors(list(fade) if fade is not None else [], empty=True),
        "trail": bool(scalar(entry, "FireworkTrail", nbt.ByteTag, 0)),
        "flicker": bool(scalar(entry, "FireworkFlicker", nbt.ByteTag, 0)),
    }


def _read_metadata(item, kind):
    tag = compound(item, "tag")
    if kind == "book":
        pages = compound_list(tag, "pages", LIMITS["pages"])
        data = {
            "pages": [{"source_index": i, "text": text_value(scalar(page, "text", nbt.StringTag, ""), LIMITS["page_length"])} for i, page in enumerate(pages)]
        }
        if str(item["Name"].py_data) == "minecraft:written_book":
            data.update(
                title=text_value(scalar(tag, "title", nbt.StringTag, ""), LIMITS["title_length"]),
                author=text_value(scalar(tag, "author", nbt.StringTag, ""), LIMITS["author_length"]),
            )
        return data
    if kind == "banner":
        banner_type = integer(scalar(tag, "Type", nbt.IntTag, 0), 0, 1)
        patterns = compound_list(tag, "Patterns", LIMITS["patterns"])
        data = []
        for i, entry in enumerate(patterns):
            pattern = scalar(entry, "Pattern", nbt.StringTag, "")
            if pattern not in BANNER_PATTERNS:
                reject()
            data.append({"source_index": i, "pattern": pattern, "color": integer(scalar(entry, "Color", nbt.IntTag, -1), 0, 15)})
        return {"patterns": data, **({"type": 1} if banner_type else {})}
    if kind == "fireworks":
        firework = compound(tag, "Fireworks")
        return {
            "flight": integer(scalar(firework, "Flight", nbt.ByteTag, 1), 1, 3),
            "explosions": [_read_explosion(entry, i) for i, entry in enumerate(compound_list(firework, "Explosions", LIMITS["explosions"]))],
        }
    if kind == "firework_star":
        scalar(tag, "customColor", nbt.IntTag, None)
        entry = tag.get("FireworksItem")
        return {"explosions": [_read_explosion(compound(tag, "FireworksItem"), 0)] if entry is not None else []}
    raise ValueError("Unknown metadata kind")


def describe(item, parse_child, *, depth: int = 0, budget: list[int] | None = None):
    kind = kind_for_item(item)
    if not kind:
        return None
    try:
        if depth >= LIMITS["depth"]:
            reject()
        if kind in {"shulker", "bundle"}:
            from .item_containers import read_contents

            data = read_contents(item, kind, parse_child, depth=depth, budget=budget or [LIMITS["nodes"]])
        else:
            data = _read_metadata(item, kind)
        return {"kind": kind, "editable": True, "data": data}
    except ValueError:
        return {"kind": kind, "editable": False, "reason": t(PROTECTED_MESSAGE)}


def _write_rows(payload, originals, maximum, update):
    result, seen = [], set()
    for row in rows(payload, maximum):
        entry = source_row(row, originals, seen)
        update(entry, row)
        result.append(entry)
    return nbt.ListTag(result, originals.list_data_type if not result else 10)


def _apply_explosion(entry, row):
    exact_fields(row, {"shape", "colors", "fade", "trail", "flicker"}, {"source_index"})
    existing = row.get("source_index") is not None
    set_scalar(entry, "FireworkType", integer(row["shape"], 0, 4), nbt.ByteTag, 0 if existing else None)
    for field, key in (("colors", "FireworkColor"), ("fade", "FireworkFade")):
        colors = _colors(row[field], empty=field == "fade")
        old = entry.get(key)
        if old is not None and type(old) is not nbt.ByteArrayTag:
            reject()
        if old is None and not colors and existing:
            continue
        if old is None or list(old) != colors:
            entry[key] = nbt.ByteArrayTag(colors)
    for field, key in (("trail", "FireworkTrail"), ("flicker", "FireworkFlicker")):
        if type(row[field]) is not bool:
            reject("Ungültiger Schalterwert im Spezialeditor.")
        set_scalar(entry, key, row[field], nbt.ByteTag, False if existing else None)


def _apply_metadata(item, kind, data):
    tag = compound(item, "tag")
    if kind == "book":
        signed = str(item["Name"].py_data) == "minecraft:written_book"
        exact_fields(data, {"pages", "title", "author"} if signed else {"pages"})

        def update_page(entry, row):
            exact_fields(row, {"text"}, {"source_index"})
            set_scalar(entry, "text", text_value(row["text"], LIMITS["page_length"]), nbt.StringTag, "" if row.get("source_index") is not None else None)
            if row.get("source_index") is None and "photoname" not in entry:
                entry["photoname"] = nbt.StringTag("")

        pages = _write_rows(data["pages"], compound_list(tag, "pages", LIMITS["pages"]), LIMITS["pages"], update_page)
        if "pages" in tag or pages:
            tag["pages"] = pages
        if signed:
            for field in ("title", "author"):
                set_scalar(tag, field, text_value(data[field], LIMITS[field + "_length"]), nbt.StringTag, "")
            # Signing creates generation; this editor changes an already signed
            # book and does not own its generation or other absent defaults.
    elif kind == "banner":
        exact_fields(data, {"patterns"}, {"type"})
        previous_type = scalar(tag, "Type", nbt.IntTag, 0)
        banner_type = integer(data.get("type", previous_type), 0, 1)
        previous_patterns = _read_metadata(item, kind)["patterns"]
        if banner_type == 1 and data["patterns"] and (previous_type != 1 or data["patterns"] != previous_patterns):
            reject("Ein ominöses Banner verwendet das feste Vanilla-Design ohne zusätzliche Muster.")
        if banner_type != previous_type:
            tag["Type"] = nbt.IntTag(banner_type)
        if banner_type == 1 and (previous_type != 1 or data["patterns"] != previous_patterns):
            item["Damage"] = nbt.ShortTag(15)

        def update_pattern(entry, row):
            exact_fields(row, {"pattern", "color"}, {"source_index"})
            if row["pattern"] not in BANNER_PATTERNS:
                reject("Unbekanntes Bannermuster.")
            set_scalar(entry, "Pattern", row["pattern"], nbt.StringTag)
            set_scalar(entry, "Color", integer(row["color"], 0, 15), nbt.IntTag)

        # Bedrock can render Patterns over the illager motif. Preserve existing
        # hybrids on echo, but create the vanilla design without extra layers.
        if data["patterns"] != previous_patterns:
            if banner_type == 1:
                tag.pop("Patterns", None)
            else:
                tag["Patterns"] = _write_rows(data["patterns"], compound_list(tag, "Patterns", LIMITS["patterns"]), LIMITS["patterns"], update_pattern)
    elif kind == "fireworks":
        exact_fields(data, {"flight", "explosions"})
        firework = compound(tag, "Fireworks")
        set_scalar(firework, "Flight", integer(data["flight"], 1, 3), nbt.ByteTag, 1)
        explosions = _write_rows(data["explosions"], compound_list(firework, "Explosions", LIMITS["explosions"]), LIMITS["explosions"], _apply_explosion)
        if "Explosions" in firework or explosions:
            firework["Explosions"] = explosions
        tag["Fireworks"] = firework
    elif kind == "firework_star":
        exact_fields(data, {"explosions"})
        if len(rows(data["explosions"], 1)) != 1:
            reject("Ein Feuerwerksstern benötigt genau einen Effekt.")
        originals = nbt.ListTag([tag["FireworksItem"]], 10) if "FireworksItem" in tag else nbt.ListTag([], 10)
        old_colors = list(originals[0]["FireworkColor"]) if originals else None
        old_color = scalar(tag, "customColor", nbt.IntTag, None)
        tag["FireworksItem"] = _write_rows(data["explosions"], originals, 1, _apply_explosion)[0]
        # Bedrock's star icon uses an ARGB color. Preserve an explicit custom
        # override; refresh only the derived dye mixture when colors change.
        if old_colors != data["explosions"][0]["colors"] and (old_color is None or old_colors and old_color == _mixed_star_color(old_colors)):
            set_scalar(tag, "customColor", _mixed_star_color(data["explosions"][0]["colors"]), nbt.IntTag)
    item["tag"] = tag


def _mixed_star_color(colors):
    rgb = sum((sum((DYE_RGB[color] >> shift) & 255 for color in colors) // len(colors)) << shift for shift in (0, 8, 16))
    return rgb - (1 << 24)  # Signed opaque ARGB (0xffRRGGBB).


def _consume_preserved_contents(item, parse_child, depth, budget):
    if budget is None or kind_for_item(item) not in {"shulker", "bundle"}:
        return
    # The parent writer counts this item; its preserved descendants also consume
    # the transaction's shared budget. Use the reader's occupied-item accounting
    # so canonical empty slots and opaque original data retain their semantics.
    describe(item, parse_child, depth=depth, budget=budget)
    if budget[0] < 0:
        raise ValueError(t("Der Container enthält zu viele verschachtelte Items. Maximal {max} Items sind erlaubt.", max=LIMITS["nodes"]))


def _same_edit_data(kind, requested, current):
    if kind == "banner" and isinstance(requested, dict):
        # Type 0 may be implicit. Echoing it must not create a missing tag;
        # omitting Type also preserves an existing ominous banner.
        banner_type = requested.get("type", current.get("type", 0))
        return type(banner_type) is int and {**requested, "type": banner_type} == {**current, "type": current.get("type", 0)}
    if kind not in {"shulker", "bundle"} or requested == current:
        return requested == current
    if not isinstance(requested, dict) or set(requested) != {"items"}:
        return False
    children = requested["items"]
    if not isinstance(children, list) or len(children) != len(current["items"]):
        return False
    # Save payloads omit read-only presentation data. Comparing it would turn
    # a reverted edit into a real write, normalizing otherwise untouched lists.
    presentation = {
        "stack_key",
        "special_item",
        "nbt_view",
        "item_tag_opaque",
        "entity_variant",
        "entity_variant_state",
        "has_unknown_enchantments",
        "has_protected_nbt",
        "has_preserved_nbt",
        "preserved_nbt_summary",
        "protected_nbt_summary",
    }
    for child, original in zip(children, current["items"], strict=True):
        if not isinstance(child, dict):
            return False
        values = {key: value for key, value in child.items() if key not in presentation}
        nested_edit = values.pop("special_edit", None)
        if values != {key: value for key, value in original.items() if key not in presentation}:
            return False
        if nested_edit is not None:
            metadata = original.get("special_item")
            if (
                not isinstance(nested_edit, dict)
                or set(nested_edit) != {"kind", "data"}
                or not metadata
                or not metadata.get("editable")
                or nested_edit["kind"] != metadata["kind"]
                or not _same_edit_data(metadata["kind"], nested_edit["data"], metadata["data"])
            ):
                return False
    return True


def apply(item, edit, parse_child, build_child, *, depth: int = 0, budget: list[int] | None = None):
    if edit is None:
        _consume_preserved_contents(item, parse_child, depth, budget)
        return
    exact_fields(edit, {"kind", "data"})
    kind = kind_for_item(item)
    if kind is None or edit["kind"] != kind or depth >= LIMITS["depth"]:
        reject("Der Spezialeditor passt nicht zu diesem Item.")
    current = describe(item, parse_child, depth=depth)
    if not current or not current["editable"]:
        reject()
    # An echoed editor is a strict no-op, including missing tags and raw strings.
    if _same_edit_data(kind, edit["data"], current["data"]):
        _consume_preserved_contents(item, parse_child, depth, budget)
        return
    if kind in {"shulker", "bundle"}:
        from .item_containers import write_contents

        write_contents(item, kind, edit["data"], build_child, depth=depth, budget=budget or [LIMITS["nodes"]])
    else:
        _apply_metadata(item, kind, edit["data"])
