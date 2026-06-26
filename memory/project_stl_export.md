# STL export (3D printing) — shipped 2026-05-27

Export the **surface representation** as a binary STL for 3D printing.
File menu → "Export Surface STL (3D print)".

## Pipeline
- Reuses the existing molecular-surface mesh: `compute_surface()` in
  `backend/core/surface.py` → `SurfaceMesh` (vertices nm, faces).
- New module `backend/core/stl_export.py`:
  - `auto_scale(mesh, target_mm=200.0)` — scale so longest bbox dim = target_mm.
  - `export_stl(mesh, scale, name)` — vectorized binary STL via packed numpy
    structured dtype (itemsize == 50). Per-face normals from winding; global
    signed-volume flip as orientation safety net.
- Route `GET /design/export/stl?grid_spacing&probe_radius&target_mm` in
  `backend/api/crud.py` (right before `export_pdb_file`). 422 if empty surface;
  404 if no design (`_design_for_export`).
- Frontend: `exportSurfaceStl()` in `api/client.js` (blob-download pattern,
  mirrors `exportSequenceCsv`); button in `index.html`; handler in `main.js`
  next to PDB/PSF handlers.

## Decisions
- Auto-fit longest dimension to **200 mm** (consumer printer bed). No dialog.
- **Monochrome** single STL (standard STL carries no color). Strand colors dropped.
- **Loaded design only** (no assembly export). Assembly surface route exists
  (`/assembly/instances/{id}/surface-geometry`) if extended later.
- **Auto-inflate +30% over the displayed surface** (`radius_inflate=1.30` →
  `compute_surface(radius_scale=1.2 × 1.30 = 1.56)`) — thin features fatten and
  fuse into printable solids. Display surface unchanged (`radius_scale=1.2`).
- **Auto-smooth** with Taubin 15 iters (λ=0.5, μ=-0.53) → halves adjacent-face
  facet roughness (~0.177 → 0.088 on a 6HB-42 test). Closedness preserved.
  Lives in `surface.py::smooth_mesh` (general SurfaceMesh op).
- **Display surface uses the same defaults** (2026-05-27 follow-up): the three
  display routes — `/design/surface`, `/design/features/surface-batch` (animation
  pre-bake), `/assembly/instances/{id}/surface-geometry` — now default to
  `radius_inflate=1.30, smooth=15`, so the on-screen surface visually matches the
  STL export and the marching-cubes faceting that motivated this work is gone.
  `compute_surface`'s library default stays `radius_scale=1.2` (no change to the
  low-level API); the new defaults live at the route layer only. Cost: surface
  compute +17-19% wall time (one-time, cached client-side): +40 ms on a 6HB-42
  (~250 ms total), +525 ms on a 24HB-126 (~3.6 s total). Triangle count +7-12%
  → negligible render impact. Pass `radius_inflate=1.0&smooth=0` on any of those
  routes to recover the raw molecular surface.

## Watertightness reality (important)
The marching-cubes surface is **closed (no boundary/hole edges)** at both grid
0.20 and 0.30 — verified. But skimage marching_cubes emits a *handful* (≈6) of
**non-manifold junction edges** (shared by 4 triangles) where two surface lobes
touch. This is a normal marching-cubes artifact; slicers (Cura/PrusaSlicer)
auto-repair it on import. The print-critical invariant is "no odd-count edges"
(no holes), NOT "every edge shared by exactly 2 triangles" — `test_stl_export.py`
asserts the former.

## Tests
`tests/test_stl_export.py` — binary layout, unit normals, closedness (no holes,
junctions bounded), auto_scale fit, empty-mesh → 84-byte 0-triangle STL.

## Multi-color 3MF export — shipped 2026-06-02
File menu → "Export Surface 3MF (multi-color print)", alongside the STL item.
**4 groups: scaffold + 3 map-colored staple sets** (see coloring section below).
- New module `backend/core/threemf_export.py`:
  - `scaffold_staple_colored_groups(mesh, design, n_staple_colors=3)` →
    `(face_group, names, colors, stats)`. THIS is what the route uses. Group 0 =
    scaffold; groups 1..k = staple sets A..C. Colors: #29B6F6 scaffold, then
    #FF6B6B / #6BCB77 / #FFD93D (red/green/yellow). `stats` = n_staples,
    conflicts, per-set counts. `n_staple_colors` clamped to 1..3.
  - `scaffold_staple_groups(mesh, design)` → simple 2-group (scaffold/staples)
    by per-face majority vote. KEPT as a building block / unit-tested, but the
    route no longer calls it.
  - `export_3mf(mesh, face_group, names, colors, scale, name)` → zipped 3MF.
    Handles an arbitrary number of groups (loops `len(names)`; emits only
    non-empty groups).
  - Reuses `auto_scale` + `_signed_volume` from `stl_export` (same nm→mm fit +
    global orientation flip).

### Staple map-coloring (the "no two nearby staples share a color" feature)
- **Adjacency = surface-region border, not 3D proximity.** Two staples are
  adjacent iff some surface **mesh edge** joins a vertex of one to a vertex of
  the other — i.e. their colored regions *touch on the printed part*.
  `_staple_adjacency(faces, vert_code)` builds the unique staple-index pairs
  (vert_code: -1 scaffold, -2 unassigned, ≥0 staple index).
- **Coloring** = `_color_staples(n, pairs, k=3)`: largest-degree-first greedy,
  each node takes the color used by the fewest already-colored neighbors, ties
  → globally least-used color (keeps the 3 sets balanced). Returns
  `(color_per_staple, conflicts)`.
- **3 colors can't always succeed** (four-color theorem: a map on a surface can
  need 4). `conflicts` counts the unavoidable same-color borders that remain;
  reported in response header `X-NADOC-Coloring` and surfaced in the success
  toast. 6hb_test (8 staples) → 1 conflict, which is expected, not a bug.
- Unassigned vertices (empty strand id) are lumped into staple set A.
- `compute_staple_coloring(mesh, design, k)` → `(strand_to_group, names, colors,
  stats)`. Colors ALL staple strands in the design (group 1..k); scaffold = 0.
  Adjacency from surface edges; staples never on the surface are isolated nodes
  that just balance the sets. THIS is what the manifold route uses.
- `scaffold_staple_colored_groups` is now a thin wrapper over
  `compute_staple_coloring` that builds a per-FACE group label (used by the old
  single-mesh split path + tests, not the route).
- **Encoding decision (important):** uses the Materials & Properties extension —
  one `<object>` per color group, each with a default `<base>` material,
  gathered as `<component>`s of one assembly object (shared coordinate frame).
  Read by ALL slicers. Did NOT use per-triangle `mmu_segmentation`/`paint_color`
  — slicer-specific and PrusaSlicer ignores them on import (opens as plain STL).

### MANIFOLD FIX — closed sub-solids (2026-06-02, replaces open-shell split)
**Bug:** the first cut split the single closed surface into per-color shells via
`export_3mf` + `face_group`. Each shell was OPEN along the color seams →
slicers reported **thousands of boundary/"non-manifold" edges** (measured ~4300
on 6hb_test: scaffold 1864 + A 1116 + B 482 + C 872; zero true >2-tri edges).
The 3MF spec REQUIRES watertight meshes, so open shells are spec-violating.
**Fix (chosen by user; targets Bambu AMS):** re-surface each color as its own
**closed solid** instead of cutting one shell.
- `surface.compute_colored_surfaces(atoms, strand_to_group, n_groups, ...)`:
  rebuilds the SES voxel volume exactly as `compute_surface`, labels each
  occupied voxel by its nearest atom's group (KD-tree), then runs marching cubes
  **per group's voxel mask** (cropped to bbox + 1-pad). Each part is closed.
  Adjacent groups' interface walls are the same voxel mid-plane for both → they
  coincide. `_weld_smooth_parts` welds all parts by rounded position (1e-4 nm),
  Taubin-smooths the welded complex once, then redistributes — shared walls move
  in lock-step so they stay coincident while each part stays watertight.
- `threemf_export.export_3mf_parts(parts, scale, name)`: writes each closed part
  mesh as its own `<object>` + base material (parts = list of
  `(SurfaceMesh|None, name, hex)`). Per-part `_signed_volume` orientation flip.
- Result on 6hb_test live: 4 parts, **boundary edges = 0 on every part** (was
  ~4300). Residual ~6-9 marching-cubes junction edges (4-tri, where lobes touch)
  remain — IDENTICAL kind/count to the STL the user already prints; Bambu
  auto-repairs them on import. If zero-junction is ever needed → true manifold
  repair is a follow-up (see TODO).
- Cost: route now computes the single surface (for coloring) PLUS one marching
  cubes per color (~Ngroups×). Acceptable for an export action; not interactive.
- Tests added (`tests/test_threemf_export.py`, now 17): parts-are-closed
  (no odd-count edges), walls-coincide (shared vertices > 0),
  export_3mf_parts manifold-objects. Live: 366 KB, header "3 staple colors,
  8 staples, 0 adjacent same-color".
- Route `GET /design/export/3mf`: STL query params + `staple_colors` (1-3).
  Pipeline = compute_surface→smooth → compute_staple_coloring →
  compute_colored_surfaces → export_3mf_parts. `X-NADOC-Coloring` header +
  toast unchanged. `_zip_store` hand-rolled deflate zip (no deps).

## TODO if revisited
- Color mappings beyond scaffold/staple-sets (cluster / strand-group / manual
  pick). The staple coloring is map-based on surface adjacency; a different
  semantic grouping would be a new grouper alongside `scaffold_staple_*`.
- Assembly export. Optional explicit-scale dialog (currently `target_mm` param only).
- True manifold repair to kill the residual ~6-9 marching-cubes junction edges
  (4-triangle, lobe-touch) if a slicer ever chokes on them. Bambu auto-repairs
  today, and the STL has the same artifact, so low priority. Would split the
  shared junction vertex/edge per incident lobe.
- Per-color-solid extraction triple-junction lines (g/h/empty) can leave tiny
  sub-voxel mismatches between parts (each part still closed). Not observed to
  matter for Bambu AMS; revisit only if interface seams print poorly.
