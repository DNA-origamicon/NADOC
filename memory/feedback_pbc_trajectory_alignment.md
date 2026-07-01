---
name: MD trajectory PBC correction — diagnostics and algorithm lessons
description: How to detect raw vs pre-processed trajectories; why median centroid beats mean; sequential unwrap chain error behavior
type: feedback
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
## Use "atoms moved by sequential unwrap" as the trajectory quality signal

Counting atoms whose position changes > 3 Å after `_unwrap_min_image` is the correct way to distinguish a `trjconv -pbc whole` pre-processed trajectory from a raw GROMACS output:
- `view_whole.xtc`: 0 atoms moved at every frame
- Raw `prod_best.xtc`: 0–307 atoms moved depending on frame

**Why:** P-P consecutive pairs in the raw file can have distances of 8–15 nm when a strand crosses the periodic boundary. Sequential unwrap fixes these, but each correction "moves" that atom. A pre-processed file already has molecules whole, so unwrap moves nothing.

**How to apply:** Use this as the `_load_sync` PBC quality check, not P-P gap ranges (which confound strand boundaries with wrapping artifacts).

---

## Use median, not mean, for the dynamic centroid in `_seek_sync`

`_c_box = np.median(p_box[rigid_mask], axis=0)` is more robust than `p_box.mean(axis=0)`.

**Why:** At late frames of raw trajectories, sequential unwrap can misplace a chain of atoms (chain error from one wrong atom propagating to all subsequent atoms in a strand). With 307/948 atoms relocated at frame 700 of `prod_best.part0003.xtc`, the mean centroid Y-coordinate jumped 2 nm (5.1 → 7.2 nm), shifting ALL atoms 20 Å in p_nm. The median (dominated by the ~70% correctly-placed atoms) stayed stable. This reduced the RMSD spike from 22 Å → 16 Å.

**How to apply:** Always use the rigid-mask median for `_c_box` in `_seek_sync`. The non-rigid (ssDNA) atoms are excluded from the median because they can be anywhere in the box.

---

## The per-atom design-eq nearest-image correction fails for 90° rotational diffusion

After ~73 ns, a 10hb bundle can rotate ~28° (RMS) with individual frames up to ~90°. At 90° rotation, peripheral atoms move up to 4.4 nm from their design positions. For a box with half-Y = 4.39 nm, some of these are near or over the nearest-image threshold — the correction cannot distinguish a genuine large thermal displacement from a PBC image error.

**Why this matters:** Kabsch rotation can still work correctly if the pre-Kabsch RMSD is moderate (< ~30 Å), because large rotational displacements are coherent across many atoms and the SVD averages them out. The failure mode at frames 680/700 was caused by the centroid bias (above), not by individual atom misimaging.

**How to apply:** For trajectories > ~50 ns in small boxes, expect RMSD_rigid of 10–16 Å instead of 7–9 Å due to genuine rotational drift. This is not a code bug — it's real structural displacement that Kabsch corrects only partially because thermal fluctuations dominate at large rotations. Recommend `view_whole.xtc` extended to cover the full run.

---

## Do not confuse strand-boundary P-P gaps with PBC wrapping artifacts

After `_unwrap_min_image`, all large gaps (> 1 nm) in consecutive P-P distances are **strand boundaries** — the unwrapper left them uncorrected by design. This means the post-unwrap gap count is NOT a useful diagnostic for raw vs pre-processed trajectories: both show the same number of strand-boundary gaps.

**How to apply:** Check pre-unwrap raw P-P distances (> half-box range indicates wrapping) OR count atoms moved by the unwrapper. Do not check post-unwrap gaps.
