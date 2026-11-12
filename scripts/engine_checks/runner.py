"""Bounded Docker orchestration; optional loopback client, never existing worlds."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import stat
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .addon import ADDON_LIMITS, DATA_MODULE_ID, make_addon_cases, prepare_addon
from .cases import make_cases, validate_case_events
from .client_profile import CLIENT_API_VERSION, CONTROL_NAME, CONTROL_SLOTS
from .equipment import make_equipment_cases
from .extended import enchantment_registry_result, extend_cases, matrix_result, validate_behavior_events
from .protocol import ProbeError, Transcript, catalog_result
from .service_profile import assignments, make_service_cases
from .special import make_special_cases, revision_cases

ROOT = Path(__file__).resolve().parents[2]
PACK = Path(__file__).with_name("pack")
PACK_ID = "17d45c09-8f23-48f5-b677-978d76841561"
SCRIPT_ID = "7a5336d1-e3ae-49c6-9f0d-e677ab0728fd"
WORLD_NAME = "engine-probe"
API_VERSION = "2.9.0"


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    from mcbe_editor.runtime_data import atomic_write_private_text

    # Status readers must see either complete version, including after an
    # interrupted write. This also keeps account-bearing identity files private.
    atomic_write_private_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def extract_server(archive: Path, destination: Path, expected_hash: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) or sha256(archive) != expected_hash.lower():
        raise ProbeError("Server archive SHA-256 mismatch")
    if destination.exists():
        raise ProbeError("Server extraction requires a new directory")
    with zipfile.ZipFile(archive) as zipped:
        infos = zipped.infolist()
        if len(infos) > 100_000 or sum(info.file_size for info in infos) > 2_000_000_000:
            raise ProbeError("Server archive exceeds extraction limits")
        seen = set()
        for info in infos:
            path = PurePosixPath(info.filename)
            parts = path.parts
            if (
                not parts
                or path.is_absolute()
                or "\\" in info.filename
                or any(part in {".", ".."} or ":" in part or part.endswith((".", " ")) for part in parts)
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ProbeError("Unsafe path in server archive")
            key = path.as_posix().casefold()
            if key in seen:
                raise ProbeError("Duplicate path in server archive")
            seen.add(key)
            if parts[0].casefold() == "worlds":
                raise ProbeError("Server archive contains pre-existing worlds")
        if "bedrock_server" not in seen:
            raise ProbeError("A Linux Bedrock Dedicated Server archive is required")
        destination.mkdir(parents=True)
        for info in infos:
            path = destination.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as source, path.open("xb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            path.chmod(0o755 if path.name == "bedrock_server" or path.suffix == ".so" else 0o644)
    with (destination / "bedrock_server").open("rb") as binary:
        if binary.read(4) != b"\x7fELF":
            raise ProbeError("Server executable is not a Linux ELF binary")


def prepare_pack(server: Path, config: dict) -> None:
    pack = server / "behavior_packs" / "mcbe_engine_probe"
    (pack / "scripts").mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": 2,
        "header": {
            "name": "MCBE editor engine checks",
            "description": "Disposable test instrumentation; no Vanilla overrides",
            "uuid": PACK_ID,
            "version": [1, 0, 0],
            "min_engine_version": [1, 26, 50],
        },
        "modules": [{"type": "script", "language": "javascript", "uuid": SCRIPT_ID, "version": [1, 0, 0], "entry": "scripts/main.js"}],
        "dependencies": [{"module_name": "@minecraft/server", "version": API_VERSION}],
    }
    if config.get("controlled_addon"):
        manifest["modules"].append({"type": "data", "uuid": DATA_MODULE_ID, "version": [1, 0, 0]})
        prepare_addon(pack)
    if config.get("client_profile") or config.get("village_profile"):
        manifest["dependencies"][0]["version"] = CLIENT_API_VERSION
        manifest["header"]["min_engine_version"] = [1, 26, 60]
    write_json(pack / "manifest.json", manifest)
    for script in (PACK / "scripts").glob("*.js"):
        (pack / "scripts" / script.name).write_bytes(script.read_bytes())
    (pack / "scripts" / "config.js").write_text("export const config = " + json.dumps(config, ensure_ascii=True) + ";\n", encoding="utf-8")
    world = server / "worlds" / WORLD_NAME
    world.mkdir(parents=True, exist_ok=True)
    write_json(world / "world_behavior_packs.json", [{"pack_id": PACK_ID, "version": [1, 0, 0]}])


def configure_server(server: Path, *, client_port: int | None = None) -> None:
    # Only a runner-owned Docker container may start this configuration.
    properties = {
        "server-name": "MCBE disposable engine check",
        "level-name": WORLD_NAME,
        "level-seed": "9172026",
        "gamemode": "creative",
        "difficulty": "peaceful",
        "allow-cheats": "true",
        "max-players": "1",
        "online-mode": "false",
        "allow-list": "false",
        "transport": "raknet",
        "enable-lan-visibility": "false",
        "view-distance": "5",
        "tick-distance": "4",
        "max-threads": "2",
        "content-log-file-enabled": "true",
        "content-log-console-output-enabled": "true",
        "emit-server-telemetry": "false",
        "script-watchdog-enable": "true",
    }
    if client_port is not None:
        if type(client_port) is not int or not 1024 <= client_port <= 65535:
            raise ProbeError("Client port must be an integer between 1024 and 65535")
        # Current clients require NetherNet's local HTTP/TCP signaling and
        # negotiated UDP transport. Advertise only the host's loopback mapping,
        # never an ephemeral container/private/public address as the target.
        properties.update({"transport": "nethernet", "server-port": "19132", "server-ip": "0.0.0.0", "server-udp-ports": f"127.0.0.1:{client_port}:19132"})
    (server / "server.properties").write_text("".join(f"{key}={value}\n" for key, value in properties.items()), encoding="utf-8")
    write_json(server / "allowlist.json", [])
    write_json(server / "permissions.json", [])
    permissions = server / "config" / "default"
    permissions.mkdir(parents=True, exist_ok=True)
    write_json(permissions / "permissions.json", {"allowed_modules": ["@minecraft/server"]})


def docker_command(args: list[str], *, timeout: float = 30) -> str:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError("Docker is unavailable or did not respond in time") from exc
    if result.returncode:
        raise ProbeError(f"Docker {args[0]} failed: {result.stderr.strip()[:1200]}")
    return result.stdout.strip()


def container_arguments(server: Path, name: str, image_id: str, owner: str | None = None, *, client_port: int | None = None) -> list[str]:
    source = str(server.resolve())
    if "," in source:
        raise ProbeError("Docker bind-mount paths may not contain commas")
    network = ["--network", "none"]
    if client_port is not None:
        if type(client_port) is not int or not 1024 <= client_port <= 65535:
            raise ProbeError("Client port must be an integer between 1024 and 65535")
        network = ["--network", "bridge", "--publish", f"127.0.0.1:{client_port}:19132/tcp", "--publish", f"127.0.0.1:{client_port}:19132/udp"]
    return [
        "create",
        "--interactive",
        "--name",
        name,
        "--label",
        "mcbe.engine-probe=true",
        "--label",
        f"mcbe.engine-probe.owner={owner or name}",
        *network,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--pids-limit",
        "256",
        "--user",
        f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0",
        "--workdir",
        "/server",
        "--env",
        "LD_LIBRARY_PATH=/server",
        "--mount",
        f"type=bind,source={source},target=/server",
        "--entrypoint",
        "/server/bedrock_server",
        image_id,
    ]


def client_progress(run_dir: Path, phase: str, status: str, port: int, connections: int, *, profile: str = "inventory") -> None:
    """Expose only runner-owned progress; never log player identity or raw NBT."""
    connection = {"seed": 1, "reload1": 2, "reload2": 3}[phase]
    messages = {
        "starting": "Starting the test server. Please wait before joining.",
        "waiting_for_client": f"Join {connection}/{connections} ready: connect to 127.0.0.1:{port} with the same account.",
        "client_connected": "Connected. Automatic checks are running; please do not change items.",
        "saving": "Checks observed. The server will save and disconnect you intentionally.",
        "stopped": "Server stopped cleanly. Checking the saved data; please wait.",
        "editing": "Applying offline editor changes. Please wait for the next join invitation.",
    }
    if profile == "village":
        messages.update(
            client_connected="Connected. Loading the natural village; wait for the trade instruction.",
            trade_required="Buy bread once from the named farmer with emeralds, then close the trade screen.",
            pickup_required="Close the trade screen and drop one selected carrot with Q in front of the named farmer.",
            chunk_reload="Checking natural villagers after a real chunk unload and reload. Please wait.",
        )
    message = messages[status]
    write_json(
        run_dir / "client-status.json",
        {"phase": phase, "status": status, "connection": connection, "required_connections": connections, "address": "127.0.0.1", "port": port},
    )
    print(f"[Client] {message}", flush=True)


def run_phase(
    server: Path,
    run_dir: Path,
    phase: str,
    run_id: str,
    version: str,
    image_id: str,
    timeout: float,
    *,
    client_port: int | None = None,
    client_connections: int = 3,
    client_profile: str = "inventory",
) -> list[dict]:
    name = f"mcbe-engine-{uuid.uuid4().hex}"
    owner = uuid.uuid4().hex
    container_id = None
    process = None
    transcript = Transcript(run_id, phase, version)
    lines: queue.Queue[str | None] = queue.Queue()
    failure = None
    try:
        if client_port is not None:
            client_progress(run_dir, phase, "starting", client_port, client_connections, profile=client_profile)
        created_id = docker_command(container_arguments(server, name, image_id, owner, client_port=client_port))
        if not re.fullmatch(r"[0-9a-f]{64}", created_id):
            raise ProbeError("Docker did not return an owned container ID")
        container_id = created_id
        process = subprocess.Popen(
            ["docker", "start", "--attach", "--interactive", container_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def read_output():
            assert process is not None and process.stdout is not None
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        stop_sent = False
        byte_count = 0
        with (run_dir / f"{phase}.log").open("w", encoding="utf-8") as log:
            while True:
                if time.monotonic() >= deadline:
                    raise ProbeError(f"{phase}: engine timeout, no successful result")
                try:
                    line = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if line is None:
                    break
                byte_count += len(line)
                if byte_count > 32_000_000:
                    raise ProbeError("Engine log exceeded 32 MB")
                log.write(line)
                log.flush()
                previous_events = len(transcript.events)
                transcript.feed(line)
                if client_port is not None and len(transcript.events) > previous_events:
                    event = transcript.events[-1]
                    stages = {"waiting_for_client", "client_connected"}
                    if client_profile == "village":
                        stages.update({"trade_required", "pickup_required", "chunk_reload"})
                    if event["kind"] == "checkpoint" and event.get("stage") in stages:
                        client_progress(run_dir, phase, event["stage"], client_port, client_connections, profile=client_profile)
                if transcript.done and not stop_sent:
                    if client_port is not None:
                        client_progress(run_dir, phase, "saving", client_port, client_connections, profile=client_profile)
                    assert process.stdin is not None
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                    process.stdin.close()
                    stop_sent = True
                    deadline = min(deadline, time.monotonic() + 30)
            exit_code = process.wait(timeout=10)
        state = json.loads(docker_command(["inspect", "--format", "{{json .State}}", container_id]))
        if exit_code != 0 or state.get("Running") is not False or state.get("ExitCode") != 0 or state.get("OOMKilled"):
            raise ProbeError(f"{phase}: server did not stop cleanly")
        events = transcript.finish()
        if client_port is not None:
            client_progress(run_dir, phase, "stopped", client_port, client_connections, profile=client_profile)
        return events
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            if container_id is None:
                # A timed-out create can have succeeded in the daemon before
                # the CLI lost its response. Never discover/delete by a shared
                # label alone: this token is unique to this create attempt.
                recovered = docker_command(["ps", "--all", "--no-trunc", "--filter", f"label=mcbe.engine-probe.owner={owner}", "--format", "{{.ID}}"])
                if recovered and not re.fullmatch(r"[0-9a-f]{64}", recovered):
                    raise ProbeError("Could not identify one owned container for cleanup")
                container_id = recovered or None
            if container_id is not None:
                docker_command(["rm", "--force", container_id], timeout=20)
        except ProbeError as cleanup_error:
            original = f"{failure or type(failure).__name__}; " if failure is not None else ""
            raise ProbeError(f"{original}Cleanup failed for owned container {container_id or name}: {cleanup_error}") from cleanup_error
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()


def source_hashes() -> dict[str, str]:
    result = {}
    for label, directory in (("probe_sha256", Path(__file__).parent), ("editor_source_sha256", ROOT / "mcbe_editor")):
        digest = hashlib.sha256()
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if label == "editor_source_sha256" and path.suffix not in {".py", ".json"}:
                continue
            digest.update(path.relative_to(directory).as_posix().encode() + b"\0" + path.read_bytes())
        result[label] = digest.hexdigest()
    return result


def editor_provenance() -> dict:
    def git(*args):
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=10, check=False)
        return result.stdout if result.returncode == 0 else b"unavailable"

    return {
        "commit": git("rev-parse", "HEAD").decode().strip(),
        "dirty": bool(git("status", "--porcelain")),
        "diff_sha256": hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest(),
        **source_hashes(),
    }


def nbt_worker(run_dir: Path, action: str, *, module: str = "scripts.engine_checks.nbt_roundtrip") -> dict:
    env = {
        **{key: value for key, value in os.environ.items() if not key.startswith("MCBE_")},
        "MCBE_DATA_ROOT": str(run_dir / "app-data"),
        "MCBE_BACKUP_ROOT": str(run_dir / "backups"),
        "MCBE_ITEM_DB_PATH": str(run_dir / "catalog.json"),
        "PYTHONIOENCODING": "utf-8",
        "MCBE_ENCHANTMENT_COMPATIBILITY_PATH": str(ROOT / "mcbe_editor/enchantment_compatibility.json"),
    }
    result = subprocess.run(
        [sys.executable, "-m", module, str(run_dir), action],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    (run_dir / f"nbt-{action}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ProbeError(f"Offline NBT {action} failed; see the local nbt-{action}.log")
    try:
        report = json.loads(result.stdout)
    except ValueError as exc:
        raise ProbeError(f"Offline NBT {action} returned malformed JSON; see the local nbt-{action}.log") from exc
    if not isinstance(report, dict) or report.get("status") not in ("pass", "fail"):
        raise ProbeError(f"Offline NBT {action} returned an invalid result status")
    # Rule differences are report data and the caller explicitly rejects them.
    # Every persistence operation must prove success and complete case coverage;
    # a process exiting normally is not evidence that its checks passed.
    if action != "rules":
        if report["status"] != "pass":
            raise ProbeError(f"Offline NBT {action} reported failed checks")
        if module == "scripts.engine_checks.village_worker":
            if type(report.get("native_trades")) is not int or report["native_trades"] != 1:
                raise ProbeError(f"Offline NBT {action} did not verify a native client trade")
        else:
            cases = json.loads((run_dir / "cases.json").read_text(encoding="utf-8"))
            if not isinstance(cases, list) or not cases or type(report.get("cases")) is not int or report["cases"] != len(cases):
                raise ProbeError(f"Offline NBT {action} did not verify every planned case")
    return report


def public_summary(report: dict) -> dict:
    """Allowlisted CI artifact: raw logs, exceptions and world NBT stay local."""
    catalog = report.get("catalog", {})
    player_service = report.get("nbt_edit", {}).get("player_service", {"status": "not_selected"})
    client = report.get("client", {"status": "not_selected"})
    equipment = report.get("nbt_edit", {}).get("equipment", {"status": "not_selected"})
    return {
        "format": "mcbe-engine-summary-v1",
        "status": report["status"],
        "suite": report["suite"],
        "engine": report["engine"],
        "editor": report["editor"],
        "catalog_sha256": report["catalog_sha256"],
        "cases_sha256": report.get("cases_sha256"),
        "trade_reference": {key: value for key, value in report.get("trade_reference", {}).items() if key in {"version", "sha256"}},
        "trade_tables_sha256": report.get("trade_tables_sha256"),
        "trade_enchantments_sha256": report.get("trade_enchantments_sha256"),
        "catalog_source": report.get("catalog_source", "bundled"),
        "phases": report["phases"],
        "not_covered": report["not_covered"],
        "catalog": {
            key: catalog[key]
            for key in (
                "status",
                "expected_count",
                "observed_count",
                "missing",
                "mismatches",
                "outside_editor_count_range",
                "registry_missing",
                "registry_extra",
                "new_limit_candidates",
                "durability_mismatches",
                "new_durability_candidates",
            )
            if key in catalog
        },
        "roundtrip": report.get("roundtrip", {"status": "not_completed"}),
        "extended": report.get("extended", {"status": "not_selected"}),
        "special": {
            key: value
            for key, value in report.get("special", {"status": "not_selected"}).items()
            if key in {"status", "cases", "kinds", "revised_cases", "preserved_cases", "rejected_edits", "content_observer"}
        },
        "enchantment_registry": {
            key: value
            for key, value in report.get("enchantment_registry", {"status": "not_selected"}).items()
            if key in {"status", "expected_count", "observed_count", "added", "removed", "level_mismatches"}
        },
        "editor_rules": {
            key: value
            for key, value in report.get("editor_rules", {"status": "not_selected"}).items()
            if key
            in {
                "status",
                "applicability_checks",
                "pair_conflict_checks",
                "incompatible_creation_checks",
                "enchantment_level_checks",
                "durability_rejection_checks",
                "intentional_exceptions",
                "differences",
            }
        },
        "addon": report.get("addon", {"status": "not_selected"}),
        "player_service": {
            key: player_service[key]
            for key in (
                "status",
                "synthetic_players",
                "real_players",
                "backed_up_saves",
                "no_op_checks",
                "stale_revision_rejections",
                "cross_container_moves",
                "intermediate_state_checks",
                "client_login_verified",
                "mixed_metadata_moves",
                "mixed_metadata_recreations",
                "special_content_cases",
            )
            if key in player_service
        },
        "client": {key: client[key] for key in ("status", "required_connections", "completed_connections", "profile") if key in client},
        "equipment": {key: equipment[key] for key in ("status", "cases", "backed_up_saves", "no_op_checks") if key in equipment},
        "villagers": {
            key: value
            for key, value in report.get("villagers", {"status": "not_selected"}).items()
            if key in {"status", "cases", "warmup_cycles", "reload_cycles", "backed_up_saves", "no_op_checks", "stale_revision_rejections"}
        },
        "villager_trades": {
            key: value
            for key, value in report.get("villager_trades", {"status": "not_selected"}).items()
            if key
            in {
                "status",
                "cases",
                "professions",
                "warmup_cycles",
                "reload_cycles",
                "backed_up_saves",
                "no_op_checks",
                "stale_revision_rejections",
                "limitations",
                "recipe_structure",
                "metadata",
            }
        },
        "village": {
            key: value
            for key, value in report.get("village", {"status": "not_selected"}).items()
            if key in {"status", "required_connections", "completed_connections", "reload_cycles", "backed_up_saves", "trades", "pickups", "chunk_reloads"}
        },
    }


def run_villager_checks(run_dir: Path, report: dict, config: dict, phase: Callable[[str], list[dict]], observations: dict, limits: dict) -> None:
    from .villager_profile import edit_groups, make_villager_cases, validate_villager_events

    cases = make_villager_cases(observations, limits)
    write_json(run_dir / "cases.json", cases)
    report["cases_sha256"] = sha256(run_dir / "cases.json")
    report["villagers"] = {"status": "incomplete", "cases": len(cases), "warmup_cycles": 2, "reload_cycles": 4}
    report["not_covered"] = [
        "real client UI and player persistence",
        "villager trading, breeding, food sharing, farming and combat gameplay",
        "legacy villager schemas and version migration",
        "third-party add-ons, overrides and experimental features",
        "name, health and supply combinations outside the explicit cases",
        "item-carrier and specialized-item persistence",
    ]
    config.update(villager_profile=True, cases=cases)

    def worker(action):
        write_json(run_dir / "run.json", report)
        result = nbt_worker(run_dir, action, module="scripts.engine_checks.villager_worker")
        report.setdefault("villager_results", {})[action] = result
        return result

    validate_villager_events(phase("seed"), cases, stage="seed")
    report["phases"]["seed"] = "pass"
    worker("seed")
    for name in ("warmup1", "warmup2"):
        validate_villager_events(phase(name), cases, stage="seed")
        worker(name)
        report["phases"][name] = "pass"

    for action, stage, reloads in (("edit", "edited", ("reload1", "reload2")), ("revise", "revised", ("reload3", "reload4"))):
        edit_phase = "revision" if action == "revise" else "edit"
        report["phases"][edit_phase] = "running"
        result = worker(action)
        for field in ("backed_up_saves", "no_op_checks", "stale_revision_rejections"):
            expected_checks = 1 if action == "revise" and field != "no_op_checks" else len(edit_groups(cases, action))
            if type(result.get(field)) is not int or result[field] != expected_checks:
                raise ProbeError("Villager worker did not complete every planned service check: " + field)
            report["villagers"][field] = report["villagers"].get(field, 0) + result[field]
        if action == "revise" and result.get("central_workspace") is not True:
            raise ProbeError("Villager worker omitted the central workspace save")
        report["phases"][edit_phase] = "pass"
        for name in reloads:
            validate_villager_events(phase(name), cases, stage=stage)
            report[name + "_disk"] = worker("verify")
            report["phases"][name] = "pass"
    report["villagers"]["status"] = "pass"
    report["roundtrip"] = {
        "status": "pass",
        "cases": len(cases),
        "reload_cycles": 4,
        "write_path": "production villager service, codec, backup and pure-Python WAL batch",
    }


def run_villager_trade_checks(run_dir: Path, report: dict, config: dict, phase: Callable[[str], list[dict]]) -> None:
    from .extended import ENCHANTMENT_NAMES
    from .villager_trade_profile import PROFESSIONS, make_trade_cases, validate_trade_events
    from .villager_trade_tables import load_run_trade_tables, trade_enchantment_items

    cases = make_trade_cases()
    tables = load_run_trade_tables(run_dir, report)
    enchantment_items = trade_enchantment_items(tables)
    write_json(run_dir / "cases.json", cases)
    report["cases_sha256"] = sha256(run_dir / "cases.json")
    report["trade_tables_sha256"] = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    report["villager_trades"] = {"status": "incomplete", "cases": len(cases), "professions": len(PROFESSIONS), "warmup_cycles": 0, "reload_cycles": 0}
    report["not_covered"] = [
        "real-client trade UI, tier unlock visibility and successful purchases",
        "restocking, workstations, job binding through real trades and natural job changes",
        "random-offer distribution or all possible generated enchantment combinations",
        "legacy villager schemas, version migration, add-ons and experimental trade rebalance",
    ]
    config.update(villager_profile=True, villager_trade_profile=True, cases=cases, trade_enchantment_items=enchantment_items)

    def worker(action):
        write_json(run_dir / "run.json", report)
        result = nbt_worker(run_dir, action, module="scripts.engine_checks.villager_trade_worker")
        report.setdefault("villager_trade_results", {})[action] = result
        report["villager_trades"]["limitations"] = sorted(set(report["villager_trades"].get("limitations", [])) | set(result.get("limitations", [])))
        return result

    events = phase("seed")
    validate_trade_events(events, cases, stage="seed")
    registries = [event for event in events if event.get("kind") == "matrix_registry"]
    registry = registries[0].get("enchantments") if len(registries) == 1 else None
    if (
        not isinstance(registry, dict)
        or set(registry) != set(ENCHANTMENT_NAMES)
        or any(type(value) is not int or not 1 <= value <= 255 for value in registry.values())
    ):
        raise ProbeError("Native trade seed omitted or changed its complete enchantment registry")
    compatibility = registries[0].get("enchantability")
    if (
        not isinstance(compatibility, dict)
        or set(compatibility) != set(enchantment_items)
        or any(
            not isinstance(allowed, list)
            or not allowed
            or any(not isinstance(name, str) or name not in registry for name in allowed)
            or len(set(allowed)) != len(allowed)
            for allowed in compatibility.values()
        )
    ):
        raise ProbeError("Native trade seed omitted or changed item enchantability")
    write_json(run_dir / "trade-enchantments.json", {"limits": registry, "compatibility": compatibility})
    report["trade_enchantments_sha256"] = sha256(run_dir / "trade-enchantments.json")
    report["phases"]["seed"] = "pass"
    worker("seed")
    for name in ("warmup1", "warmup2"):
        validate_trade_events(phase(name), cases, stage="seed")
        worker(name)
        report["phases"][name] = "pass"
        report["villager_trades"]["warmup_cycles"] += 1
    for action, stage, reloads in (("edit", "edited", ("reload1", "reload2")), ("revise", "revised", ("reload3", "reload4"))):
        report["phases"][action] = "running"
        result = worker(action)
        expected = sum(case[action] is not None for case in cases)
        for field in ("backed_up_saves", "no_op_checks", "stale_revision_rejections"):
            if type(result.get(field)) is not int or result[field] != expected:
                raise ProbeError("Native trade worker omitted production save checks: " + field)
            report["villager_trades"][field] = report["villager_trades"].get(field, 0) + result[field]
        report["phases"][action] = "pass"
        for name in reloads:
            validate_trade_events(phase(name), cases, stage=stage)
            worker(name)
            report["phases"][name] = "pass"
            report["villager_trades"]["reload_cycles"] += 1
    report["villager_trades"].update(status="partial", recipe_structure="pass", metadata="partial")
    report["roundtrip"] = {
        "status": "pass",
        "cases": len(cases),
        "reload_cycles": 4,
        "write_path": "production career service; independently checked native Vanilla tables and persisted offers",
    }


def run_village_checks(run_dir: Path, report: dict, config: dict, phase: Callable[[str], list[dict]]) -> None:
    from .village_profile import PHASES, make_village_plan, validate_actor_snapshots, validate_village_events

    plan = make_village_plan()
    write_json(run_dir / "village-plan.json", plan)
    report["village_plan_sha256"] = sha256(run_dir / "village-plan.json")
    config["village_profile"] = plan
    report["village"] = {
        "status": "incomplete",
        "required_connections": 3,
        "completed_connections": 0,
        "reload_cycles": 2,
        "backed_up_saves": 0,
        "trades": 0,
        "pickups": 0,
        "chunk_reloads": 0,
    }
    report["not_covered"] = [
        "villager farming, breeding, food sharing, restocking and combat gameplay",
        "trades and supplies outside the selected natural farmer scenario",
        "other seeds, village biomes, legacy worlds and version migration",
        "third-party add-ons, overrides and experimental features",
        "online authentication and player inventory editing",
    ]
    for index, name in enumerate(PHASES):
        evidence = validate_village_events(phase(name), plan, phase=name)
        write_json(run_dir / f"{name}.village.json", evidence)
        report["phases"][name] = "pass"
        write_json(run_dir / "run.json", report)
        action = "edit" if name == "seed" else "verify"
        try:
            result = nbt_worker(run_dir, action, module="scripts.engine_checks.village_worker")
            if result.get("status") != "pass" or type(result.get("native_trades")) is not int or result["native_trades"] != 1:
                raise ProbeError("Natural village worker did not verify the native trade")
            validate_actor_snapshots(result.get("expected"), edited=True)
            if name == "seed":
                if type(result.get("backed_up_saves")) is not int or result["backed_up_saves"] != 2:
                    raise ProbeError("Natural village worker did not complete both backed-up saves")
                report["village"]["backed_up_saves"] = result["backed_up_saves"]
                report["phases"]["edit"] = "pass"
            elif type(result.get("verified_reloads")) is not int or result["verified_reloads"] != index:
                raise ProbeError("Natural village worker omitted a saved reload")
        except (ProbeError, OSError, ValueError, subprocess.SubprocessError):
            report["phases"][name] = "fail"
            raise
        report.setdefault("village_results", {})[name] = result
        config["village_expected"] = deepcopy(result["expected"])
        for counter in ("completed_connections", "trades", "pickups", "chunk_reloads"):
            report["village"][counter] += 1
    report["village"]["status"] = "pass"
    report["roundtrip"] = {
        "status": "pass",
        "reload_cycles": 2,
        "write_path": "production villager service; natural villagers; real client trades and food pickup",
    }


def run_probe(
    archive: Path,
    expected_hash: str,
    version: str,
    image: str,
    work_root: Path,
    suite: str,
    timeout: float,
    catalog_path: Path | None = None,
    *,
    client_port: int = 19134,
    client_reloads: int = 2,
    samples_archive: Path | None = None,
    samples_sha256: str | None = None,
    samples_version: str | None = None,
) -> tuple[Path, dict]:
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ProbeError("An exact four-part Bedrock server version is required")
    if not 10 <= timeout <= 1800:
        raise ProbeError("Timeout must be between 10 and 1800 seconds per engine phase")
    if suite not in {"catalog", "items", "extended", "special", "addons", "service", "villagers", "villager_trades", "village", "client"}:
        raise ProbeError("Unknown engine check suite")
    samples_options = (samples_archive, samples_sha256, samples_version)
    if any(value is not None for value in samples_options) and (suite != "villager_trades" or not all(samples_options)):
        raise ProbeError("Samples archive, SHA-256 and release version must be supplied together for villager_trades")
    if suite in {"client", "village"} and (type(client_port) is not int or not 1024 <= client_port <= 65535):
        raise ProbeError("Client port must be an integer between 1024 and 65535")
    if type(client_reloads) is not int or client_reloads not in (1, 2) or (suite != "client" and client_reloads != 2):
        raise ProbeError("Client reloads must be 1 or 2 and may only be changed for the client suite")
    reload_cycles = client_reloads if suite == "client" else 2
    resolved_work = work_root.resolve()
    run_id = uuid.uuid4().hex
    run_dir = resolved_work / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + run_id[:12])
    if run_dir.is_relative_to(ROOT):
        # The directory itself must be excluded. An ignored *.json marker says
        # nothing about whether the generated LevelDB/world files are ignored.
        relative = run_dir.relative_to(ROOT).as_posix() + "/"
        ignored = subprocess.run(["git", "check-ignore", "--quiet", "--no-index", str(relative)], cwd=ROOT, timeout=10, check=False)
        if ignored.returncode != 0:
            raise ProbeError("Generated engine worlds must be placed in a Git-ignored work directory")
    image_info = json.loads(docker_command(["image", "inspect", "--format", "{{json .}}", image]))
    if image_info.get("Os") != "linux" or image_info.get("Architecture") != "amd64":
        raise ProbeError("The probe requires a Linux amd64 Docker image")
    image_id = image_info["Id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ProbeError("Docker image has no immutable local ID")
    run_dir.mkdir(parents=True, exist_ok=False)
    bundled_path = ROOT / "mcbe_editor/resources/item_db.json"
    catalog_path = bundled_path if catalog_path is None else catalog_path.resolve(strict=True)
    catalog_bytes = catalog_path.read_bytes()
    db = json.loads(catalog_bytes)
    if not isinstance(db, dict) or not isinstance(db.get("addable_items"), list) or not isinstance(db.get("stack_limits"), dict):
        raise ProbeError("The catalog must contain explicit addable_items and stack_limits")
    (run_dir / "catalog.json").write_bytes(catalog_bytes)
    expected_ids = sorted(set(db["addable_items"]))
    report = {
        "format": "mcbe-engine-check-v1",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "incomplete",
        "suite": suite,
        "engine": {
            "version": version,
            "archive_sha256": expected_hash.lower(),
            "image_id": image_id,
            "api_version": API_VERSION,
            "network": "none",
            "vanilla_definitions": True,
            "experiments": False,
        },
        "editor": editor_provenance(),
        "catalog_sha256": sha256(run_dir / "catalog.json"),
        "phases": {},
        "catalog_source": "bundled" if catalog_path == bundled_path else "candidate",
        "not_covered": [
            "real-player login and save",
            "singleplayer local-player engine saves",
            "real-player Ender Chest persistence",
            "UI interactions",
            "complete player service",
            "mount creation and mount gameplay",
            "arbitrary third-party add-ons and overrides",
            "Education-only behavior",
            "version migration",
            "all metadata combinations",
            "combat, equipping, consumption, crafting and brewing",
            "stack merging and gameplay item transport",
            "special-editor contents persistence",
            "special-item gameplay: opening, placing, extracting, reading and launching",
        ],
    }
    write_json(run_dir / "run.json", report)
    if suite in {"client", "village"}:
        print(f"[Client] Preparing a fresh world and catalog. {reload_cycles + 1} joins will be needed; wait for each invitation.", flush=True)
    try:
        server = run_dir / "server"
        extract_server(archive, server, expected_hash)
        if suite == "villager_trades":
            from .villager_trade_tables import load_run_trade_tables, stage_samples

            if samples_archive is not None:
                report["trade_reference"] = stage_samples(run_dir, samples_archive, samples_sha256, samples_version)
            # Fail before starting BDS if the independent reference cannot load.
            load_run_trade_tables(run_dir, report)
        report["engine"]["executable_sha256"] = sha256(server / "bedrock_server")
        configure_server(server)
        config = {"run_id": run_id, "phase": "catalog", "expected_ids": expected_ids, "cases": []}

        def phase(name):
            config["phase"] = name
            report["phases"][name] = "running"
            prepare_pack(server, config)
            write_json(run_dir / "run.json", report)
            options = (
                {"client_port": client_port, "client_connections": reload_cycles + 1} if config.get("client_profile") or config.get("village_profile") else {}
            )
            if config.get("village_profile"):
                options["client_profile"] = "village"
            events = run_phase(server, run_dir, name, run_id, version, image_id, timeout, **options)
            write_json(run_dir / f"{name}-events.json", events)
            report["phases"][name] = "observed"
            return events

        catalog = catalog_result(phase("catalog"), expected_ids, db["stack_limits"], db.get("durability", {}))
        report["catalog"] = catalog
        report["phases"]["catalog"] = catalog["status"]
        if catalog["status"] == "fail":
            raise ProbeError("Engine disagrees with catalog limits; no NBT mutations were attempted")
        if suite == "village":
            configure_server(server, client_port=client_port)
            report["engine"].update(
                {"api_version": CLIENT_API_VERSION, "experiments": False, "network": "bridge; IPv4 loopback TCP+UDP only; NetherNet loopback candidate"}
            )
            run_village_checks(run_dir, report, config, phase)
        elif suite == "villagers":
            run_villager_checks(run_dir, report, config, phase, catalog["observations"], db["stack_limits"])
        elif suite == "villager_trades":
            run_villager_trade_checks(run_dir, report, config, phase)
        elif suite in {"items", "extended", "special", "addons", "service", "client"}:
            cases = make_cases(expected_ids, catalog["observations"], db["stack_limits"])
            if suite == "special":
                cases = make_special_cases(catalog["observations"], db["stack_limits"])
                revised = sum(case["revision"] is not None for case in cases)
                report["special"] = {
                    "status": "incomplete",
                    "cases": len(cases),
                    "kinds": sorted({case["special_edit"]["kind"] for case in cases}),
                    "revised_cases": revised,
                    "preserved_cases": len(cases) - revised,
                    "content_observer": "independent typed disk NBT after each engine stop; no gameplay assertion",
                }
            if suite in {"service", "client"}:
                cases = make_service_cases(catalog["observations"], db["stack_limits"], db["enchantments"])
            if suite == "client":
                cases.extend(make_equipment_cases(catalog["observations"], db["stack_limits"]))
                configure_server(server, client_port=client_port)
                config.update(
                    {"client_profile": True, "client_locations": assignments(cases), "client_control_slots": CONTROL_SLOTS, "client_control_name": CONTROL_NAME}
                )
                report["engine"].update(
                    {"api_version": CLIENT_API_VERSION, "experiments": False, "network": "bridge; IPv4 loopback TCP+UDP only; NetherNet loopback candidate"}
                )
                report["client"] = {
                    "status": "incomplete",
                    "required_connections": reload_cycles + 1,
                    "completed_connections": 0,
                    "profile": "real client; offline local dedicated server; stable API Ender Chest observer",
                }
                if reload_cycles == 1:
                    report["not_covered"].append("second real-client reload after the first engine save (limited client run)")
            if suite == "addons":
                config["controlled_addon"] = True
                config["addon_ids"] = sorted(ADDON_LIMITS)
                measured_addon = catalog_result(phase("addon_catalog"), sorted(ADDON_LIMITS), ADDON_LIMITS)
                if measured_addon["status"] != "pass":
                    raise ProbeError("The controlled add-on did not expose its expected item definitions")
                cases = make_addon_cases({**catalog["observations"], **measured_addon["observations"]})
                report["phases"]["addon_catalog"] = "pass"
                report["addon"] = {
                    "status": "incomplete",
                    "profile": "owned conformance pack; no Vanilla overrides",
                    "item_ids": sorted(ADDON_LIMITS),
                    "catalog_kept_vanilla": True,
                }
            if suite == "extended":
                events = phase("matrix")
                report["enchantment_registry"] = enchantment_registry_result(events, db)
                matrix = matrix_result(events, expected_ids, db)
                write_json(run_dir / "matrix.json", matrix)
                plan = extend_cases(cases, catalog["observations"], matrix)
                write_json(run_dir / "behavior-cases.json", plan)
                config.update({key: plan[key] for key in ("merges", "gameplay")})
                report["phases"]["matrix"] = "pass"
                report["extended"] = {
                    "status": "incomplete",
                    **plan["counts"],
                    "matrix_sha256": sha256(run_dir / "matrix.json"),
                    "behavior_cases_sha256": sha256(run_dir / "behavior-cases.json"),
                    "item_enchantment_checks": matrix["item_enchantment_checks"],
                    "ordered_pair_checks": matrix["ordered_pair_checks"],
                    "rejected_pair_checks": matrix["rejected_pair_checks"],
                }
                write_json(run_dir / "run.json", report)
                report["editor_rules"] = nbt_worker(run_dir, "rules")
                if report["editor_rules"]["status"] != "pass":
                    raise ProbeError("Editor rules disagree with the engine; see editor_rules in summary.json")
            if not cases:
                raise ProbeError("No eligible item roundtrip cases")
            write_json(run_dir / "cases.json", cases)
            report["cases_sha256"] = sha256(run_dir / "cases.json")
            config["cases"] = cases
            validate_case_events(phase("seed"), cases, seed=True)
            report["phases"]["seed"] = "pass"
            if suite == "client":
                report["client"]["completed_connections"] += 1
            write_json(run_dir / "run.json", report)
            if suite == "client":
                client_progress(run_dir, "seed", "editing", client_port, reload_cycles + 1)
            report["nbt_edit"] = nbt_worker(run_dir, "edit")
            for name in ("reload1", "reload2")[:reload_cycles]:
                if name == "reload2" and suite == "special":
                    report["phases"]["revision"] = "running"
                    write_json(run_dir / "run.json", report)
                    report["special_revision"] = nbt_worker(run_dir, "revise")
                    report["phases"]["revision"] = "pass"
                    config["cases"] = revision_cases(cases)
                validate_case_events(phase(name), config["cases"])
                report[name + "_disk"] = nbt_worker(run_dir, "verify")
                report["phases"][name] = "pass"
                if suite == "client":
                    report["client"]["completed_connections"] += 1
            report["roundtrip"] = {
                "status": "pass",
                "cases": len(cases),
                "item_ids": len({case["id"] for case in cases}),
                "save_reload_cycles": reload_cycles,
                "write_path": "production item builder, codec, backup and pure-Python WAL batch; test carrier adapter",
            }
            if suite == "extended":
                validate_behavior_events(phase("behavior"), plan)
                report["behavior_disk"] = nbt_worker(run_dir, "verify")
                report["phases"]["behavior"] = "pass"
                report["extended"]["status"] = "pass"
                report["not_covered"].remove("stack merging and gameplay item transport")
                report["not_covered"].append("enchantment/metadata products beyond the explicit pairs, equipment profiles and boundary cases")
            if suite == "addons":
                report["addon"]["status"] = "pass"
            if suite == "special":
                report["special"].update(status="pass", rejected_edits=report["nbt_edit"]["rejected_special_edits"])
                report["not_covered"].remove("special-editor contents persistence")
                report["not_covered"].append("special-item combinations outside the explicit special profile")
            if suite in {"service", "client"}:
                report["roundtrip"]["write_path"] = "production player service, codec, backup and pure-Python WAL batch"
                report["not_covered"].remove("complete player service")
                fields = "Inventory, EnderChestInventory, Armor and Offhand" if suite == "client" else "Inventory and EnderChestInventory"
                report["not_covered"].append(f"player service fields outside {fields} editing")
                report["not_covered"].remove("special-editor contents persistence")
                report["not_covered"].append("special-editor contents outside the selected player-service special cases")
            if suite == "client":
                report["client"]["status"] = "pass"
                report["nbt_edit"]["player_service"]["client_login_verified"] = True
                report["not_covered"].remove("real-player login and save")
                report["not_covered"].remove("real-player Ender Chest persistence")
                report["not_covered"].append("online authentication")
        else:
            report["not_covered"].append("item NBT persistence (catalog-only run)")
        # Phases and fresh workers load source files at different times. Do not
        # attribute a mixed-source run to the snapshot recorded at startup.
        if any(report["editor"][key] != digest for key, digest in source_hashes().items()):
            raise ProbeError("Probe or editor sources changed during the run; rerun with stable sources")
        report["status"] = report["villager_trades"]["status"] if suite == "villager_trades" else catalog["status"]
    except (ProbeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        report["status"] = "fail"
        report["failure"] = str(exc)
        for name, status in report["phases"].items():
            if status in {"running", "observed"}:
                report["phases"][name] = "fail"
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        write_json(run_dir / "run.json", report)
        write_json(run_dir / "summary.json", public_summary(report))
        if suite in {"client", "village"}:
            write_json(
                run_dir / "client-status.json",
                {
                    "status": report["status"],
                    "required_connections": reload_cycles + 1,
                    "completed_connections": report.get("village" if suite == "village" else "client", {}).get("completed_connections", 0),
                },
            )
    return run_dir, report
