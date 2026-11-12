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

# SPDX-License-Identifier: Apache-2.0
"""GAPBS recipes with the original thread/context-switch configurations."""
from tools.source_list import cases as list_cases

def cases():
    variants = [("_1co", ["-DTHREAD_NUMBER=1", "--channels-number=1", "--channels-type=MEM_ACC_11"]),
                ("_2co", ["-DTHREAD_NUMBER=2", "--channels-number=2", "--channels-type=MEM_ACC_NN"]),
                ("_4co", ["-DTHREAD_NUMBER=4", "--channels-number=4", "--channels-type=MEM_ACC_NN"]),
                ("_2co_2cs", ["-DTHREAD_NUMBER=4", "--context_switch=2", "--channels-number=2", "--channels-type=MEM_ACC_NN"])]
    return list_cases("gapbs", "gapbs_list", "gapbs/sources", variants)

sys.exit(run_suite('gapbs', cases, common_flags=['--simulate', '--simulator=VERILATOR', '--compiler=I386_CLANG13', '-m64', '--memory-allocation-policy=NO_BRAM', '--enable-ramulator', '--output-directory=output', '-v5', '--generate-interface=INFER', '-lm', '-fopenmp', '--bus-pipelined', '--tb-queue-size=20']))
PYTHON
