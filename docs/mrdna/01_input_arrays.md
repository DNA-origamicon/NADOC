# Stage 0 — Input Arrays

The entry point to mrdna is `model_from_basepair_stack_3prime()` in
`mrdna/readers/segmentmodel_from_lists.py`. It accepts five 1-D or 2-D
numpy arrays, all indexed by **nucleotide index** `i` (0 … N−1).

---

## Arrays

### `coordinate`  — shape (N, 3)

Position of nucleotide `i` in **Ångströms**.

Physically this is the **backbone atom position** — typically the phosphate
or sugar centroid, not the helix axis.  In the NADOC bridge
(`_build_nt_arrays` in `mrdna_bridge.py`) it is placed at

```
position_i = axis_point + HELIX_RADIUS * radial_hat_i      (in Å)
```

where `HELIX_RADIUS = 10.0 Å` (1.0 nm) and `radial_hat_i` is the unit
vector pointing from the helix axis to the backbone at base-pair `i`.

For a straight B-DNA helix the FORWARD strand nucleotide at local index `k`
lands at

```
x = HELIX_RADIUS · cos(phase_offset + k · twist)
y = HELIX_RADIUS · sin(phase_offset + k · twist)
z = axis_start_z + k · RISE_PER_BP
```

and the REVERSE strand partner is rotated by `+150°` (minor-groove angle)
about the same axis point.

### `basepair`  — shape (N,), dtype int

`basepair[i]` = index of the nucleotide paired with nucleotide `i`,
or `−1` if unpaired.

- For dsDNA: every FORWARD nucleotide points to its REVERSE partner and
  vice versa.
- ssDNA overhangs or scaffold loops: `basepair[i] = −1`.
- **Purpose**: identifies which nucleotides form double-stranded helices.

### `stack`  — shape (N,), dtype int

`stack[i]` = index of the nucleotide stacked on the **3′ side** of
nucleotide `i` (i.e. the next nucleotide in the helical column
toward the 3′ end), or `−1` if there is no stack.

- A contiguous run of stack bonds on both strands of a helix defines one
  helical **Segment**.
- Stack bonds must obey: `basepair[stack[i]] == basepair[basepair[i]]`
  (the partner of my stack partner is the partner of my partner's stack).
  mrdna silently drops stacks that violate this.
- At crossover junctions the stack bond is broken → two separate Segments.

### `three_prime`  — shape (N,), dtype int

`three_prime[i]` = index of the nucleotide connected via a
phosphodiester bond to the **3′ end** of nucleotide `i`, or `−1` if `i`
is a 3′ terminus.

- Defines strand topology (which nucleotides belong to the same strand
  in the correct 5′→3′ order).
- Used to build ARBD bond lists and PSF chain entries.
- Distinct from `stack`: `three_prime` can cross helix boundaries
  (crossover), `stack` cannot.

### `orientation`  — shape (N, 3, 3), optional

`orientation[i]` is a 3×3 rotation matrix that maps from the global frame
to the local nucleotide frame at nucleotide `i`.

- **Column 0 (x-axis)**: radial direction — from helix axis toward the
  backbone (outward).
- **Column 1 (y-axis)**: azimuthal direction — tangent to the backbone
  circle at this bp (orthogonal to x and z).
- **Column 2 (z-axis)**: helix axis tangent (5′→3′ direction).

When provided, mrdna uses it to detect base-stacking pairs (`find_stacks`)
and to generate per-nucleotide twist states for the spline.

In the NADOC bridge this is the `_orientation_matrix(rad, axis_hat)` output:
columns are `[radial_hat, azimuthal_hat, axis_hat]`.

---

## Coordinate Convention Summary

| Quantity | Value | Unit |
|----------|-------|------|
| All mrdna coordinates | Å (Ångströms) | — |
| NADOC internal coordinates | nm | multiply by 10 to enter mrdna |
| FORWARD backbone offset from axis | 10.0 Å | HELIX_RADIUS = 1.0 nm |
| REVERSE backbone offset from axis | 10.0 Å | same radius, +150° angle |
| Rise per bp | 3.4 Å | B-DNA canonical |
| Twist per bp | 34.3–34.5° | B-DNA; 360°/10.44 bp ≈ 34.5° |
| Minor groove angle (fwd → rev) | +150° CCW | NADOC sign convention |

---

## What the Input Does NOT Contain

- **Helix axis positions** — mrdna derives these by averaging forward and
  reverse backbone positions (see Stage 1).
- **Atomic detail** — only one point per nucleotide is provided.
- **Box / periodic boundary** — supplied separately to SegmentModel.
- **Force field parameters** — hard-coded inside mrdna (WLC, Debye-Hückel).

---

## Relationship to the Next Stage

`model_from_basepair_stack_3prime` reads these arrays and:

1. Groups nucleotides into helical **Segments** using `basepair` + `stack`.
2. Builds a **position spline** for each Segment by averaging fwd+rev
   coordinates at each bp rank level.
3. Builds an **orientation spline** (if `orientation` supplied) for twist.

The per-nucleotide positions are only used at this construction step.
After Stage 1 the simulation is entirely spline-based; the raw
coordinate array is no longer accessed.
