"""Bounded, state-specific player discovery, separate from selected reads."""

import copy
import logging
import threading
from collections import OrderedDict

from .db_state import CommittedDbChange
from .players import PlayerScanner, classify_player_record, encode_player_key, localize_player_labels

LOGGER = logging.getLogger(__name__)


class PlayerDirectory:
    def __init__(self, max_worlds: int = 8):
        self._max_worlds = max_worlds
        self._entries: OrderedDict[str, tuple[tuple, list[dict]]] = OrderedDict()
        self._guard = threading.Lock()

    def list_players(self, db) -> list[dict]:
        token_of = getattr(db, "content_token", None)
        try:
            token = token_of() if callable(token_of) else None
        except OSError:
            LOGGER.warning("Datenbankzustand nicht bestimmbar; Spielerliste wird ohne Cache gelesen.", exc_info=True)
            token = None
        if token is not None:
            with self._guard:
                cached = self._entries.get(token[0])
                if cached is not None and cached[0] == token:
                    self._entries.move_to_end(token[0])
                    return localize_player_labels(copy.deepcopy(cached[1]))
        players = PlayerScanner(db).list_players()
        if token is not None:
            with self._guard:
                self._entries[token[0]] = (token, copy.deepcopy(players))
                self._entries.move_to_end(token[0])
                while len(self._entries) > self._max_worlds:
                    self._entries.popitem(last=False)
        return players

    def accept_committed_write(self, db) -> None:
        """Best-effort maintenance; never turn a committed save into a failure."""

        try:
            receipt_of = getattr(db, "committed_change", None)
            change = receipt_of() if callable(receipt_of) else None
            if isinstance(change, CommittedDbChange):
                self._apply_change(change)
        except Exception:
            LOGGER.warning("Spielerverzeichnis konnte nach dem Schreiben nicht aktualisiert werden.", exc_info=True)

    def _apply_change(self, change: CommittedDbChange) -> None:
        # Start with one existing player. Unknown-key candidates have a bounded
        # discovery order: patching those could expose/hide another candidate.
        # Imports, deletions and actor/multi-record changes use full discovery.
        if len(change.entries) != 1 or change.before[0] != change.after[0]:
            return
        key, value = change.entries[0]
        if value is None:
            return
        with self._guard:
            cached = self._entries.get(change.before[0])
            if cached is None or cached[0] != change.before:
                return
        encoded_key = encode_player_key(key)
        if not any(player["player_key"] == encoded_key for player in cached[1]):
            return
        player = classify_player_record(key, value)
        if player is None:
            return
        updated = [player if entry["player_key"] == encoded_key else entry for entry in cached[1]]
        updated.sort(key=lambda item: (item["kind"] != "local", item["kind"] == "unknown", item["label"].lower()))
        with self._guard:
            # Another discovery must not be replaced by an older transition.
            if self._entries.get(change.before[0]) is cached:
                self._entries[change.before[0]] = (change.after, updated)
                self._entries.move_to_end(change.before[0])
