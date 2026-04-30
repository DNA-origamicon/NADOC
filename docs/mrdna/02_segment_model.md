# Stage 1 — SegmentModel

`model_from_basepair_stack_3prime` builds a `SegmentModel` — a graph of
**Segments** connected by typed joints.  Everything downstream (bead
generation, simulation, atomistic output) operates on this graph.

---

## What Is a Segment?

A Segment is a **continuous helical domain** — the longest unbroken run of
base-stacked, base-paired nucleotides that belongs to a single structural
helix.  It has no crossovers inside it.

| Class | Physical meaning | Key fields |
|-------|-----------------|------------|
| `DoubleStrandedSegment` | Paired dsDNA helix arm | `num_bp`, rise=3.4 Å, repeat=10.44 bp |
| `SingleStrandedSegment` | Unpaired loop, overhang, or scaffold strand | `num_nt`, dist_per_nt=5 Å |

A single NADOC helix with crossovers at internal positions becomes
**multiple** `DoubleStrandedSegment` objects — one per continuous arm
between crossovers.

---

## Helix Mapping Arrays

Three parallel arrays of length N (one entry per nucleotide) are computed
by `basepairs_and_stacks_to_helixmap`:

| Array | Type | Meaning |
|-------|------|---------|
| `hmap[i]` | int | Which Segment nucleotide `i` belongs to. `−1` initially for ssDNA |
| `hrank[i]` | float | Position along the Segment axis (0, 1, 2, … per bp level) |
| `fwd[i]` | int (0/1) | `1` if on the "forward" strand of this helix; `0` on the reverse |

**Algorithm**: starting from every 3′ helix end (`stack[i] == −1` and
`basepair[i] ≥ 0`), follow `stack` bonds upward, assigning consecutive
`hrank` values. The basepair partner at each rank gets the same `hmap` and
`hrank` but `fwd = 0`.

---

## The Position Spline

Each Segment carries a **position spline** (`position_spline_params`) that
maps a normalized contour coordinate `s ∈ [0, 1]` to a 3-D position (Å).

### How It Is Built

For a Segment with `maxrank+1` bp levels:

```python
for rank in range(maxrank + 1):
    ids = where(hmap == hid and hrank == rank)   # fwd + rev nucleotide
    coord = mean(coordinate[ids])                # centroid of both strands
    contour = (rank + 0.5) / (maxrank + 1)       # centre of bp slot
    coords.append(coord)
    contours.append(contour)
```

The spline knots are placed at **half-integer contour positions** so that
the endpoints `s=0` and `s=1` lie outside the data range and map cleanly
to the segment ends via linear interpolation.

### Centroid Position vs Helix Axis

The spline is built through the **average of forward and reverse backbone
positions at each bp level**, NOT through the helix axis.

For B-DNA with HELIX_RADIUS = 10 Å and minor-groove angle 150°:

```
fwd_radial = [cos α, sin α, 0] · 10 Å
rev_radial = [cos(α+150°), sin(α+150°), 0] · 10 Å
centroid   = (fwd + rev) / 2
|centroid - axis| = 10 · cos(75°) = 10 · 0.259 = 2.59 Å
```

**The spline positions are 2.59 Å off-axis, rotating helically with
twist.** For a 42-bp helix this traces a mini-helix of radius 2.59 Å
around the true helix axis.

This offset is small compared to the inter-helix spacing (~20 Å) so
helix assignment is unaffected, but it matters for spline tangent
directions (see Stage 2 note below).

---

## The Orientation Spline

When `orientation` arrays are provided, a second spline is built through
quaternion-averaged nucleotide frames. At each bp level the forward
nucleotide's orientation matrix is averaged with its basepair partner's
(after rotating by 180° about the x-axis to account for the anti-parallel
geometry).

`contour_to_orientation(s)` returns a 3×3 rotation matrix whose z-column
is the local helix axis tangent and whose x-column is the radial direction
toward the backbone.

---

## Connections Between Segments

Segments are joined by typed `Connection` objects:

| Type | When created | Physical meaning |
|------|-------------|-----------------|
| `intrahelical` | Contiguous helix arm ending at a helix-helix junction | Rigid continuation of the helical axis (no kink) |
| `crossover` | Strand jumps from one helix to another mid-arm | Flexible inter-helix junction |
| `terminal_crossover` | Crossover at a helix end (`rank == 0` or `rank == num_bp−1`) | Kinkable end junction |
| `sscrossover` | dsDNA ↔ ssDNA boundary | Transition from helical to single-stranded |

Terminal crossovers within 75 bp of another crossover on the same segment
pair are promoted to regular `crossover` connections.

Connection endpoints are `Location` objects that store: which segment,
which contour address (0 or 1 for ends), and which strand (fwd/rev).

---

## Segment Model vs SegmentModel

- A **Segment** (`DoubleStrandedSegment`, `SingleStrandedSegment`) is one
  helical arm.  It has a spline and a list of beads.
- The **SegmentModel** is the full graph: a list of Segments + Connection
  objects + global simulation parameters (box, temperature, timestep).

`SegmentModel.__init__` immediately calls `generate_bead_model()` with
whatever parameters were passed to `model_from_basepair_stack_3prime`,
so the model is always ready for simulation when returned.

---

## Key `contour_to_position` Behavior

| Input `s` | Output |
|-----------|--------|
| 0 | Extrapolated position at start of segment (bp level −0.5) |
| `0.5/(maxrank+1)` | Position at bp rank 0 (first bp centroid) |
| `(rank+0.5)/(maxrank+1)` | Position at bp rank `rank` |
| 1 | Extrapolated position at end of segment (bp level maxrank+0.5) |

For a **straight** helix this traces a line offset 2.59 Å from the true
axis.  For a **bent** helix (after coarse simulation) the spline curves
to follow the deformed axis trajectory.

---

## Relationship to Coarse and Fine Beads

Bead positions come directly from this spline:

```python
def _generate_one_bead(self, contour_position, nts):
    pos = self.contour_to_position(contour_position)
```

Bead positions are therefore at the **fwd-rev centroid** (2.59 Å off-axis
for ideal B-DNA input), not at the helix axis and not at either backbone.
This matters for how `nuc_pos_override_from_mrdna_coarse` interprets the
dry-run PSF/PDB (see `08_nadoc_integration.md`).
