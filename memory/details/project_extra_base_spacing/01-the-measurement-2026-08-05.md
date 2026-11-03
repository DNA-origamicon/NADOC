# The measurement (2026-08-05) — supporting detail

[Topic head](../../project_extra_base_spacing.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## The measurement (2026-08-05)

Archived unrestrained NAMD production trajectories, two **matched-control** series — designs
identical apart from their crossover inserts:

| series | helices | crossovers | carrying inserts |
|---|---|---|---|
| `24hb_{0,1,2}xT` | 24 | 384 | 338 |
| `6hbx100_{noT,1xT,2xT}` | 6 | 66 | 60 |

Mean nearest-neighbour interhelical distance, **matched MGHH-only stage** (the only apples-to-apples
comparison — see the equilibration trap below):

| extra bases | 6hbx100 | 24hb | Δ vs 0 |
|---|---|---|---|
| 0 | 24.02 Å | 23.58 Å | — |
| 1 (T) | 24.95 Å | 24.14 Å | +0.93 / +0.56 |
| 2 (TT) | 25.34 Å | 24.32 Å | +1.32 / +0.74 |

**Sub-linear**: the second inserted base adds roughly a third of what the first does. The slack
absorbs into the loop conformation rather than pushing helices apart. Do NOT extrapolate linearly
past 2 — the shipped table clamps instead.

**The small bundle expands ~1.7× more than the large one** (+0.93 vs +0.56 for one base). A
6-helix tube is laterally soft; a 24-helix block's interior helices are pinned by neighbours on
every side. So the "per extra base" number is not a universal constant — it is bundle-stiffness
dependent. The shipped table averages the two; per-lattice-size deltas were considered and
rejected as making the display depend on helix count.

## Method (`scripts/measure_interhelical_spacing.py`)

```bash
uv run python scripts/measure_interhelical_spacing.py \
  --psf <pkg>/<stem>.psf --pdb <pkg>/<stem>.pdb --dcd <pkg>/output/<stem>_..._k0.dcd \
  --n-helices 24 --label 24hb_2xT
```
Archived job packages live under `/media/jojo/Archive/nadoc_jobs/<job>/package/<stem>_namd_solvated/`.
Use a **free** stage only — `_k0` production or `MGHH_only`; anything with `ENM` in the name is
restrained to the built geometry and will just report the lattice back at you.


C1′ atoms only. Reference = the NADOC-built DNA-only PDB in the package. **Cluster the MIDDLE
axial slab into helices, then propagate that labelling outward slab by slab**, seeding each slab's
k-means from its solved neighbour. A single global 2-D projection is NOT enough — over a 400–500 Å
bundle even mild bending smears adjacent helices together, and the first attempt silently merged
helix pairs and split others (the tell: "neighbour" pairs at 8 Å in a 22.5 Å lattice).

Two more things that were load-bearing:

- **Refine each slab-helix centroid from its duplex core only** (atoms within `r_cut` of the
  centroid), then re-assign. Inserts sit *between* helices and otherwise drag the k-means centroid
  off-axis — worse at 2 inserts than 1, which would have manufactured exactly the trend being
  looked for. A starved-cluster repair (retire the starved centre, split the fattest) is what
  finally made `24hb_2xT` converge.
- **Minimum-image every slab-helix before averaging.** `wrapAll on` in these runs, and the box
  cross-section (83 × 89 Å) barely exceeds the bundle, so the DNA is genuinely split across the
  periodic boundary.

Every run self-validates (balanced occupancy, no sub-15 Å reference "neighbours") and reports
failure rather than averaging garbage.
