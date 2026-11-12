# SPDX-License-Identifier: Apache-2.0
"""Dispatch independent suites once, then compare their completed results."""
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.golden import ROOT, compare, write

SUITES = ('smoke', 'micro', 'openmp', 'gapbs', 'polybench', 'machsuite')


def main(arguments):
    if arguments[:1] in (['--help'], ['-h']):
        print('Usage: ./run_tests.sh [--all | --suite NAME | --smoke] [suite options]')
        print('Suites: ' + ', '.join(SUITES))
        print("Subset: --tests 'smoke_*,polybench_trisolv_*' (repeatable, comma-separated names/globs)")
        print('Runs each suite once, then compares with the latest approved golden collection.')
        print('Use --no-compare to validate test execution only.')
        print('Each suite also runs directly as <suite>/run.sh. Use it with --help for options.')
        return 0
    if arguments[:1] in (['--list-boards'], ['--clean-work']):
        return subprocess.call([sys.executable, str(ROOT / 'tools/execution.py'), *arguments])
    selected = SUITES
    if arguments[:1] == ['--suite']:
        if len(arguments) < 2 or arguments[1] not in SUITES:
            raise ValueError('--suite requires one of: ' + ', '.join(SUITES))
        selected, arguments = (arguments[1],), arguments[2:]
    elif arguments[:1] == ['--smoke']:
        selected, arguments = ('smoke',), arguments[1:]
    elif arguments[:1] == ['--all']:
        arguments = arguments[1:]
    if '--help' in arguments or '-h' in arguments:
        return subprocess.call([str(ROOT / selected[0] / 'run.sh'), *arguments])
    runs = ROOT / '.runs'
    runs.mkdir(exist_ok=True)
    batch = Path(tempfile.mkdtemp(prefix=f'batch_{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}_', dir=runs))
    manifest = {'complete': False, 'suites': list(selected), 'runs': [], 'failures': []}
    write(batch / 'batch.json', manifest)
    print(f'Batch directory: {batch}', flush=True)
    environment = dict(os.environ, RAMULATOR_BATCH=str(batch))
    failed = False
    for suite in selected:
        before = set(batch.glob('run_*'))
        print(f'=== {suite} ===', flush=True)
        code = subprocess.call([str(ROOT / suite / 'run.sh'), *arguments], env=environment)
        created = sorted(set(batch.glob('run_*')) - before)
        manifest['runs'].extend(path.name for path in created)
        if code:
            failed = True
            if not created:
                manifest['failures'].append({'test': suite, 'status': 'FAIL', 'reason': f'Suite exited {code} without results'})
        write(batch / 'batch.json', manifest)
    manifest['complete'] = True
    write(batch / 'batch.json', manifest)
    if '--dry-run' not in arguments and '--no-compare' not in arguments:
        failed |= bool(compare(batch, ROOT / 'results'))
    if '--dry-run' in arguments:
        print('Dry run: no tests executed; comparison and golden approval are unavailable.', flush=True)
    else:
        print(f'Approve successful results manually: ./results/golden.sh {batch}', flush=True)
    return int(failed)


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print('Interrupted; incomplete batch retained, golden results unchanged.', file=sys.stderr)
        sys.exit(130)
