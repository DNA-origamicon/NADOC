# exp55 — `2hb_1xT` extra-base orientation phase space

This experiment compiles the two reciprocal extra-base thymines in the archived
`2hb_1xT` NAMD trajectories into publication-ready two-angle phase-space plots.

## Primary observable

The orientation is not inferred from an arbitrary ring normal. Each residue is rigid-fit
to the same atom template used by the builder, then permuted with the exact Full-view slab
basis from `crossoverExtraSlabQuaternion`:

```
slab basis = [template-y, template-z, template-x]
```

The plotted direction is the directed slab-face normal (mesh local `+Y`, template `+Z`).
For every frame it is resolved in a stable local two-helix basis:

```
e_ih   = helix(min id) -> helix(max id)
e_ax   = increasing-bp helix axis, perpendicularized against e_ih
e_perp = e_ih x e_ax
azimuth = atan2(n . e_perp, n . e_ih)     [-180, 180] degrees
polar   = acos(n . e_ax)                  [0, 180] degrees
```

The C1′ positional sphere is exported and plotted separately. It is a positional control,
not a substitute for slab orientation.

## Included archive data

- Replica A: job `29c5b267380f`, 200 ns unrestrained (`k0`) production.
- Replica B prelude: job `7d5937e569c6`, the archived 69.81–82.06 ns tail.
- Replica B continuation: job `4c0ba3a85587`, 800 ns unrestrained production starting
  from the prelude endpoint.

All are sampled at a common 200 ps interval. Restrained ENM/MGHH setup and short protocol
test DCDs are recorded in `data/archive_inventory.json` but excluded from the ensemble.

Frames must pass the exp53 integrity criteria: at least 90% global pairing, both flanking
C1′ pairs in 8–13 Å, both insert linker bonds in 1.2–2.2 Å, and template-fit RMSD no more
than 1.5 Å. Only contiguous valid windows of at least 25 samples (5 ns at this sampling)
are plotted.

## Reproduce

```bash
uv run python experiments/exp55_2hb_extra_base_orientation/run.py all
```

The archive is only read. Derived metrics and CSV data are written to `data/`; PNG and PDF
figures are written to `plots/`.

## 24-helix comparison

The large-bundle comparison reuses the existing exp53 metric cache for all 338 extra
bases. The cached landmark coordinates reconstruct the exact representation-aligned slab
frame, so the 181 GB DCD does not need to be reread:

```bash
uv run python experiments/exp55_2hb_extra_base_orientation/run_24hb.py
```

The density gives every crossover unit total weight, corrects bins for spherical solid
angle, and bootstraps crossovers (not frames). Reciprocal lower-bp and higher-bp sides are
reported separately; 20 inserts without an adjacent reciprocal insert remain visible as a
separate group.

Subpopulation and flanking-sequence analysis:

```bash
uv run python experiments/exp55_2hb_extra_base_orientation/analyze_24hb_subpopulations.py
```

This analysis distinguishes fixed helix-ID coordinates from a chemical 3′→5′ hop frame,
then tests source/destination flank identity by permutation within lattice-edge × helical-
phase strata. This prevents traversal polarity and crossover geometry from being mistaken
for sequence-dependent conformations.

Full-ensemble traversal-aligned density figures:

```bash
uv run python experiments/exp55_2hb_extra_base_orientation/render_24hb_full_ensemble.py
```

This final rendering uses all 160,333 stable extra-base/frame observations. Each
crossover's observations sum to unit mass before pooling, so every sampled frame remains
visible without allowing sites with more valid frames to dominate the density.

Representative molecular pair audit:

```bash
uv run python experiments/exp55_2hb_extra_base_orientation/visualize_24hb_pair_orientations.py
```

This reads four selected stable frames from the archived 24hb DCD and creates local,
Molecular-Placement-Audit-style views at approximately 160°, 121°, 90°, and 60° pair
separation. Lower-bp inserts and normals are blue, higher-bp inserts and normals are
orange, and five neighboring base-pair levels are gray. The exported local PDB and BILD
files can also be reopened interactively in ChimeraX.

For interactive selection rather than this fixed four-panel export, open **Help →
Extra-Base Metrics Audit** in NADOC. Its trajectory sample viewer exposes all 338
crossovers and all 509 sampled frames from the registered `24hb_1xT` source, can add
reciprocal partners automatically, and renders the measured pose as an orbitable atomistic
or schematic 3D view. See
[`docs/extra_base_sample_audit.md`](../../docs/extra_base_sample_audit.md).
