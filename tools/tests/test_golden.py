# SPDX-License-Identifier: Apache-2.0
"""Exercise approval immutability, configuration matching and runner orchestration."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import golden, batch


class GoldenTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.results = self.root / 'results'
        self.counter = 0
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def result(self, cycles=100, version='bambu-1', board='board', test='test', status='PASS'):
        config = {'board': board, 'flags': ['--clock-period=5'], 'yaml_sha256': 'yaml'}
        return {'schema': 1, 'bambu': {'id': version}, 'test': test,
                'configuration': config, 'config_id': golden.digest(config),
                'status': status, 'metrics': {'cycles': cycles, 'dram_reads': 10, 'dram_writes': 5},
                'timestamp': 'time', 'examples_commit': 'examples'}

    def run_data(self, *records, dry=False, complete=True):
        self.counter += 1
        run = self.root / f'run_{self.counter}'
        run.mkdir()
        golden.write(run / 'metadata.json', {'bambu_identity': records[0]['bambu'], 'dry_run': dry,
                     'suite': 'suite', 'requested_cases': [r['test'] for r in records], 'cases': {}})
        for record in records:
            golden.write(run / 'cases' / f"{record['test']}.json", record)
        if complete:
            (run / '.complete').touch()
        return run

    def snapshot(self):
        return {str(p.relative_to(self.results)): p.read_bytes() for p in self.results.rglob('*.json')}

    def test_first_run_does_not_create_goldens(self):
        run = self.run_data(self.result())
        self.assertEqual(golden.compare(run, self.results), 0)
        self.assertEqual(golden.read(run/'comparison.json')['cases'][0]['status'], 'NEW')
        self.assertFalse((self.results/'latest.json').exists())

    def test_approval_repeat_and_add_configuration(self):
        run = self.run_data(self.result())
        golden.approve(run, self.results)
        first = next(self.results.glob('*/*/*/golden.json')).read_bytes()
        record = self.result();record['timestamp'] = 'later';record['examples_commit'] = 'different'
        golden.approve(self.run_data(record), self.results)
        self.assertEqual(next(self.results.glob('*/*/*/golden.json')).read_bytes(), first)
        golden.approve(self.run_data(self.result(board='other')), self.results)
        self.assertEqual(len(list(self.results.glob('*/*/*/golden.json'))), 2)

    def test_conflict_does_not_add_other_missing_cases(self):
        golden.approve(self.run_data(self.result()), self.results)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'nothing was changed'):
            golden.approve(self.run_data(self.result(cycles=101), self.result(test='new')), self.results)
        self.assertEqual(before, self.snapshot())

    def test_compare_latest_other_version_both_directions(self):
        golden.approve(self.run_data(self.result()), self.results)
        for cycles, status, code in [(101,'REGRESSION',1),(99,'IMPROVEMENT',0),(100,'UNCHANGED',0)]:
            run = self.run_data(self.result(cycles=cycles, version='bambu-2'))
            before = self.snapshot()
            self.assertEqual(golden.compare(run, self.results), code)
            self.assertEqual(golden.read(run/'comparison.json')['cases'][0]['status'], status)
            self.assertEqual(before, self.snapshot())

    def test_new_board_not_compared_with_old(self):
        golden.approve(self.run_data(self.result()), self.results)
        run = self.run_data(self.result(board='other', cycles=1000))
        self.assertEqual(golden.compare(run, self.results), 0)
        self.assertEqual(golden.read(run/'comparison.json')['cases'][0]['status'], 'NEW')

    def test_failed_cases_excluded_and_reported(self):
        run = self.run_data(self.result(), self.result(test='broken', status='FAIL'))
        golden.approve(run, self.results)
        self.assertEqual(len(list(self.results.glob('*/*/*/golden.json'))), 1)
        self.assertEqual(golden.compare(run, self.results), 1)

    def test_latest_means_last_approved_not_lexical_order(self):
        golden.approve(self.run_data(self.result(version='bambu-9')), self.results)
        golden.approve(self.run_data(self.result(version='bambu-2')), self.results)
        self.assertEqual(golden.read(self.results/'latest.json')['version'], 'bambu-2')

    def test_dry_and_incomplete_not_approved(self):
        for run in [self.run_data(self.result(), dry=True), self.run_data(self.result(), complete=False)]:
            with self.assertRaises(ValueError):golden.approve(run,self.results)
        self.assertFalse(self.results.exists())

    def test_tampered_configuration_rejected(self):
        record = self.result();record['configuration']['board'] = 'tampered'
        with self.assertRaisesRegex(ValueError,'checksum'):
            golden.approve(self.run_data(record),self.results)

    def test_batch_includes_every_suite_and_missing_case(self):
        runs = [self.run_data(self.result()), self.run_data(self.result(test='other'))]
        (runs[1]/'cases/other.json').unlink()
        directory = self.root/'batch';directory.mkdir()
        for run in runs:run.rename(directory/run.name)
        golden.write(directory/'batch.json', {'complete':True,'runs':[r.name for r in runs]})
        self.assertEqual(golden.compare(directory,self.results),1)
        report = golden.read(directory/'comparison.json')
        self.assertEqual({r['status'] for r in report['cases']}, {'FAIL','NEW'})

    def test_batch_mixed_builds_rejected(self):
        runs = [self.run_data(self.result()),self.run_data(self.result(version='bambu-other',test='other'))]
        directory = self.root/'batch';directory.mkdir()
        for run in runs:run.rename(directory/run.name)
        golden.write(directory/'batch.json',{'complete':True,'runs':[r.name for r in runs]})
        with self.assertRaisesRegex(ValueError,'one Bambu'):golden.approve(directory,self.results)

    def test_runner_invokes_every_suite_once_then_compares_once(self):
        calls=[]
        def invoke(argv,env):
            suite=Path(argv[0]).parent.name
            calls.append(suite)
            run=Path(env['RAMULATOR_BATCH'])/f'run_{suite}'
            run.mkdir()
            return int(suite=='micro')
        with patch.object(batch,'ROOT',self.root),patch.object(batch.subprocess,'call',side_effect=invoke),patch.object(batch,'compare',return_value=0) as comparison:
            self.assertEqual(batch.main(['--all']),1)
            self.assertEqual(calls,list(batch.SUITES))
            comparison.assert_called_once()
            manifest=golden.read(comparison.call_args.args[0]/'batch.json')
            self.assertTrue(manifest['complete'])
            self.assertEqual(len(manifest['runs']),len(batch.SUITES))

    def test_approve_subset_ignores_unselected_conflicts(self):
        golden.approve(self.run_data(self.result(test='other')), self.results)
        run = self.run_data(self.result(test='chosen'), self.result(test='other', cycles=999))
        golden.approve(run, self.results, ['chosen'])
        self.assertEqual(len(list(self.results.glob('*/*/*/golden.json'))), 2)
        self.assertEqual(golden.compare(run, self.results, ['chosen']), 0)
        self.assertEqual(len(golden.read(run/'comparison.json')['cases']), 1)

    def test_patterns_combine_and_no_match_is_error(self):
        run = self.run_data(self.result(test='smoke_one'), self.result(test='poly_two'), self.result(test='other'))
        _, records, _ = golden.load_run(run, ['smoke_*,exact', 'poly_*'])
        self.assertEqual({r['test'] for r in records}, {'smoke_one', 'poly_two'})
        with self.assertRaisesRegex(ValueError, 'No results match'):
            golden.approve(run, self.results, ['missing_*'])

    def test_suite_subset_and_skip_do_not_run_extra_cases(self):
        from tools import execution
        cases = lambda: [{'name':name,'flags':[]} for name in ('smoke_one','smoke_two','other')]
        with patch.object(execution, 'main', return_value=0) as execute:
            self.assertEqual(execution.run_suite('smoke', cases, ['--tests','smoke_*']), 0)
            self.assertEqual([case['name'] for case in execute.call_args.args[-1]], ['smoke_one','smoke_two'])
            execute.reset_mock()
            self.assertEqual(execution.run_suite('smoke', cases, ['--tests','absent']), 0)
            execute.assert_not_called()

    def test_record_normalizes_temporary_paths_and_keeps_yaml(self):
        results = []
        for index in range(2):
            run = self.root / f'normalization_{index}'
            snapshot = run / 'config_snapshot' / 'test'
            snapshot.mkdir(parents=True)
            yaml = snapshot / 'memory.yaml'
            yaml.write_text('MemorySystem: {}\n')
            golden.write(snapshot / 'inputs.json', {
                'argv': ['/installed/bambu', str(snapshot/'inputs/kernel.c')],
                'inputs_sha256': {'kernel.c': 'kernel-hash'}, 'yaml_sha256': 'yaml-hash',
                'ramulator2_config': str(yaml)})
            metadata = {'board_profile': {'name':'board','bambu_device':'device'},
                        'ramulator_library': {'sha256':'ramulator'}, 'tool_versions': {},
                        'bambu_identity': {'id':'bambu-1'}, 'git_commit':'examples',
                        'cases': {'test': {'timestamp':'time'}}}
            row = {'status':'PASS','total_sim_cycles':100,'dram_read_reqs':10,'dram_write_reqs':5}
            golden.record_result(run, metadata, {'name':'test'}, row, snapshot, '5')
            results.append(golden.read(run/'cases/test.json'))
        self.assertEqual(results[0]['configuration'], results[1]['configuration'])
        self.assertEqual(results[0]['configuration']['flags'], ['@/kernel.c'])
        self.assertEqual(results[0]['configuration']['yaml'], 'MemorySystem: {}\n')

    def test_failed_preflight_without_bambu_is_comparable(self):
        run=self.run_data(self.result())
        meta=golden.read(run/'metadata.json');meta.update(bambu_identity=None,requested_cases=[],preflight_errors=['no Bambu'])
        golden.write(run/'metadata.json',meta)
        self.assertEqual(golden.compare(run,self.results),1)


if __name__ == '__main__':
    unittest.main()
