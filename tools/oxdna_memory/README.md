# oxDNA adaptive CUDA memory build

The opt-in build keeps oxDNA's force-facing edge-list representation unchanged,
but replaces two worst-case allocations:

- the edge array is allocated from the observed edge count with 20% growth headroom;
- the dense neighbor matrix starts at a small capacity, detects overflow without an
  out-of-bounds write, then grows and rebuilds before force evaluation.
- the worst-cell-capacity array is replaced by sorted cell keys, particle IDs, and
  cell offsets.

Build it separately from the pinned upstream control:

```bash
NADOC_OXDNA_ADAPTIVE_MEMORY=1 scripts/build-oxdna.sh
```

Enable adaptive neighbor sizing in an oxDNA input with:

```text
use_edge = true
adaptive_neighbor_list = true
adaptive_neighbor_initial_capacity = 64
adaptive_compact_cells = true
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
| adaptive neighbors | 64 → 142 | 119 initially | ~490 MB steady | 10.344 s |
| + compact cells | 64 → 142 | 119 initially | ~31.5 MB steady | 10.946 s |

Adaptive neighbors alone reduce total allocation by about **6.9×** with flat
runtime. Compact cells reduce estimated steady allocation by about **108×** versus
upstream while making the 10k-step run **4.7% slower**. The initial potential
energy matched exactly in both variants.

These are oxDNA's internally reported allocations, not whole-process NVML usage;
the benchmark also samples whole-device memory around each process.

## Multi-origami scale

The benchmark can tile a valid topology/configuration while preserving all strand
and neighbor indices (`--copies N`). With output discarded, the managed build ran:

| VoltronCoreArm copies | nucleotides | peak device-memory delta |
|---:|---:|---:|
| 2 | 58,926 | 239 MB |
| 10 | 294,630 | 740 MB |
| 30 | 883,890 | 1,287 MB |
| 60 | 1,767,780 | 2,399 MB |

For comparison, two copies on upstream oxDNA consumed a 4,217 MB device-memory
delta. Sixty copies completed ten MD steps on the same 8 GB card.

## Diminishing-return boundary

At 60 copies, the remaining large custom buffers are the 958 MB neighbor matrix
and 521 MB edge list. Exact CSR neighbors could save roughly 500 MB and reducing
edge headroom could save about 87 MB, together less than 25% of measured device
usage. CSR would also require changing every interaction kernel and its coalesced
access pattern. That is a much smaller return than the 17.6× measured two-copy
gain delivered here, so it is intentionally left as a separate speed/kernel
redesign rather than extending this capacity patch.
