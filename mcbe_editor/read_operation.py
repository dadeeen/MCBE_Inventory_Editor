"""Cooperative progress and cancellation for read-only world operations."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .world_locks import world_lock_if_free


class ReadStoppedError(Exception):
    """A read exceeded its deadline, was cancelled, or lost its observer."""


_observer: ContextVar[Callable[..., None] | None] = ContextVar("world_read_observer", default=None)


@contextmanager
def observe(callback: Callable[..., None]) -> Iterator[None]:
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


def checkpoint(phase: str | None = None, *, current: int | None = None) -> None:
    callback = _observer.get()
    if callback is not None:
        callback(phase, current=current)


def is_observed() -> bool:
    return _observer.get() is not None


@contextmanager
def cancellable_world_lock(world_path: str) -> Iterator[None]:
    checkpoint("waiting")
    while True:
        with world_lock_if_free(world_path) as acquired:
            if acquired:
                checkpoint("opening")
                yield
                return
        checkpoint()
        time.sleep(0.05)
