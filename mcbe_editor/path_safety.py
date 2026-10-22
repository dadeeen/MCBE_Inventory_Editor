"""Filesystem boundaries shared by world, backup and asset readers."""

from __future__ import annotations

import os
import re
import stat

_WINDOWS_DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"})


def is_unsafe_windows_name(part: str) -> bool:
    """Identify a path component Win32 rejects or resolves as a device/alias."""
    device = part.split(".", 1)[0].rstrip(" ").upper()
    return (
        part.endswith((".", " "))
        or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
        or device in _WINDOWS_DEVICE_NAMES
        or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", device) is not None
    )


def is_linklike_stat(info: os.stat_result) -> bool:
    """Include Windows junctions and other reparse points, not just symlinks."""
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def is_linklike(path: str | os.PathLike[str]) -> bool:
    try:
        return is_linklike_stat(os.lstat(path))
    except FileNotFoundError:
        return False
