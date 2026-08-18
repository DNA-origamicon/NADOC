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
| **Visualization** | Representation toggles, Representation Options, Reset Camera, Unhide All, Multi-view, Multi-overlay |
| **Clustering** | Movable Clusters, Joints |
| **Overhangs** | Overhangs, Overhang Connections, Strand Animation |

Each section uses the same grey-gradient card treatment as the left sidebar. Use the
chevron at the top of the tab strip to collapse or restore the sidebar. Drag the divider
between the tab strip and viewport to resize it. The Blunt End and empty Measurements
cards are intentionally absent.

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
