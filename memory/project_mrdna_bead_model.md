---
name: mrdna fine-stage bead model — critical insight for CG→atomistic override
description: Documents the 1-bead-per-bp structure of the mrdna ARBD fine stage, why per-strand splines failed because of it, and the correct per-helix approach. Read before touching nuc_pos_override_from_arbd_strands.
type: project
originSessionId: 96f9c7f1-a2dc-42fd-ade8-1e21c39596f9
---
# mrdna Fine-Stage Bead Model

## The Core Fact (read this first)

**mrdna ARBD fine stage has exactly 1 DNA bead per BASE PAIR — NOT 1 per nucleotide.**

For U6hb (5036 nt = 2518 bp): the PSF has **2518 DNA beads** and 2518 O beads (total 5036 atoms).
Each DNA bead represents the FORWARD strand backbone position for that base pair.
Each O bead is an orientation indicator at ~1.5 Å from the DNA bead.

There is **no separate bead for the REVERSE strand backbone.** The REVERSE backbone position must
be reconstructed synthetically using the minor-groove rotation from the FORWARD bead position.

```
(helix axis) ← HELIX_RADIUS → [DNA bead] ← FORWARD backbone of bp N
                                            |
                              rotate 150°  v
                              (axis)  ← HELIX_RADIUS → [reconstructed REVERSE]
```

## Why Per-Strand Splines Failed

The first implementation of `nuc_pos_override_from_arbd_strands` tried to:
1. Classify each DNA bead as FORWARD or REVERSE by comparing its radial angle to the expected
   FORWARD and REVERSE angles at that bp position
2. Group beads by strand (5'→3' order) using the direction-classified keys
3. Fit a per-strand CubicSpline through those grouped beads

**This failed catastrophically** because:
- ALL beads are at FORWARD positions; the "direction assignment" misclassified ~50% of them
- Misclassified beads left FORWARD nucleotides without any bead data
- Multiple nucleotides got assigned to the same spline t-value
- The DCD frame also has PBC drift: positions up to 138 nm from origin (correct for a 139 nm
  tall structure like U6hb, but not obviously so from the diagnostic output)

**Symptom**: 75 duplicate positions in override dict, max position 138 nm, LJ = 2.1e37 at EM step 0.

**Diagnostic that revealed it**:
```python
pos_tuples = [tuple(np.round(v, 4)) for v in vals]
from collections import Counter
dups = [(p, c) for p, c in Counter(pos_tuples).items() if c > 1]
print(f"Duplicate positions: {len(dups)}")  # → 75
print(f"First dup: {dups[0]}")              # → same coord assigned to 17 nucleotides
```

## What Works: Per-Helix Spline

The correct approach (implemented in commit 84e8148, 2026-04-24):
1. Read initial fine PDB — this IS in NADOC coordinate frame
2. Use initial PDB positions for bead→helix assignment (not DCD positions)
3. Align DCD positions to NADOC frame via rigid-body fit (handles PBC drift)
4. Deduplicate: 1 bead per (h_id, bp_idx), keep closest to helix axis
5. Per-helix CubicSpline through aligned bead positions
6. FORWARD nucleotides: spline position directly (bead ≈ FORWARD backbone)
7. REVERSE nucleotides: axis + `_rotate(fwd_rad, axis_hat, BDNA_MINOR_GROOVE_ANGLE_RAD)`
8. Include crossover keys (don't exclude them — that's the whole point vs. the old function)

**Key: no direction assignment step at all. Each bead → (h_id, bp_idx) only.**

## Validation Result

- Baseline (ideal B-DNA, U6hb, 500-step EM cap): **500 steps, 132 s**
- Phase 3b (CG override, same cap): **14 steps, 8 s** — ratio 0.03×
- Success criterion (>50% step reduction): **PASS by wide margin**

## Watch-Out: "Per-Strand" Terminology

When any future session reads about "per-strand splines" in the roadmap, be aware:
- The CONCEPT of spanning crossover junctions via strand continuity is sound
- The IMPLEMENTATION with mrdna fine-stage data is impossible per-strand, because
  there is only 1 bead per bp (not per strand-nucleotide)
- The current implementation achieves crossover inclusion by a different means:
  simply not excluding crossover keys from the override dict

## If You Need to Debug nuc_pos_override_from_arbd_strands

Run this diagnostic first:
```python
from backend.core.mrdna_bridge import nuc_pos_override_from_arbd_strands
import numpy as np
override = nuc_pos_override_from_arbd_strands(design, psf_path, dcd_path)
vals = np.array(list(override.values()))
print(f"Entries: {len(override)}")
print(f"NaN/Inf: {np.isnan(vals).sum()} / {np.isinf(vals).sum()}")
print(f"Range: {vals.min():.1f} to {vals.max():.1f} nm")
print(f"Mean |pos|: {np.linalg.norm(vals, axis=1).mean():.1f} nm")
from collections import Counter
dups = [(p,c) for p,c in Counter([tuple(np.round(v,4)) for v in vals]).items() if c>1]
print(f"Duplicate positions: {len(dups)}")
```

Good output: 0 NaN/Inf, 0 duplicates, range matches physical structure extent.
Bad output: duplicates > 0, or range far exceeding structure dimensions.

## Key Files

| File | Function |
|------|----------|
| `backend/core/mrdna_bridge.py` | `nuc_pos_override_from_arbd_strands` (per-helix spline, the working approach) |
| `backend/core/mrdna_bridge.py` | `nuc_pos_override_from_mrdna` (per-helix, no spline, excludes crossovers) |
| `backend/core/mrdna_bridge.py` | `nuc_pos_override_from_mrdna_coarse` (per-helix spline, coarse-stage version) |
| `tests/validate_phase3b.py` | EM step-count validation harness |
| `tests/test_mrdna_pipeline.py` | Unit + integration tests for round-trip fidelity |

## Why: Coordinate Frame

Initial fine PDB at `/path/stem-2.pdb` is always in NADOC frame (mrdna writes it from
our coordinates). The DCD at `/path/output/stem-2.dcd` may have PBC drift of many nm.
For U6hb the structure is 139 nm tall, so positions at 138 nm are correct — do NOT
mistake this for a coordinate frame problem. The diagnostic "max pos 138 nm" was a
false alarm during debugging.

The rigid-body alignment (`scipy.spatial.transform.Rotation.align_vectors`) is kept
as a safety measure for structures that DO drift, but for U6hb init≈DCD frame already.
