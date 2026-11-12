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
"""OpenMP functional tests from the imported test list."""
from tools.source_list import cases as list_cases

def cases():
    return list_cases("openmp", "functional_list_axi_ramulator", "openmp", [("", [])])

sys.exit(run_suite('openmp', cases, common_flags=['--simulate', '--simulator=VERILATOR', '--compiler=I386_CLANG13', '-m64', '--memory-allocation-policy=NO_BRAM', '--enable-ramulator', '--output-directory=output', '-v5', '-lm', '-fopenmp', '--bus-pipelined', '--tb-queue-size=20']))
PYTHON
