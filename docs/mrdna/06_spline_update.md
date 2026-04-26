# Stage 5 — Reading Simulation Output and update_splines

After each ARBD run the relaxed bead positions must be fed back into the
SegmentModel so that the next stage starts from the coarse-equilibrated
geometry.

---

## Reading Restart Coordinates

`read_arbd_coordinates(fname)` in `mrdna/arbdmodel/submodule/coords.py`
reads the plain-text restart file:

```
0   x0   y0   z0
1   x1   y1   z1
...
```

Returns a `(num_beads, 3)` numpy array in **Å**.

---

## update_splines

```python
model.update_splines(coordinates)
```

1. **Distribute bead coordinates** to their parent Segments via the
   `Location` objects stored on each bead.

2. **Re-fit position spline** for each Segment:
   ```python
   tck, u = interpolate.splprep(new_coords.T, u=contours, s=0, k=1)
   seg.position_spline_params = (tck, u)
   ```
   Contour positions are kept fixed; only the 3-D coordinates of the knots
   change.

3. **Re-fit orientation spline** (if present) using quaternion slerp through
   the O-bead vectors recovered from `DNA_pos → O_pos` differences.

After `update_splines`, `seg.contour_to_position(s)` evaluates the new
spline and returns positions that now reflect the **simulated, relaxed**
geometry.

---

## What Changes Between Stages

| Before update | After update |
|---------------|-------------|
| Spline through ideal input centroids (2.59 Å off-axis, perfect helix) | Spline through ARBD-relaxed positions (may be bent, twisted, compressed) |
| Coarse beads at their starting positions | Coarse beads at equilibrated positions |

This is the mechanism by which coarse-stage shape information is passed to
the fine stage: the fine bead generator evaluates the *updated* spline at
every-bp contour positions.

---

## DCD Trajectory Alternative

For analysis the DCD trajectory (all frames) can be read via MDAnalysis:

```python
import MDAnalysis as mda
u = mda.Universe('stem-0.psf', 'output/stem-0.dcd')
for ts in u.trajectory:
    positions = u.atoms.positions   # (N_beads, 3) Å, current frame
```

The NADOC bridge functions `nuc_pos_override_from_mrdna` and
`nuc_pos_override_from_mrdna_coarse` use this interface to read a specific
frame (default: last frame, `frame=-1`) from the DCD.

---

## Coordinate Frame After Simulation

ARBD may translate or rotate the system over the course of a simulation due
to random Brownian kicks (there is no center-of-mass fixing by default).

`nuc_pos_override_from_arbd_strands` handles this by performing a
**rigid-body alignment** of the DCD frame back to the initial PDB frame:

```python
rot, _ = Rotation.align_vectors(dna_init_pos - center_init,
                                 dna_sim_pos  - center_sim)
dna_aligned = rot.apply(dna_sim_pos - center_sim) + center_init
```

`nuc_pos_override_from_mrdna_coarse` does **not** align — it uses only the
**axial projection** to assign bp indices (which is rotation-invariant) and
reconstructs override positions from the ideal axis formula (which is also
rotation-invariant). Global translation would shift bp assignments, but
ARBD's Brownian motion is typically small compared to the 3.4 Å inter-bp
rise.
