# T-junction routing previews

Open **Help → T-junction routing previews…**. No active design is needed.
The isolated 3D viewer shows two six-helix bundles with a body that continues
through an interior attachment site. Presets include 90°, 60°, 120°, an
off-center attachment, and a spatial junction. Angle, rotation and attachment
controls change the proposed pose. Drag to orbit, scroll to zoom, or focus the
view and use the arrow keys. Reset view restores framing.

Switch between **Separate loops** and **Joined scaffold** to inspect the
connection. Bundle and scaffold visibility can be controlled independently.
The highlighted links carry scaffold direction; the marked original segments
identify where the separate cycles are opened. The attachment slider chooses
a nearby discrete surface site rather than an arbitrary point in a duplex.

## What the connection means

Original MagicDNA supports genuine end-to-side connections, as well as end-to-end
and side-to-side connections. Its side nodes are exposed scaffold sites where a
backbone break can be introduced. The side port uses neighboring positions on
one helix, while the donor end port uses two different helices at a blunt end.

The preview demonstrates the directed double-scaffold connection (DSCC):

1. Open the body's scaffold edge `a → b` at an interior side site.
2. Open the branch's end turn `c → d`.
3. Join `a → d` and `c → b`, so the scaffold enters the branch and returns to
   the body. Two directed cycles become one without losing or duplicating sites.

The host duplex axes remain continuous. This differs from the existing
**Help → Connectivity** shared-section fork preview, which partitions a
thickened bundle into branches.

MagicDNA's full routing algorithm starts with paired-helix cycles, applies
component connections, then merges remaining cycles using permissible internal
crossovers selected through a spanning tree. Here, two already connected
component cycles isolate the end-to-side splice for inspection.

## Scope

This is an independently implemented routing concept preview, not a port of
MagicDNA or a generated native NADOC design. It does not edit the current
document, create strands in it, assign sequence, or start simulation. Both
bundles contain right-handed ideal helix traces; the directed graph checks
ensure a single closed traversal after joining.

One DSCC demonstrates connectivity. It does not establish a rigid six-helix
junction. The chosen angle is a desired pose, not a predicted folded angle.
Linker contour lengths, junction phase compatibility, staple reinforcement,
scaffold source matching and mechanics remain unvalidated. More connection
pairs and physical validation are needed for an actual joint design.

## Primary references

- Huang, C.-M. et al. **Integrated computer-aided engineering and design for DNA
  assemblies.** *Nature Materials* (2021).
  [Paper](https://doi.org/10.1038/s41563-021-00978-5).
- [Original supplementary information](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41563-021-00978-5/MediaObjects/41563_2021_978_MOESM1_ESM.pdf):
  pp. 6–8 describe connectivity and scaffold routing; Fig. 7 (p. 22) includes
  surface nodes; Fig. 8 (pp. 23–24) illustrates the two scaffold connections.
- [Original source, 11 April 2021 revision](https://github.com/cmhuang2011/MagicDNA/blob/fd09b660b542e03a6d3f87dc2f5ff871219c8eab/class/hyperbundle.m#L6146):
  side/end candidate generation at lines 6146–6200; connection compilation at
  lines 7539–7597; cycle splicing at lines 4201–4420.

## Verification

`frontend/src/design/t_junction_preview.test.js` checks the graph splice,
polarity, site conservation and geometry. UI and renderer tests exercise
controls and cleanup. `frontend/e2e/t_junction_previews.spec.js` uses the actual
Help menu and WebGL viewer, including orbit, stages, presets, resizing,
close/reopen and the absence of document mutations.
