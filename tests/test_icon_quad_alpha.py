"""A flat translucent face must not gain opacity along its triangulation seam."""

import pytest

from mcbe_editor.block_icon_renderer import ICON_SIZE, Texture, _draw_model_quad, _draw_quad


@pytest.mark.parametrize("model", [False, True], ids=["block", "model"])
@pytest.mark.parametrize("reverse", [False, True], ids=["clockwise", "counterclockwise"])
def test_translucent_quad_has_uniform_alpha(model, reverse):
    texture = Texture(1, 1, bytes((80, 160, 240, 128)))
    points = [(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)]
    if reverse:
        points.reverse()
    canvas = bytearray(ICON_SIZE * ICON_SIZE * 4)
    if model:
        _draw_model_quad(
            canvas,
            [float("inf")] * (ICON_SIZE * ICON_SIZE),
            texture,
            [(x, y, 0.0) for x, y in points],
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            1.0,
        )
    else:
        _draw_quad(canvas, texture, points, 1.0)

    for y in range(ICON_SIZE):
        for x in range(ICON_SIZE):
            expected_alpha = 128 if x < 8 and y < 8 else 0
            assert canvas[(y * ICON_SIZE + x) * 4 + 3] == expected_alpha, (x, y)
