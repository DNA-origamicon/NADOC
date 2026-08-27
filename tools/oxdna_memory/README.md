# oxDNA adaptive CUDA memory build

The opt-in build keeps oxDNA's force-facing edge-list representation unchanged,
but replaces two worst-case allocations:

- the edge array is allocated from the observed edge count with 20% growth headroom;
- the dense neighbor matrix starts at a small capacity, detects overflow without an
  out-of-bounds write, then grows and rebuilds before force evaluation.

Build it separately from the pinned upstream control:

```bash
NADOC_OXDNA_ADAPTIVE_MEMORY=1 scripts/build-oxdna.sh
```

Enable adaptive neighbor sizing in an oxDNA input with:

```text
use_edge = true
adaptive_neighbor_list = true
adaptive_neighbor_initial_capacity = 64
```

The build logs observed/capacity counts and allocation sizes. Compare builds with:

```bash
uv run python scripts/benchmark_oxdna_memory.py INPUT \
  --upstream-bin ~/.local/share/nadoc/engines/oxdna/REV-upstream/bin/oxDNA \
  --adaptive-bin ~/.local/share/nadoc/engines/oxdna/REV-adaptive-memory/bin/oxDNA
```

## VoltronCoreArm baseline

On the 29,463-nucleotide equilibration fixture and an RTX 2080 Super:

| build | neighbor capacity | observed maximum | allocated CUDA memory | 10k steps |
|---|---:|---:|---:|---:|
| pinned upstream | 8,658 | — | 3,393.65 MB | 10.452 s |
| adaptive prototype | 64 → 142 | 119 initially | 481.56 MB before growth | 10.344 s |

The reported startup allocation falls by **7.05×**. The grown matrix adds about
9 MB, leaving the steady allocation near 490 MB (about **6.9× lower**). Runtime was
flat in this first sample. The initial potential energy matched exactly.

The next dominant allocation is the 467.96 MB dense cell array. Compacting it
requires changing neighbor construction, but not the interaction kernels.
