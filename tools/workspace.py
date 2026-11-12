"""Prune generated work while protecting local run evidence."""

from contextlib import contextmanager, suppress
import argparse
import csv
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import time


@contextmanager
def work_lock(directory, blocking=True, create=True):
    lock_path = directory / ".work.lock"
    if lock_path.is_symlink():
        yield False
        return
    if not create and not lock_path.exists():
        yield True
        return
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def compress_log(path):
    """Publish a gzip copy atomically. The caller decides when to remove the original."""
    with tempfile.NamedTemporaryFile(prefix="." + path.name + ".", dir=path.parent, delete=False) as temporary:
        pending = Path(temporary.name)
        try:
            with path.open("rb") as source, gzip.GzipFile(filename="", mode="wb", fileobj=temporary,
                                                        mtime=0) as output:
                shutil.copyfileobj(source, output)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary.close()
            compressed = path.with_name(path.name + ".gz")
            pending.replace(compressed)
            return compressed
        finally:
            pending.unlink(missing_ok=True)


def prune_work(work):
    """Preserve evidence and symlinks, removing Verilator builds, objects and wave dumps."""
    removed = compressed = 0
    if work.is_symlink() or not work.is_dir():
        return {"files_removed": 0, "logs_compressed": 0}
    evidence = {".xml", ".yaml", ".yml", ".json", ".txt", ".csv", ".gz", ".mem", ".data"}
    for current, directories, files in os.walk(work, topdown=False, followlinks=False):
        directory = Path(current)
        parts = directory.relative_to(work).parts
        backend = "obj_dir" in parts or any(
            parent in ("verilator_backend", "verilator") and child == "work"
            for parent, child in zip(parts, parts[1:]))
        for name in files:
            path = directory / name
            if path.is_symlink():
                continue
            if path.suffix == ".log":
                compress_log(path)
                path.unlink()
                compressed += 1
                continue
            generated = backend or (name.startswith("Vbambu_testbench") and path.suffix in ("", ".cpp", ".h", ".mk", ".d"))
            if path.suffix in (".o", ".vcd", ".fst", ".vpd", ".ghw") or (generated and path.suffix not in evidence):
                path.unlink()
                removed += 1
        for name in directories:
            child = directory / name
            if not child.is_symlink():
                with suppress(OSError):
                    child.rmdir()
    return {"files_removed": removed, "logs_compressed": compressed}


def process_alive(work):
    marker = work / ".process.json"
    if not marker.exists():
        return False
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
        if record["host"] != socket.gethostname() or not isinstance(record["pgid"], int) or record["pgid"] <= 0:
            return True
        os.killpg(record["pgid"], 0)
    except ProcessLookupError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return True


def newest_mtime(directory):
    newest = directory.stat().st_mtime
    for current, directories, files in os.walk(directory, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for name in (*directories, *files):
            path = base / name
            if name != ".work.lock" and not path.is_symlink():
                newest = max(newest, path.stat().st_mtime)
    return newest


def save_work_evidence(work, destination):
    for current, directories, files in os.walk(work, followlinks=False):
        source_directory = Path(current)
        directories[:] = [name for name in directories if not (source_directory / name).is_symlink()]
        for name in files:
            source = source_directory / name
            is_evidence = source.suffix in (".log", ".xml", ".yaml", ".yml", ".json") or name.endswith(".log.gz")
            if source.is_symlink() or not is_evidence:
                continue
            target = destination / source.relative_to(work)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if source.suffix == ".log":
                compress_log(target)
                target.unlink()


def clean_stale_work(results, older_than_days=7, dry_run=False, completed_only=False):
    """Remove old PASS work with saved evidence, and prune abandoned work conservatively."""
    cutoff = time.time() - older_than_days * 86400
    actions = []
    runs = sorted(path for pattern in ("run_*", "batch_*/run_*")
                  for path in results.glob(pattern) if path.is_dir() and not path.is_symlink())
    for run in runs:
        if completed_only and not (run / ".complete").is_file():
            continue
        with work_lock(run, blocking=False, create=not dry_run) as available:
            if not available:
                continue
            try:
                metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
            except FileNotFoundError:
                metadata = {}
            except (OSError, ValueError):
                continue
            if not isinstance(metadata, dict):
                continue
            if metadata.get("keep_work") or metadata.get("status") in ("ERROR", "FAIL"):
                continue
            work_root = run / "work"
            if work_root.is_symlink() or not work_root.is_dir():
                continue
            summary = {}
            if (run / "summary.csv").is_file():
                with (run / "summary.csv").open(encoding="utf-8", newline="") as stream:
                    summary = {row["test_name"]: row for row in csv.DictReader(stream)}
            for work in sorted(work_root.iterdir()):
                if not work.is_dir() or work.is_symlink() or process_alive(work):
                    continue
                status = metadata.get("cases", {}).get(work.name, {}).get("status")
                if status not in (None, "PASS") or newest_mtime(work) > cutoff:
                    continue
                row = summary.get(work.name, {})
                saved = (status == "PASS" and (run / "logs" / f"{work.name}.bambu_results.xml").is_file()
                         and row.get("log_file") and (run / row["log_file"]).is_file()
                         and row.get("yaml_config") and (run / row["yaml_config"]).is_file())
                action = "remove" if saved else "prune"
                actions.append({"path": str(work.relative_to(results)), "action": action})
                if not dry_run:
                    if saved:
                        save_work_evidence(work, run / "logs" / f"{work.name}.artifacts")
                        shutil.rmtree(work)
                    else:
                        prune_work(work)

    # This location is reserved for temporary work. Unknown directories retain evidence.
    temporary_root = results / "work"
    if not completed_only and temporary_root.is_dir() and not temporary_root.is_symlink():
        for work in sorted(temporary_root.iterdir()):
            if not work.is_dir() or work.is_symlink() or process_alive(work) or newest_mtime(work) > cutoff:
                continue
            with work_lock(work, blocking=False, create=not dry_run) as available:
                if not available:
                    continue
                try:
                    metadata = json.loads((work / "metadata.json").read_text(encoding="utf-8"))
                except FileNotFoundError:
                    metadata = {}
                except (OSError, ValueError):
                    continue
                if not isinstance(metadata, dict):
                    continue
                if metadata.get("keep_work") or metadata.get("status") in ("ERROR", "FAIL") or any(
                    case.get("status") in ("ERROR", "FAIL") for case in metadata.get("cases", {}).values()
                ):
                    continue
                actions.append({"path": str(work.relative_to(results)), "action": "prune"})
                if not dry_run:
                    prune_work(work)
    return actions


def maintenance_cli(results, arguments):
    parser = argparse.ArgumentParser(prog="run_tests.sh --clean-work")
    parser.add_argument("--older-than-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(arguments)
    if options.older_than_days < 0:
        parser.error("--older-than-days must be nonnegative")
    actions = clean_stale_work(results, options.older_than_days, options.dry_run)
    for action in actions:
        prefix = "Would " if options.dry_run else ""
        print(f"{prefix}{action['action']}: {action['path']}")
    print(f"{len(actions)} eligible work directories (minimum age {options.older_than_days} days).")
