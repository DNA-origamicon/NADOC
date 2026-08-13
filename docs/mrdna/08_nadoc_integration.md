# NADOC ↔ MrDNA Integration

This document describes how NADOC builds mrDNA models, preserves nucleotide
identity, and reconstructs coarse and Fine trajectories for display.

---

## Building the mrdna Model from a NADOC Design

`mrdna_model_from_nadoc(design)` in `backend/core/mrdna_bridge.py` calls
`_build_nt_arrays(design)` which produces the Stage 0 input arrays.

### Nucleotide Position Formula (_build_nt_arrays)

For each nucleotide at bp index `bp_idx` on helix `h`:

```python
local_i  = bp_idx - h.bp_start
fwd_angle = h.phase_offset + local_i * h.twist_per_bp_rad
angle = fwd_angle  (FORWARD)  or  fwd_angle + groove  (REVERSE)
rad = cos(angle) * x_hat + sin(angle) * y_hat
backbone_ang = (axis_pt + HELIX_RADIUS * rad) * 10.0   # nm → Å
```

where:
- `axis_pt = h.axis_start + local_i * BDNA_RISE_PER_BP * axis_hat` (nm)
- `HELIX_RADIUS = 1.0 nm = 10.0 Å`
- `groove = ±BDNA_MINOR_GROOVE_ANGLE_RAD = ±150°` (sign depends on `h.direction`)
- `x_hat, y_hat` = right-hand perpendicular frame from `_xy_frame(axis_hat)`

For paired bases, the two nucleotide inputs encode one mrDNA base-pair frame.
mrDNA transforms the reverse frame by a local-x 180° rotation before averaging;
NADOC supplies the inverse representation so the transformed frames agree.

---

## xy_frame Convention

Both `geometry.py` (`_frame_from_helix_axis`) and `mrdna_bridge.py`
(`_xy_frame`) compute identical frames:

```python
ref   = [0, 0, 1]
if |dot(axis_hat, ref)| > 0.9:  ref = [1, 0, 0]
x_hat = cross(ref, axis_hat);   x_hat /= |x_hat|
y_hat = cross(axis_hat, x_hat)
```

This ensures the radial formula `cos(angle)*x_hat + sin(angle)*y_hat`
gives the same direction in `_build_nt_arrays`, `nucleotide_positions`
(geometry.py), and `nuc_pos_override_from_mrdna_coarse`.

---

## Crossover Junction Exclusion

`_crossover_junction_keys(design)` returns the set of
`(helix_id, bp_idx, direction_str)` keys at domain-boundary crossover
positions.  These are excluded from the override dict so that
`_minimize_backbone_bridge` can place them using ideal B-DNA geometry
instead of mrdna bead positions (which would place them at two separate
helix radii, breaking backbone continuity).

This describes the older coarse/atomistic override. Managed simulation
visualizations instead retain every real nucleotide and covalent edge through
`nucleotide_map.json`; crossover endpoints are not dropped or independently
rediscovered.

---

## Managed Fine Reconstruction Contract

Fine jobs use an identity-preserving round trip:

1. The job snapshot removes reference geometry before model construction.
2. `_build_nt_arrays` enumerates topology and writes the authoritative analytic
   positions and paired orientation frames used to seed mrDNA.
3. `nucleotide_map.json` records stable nucleotide identity, predecessor,
   successor, pair, render address, and exact DNA/NAS particle bindings.
4. The decoder reads final DNA and O particles by manifest index. It never
   assigns identities using spatial proximity.
5. DNA→O is mrDNA frame x. The nucleotide backbone projection is frame y,
   obtained using mrDNA's documented +90° `DefaultOrientation` convention.
6. The decoder rotates each nucleotide's authoritative native radial offset from
   the analytic seed frame into the relaxed frame. Pair normals, explicit base
   positions, slab tangents, scalar maps, and covalent bonds all use that same
   reconstructed identity record.

The analytic seed frame is essential. Numbered Fine PDBs are intermediate
resolution-stage restarts; using their O frames as the phase baseline can create
artificial stretches of slow twist followed by rotations approaching 180°.

### Crossover interpretation

mrDNA restrains coarse helix-axis particles, not individual phosphate atoms.
Its crossover bond targets are approximately 1.2–1.25 nm between coarse
particles. NADOC backmaps those frames to strand backbone sites, so displayed
covalent crossover lengths should be much shorter than the raw DNA-particle
separation but need not equal native geometry after relaxation.

Use the exact manifest successor edges for validation. Design crossover markers
alone may include non-covalent or under-resolved cases. Useful audits are:

```bash
uv run python scripts/audit_mrdna_slabs.py JOB_ID
uv run python scripts/audit_mrdna_crossover_phase.py JOB_ID
```

Expected invariants include complete identity coverage, mate-facing paired slabs,
no large per-bp phase resets, and a crossover distribution without design-spanning
bonds. Local long bonds remain confidence warnings because a coarse model can
resolve a strained junction without atomistic phosphate detail.

### Rerun policy

- Decoder/display/backmapping changes only: regenerate the display cache; the
  simulation does not need rerunning.
- Input topology, paired seed-frame, particle binding, or force/potential changes:
  rerun the job because the saved trajectory encodes the old physical model.
- Jobs without `nucleotide_map.json` are unsupported legacy runs.

---

## Coarse Override Path: Fixed Implementation

`nuc_pos_override_from_mrdna_coarse` reads the dry-run coarse PSF/PDB and
reconstructs override positions.  For straight helices the formula now
exactly reproduces the direct NADOC path (0.000 Å P-atom RMSD).

Three bugs were identified and fixed (2026-04-24):

### Bug 1 — Out-of-Range Junction Beads

mrdna places one junction bead per helix at contour=1.0, which maps to
`bp_idx = bp_start + length_bp` (e.g. bp=42 for a 42-bp helix).  This
is outside the valid range `[bp_start, bp_start + length_bp − 1]` and
corrupted the spline near the helix end.

**Fix**: skip any bead where `bp_idx < bp_start or bp_idx >= bp_start + length_bp`.

### Bug 2 — Off-Axis Spline Tangent Tilt (~6.5°)

Coarse beads are at the fwd-rev centroid, 2.59 Å from axis, tracing a
mini-helix.  With only ~8 beads per 42-bp helix, consecutive beads rotate
~172.5° in azimuth, causing the 3-D cubic spline tangent to point almost
perpendicular to the helix axis at some positions.  This caused completely
wrong `axis_hat_spline` values and P-atom displacements up to ~12 Å.

**Fix**: project each bead position onto the ideal helix axis before fitting
the spline:
```python
axial_dots = (raw_pos - ax_s).dot(ideal_axis_hat)
raw_pos_on_axis = ax_s + np.outer(axial_dots, ideal_axis_hat)
cs = CubicSpline(bp_idxs, raw_pos_on_axis, ...)
```
For straight helices the projected points are colinear → tangent = ideal_axis_hat.
For globally bent helices the projected feet trace the deformed axis.

### Bug 3 — Wrong Groove Sign for REVERSE-Direction Helices

The REVERSE strand backbone is at `fwd_angle + groove` where `groove = +150°`
for FORWARD-direction helices and `groove = −150°` for REVERSE-direction helices
(set by the helix `direction` field in the NADOC design).  The override was
always using `+BDNA_MINOR_GROOVE_ANGLE_RAD`, placing the REVERSE bead 60°
off (= 150° − (−150°) = 300° → 360°−300° = 60° separation), causing 8.92 Å
P-atom displacement on all REVERSE-direction helices.

**Fix**: use `groove = ±BDNA_MINOR_GROOVE_ANGLE_RAD` based on `h.direction`:
```python
groove = (BDNA_MINOR_GROOVE_ANGLE_RAD
          if h_dir == Direction.FORWARD
          else -BDNA_MINOR_GROOVE_ANGLE_RAD)
rev_rad = _rotate(fwd_rad, axis_hat, groove)
```

---

## Unit Conversion Summary

| Location | Units | Conversion |
|----------|-------|-----------|
| NADOC Design (`axis_start`, positions) | nm | × 10 → Å |
| `_build_nt_arrays` output `backbone_ang` | Å | ÷ 10 → nm |
| mrdna PSF/PDB (`write_pdb`) | Å | ÷ 10 → nm |
| `nuc_pos_override_from_mrdna_coarse` input (`dna_sim_pos`) | Å | ÷ 10 for override values |
| Override dict values | nm | × 10 → Å |
| `build_atomistic_model` internal (`axis_pt`) | nm | — |
| `_atom_frame` (`bb`, `_ATOMISTIC_P_RADIUS`) | nm | — |
| Final atom positions in `Atom` dataclass | nm | × 10 → Å for PDB |

---

## Full Coordinate Flow: Direct NADOC Path

```
NADOC Design
    ↓ geometry.py nucleotide_positions()
NucleotidePosition.position
= axis_pt + HELIX_RADIUS * fwd_radial      (nm, HELIX_RADIUS = 1.0 nm)
    ↓ _atom_frame()
1. e_radial = (position − axis_pt) / |...| = fwd_radial
2. bb = axis_pt + _ATOMISTIC_P_RADIUS * e_radial   (radius → 0.886 nm)
3. REVERSE correction: rotate e_radial by ±58.2° or −1.8°
4. Phase offset: rotate e_radial by −32°
5. origin = final bb                              (nm)
6. R = [−e_radial, e_y, e_z]
    ↓ sugar/base template
All-atom positions = origin + R @ template_offsets   (nm)
```

## Full Coordinate Flow: Coarse Override Path

```
NADOC Design
    ↓ _build_nt_arrays()  (× 10: nm → Å)
mrdna input positions at HELIX_RADIUS = 10 Å from axis
    ↓ model_from_basepair_stack_3prime() → SegmentModel
Segment splines through fwd+rev centroids (2.59 Å from axis)
    ↓ dry_run=True  → write_pdb()
Coarse PSF/PDB: DNA beads at centroid positions (Å, NADOC frame)
    ↓ nuc_pos_override_from_mrdna_coarse()  (÷ 10: Å → nm)
1. Read coarse bead positions (Å) from PDB
2. Assign each bead to nearest helix by axis-line perp distance
3. Compute bp_idx from axial projection
4. Fit CubicSpline through bead positions per helix
5. At each bp: tangent = spline.derivative → axis_hat_spline
              (≠ ideal_axis_hat by ~6.5° for straight helix)
6. Compute ideal_fwd_rad = cos(fwd_angle)*x_hat + sin(fwd_angle)*y_hat
7. Project onto ⊥ plane: perp_comp = ideal_fwd_rad − dot(…)*axis_hat_spline
8. fwd_ang = ideal_axis_pt + HELIX_RADIUS * perp_comp/|perp_comp|  (Å)
9. override = fwd_ang / 10.0                                        (nm)
    ↓ build_atomistic_model(design, nuc_pos_override=override)
Same as direct path from step 1 of _atom_frame above
```

The override position passed into `_atom_frame` should ideally equal
`axis_pt + 1.0 nm * ideal_fwd_rad` but instead equals
`ideal_axis_pt + 1.0 nm * perp_comp/|perp_comp|` where `perp_comp` has
a small axial component due to the spline tangent tilt.  This is the
source of the ~5 Å P-atom RMSD in the coarse round-trip validation.
