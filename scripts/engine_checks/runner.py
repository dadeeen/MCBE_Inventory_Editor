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
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .addon import ADDON_LIMITS, DATA_MODULE_ID, make_addon_cases, prepare_addon
from .cases import make_cases, validate_case_events
from .client_profile import CLIENT_API_VERSION, CONTROL_NAME, CONTROL_SLOTS, enable_client_experiment
from .extended import extend_cases, matrix_result, validate_behavior_events
from .protocol import ProbeError, Transcript, catalog_result
from .service_profile import assignments, make_service_cases

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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
            if (not parts or path.is_absolute() or "\\" in info.filename
                    or any(part in {".", ".."} or ":" in part or part.endswith((".", " ")) for part in parts)
                    or stat.S_ISLNK(info.external_attr >> 16)):
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
        "header": {"name": "MCBE editor engine checks", "description": "Disposable test instrumentation; no Vanilla overrides",
                   "uuid": PACK_ID, "version": [1, 0, 0], "min_engine_version": [1, 26, 50]},
        "modules": [{"type": "script", "language": "javascript", "uuid": SCRIPT_ID, "version": [1, 0, 0], "entry": "scripts/main.js"}],
        "dependencies": [{"module_name": "@minecraft/server", "version": API_VERSION}],
    }
    if config.get("controlled_addon"):
        manifest["modules"].append({"type": "data", "uuid": DATA_MODULE_ID, "version": [1, 0, 0]})
        prepare_addon(pack)
    if config.get("client_profile"):
        manifest["dependencies"][0]["version"] = CLIENT_API_VERSION
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
        "server-name": "MCBE disposable engine check", "level-name": WORLD_NAME,
        "level-seed": "9172026", "gamemode": "creative", "difficulty": "peaceful",
        "allow-cheats": "true", "max-players": "1", "online-mode": "false", "allow-list": "false", "transport": "raknet",
        "enable-lan-visibility": "false", "view-distance": "5", "tick-distance": "4",
        "max-threads": "2", "content-log-file-enabled": "true", "content-log-console-output-enabled": "true",
        "emit-server-telemetry": "false", "script-watchdog-enable": "true",
    }
    if client_port is not None:
        if type(client_port) is not int or not 1024 <= client_port <= 65535:
            raise ProbeError("Client port must be an integer between 1024 and 65535")
        # Current clients require NetherNet's local HTTP/TCP signaling and
        # negotiated UDP transport. Advertise only the host's loopback mapping,
        # never an ephemeral container/private/public address as the target.
        properties.update({"transport": "nethernet", "server-port": "19132", "server-ip": "0.0.0.0",
                           "server-udp-ports": f"127.0.0.1:{client_port}:19132"})
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
        network = ["--network", "bridge", "--publish", f"127.0.0.1:{client_port}:19132/tcp",
                   "--publish", f"127.0.0.1:{client_port}:19132/udp"]
    return [
        "create", "--interactive", "--name", name, "--label", "mcbe.engine-probe=true",
        "--label", f"mcbe.engine-probe.owner={owner or name}",
        *network, "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m", "--memory", "2g", "--cpus", "2", "--pids-limit", "256",
        "--user", f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0",
        "--workdir", "/server", "--env", "LD_LIBRARY_PATH=/server",
        "--mount", f"type=bind,source={source},target=/server", "--entrypoint", "/server/bedrock_server", image_id,
    ]


def run_phase(server: Path, run_dir: Path, phase: str, run_id: str, version: str, image_id: str, timeout: float,
              *, client_port: int | None = None) -> list[dict]:
    name = f"mcbe-engine-{uuid.uuid4().hex}"
    owner = uuid.uuid4().hex
    container_id = None
    process = None
    transcript = Transcript(run_id, phase, version)
    lines: queue.Queue[str | None] = queue.Queue()
    failure = None
    try:
        created_id = docker_command(container_arguments(server, name, image_id, owner, client_port=client_port))
        if not re.fullmatch(r"[0-9a-f]{64}", created_id):
            raise ProbeError("Docker did not return an owned container ID")
        container_id = created_id
        process = subprocess.Popen(["docker", "start", "--attach", "--interactive", container_id], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)

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
                if (client_port is not None and len(transcript.events) > previous_events
                        and transcript.events[-1].get("stage") == "waiting_for_client"):
                    write_json(run_dir / "client-status.json", {"phase": phase, "status": "waiting_for_client", "address": "127.0.0.1", "port": client_port})
                if transcript.done and not stop_sent:
                    if client_port is not None:
                        write_json(run_dir / "client-status.json", {"phase": phase, "status": "saving"})
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
        return transcript.finish()
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            if container_id is None:
                # A timed-out create can have succeeded in the daemon before
                # the CLI lost its response. Never discover/delete by a shared
                # label alone: this token is unique to this create attempt.
                recovered = docker_command(["ps", "--all", "--no-trunc", "--filter", f"label=mcbe.engine-probe.owner={owner}",
                                            "--format", "{{.ID}}"])
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

    return {"commit": git("rev-parse", "HEAD").decode().strip(), "dirty": bool(git("status", "--porcelain")),
            "diff_sha256": hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest(), **source_hashes()}


def nbt_worker(run_dir: Path, action: str) -> dict:
    env = {**os.environ, "MCBE_DATA_ROOT": str(run_dir / "app-data"), "MCBE_BACKUP_ROOT": str(run_dir / "backups"),
           "MCBE_ITEM_DB_PATH": str(run_dir / "catalog.json"), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-m", "scripts.engine_checks.nbt_roundtrip", str(run_dir), action], cwd=ROOT,
                            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
    (run_dir / f"nbt-{action}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ProbeError(f"Offline NBT {action} failed; see the local nbt-{action}.log")
    return json.loads(result.stdout)


def public_summary(report: dict) -> dict:
    """Allowlisted CI artifact: raw logs, exceptions and world NBT stay local."""
    catalog = report.get("catalog", {})
    player_service = report.get("nbt_edit", {}).get("player_service", {"status": "not_selected"})
    client = report.get("client", {"status": "not_selected"})
    return {
        "format": "mcbe-engine-summary-v1", "status": report["status"], "suite": report["suite"],
        "engine": report["engine"], "editor": report["editor"], "catalog_sha256": report["catalog_sha256"],
        "cases_sha256": report.get("cases_sha256"),
        "catalog_source": report.get("catalog_source", "bundled"),
        "phases": report["phases"], "not_covered": report["not_covered"],
        "catalog": {key: catalog[key] for key in ("status", "expected_count", "observed_count", "missing", "mismatches",
                                                 "outside_editor_count_range", "registry_missing", "registry_extra", "new_limit_candidates",
                                                 "durability_mismatches", "new_durability_candidates") if key in catalog},
        "roundtrip": report.get("roundtrip", {"status": "not_completed"}),
        "extended": report.get("extended", {"status": "not_selected"}),
        "addon": report.get("addon", {"status": "not_selected"}),
        "player_service": {key: player_service[key] for key in ("status", "synthetic_players", "real_players", "backed_up_saves",
                                                               "no_op_checks", "stale_revision_rejections", "cross_container_moves",
                                                               "client_login_verified") if key in player_service},
        "client": {key: client[key] for key in ("status", "required_connections", "completed_connections", "profile") if key in client},
    }


def run_probe(archive: Path, expected_hash: str, version: str, image: str, work_root: Path, suite: str, timeout: float,
              catalog_path: Path | None = None, *, client_port: int = 19134) -> tuple[Path, dict]:
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ProbeError("An exact four-part Bedrock server version is required")
    if not 10 <= timeout <= 1800:
        raise ProbeError("Timeout must be between 10 and 1800 seconds per engine phase")
    if suite not in {"catalog", "items", "extended", "addons", "service", "client"}:
        raise ProbeError("Unknown engine check suite")
    if suite == "client" and (type(client_port) is not int or not 1024 <= client_port <= 65535):
        raise ProbeError("Client port must be an integer between 1024 and 65535")
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
        "format": "mcbe-engine-check-v1", "run_id": run_id, "started_at": datetime.now(UTC).isoformat(), "status": "incomplete", "suite": suite,
        "engine": {"version": version, "archive_sha256": expected_hash.lower(), "image_id": image_id, "api_version": API_VERSION,
                   "network": "none", "vanilla_definitions": True, "experiments": False},
        "editor": editor_provenance(), "catalog_sha256": sha256(run_dir / "catalog.json"), "phases": {},
        "catalog_source": "bundled" if catalog_path == bundled_path else "candidate",
        "not_covered": ["real-player login and save", "singleplayer local-player engine saves", "real-player Ender Chest persistence",
                        "UI interactions", "complete player service", "mount creation and mount gameplay", "arbitrary third-party add-ons and overrides",
                        "Education-only behavior", "version migration", "all metadata combinations",
                        "combat, equipping, consumption, crafting and brewing", "stack merging and gameplay item transport"],
    }
    write_json(run_dir / "run.json", report)
    try:
        server = run_dir / "server"
        extract_server(archive, server, expected_hash)
        report["engine"]["executable_sha256"] = sha256(server / "bedrock_server")
        configure_server(server)
        config = {"run_id": run_id, "phase": "catalog", "expected_ids": expected_ids, "cases": []}

        def phase(name):
            config["phase"] = name
            report["phases"][name] = "running"
            prepare_pack(server, config)
            write_json(run_dir / "run.json", report)
            options = {"client_port": client_port} if config.get("client_profile") else {}
            events = run_phase(server, run_dir, name, run_id, version, image_id, timeout, **options)
            write_json(run_dir / f"{name}-events.json", events)
            report["phases"][name] = "observed"
            return events

        catalog = catalog_result(phase("catalog"), expected_ids, db["stack_limits"], db.get("durability", {}))
        report["catalog"] = catalog
        report["phases"]["catalog"] = catalog["status"]
        if catalog["status"] == "fail":
            raise ProbeError("Engine disagrees with catalog limits; no NBT mutations were attempted")
        if suite in {"items", "extended", "addons", "service", "client"}:
            cases = make_cases(expected_ids, catalog["observations"], db["stack_limits"])
            if suite in {"service", "client"}:
                cases = make_service_cases(catalog["observations"], db["stack_limits"])
            if suite == "client":
                enable_client_experiment(server)
                configure_server(server, client_port=client_port)
                config.update({"client_profile": True, "client_locations": assignments(cases),
                               "client_control_slots": CONTROL_SLOTS, "client_control_name": CONTROL_NAME})
                report["engine"].update({"api_version": CLIENT_API_VERSION, "experiments": True,
                                         "network": "bridge; IPv4 loopback TCP+UDP only; NetherNet loopback candidate"})
                report["client"] = {"status": "incomplete", "required_connections": 3, "completed_connections": 0,
                                    "profile": "real client; offline local dedicated server; Beta API Ender Chest observer"}
            if suite == "addons":
                config["controlled_addon"] = True
                config["addon_ids"] = sorted(ADDON_LIMITS)
                measured_addon = catalog_result(phase("addon_catalog"), sorted(ADDON_LIMITS), ADDON_LIMITS)
                if measured_addon["status"] != "pass":
                    raise ProbeError("The controlled add-on did not expose its expected item definitions")
                cases = make_addon_cases({**catalog["observations"], **measured_addon["observations"]})
                report["phases"]["addon_catalog"] = "pass"
                report["addon"] = {"status": "incomplete", "profile": "owned conformance pack; no Vanilla overrides",
                                   "item_ids": sorted(ADDON_LIMITS), "catalog_kept_vanilla": True}
            if suite == "extended":
                matrix = matrix_result(phase("matrix"), expected_ids, db)
                write_json(run_dir / "matrix.json", matrix)
                plan = extend_cases(cases, catalog["observations"], matrix)
                write_json(run_dir / "behavior-cases.json", plan)
                config.update({key: plan[key] for key in ("merges", "gameplay")})
                report["phases"]["matrix"] = "pass"
                report["extended"] = {"status": "incomplete", **plan["counts"], "matrix_sha256": sha256(run_dir / "matrix.json"),
                                      "behavior_cases_sha256": sha256(run_dir / "behavior-cases.json"),
                                      "item_enchantment_checks": matrix["item_enchantment_checks"], "ordered_pair_checks": matrix["ordered_pair_checks"],
                                      "rejected_pair_checks": matrix["rejected_pair_checks"]}
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
            report["nbt_edit"] = nbt_worker(run_dir, "edit")
            for name in ("reload1", "reload2"):
                validate_case_events(phase(name), cases)
                report[name + "_disk"] = nbt_worker(run_dir, "verify")
                report["phases"][name] = "pass"
                if suite == "client":
                    report["client"]["completed_connections"] += 1
            report["roundtrip"] = {"status": "pass", "cases": len(cases), "item_ids": len({case['id'] for case in cases}), "save_reload_cycles": 2,
                                   "write_path": "production item builder, codec, backup and native batch; test carrier adapter"}
            if suite == "extended":
                validate_behavior_events(phase("behavior"), plan)
                report["behavior_disk"] = nbt_worker(run_dir, "verify")
                report["phases"]["behavior"] = "pass"
                report["extended"]["status"] = "pass"
                report["not_covered"].remove("stack merging and gameplay item transport")
                report["not_covered"].append("higher-order enchantment/metadata products beyond the explicit pair and boundary cases")
            if suite == "addons":
                report["addon"]["status"] = "pass"
            if suite in {"service", "client"}:
                report["roundtrip"]["write_path"] = "production player service, codec, backup and native batch"
                report["not_covered"].remove("complete player service")
                report["not_covered"].append("player service fields outside Inventory and EnderChestInventory editing")
            if suite == "client":
                report["client"]["status"] = "pass"
                report["nbt_edit"]["player_service"]["client_login_verified"] = True
                report["not_covered"].remove("real-player login and save")
                report["not_covered"].remove("real-player Ender Chest persistence")
                report["not_covered"].extend(["online authentication", "stable-API-only Ender Chest observer"])
        else:
            report["not_covered"].append("item NBT persistence (catalog-only run)")
        # Phases and fresh workers load source files at different times. Do not
        # attribute a mixed-source run to the snapshot recorded at startup.
        if any(report["editor"][key] != digest for key, digest in source_hashes().items()):
            raise ProbeError("Probe or editor sources changed during the run; rerun with stable sources")
        report["status"] = catalog["status"]
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
        if suite == "client":
            write_json(run_dir / "client-status.json", {"status": report["status"],
                                                      "completed_connections": report.get("client", {}).get("completed_connections", 0)})
    return run_dir, report
