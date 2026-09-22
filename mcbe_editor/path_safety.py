"""Filesystem boundaries shared by world, backup and asset readers."""

from __future__ import annotations

import os
import stat


def is_linklike_stat(info: os.stat_result) -> bool:
    """Include Windows junctions and other reparse points, not just symlinks."""
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def is_linklike(path: str | os.PathLike[str]) -> bool:
    try:
        return is_linklike_stat(os.lstat(path))
    except FileNotFoundError:
        return False
