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
"""Memory access pattern recipes."""
ONE_CHANNEL = ["--channels-type=MEM_ACC_11", "--channels-number=1"]

def cases():
    # Channel variants change the HLS interface. Physical topology comes from the board YAML.
    for name, pattern, words, outputs, stride in (
        ("t01_clock", 1, 2, 1, 1),
        ("t02_single_read", 2, 1, 1, 1),
        ("t03_read_after_write", 3, 2, 1, 1),
        ("t04_stream", 4, 512, 512, 1),
        ("t05_queue_pressure", 5, 4096, 4096, 1),
        ("t06_byte_lanes", 6, 2, 1, 1),
        ("t07_row_local", 7, 32769, 1, 1),
        ("t07_row_stride", 7, 32769, 1, 32768),
        ("t08_refresh_stream", 8, 32768, 1, 1),
        ("t09_channels_1", 9, 8192, 1, 16),
        ("t09_channels_4", 9, 8192, 1, 16),
        ("t10_native_and_axi", 10, 512, 512, 1),
    ):
        channels = (["--channels-type=MEM_ACC_NN", "--channels-number=4"]
                    if name == "t09_channels_4" else ONE_CHANNEL)
        yield {
            "name": name, "members": ["micro/pattern.c", "micro/check.c"],
            "limit": 10000000, "marker": "MICRO CHECK PASS",
            "flags": [
                "--top-fname=memory_pattern", "--generate-tb=@/micro/check.c", "@/micro/pattern.c",
                f"-DPATTERN={pattern}", f"-DWORDS={words}", f"-DOUT_WORDS={outputs}", f"-DSTRIDE={stride}",
                f"--tb-param-size=in:{4 * words},out:{4 * outputs}", "--std=gnu11",
                "--tb-queue-size=64" if pattern == 5 else "--tb-queue-size=20",
                "-fno-tree-vectorize", *channels, "--bus-pipelined",
            ],
        }

sys.exit(run_suite('micro', cases, common_flags=['--simulate', '--simulator=VERILATOR', '--compiler=I386_CLANG13', '-m64', '--memory-allocation-policy=NO_BRAM', '--enable-ramulator', '--output-directory=output', '-v5', '--generate-interface=INFER']))
PYTHON
