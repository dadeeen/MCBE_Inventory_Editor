"""Bedrock banner codes and front-face texture preparation.

Only bindings and UV coordinates live in the application. Minecraft textures
are extracted locally by the existing Vanilla icon updater, never bundled.
"""

from .block_icon_renderer import decode_png, encode_rgba_png

BANNER_PATTERN_TEXTURES = {
    "bo": "border",
    "bri": "bricks",
    "mc": "circle",
    "cre": "creeper",
    "cr": "cross",
    "cbo": "curly_border",
    "lud": "diagonal_left",
    "rd": "diagonal_right",
    "ld": "diagonal_up_left",
    "rud": "diagonal_up_right",
    "flo": "flower",
    "flw": "flow",
    "glb": "globe",
    "gra": "gradient",
    "gru": "gradient_up",
    "gus": "guster",
    "hh": "half_horizontal",
    "hhb": "half_horizontal_bottom",
    "vh": "half_vertical",
    "vhr": "half_vertical_right",
    "moj": "mojang",
    "pig": "piglin",
    "mr": "rhombus",
    "sku": "skull",
    "ss": "small_stripes",
    "bl": "square_bottom_left",
    "br": "square_bottom_right",
    "tl": "square_top_left",
    "tr": "square_top_right",
    "sc": "straight_cross",
    "bs": "stripe_bottom",
    "cs": "stripe_center",
    "dls": "stripe_downleft",
    "drs": "stripe_downright",
    "ls": "stripe_left",
    "ms": "stripe_middle",
    "rs": "stripe_right",
    "ts": "stripe_top",
    "bt": "triangle_bottom",
    "tt": "triangle_top",
    "bts": "triangles_bottom",
    "tts": "triangles_top",
}
BANNER_TEXTURES = {code: f"entity/banner/banner_{name}" for code, name in {"base": "base", **BANNER_PATTERN_TEXTURES}.items()}


def crop_banner_texture(png: bytes) -> bytes:
    """Keep the 20x40 cloth front at (1, 1) of the 64x64 box-UV atlas.

    Preserve RGB shading and fractional alpha; neither thresholding nor a
    silhouette approximation reproduces the gradients and detailed motifs.
    Integer HD scales use the same UVs. Reject other layouts explicitly.
    """
    texture = decode_png(png)
    if texture.width != texture.height or texture.width % 64 or not 64 <= texture.width <= 512:
        raise ValueError("Ungültiges Bannermuster-Texturformat.")
    scale = texture.width // 64
    width, height = 20 * scale, 40 * scale
    rows = bytearray()
    for y in range(scale, scale + height):
        offset = (y * texture.width + scale) * 4
        rows.extend(texture.rgba[offset : offset + width * 4])
    return encode_rgba_png(width, height, bytes(rows))
