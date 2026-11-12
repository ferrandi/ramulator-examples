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

"""AXI vector add, channel variants, clock-ratio and memory diagnostics."""
def recipe(name, channels=1, config=None, period=None):
    case = {"name": name, "diagnostic_config": config,
            "members": ["smoke/vector_add_axi.c", "smoke/test_vector_add.xml"], "limit": 100000, "require_read_drain": True,
            "flags": ["--top-fname=vector_add", "--generate-tb=@/smoke/test_vector_add.xml",
                      "--tb-param-size=vec_a:32,vec_b:32,vec_c:32", "@/smoke/vector_add_axi.c",
                      f"--channels-type={'MEM_ACC_11' if channels == 1 else 'MEM_ACC_NN'}",
                      f"--channels-number={channels}"]}
    if channels > 1:
        case["flags"] += ["--bus-pipelined"]
    if period is not None:
        case["clock_period_ns"] = period
    return case

def cases():
    yield recipe("smoke_vector_add")
    for channels in (1, 2, 4):
        yield recipe(f"smoke_axi_{channels}ch", channels, period=10)
        yield recipe(f"smoke_clock_ratio_{channels}ch", channels, "smoke/clock_ratio.yaml", 10)
    for name, config in [("ddr5", "smoke/configs/ddr5.yaml"),
                         ("ddr3", "installed:xcu250_ddr3_1600K.yaml"),
                         ("hbm2", "smoke/configs/hbm2_32ch.yaml")]:
        yield recipe(f"diagnostic_{name}", config=config)

sys.exit(run_suite('smoke', cases, common_flags=['--simulate', '--simulator=VERILATOR', '--compiler=I386_CLANG13', '-m64', '--memory-allocation-policy=NO_BRAM', '--enable-ramulator', '--output-directory=output', '-v5', '--generate-interface=INFER']))
PYTHON
