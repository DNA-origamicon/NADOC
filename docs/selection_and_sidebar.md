# Selection and right sidebar

NADOC's design workspace uses one selection model across the 3D view, sidebars,
spreadsheet, keyboard commands, and programmatic actions. Selecting the same design
entity through two different UI paths therefore produces the same Properties readout,
highlight, and command target.

## Right sidebar

The right sidebar is divided into four vertical tabs:

| Tab | Sections |
|---|---|
| **Properties** | Properties, Strand Lengths, Staple Groups |
| **Visualization** | Representation toggles, Representation Options, View Actions (Reset Camera, Unhide All, Section view), Multi-view, Multi-overlay, View Volumes |
| **Clustering** | Movable Clusters, Joints |
| **Overhangs** | Overhangs, Overhang Connections, Strand Animation |

Each section uses the same grey-gradient card treatment as the left sidebar. Use the
chevron at the top of the tab strip to collapse or restore the sidebar. Drag the divider
between the tab strip and viewport to resize it. The Blunt End and empty Measurements
cards are intentionally absent.

### Section view

In **Visualization → View Actions**, toggle **Section view** to cut through the
current representation. Intersected solids have closed, diagonally hatched cut
faces. Toggle it off to restore the full representation without editing the design.

The framed **Section plane** controls provide:

- **Move / Rotate:** choose the canvas gizmo mode. Move slides along the plane's
  local normal; Rotate changes its orientation.
- **Position (nm):** enter world X, Y, and Z coordinates, or use each row's
  **−2 / +2** buttons for 2 nm increments.
- **Rotation (°):** enter X, Y, and Z Euler angles (XYZ order), or use
  **−5° / +5°** for 5° increments. Enter applies a field; arrow keys use the
  same increments as the buttons. Gizmo changes update the fields.
- **Flip:** reverse the side retained by the cut.
- **Reset:** move the plane to the part's current nucleotide-position centroid,
  set rotation to **180°, 0°, 0°**, and clear Flip. If nucleotide geometry is
  unavailable, or an assembly is active, use the visible content's bounding-box
  center instead.
- **Hide controls:** hide the canvas gizmo and plane outline while keeping the
  section and numeric controls active.

On activation the plane starts at the visible content's center, oriented to the
current viewing direction. Reset uses the fixed rotation described above. Section
settings last for the current view session and are not saved into the design.

The renderer clips surfaces and uses winding stencils to fill solid intersections.
Invisible picking meshes and open sheets do not contribute hatched fills. Open
circular tube/cylinder ends are closed in temporary stencil geometry; source meshes
remain unchanged. This requires the main renderer's stencil buffer. Coverage lives
in `frontend/e2e/section_view.spec.js` and the `section_view` / `section_geometry`
unit tests, including stray-fill regressions and restoration after disabling.

### Multi-view

The **Multi-view** card splits the 3D viewport into two, three, or four synchronized
panels. Choose a layout with its icon button; click the active layout again to return
to one view. Each panel contains numbered Representation and Coloring menus in its
upper-left corner. Heavy representations show a loading status while their isolated
scene is prepared.

The menus also include **mrDNA Coarse** and **mrDNA Fine** input previews. They show
the current design before simulation: coarse combines adjacent geometry into the
five-base-pair beads sent to ARBD, while fine uses one site per base pair. Connections
follow strand order, including crossovers. Both retain mrDNA's model coloring.

These two input representations are also available as normal global choices in
**View → Representation** and in the Visualization tab's **Representations** card.
They apply to individual designs rather than assemblies.

Every panel uses Hull Audit framing: a 38° perspective camera, molecular-content-only
bounds, and an orbit target at the arithmetic centroid of the design's nucleotide
positions. Axes, grids, gizmos, and diagnostic overlays do not affect fitting. Orbit,
pan, and zoom are interpreted in the coordinate system of the panel under the pointer,
then synchronized to the other panels. Collapsing or resizing either sidebar resizes
all viewports without changing their shared navigation state. Closing Multi-view
restores the workspace camera and controls.

### Multi-overlay

The **Multi-overlay** card composites one to four independently selected
representations in the same 3D view. Its numbered Representation and Coloring menus,
plus per-layer Opacity sliders, appear in the upper-left of the viewport. The Separation slider in
the card moves layers evenly along the world X axis: zero overlaps them exactly, while
one uses the design's longest molecular dimension as the spacing between adjacent
layers. Offsets are centered around the design, so separation does not introduce a
one-sided drift.

Multi-view and Multi-overlay are mutually exclusive. Activating either mode closes the
other cleanly before preparing its representations. Multi-overlay uses isolated scene
copies, so representations remain visible together even when their normal workspace
renderers are mutually exclusive. Clicking the active layer-count button exits the
mode and restores the prior workspace camera.

The same mrDNA Coarse and mrDNA Fine choices are available for every overlay layer,
so simulation output can be compared directly with native representations or with
the other mrDNA resolution.

### View volumes

The collapsible **View Volumes** card applies a representation and opacity to a
spatial region without changing the design topology. Use the square-plus button for
an oriented box or the hexagon-plus button for a regular hexagonal prism suited to
honeycomb helix bundles. A hexagonal volume has two resize dimensions: the red radial
arm changes both cross-section axes together, while the blue Z arm changes its length.

Hovering a volume edge highlights its outline. Clicking the highlighted edge selects
only the volume and does not also snap-select a nearby strand. Dragging empty viewport
space to orbit preserves the volume selection; a stationary empty-space click clears
it. The eye button on a volume row hides that volume's outline, handles, hover target,
and transform gizmo while leaving its representation active. The eye button in the
card header shows or hides every outline. Outline visibility and the card's collapsed
state persist across reloads.

The power button on each row independently enables or disables that volume's
representation layer without hiding its editable outline. The power button in the
card header enables or disables every layer, making it quick to compare combinations
of representations at different locations. Enabled state is saved with the design.

Volume membership is evaluated per base-pair column. Cylinder representation clips
domains into contiguous in-volume runs, including boundaries that fall in the middle
of a domain, so the cylinder length follows the spatial boundary instead of dropping
the complete domain. Overlapping volumes remain independent representation layers.

## Selection levels

The selection control limits what a 3D click targets. Fixed levels select only that
kind; Default supports hierarchical drill-down. In Default, the first click on a strand
selects the strand and the next click on one of its bases selects that exact base. That
base selection is identical to selecting it through the explicit Base level.

Modifier clicks and lasso operations extend or toggle the same canonical selection.
Re-clicking the sole item clears it at fixed levels, while Default retains its
hierarchical drill behavior. Selection level always resets to **Default** when a design
is loaded or when switching between design and assembly contexts.

Design and assembly selections are deliberately separate. Entering or leaving assembly
clears the design selection rather than carrying ambiguous IDs between contexts.

## Display names

The strand spreadsheet begins with a compact display-only ID column. IDs are assigned
from design order and do not change when the spreadsheet is sorted:

- Staples: `S1`, `S2`, …
- Linkers: `L1`, `L2`, …
- Scaffold, OH binders, and other strand types: `X1`, `X2`, …

Properties uses the same ID as the spreadsheet. Stable internal IDs remain unchanged in
the saved design and selection state.

All user-facing helix references use the helix's display label, including Properties,
strand endpoints, crossover endpoints, blunt-end tools, and simulation status text.
Internal lattice IDs such as `h_XY_0_1` remain implementation details and are not shown.
An explicit helix label is preferred; otherwise NADOC uses the helix's zero-based design
index.

A single selected base has a detailed Properties readout:

```text
base: A
location: Staple - 1[34]
position: 4 in staple S2
```

The position is the base's 1-based location along the complete strand. When the strand
spreadsheet is expanded, selecting one or more bases automatically scrolls to the owning
strand, highlights its row, and marks the selected letters in the Sequence column. A
collapsed spreadsheet remains closed and does not scroll.

Multiple selected bases are grouped by type and helix, for example:

```text
Staple - 1[34,35]
Scaffold - 1[34,35]
Linker - 44[10-22]
```

Runs of three or more consecutive bases are compressed. Extension and crossover
insert bases have synthetic internal coordinates, so their labels retain the parent
helix and add an anchor-relative ordinal, such as `Extension - 1[43›2]` or
`Extra base - 1[43+1]`.

## Developer contract

Selection identity is stored only in the canonical `selection` field. New UI consumers
must use the typed selectors rather than introduce writable projections or decode live
Three.js objects as identity. Picking resolves stable refs; rendering derives highlights
from those refs and may rebuild without changing logical selection.

The full architecture contract and regression matrix live in
[`memory/project_selection_model.md`](../memory/project_selection_model.md) and
[`memory/selection_behavior_matrix.md`](../memory/selection_behavior_matrix.md).
