"""Remember native window size without persisting monitor positions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mcbe_editor.runtime_data import atomic_write_private_text

LOGGER = logging.getLogger(__name__)


def initial_window_bounds(left: int, top: int, width: int, height: int, dpi: int, preferred_size: tuple[int, int] | None = None) -> tuple[int, int, int, int]:
    """Center a usable window inside the monitor's physical work area."""
    scale = dpi / 96
    margin = round(24 * scale)
    preferred_width, preferred_height = preferred_size or (round(1440 * scale), round(1280 * scale))
    window_width = min(max(round(800 * scale), preferred_width), max(1, width - 2 * margin))
    window_height = min(max(round(600 * scale), preferred_height), max(1, height - 2 * margin))
    return left + (width - window_width) // 2, top + (height - window_height) // 2, window_width, window_height


class DesktopWindowState:
    def __init__(self, data: Path):
        self.path = data / "desktop-window.json"
        self._maximized = False

    def _read(self) -> dict | None:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return None
        if not isinstance(saved, dict) or type(saved.get("maximized")) is not bool:
            return None
        if not all(type(saved.get(key)) is int and saved[key] > 0 for key in ("width", "height", "dpi")):
            return None
        return saved

    def apply(self, window) -> None:
        """Run before_show on the WinForms UI thread, before the first paint."""
        try:
            from System.Drawing import Point, Size
            from System.Windows.Forms import FormStartPosition, FormWindowState, Screen

            native = window.native
            area = Screen.FromControl(native).WorkingArea
            dpi = native.DeviceDpi
            saved = self._read()
            preferred = None
            if saved is not None:
                # Integer scaling retains the exact size at the same DPI.
                preferred = tuple((saved[key] * dpi + saved["dpi"] // 2) // saved["dpi"] for key in ("width", "height"))
            x, y, width, height = initial_window_bounds(area.Left, area.Top, area.Width, area.Height, dpi, preferred)
            native.MinimumSize = Size(min(round(800 * dpi / 96), width), min(round(600 * dpi / 96), height))
            native.StartPosition = FormStartPosition.Manual
            native.Size = Size(width, height)
            native.Location = Point(x, y)
            native.Resize += self._resized
            # FormClosed runs on the UI thread, only after the close guard allows
            # closing and before WinForms disposes the native window.
            native.FormClosed += self._closed
            if saved is not None and saved["maximized"]:
                native.WindowState = FormWindowState.Maximized
            self._resized(native, None)
        except Exception:
            LOGGER.warning("Could not restore the desktop window size", exc_info=True)

    def _resized(self, native, _event) -> None:
        from System.Windows.Forms import FormWindowState

        # Minimizing must not replace the previous normal/maximized preference.
        if native.WindowState != FormWindowState.Minimized:
            self._maximized = native.WindowState == FormWindowState.Maximized

    def _closed(self, native, _event) -> None:
        try:
            from System.Windows.Forms import FormWindowState

            bounds = native.Bounds if native.WindowState == FormWindowState.Normal else native.RestoreBounds
            saved = {"width": bounds.Width, "height": bounds.Height, "dpi": native.DeviceDpi, "maximized": self._maximized}
            atomic_write_private_text(self.path, json.dumps(saved) + "\n")
        except Exception:
            # A preference failure must never interfere with closing the editor.
            LOGGER.warning("Could not remember the desktop window size", exc_info=True)
