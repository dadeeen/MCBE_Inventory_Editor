"""Direct Docker health check, independent of runtime data and first-run setup."""

from __future__ import annotations

import json
import os
import sys
from contextlib import closing
from http.client import HTTPConnection, HTTPException

from .config import _host_for_origin, request_host_is_trusted


def _health_host_header(port: int, trusted_hosts: tuple[str, ...]) -> str:
    # Connect to loopback even when only the deployment's public hostname is
    # accepted. A leading dot permits that domain and its subdomains in Flask.
    trusted = list(trusted_hosts) or None
    for configured in trusted_hosts or ("127.0.0.1",):
        try:
            authority = _host_for_origin(configured.removeprefix(".")).encode("idna").decode("ascii")
        except UnicodeError:
            continue
        if not request_host_is_trusted(authority, trusted):
            continue
        # Validate before replacing the optional deployment port so malformed
        # authorities cannot become valid through normalization. IPv6 colons
        # belong to the bracketed address, not to a port separator.
        host = authority.partition("]")[0] + "]" if authority.startswith("[") else authority.partition(":")[0]
        header = f"{host}:{port}"
        if request_host_is_trusted(header, trusted):
            return header
    raise ValueError("MCBE_TRUSTED_HOSTS contains no valid health-check hostname")


def check_health(port: int, *, trusted_hosts: tuple[str, ...] = ()) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("Health-check port must be between 1 and 65535")
    header = _health_host_header(port, trusted_hosts)
    # HTTPConnection never consults environment proxies or follows redirects.
    with closing(HTTPConnection("127.0.0.1", port, timeout=2)) as connection:
        connection.request("GET", "/healthz", headers={"Host": header})
        response = connection.getresponse()
        if response.status != 200 or json.loads(response.read(4096)) != {"success": True, "status": "ok"}:
            raise ValueError("Unexpected local health response")


def main() -> int:
    try:
        port = int(os.environ.get("MCBE_EDITOR_PORT") or "8080")
        trusted_hosts = tuple(host.strip().rstrip("/") for host in os.environ.get("MCBE_TRUSTED_HOSTS", "").split(",") if host.strip())
        check_health(port, trusted_hosts=trusted_hosts)
    except (OSError, ValueError, HTTPException) as exc:
        print(f"Local health check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
