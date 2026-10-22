from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from mcbe_editor import desktop_window


@pytest.fixture
def native_window(monkeypatch):
    native = SimpleNamespace(
        DeviceDpi=144,
        WindowState="normal",
        Bounds=SimpleNamespace(Width=1500, Height=1050),
        RestoreBounds=SimpleNamespace(Width=1401, Height=901),
        Resize=MagicMock(),
        FormClosed=MagicMock(),
    )
    native.Resize.__iadd__.return_value = native.Resize
    native.FormClosed.__iadd__.return_value = native.FormClosed
    area = SimpleNamespace(Left=-2560, Top=40, Width=2560, Height=1400)
    monkeypatch.setitem(sys.modules, "System.Drawing", SimpleNamespace(Point=lambda *xy: xy, Size=lambda *wh: wh))
    monkeypatch.setitem(
        sys.modules,
        "System.Windows.Forms",
        SimpleNamespace(
            Screen=SimpleNamespace(FromControl=lambda _native: SimpleNamespace(WorkingArea=area)),
            FormStartPosition=SimpleNamespace(Manual="manual"),
            FormWindowState=SimpleNamespace(Normal="normal", Maximized="maximized", Minimized="minimized"),
        ),
    )
    return native


@pytest.mark.parametrize("maximized", [False, True])
def test_restore_saved_size_scales_to_current_dpi(tmp_path, native_window, maximized):
    state = desktop_window.DesktopWindowState(tmp_path)
    state.path.write_text(json.dumps({"width": 1000, "height": 700, "dpi": 96, "maximized": maximized}))
    state.apply(SimpleNamespace(native=native_window))
    assert native_window.Size == (1500, 1050)
    assert native_window.Location == (-2030, 215)
    assert native_window.WindowState == ("maximized" if maximized else "normal")
    assert native_window.MinimumSize == (1200, 900)


@pytest.mark.parametrize("preferred,expected", [((5000, 3000), (1318, 680)), ((1, 1), (800, 600)), ((1001, 650), (1001, 650))])
def test_restore_size_fits_smaller_monitor_and_keeps_controls_reachable(preferred, expected):
    x, y, width, height = desktop_window.initial_window_bounds(100, 40, 1366, 728, 96, preferred)
    assert (width, height) == expected
    assert x >= 100 and y >= 40
    assert x + width <= 1466 and y + height <= 768


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"\xff",
        b"[]",
        b"null",
        b'{"width": 1000, "height": 700}',
        b'{"width": true, "height": 700, "dpi": 96, "maximized": false}',
        b'{"width": 1000, "height": -1, "dpi": 96, "maximized": false}',
        b'{"width": 1000, "height": 700, "dpi": 0, "maximized": false}',
        b'{"width": 1000, "height": 700, "dpi": 96, "maximized": "false"}',
    ],
)
def test_invalid_settings_keep_automatic_start_size(tmp_path, native_window, content):
    state = desktop_window.DesktopWindowState(tmp_path)
    state.path.write_bytes(content)
    state.apply(SimpleNamespace(native=native_window))
    assert native_window.Size == (2160, 1328)
    assert native_window.WindowState == "normal"


@pytest.mark.parametrize("maximized,minimized", [(False, False), (True, False), (False, True), (True, True)])
def test_close_remembers_normal_bounds_and_last_nonminimized_state(tmp_path, native_window, maximized, minimized):
    state = desktop_window.DesktopWindowState(tmp_path)
    state.apply(SimpleNamespace(native=native_window))
    resized = native_window.Resize.__iadd__.call_args.args[0]
    closed = native_window.FormClosed.__iadd__.call_args.args[0]
    native_window.WindowState = "maximized" if maximized else "normal"
    resized(native_window, None)
    if minimized:
        native_window.WindowState = "minimized"
        resized(native_window, None)
    # Resizing and an unconfirmed close cannot persist or discard anything.
    assert not state.path.exists()
    closed(native_window, None)
    expected_size = (1401, 901) if maximized or minimized else (1500, 1050)
    assert json.loads(state.path.read_text()) == {"width": expected_size[0], "height": expected_size[1], "dpi": 144, "maximized": maximized}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["desktop-window.json"]
    # At unchanged DPI the restore bounds survive without rounding drift.
    native_window.WindowState = "normal"
    desktop_window.DesktopWindowState(tmp_path).apply(SimpleNamespace(native=native_window))
    assert native_window.Size == expected_size
    assert native_window.WindowState == ("maximized" if maximized else "normal")


def test_preference_write_failure_does_not_prevent_closing(tmp_path, native_window, monkeypatch, caplog):
    state = desktop_window.DesktopWindowState(tmp_path)
    state.apply(SimpleNamespace(native=native_window))
    monkeypatch.setattr(desktop_window, "atomic_write_private_text", Mock(side_effect=OSError("read only")))
    native_window.FormClosed.__iadd__.call_args.args[0](native_window, None)
    assert "Could not remember the desktop window size" in caplog.text
    assert not state.path.exists()
