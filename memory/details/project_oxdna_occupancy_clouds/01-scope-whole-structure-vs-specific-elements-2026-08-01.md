# Scope: whole structure vs specific elements (2026-08-01) — supporting detail

[Topic head](../../project_oxdna_occupancy_clouds.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
