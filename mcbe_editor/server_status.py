from __future__ import annotations

import random
import socket
import threading
import time
from typing import Any

from .config import AppConfig

RAKNET_MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")
_TRUE_STRING_VALUES = {"1", "true", "yes", "ja", "on", "confirmed"}
_STATUS_REVISION_LOCK = threading.Lock()
_STATUS_REVISION = 0


def _message_fields(message_key: str, **message_params: object) -> dict[str, object]:
    message = message_key
    for name, value in message_params.items():
        message = message.replace(f"{{{name}}}", str(value))
    return {
        "message": message,
        "message_key": message_key,
        "message_params": message_params,
    }


class ServerStatusProbeError(OSError):
    """An expected probe failure with a stable, localizable API message."""

    def __init__(self, message_key: str, *, technical_error: str = "", **message_params: object):
        self.message_key = message_key
        self.message_params = message_params
        self.technical_error = technical_error
        super().__init__(_message_fields(message_key, **message_params)["message"])


def _observed_status(status: dict[str, object]) -> dict[str, object]:
    global _STATUS_REVISION
    with _STATUS_REVISION_LOCK:
        _STATUS_REVISION += 1
        revision = _STATUS_REVISION
    return {**status, "server_status_revision": revision}


def _bedrock_ping_packet() -> bytes:
    ping_time = int(time.time() * 1000)
    client_guid = random.getrandbits(64)
    return b"\x01" + ping_time.to_bytes(8, "big", signed=True) + RAKNET_MAGIC + client_guid.to_bytes(8, "big")


def _parse_bedrock_pong(response: bytes) -> dict:
    if not response:
        return {"status": "unknown", **_message_fields("Leere Serverantwort.")}
    if response[0] != 0x1C:
        return {"status": "unknown", **_message_fields("Unerwartete Bedrock-Serverantwort.")}

    motd = ""
    if len(response) > 35:
        try:
            motd_len = int.from_bytes(response[33:35], "big")
            motd = response[35 : 35 + motd_len].decode("utf-8", errors="replace")
        except Exception:
            motd = ""
    return {"status": "online", **_message_fields("Server erreichbar."), "motd": motd}


def _bedrock_unconnected_ping(host: str, port: int, timeout: float = 1.5) -> dict:
    """Return Bedrock ping status for IPv4 or IPv6 server addresses.

    A failed address-family lookup must not silently downgrade an online IPv6
    server to an unknown-but-confirmable state. Try every UDP address returned
    by getaddrinfo. A timeout remains unknown because a missing UDP response
    cannot prove that the server is offline.
    """

    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except OSError as exc:
        raise ServerStatusProbeError(
            "Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden.",
            technical_error=str(exc),
        ) from exc
    if not addresses:
        raise ServerStatusProbeError("Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden.")

    packet = _bedrock_ping_packet()
    saw_timeout = False
    last_error: OSError | None = None
    first_unknown_response: dict | None = None
    tried_sockaddrs = set()

    for family, socktype, proto, _canonname, sockaddr in addresses:
        if sockaddr in tried_sockaddrs:
            continue
        tried_sockaddrs.add(sockaddr)
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(timeout)
                sock.sendto(packet, sockaddr)
                response, _addr = sock.recvfrom(4096)
        except TimeoutError:
            saw_timeout = True
            continue
        except OSError as exc:
            last_error = exc
            continue

        parsed = _parse_bedrock_pong(response)
        if parsed.get("status") == "online":
            return parsed
        if first_unknown_response is None:
            first_unknown_response = parsed

    if first_unknown_response is not None:
        return first_unknown_response
    if saw_timeout:
        raise TimeoutError("Keine Antwort vom Server.")
    if last_error is not None:
        raise last_error
    return {
        "status": "unknown",
        **_message_fields("Serverstatus unbekannt: keine prüfbare Serveradresse."),
    }


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRING_VALUES
    return False


def unknown_status_confirmation_from_payload(data: Any) -> bool:
    """Parse the explicit unknown-server confirmation flag from a request payload.

    Pure Hilfsfunktion ohne Flask-Kopplung: Die Web-Schicht (main.py) liest das
    Request-JSON und übergibt das Ergebnis explizit an ``write_gate``.
    """

    if not isinstance(data, dict):
        return False
    return _boolish(data.get("confirm_unknown_server_status"))


def check_server_status(config: AppConfig) -> dict:
    base = {
        "server_name": config.server_name,
        "server_host": config.server_host,
        "server_port": config.server_port,
        "require_server_offline": config.require_server_offline,
        "allow_edit_while_online": config.allow_edit_while_online,
        "read_only": bool(getattr(config, "read_only", False)),
    }

    if not config.server_host:
        return _observed_status(
            {
                **base,
                "status": "unknown",
                **_message_fields("Kein Minecraft-Server konfiguriert."),
            }
        )

    try:
        result = _bedrock_unconnected_ping(config.server_host, config.server_port)
        status = {**base, **result}
    except TimeoutError:
        status = {**base, "status": "unknown", **_message_fields("Keine Antwort vom Server.")}
    except ServerStatusProbeError as exc:
        status = {
            **base,
            "status": "unknown",
            **_message_fields(exc.message_key, **exc.message_params),
            "technical_error": exc.technical_error,
        }
    except OSError as exc:
        status = {
            **base,
            "status": "unknown",
            **_message_fields("Serverstatus unbekannt."),
            "technical_error": str(exc),
        }
    return _observed_status(status)


def _public_gate_config(config: AppConfig) -> dict:
    """Return only non-secret config fields useful for write-gate diagnostics."""

    return {
        "mode": config.mode,
        "server_name": config.server_name,
        "server_host": config.server_host,
        "server_port": config.server_port,
        "require_server_offline": config.require_server_offline,
        "allow_edit_while_online": config.allow_edit_while_online,
        "read_only": bool(getattr(config, "read_only", False)),
    }


def write_gate(config: AppConfig, status: dict | None = None, *, unknown_status_confirmed: bool | None = None) -> dict:
    status = status or check_server_status(config)
    allowed = True
    reason = "Bearbeitung erlaubt."
    override_active = False
    requires_unknown_server_confirmation = False
    # Die Bestätigung wird von der Web-Schicht explizit übergeben; dieses Modul
    # liest bewusst nicht mehr implizit aus dem Flask-Request.
    confirmed_unknown = bool(unknown_status_confirmed)

    status_value = status.get("status")
    if status_value == "unknown":
        if confirmed_unknown:
            allowed = True
            override_active = True
            reason = "Serverstatus unbekannt; Nutzerbestätigung für Schreibversuch liegt vor."
        else:
            allowed = False
            requires_unknown_server_confirmation = True
            reason = "Serverstatus unbekannt. Bitte bestätige vor dem Schreiben ausdrücklich, dass der Server gestoppt ist."
    elif config.require_server_offline and status_value == "online":
        allowed = False
        reason = "Server läuft noch. Bitte Server stoppen."

    # LevelDB read endpoints are always allowed because they must use the pure
    # readonly reader and never fall back to the mutating Amulet/LevelDbAdapter.
    # Server state is enforced at every write boundary instead.
    read_allowed = True
    read_only = bool(getattr(config, "read_only", False))
    if read_only:
        allowed = False
        override_active = False
        requires_unknown_server_confirmation = False
        reason = "Read-Only-Modus aktiv (MCBE_READ_ONLY). Welten können angesehen werden; Schreibaktionen bleiben blockiert."

    return {
        "allowed": allowed,
        "reason": reason,
        "override_active": override_active,
        "read_allowed": read_allowed,
        "read_only": read_only,
        "requires_unknown_server_confirmation": requires_unknown_server_confirmation,
        "unknown_status_confirmed": confirmed_unknown,
        "server_status": status,
        "config": _public_gate_config(config),
    }
