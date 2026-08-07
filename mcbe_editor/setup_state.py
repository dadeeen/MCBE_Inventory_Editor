from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import new as new_hash
from pathlib import Path
from string import hexdigits
from typing import Any

from mcbe_editor.runtime_data import atomic_write_private_text, restrict_private_file

_MAX_PASSWORD_HASH_WORK = 128 * 1024 * 1024
_MAX_PBKDF2_ITERATIONS = 2_000_000
_MAX_SCRYPT_N = 1 << 20
_MAX_SCRYPT_R = 64
_MAX_SCRYPT_P = 16


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def is_supported_password_hash(value: object) -> bool:
    """Validate the serialized shape of a Werkzeug password hash cheaply.

    Password verification itself is intentionally not performed here because
    scrypt would make this frequently called setup-state check expensive.  The
    project pins Werkzeug 3.x, whose supported serialized methods are scrypt
    and PBKDF2.
    """

    if not isinstance(value, str):
        return False
    serialized = value.strip()
    try:
        method_spec, salt, digest = serialized.split("$", 2)
    except ValueError:
        return False
    if not method_spec or not salt or not digest or len(digest) % 2 or any(char not in hexdigits for char in digest):
        return False

    method_parts = method_spec.split(":")
    method = method_parts[0]
    if method == "scrypt":
        if len(method_parts) == 1:
            return len(digest) == 128
        if len(method_parts) != 4:
            return False
        try:
            n, r, p = (int(part) for part in method_parts[1:])
        except ValueError:
            return False
        estimated_work = 132 * n * r * p
        return (
            n > 1
            and n & (n - 1) == 0
            and n <= _MAX_SCRYPT_N
            and 0 < r <= _MAX_SCRYPT_R
            and 0 < p <= _MAX_SCRYPT_P
            and estimated_work <= _MAX_PASSWORD_HASH_WORK
            and len(digest) == 128
        )

    if method == "pbkdf2":
        if len(method_parts) == 1:
            algorithm = "sha256"
        elif len(method_parts) in {2, 3}:
            algorithm = method_parts[1]
            if len(method_parts) == 3:
                try:
                    iterations = int(method_parts[2])
                    if iterations <= 0 or iterations > _MAX_PBKDF2_ITERATIONS:
                        return False
                except ValueError:
                    return False
        else:
            return False
        try:
            expected_hex_length = new_hash(algorithm).digest_size * 2
        except ValueError:
            return False
        return len(digest) == expected_hex_length

    return False


@dataclass(frozen=True)
class SetupSummary:
    enabled: bool
    completed: bool
    mode: str
    path: str | None
    reason: str | None = None


class FirstRunSetup:
    """Persistent first-run setup state for small LAN/Docker deployments.

    Environment variables remain the strongest configuration mechanism.  This
    state file is only used when the app is reachable beyond localhost and no
    password/hash was provided by the operator.  It lets a human make an explicit
    first-open decision without turning the normal Docker Compose example into a
    wall of security knobs.
    """

    def __init__(self, path: str | os.PathLike[str] | None):
        self.path = Path(path).expanduser() if path else None
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {}
        self._storage_available = False
        self._storage_error: str | None = None
        self.reload()

    @property
    def storage_available(self) -> bool:
        return self._storage_available

    @property
    def storage_error(self) -> str | None:
        return self._storage_error

    def _refresh_storage_availability(self) -> None:
        if self.path is None:
            self._storage_available = False
            self._storage_error = "no-persistent-setup-path"
            return

        probe = self.path.with_name(f".{self.path.name}.{os.getpid()}.{secrets.token_hex(8)}.probe")
        try:
            atomic_write_private_text(probe, "")
            probe.unlink()
        except OSError as exc:
            self._storage_available = False
            self._storage_error = f"{exc.__class__.__name__}: {exc}"
            with contextlib.suppress(OSError):
                probe.unlink(missing_ok=True)
        else:
            self._storage_available = True
            self._storage_error = None

    def reload(self) -> None:
        with self._lock:
            self._state = {}
            if self.path and self.path.exists():
                try:
                    restrict_private_file(self.path)
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                    pass
                else:
                    if isinstance(data, dict):
                        self._state = data
            self._refresh_storage_availability()

    def _atomic_write(self, data: dict[str, Any]) -> None:
        if not self.path:
            raise RuntimeError("Setup kann nicht gespeichert werden: kein Setup-Pfad konfiguriert.")
        atomic_write_private_text(self.path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        self._state = data
        self._storage_available = True
        self._storage_error = None

    def completed(self) -> bool:
        """Return whether the persisted setup decision is internally complete.

        A mode marker alone is not sufficient.  Interrupted/manual writes can
        leave ``auth_mode`` behind without the password hash or explicit open-
        mode acknowledgement.  Treating that state as completed can otherwise
        bypass first-run setup or make an auth-required deployment impossible
        to unlock.
        """

        with self._lock:
            mode = self._state.get("auth_mode")
            if mode == "password":
                return is_supported_password_hash(self._state.get("password_hash"))
            if mode == "open":
                return self._state.get("risk_acknowledged") is True
            return False

    def mode(self) -> str:
        with self._lock:
            value = self._state.get("auth_mode")
        return value if value in {"password", "open"} else "pending"

    def username(self, default: str = "admin") -> str:
        with self._lock:
            value = self._state.get("username")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    def password_hash(self) -> str | None:
        with self._lock:
            if self._state.get("auth_mode") != "password":
                return None
            value = self._state.get("password_hash")
        return value.strip() if isinstance(value, str) and is_supported_password_hash(value) else None

    def secret_key(self) -> str | None:
        with self._lock:
            value = self._state.get("secret_key")
        return value if isinstance(value, str) and value else None

    def open_acknowledged(self) -> bool:
        with self._lock:
            return self._state.get("auth_mode") == "open" and self._state.get("risk_acknowledged") is True

    def save_password(self, *, username: str, password_hash: str) -> str:
        if not username.strip():
            raise ValueError("Benutzername darf nicht leer sein.")
        if not is_supported_password_hash(password_hash):
            raise ValueError("Passwort-Hash ist leer oder hat kein unterstütztes Werkzeug-Format.")
        with self._lock:
            secret_key = self._state.get("secret_key")
            if not isinstance(secret_key, str) or not secret_key:
                secret_key = secrets.token_urlsafe(32)
            data = {
                "setup_version": 1,
                "created_at": self._state.get("created_at") or _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "auth_mode": "password",
                "username": username.strip(),
                "password_hash": password_hash.strip(),
                "secret_key": secret_key,
            }
            self._atomic_write(data)
        return secret_key

    def save_open(self) -> None:
        with self._lock:
            data = {
                "setup_version": 1,
                "created_at": self._state.get("created_at") or _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "auth_mode": "open",
                "risk_acknowledged": True,
            }
            self._atomic_write(data)

    def summary(self) -> SetupSummary:
        return SetupSummary(
            enabled=self.storage_available,
            completed=self.completed(),
            mode=self.mode(),
            path=str(self.path) if self.path else None,
            reason=None if self.storage_available else ("no-persistent-setup-path" if self.path is None else "setup-storage-unwritable"),
        )
