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
from machsuite.cases import COMMON_FLAGS, cases

if sys.argv[1:] == ['--list']:
    for case in cases():
        print(case['name'])
else:
    sys.exit(run_suite('machsuite', cases, common_flags=COMMON_FLAGS))
PYTHON
