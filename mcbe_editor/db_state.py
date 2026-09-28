"""Optional evidence for reusing derived data across a committed DB write."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommittedDbChange:
    """A committed batch and its expected state transition.

    Tokens are opaque to consumers. ``after`` is derived from ``before`` and
    the verified write, not a later observation that could include unrelated
    changes. A fresh reader must still match it before reusing derived data.
    """

    before: tuple
    after: tuple
    entries: tuple[tuple[bytes, bytes | None], ...]
