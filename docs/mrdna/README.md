# MrDNA Pipeline Reference

These documents describe the full MrDNA multi-resolution simulation pipeline,
from raw nucleotide arrays through coarse-grained relaxation to atomistic output.

## Document Index

| File | Covers |
|------|--------|
| [01_input_arrays.md](01_input_arrays.md) | Stage 0 — input data format, units, coordinate convention |
| [02_segment_model.md](02_segment_model.md) | Stage 1 — SegmentModel, Segments, splines, connections |
| [03_coarse_beads.md](03_coarse_beads.md) | Stage 2 — coarse bead model (5 bp/bead, no twist) |
| [04_fine_beads.md](04_fine_beads.md) | Stage 3 — fine bead model (1 bp/bead, with twist) |
| [05_arbd_simulation.md](05_arbd_simulation.md) | Stage 4 — ARBD rigid-body dynamics engine |
| [06_spline_update.md](06_spline_update.md) | Stage 5 — reading simulation output, update_splines |
| [07_atomistic_output.md](07_atomistic_output.md) | Stage 6 — atomistic model generation from fine beads |
| [08_nadoc_integration.md](08_nadoc_integration.md) | NADOC-specific bridge: coordinate mapping, override path |

## Pipeline at a Glance

```
Nucleotide arrays (N×3 Å, basepair/stack/3prime topology)
        │
        ▼  model_from_basepair_stack_3prime()
   SegmentModel
   DoubleStrandedSegment / SingleStrandedSegment
   Splines through bp-centroid positions
        │
        ├─── COARSE stage ──────────────────────────────────────────
        │    generate_bead_model(max_bp=5, local_twist=False)
        │    → 1 DNA bead / 5 bp  (at fwd-rev centroid, ~2.6 Å off-axis)
        │    → ARBD simulation → update_splines with relaxed positions
        │
        ├─── FINE stage ────────────────────────────────────────────
        │    generate_bead_model(max_bp=1, local_twist=True)
        │    → 1 DNA bead + 1 O bead / bp  (same centroid position)
        │    → ARBD simulation → update_splines with relaxed positions
        │
        └─── ATOMISTIC output ──────────────────────────────────────
             generate_atomic_model()  [mrdna internal]
          OR nuc_pos_override_from_mrdna_*()  [NADOC bridge]
             → full heavy-atom DNA structure
```

## Key Numbers (B-DNA defaults)

| Quantity | Value | Notes |
|----------|-------|-------|
| Rise per bp | 3.4 Å | `DoubleStrandedSegment.distance_per_nt` |
| Helical repeat | 10.44 bp/turn | `DoubleStrandedSegment.helical_rise` |
| Twist per bp | 34.5°/bp | derived from helical repeat |
| O-bead offset | 1.5 Å | `Segment.orientation_bond.r0` |
| Coarse stage timestep | 200 μs (no local_twist) | ARBD Langevin |
| Fine stage timestep | 40 μs (local_twist) | ARBD Langevin |
| All coordinates | Ångströms (Å) | throughout mrdna |
| NADOC coordinates | nanometres (nm) | multiply by 10 to enter mrdna |
