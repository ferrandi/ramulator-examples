# SPDX-License-Identifier: Apache-2.0
"""Translate the imported benchmark lists into shared-runner recipes."""
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parent.parent

def cases(suite, filename, source, variants):
    for line in (ROOT / suite / filename).read_text().splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        flags = [token.replace("BENCHMARKS_ROOT", "@/" + source) for token in tokens[1:]]
        name = next(token.split("=", 1)[1] for token in flags if token.startswith("--benchmark-name="))
        for suffix, extra in variants:
            yield {"name": f"{suite}_{name}{suffix}", "members": [], "trees": [source + "/src"] if suite == "openmp" else [source],
                   "flags": ["@/" + source + "/" + (tokens[0][len("BENCHMARKS_ROOT/"):] if tokens[0].startswith("BENCHMARKS_ROOT/") else tokens[0]),
                             *flags, *extra]}
