# GAPBS

`./run.sh` owns the original graph kernels and thread/context-switch variants.
Example: `./run.sh --case gapbs_BFS_1co --dry-run`.
The pinned `sources/` submodule includes the outgoing graph dataset used by the
undirected graph loader. The incoming-file argument slots are unused by that loader.
