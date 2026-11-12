#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Dispatch independent suite scripts, then compare their results with golden data.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$root/tools/batch.py" "$@"
