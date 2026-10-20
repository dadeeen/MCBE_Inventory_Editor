"""Local browser launch and bounded identification of an occupied editor port."""

from __future__ import annotations

import contextlib
import ipaddress
import os
import sys
import webbrowser
from http.client import HTTPConnection, HTTPException

from .config import _host_for_origin


def browser_url(host: str, port: int) -> str:
    browser_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    return f"http://{_host_for_origin(browser_host)}:{port}/"


def existing_editor_url(host: str, port: int) -> str | None:
    """Only identify a local editor; never follow redirects or system proxies."""
    probe_host = {"0.0.0.0": "127.0.0.1", "::": "::1", "localhost": "127.0.0.1"}.get(host, host)
    try:
        if not ipaddress.ip_address(probe_host).is_loopback:
            return None
    except ValueError:
        return None
    try:
        with contextlib.closing(HTTPConnection(probe_host, port, timeout=2)) as connection:
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            if response.status == 200 and response.getheader("X-MCBE-Editor") == "1":
                return browser_url(probe_host, port) + "?already_running=1"
    except (OSError, HTTPException):
        pass
    return None


def open_browser_url(url: str, logger) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(url)
            logger.info("opened browser via Windows shell url=%s", url)
        elif webbrowser.open(url, new=2):
            logger.info("opened browser url=%s", url)
        else:
            logger.warning("browser auto-open returned false url=%s", url)
    except Exception as exc:
        logger.warning("browser auto-open failed url=%s error=%s", url, exc)
