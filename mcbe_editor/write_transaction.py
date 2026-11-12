"""Typed write plans and the boundary between attempted and committed writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Literal

from .db import BedrockDb
from .service_errors import WriteNotAttemptedError


def _may_have_reached_storage(db: BedrockDb, error: BaseException) -> bool:
    """Only a known gate rejection or a writer's own evidence rules out a write."""

    if isinstance(error, WriteNotAttemptedError):
        return False
    reached = getattr(db, "last_write_reached_log", None)
    if not callable(reached):
        return True
    try:
        return reached() is not False
    except Exception:
        return True


@dataclass(frozen=True)
class WritePlan:
    writes: Mapping[bytes, bytes | None]
    mode: Literal["single", "batch"] = "batch"
    precondition: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        entries = dict(self.writes)
        if not entries or any(not isinstance(key, bytes) or (value is not None and not isinstance(value, bytes)) for key, value in entries.items()):
            raise ValueError("Ungültiger Schreibplan: Es werden nicht leere binäre Datenbankeinträge erwartet.")
        if self.mode not in {"single", "batch"}:
            raise ValueError("Ungültiger Schreibplan: Unbekannte Schreibart.")
        if self.mode == "single" and (len(entries) != 1 or next(iter(entries.values())) is None):
            raise ValueError("Ungültiger Schreibplan: Einzelschreiben benötigt genau einen Wert.")
        if self.precondition is not None and not callable(self.precondition):
            raise ValueError("Ungültiger Schreibplan: Die Schreibvorbedingung muss aufrufbar sein.")
        # A caller must not change the batch after preparing it.
        object.__setattr__(self, "writes", MappingProxyType(entries))

    @classmethod
    def single(cls, key: bytes, value: bytes, *, precondition: Callable[[], None] | None = None) -> WritePlan:
        return cls({key: value}, mode="single", precondition=precondition)


class WritePhase(Enum):
    PREPARED = "prepared"
    ATTEMPTED = "attempted"
    COMMITTED = "committed"


@dataclass
class WriteState:
    phase: WritePhase = field(default=WritePhase.PREPARED, init=False)
    storage_possibly_changed: bool = field(default=True, init=False)
    _execution_started: bool = field(default=False, init=False)

    @property
    def attempted(self) -> bool:
        return self.phase is not WritePhase.PREPARED

    @property
    def committed(self) -> bool:
        return self.phase is WritePhase.COMMITTED

    @property
    def outcome_unknown(self) -> bool:
        """The database call raised after its batch may have reached storage."""

        return self.phase is WritePhase.ATTEMPTED and self.storage_possibly_changed

    def execute(self, db: BedrockDb, plan: WritePlan) -> None:
        if self._execution_started:
            raise RuntimeError("Dieser Schreibvorgang wurde bereits versucht und darf nicht erneut ausgeführt werden.")
        self._execution_started = True
        precondition_failed = False

        def check() -> None:
            nonlocal precondition_failed
            try:
                assert plan.precondition is not None
                plan.precondition()
            except BaseException:
                precondition_failed = True
                raise

        bind_condition = getattr(db, "write_precondition", None) if plan.precondition is not None else None
        with bind_condition(check) if callable(bind_condition) else nullcontext():
            self.phase = WritePhase.ATTEMPTED
            try:
                if plan.precondition is not None and not callable(bind_condition):
                    # Simple/offline adapters have no later application gate.
                    check()
                if plan.mode == "single":
                    key, value = next(iter(plan.writes.items()))
                    assert value is not None  # Enforced when the immutable plan is built.
                    db.put(key, value)
                else:
                    db.put_batch(dict(plan.writes))
            except BaseException as exc:
                if precondition_failed:
                    # The callback precedes storage, even if this adapter still
                    # carries evidence of an earlier successful write. Keep the
                    # original exception and let callers remove aborted backups.
                    self.phase = WritePhase.PREPARED
                    self.storage_possibly_changed = False
                else:
                    self.storage_possibly_changed = _may_have_reached_storage(db, exc)
                raise
            # A put can raise after touching storage. Such an attempt stays distinct
            # from a confirmed commit, and its recovery backup must be retained.
            self.phase = WritePhase.COMMITTED
