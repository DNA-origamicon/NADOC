# ✅ FIXED 2026-07-31 — resumed runs were analysed at ~1/3 coverage — supporting detail

[Topic head](../../project_cpd_umbrella_sampling.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ✅ FIXED 2026-07-31 — resumed runs were analysed at ~1/3 coverage

`routes_md._md_segment_dcds` took **one** DCD per segment (`max(dcds, key=mtime)`),
treating `.cont1.dcd` as a *replacement* for the base `.dcd`. They are sequential pieces:
`md_protocols` re-emits a resume conf with `firsttimestep <restart_step>` and only the
**remaining** steps, writing to `cont<k>.dcd`. Confirmed on the run created 2026-07-30
15:26 — base 0.10–104.30 ns, cont1 104.40–161.90 ns, one frame apart, no overlap.

Every consumer inherited it: RMSF, the metrics card, the scrub view, the weld trace all
saw **36% of the run** and reported nothing wrong.

Now returns **one entry per DCD, ordered by the trajectory's own clock** (`_dcd_first_step`,
a header read). mtime reorders when a file is archived or re-touched; name sorting puts
`cont10` before `cont2`. Tiebreak sorts the base first, because equal keys otherwise keep
the glob order — which lists `cont*` first (a test caught exactly this).

Live result on that run: **576 → 1619 frames, 0.1 → 161.1 ns**, and d_min/d_mean now match
the Phase 0 direct-load numbers exactly — the route and the offline analysis agree.
Window seeding improved 4/13 → **5/13**. Regression: `tests/test_md_segment_dcds.py`.

**Overlap is possible in principle** (a checkpoint behind the last written frame, when
`restartfreq` does not divide `dcdfreq` — NADOC's 5000/25000 always does). Logged, not
dropped: a few double-counted frames skew an average slightly, where dropping a whole
piece loses real trajectory. `md_health._latest_segment_dcd` is a DIFFERENT function that
genuinely wants the newest (it probes current state) — deliberately unchanged.

**Side-fix 2026-07-31 — the trajectory-scrub view now has sticks.** `md_atomistic_model`
served `bonds: []` with a note to port ws.py's version "when the scrub view needs sticks";
watching the weld overlay on a finished run is exactly that. `heavy_bond_pairs` now lives
in `md_trajectory.py` and `ws.py` delegates to it (same serial space, one owner).
**The wire shape differs per consumer and that is load-bearing:**
`atomistic_renderer._rebuild` reads a **typed** array as flat and a **plain** array as
nested, so the REST path must send `nested=True` — a flat plain list renders zero sticks
and reports no error. Live WS keeps flat (it goes through `toBondPairs`). Verified: the
2hb_1xT scrub model went 0 → **2204 bonds**, `bonds_available: true`, no end outside the
atom set. Also had to add `|| model.bonds?.length > 0` to `oxdna_display`'s
`_atomTopoBonds`, or a vdw→ballstick flip re-fetches bonds it already holds.

**Refer to jobs by part + creation time, never by hex job_id**
([[feedback_refer_to_jobs_by_part_and_time]]) — the frontend exposes no job ids, so a
verification request naming them cannot be acted on. Note part+minute is not always
unique: two 2hb_1xT runs here share 2026-07-28 16:39.

## Phase 1 — what shipped (the weld is visible in 3D)

| Piece | File |
|---|---|
| Pair identity + geometry (analysis) | `backend/core/cpd_metrics.py` |
| Route `GET /api/md/jobs/{id}/cpd-pairs` | `backend/api/routes_md_metrics.py` |
| Geometry (viewer) | `frontend/src/scene/cpd_geometry.js` |
| 3D overlay | `frontend/src/scene/cpd_weld_overlay.js` |
| Client fn `getMdCpdPairs` | `frontend/src/api/client.js` |
| Reusable CLI | `scripts/measure_cpd_coordinates.py` |
| Shared cross-language fixture | `tests/fixtures/cpd_reference_cases.json` |

**Two architectural decisions worth not re-litigating:**

1. **The backend sends atom SERIALS, never coordinates.** The viewer computes d_mid/η from
   the frame it is already rendering. This is forced: the MD display affine is *handed
   over, not re-derived* ([[project_md_viz_tools]]), so a second coordinate path would
   draw the markers offset from the atoms. The overlay is driven from **inside**
   `atomistic_renderer.applyPositionLerp`, using the same `_atomXYZ` placement the atom
   instances get. Under an active cluster transform (rigid-body branch, keyed by helix_id
   — an identity serial-only pairs cannot supply) it is fed `null` and **hides itself
   rather than drawing at a wrong position**.
2. **The geometry exists twice (Python + JS) on purpose, and is pinned.** Both assert
   against `tests/fixtures/cpd_reference_cases.json`. Change one without the other and the
   tests go red instead of the screen quietly disagreeing with the analysis. Regenerate
   that fixture deliberately, **never** to make a failing test pass.

Colour = KIMMDY propensity k: red far → amber approaching → green reactive. Sub-vdW
separation is flagged (`belowVdw`) because the force field cannot really represent it.

Tests: `tests/test_cpd_metrics.py` (20), `frontend/src/scene/cpd_geometry.test.js` (28),
`cpd_weld_overlay.test.js` (21, incl. real-three.js mesh placement/aim/recolour/dispose).

**Verified live:** the route returns the right pair with resolved serials
(C5 241/948, C6 233/940) on real jobs `ccdcdca7675a`, `c8bcf4c1406f`, `29c5b267380f`.
**NOT yet watched in the browser against a moving trajectory** — that is the first thing
to do next session.

## The target — verified from the design, not assumed

| Fact | Value | How |
|---|---|---|
| Design | `workspace/2hb_1xT.nadoc`, 2 helices, 3 strands, HONEYCOMB | design file |
| Extra-base crossovers | bp **13** and bp **14**, antiparallel **reciprocal** | `crossover_connectors()` |
| Designed pairing | `reciprocal_pairs: [(0, 1)]` | `junction_topology` |
| Extra bases | 1 × T each (`n_inserts=1`) | design |
| Scaffold forced ligation, bp 30 | 0 inserts — **not a target** | design |
| **Designed T–T pairs** | **exactly 1** | — |
| `photoproduct_junctions` | `[]` — schema hook exists, unpopulated | design |

There is no candidate-ranking problem here: the pair is a topological fact. Pair selection
must come from **design intent** (`reciprocal_pairs`), never spatial proximity.
