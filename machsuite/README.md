# MachSuite with Bambu and Ramulator

The suite includes the complete official MachSuite source snapshot and **21 runnable
recipes**: all 19 official workloads, plus the two existing compatibility cases
`machsuite_spmv` and `machsuite_bfs`. No ZIP archive or `BENCHMARK_ARCHIVES` setting
is required. Run these commands from the repository root:

```sh
./machsuite/run.sh --list
./machsuite/run.sh --case machsuite_spmv --tag spmv
./machsuite/run.sh --case machsuite_bfs --tag bfs
./machsuite/run.sh --case machsuite_gemm_blocked --tag gemm
./machsuite/run.sh --tests 'machsuite_bfs_*' --tag official-bfs
./machsuite/run.sh --tag machsuite --no-compare
# The existing global runner also discovers this expanded suite:
./run_tests.sh --suite machsuite --tests 'machsuite_spmv_*'
```

The Bambu/Ramulator installation and Linux x86-64 host requirements in the main
README still apply. `--list`, source verification and native functional checks
do not require that installation. The suite-specific `--list` option is used with
`machsuite/run.sh`; other selection/execution options are delegated to the shared
runner without changes.

## Source layout and provenance

| Path | Purpose |
|---|---|
| `sources/` | All 204 tracked files from official MachSuite, unchanged |
| `UPSTREAM.json` | Official URL, pinned commit and SHA-256 for every upstream file |
| `adapters/<algorithm>/<variant>/kernel.c` | Generated original kernel plus conditional per-port AXI annotations |
| `adapters/<algorithm>/<variant>/local_support.c` | Generated input/output support, MDPI allocation sizes and checked outputs |
| `prepare.py` | Verify/import the pinned source and regenerate adapters |
| `cases.py` | Explicit 19-workload mapping, ports, references and compatibility recipes |
| `legacy/` | Exact sources/data needed by the previous two archive-based recipes, with license |
| `references/backprop/check.data` | Separately attributed alternate backprop reference used by the executable recipe |
| `LEGACY.json` | Archive provenance and hashes for compatibility/reference files |
| `validate.py`, `tests/` | Host checks and integration/checker regression tests |

Official source: [breagen/MachSuite](https://github.com/breagen/MachSuite), pinned to
[`6236e593012cb86b0d2f08d9fb9ba0411ff989b4`](https://github.com/breagen/MachSuite/tree/6236e593012cb86b0d2f08d9fb9ba0411ff989b4).
The upstream license and individual notices are preserved in `sources/LICENSE`
and the original files. The vendored Makefiles, HLS Tcl scripts, generators,
legacy test programs, fixtures and common support are all kept intact. Their
original top-level Makefile excludes backprop; our explicit `cases.py` does not.
Use this suite's launcher for the integrated flow rather than the vendored
upstream Makefile or Vitis scripts.

The compatibility files and alternate backprop reference come from the supplied
`MachSuite_modified.zip`. The original integration and benchmark scripts were
provided by [@jesunsahariar](https://github.com/jesunsahariar) and collected in
[@BENfrost-20's tests repository](https://github.com/BENfrost-20/tests_bambu_ramulator),
as described in the main README. Archive file hashes are recorded in `LEGACY.json`.

## Official workloads

Each official recipe uses its original input, dimensions, types and computation.
All use one AXI memory channel and the repository's existing `--enable-ramulator`,
`INFER`, `NO_BRAM`, `I386_CLANG13`, 64-bit, Verilator flow. Board, clock and YAML
selection remain controlled by the shared runner. No new Vitis dependency or
old fixed-delay Ramulator launcher is introduced.

| Case | Official workload | Active check |
|---|---|---|
| `machsuite_aes` | `aes/aes` | Exact ciphertext |
| `machsuite_backprop` | `backprop/backprop` | Finite weights/biases, tolerance `1e-6`; alternate reference below |
| `machsuite_bfs_bulk` | `bfs/bulk`, 256 nodes/4,096 edges | Every vertex distance plus reference histogram |
| `machsuite_bfs_queue` | `bfs/queue`, 256 nodes/4,096 edges | Every vertex distance plus reference histogram |
| `machsuite_fft_strided` | `fft/strided`, 1,024 complex samples | Finite real/imaginary outputs, tolerance `1e-6` |
| `machsuite_fft_transpose` | `fft/transpose`, 512 complex samples | Finite real/imaginary outputs, tolerance `1e-6` |
| `machsuite_gemm_blocked` | `gemm/blocked`, 64×64, block size 8 | Finite product, tolerance `1e-6` |
| `machsuite_gemm_ncubed` | `gemm/ncubed`, 64×64 | Finite product, tolerance `1e-6` |
| `machsuite_kmp` | `kmp/kmp` | Exact match count |
| `machsuite_md_grid` | `md/grid` | Finite forces, tolerance `1e-6` |
| `machsuite_md_knn` | `md/knn` | Finite forces, tolerance `1e-6` |
| `machsuite_nw` | `nw/nw`, two length-128 sequences | Exact aligned sequences |
| `machsuite_merge` | `sort/merge`, 2,048 integers | Exact sorted reference array |
| `machsuite_radix` | `sort/radix`, 2,048 integers | Exact sorted reference array |
| `machsuite_spmv_crs` | `spmv/crs`, 494 rows/1,666 nonzeros | Finite output, tolerance `1e-6` |
| `machsuite_spmv_ellpack` | `spmv/ellpack`, 494 rows, width 10 | Finite output, tolerance `1e-6` |
| `machsuite_stencil2d` | `stencil/stencil2d`, 128×64 | Exact integer output |
| `machsuite_stencil3d` | `stencil/stencil3d`, 16×32×32 | Exact integer output |
| `machsuite_viterbi` | `viterbi/viterbi`, 64 states/140 observations | Exact state path |

The generated kernel adds `#pragma HLS interface ... mode=m_axi offset=direct`
under `MACHSUITE_USE_AXI` immediately before the original top definition. The
algorithm body, types, bounds and arithmetic remain official. Every pointer
parameter is mapped to its original `bench_args_t` field; its full byte size is
registered with `m_param_alloc` under `__BAMBU_SIM__`. BFS's scalar source-node
parameter is not treated as a memory parameter.

Original input/output parsing and the common C harness are reused. Active adapter
checkers additionally reject non-finite floating outputs, compare sorting results
exactly instead of overflowing signed checksums, and check BFS vertex distances
using a separate host traversal. Integer stencil checks use exact array comparison.
These changes are confined to the adapters; the original checkers remain in
`sources/`. The shared runner still checks the harness success marker, Bambu
return value, completed simulation, Ramulator initialization and memory traffic.

### Backprop reference exception

All 19 official inputs and all 19 official references are preserved unchanged.
Eighteen official recipes use the official reference. The backprop recipe
explicitly selects `references/backprop/check.data`, the outer archive reference
previously selected by the modified suite's Bambu manifest. Both the unchanged
public kernel and the modified kernel pass against that file on the tested host
and fail against the upstream reference. The upstream file is not overwritten or
regenerated; both references are included in the staged case for traceability.
The alternative is a documented compatibility choice, not a claim of independent
mathematical verification of the backprop oracle.

To inspect that discrepancy directly without changing either file:

```sh
python3 machsuite/validate.py --case machsuite_backprop
# Diagnostic: expected to fail on the host used for this import.
python3 machsuite/validate.py --case machsuite_backprop --upstream-reference
```

## Existing compatibility cases

- `machsuite_spmv` retains the previous archive's serial C++ CSR AXI source,
  input, reference and significant HLS settings. It is distinct from the new
  official-C `machsuite_spmv_crs` case.
- `machsuite_bfs` retains the previous C++ frontier BFS source and scale-4 data,
  with **`SCALE=4`, `EDGE_FACTOR=4`, `THREAD_NUMBER=1`**. The source's large root
  dataset is not imported or selected. The exact output-file check remains.
  This deliberately single-thread configuration does not establish correctness
  for the source's unsynchronized multithreaded vertex marking. Use the two new
  official BFS cases for upstream workloads; do not increase thread count here
  without addressing that race and validating parallel behavior.

Their names remain available to existing commands. Moving sources out of the ZIP
changes staged paths and configuration hashes, so previously approved performance
goldens can be reported as `NEW`. New official cases also require their own
measured results. Existing golden data is not changed automatically. Review runs
and use the existing manual approval workflow; native checks do not approve
hardware timing.

## Reproducible source import and adapter maintenance

Verify all 204 official hashes and all 38 generated adapter files:

```sh
python3 machsuite/prepare.py --check
```

After deliberately editing the adapter generation logic or workload metadata,
regenerate the adapters and review their diff:

```sh
python3 machsuite/prepare.py
```

To reproduce the import from a fresh official checkout at the pinned commit:

```sh
python3 machsuite/prepare.py --import-from /absolute/path/to/MachSuite
```

The import uses only Python's standard library, verifies every pinned source hash
before writing, and writes only under `machsuite/`. It makes no network request.
A different upstream revision requires a reviewed manifest/adapter update; the
script will not guess how to patch it. Avoid editing generated adapter files by
hand, and keep local integration changes out of `sources/`.

## Validation and limits

```sh
python3 -m unittest discover -s machsuite/tests -v
python3 machsuite/validate.py
python3 machsuite/validate.py --sanitizers --work-dir machsuite/build/sanitized
```

Native validation requires C and C++ compilers (`--cc`, `--cxx`, or `CC`/`CXX` can
select them). Artifacts go under `machsuite/build/` by default. OpenMP/HLS pragmas
are ignored for these host checks; the compatibility BFS uses its fixed single
thread. The upstream-reference diagnostic intentionally returns failure when
that reference does not match; the main native run uses the documented active
reference. Sanitizer reports cause failure even if the benchmark returns zero.

During this import, all 21 cases passed native execution and ASan/UBSan checks on
Apple Clang 21/arm64 macOS. Eight integration/checker tests passed, including
staging every recipe through the unchanged shared runner and rejection of NaN
GEMM outputs, incorrect sorted multisets and incorrect BFS vertex levels. All
21 simulation support sources also passed syntax checks against the local Bambu
MDPI header. The existing 19 shared golden-workflow tests passed.

Bambu, Verilator and the Linux x86-64 runtime were not available on that host, so
these results do **not** establish synthesis, RTL co-simulation, Ramulator traffic,
performance, or multithreaded correctness for the expanded suite. Run the selected
hardware cases on the configured Linux host before treating them as validated
Ramulator benchmarks. Expensive kernels can take substantial time; select cases
or patterns when establishing the first hardware results.
