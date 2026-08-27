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
configuration_print_energy = false
print_initial_energy = false
no_stdout_energy = true
verlet_skin = 0.40
```

The managed runner adds these settings only for the custom adaptive build. The
energy settings avoid redundant CPU force-field passes at startup and while
writing restart configurations; energy sampling still occurs at the requested
positive step intervals. Restart configurations retain the standard three-value
`E =` header with zero placeholders, which oxDNA does not read on restart.

Compact cell construction uses a linear histogram → exclusive scan → scatter
pipeline. This replaces the first implementation's per-rebuild particle sort and
per-cell binary searches, at the cost of one additional integer counter per cell.

## Wide CUDA particle indices

The custom build also removes upstream oxDNA's packed 22-bit CUDA particle index
(the former 4,194,303-particle ceiling). Position `.w` now stores the complete
signed base type, while particle identity is carried in a separate signed 32-bit
array and permuted alongside positions during Hilbert sorting. This preserves
special DNA3/RNA base types such as `±300` rather than trading their 10-bit field
for a wider packed index.

The practical representation limit is now `INT_MAX` particles; memory and CUDA
launch limits will be reached much earlier. The persistent cost is 4 bytes per
particle, with another 4 bytes per particle only when Hilbert sorting is enabled.
On a 60-million-particle H200-scale system that is about 229 MiB persistent (and
229 MiB temporary with sorting), small relative to the neighbor and force arrays.

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

## BigO runtime scaling

The fully sequenced 14,112-nt BigO periodic part exposes the runtime behavior at
larger scale. On the RTX 2080 Super, 1,000-step runs showed:

| BigO repeats | nucleotides | original corrected runtime | optimized runtime |
|---:|---:|---:|---:|
| 8 | 112,896 | 10.21 ms/step | 4.30 ms/step |
| 16 | 225,792 | 24.07 ms/step | 11.37 ms/step |
| 32 | 451,584 | — | 22.04 ms/step |

At 16 repeats, `verlet_skin = 0.40` was the measured optimum: 0.35, 0.45, and
0.50 produced 12.51, 11.89, and 11.74 ms/step respectively. The optimized 16→32
curve is effectively linear (1.94× runtime for 2× particles). Further skin tuning
has crossed into diminishing returns; the next material gain would require force
kernel or neighbor representation redesign rather than another scalar setting.

## Capacity projections with wide indices

The optimized 16→32 BigO measurements add about 29 MB of whole-device CUDA usage
per repeat. Projections below reserve 15% of nominal VRAM and are planning
estimates, not successful allocations on those GPUs:

| target | usable VRAM assumption | memory-only BigO estimate | index-limited? |
|---|---:|---:|---:|
| RTX 3080 Ti 12 GB | 10.2 GB | ~345 repeats / 4.87 Mnt | no |
| Alpine H200 35 GB MIG | 29.8 GB | ~1,020 repeats / 14.4 Mnt | no |
| Alpine H200 71 GB MIG | 60.4 GB | ~2,080 repeats / 29.3 Mnt | no |
| Alpine H200 141 GB | 119.9 GB | ~4,130 repeats / 58.3 Mnt | no |

The separate 32-bit particle identity array removes the former ×297/4.19 Mnt
address boundary. These estimates are now VRAM-limited rather than index-limited.
Alpine currently offers full 141 GB H200s and 71 GB/35 GB MIG profiles, so the
requested GRES determines which memory-only projection applies. A remote oxDNA
submission path is not currently implemented in NADOC; Alpine/SLURM submission is
available only for the atomistic MD pipeline.
