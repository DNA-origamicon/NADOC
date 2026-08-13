# Stage 3 — Fine Bead Model

The fine stage adds per-base-pair resolution and explicit twist tracking.
It starts from the coarse-relaxed segment splines, so it inherits any
large-scale shape changes computed in Stage 2.

---

## What Changes from Coarse

| Property | Coarse (Stage 2) | Fine (Stage 3) |
|----------|-----------------|----------------|
| `max_basepairs_per_bead` | 5 | 1 |
| `local_twist` | False | True |
| DNA beads per 42-bp helix | ~8 | 42 |
| Orientation (O) beads | None | 1 per DNA bead |
| Twist DOF simulated | No | Yes |
| Timestep | 200 μs | 40 μs |

---

## DNA Bead — Fine Stage

One `DNA` bead per base pair.  Position is `contour_to_position(s)` at
the single-bp contour slot, i.e. the same fwd-rev centroid formula as
for coarse beads, just evaluated at every bp rather than every 5 bp.

For a 42-bp straight helix:
- 42 DNA beads, spaced 3.4 Å apart along the axis
- Each bead is 2.59 Å from the helix axis (same offset as coarse)

```
DNA bead position (bp rank k) =
    axis_pt_k + 2.59 Å · bisector_direction(φ_k)
```

where `φ_k = phase_offset + k · twist` is the forward-strand azimuth.

---

## O (Orientation) Bead — Fine Stage

For each DNA bead, one `O` bead is placed:

```python
orientation = seg.contour_to_orientation(s)   # 3×3 rotation matrix
opos = DNA_bead_pos + orientation @ [r0, 0, 0]
```

where `r0 = Segment.orientation_bond.r0 = 1.5 Å`.

The orientation matrix at contour `s` has:
- **Column 0 (x)**: mrDNA orientation reference, recorded by the O bead
- **Column 1 (y)**: nucleotide-backbone projection axis
- **Column 2 (z)**: helix axis tangent (5′→3′)

The O bead therefore records frame x; it is **not itself a phosphate or a
backbone site**. mrDNA's own backmapping applies `DefaultOrientation = Rz(90°)`
before placing nucleotides, so the strand backbone is projected on local ±y.
Treating DNA→O as the backbone radial produces a smooth but approximately
quarter-turn-out-of-phase duplex and places most crossovers on the far side.

```
O bead position = DNA bead pos + 1.5 Å × frame_x
backbone axis   = frame_y = cross(frame_z, frame_x)
```

The DNA→O bond is a rigid-body orientation constraint enforced during ARBD
simulation by a stiff harmonic bond.  The DNA-O vector encodes the current
twist phase of that bp.

---

## Bead Names in PSF/PDB

| Atom name | Particle type name | Physical meaning |
|-----------|--------------------|-----------------|
| `DNA` | `D` | Base-pair centroid (fwd-rev average at 1 bp resolution) |
| `O` | `O` | Orientation-frame x indicator, 1.5 Å from DNA bead |

The PSF has two entries per bp: `DNA` first, then `O`.  Bonds, angles, and
dihedrals in the PSF reference these indices.

---

## Force Field (Fine Stage, local_twist=True)

Bonded:
- **WLC bond** DNA–DNA along the helix (same as coarse, shorter groups).
- **DNA–O bond** (rigid harmonic, r0 = 1.5 Å): keeps each O bead at the
  correct distance from its DNA bead.
- **Twist angle** potential: harmonic angle restraint around each O–DNA–O
  triplet that spans consecutive bp.  The equilibrium angle encodes the
  ideal B-DNA twist (34.5°/bp).  This directly controls the twist DOF.
- **Bend angle** potential: triplet of three consecutive DNA beads;
  persistence length = 50 nm.

Non-bonded: same Debye-Hückel + excluded volume as coarse.

---

## Relationship to the Atomistic Model

After fine-stage simulation, NADOC reads the fine PSF/PDB/DCD via
`nuc_pos_override_from_mrdna` or `nuc_pos_override_from_arbd_strands`.

Current identity-preserving mapping:
- Each `DNA` bead represents one **base pair** (one FORWARD and one REVERSE
  nucleotide).
- `nucleotide_map.json` binds every NADOC nucleotide identity to its exact
  DNA/NAS particle ownership; helix/bp labels are render addresses only.
- The final DNA→O vector and relaxed helix tangent form mrDNA's local frame.
- NADOC converts frame x to backbone y with the same +90° convention used by
  mrDNA's `_generate_oxdna_nucleotide`, then rotates the authoritative native
  strand offsets from the analytic seed frame into the relaxed frame.
- Paired nucleotides share the DNA axis particle but retain separate identities
  and opposite, mate-facing slab/base sites.
- The all-atom template is placed at the corrected P position with the
  −32° phase offset applied by `_atom_frame`.

The fine bead's position is **not** the same as the all-atom P position:

| Position | Distance from axis |
|----------|--------------------|
| Fine DNA bead (fwd-rev centroid) | 2.59 Å |
| Atomistic FORWARD P atom | 8.86 Å (`_ATOMISTIC_P_RADIUS = 0.886 nm`) |
| Atomistic REVERSE P atom | 8.86 Å (same radius, +208.2°) |

The bridge functions handle this transformation explicitly.

---

## Fine-Stage PSF/PDB Used by NADOC

The managed-job decoder does **not** infer identity by nearest-axis assignment.
It reads particle indices from `nucleotide_map.json` and uses the DCD for final
DNA/O frames. The numbered initial Fine PDB is used for particle coordinates and
trajectory unwrapping, but not as the phase reference: intermediate mrDNA restart
PDBs can contain frame discontinuities that create a false slow-wind/large-jump
pattern. The phase reference is the exact analytic frame originally supplied by
`_build_nt_arrays`.
