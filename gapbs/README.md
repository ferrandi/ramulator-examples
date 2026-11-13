# GAPBS

`./run.sh` owns the original graph kernels and thread/context-switch variants.
Example: `./run.sh --case gapbs_BFS_1co --dry-run`.

## Source and setup

`sources/` is the existing submodule of the
[Bambu-adapted GAPBS fork](https://github.com/jesunsahariar/gapbs), pinned to
[`5dee20020e91856bc5c7d9d4a92184212354a3bc`](https://github.com/jesunsahariar/gapbs/tree/5dee20020e91856bc5c7d9d4a92184212354a3bc).
The original benchmark is [sbeamer/gapbs](https://github.com/sbeamer/gapbs);
the registered recipes require the fork's adapted `.cpp` interfaces, not the
original `.cc` programs. See the main README for submodule initialization.

Recipes continue to select `src/bfs.cpp`, `src/cc.cpp`, `src/pr.cpp` and
`src/tc.cpp`. The separate `src_axi/` variants are not substituted. Source
licenses remain in `sources/LICENSE` and the individual files.

## Active dataset

The two `dataset/13-6-Out*` files are included in that pinned revision and match
the supplied `OpenMP_modified.zip` archive byte-for-byte. Their binary headers
report 8,192 vertices and 98,230 edge entries, within the unchanged recipe
capacities `MAX_VERTEX_NUMBER=26455` and `MAX_EDGE_NUMBER=100573`.

The selected programs set `directed=false`. Their loader opens the incoming
files only for directed graphs, so the four positional argument slots are
retained while the missing `13-6-In*` paths remain unused. No placeholder files
or regenerated graph are needed.

The archive's selected headers and dataset match the public pin. Its four
`src/*.cpp` files only comment out the bank-layout pragmas. Restoring dependencies
requires no such change, so the pinned sources and their pragmas remain intact;
no archive overlay is applied. Hardware execution must still be validated with
the configured Bambu/Ramulator installation.
