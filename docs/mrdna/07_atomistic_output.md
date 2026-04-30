# Stage 6 — Atomistic Output

There are two distinct paths from fine-bead geometry to all-atom structure:
mrdna's internal `generate_atomic_model()` (used for NAMD), and NADOC's
bridge functions (used for GROMACS via CHARMM36).

---

## Path A: mrdna generate_atomic_model()

Called after the fine simulation; generates a NAMD-ready all-atom PDB/PSF.

### How It Works

1. Switches the SegmentModel from bead mode to strand mode
   (`self.children = self.strands`).
2. For each strand, iterates contour positions corresponding to each
   nucleotide.
3. Calls `seg._generate_atomic_nucleotide(c, is_fwd, seq, scale)` which:
   - Evaluates `contour_to_position(c)` → backbone position
   - Evaluates `contour_to_orientation(c)` → local frame
   - Builds sugar-phosphate backbone and nitrogenous base using rigid-body
     templates relative to the local frame
   - Applies a `scale` factor to backbone geometry (default 1.0)
4. Links consecutive nucleotides via O3′–P bonds.

### Coordinate Origin

Atom positions come directly from the fine-bead spline.  For B-DNA
templates the phosphorus atom is placed at approximately
`contour_to_position + template_offset`, where `template_offset` places P
at ~8–10 Å from the helix axis (matching canonical B-DNA geometry).

### Output Files

Written by `generate_atomic_model` + NAMD prep:
- `{name}.pdb` — all-atom coordinates (Å)
- `{name}.psf` — NAMD topology

These are **not compatible with GROMACS CHARMM36** (different atom naming,
residue names, and connectivity conventions).  See Path B.

---

## Path B: NADOC Bridge Functions

NADOC provides three bridge functions that read mrdna output and
produce a `nuc_pos_override` dict, which is then consumed by
`build_atomistic_model(design, nuc_pos_override=override)`.

| Function | Reads from | Use case |
|----------|-----------|----------|
| `nuc_pos_override_from_mrdna_coarse` | Coarse PSF + DCD/PDB | 0-step or coarse-stage relaxation |
| `nuc_pos_override_from_mrdna` | Fine PSF + DCD (fine stage, DNA beads) | Standard fine-stage pipeline |
| `nuc_pos_override_from_arbd_strands` | Fine PSF + DCD (with rigid-body alignment) | Large-deformation structures (U-shapes, etc.) |

### What the Override Dict Contains

```python
override = {
    (helix_id, bp_index, 'FORWARD'): np.array([x, y, z]),  # nm
    (helix_id, bp_index, 'REVERSE'): np.array([x, y, z]),  # nm
    ...
}
```

Positions are in **nm** (NADOC units).  Each value is the desired CG
backbone position for that nucleotide before `_atom_frame` applies its
atomistic corrections.

### How build_atomistic_model Uses the Override

```python
# In build_atomistic_model (atomistic.py):
if nuc_pos_override is not None:
    cg_pos = nuc_pos_override.get((h_id, bp, dir_str))
    if cg_pos is not None:
        nuc_pos = dataclasses.replace(nuc_pos, position=cg_pos)

# Then:
origin, R = _atom_frame(nuc_pos, direction,
                         axis_point=axis_pt,
                         helix_direction=helix.direction)
```

`_atom_frame` then:
1. Computes the outward radial direction from `nuc_pos.position − axis_pt`
2. Renormalises to `_ATOMISTIC_P_RADIUS = 8.86 Å` (0.886 nm)
3. Applies REVERSE strand P azimuthal correction (±58.2° or −1.8°)
4. Applies `_ATOMISTIC_PHASE_OFFSET_RAD = −32°` rigid-body rotation

The net result is that the override position's **angular direction** is
used; its radius is replaced by 8.86 Å.

---

## Coordinate Conversion Table

| Quantity | mrdna / ARBD | NADOC internal | Atomistic P (final) |
|----------|-------------|----------------|---------------------|
| Units | Å | nm | nm |
| FORWARD backbone radius from axis | 2.59 Å (centroid) | 10.0 Å (1.0 nm) | 8.86 Å (0.886 nm) |
| REVERSE backbone radius from axis | 2.59 Å (centroid) | 10.0 Å (1.0 nm) | 8.86 Å (0.886 nm) |
| Frame origin | helix arm centroid | helix axis start | helix axis at bp |

---

## Why mrdna Atomistic PDB Cannot Be Used with GROMACS CHARMM36

mrdna's `generate_atomic_model()` produces atoms in mrdna's own naming and
connectivity conventions (not GROMACS-compatible CHARMM names).  Trying to
run this PDB through GROMACS pdb2gmx typically yields:

```
Epot = 9×10²⁷  Fmax = inf
```

because bond lengths and atom names do not match the CHARMM36 residue
database.  Always use the NADOC bridge path (`build_atomistic_model` +
`_build_gromacs_input_pdb`) for GROMACS production runs.
