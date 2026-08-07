"""Handlers for basic app information and landing routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AppInfoRouteDeps:
    jsonify: Callable[..., Any]
    render_template: Callable[..., Any]
    get_csrf_token: Callable[[], str]
    public_app_config: Callable[[], dict]
    runtime_status_snapshot: Callable[[], dict]
    source_version_history_entries: Callable[[], list[dict]]


def healthz(deps: AppInfoRouteDeps):
    return deps.jsonify({"success": True, "status": "ok"})


def index(deps: AppInfoRouteDeps):
    return deps.render_template("index.html", csrf_token=deps.get_csrf_token(), app_config=deps.public_app_config())


def app_config(deps: AppInfoRouteDeps):
    return deps.jsonify({"success": True, "config": deps.public_app_config()})


def runtime_status(deps: AppInfoRouteDeps):
    return deps.jsonify({"success": True, "runtime_status": deps.runtime_status_snapshot()})


def versions(deps: AppInfoRouteDeps):
    return deps.render_template("versions.html", entries=reversed(deps.source_version_history_entries()))
