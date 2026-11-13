# SPDX-License-Identifier: Apache-2.0
"""Source fidelity, staging compatibility and meaningful checker regressions."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from machsuite.cases import BENCHMARKS, COMMON_FLAGS, SUITE, cases
from machsuite.prepare import BANNER, generate, prepare
from tools import execution


class IntegrationTests(unittest.TestCase):
    def test_complete_official_snapshot_and_reproducible_adapters(self):
        self.assertEqual(prepare(check=True), (204, 38))
        manifest = json.loads((SUITE / 'UPSTREAM.json').read_text())
        self.assertEqual(len(manifest['files']), 204)

    def test_kernel_bodies_are_official_with_only_conditional_pragmas(self):
        for spec in BENCHMARKS:
            with self.subTest(benchmark=spec['name']):
                generated = generate(spec, SUITE / 'sources')['kernel.c']
                stripped = re.sub(r'#ifdef MACHSUITE_USE_AXI\n.*?#endif\n', '',
                                  generated[len(BANNER):], flags=re.S)
                original = SUITE / 'sources' / spec['path'] / (spec['kernel'] + '.c')
                self.assertEqual(stripped, original.read_text())

    def test_port_names_and_positions_match_actual_top_definitions(self):
        for spec in BENCHMARKS:
            source = (SUITE / 'sources' / spec['path'] / (spec['kernel'] + '.c')).read_text()
            signature = re.search(r'^(?:void|int)\s+' + spec['top'] + r'\s*\((.*?)\)\s*\{',
                                  source, flags=re.S | re.M).group(1)
            pointers = []
            for position, parameter in enumerate(signature.split(',')):
                if '[' in parameter or '*' in parameter:
                    parameter = re.sub(r'\[[^\]]*\]', '', parameter)
                    pointers.append((re.findall(r'\w+', parameter)[-1], position))
            self.assertEqual([(port, position) for port, _, position in spec['ports']], pointers,
                             spec['name'])

    def test_all_cases_stage_with_unmodified_shared_runner(self):
        profile = dict(default_ramulator_yaml='smoke/configs/ddr4_1ch.yaml',
                       default_clock_ns=5.0, bambu_device='xcu250-2Lfigd2104')
        entries = list(cases())
        self.assertEqual(len(entries), 21)
        self.assertEqual(len({case['name'] for case in entries}), 21)
        with tempfile.TemporaryDirectory() as temporary, patch.object(execution, 'ROOT', SUITE.parent):
            for case in entries:
                with self.subTest(case=case['name']):
                    self.assertNotIn('archive', case)
                    self.assertEqual(len(case['members']), len(set(case['members'])))
                    snapshot = Path(temporary) / case['name']
                    snapshot.mkdir()
                    configured = dict(case, flags=COMMON_FLAGS + case['flags'])
                    argv, yaml = execution.stage_case(configured, snapshot, '', 'bambu', profile)
                    self.assertTrue(yaml.is_file())
                    self.assertIn('--enable-ramulator', argv)
                    self.assertIn('--generate-interface=INFER', argv)
                    for flag in argv[1:]:
                        if flag.startswith(('--generate-tb=', '--tb-arg=')):
                            self.assertTrue(Path(flag.split('=', 1)[1]).is_file(), flag)
                        elif flag.startswith('-I'):
                            self.assertTrue(Path(flag[2:]).is_dir(), flag)
                        elif flag.endswith(('.c', '.cpp')):
                            self.assertTrue(Path(flag).is_file(), flag)
                    info = json.loads((snapshot / 'inputs.json').read_text())
                    self.assertEqual(len(info['inputs_sha256']), len(case['members']))

    def test_compatibility_cases_and_explicit_backprop_reference(self):
        entries = {case['name']: case for case in cases()}
        self.assertIn('machsuite_spmv', entries)
        bfs = entries['machsuite_bfs']
        for flag in ('-DSCALE=4', '-DEDGE_FACTOR=4', '-DTHREAD_NUMBER=1'):
            self.assertIn(flag, bfs['flags'])
        self.assertIn('/data/scale4/', bfs['byte_check'])
        backprop = entries['machsuite_backprop']
        self.assertIn('--tb-arg=@/machsuite/references/backprop/check.data', backprop['flags'])
        self.assertIn('machsuite/sources/backprop/backprop/check.data', backprop['members'])
        legacy = json.loads((SUITE / 'LEGACY.json').read_text())
        for relative, expected in legacy['files'].items():
            self.assertEqual(hashlib.sha256((SUITE / relative).read_bytes()).hexdigest(), expected)


@unittest.skipUnless(shutil.which('cc'), 'C compiler required for checker regression tests')
class CheckerTests(unittest.TestCase):
    def compile_and_run(self, name, body):
        spec = next(item for item in BENCHMARKS if item['name'] == name)
        source = SUITE / 'sources' / spec['path']
        adapter = SUITE / 'adapters' / spec['path']
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            driver = work / 'driver.c'
            driver.write_text('#include "' + spec['kernel'] + '.h"\n#include <math.h>\n'
                              '#include <fcntl.h>\n' + body)
            command = ['cc', '-O1', '-I' + str(source), '-I' + str(SUITE / 'sources/common'),
                       str(adapter / 'kernel.c'), str(adapter / 'local_support.c'),
                       str(SUITE / 'sources/common/support.c'), str(driver), '-lm',
                       '-o', str(work / 'check')]
            built = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(work / 'check')], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_nan_output_is_rejected(self):
        self.compile_and_run('gemm_blocked', '''
int main(void) {
  struct bench_args_t *data = calloc(1, sizeof(*data)), *ref = calloc(1, sizeof(*ref));
  for (int i = 0; i < N; ++i) { data->prod[i] = NAN; ref->prod[i] = 1.0; }
  return check_data(data, ref) ? 1 : 0;
}
''')

    def test_wrong_sorted_multiset_is_rejected(self):
        self.compile_and_run('merge', '''
int main(void) {
  struct bench_args_t *data = calloc(1, sizeof(*data)), *ref = calloc(1, sizeof(*ref));
  for (int i = 0; i < SIZE; ++i) data->a[i] = ref->a[i] = 10;
  data->a[0] = 9; data->a[SIZE-1] = 11;
  return check_data(data, ref) ? 1 : 0;
}
''')

    def test_wrong_vertex_distances_are_rejected(self):
        input_file = json.dumps(str(SUITE / 'sources/bfs/queue/input.data'))
        check_file = json.dumps(str(SUITE / 'sources/bfs/queue/check.data'))
        self.compile_and_run('bfs_queue', '''
int main(void) {
  struct bench_args_t *data = calloc(1, sizeof(*data)), *ref = calloc(1, sizeof(*ref));
  input_to_data(open(INPUT_FILE, O_RDONLY), data);
  output_to_data(open(CHECK_FILE, O_RDONLY), ref);
  run_benchmark(data);
  if (!check_data(data, ref)) return 2;
  data->level[data->starting_node] = MAX_LEVEL;
  return check_data(data, ref) ? 1 : 0;
}
'''.replace('INPUT_FILE', input_file).replace('CHECK_FILE', check_file))


if __name__ == '__main__':
    unittest.main()
