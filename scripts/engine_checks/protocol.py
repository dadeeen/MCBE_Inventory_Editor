"""Strict, run-bound framing for observations made inside the real engine."""

from __future__ import annotations

import json
import re

PREFIX = "[MCBE_ENGINE] "
ITEM_ID = re.compile(r"minecraft:[a-z0-9_]+\Z")
VERSION = re.compile(r"\bVersion:\s*(\d+\.\d+\.\d+\.\d+)\b")


class ProbeError(RuntimeError):
    """An incomplete or contradictory observation is never a successful test."""


class Transcript:
    def __init__(self, run_id: str, phase: str, expected_version: str):
        self.run_id = run_id
        self.phase = phase
        self.expected_version = expected_version
        self.version: str | None = None
        self.events: list[dict] = []
        self.done = False

    def feed(self, line: str) -> None:
        if match := VERSION.search(line):
            version = match.group(1)
            if version != self.expected_version:
                raise ProbeError(f"Server version mismatch: expected {self.expected_version}, observed {version}")
            self.version = version
        if PREFIX not in line:
            return
        raw = line.split(PREFIX, 1)[1].strip()
        if len(raw) > 1_000_000:
            raise ProbeError("Oversized probe event")
        try:
            event = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ProbeError("Malformed probe event") from exc
        if not isinstance(event, dict) or event.get("run_id") != self.run_id or event.get("phase") != self.phase:
            raise ProbeError("Probe event belongs to another run or phase")
        if self.done or type(event.get("seq")) is not int or event["seq"] != len(self.events):
            raise ProbeError("Duplicate, missing, reordered or trailing probe event")
        kind = event.get("kind")
        if not self.events and kind != "begin":
            raise ProbeError("Missing probe begin event")
        if self.events and kind == "begin":
            raise ProbeError("Duplicate probe begin event")
        if kind not in {"begin", "registry", "item", "case", "error", "done"}:
            raise ProbeError("Unknown probe event")
        self.events.append(event)
        self.done = kind == "done"

    def finish(self) -> list[dict]:
        if not self.done or self.version is None:
            raise ProbeError("Engine exited without both the expected version and a complete probe")
        errors = [event for event in self.events if event["kind"] == "error"]
        last = self.events[-1]
        for kind, field in (("item", "items"), ("case", "cases"), ("error", "errors")):
            count = sum(event["kind"] == kind for event in self.events)
            if type(last.get(field)) is not int or last[field] != count:
                raise ProbeError(f"Incomplete {kind} event count")
        if errors and self.phase != "catalog":
            raise ProbeError(f"Engine reported {len(errors)} test failures: {errors[0].get('message', '')}")
        return self.events


def catalog_result(events: list[dict], expected_ids: list[str], recorded_limits: dict[str, int]) -> dict:
    if any(type(limit) is not int or not 1 <= limit <= 127 for limit in recorded_limits.values()):
        raise ProbeError("Invalid recorded catalog stack limit")
    registries = [event for event in events if event["kind"] == "registry"]
    if len(registries) != 1 or not isinstance(registries[0].get("ids"), list):
        raise ProbeError("Missing or duplicate engine registry")
    registered = registries[0]["ids"]
    if any(not isinstance(item, str) or not ITEM_ID.fullmatch(item) for item in registered) or len(set(registered)) != len(registered):
        raise ProbeError("Invalid or duplicate registered item ID")
    requested = set(expected_ids) | set(registered)
    observed, errors = {}, {}
    for event in events:
        kind = event["kind"]
        if kind not in {"item", "error"}:
            continue
        item_id = event.get("id")
        if item_id not in requested or item_id in observed or item_id in errors:
            raise ProbeError("Unexpected or duplicate catalog observation")
        if kind == "error":
            errors[item_id] = str(event.get("message", "Probe failed"))[:500]
            continue
        limit = event.get("max_amount")
        durability = event.get("max_durability")
        components = event.get("components")
        if type(limit) is not int or not 1 <= limit <= 255:
            raise ProbeError(f"Invalid engine stack limit: {item_id}")
        if durability is not None and (type(durability) is not int or durability < 1):
            raise ProbeError(f"Invalid engine durability: {item_id}")
        if not isinstance(components, list) or any(not isinstance(component, str) for component in components):
            raise ProbeError(f"Invalid component list: {item_id}")
        observed[item_id] = {"max_amount": limit, "max_durability": durability, "components": sorted(set(components))}
    if set(observed) | set(errors) != requested:
        raise ProbeError("Catalog probe omitted requested items")
    missing = sorted(set(expected_ids) - set(observed))
    mismatches = {
        item: {"catalog": recorded_limits[item], "engine": observed[item]["max_amount"]}
        for item in expected_ids if item in observed and item in recorded_limits and recorded_limits[item] != observed[item]["max_amount"]
    }
    unsupported = sorted(item for item in expected_ids if item in observed and observed[item]["max_amount"] > 127)
    registry_missing = sorted(set(expected_ids) - set(registered))
    registry_extra = sorted(set(registered) - set(expected_ids))
    candidates = {item: observed[item]["max_amount"] for item in sorted(observed) if item not in recorded_limits}
    return {
        "status": "fail" if mismatches or unsupported else "partial" if missing or errors or registry_missing or registry_extra or candidates else "pass",
        "expected_count": len(expected_ids), "observed_count": len(set(expected_ids) & observed.keys()),
        "missing": missing, "mismatches": mismatches, "outside_editor_count_range": unsupported,
        "registry_missing": registry_missing,
        "registry_extra": registry_extra,
        "observations": dict(sorted(observed.items())), "errors": dict(sorted(errors.items())),
        "new_limit_candidates": candidates,
    }
