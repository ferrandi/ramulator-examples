#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile and functionally check local sources without Bambu or Ramulator."""
import argparse
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from machsuite.cases import SUITE, cases
from machsuite.prepare import prepare


def validate(case, directory, cc, cxx, sanitizers=False, upstream_reference=False):
    root = SUITE.parent
    directory.mkdir(parents=True, exist_ok=True)
    flags = case['flags']
    sources = [flag for flag in flags if flag.startswith('@/') and flag.endswith(('.c', '.cpp'))]
    sources += [flag.split('=', 1)[1] for flag in flags if flag.startswith('--generate-tb=')]
    cpp = any(path.endswith('.cpp') for path in sources)
    expand = lambda value: value.replace('@/', str(root) + '/')
    command = shlex.split(cxx if cpp else cc) + ['-O1' if sanitizers else '-O3', '-g',
               '-Wno-unknown-pragmas', '-Wno-unused-label']
    command += [expand(flag) for flag in flags if flag.startswith(('-I', '-D'))]
    command += ['-std=' + ('gnu++11' if cpp else 'gnu11')]
    if sanitizers:
        command += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    command += list(map(expand, sources)) + ['-lm', '-o', str(directory / 'benchmark')]
    build = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (directory / 'build.log').write_text(build.stdout + build.stderr)
    result = dict(name=case['name'], build_command=command, build_returncode=build.returncode)
    if build.returncode:
        return dict(result, status='BUILD_FAIL')
    arguments = [expand(flag.split('=', 1)[1]) for flag in flags if flag.startswith('--tb-arg=')]
    if upstream_reference and case['name'] == 'machsuite_backprop':
        arguments[1] = str(SUITE / 'sources/backprop/backprop/check.data')
    result['input_files'] = arguments
    run = subprocess.run([str(directory / 'benchmark'), *arguments], cwd=directory,
                         capture_output=True, text=True, timeout=120)
    (directory / 'run.log').write_text(run.stdout + run.stderr)
    success = run.returncode == 0 and 'Success.' in run.stdout.splitlines()
    if case.get('byte_check'):
        success &= (directory / 'output.data').is_file() and (
            directory / 'output.data').read_bytes() == (root / case['byte_check']).read_bytes()
    # Sanitizer runtimes can report UB while the program still returns zero.
    success &= 'runtime error:' not in run.stderr and 'ERROR: AddressSanitizer' not in run.stderr
    return dict(result, status='PASS' if success else 'FAIL', run_returncode=run.returncode,
                stdout=run.stdout, stderr=run.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', help='One exact name from run.sh --list')
    parser.add_argument('--tests', default='*', help='Comma-separated case names/globs')
    parser.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    parser.add_argument('--cxx', default=os.environ.get('CXX', 'c++'))
    parser.add_argument('--work-dir', type=Path, default=SUITE / 'build/native')
    parser.add_argument('--sanitizers', action='store_true', help='Require compiler ASan/UBSan support')
    parser.add_argument('--upstream-reference', action='store_true',
                        help='Diagnose backprop using the unchanged upstream oracle instead')
    args = parser.parse_args()
    prepare(check=True)
    selection = [case for case in cases()
                 if (not args.case or case['name'] == args.case)
                 and any(fnmatchcase(case['name'], pattern) for pattern in args.tests.split(','))]
    if not selection:
        parser.error('No cases selected')
    work = args.work_dir.resolve()
    results = []
    print('Host functional checks only. Legacy BFS uses its fixed single thread; OpenMP/HLS pragmas are ignored.')
    for case in selection:
        try:
            result = validate(case, work / case['name'], args.cc, args.cxx,
                              args.sanitizers, args.upstream_reference)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = dict(name=case['name'], status='ERROR', error=str(exc))
        results.append(result)
        print('%-30s %s' % (case['name'], result['status']), flush=True)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print('Results: ' + str(work / 'results.json'))
    return int(any(result['status'] != 'PASS' for result in results))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
