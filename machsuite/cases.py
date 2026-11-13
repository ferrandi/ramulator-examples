# SPDX-License-Identifier: Apache-2.0
"""Official workloads and the two previously recorded compatibility recipes."""
from pathlib import Path

SUITE = Path(__file__).resolve().parent
COMMON_FLAGS = [
    '--simulate', '--simulator=VERILATOR', '--compiler=I386_CLANG13', '-m64',
    '--memory-allocation-policy=NO_BRAM', '--enable-ramulator',
    '--output-directory=output', '-v5', '--generate-interface=INFER',
]


def benchmark(name, path, kernel, top, ports, fields=None):
    """ports are (top parameter, bench_args_t field, zero-based position)."""
    return dict(name=name, path=path, kernel=kernel, top=top,
                ports=ports, finite_fields=fields or [])


def arrays(*names):
    return [(name, name, index) for index, name in enumerate(names)]


BENCHMARKS = [
    benchmark('aes', 'aes/aes', 'aes', 'aes256_encrypt_ecb', arrays('ctx', 'k', 'buf')),
    benchmark('backprop', 'backprop/backprop', 'backprop', 'backprop',
              arrays('weights1', 'weights2', 'weights3', 'biases1', 'biases2',
                     'biases3', 'training_data', 'training_targets'),
              ['weights1', 'weights2', 'weights3', 'biases1', 'biases2', 'biases3']),
    *[benchmark('bfs_' + variant, 'bfs/' + variant, 'bfs', 'bfs',
                [('nodes', 'nodes', 0), ('edges', 'edges', 1),
                 ('level', 'level', 3), ('level_counts', 'level_counts', 4)])
      for variant in ('bulk', 'queue')],
    benchmark('fft_strided', 'fft/strided', 'fft', 'fft',
              arrays('real', 'img', 'real_twid', 'img_twid'), ['real', 'img']),
    benchmark('fft_transpose', 'fft/transpose', 'fft', 'fft1D_512',
              arrays('work_x', 'work_y'), ['work_x', 'work_y']),
    *[benchmark('gemm_' + variant, 'gemm/' + variant, 'gemm', top,
                arrays('m1', 'm2', 'prod'), ['prod'])
      for variant, top in (('blocked', 'bbgemm'), ('ncubed', 'gemm'))],
    benchmark('kmp', 'kmp/kmp', 'kmp', 'kmp', arrays('pattern', 'input', 'kmpNext', 'n_matches')),
    benchmark('md_grid', 'md/grid', 'md', 'md', arrays('n_points', 'force', 'position')),
    benchmark('md_knn', 'md/knn', 'md', 'md_kernel',
              arrays('force_x', 'force_y', 'force_z', 'position_x', 'position_y', 'position_z', 'NL'),
              ['force_x', 'force_y', 'force_z']),
    benchmark('nw', 'nw/nw', 'nw', 'needwun',
              [('SEQA', 'seqA', 0), ('SEQB', 'seqB', 1), ('alignedA', 'alignedA', 2),
               ('alignedB', 'alignedB', 3), ('M', 'M', 4), ('ptr', 'ptr', 5)]),
    benchmark('merge', 'sort/merge', 'sort', 'ms_mergesort', arrays('a')),
    benchmark('radix', 'sort/radix', 'sort', 'ss_sort', arrays('a', 'b', 'bucket', 'sum')),
    benchmark('spmv_crs', 'spmv/crs', 'spmv', 'spmv',
              arrays('val', 'cols', 'rowDelimiters', 'vec', 'out'), ['out']),
    benchmark('spmv_ellpack', 'spmv/ellpack', 'spmv', 'ellpack',
              arrays('nzval', 'cols', 'vec', 'out'), ['out']),
    benchmark('stencil2d', 'stencil/stencil2d', 'stencil', 'stencil', arrays('orig', 'sol', 'filter')),
    benchmark('stencil3d', 'stencil/stencil3d', 'stencil', 'stencil3d', arrays('C', 'orig', 'sol')),
    benchmark('viterbi', 'viterbi/viterbi', 'viterbi', 'viterbi',
              arrays('obs', 'init', 'transition', 'emission', 'path')),
]


def official_case(spec):
    source = 'machsuite/sources/' + spec['path']
    adapter = 'machsuite/adapters/' + spec['path']
    common = 'machsuite/sources/common'
    check = source + '/check.data'
    # Keep upstream's reference; select the archive's separately attributed
    # working reference for the executable backprop case.
    if spec['name'] == 'backprop':
        check = 'machsuite/references/backprop/check.data'
    members = [
        source + '/' + spec['kernel'] + '.c', source + '/' + spec['kernel'] + '.h',
        source + '/local_support.c', source + '/input.data', source + '/check.data',
        adapter + '/kernel.c', adapter + '/local_support.c',
        *[common + '/' + filename for filename in ('support.h', 'support.c', 'harness.c')],
    ]
    if check not in members:
        members.append(check)
    return dict(
        name='machsuite_' + spec['name'], members=members,
        flags=[
            '--top-fname=' + spec['top'], '-I@/' + source, '-I@/' + common,
            '@/' + adapter + '/kernel.c', '--generate-tb=@/' + adapter + '/local_support.c',
            '--generate-tb=@/' + common + '/harness.c', '--generate-tb=@/' + common + '/support.c',
            '--tb-arg=@/' + source + '/input.data', '--tb-arg=@/' + check,
            '--std=gnu11', '-DMACHSUITE_USE_AXI', '-lm', '-fno-tree-vectorize',
            '-fno-delete-null-pointer-checks', '--hls-div=NR', '--tb-queue-size=4',
            '--channels-type=MEM_ACC_11', '--channels-number=1', '--bus-pipelined',
        ], marker='Success.',
    )


def compatibility_cases():
    """Keep the old names, kernel contents, inputs and significant HLS flags."""
    for name, relative, macros in (
        ('spmv', 'spmv/crs_axi', []),
        ('bfs', 'bfs_parallel/queue_axi', ['-DSCALE=4', '-DEDGE_FACTOR=4', '-DTHREAD_NUMBER=1', '-fopenmp']),
    ):
        kernel = 'machsuite/legacy/' + relative
        common = 'machsuite/legacy/common'
        data = kernel + '/data/scale4' if name == 'bfs' else kernel
        check = data + '/check.data'
        yield dict(
            name='machsuite_' + name,
            members=[kernel + '/' + name + '.cpp', kernel + '/' + name + '.hpp',
                     kernel + '/local_support.cpp',
                     *[common + '/' + filename for filename in ('support.hpp', 'support.cpp', 'harness.cpp')],
                     data + '/input.data', check],
            flags=[
                '--top-fname=' + name, '-I@/' + common, '@/' + kernel + '/' + name + '.cpp',
                '--generate-tb=@/' + kernel + '/local_support.cpp',
                '--generate-tb=@/' + common + '/harness.cpp', '--generate-tb=@/' + common + '/support.cpp',
                '--tb-arg=@/' + data + '/input.data', '--tb-arg=@/' + check,
                '--std=gnu++11', '-fno-tree-vectorize', '-fno-delete-null-pointer-checks',
                '--hls-div=NR', '--tb-queue-size=4', '--channels-type=MEM_ACC_11',
                '--channels-number=1', '--bus-pipelined', *macros,
            ], marker='Success.', byte_check=check if name == 'bfs' else None,
        )


def cases():
    yield from compatibility_cases()
    for spec in BENCHMARKS:
        yield official_case(spec)
