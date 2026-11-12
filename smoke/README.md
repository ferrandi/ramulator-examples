# Smoke examples

`./run.sh` owns all smoke cases and their Bambu options. Examples:

```sh
./run.sh --case smoke_vector_add
./run.sh --case smoke_axi_2ch
./run.sh --case smoke_clock_ratio_1ch
./run.sh --case diagnostic_ddr3
```

One attributed vector-add source and XML fixture serve every channel variant.
`clock_ratio.yaml` belongs to the ratio tests. `configs/` contains the custom
memory diagnostics; standard presets come from the Bambu installation.
