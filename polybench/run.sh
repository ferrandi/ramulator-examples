#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Original integration and benchmark scripts: @jesunsahariar.
set -euo pipefail
suite_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export RAMULATOR_SUITE_DIR="$suite_dir"
export PYTHONDONTWRITEBYTECODE=1
exec python3 - "$@" <<'PYTHON'
import os
import sys
from pathlib import Path
suite_dir = Path(os.environ["RAMULATOR_SUITE_DIR"])
sys.path.insert(0, str(suite_dir.parent))
from tools.execution import run_suite

"""Original native, dedicated AXI and testbench-utility profiles."""
KERNELS = [
    ('gemm', 'kernel_gemm'),
    ('atax', 'kernel_atax'),
    ('bicg', 'kernel_bicg'),
    ('mvt', 'kernel_mvt'),
    ('trisolv', 'kernel_trisolv'),
    ('jacobi-1d', 'kernel_jacobi_1d'),
    ('jacobi-2d', 'kernel_jacobi_2d'),
    ('floyd-warshall', 'kernel_floyd_warshall'),
]

def recipe(name, top, profile, channels):
    kernel = f"polybench/kernels/{name}"
    filename = f"{name}.c"
    utils = "polybench/utilities"
    utility = f"@/{utils}/polybench.c"
    flags = [f"--generate-interface={'MINIMAL' if profile == 'native' else 'INFER'}",
             f"--top-fname={top}", f"--generate-tb=@/{kernel}/tb_{name}.c",
             f"-I@/{utils}", f"@/{kernel}/{filename}", "-DMINI_DATASET", "-DDATA_TYPE_IS_FLOAT",
             "-DPOLYBENCH_USE_RESTRICT", "--std=gnu11", "-p=__float,expf", "--hls-fpdiv=SRT4U", "-s",
             f"--channels-type={'MEM_ACC_11' if channels == 1 else 'MEM_ACC_NN'}",
             f"--channels-number={channels}"]
    if profile != "native":
        flags += ["-DUSE_AXI"]
    if profile in ("native", "axi_tb"):
        flags += [f"--generate-tb={utility}", "--bambu-parameter=simple-benchmark-name=1"]
    else:
        flags += [utility]
    if profile == "native":
        flags += ["-funroll-loops"]
    elif channels > 1 or profile == "recorded":
        flags += ["--bus-pipelined"]
    if profile == "recorded":
        flags += ["-fno-delete-null-pointer-checks", "--max-ulp=1", "--tb-queue-size=20"]
    return {"name": f"polybench_{name}_{profile}_{channels}ch", "limit": 20000000,
            "clock_period_ns": 10,
            "members": [f"{kernel}/{filename}", f"{kernel}/{name}.h", f"{kernel}/tb_{name}.c",
                        f"{utils}/polybench.c", f"{utils}/polybench.h"], "flags": flags}

def cases():
    for name, top in KERNELS:
        for profile in ("native", "axi"):
            for channels in (1, 2, 4):
                yield recipe(name, top, profile, channels)
        yield recipe(name, top, "axi_tb", 1)
    # Preserve the standalone collection's original two case names and flags.
    for name, top in KERNELS[:2]:
        case = recipe(name, top, "recorded", 1 if name == "gemm" else 2)
        case["name"] = f"polybench_{name}"
        case.pop("clock_period_ns")
        yield case

sys.exit(run_suite('polybench', cases, common_flags=['--simulate', '--simulator=VERILATOR', '--compiler=I386_CLANG13', '-m64', '--memory-allocation-policy=NO_BRAM', '--enable-ramulator', '--output-directory=output', '-v5']))
PYTHON
