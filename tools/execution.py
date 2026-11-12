"""Stage inputs and record Bambu co-simulation results. Uses the Python 3 standard library."""
from contextlib import suppress
import csv
import datetime as dt
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.golden import compare, record_result, selected, tool_identity
from tools.workspace import compress_log, maintenance_cli, prune_work, work_lock


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / ".runs"
BOARDS = ROOT / "boards.json"
COLUMNS = (
    "board", "test_name", "status", "total_sim_cycles", "wall_time_s", "dram_read_reqs",
    "dram_write_reqs", "yaml_config", "log_file",
)


def load_board_profiles():
    configured = json.loads(BOARDS.read_text(encoding="utf-8"))
    if not isinstance(configured, list) or any(not isinstance(profile, dict) for profile in configured):
        raise ValueError("boards.json must contain a list of board profile objects")
    profiles = {}
    for profile in configured:
        missing = {"name", "bambu_device", "default_clock_ns", "default_ramulator_yaml", "description"} - profile.keys()
        if missing:
            raise ValueError(f"Board profile is missing fields: {', '.join(sorted(missing))}")
        name = profile["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError("Board names must use letters, digits, underscores or hyphens")
        if name in profiles:
            raise ValueError(f"Duplicate board profile {name}")
        for field in ("bambu_device", "default_ramulator_yaml", "description"):
            if not isinstance(profile[field], str) or not profile[field].strip():
                raise ValueError(f"Board {name} requires {field}")
        clock = profile["default_clock_ns"]
        if isinstance(clock, bool) or not isinstance(clock, (int, float)) or not math.isfinite(clock) or clock <= 0:
            raise ValueError(f"Board {name} requires a positive finite default_clock_ns")
        profiles[name] = profile
    if "xcu250" not in profiles:
        raise ValueError("boards.json must define the default xcu250 profile")
    return profiles


def board_profile(name):
    profiles = load_board_profiles()
    if name not in profiles:
        raise ValueError(f"Unknown board {name}. Available boards: {', '.join(profiles)}")
    return profiles[name]


def list_boards():
    print(f"{'BOARD':<12} {'STATUS':<14} {'BAMBU DEVICE':<24} {'CLOCK NS':>9}  RAMULATOR YAML")
    for profile in load_board_profiles().values():
        print(f"{profile['name']:<12} {profile.get('status', 'unspecified'):<14} {profile['bambu_device']:<24} "
              f"{profile['default_clock_ns']:>9}  {profile['default_ramulator_yaml']}")
        print(f"  {profile['description']}")


def capture(argv, cwd=None, env=None):
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", timeout=15, check=False)
        return {"exit_code": result.returncode, "output": result.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "output": str(exc)}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def create_run(tag, now):
    RESULTS.mkdir(exist_ok=True)
    parent = Path(os.environ.get("RAMULATOR_BATCH", str(RESULTS))).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    prefix = f"run_{now:%Y%m%d_%H%M%S}_{tag}"
    for suffix in range(1000):
        run = parent / (f"{prefix}_{suffix + 1}" if suffix else prefix)
        try:
            run.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError(f"Run directory collision for {prefix}")
    for name in ("config_snapshot", "logs"):
        (run / name).mkdir()
    link = RESULTS / f".latest-{uuid.uuid4().hex}"
    link.symlink_to(run, target_is_directory=True)
    try:
        link.replace(RESULTS / "latest")
    finally:
        if link.is_symlink():
            link.unlink()
    return run


def inspect_host():
    names = (
        "bambu", "verilator", "make", "objcopy", "readelf", "ldd", "git",
        "bash", "awk", "bc", "envsubst", "timeout",
    )
    paths = {name: shutil.which(name) for name in names}
    errors = [f"{name} was not found on PATH" for name, path in paths.items() if not path]
    for name, aliases in (
        ("clang_host", ("clang-19", "clang-19.0", "clang19", "clang")),
        ("clang_hls", ("clang-13", "clang-13.0", "clang13")),
    ):
        paths[name] = next((path for path in map(shutil.which, aliases) if path), None)
        if not paths[name]:
            errors.append(f"{name} was not found on PATH (tried {', '.join(aliases)})")
    versions = {name: capture([paths[name], "--version"]) if paths[name] else None
                for name in ("bambu", "verilator", "clang_host", "clang_hls")}
    for name, version in versions.items():
        if version and version["exit_code"] != 0:
            errors.append(f"{name} --version failed")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        errors.append("I386_CLANG13 co-simulation requires a Linux x86_64 host")
    for name in ("BAMBU_HLS", "BAMBU_HLS_BACKEND_PATH", "RAMULATOR2_DIR"):
        if not os.environ.get(name):
            errors.append(f"{name} is unset (copy env.example.sh to env.sh and configure it)")
    if os.environ.get("BAMBU_HLS"):
        makefile = Path(os.environ["BAMBU_HLS"]) / "share/panda/libmdpi/Makefile.mk"
        if not makefile.is_file():
            errors.append(f"Installed MDPI Makefile missing: {makefile}")

    env = os.environ.copy()
    library_info = None
    if env.get("RAMULATOR2_DIR"):
        directory = Path(env["RAMULATOR2_DIR"]).resolve()
        library = next((path / "libramulator.so" for path in
                        (directory / "lib", directory / "lib64", *sorted((directory / "lib").glob("*-linux-gnu")))
                        if (path / "libramulator.so").is_file()), directory / "lib/libramulator.so")
        header = directory / "include/ramulator/frontend/frontend.h"
        for path in (library, header):
            if not path.is_file() or not os.access(path, os.R_OK):
                errors.append(f"Missing or unreadable installed Ramulator input: {path}")
        env["RAMULATOR2_DIR"] = str(directory)
        if library.is_file() and os.access(library, os.R_OK):
            with library.open("rb") as handle:
                header = handle.read(20)
            elf64_x86_64 = header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\x3e\x00"
            library_info = {"path": str(library), "sha256": sha256(library), "elf64_x86_64": elf64_x86_64}
            if not elf64_x86_64:
                errors.append(f"Expected an ELF64 x86-64 libramulator.so: {library}")
            elif paths["ldd"] and platform.system() == "Linux":
                result = capture([paths["ldd"], str(library)], env=dict(env, LC_ALL="C"))
                library_info["ldd"] = result
                if result["exit_code"] or "not found" in result["output"]:
                    errors.append("The loader could not resolve libramulator.so dependencies; see metadata.json")
    for variable in ("OUT_LVL", "BAMBU_IPC_SIM_CMD", "RAMULATOR_OVERRIDE_CHANNELS"):
        env.pop(variable, None)
    return paths, versions, env, library_info, errors


def read_os_release():
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        fields = {}
        for line in lines:
            key, _, value = line.partition("=")
            if key in ("ID", "VERSION_ID", "PRETTY_NAME"):
                fields[key] = value.strip().strip("\"'")
        return fields
    return {}


def stage_case(case, snapshot, config_override, bambu, profile=None):
    profile = profile or board_profile("xcu250")
    preset = case.get("diagnostic_config") or profile["default_ramulator_yaml"]
    if preset.startswith("installed:"):
        default_config = Path(os.environ["BAMBU_HLS"]) / "share/panda/libmdpi/configs" / preset.split(":", 1)[1]
    else:
        default_config = ROOT / preset
    source_config = Path(config_override).resolve() if config_override else default_config
    data = source_config.read_bytes()
    if b"!include" in data:
        raise ValueError("Use a self-contained YAML; Ramulator resolves !include relative to runtime paths")
    yaml = snapshot / (source_config.name if source_config.suffix in (".yaml", ".yml") else "ramulator2_config.yaml")
    yaml.write_bytes(data)
    members = list(case["members"])
    inputs = snapshot / "inputs"
    source_info = {"yaml_source": str(source_config), "yaml_sha256": sha256(yaml)}
    if "archive" in case:
        archives = Path(os.environ.get("BENCHMARK_ARCHIVES", str(ROOT.parent / "Archive 2")))
        archive = (archives / case["archive"]).resolve()
        source_info.update(archive=str(archive), archive_sha256=sha256(archive))
        with ZipFile(archive) as bundle:
            for name in members:
                target = inputs / name
                target.parent.mkdir(parents=True, exist_ok=True)
                # Extract only the explicit member paths in the recipe.
                target.write_bytes(bundle.read(name))
    else:
        for name in members:
            target = inputs / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
    for name in case.get("trees", []):
        shutil.copytree(ROOT / name, inputs / name, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    members = sorted(str(path.relative_to(inputs)) for path in inputs.rglob("*") if path.is_file())
    source_info["inputs_sha256"] = {name: sha256(inputs / name) for name in members}
    period = os.environ.get("CLOCK_PERIOD_NS") or str(case.get("clock_period_ns", profile["default_clock_ns"]))
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", period) or float(period) <= 0:
        raise ValueError("CLOCK_PERIOD_NS must be a positive decimal number")
    argv = [
        bambu, f"--device-name={profile['bambu_device']}", f"--clock-period={period}",
        f"--max-sim-cycles={case.get('limit', 200000000)}",
        *(flag.replace("@/", str(inputs) + "/") for flag in case["flags"]),
    ]
    write_json(snapshot / "bambu_flags.json", argv[1:])
    source_info.update(clock_period_ns=period, argv=argv, ramulator2_config=str(yaml))
    write_json(snapshot / "inputs.json", source_info)
    return argv, yaml


def launch(argv, work, log, env, timeout):
    with log.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {shlex.join(argv)}\n")
        handle.flush()
        with subprocess.Popen(argv, cwd=work, env=env, stdout=handle, stderr=subprocess.STDOUT,
                              start_new_session=True) as process:
            marker = work / ".process.json"
            try:
                write_json(marker, {"pgid": process.pid, "host": socket.gethostname()})
                return process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt, OSError) as exc:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                if isinstance(exc, (KeyboardInterrupt, OSError)):
                    raise
                handle.write(f"\nRUNNER: wall timeout after {timeout:g}s\n")
                return None
            finally:
                if process.poll() is not None:
                    with suppress(OSError):
                        marker.unlink(missing_ok=True)


def measure(log):
    reads = writes = completions = ticks = 0
    initialized = False
    used_config = None
    functional_failure = False
    memory_stats = []
    for line in log:
        reads += bool(re.search(r"Issued Ramulator2 read request tag \d+|Ramulator2 queued read tag \d+ resubmitted", line))
        writes += "Issued Ramulator2 write request for addr " in line or "Ramulator2 queued write submitted for addr " in line
        completions += "Ramulator2 read completion: tag=" in line
        step = re.search(r"Advanced Ramulator2 by (\d+) cycles", line)
        if step:
            ticks += int(step[1])
        initialized |= "Ramulator2 successfully initialized for interface " in line
        marker = "Using Ramulator2 config from RAMULATOR2_CONFIG env var: "
        if marker in line:
            used_config = line.split(marker, 1)[1].strip()
        stats = re.search(r"\[MDPI-MEMORY\].*DRAM_TICKS=(\d+),READS=(\d+),COMPLETED=(\d+),WRITES=(\d+)", line)
        if stats:
            memory_stats.append(tuple(map(int, stats.groups())))
        functional_failure |= any(token in line for token in (
            "CHECK FAIL:", "Memory parameter mismatch has been found.", "Benchmark results are incorrect",
        ))
    if memory_stats:
        ticks, reads, completions, writes = map(sum, zip(*memory_stats))
    return reads, writes, completions, ticks, initialized, used_config, functional_failure


def assess(case, row, log, work, yaml, exit_code):
    with log.open(encoding="utf-8", errors="replace") as handle:
        reads, writes, completions, ticks, initialized, config, mismatch = measure(handle)
    row.update(dram_read_reqs=reads, dram_write_reqs=writes)
    details = {"bambu_exit_code": exit_code, "read_completions": completions, "logged_dram_ticks": ticks,
               "initialized": initialized, "reported_config": config}
    try:
        simulation = ET.parse(work / "output/bambu_results.xml").find("./timing/simulation")
        if simulation is None:
            raise ValueError("missing timing/simulation")
        runs = [(node.text or "").strip() for node in simulation.findall("run")]
        return_value = simulation.get("return_value")
        if runs and all(re.fullmatch(r"[0-9]+", value) for value in runs):
            row["total_sim_cycles"] = sum(map(int, runs))
        else:
            raise ValueError(f"incomplete cycle data: {runs}")
        if not re.fullmatch(r"-?[0-9]+", return_value or ""):
            raise ValueError(f"incomplete testbench return value: {return_value}")
    except (OSError, ET.ParseError, ValueError) as exc:
        result_error = str(exc)
    else:
        result_error = None
    if exit_code is None:
        return "ERROR", "wall timeout", details
    if mismatch:
        return "FAIL", "functional mismatch", details
    if result_error:
        return "ERROR", f"no completed Bambu result (exit={exit_code}): {result_error}", details
    if int(return_value) != 0:
        return "FAIL", f"testbench returned {return_value}", details
    if exit_code != 0:
        return "ERROR", f"Bambu exited {exit_code}", details
    if not row["total_sim_cycles"]:
        return "ERROR", "no simulated accelerator cycles", details
    if not initialized or (config is not None and config != str(yaml)):
        return "ERROR", "MDPI initialization missing or reported a different YAML snapshot", details
    if not reads or not completions:
        return "FAIL", "MDPI did not report an accepted read and completion", details
    if case.get("require_read_drain") and reads != completions:
        return "FAIL", "Ramulator accepted reads remain incomplete", details
    if case.get("marker"):
        with log.open(encoding="utf-8", errors="replace") as handle:
            if not any(line.strip() == case["marker"] for line in handle):
                return "FAIL", "functional harness success marker missing", details
    if case.get("byte_check"):
        expected = yaml.parent / "inputs" / case["byte_check"]
        if not (work / "output.data").is_file() or sha256(work / "output.data") != sha256(expected):
            return "FAIL", "BFS output.data differs from check.data", details
    return "PASS", "functional checks and MDPI traffic confirmed", details


def main(suite, tag, config, dry_run, board="xcu250", keep_work=False, case_name="", cases=()):
    profile = board_profile(board)
    now = dt.datetime.now(dt.timezone.utc)
    run = create_run(tag, now)
    with work_lock(run) as locked:
        if not locked:
            raise ValueError(f"Cannot lock run directory {run}")
        print(f"Run directory: {run}", flush=True)
        paths, versions, env, library, preflight = {}, {}, os.environ.copy(), None, []
        distro = {}
        timeout_text = os.environ.get("CASE_TIMEOUT_S", "2700")
        paths, versions, env, library, preflight = inspect_host()
        distro = read_os_release()
        if not re.fullmatch(r"[1-9][0-9]*", timeout_text):
            preflight.append("CASE_TIMEOUT_S must be a positive integer")
        if any(ch.isspace() for ch in str(run)):
            preflight.append("The Bambu backend requires a workspace path without whitespace")
        config_override = config
        metadata = {
            "timestamp_utc": now.isoformat(), "suite": suite, "tag": tag, "dry_run": dry_run,
            "board_profile": profile, "keep_work": keep_work,
            "git_commit": capture(["git", "rev-parse", "HEAD"], ROOT)["output"],
            "git_status": capture(["git", "status", "--porcelain"], ROOT)["output"],
            "user": getpass.getuser(), "host": socket.gethostname(),
            "os": platform.platform(), "os_release": distro, "architecture": platform.machine(),
            "environment": {key: os.environ.get(key) for key in (
                "BAMBU_HLS", "BAMBU_HLS_BACKEND_PATH", "RAMULATOR2_DIR", "RAMULATOR2_CONFIG",
                "RAMULATOR_OVERRIDE_CHANNELS", "LD_LIBRARY_PATH", "CPLUS_INCLUDE_PATH",
                "BENCHMARK_ARCHIVES", "CLOCK_PERIOD_NS", "CASE_TIMEOUT_S", "PATH",
            )},
            "effective_environment": {key: env.get(key) for key in (
                "RAMULATOR2_DIR", "LD_LIBRARY_PATH", "CPLUS_INCLUDE_PATH", "RAMULATOR_OVERRIDE_CHANNELS",
            )},
            "config_override": str(Path(config_override).resolve()) if config_override else None,
            "tool_paths": paths, "tool_versions": versions, "ramulator_library": library,
            "bambu_identity": tool_identity(paths.get("bambu"), versions.get("bambu")),
            "requested_cases": [case["name"] for case in cases],
            "preflight_errors": preflight, "cases": {},
        }
        metadata["runner_sha256"] = {
            name: sha256(ROOT / name) for name in
            ("run_tests.sh", "tools/execution.py", "tools/source_list.py", "tools/golden.py", "tools/workspace.py")
        }
        script = ROOT / suite / "run.sh"
        if script.is_file():
            metadata["runner_sha256"][str(script.relative_to(ROOT))] = sha256(script)
        local_env = os.environ.get("BAMBU_LOCAL_ENV_FILE")
        metadata["local_environment"] = {
            "path": local_env, "sha256": sha256(Path(local_env)) if Path(local_env).is_file() else None,
        } if local_env else None
        metadata["boards_sha256"] = sha256(BOARDS)
        write_json(run / "metadata.json", metadata)
        failed = False
        with (run / "summary.csv").open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, COLUMNS)
            writer.writeheader()
            output.flush()
            if preflight:
                for error in preflight:
                    print(f"[ERROR] Pre-flight: {error}", file=sys.stderr)
                failed = True
            else:
                print(f"{'TEST':<25} {'STATUS':<7} {'CYCLES':>11} {'WALL S':>8} {'READS':>9} {'WRITES':>9}", flush=True)
                for case in cases:
                    name = case["name"]
                    log = run / "logs" / f"{name}.log"
                    snapshot = run / "config_snapshot" / name
                    snapshot.mkdir()
                    row = dict(board=board, test_name=name, log_file=str(log.relative_to(run)))
                    clock_ns = None
                    details = {}
                    started = time.monotonic()
                    try:
                        argv, yaml = stage_case(case, snapshot, config_override, paths["bambu"], profile)
                        clock_ns = next(flag.split("=", 1)[1] for flag in argv if flag.startswith("--clock-period="))
                        row["yaml_config"] = str(yaml.relative_to(run))
                        if dry_run:
                            log.write_text(f"RAMULATOR2_CONFIG={shlex.quote(str(yaml))}\n$ {shlex.join(argv)}\n",
                                           encoding="utf-8")
                            print(f"{name:<25} PLANNED", flush=True)
                            metadata["cases"][name] = {"planned": True, "yaml_config": str(yaml)}
                            continue
                        work = run / "work" / name
                        (work / "tmp").mkdir(parents=True)
                        case_env = dict(env, RAMULATOR2_CONFIG=str(yaml), TMPDIR=str(work / "tmp"),
                                        BAMBU_IPC_FILENAME=str(work / "panda_ipc_mmap"))
                        started = time.monotonic()
                        exit_code = launch(argv, work, log, case_env, int(timeout_text))
                        row["wall_time_s"] = f"{time.monotonic() - started:.3f}"
                        for artifact in ("output/bambu_results.xml", "output/bambu_time_simulation.txt", "output.data"):
                            source = work / artifact
                            if source.is_file():
                                shutil.copyfile(source, log.with_suffix(f".{source.name}"))
                        status, reason, details = assess(case, row, log, work, yaml, exit_code)
                    except (OSError, ValueError, KeyError, BadZipFile) as exc:
                        status, reason = "ERROR", str(exc)
                    row["status"] = status
                    if not dry_run:
                        row.setdefault("wall_time_s", f"{time.monotonic() - started:.3f}")
                    with log.open("a", encoding="utf-8") as handle:
                        handle.write(f"\nRUNNER: {status}: {reason}\n")
                    compressed = None
                    if not dry_run:
                        try:
                            compressed = compress_log(log)
                            row["log_file"] = str(compressed.relative_to(run))
                        except OSError as exc:
                            details["cleanup_warning"] = f"Log compression failed: {exc}"
                    writer.writerow(row)
                    output.flush()
                    os.fsync(output.fileno())
                    metadata["cases"][name] = dict(details, status=status, reason=reason,
                                                   yaml_config=row.get("yaml_config"), log_file=row["log_file"],
                                                   timestamp=dt.datetime.now(dt.timezone.utc).isoformat())
                    write_json(run / "metadata.json", metadata)
                    if not dry_run:
                        record_result(run, metadata, case, row, snapshot, clock_ns)
                    if compressed:
                        try:
                            log.unlink()
                            if status == "PASS" and not keep_work:
                                metadata["cases"][name]["work_cleanup"] = prune_work(run / "work" / name)
                        except OSError as exc:
                            metadata["cases"][name]["cleanup_warning"] = str(exc)
                        write_json(run / "metadata.json", metadata)
                    if metadata["cases"][name].get("cleanup_warning"):
                        print(f"[WARNING] {name} cleanup: {metadata['cases'][name]['cleanup_warning']}", file=sys.stderr)
                    failed |= status != "PASS"
                    print(f"{name:<25} {status:<7} {str(row.get('total_sim_cycles', '-')):>11} "
                          f"{row.get('wall_time_s', '-'):>8} {str(row.get('dram_read_reqs', '-')):>9} "
                          f"{str(row.get('dram_write_reqs', '-')):>9}", flush=True)
        write_json(run / "metadata.json", metadata)
        (run / ".complete").touch()
        if not dry_run and not os.environ.get("RAMULATOR_BATCH"):
            failed |= bool(compare(run, ROOT / "results"))
        return int(failed)



def interrupt(_signal, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGHUP, interrupt)
    try:
        if sys.argv[1:] == ["--list-boards"]:
            list_boards()
            sys.exit(0)
        if sys.argv[1] == "--clean-work":
            maintenance_cli(RESULTS, sys.argv[2:])
            sys.exit(0)
        if sys.argv[1] == "--validate-board":
            board_profile(sys.argv[2])
            sys.exit(0)
        raise ValueError("Use the benchmark's run.sh to execute tests")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted; partial run evidence was retained.", file=sys.stderr)
        sys.exit(130)


def run_suite(suite, factory, argv=None, common_flags=()):
    """Run the cases supplied by one independent suite script."""
    import argparse
    parser = argparse.ArgumentParser(description=f"Run the {suite} benchmark suite")
    parser.add_argument("--board", default="xcu250")
    parser.add_argument("--config", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--case", default="")
    parser.add_argument("--tests", action="append", default=[],
                        help="Select comma-separated test names/globs; repeat to combine selections")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args(argv)
    tag = args.tag or suite
    for value in (tag,):
        if value and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", value):
            parser.error("Labels must contain 1–64 letters, digits, dots, underscores or hyphens")
    local_env = ROOT / "env.sh"
    if local_env.is_file() and (not os.environ.get("BAMBU_HLS") or not os.environ.get("RAMULATOR2_DIR")):
        # Source once in Bash and re-exec this same independent script.
        command = 'set -a; source "$1"; set +a; export BAMBU_LOCAL_ENV_FILE="$1"; exec "$2" "${@:3}"'
        os.execvp("bash", ["bash", "-c", command, "suite-env", str(local_env),
                           str(ROOT / suite / "run.sh"), *(sys.argv[1:] if argv is None else argv)])
    cases = list(factory())
    if args.case:
        cases = [case for case in cases if case["name"] == args.case]
        if not cases:
            parser.error(f"Unknown case {args.case!r} for {suite}")
    if args.tests:
        cases = [case for case in cases if selected(case['name'], args.tests)]
        if not cases:
            print(f"{suite}: skipped (no selected tests)")
            return 0
    for case in cases:
        case["flags"] = [*common_flags, *case["flags"]]
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGHUP, interrupt)
    try:
        return main(suite, tag, args.config, args.dry_run,
                    args.board, args.keep_work, args.case, cases)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; partial run evidence was retained.", file=sys.stderr)
        return 130
