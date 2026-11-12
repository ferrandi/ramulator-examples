# SPDX-License-Identifier: Apache-2.0
"""Compare completed runs and explicitly approve immutable versioned golden results."""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def tool_identity(binary, version):
    """Use installed artifacts as well as the banner: rebuilt binaries can share a commit."""
    if not binary or not version or version["exit_code"] != 0:
        return None
    banner = version["output"]
    release = re.search(r"\b(?:PandA|Bambu)\s+(\d+(?:\.\d+)+)\b", banner, re.I)
    commit = re.search(r"\brevision\s+([0-9a-f]{7,40})\b", banner, re.I)
    binary = Path(binary).resolve()
    runtime = Path(os.environ.get("BAMBU_HLS", str(binary.parent.parent))) / "share/panda/libmdpi"
    files = {str(p.relative_to(runtime)): file_digest(p) for p in sorted(runtime.rglob('*')) if p.is_file()}
    identity = {"release": release[1] if release else "unknown", "commit": commit[1] if commit else "unknown",
                "binary_sha256": file_digest(binary), "mdpi_sha256": digest(files)}
    identity["id"] = f"bambu-{identity['release']}-{identity['commit'][:12]}-{digest(identity)[:12]}"
    return identity


def record_result(run, metadata, case, row, snapshot, clock):
    if not (snapshot / 'inputs.json').is_file():
        return  # The comparison reports this requested case as missing/failed.
    inputs = read(snapshot / 'inputs.json')
    prefix = str(snapshot / 'inputs') + '/'
    flags = [flag.replace(prefix, '@/') for flag in inputs['argv'][1:]]
    config = {"board": metadata['board_profile']['name'], "device": metadata['board_profile']['bambu_device'],
              "clock_period_ns": format(float(clock), '.12g'), "flags": flags,
              "inputs_sha256": inputs['inputs_sha256'], "yaml_sha256": inputs['yaml_sha256'],
              "yaml": Path(inputs['ramulator2_config']).read_text(encoding="utf-8"),
              "ramulator_sha256": (metadata.get('ramulator_library') or {}).get('sha256'),
              "tool_versions": {k: v['output'] if v else None for k, v in metadata['tool_versions'].items() if k != 'bambu'}}
    metrics = {key: int(row[field]) if row.get(field) not in (None, '') else None for key, field in
               [('cycles', 'total_sim_cycles'), ('dram_reads', 'dram_read_reqs'), ('dram_writes', 'dram_write_reqs')]}
    result = {"schema": 1, "bambu": metadata['bambu_identity'], "test": case['name'],
              "config_id": digest(config), "configuration": config, "status": row['status'], "metrics": metrics,
              "timestamp": metadata['cases'][case['name']]['timestamp'], "examples_commit": metadata['git_commit']}
    write(run / 'cases' / f"{case['name']}.json", result)


@contextmanager
def collection_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def selected(name, patterns):
    return not patterns or any(fnmatchcase(name, pattern) for group in patterns
                               for pattern in group.split(',') if pattern)


def load_run(path, patterns=()):
    path = path.resolve()
    if (path / 'batch.json').is_file():
        batch = read(path / 'batch.json')
        if not batch.get('complete'):
            raise ValueError(f"Batch is incomplete: {path}")
        runs = [path / name for name in batch['runs']]
    elif (path / 'metadata.json').is_file():
        runs = [path]
    else:
        raise ValueError(f"Not a run or batch directory: {path}")
    records, failures, identities = {}, list(batch.get("failures", [])) if (path / "batch.json").is_file() else [], {}
    for run in runs:
        if not (run / '.complete').is_file():
            raise ValueError(f"Run is incomplete: {run}")
        meta = read(run / 'metadata.json')
        if meta.get('dry_run'):
            raise ValueError('Dry runs cannot be compared or collected')
        identity = meta.get('bambu_identity')
        if identity:
            identities[identity['id']] = identity
        if meta.get('preflight_errors'):
            failures.append({'test': meta['suite'], 'status': 'FAIL', 'reason': 'Preflight failed'})
        for name in meta.get('requested_cases', []):
            source = run / 'cases' / f'{name}.json'
            if not source.is_file():
                failures.append({'test': name, 'status': 'FAIL', 'reason': meta.get('cases', {}).get(name, {}).get('reason', 'No result')})
                continue
            result = read(source)
            if not result.get('bambu') or result['bambu'] != identity:
                raise ValueError(f'Missing or inconsistent Bambu identity: {source}')
            if digest(result['configuration']) != result['config_id']:
                raise ValueError(f'Configuration checksum mismatch: {source}')
            key = result['test'], result['config_id']
            if key in records and stable(records[key]) != stable(result):
                raise ValueError(f'Conflicting repeated case: {name}')
            records[key] = result
    if len(identities) > 1:
        raise ValueError('Expected exactly one Bambu build across the run')
    records = {key: result for key, result in records.items() if selected(result['test'], patterns)}
    failures = [failure for failure in failures if selected(failure['test'], patterns)]
    if not records and not failures:
        raise ValueError('No results match the selected tests')
    return next(iter(identities.values()), None), list(records.values()), failures


def stable(result):
    return {key: result[key] for key in ('bambu', 'test', 'config_id', 'configuration', 'status', 'metrics')}


def relative_path(result):
    test = result['test']
    board = result['configuration']['board']
    for name in (test, board, result['bambu']['id']):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name in ('.', '..'):
            raise ValueError(f'Invalid result name: {name}')
    return Path(test) / f"{board}-{result['config_id']}" / 'golden.json'


def compare(path, root, patterns=()):
    identity, records, failures = load_run(path, patterns)
    report = {"bambu": identity, "reference": None, "cases": list(failures)}
    with collection_lock(root):
        latest = read(root / 'latest.json') if (root / 'latest.json').is_file() else None
        if latest:
            reference = latest['version']
            if Path(reference).name != reference:
                raise ValueError('Invalid golden reference')
            report['reference'] = reference
        for result in records:
            entry = {'test': result['test'], 'config_id': result['config_id']}
            target = root / latest['version'] / relative_path(result) if latest else None
            if result['status'] != 'PASS':
                entry.update(status='FAIL', reason=result['status'])
            elif target is None or not target.is_file():
                entry.update(status='NEW', reason='No golden for this configuration')
            else:
                gold = read(target)
                if gold['configuration'] != result['configuration']:
                    raise ValueError(f'Golden configuration mismatch: {target}')
                old, new = gold['metrics']['cycles'], result['metrics']['cycles']
                if old is None or new is None:
                    raise ValueError(f'Missing cycle count for {result["test"]}')
                entry.update(status='REGRESSION' if new > old else 'IMPROVEMENT' if new < old else 'UNCHANGED',
                             golden_cycles=old, cycles=new, delta_cycles=new-old,
                             delta_percent=100*(new-old)/old if old else None,
                             traffic_changed={k: [gold['metrics'][k], result['metrics'][k]] for k in ('dram_reads','dram_writes')
                                              if gold['metrics'][k] != result['metrics'][k]})
            report['cases'].append(entry)
    write(path / 'comparison.json', report)
    print(f"Golden reference: {report['reference'] or 'none (manual approval required)'}")
    for entry in report['cases']:
        delta = f" ({entry['delta_cycles']:+d} cycles)" if 'delta_cycles' in entry else ''
        print(f"{entry['status']:<12} {entry['test']}{delta}")
    print(f"Comparison: {path / 'comparison.json'}")
    return int(any(e['status'] in ('REGRESSION', 'FAIL') for e in report['cases']))


def approve(path, root, patterns=()):
    identity, records, failures = load_run(path, patterns)
    passing = [r for r in records if r['status'] == 'PASS']
    excluded = len(failures) + len(records) - len(passing)
    if not passing or not identity:
        raise ValueError('No successful results with a Bambu identity to approve')
    for result in passing:
        if any(result['metrics'][key] is None for key in ('cycles', 'dram_reads', 'dram_writes')):
            raise ValueError(f"Incomplete metrics: {result['test']}")
    with collection_lock(root):
        version = root / identity['id']
        if (version / 'collection.json').is_file() and read(version / 'collection.json')['bambu'] != identity:
            raise ValueError('Bambu build identifier collision')
        additions, conflicts = [], []
        for result in passing:
            destination = version / relative_path(result)
            if destination.is_file():
                old = read(destination)
                if stable(old) != stable(result):
                    conflicts.append({'test': result['test'], 'config_id': result['config_id'],
                                      'golden': old['metrics'], 'new': result['metrics']})
            else:
                additions.append((destination, result))
        if conflicts:
            raise ValueError('Existing golden differs; nothing was changed:\n' + json.dumps(conflicts, indent=2))
        for destination, result in additions:
            write(destination, result)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        write(version / 'collection.json', {'schema': 1, 'bambu': identity, 'approved_at': now,
              'configurations': len(list(version.glob('*/*/golden.json')))})
        write(root / 'latest.json', {'version': identity['id'], 'approved_at': now})
    print(f"Golden {identity['id']}: added {len(additions)}, unchanged {len(passing)-len(additions)}, excluded {excluded} failed/missing cases.")
    for failure in failures:
        print(f"EXCLUDED     {failure['test']}: {failure.get('reason', failure['status'])}")
    for result in records:
        if result['status'] != 'PASS':
            print(f"EXCLUDED     {result['test']}: {result['status']}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['compare', 'approve'])
    parser.add_argument('run', type=Path, help='Completed run or batch directory; benchmarks are never executed')
    parser.add_argument('--tests', action='append', default=[],
                        help='Select comma-separated test names/globs; repeat to combine selections')
    parser.add_argument('--results', type=Path, default=ROOT / 'results')
    args = parser.parse_args()
    try:
        return (compare if args.action == 'compare' else approve)(args.run.resolve(), args.results.resolve(), args.tests)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
