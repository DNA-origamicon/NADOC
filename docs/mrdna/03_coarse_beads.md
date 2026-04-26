# Stage 2 — Coarse Bead Model

The coarse stage is the first simulation pass.  It captures large-scale
shape changes (bending, global twist) using a small number of beads per
helix, which makes the simulation fast.

---

## What Is a Coarse Bead?

A coarse DNA bead represents a **group of up to 5 base pairs** (default
`max_basepairs_per_bead = 5`) as a single point particle.

It is **not** at the helix axis. It is at the `contour_to_position` value
of the segment spline, which for ideal B-DNA input is the **fwd-rev
backbone centroid**, located **~2.59 Å from the true helix axis** in the
direction that bisects the minor groove.

---

## Bead Generation

`SegmentModel.generate_bead_model(max_basepairs_per_bead=5,
local_twist=False)` iterates over each Segment and calls
`_generate_beads()`, which:

1. Decides how many bp to group together (at most 5).
2. Computes the center contour position `s` of each group.
3. Calls `_generate_one_bead(s, nts)`:

```python
def _generate_one_bead(self, contour_position, nts):
    pos = self.contour_to_position(contour_position)
    bead = SegmentParticle(Segment.dsDNA_particle, pos,
                           name="DNA", num_nt=nts, ...)
    self._add_bead(bead)
    return bead
```

No orientation bead is created when `local_twist=False`.

---

## Coarse Bead Properties

| Property | Value |
|----------|-------|
| Particle name in PSF/PDB | `DNA` |
| Particle type | `D` (dsDNA_particle) |
| Position | `contour_to_position(s)` — fwd+rev centroid, ~2.59 Å off-axis |
| Orientation bead | **None** (`local_twist=False`) |
| Beads per 42-bp helix | **8** (⌊42/5⌋ + boundary beads) |
| Units | Å throughout |

---

## Bead Count Formula

For a DoubleStrandedSegment of `num_bp` bp, internal beads span the
range `[eps, 1−eps]` in contour space with spacing ≈ `max_bp/num_bp`.
A single helix arm of 42 bp gives approximately:

```
42 bp / 5 bp·bead⁻¹ = 8.4 → 8 interior beads
```

Boundary beads at segment-segment junctions (intrahelical connections,
crossovers) get one extra bead each at contour 0 and/or 1.  A fully
interior arm adds 0–2 junction beads depending on whether its neighbours
are already covered.

---

## Position Relative to Helix Axis — Derivation

For ideal B-DNA with HELIX_RADIUS R = 10 Å and minor-groove angle θ = 150°:

```
fwd_pos  = axis + R [cos φ,    sin φ,    0]
rev_pos  = axis + R [cos(φ+θ), sin(φ+θ), 0]
centroid = axis + (R/2) · [cos φ + cos(φ+θ),  sin φ + sin(φ+θ),  0]

|centroid − axis| = R · |cos(θ/2)| = 10 · cos(75°) = 10 · 0.259 = 2.59 Å
```

The centroid direction bisects the forward and reverse radials.  Because
the helix twists, this direction rotates at the same rate as the backbone,
so the coarse bead trajectory is itself a helix of radius 2.59 Å around
the main helix axis.

---

## Spline Tangent Error from Off-Axis Position

Because the coarse beads trace a 2.59 Å helix around the axis, the
position spline's tangent direction is **not exactly the helix axis**.
For a 42-bp helix (total length 140.3 Å, centroid radius 2.59 Å):

```
tangent angle from axis ≈ arctan(2π · 2.59 / 140.3) ≈ 6.6°
```

This 6.6° tilt causes a small error when `nuc_pos_override_from_mrdna_coarse`
projects the ideal radial direction onto the plane perpendicular to the
spline tangent.  The resulting radial direction can have a component along
the helix axis of `sin(6.6°) ≈ 0.115`, displacing override positions by up
to `0.115 × HELIX_RADIUS = 1.15 Å` axially per bp.  (See
`08_nadoc_integration.md` for the full round-trip error analysis.)

---

## Force Field (Coarse Stage, local_twist=False)

Bonded (along the same helical arm):
- **WLC bond** between consecutive DNA beads: harmonic at short range,
  worm-like chain repulsion at large extension.
- **Angle potential** restraining bending at each triplet of DNA beads;
  persistence length = 50 nm (dsDNA canonical).

Non-bonded:
- **Debye-Hückel** electrostatic (pre-tabulated on a grid; Debye length
  set from salt concentration, default ~1 nm).
- **Excluded volume** (soft repulsion, also grid-tabulated).

No torsional potential is applied without orientation beads.

---

## PSF/PDB Written by dry_run=True

When `model.simulate(name, dry_run=True, num_steps=0)` is called, mrdna
writes `{name}.psf` and `{name}.pdb` with the current bead model.

For the coarse stage (the default first call) these files contain:
- One `DNA` bead per ~5-bp group, at the fwd-rev centroid position (~2.59 Å off-axis)
- No `O` orientation beads
- Coordinates in **Å**, in the original NADOC coordinate frame (no transformation applied)

The PSF defines NAMD-style topology: ATOM entries with bead index, type,
charge, mass.  The PDB gives their 3-D positions.

---

## Output → Input for Next Stage

After coarse ARBD simulation, `update_splines` reads the relaxed bead
positions from the restart file and re-fits the segment position splines.
The fine-stage `generate_bead_model(max_bp=1, local_twist=True)` then
evaluates these updated splines at every-bp contour positions to place the
1 bead/bp fine model at the coarse-relaxed geometry.
