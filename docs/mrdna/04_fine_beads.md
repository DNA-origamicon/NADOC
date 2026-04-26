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
- **Column 0 (x)**: radial direction — from axis toward backbone
- **Column 1 (y)**: azimuthal tangent
- **Column 2 (z)**: helix axis tangent (5′→3′)

So the O bead sits **1.5 Å along the radial direction** from the DNA
bead — i.e. on the same radial ray as the backbone, further from the axis.

```
O bead position = DNA bead pos + 1.5 Å × radial_hat
                = fwd-rev centroid + 1.5 Å × radial_hat
```

The DNA→O bond is a rigid-body orientation constraint enforced during ARBD
simulation by a stiff harmonic bond.  The DNA-O vector encodes the current
twist phase of that bp.

---

## Bead Names in PSF/PDB

| Atom name | Particle type name | Physical meaning |
|-----------|--------------------|-----------------|
| `DNA` | `D` | Base-pair centroid (fwd-rev average at 1 bp resolution) |
| `O` | `O` | Orientation indicator, 1.5 Å radially from DNA bead |

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

Key mapping:
- Each `DNA` bead represents one **base pair** (one FORWARD and one REVERSE
  nucleotide).
- The FORWARD backbone position is extracted from the DNA bead's radial
  direction relative to the ideal helix axis.
- The REVERSE backbone position is reconstructed by rotating the forward
  radial by the minor-groove angle (150°).
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

`nuc_pos_override_from_mrdna` reads the **initial fine PDB**
(`{name}-2.pdb` or similar) to assign beads to helices by perpendicular
distance to the known helix axis lines.  The DCD then provides the
simulation trajectory.  The initial PDB is in the NADOC coordinate frame
(no transformation applied during dry_run).
