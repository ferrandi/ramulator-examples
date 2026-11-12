# Golden results

See the [result workflow](../README.md#results-execute-compare-approve).

- `golden.sh RUN_OR_BATCH`: manually approve already executed successful results.
- `compare.sh RUN_OR_BATCH`: compare already executed results with `latest.json`.

Both commands accept `--tests` with comma-separated names or patterns.
Versioned golden JSON is tracked; execution evidence lives in ignored `../.runs/`.
