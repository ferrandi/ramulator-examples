# Bambu + Ramulator examples

Examples and longer benchmark suites for [Bambu](https://github.com/ferrandi/PandA-bambu)
with [Ramulator memory timing](https://github.com/ferrandi/ramulator2).

## Credits and provenance

- [@jesunsahariar](https://github.com/jesunsahariar) developed the original Bambu/Ramulator
  integration and benchmark scripts in
  [bambu-ramulator-release](https://github.com/jesunsahariar/bambu-ramulator-release).
- [@BENfrost-20](https://github.com/BENfrost-20) collected the standalone suites,
  runner, configurations, and recorded results in
  [tests_bambu_ramulator](https://github.com/BENfrost-20/tests_bambu_ramulator).
  This repository preserves that repository's Git history, starting from
  [`b55d3d5`](https://github.com/BENfrost-20/tests_bambu_ramulator/commit/b55d3d5).

Original source copyright and license notices remain with the respective files.
The imported benchmark projects retain their own licenses.

## Repository layout

Each suite has a `run.sh` containing its cases, compiler options and test
configuration. Run a suite directly or use `run_tests.sh` to execute several suites.

| Directory | Contents |
|---|---|
| `smoke/` | Vector-add channel variants, clock-ratio and memory diagnostics |
| `micro/` | Memory access patterns and reference checker |
| `openmp/` | Functional kernels and the original test list |
| `gapbs/` | Graph test list and pinned `sources/` submodule |
| `polybench/` | Eight checked-in kernels with conditional AXI pragmas, headers, testbenches and utilities |
| `machsuite/` | SpMV and BFS benchmarks |
| `results/` | Manually approved versioned golden data and collection/comparison scripts |
| `tools/` | Environment checks, input staging, local execution and golden comparison |

`run_tests.sh` executes the selected suites in sequence and compares their results
with the latest approved golden collection. It completes the remaining suites
after a failure and returns a failure status for failed tests or cycle-count
regressions.

`boards.json` defines the Bambu device, default clock and memory configuration
for each board. Standard memory presets come from the Bambu installation under
`share/panda/libmdpi/configs`.
Test-specific YAMLs live next to their owning tests: `smoke/configs/` contains
the recorded DDR5 diagnostic variant and a 32-channel HBM2 configuration (also
selected by the HBM board aliases), while `smoke/clock_ratio.yaml` configures the ratio variants.
`--config PATH` overrides the YAML for an execution.

## Setup and execution

Use an installed Bambu supporting `--enable-ramulator`, Verilator, Python 3.8+,
and the **64-bit installed** Ramulator library from `ferrandi/ramulator2`.
The recipes use the `I386_CLANG13` HLS frontend. Install Clang 13 for synthesis
and a host Clang compiler (the runner tries Clang 19 first). Required command-line
tools include Make, Git, Bash, Awk, `bc`, `envsubst`, `timeout` and the Binutils
utilities `objcopy` and `readelf`. The runtime library check uses `ldd`.

```sh
git clone --recursive https://github.com/gggg100/ramulator-examples.git
cd ramulator-examples
cp env.example.sh env.sh
# Configure BAMBU_HLS and RAMULATOR2_DIR, then:
source env.sh
./smoke/run.sh --tag smoke
./micro/run.sh --tag patterns
./openmp/run.sh --tag openmp
./gapbs/run.sh --tag graphs
./polybench/run.sh --tag polybench
./machsuite/run.sh --tag machsuite
```

GAPBS retains its pinned `sources/` submodule.
PolyBench includes its sources and conditional AXI pragmas.
`RAMULATOR2_DIR` points to the prefix containing
`include/ramulator/` and `lib/libramulator.so` (or `lib64/`).

The runner and each suite script accept `--board NAME`, `--config PATH`, `--tag LABEL`,
`--dry-run`, `--keep-work`, `--case NAME` and `--tests PATTERNS`. For example:

```sh
./openmp/run.sh --case openmp_monothread_1ch --tag single-case
./smoke/run.sh --case diagnostic_ddr3 --tag memory-preset
./run_tests.sh --all --tag complete
./smoke/run.sh --case smoke_axi_1ch
./smoke/run.sh --case smoke_clock_ratio_1ch
```

`--case` selects one exact case within a suite; use `--suite NAME` with the
global runner. `--tests` selects names or patterns across suites. By default,
the global runner executes all suites.

Clock selection uses `CLOCK_PERIOD_NS` when set, then the case's clock setting,
then the selected board's default. For example:

```sh
CLOCK_PERIOD_NS=10 ./smoke/run.sh --case smoke_axi_1ch
```

PolyBench includes all eight original kernels in three profiles:
`native` (1/2/4 channels), `axi` (1/2/4 channels) and `axi_tb` (one channel,
with the utility compiled as part of the testbench). The two originally recorded
cases retain their names `polybench_gemm` and `polybench_atax`.

```sh
./polybench/run.sh --case polybench_trisolv_axi_tb_1ch
./polybench/run.sh --case polybench_gemm_native_2ch
```

GAPBS keeps the original undirected graph. Its incoming-graph argument positions
are retained for compatibility; the loader only reads the outgoing graph files.
Long suites can take hours.

## Results: execute, compare, approve

The runner executes the tests. The result scripts compare or approve the saved
results.

```sh
./run_tests.sh --all --board xcu250 --tag current
# Or a selected suite / case:
./run_tests.sh --suite polybench --case polybench_trisolv_axi_tb_1ch
```

The runner prints a batch directory under `.runs/`. After all selected suites
finish, including failures, it automatically compares their results with the
**last manually approved** golden version. Independent `<suite>/run.sh` executions
also perform this comparison when used directly. Golden data is updated through
manual approval. Logs, input/configuration snapshots, metadata, per-case
JSON results and `comparison.json` remain local and ignored by Git.

Select a subset with comma-separated names or shell-style patterns. Quote the
patterns so the shell does not expand them. Repeat `--tests` to combine selections:

```sh
./run_tests.sh --all --tests 'smoke_*,polybench_trisolv_*'
./polybench/run.sh --tests 'polybench_gemm_*,polybench_atax_*'
# Set RUN_DIR to the batch directory printed by the runner.
RUN_DIR=.runs/batch_...
./results/golden.sh "$RUN_DIR" --tests 'smoke_*'
./results/compare.sh "$RUN_DIR" --tests 'polybench_*'
```

The runner skips suites with no selected cases. Golden collection and comparison
process the selected saved results.
Without `--tests`, each command processes its full normal selection. A golden or
comparison selection with no matching results is an error.

Set `RUN_DIR` to the printed batch or direct suite run directory. Inspect its
results, then explicitly approve its successful cases:

```sh
./results/golden.sh "$RUN_DIR"
# Repeat a comparison of the saved results:
./results/compare.sh "$RUN_DIR"
```

The manual collector adds missing configurations under the Bambu build used by
that run. Existing identical golden results are left unchanged. If any existing
golden differs, it reports the conflicting metrics and exits with an error
**before adding anything**. Failed or missing cases are reported and excluded; dry runs and incomplete batches cannot be approved.
Approval makes that version the reference for subsequent comparisons. Each
version contains the configurations explicitly approved for that build.

```text
results/
  latest.json
  bambu-<release>-<commit>-<build-fingerprint>/
    collection.json
    <test-name>/
      <board>-<configuration-hash>/
        golden.json
.runs/
  batch_<id>/
    batch.json
    comparison.json
    run_<id>/
      metadata.json
      summary.csv
      cases/<test-name>.json
      logs/
      config_snapshot/
```

The build fingerprint covers the Bambu binary and installed MDPI runtime, so
local changes remain distinguishable even if the version banner is unchanged.
The test configuration includes the board/device, effective clock and Bambu
flags, source/input hashes, exact YAML, Ramulator library fingerprint and
compiler/simulator versions. Paths to temporary directories are normalized.
Different boards or parameters create separate configurations within a version.
A changed test, toolchain or memory configuration is reported as `NEW`.

Automatic comparison reports `UNCHANGED`, `IMPROVEMENT` or `REGRESSION` from the
simulated cycle count, and `FAIL` or `NEW` where appropriate. Any increase in
cycles is a regression; failures and regressions produce a nonzero runner exit
status. Changed read/write counts are included in `comparison.json`. Host wall
time and timestamps are not golden metrics. With no approved collection, all
successful cases are `NEW`; execution still succeeds.

Golden JSON files belong in Git; commit them after manual review. Create the
initial golden collection from a reviewed run. Historical measurements remain
available in [@BENfrost-20's repository](https://github.com/BENfrost-20/tests_bambu_ramulator).
Preflight checks validate required tools and the installed 64-bit Ramulator
library.

Use `./run_tests.sh --list-boards` to inspect board profiles and
`./run_tests.sh --clean-work --dry-run` to preview cleanup of old local build
artifacts. Cleanup preserves the golden collection.

The result workflow has standalone tests:

```sh
python3 -m unittest discover -s tools/tests -v
```
