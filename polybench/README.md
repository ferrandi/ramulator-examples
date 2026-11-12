# PolyBench

`./run.sh` runs the eight selected PolyBench kernels using the sources included
in this directory.

Each `kernels/<name>/` directory contains one `<name>.c` source, its header and
testbench.
The `m_axi` pragmas are guarded by `#ifdef USE_AXI`; the runner passes `-DUSE_AXI`
only for the AXI profiles.
`utilities/` contains the shared PolyBench support code.

The 58 cases include `native` on the shared minimal bus with 1/2/4 channels, dedicated `axi` with
1/2/4 channels, `axi_tb` with one channel, and the two originally recorded cases
`polybench_gemm` and `polybench_atax`. The runner selects `MINIMAL` for `native`
and `INFER` for the AXI profiles.

```sh
./run.sh --case polybench_trisolv_native_1ch
./run.sh --case polybench_trisolv_axi_tb_1ch
```

## Source provenance and license

Kernel code, headers, testbenches and utilities come from
[ferrandi/PolyBenchC](https://github.com/ferrandi/PolyBenchC) at
[`7d31a759f6eced25e7d3da3eea029004b3a04336`](https://github.com/ferrandi/PolyBenchC/tree/7d31a759f6eced25e7d3da3eea029004b3a04336),
the PolyBench/C 4.2.1 beta code line used by these tests. The existing copyright
notices and [original distribution license](LICENSE.txt) are retained.

The kernel sources add only conditional per-array `m_axi` interface pragmas, following
[@jesunsahariar's integration](https://github.com/jesunsahariar/bambu-ramulator-release).
Without `USE_AXI`, the original kernel and interface behavior are preserved.

| Kernel | Original directory in that commit |
|---|---|
| `gemm` | `linear-algebra/blas/gemm` |
| `atax` | `linear-algebra/kernels/atax` |
| `bicg` | `linear-algebra/kernels/bicg` |
| `mvt` | `linear-algebra/kernels/mvt` |
| `trisolv` | `linear-algebra/solvers/trisolv` |
| `jacobi-1d` | `stencils/jacobi-1d` |
| `jacobi-2d` | `stencils/jacobi-2d` |
| `floyd-warshall` | `medley/floyd-warshall` |
