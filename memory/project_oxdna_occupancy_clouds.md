# Occupancy clouds — top-N configurations for oxDNA

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

## Scope: whole structure vs specific elements (2026-08-01)

A global clustering is dominated by the largest-amplitude motion in the whole object, so a
local hinge or a single flexible seam that flips between two well-defined states can sit
entirely inside its noise floor. `Analyse: [Whole structure | Specific elements…]` restricts
the feature matrix to picked clusters / strands / domains / overhangs / individual bases.

### The fit frame — what makes a scoped run mean anything (2026-08-02)

For a whole release `_superpose_on_subset` existed, was correct and was tested while having
**no production call site**, so every scoped run silently clustered the region's rigid-body
swing inside the GLOBAL fit — reporting where the region *was*, not what shape it took. Both
engines' docstrings claimed otherwise. Wired now, and generalised, because the right frame is
selection-dependent. `occupancy_fit_plan` + `apply_fit_plan` (in `occupancy_core`) own it and
BOTH engines call them; the payload carries `fit` / `fit_requested` / `fit_note` /
`n_fit_points` — the same don't-lie contract `basis` has.

| `fit` | frame | for |
|---|---|---|
| `global` | leave the whole-structure Kabsch fit | when the region's PLACEMENT is the question. The old behaviour |
| `selection` (default) | Kabsch on the picked points | a sub-region whose internal shape you want |
| `local` | each `__xb__` insert on ITS OWN junction — both halves, both strands, ±3 bp | **crossover extra bases**: what the T does relative to its own junction |

Three rules that are load-bearing:

- **A MIXED selection fits on the DUPLEX-PAIRED members only** (`_strain_index(…, "wc")`).
  Kabsch weights every point equally and an unpaired bead's RMSF is several times the duplex
  value, so letting the floppy points into the fit set lets them drag the frame and smear the
  motion the duplex part was picked to show. Below 3 paired points it fits on everything and
  says so in `fit_note`.
- **`local` is NOT subject to the 3-point floor; `selection` is.** Its fit set comes from the
  junction, not the pick, so scoping to ONE crossover's one or two inserts — the most natural
  extra-base question there is — still re-fits. Under `selection` that same pick honestly
  degrades to `global` with a note.
- **`need_idx` is wider than the selection under `local`**, because a junction's frame is
  duplex nobody picked. Both feature builders retain those extra columns per frame and only
  then apply the plan. Re-fitting is FEATURE-SPACE ONLY — the medoid frames handed back for
  rendering stay globally aligned, so the drawn states share `/trajectory`'s pose.
- Direction strings in a junction's flank keys are `"FORWARD"`/`"REVERSE"`, **not** the
  `Direction` enum the model stores. Getting that wrong yields an empty flank set, which
  degrades to `selection` silently-but-for-the-note. Cost one probe run.

**The fit frame changes the answer.** Measured on `bfd050d2ce4c` (2hb_2xT, 200 ns production,
4 T inserts, 80 frames), scoped to all extra bases:

| fit | verdict |
|---|---|
| `global` | **drift**, k=5, sil +0.29 — one state visited once |
| `selection` | **switching**, k=2, sil +0.38, 54 %/46 %, 5 visits each |
| `local` (56 flank points) | drift, k=6, sil +0.33 |

On the oxDNA twin `2d8b40a0d507` (2hb_1xT production, 2 inserts) the direction reverses, which
is the point: `global` reads **switching** (46/46 visits) while the junction frame reads
**unimodal** — what looked like the inserts flipping was the junction moving under them.

UI: a `Fit frame` select on both cards, hidden until `Analyse: Specific elements…` (there is
nothing to re-superpose on the whole structure). A degraded mode prints its `fit_note` under
the legend in amber. Changing it drops the per-state colours, like any other reclustering.

**The picker is the SHARED anchor widget, instantiated not forked.** `initOxdnaAnchorsSetup`
already drives five engine cards off an `ids` override; occupancy adds a sixth channel with
`engine: 'occupancy'`, inheriting chips, `×` delete, Clear, the scrolling list and the purple
`0xb14aff` halo. Two things this cost:

- The factory returns an **inert stub** when its `toggle`/`body` ids are missing
  (`oxdna_anchors_setup.js`), so the skeleton must be complete — a card that looks right but
  adds nothing is the failure mode. Pinned by a source-text test over `index.html`.
- It **collapses itself on init**, so the scope body is opened once after construction (it
  is already gated by the Analyse selector; a second click to reveal it is friction).
- `main.js:_refreshAnchorGlow` showed only the *engine selector's* engine, and occupancy is
  not an engine tab — its halo could never appear. It now unions the `occupancy` channel in.
  **The NAMD card registers as `md-occupancy`, a SEVENTH channel, and was left out of that
  union until 2026-08-02** — chips appeared in the list, nothing lit in the 3D view. Both
  names are listed explicitly now; pinned by a source-text test in `occupancy_controls.test.js`.
  Any future card on this widget must add its own channel name there.

Backend: `resolve_selection_keys(design, keys, selection)` — a UNION of `cluster_ids` /
`helix_ids` / `strand_ids` / `overhang_ids` / `domains` / `bases` / `extra_bases` /
`extensions`. Bases match on the first three key elements so a position takes all its loop
copies. Every criterion exists **because the picker emits that kind** — without it those
picks would silently select nothing.

**Synthetic beads are scopeable (2026-08-01).** Crossover extra-base inserts
(`("__xb__", xo_id, k)`) and extension tail beads (`("__ext_<id>", k, dir)`) carry no
(helix, bp, direction), so no coordinate criterion can reach them; `extra_bases` /
`extensions` address them by key instead — `[[owner_id, k]]`, or `[[owner_id]]` for the whole
run/tail. The asymmetry this fixed: an **unscoped** run has always included them (`key_list`
comes from `_strand_nucleotide_order`, which emits them), so they were in the feature basis by
default yet impossible to name when scoping. A scoped selection that doesn't ask for them
still excludes them, so every existing scope means exactly what it did.

Both new fields are in `OccupancySelection` (`extra="forbid"` — a criterion the model doesn't
declare is a 422) **and** in `_selection_sig`, or two different scopes collide in the cache.

Transport is `POST /oxdna/jobs/{id}/occupancy` (a base-level selection is far too big for a
query string); the unscoped `GET` is unchanged and both share one `_occupancy_impl`. The
selection is part of the cache key on both sides, order-independent (`_selection_sig`), so
two different regions can never collide — and the frontend's own cache key includes it too.

## Extra bases and extension tails in the drawn states (2026-08-01)

They are NOT the same mechanism, and only one was broken:

| | wire key | how it is drawn |
|---|---|---|
| crossover extra base | `["__xb__", <crossover_id>, k]` | **no** (helix,bp,dir) key → own instanced meshes from `buildCrossoverConnections`; `applyFemPositions` silently drops these updates |
| extension tail | `["__ext_<id>", i, direction]` | a **real** key on a synthetic helix → ordinary beads from `buildHelixObjects`, moved by `applyFemPositions` like any base |

So a ghost built from `buildHelixObjects` alone had **no extra-base geometry at all**, while
tails already worked. `_buildState` now also calls `buildCrossoverConnections` into the
ghost group and places the inserts itself (`_placeExtraBases`), mirroring
`design_renderer.applyClusterCrossoverUpdate`. Ordering is load-bearing:

1. `partitionExtraBaseUpdates` BEFORE `applyFemPositions` — the helix controller cannot
   place `__xb__` rows, and you need `simXb` anyway.
2. insert placement AFTER it — the no-sim-data fallback threads a Bezier between the arc's
   two endpoint nucleotides, which must have moved first.
3. `_setGroupOpacity` AFTER `group.add(xo.group)` — it traverses, so a subtree attached
   later keeps opaque materials.

**Latent bug fixed at source:** `crossover_connections.js` allocated `GEO_SPHERE` /
`GEO_UNIT_BOX` / `GEO_UNIT_CONE` at module level but never marked them
`userData.shared`. The ghost's traverse-and-dispose skips only flagged geometry, so the
first ghost teardown would have disposed the templates the **main model's** extra-base
meshes still draw from. Marked shared (same convention as `helix_renderer._markShared`),
which also closes the identical hazard in `assembly_renderer`'s orphan cleanup.

Verified on job `012a0fbe2de2` (6hbx100_1xT, 60 inserts): every insert is drawn at its
simulated coordinate — `frontend/e2e/occupancy_extra_bases.spec.js`. Two traps that cost a
run each there: bead instances are ordered by the design's crossover iteration while
payload keys follow the strand walk (compare SETS, never index-for-index), and a job's
`design_source_path` is a bare filename the backend resolves against the REPO ROOT
although designs live in `workspace/`.

## NAMD equivalent (2026-08-01)

`GET`/`POST /md/jobs/{id}/occupancy` → `md_trajectory.md_occupancy`. Same payload shape as
the oxDNA twin, so the same overlay, controls card and display mode draw it unchanged.

**The engine-agnostic core now lives in `backend/core/occupancy_core.py`** — PCA, k-means,
medoids, the switching/drift/unimodal verdict, `resolve_selection_keys`, `_selection_sig`,
`occupancy_confidence`, `_superpose_on_subset`. Both engines import it; `oxdna_occupancy`
re-exports for compatibility. This is safe because **MD and oxDNA speak the same nucleotide
keys** — `atomistic_to_nadoc.md_pkey` emits the identical tuples including `("__xb__", …)`
and `("__ext_<id>", …)`, so scoping and clustering transfer verbatim.

**What MD does NOT share, and must not:**

- **No `a3`.** MD's per-frame value is the P atom — already the backbone site — where oxDNA
  stores a centre of mass from which the site is *derived* via `oxdna_backbone_sites`.
  Feeding MD data to `occupancy_features` would fabricate an offset. `md_occupancy`
  assembles its own features; pinned by `test_md_does_not_route_through_oxdna_feature_assembly`.
- **No FENE gate.** `FENE_R0_OXDNA2` is an oxDNA potential, not a calibrated NAMD frame
  check. (If one is ever wanted, `md_health.C1_PAIRED_MAX_DEFAULT` is the MD-native cutoff.)

**Only PRODUCTION segments form the ensemble — a POSITIVE match on `"production"`.**
`md_production_segments` / `mdHasProductionRun` keep segments whose stage label contains
that word, and there is no opt-in and **no fallback**: a job with only equilibration
returns *"no production run yet"* rather than clustering its ramp.

Every production builder puts the word in the label, which is why the positive test works:

| builder | label |
|---|---|
| `routes_md` (Run production) | `"<N> ns <fast\|medium\|conservative> production run"` |
| `md_ensemble` | `"<N> ns production replica (seed <n>)"` |
| `md_protocols` | `"310K NPT conservative production <N> ns unrestrained"` |
| `md_shell_reprep` | `"shell NVT production (COM-restrained, HMR 4 fs)"` |

**This replaced a keyword-EXCLUSION filter that was badly wrong.** The first version kept
segments carrying none of `enm`/`fixed`/`minim`, built from the four `SegmentSpec` sites
that happen to spell restraint "ENM". Dumping the distinct stage labels across all 85 MD
jobs on this machine showed protocols that encode restraint as **`k=<value>`** instead —
and the exclusion filter admitted **every one** of:

```
50K / 100K / 200K / 300K NVT k=5.0             heating, restrained
310K NPT k=5.0 → 4.0 → … → 0.01  (11 stages)   restraint ramp
Vacuum ENRG-MD shape relaxation                restrained; "ENRG-MD" is not "ENM"
solvent equilibration (DNA position-restrained, NVT)
310K NPT unrestrained qualification            unrestrained, but a probe not sampling
```

i.e. the whole relaxation schedule. **Never enumerate "restrained" keywords here** — there
is no closed set. Match production positively; unknown labels then fail closed, which for
this feature is the safe direction.

Note `"300K NPT k=0"`, the ENM ladder's terminal unrestrained stage, is also excluded: it
is unrestrained but still equilibration. Consequence on the real job set — **17 of 85 jobs
have a production segment and get occupancy; 15 that stop at the ladder correctly do not.**

**Measured on a real production run** (`6fc87681f9de`, 24hb_0xT, 50 ns production replica,
6720 nt): **18.7 s**, 30 of 30 frames, verdict `drift`, PC1 0.35, n_eff 2.81 (preliminary).
An earlier "36.1 s / 30 frames" figure in this file came from `383f7dcc4a5d`'s terminal
EQUILIBRATION stage, before the filter was corrected — that job has no production run and
now returns not-ready.

**No shareable frame cache, and this is the dominant cost.** Every MD analysis runs through
`md_analysis_runner` in a spawned, killed-on-exit subprocess, so nothing a child computes can
be memoised and there is no `_ALIGNED_CACHE` equivalent to piggyback (oxDNA occupancy is
nearly free after a trajectory scrub; MD is never free). Mitigation is a result-level LRU in
`routes_md._MD_OCC_CACHE`, keyed on per-DCD size+mtime so a growing run self-invalidates: a
re-toggle is free, a parameter change is a full re-read.

**Measured** on `383f7dcc4a5d` (24hb_0xT, 6720 nt, 120 frames): **36.1 s**, sampling stages
`['300K NPT k=0']` → **30 of 120 frames**, verdict `drift` (1 transition, n_eff 2.66,
preliminary). 30 free frames is too few to resolve states — a property of these runs, not of
the feature. A longer unrestrained stage is what would make MD occupancy informative.

**Frontend:** `initOccupancyControls({engine, ids, fetchOccupancy})` is now id-parameterised
(`occupancyIds(prefix)`) and takes an injected fetch, because the two clients have genuinely
different signatures (oxDNA options-object, MD positional `(id, signal, opts)`). One overlay
serves both cards, so whichever activates last claims it and stands the other down via
`nadoc:occupancy-active` — otherwise the loser's list would keep describing states no longer
on screen. `mdViz` needed `onOccupancyClear` (it had none), or toggling off left ghosts.

### Three init-order bugs the NAMD work surfaced (all caught only by e2e)

Adding a second engine's card exposed how brittle the panel/init ordering is. None of these
were visible to 6232 backend + 4356 frontend unit tests:

1. **A toggle added to `_syncVizOffRadio`'s `anyOn` array must be DECLARED with its peers.**
   That function runs during init (via `_updateVizToggles`), so a `const occupancyToggle`
   further down the file is a TDZ that aborts **the whole app's boot** — the symptom is an
   unrelated "`__nadocOccupancy` is undefined", because `main()` never finished. Declare
   beside `flexToggle`/`trajToggle`.
2. **Extracting the shared core silently dropped `_OCCUPANCY_CACHE`.**
   `production_occupancy_cached` declares `global _OCCUPANCY_CACHE`; with the name gone,
   every oxDNA occupancy request died with a `NameError` while the whole unit suite stayed
   green, because nothing there calls the cached wrapper. Pinned now by
   `test_cached_wrapper_resolves_its_module_globals`.
3. **A `bluntEnds` TDZ that was NOT a real bug.** It appeared only while boot was already
   broken; once (1) was fixed the spec passed without touching it. Forward-declaring it was
   reverted — worth remembering that a TDZ deep in `main.js` can be a *symptom* of an
   earlier init failure rather than its own defect.

Order of discovery matters here: each masked the next, and a truncated `tail` of the
Playwright output made me report a fix as working when the spec was still red. Read the
whole failure block.

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

## Files

| File | Role |
|---|---|
| `backend/core/occupancy_core.py` | the engine-agnostic core: scoping, **the fit plan**, PCA, k-means, medoids, the verdict |
| `backend/core/oxdna_occupancy.py` | oxDNA feature assembly (nt/bp basis, FENE gate) over that core |
| `backend/core/md_trajectory.py` | `md_occupancy` — NAMD feature assembly over the same core |
| `backend/api/routes_oxdna.py` | `GET .../occupancy`, `POST .../occupancy` (selection + `fit`), `_OCC_PROGRESS` |
| `backend/api/routes_md.py` | the NAMD twin + `_MD_OCC_CACHE` (no shareable frame cache exists) |
| `frontend/src/scene/occupancy_overlay.js` | one copy per state (build, tint, opacity, LOD, per-state show/recolour, dispose) |
| `frontend/src/ui/occupancy_controls.js` | DOM, params, cache, scrollable state list, network |
| `frontend/src/ui/oxdna_display.js` | `_mode = 'occupancy'`, `displayOccupancy`, `onOccupancyClear` |
| `frontend/src/api/client.js` | `getOxdnaOccupancy` / `getOxdnaOccupancyProgress` |
| `tests/test_oxdna_occupancy.py` (26) · `occupancy_overlay.test.js` (46) · `occupancy_controls.test.js` (41) · `e2e/occupancy_clouds.spec.js` | |

## Reuse — nothing here was written twice

`_aligned_downsampled_frames` (frames, unwrap, Kabsch, `_ALIGNED_CACHE`) ·
**`twist_series_stats`** (`oxdna_health.py:387`) returns `{tau_int, n_eff, sem}` — feed it a
cluster's 0/1 membership series and `mean` IS the population, `sem` IS its honest error ·
`_fene_violation_fraction` + `_STRAIN_FRAME_REJECT_FRAC` (torn-frame gate) ·
`_strain_index(design, keys, "wc")` (bp pairing) · `_flatten_cg_frame` (wire format) ·
`buildHelixObjects` (ghost copies). **scipy only — scikit-learn is NOT installed.**

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

## Measured on real data

| Job | nt basis | bp basis | Verdict |
|---|---|---|---|
| `exp35_.../14b896dab3c2` (540 nt, 50 prod frames) | PC1 0.78, sil +0.58 | PC1 0.83, sil +0.59 | **drift** — 1 transition, n_eff 2.6 |
| `exp31_.../0cc5368fbfda` (14 494 nt, 108 prod frames) | PC1 0.27, sil +0.23 | PC1 0.29, sil **+0.25** | **switching** — 24 transitions, 12–13 visits/state, n_eff 54, 71 %/29 % |
| **`5ce768ef2acf` VoltronCore · field** (14 774 nt, 50 prod frames) — live `:8000`, via the route | PC1 **0.47**, sil +0.39 | PC1 0.52, sil +0.34 | **switching** — 9 transitions, 5 visits/state, n_eff 24.7 (*preliminary*), **74 %/26 %**, medoids **2.29 nm** apart |

VoltronCore behaves as the user predicted: two distinct configurations, a genuinely dominant
PC1, and enough recurrence to call them states — though `n_eff 24.7` sits just under the
`OCCUPANCY_PRELIM_NEFF = 25` bar, so the UI flags the populations as not yet converged.

The exp31 job straddles the 0.25 floor: `nt` says unimodal, `bp` says switching. The floor
is doing real work, and basis choice matters at the margin — which is why `basis` is a
user-facing control rather than a constant. Default is `nt` (matches RMSF's atom set).

Forcing `n_clusters=3` on VoltronCore correctly flips the verdict to **drift**: the third
cluster is a single frame visited once, and the recurrence guard refuses to call an outlier
a state. Cache behaved as designed — first call 20.8 s, second 0.12 s.

## Verified in the app

`frontend/e2e/occupancy_clouds.spec.js` **passes** on the VoltronCore job (`5ce768ef2acf`,
~1.5 min): job select → radio → request → verdict → legend → **ghosts present in the scene**
→ switch to the flexibility map → ghosts gone → no console errors. Screenshot at
`frontend/e2e/screenshots/occupancy-clouds.png` shows the design in its own colours with a
translucent gold state-2 ghost superposed, legend reading
`74 % ± 9 %` / `26 % ± 9 % · 2.29 nm from state 1`, and the ⚠ under-sampling line.

Note the e2e backend is a throwaway on a dedicated port but resolves the SAME on-disk
workspace, so it sees the real jobs — the run never touches the user's `:8000` process.

**Four e2e-harness traps, all of which cost a full run to find** (they are about the app's
panel chrome, not this feature — expect them in any new oxDNA spec):

1. `#oxdna-jobs-heading` **no longer exists** — engine panels are tab-fronted, oxDNA is the
   selector's default tab, so the panel is already up once Dynamics is open.
2. `#oxdna-jobs-list` is a **hidden legacy node**; the visible list is `#simulate-jobs-list`,
   whose rows are scoped to the active design. Selecting via the hidden list (after setting
   `#oxdna-jobs-show-all` programmatically) is what works.
3. **Load the design THROUGH THE PAGE** (`import('/src/api/client.js').loadDesign`). A bare
   `POST /design/load` sets backend session state the booted page never syncs, leaving
   `currentDesign`/`currentGeometry` null — the ghosts then silently build nothing, and the
   panel still looks fine because it needs no design.
4. The in-progress status is "Clustering **configuration**s…", so a `/configuration/` regex
   races the fetch and passes before any result exists. Match a terminal verdict.

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
