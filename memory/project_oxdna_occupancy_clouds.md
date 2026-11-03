
# Occupancy clouds — top-N configurations for oxDNA

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Status: SHIPPED (2026-08-01), backend + frontend, verified in the running app.**

## What it is and why

The flexibility map (RMSF) reports ONE mean structure plus a per-nucleotide spread. For a
bistable object that is the wrong estimator: a plate alternating between the two saddle
senses of a hyperbolic paraboloid has a **flat mean** — a shape it never occupies. RMSF
draws that fictitious flat structure and paints high fluctuation at the corners, telling
you something moves but not *what states it moves between*.

Occupancy clouds answer the other question: cluster the sampled frames by shape, and draw
each cluster's **medoid (a real frame)** superposed in its own flat colour, opacity keyed to
population.

**Every state is a copy owned by the overlay; the design model steps aside.** There is no
"rank 0 rides the real model" special case (there was, until 2026-08-01): two superposed
structures are only readable if each is one identifiable colour, so while this view is up
the overlay calls `setDesignVisible(false)` — the same hand-off `mrdna_display` /
`blade_display` / `md_panel` use — and restores it on teardown. N states therefore cost N
builds, not N−1.

The UI is a **scrollable state list**, one row per state: on/off checkbox, colour picker,
then population/spread/visits. Toggling is free (`group.visible`); recolouring rebuilds
that ONE copy, because the tint is baked in through `buildHelixObjects`'s `customColors`
so it survives at cylinder LOD. Per-state choices live outside the response cache so they
survive a refetch, and are dropped when the CLUSTERING changes — "state 2" of k=5 is a
different structure from "state 2" of k=2.

<a id="scope-whole-structure-vs-specific-elements-2026-08-01"></a>
- [Scope: whole structure vs specific elements (2026-08-01)](details/project_oxdna_occupancy_clouds/01-scope-whole-structure-vs-specific-elements-2026-08-01.md#scope-whole-structure-vs-specific-elements-2026-08-01)

<a id="the-fit-frame--what-makes-a-scoped-run-mean-anything-2026-08-02"></a>
- [The fit frame — what makes a scoped run mean anything (2026-08-02)](details/project_oxdna_occupancy_clouds/01-scope-whole-structure-vs-specific-elements-2026-08-01.md#the-fit-frame--what-makes-a-scoped-run-mean-anything-2026-08-02)

- [The fit frame — what makes a scoped run mean anything (2026-08-02) — continued detail](details/project_oxdna_occupancy_clouds/01-scope-whole-structure-vs-specific-elements-2026-08-01.md)

<a id="extra-bases-and-extension-tails-in-the-drawn-states-2026-08-01"></a>
- [Extra bases and extension tails in the drawn states (2026-08-01)](details/project_oxdna_occupancy_clouds/01-scope-whole-structure-vs-specific-elements-2026-08-01.md#extra-bases-and-extension-tails-in-the-drawn-states-2026-08-01)

<a id="namd-equivalent-2026-08-01"></a>
- [NAMD equivalent (2026-08-01)](details/project_oxdna_occupancy_clouds/02-namd-equivalent-2026-08-01.md#namd-equivalent-2026-08-01)

- [NAMD equivalent (2026-08-01) — continued detail](details/project_oxdna_occupancy_clouds/02-namd-equivalent-2026-08-01.md)

<a id="three-init-order-bugs-the-namd-work-surfaced-all-caught-only-by-e2e"></a>
- [Three init-order bugs the NAMD work surfaced (all caught only by e2e)](details/project_oxdna_occupancy_clouds/02-namd-equivalent-2026-08-01.md#three-init-order-bugs-the-namd-work-surfaced-all-caught-only-by-e2e)

## The three invariants (do not weaken any of them)

1. **The representative is a medoid, never a within-cluster average.** Averaging positions
   collapses bond lengths (−26 %/−67 % vs −1.8 %/+0.9 % per-frame, see
   `project_md_viz_tools.md`). A cluster mean would be exactly as unreal as the flat RMSF
   mean this feature replaces. Pinned by `test_medoid_is_a_real_frame_never_a_mean`.

2. **Separation is NOT switching — this is the one that bites.** A monotone drift along one
   collective mode gets cut in half by k-means and scores a HIGH silhouette while never
   revisiting a state. **Measured** on `exp35_autorefine_equilibration_test/ws_proxy/
   oxdna_jobs/14b896dab3c2`: silhouette **+0.58** at k=2, label sequence
   `1111111111111111111111111 0000000000000000000000000` — **1 transition**, PC1 lag-1
   autocorrelation **+1.000**, n_eff **2.6**. Those "states" were "early in the run" and
   "late in the run". So a multimodal verdict additionally requires **recurrence**: each
   state entered ≥ `_OCC_MIN_VISITS` (2) times. Otherwise `verdict="drift"` and the UI
   shows frame COUNTS, never percentages. Pinned by
   `test_monotone_drift_is_not_reported_as_two_states`.

3. **Unimodal is a legitimate answer.** A rigid origami *is* unimodal; inventing two states
   out of one Gaussian basin is worse than drawing nothing. Below silhouette 0.25 →
   `k=1`, "the flexibility map is the right view".

Populations carry autocorrelation-aware error bars — frames are not independent and a naive
`sqrt(p(1-p)/N)` overstates confidence by an order of magnitude on a slow flip.

<a id="files"></a>
- [Files](details/project_oxdna_occupancy_clouds/03-files.md#files)

<a id="reuse--nothing-here-was-written-twice"></a>
- [Reuse — nothing here was written twice](details/project_oxdna_occupancy_clouds/03-files.md#reuse--nothing-here-was-written-twice)

## Traps that fail silently (all four are live, all four cost a debugging session)

- **Frame-budget drift breaks the cache.** The route defaults to `scope='lineage'`,
  `max_frames=_SPARSE_FRAME_CAP`, `copies=True` *specifically* to hit the same
  `_ALIGNED_CACHE` entry `/trajectory` fills. Any other `max_frames` silently re-reads the
  whole trajectory. Pinned by `test_route_defaults_match_the_trajectory_route`.
- **The seed frame.** `_aligned_downsampled_frames` prepends the design-reference pose at
  composite index 0. For a production/field child that is the DESIGN pose, not a sample —
  at F≈60 it steals a whole cluster. `_sampling_indices` drops it.
- **Relaxation stages.** Included in the lineage stage list; they are a transient and
  guarantee a spurious drift split. Sliced out by `kind in ("production","field")`.
- **The LOD trap.** `buildHelixObjects` starts every cylinder mesh `visible = false` with
  `_detailLevel` at 0. A ghost built at `lod='cylinders'` draws **nothing** until
  `setDetailLevel(CG_LOD.cylinders)` is called. Pinned in `occupancy_overlay.test.js`.

Also: ghost opacity must clear `depthWrite` (a transparent mesh that writes depth is an
invisible occluder); ghost tint goes through `buildHelixObjects`'s `customColors`
(`{strandId: hex}`), **not** `applyScalarColors` — that is the scalar-map channel
`coloringInfo()` switches on for export.

<a id="measured-on-real-data"></a>
- [Measured on real data](details/project_oxdna_occupancy_clouds/04-measured-on-real-data.md#measured-on-real-data)

<a id="verified-in-the-app"></a>
- [Verified in the app](details/project_oxdna_occupancy_clouds/04-measured-on-real-data.md#verified-in-the-app)

## Open
- **The scientific oracle is unwritten**: the two top medoids of a bistable plate must have
  **anti-correlated corner displacements** (project each medoid's deviation from the
  ensemble mean onto the plate normal; cluster 0's sign pattern should be cluster 1's
  negation). Computable headlessly from the route response alone → belongs in the
  `/automate-feature` backlog as an AF oracle, not a manual step.
- `method="rmsd"` (hierarchical) is validated-and-rejected at the route; the seam exists.
- Ghosts are CG-only; a heavy-rep switch clears them with a loud status. No atomistic ghosts.
- `pc1_series` and `medoid_frame` are returned but nothing renders them — a PC1-vs-time
  switching plot and a "jump the scrubber to this medoid" button are both nearly free.
- NAMD reuse via `md_viz_adapter.js` is deliberately wire-compatible but unwired.
- **`fit="local"` covers crossover extra bases only.** An extension tail (`__ext_<id>`) has an
  equally well-defined local frame — the duplex around its anchor base — but no group is built
  for one, so a picked tail falls into the leftover group and is fitted on the selection. Cheap
  to add once the anchor→(helix, bp) lookup is threaded in.
- **`fit` has no `bp`-basis story for extra bases, and cannot.** Synthetic beads are unpaired,
  so they never appear as duplex columns: scoping to extra bases with `basis="bp"` correctly
  fails with *"the selection matched no nucleotides in this basis"*. NAMD is `nt`-only, so this
  bites the oxDNA card only.
- The `local` frame is per crossover and its groups are concatenated into one feature vector,
  so PCA describes what the inserts do *collectively*. There is no per-insert breakdown yet.
