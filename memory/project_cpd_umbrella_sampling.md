---
name: cpd-umbrella-sampling
description: "Free energy of the designed CPD weld between extra crossover bases (2hb_1xT). Phase 0 done: unbiased 161.8 ns says the weld NEVER forms (min d 7.44 A, reactive corner 0.000%). CV pair is (d_mid, eta), frame-free. Read before touching colvars/US/free-energy work."
metadata:
  node_type: memory
  type: project
---

# CPD umbrella sampling — free energy of the designed extra-base weld

**The question.** `2hb_1xT` places one extra T at each of two reciprocal crossovers so they
can photo-weld (UV point welding, Dietz-style CPD formation). **Does the physics support that
design choice?** We are testing it, not assuming it.

## ▶ RESUME HERE (2026-07-31)

**Phase 0 DONE** — unbiased 161.8 ns says the weld does not form spontaneously.
**Phase 1 (VISUALISATION) SHIPPED** — the weld pair is now drawable in the 3D scene, see
below. **Priority is SEEING, not science, for now** (user, 2026-07-31): 1xT is the target
because its single pair is the tractable case for tool development.

**The UI toggle SHIPPED 2026-07-31**: MD jobs panel → Visualizations card →
**"Weld pair (CPD)"** checkbox, under Water / Ions / Periodic box. Ticking it loads the
selected job's pair and shows a live `d / η / k` readout beneath. Most designs have no
weld pair; the control says so plainly rather than erroring.

**The TRACE PANEL SHIPPED 2026-07-31** — same card, a **"Trace over run"** button +
metric selector (distance / twist η / propensity k) + chart + summary. The overlay answers
*"how close right now"*; the trace answers *"did they EVER get close"*, which is the actual
design question. Background start/poll (`POST /md/jobs/{id}/cpd-trace/start`,
`GET /md/cpd-trace/{id}`), charted with `metric_graph`'s existing `buildChartSpec`/
`drawChart` cores — no new charting code.

Verified live on the 2hb_1xT run created 2026-07-30 15:26: `d_min 7.44 Å`, `d_mean 11.47 Å`,
`k_max 0.142`, **reactive_frames 0** — the Phase 0 result, now visible as a curve.

Two things the trace deliberately does:
- **Widens the stride, never truncates** (`trace_stride`). A series over the first N frames
  of a long run reads as "never got close" when the run simply was not looked at past N.
- **Plots time in ns, not frame index** — once the stride widens, a frame index means nothing.

**Next:** watch it in the browser on that run, then Phase 2 (the 2D PMF).

## ⚠ FOUND 2026-07-31, NOT FIXED — resumed runs are analysed at ~1/3 coverage

`routes_md._md_segment_dcds` takes **one** DCD per segment — `max(dcds, key=mtime)` —
treating a `.cont1.dcd` as a *replacement* for the base `.dcd`. On the 2hb_1xT run created
2026-07-30 15:26 they are **strictly sequential**, not alternatives:

```
2hb_1xT_01_production_500ns_k0.dcd        1043 frames    0.10 -> 104.30 ns
2hb_1xT_01_production_500ns_k0.cont1.dcd   576 frames  104.40 -> 161.90 ns
```

One 100 ps frame apart, no overlap. So every consumer of the job's segments sees only the
**last 57.6 ns of 161.9 ns — 64% of the run is dropped**: RMSF, the metrics card, the
trajectory scrub view, and the weld trace. (Phase 0's numbers are NOT affected — that
analysis loaded both DCDs directly.)

Fix is small — concatenate base + `cont*` in time order instead of picking the newest —
but it changes results for **every resumed job across several features**, so it wants a
deliberate decision + revalidation, not a drive-by. Not done. Confirm whether any protocol
writes a continuation that genuinely *restarts* the trajectory before assuming append.

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

## The collective variables — (d_mid, eta), and they are FRAME-FREE

The KIMMDY geometric rate (`~/Work/kimmdy-namd-cpd/src/kimmdy_namd_cpd/rate.py`) is

```
k = exp( -( k1·|d − d0| + k2·|η − η0| ) )
  k1 = 2.017 nm⁻¹   k2 = 0.0300 deg⁻¹   d0 = 0.157 nm   η0 = 16.74°
```

`d = |0.5·((C5₂−C5₁) + (C6₂−C6₁))|` simplifies exactly to **the distance between the two
C5=C6 bond midpoints**. So both CVs are Colvars-native:

- **d_mid** — `distance` between two atom groups, each `{C5, C6}`. C5 and C6 are both carbon,
  so centre-of-mass == centre-of-geometry == the bond midpoint. No `customFunction` needed.
- **eta** — `dihedral` on (C5_a, C6_a, C6_b, C5_b).

**Do NOT add C6–C6 as a third axis.** C6 is already inside `d_mid` as the midpoint. A third
axis would be near-collinear and does not enter the rate. The rate-relevant space is 2D.

**Reference implementation already exists** (hand-written, use as the format oracle):
`/media/jojo/Archive/NAMD/CPD_1xT/colvars_cpd_metrics.in` — same two CVs. Its sibling
`colvars_cpd_smd.in` steers d_mid 7→5 Å at k=0.25.

Being internal coordinates, they need **no body-fixed frame** — which matters, see below.

## Phase 0 result — the weld does not form (161.8 ns unbiased, k=0)

Job `ccdcdca7675a`, `2hb_1xT_01_production_500ns_k0` (+ `.cont1`), 62,677 atoms, 4 fs,
100 ps/frame, **1619 frames / 161.8 ns**, every frame measured.

| quantity | value |
|---|---|
| d_mid | mean **11.39 Å**, sd 1.38, **min 7.44 Å**, max 17.97 |
| η | mean +31.5°, sd **95.6°**, full ±180 range |
| frames d < 8 Å | 10 (0.62%) |
| frames d < 6 Å | **0** |
| **reactive corner** (d<4.5 Å ∧ \|η−η₀\|<45°) | **0 / 1619 = 0.000%** |
| stationarity, d_mid 1st/2nd half | 11.33 / 11.46 Å — equilibrated, no drift toward contact |

**Interpretation.**
1. The two extra Ts sit ~11.4 Å apart and never approach within 7.4 Å. The weld is not
   spontaneously accessible on this timescale.
2. **η is essentially free** (sd 95.6°, samples all ±180°). The torsional coordinate costs
   little at this separation — **the barrier lives in d, not η.** A 1D PMF in d with η as a
   passive observer may be nearly sufficient; η should still be a CV at close range.
3. This is the opposite of the AutoNAMD reference system, where ⟨k⟩ converged on unbiased MD.
   Here umbrella sampling is **required**, not a refinement.

**The as-built seed η (−178.5°) is meaningless** — the insert spin DOF is a free parameter
the joint solve is indifferent to ([[project_crossover_catenation]]). Only MD-relaxed η counts.

## 1xT vs 2xT — one T cannot reach, two can (suggestive, not yet conclusive)

Same measurement, `2hb_2xT` job `bfd050d2ce4c`. 2xT has 2 inserts per crossover → 4 pair
combinations.

| design / pair | frames | d mean | d min | η sd | reactive |
|---|---|---|---|---|---|
| **1xT** k0~k0 | 1619 / **161.8 ns** | 11.39 Å | 7.44 | 95.6° | **0.000%** |
| **2xT** k0~k0 | 115 / 11.4 ns | **6.38 Å** | **3.65** | **20.8°** | **6.96%** |
| 2xT k1~k1 | ″ | 6.11 Å | 3.63 | 128.4° | 0.000% |
| 2xT k0~k1 | ″ | 8.69 Å | 6.24 | 102.0° | 0.000% |
| 2xT k1~k0 | ″ | 9.60 Å | 7.15 | 155.7° | 0.000% |

**Reading.** The 2xT k0~k0 pair reaches reactive geometry ~7% of frames within 11.4 ns; 1xT
never does in 161.8 ns. Its η sd of 20.8° (vs 95.6° for 1xT) says that when the tips are in
contact they are *ordered* — π-stacked, near the [2+2] geometry — rather than diffusing.

**Caveat, important.** The 2xT run is only **11.4 ns** and was stopped early, and its seed
already started at d = 4.86 Å where 1xT's started at 11.18 Å. Part of the difference may be
seed memory rather than equilibrium. The 1xT half of the comparison IS solid (161.8 ns,
stationary). **To make this conclusive, run 2hb_2xT unbiased to ≥100 ns and re-measure.**
That is the cheapest high-value experiment available.

Only ONE of the four 2xT combinations is reactive — so "2xT works" is really "one specific
insert pairing works". Which k-index pairs with which is a design detail worth understanding.

## Scope limit — the PMF bottoms out at vdW contact

`d0 = 1.57 Å` is a *cyclobutane C–C bond* — the product. A classical force field cannot reach
it. The useful PMF range is **~3.4 Å (vdW contact between ring midpoints) → ~12 Å**. ⟨k⟩ is
integrated over that range only; the last 2 Å to product is QM territory and out of scope.
So the umbrella must close **~8 Å**, from 11.4 down to ~3.4.

## HARD GATE — topology must be clean before and after every run

[[project_crossover_catenation]] records that a catenated junction **"mimics a soft rotational
hinge"** and is **invisible to C1′/WC health checks** (an affected 2hb_1xT run reported
`c1_paired_fraction = 1.0`). The hinge it fakes is torsional — i.e. exactly η. An F(d,η)
surface is uniquely vulnerable to this defect and would look entirely plausible while being
wrong. Catenation was fixed 2026-07-28; the ring-piercing defect (which the catenation repair
was itself manufacturing) shipped **2026-07-31**, so builds between those dates can pass
catenation and still be pierced.

Verified clean 2026-07-31:

```
scripts/check_catenation.py workspace/2hb_1xT.nadoc     -> catenated 0/1, pierced 0
scripts/check_ring_piercing_frame.py <pkg>/2hb_1xT.psf <both dcds> --stride 200  -> 0
```

Run **both** gates on the seed *and* the final frame of every umbrella window.

## Frame rigidity — why the 3D Cartesian map is demoted

Measured (see the archive for the full tables): a body-fixed frame built from **multiple**
junction arms is not rigid — 8.65 Å RMSD on the AutoNAMD junction; trimming 7 bp → 3 bp does
not help (junction-core articulation, not end fraying); motion is continuous, not discrete
conformers, so per-conformer maps are not available as a rescue.

| local group, 12 Å radius | RMSD |
|---|---|
| isolated Holliday junction | 4.63 Å |
| **2hb origami crossover** | **2.83 Å** (85 frames only — a lower bound) |

The lattice helps ~1.6× but even the origami is marginal. **Rule: never build the frame from
multiple arms; use a single ~12 Å local neighbourhood and carry ~3 Å blur as explicit map
uncertainty.** A 3D Cartesian PMF is therefore a *qualitative* candidate-finder, not the
quantitative reactive surface. It earns its cost on `24hb_1xT` (338 extra T) /
`6hbx100_1xT`, not on 2hb_1xT which has exactly one pair.

## Phased plan

- **Phase 0 — unbiased baseline.** ✅ DONE (above).
- **Phase 1 — colvars emitter.** Populate `photoproduct_junctions` from `reciprocal_pairs()`;
  emit `d_mid` + `eta` per declared junction. Oracle: structural match to
  `colvars_cpd_metrics.in`. Shaped for `/automate-feature`.
- **Phase 2 — 2D F(d, η).** eABF, all-atom, d ≈ 3.4 → 12 Å, η periodic. Validate one d-slice
  against a 1D umbrella ladder. ~1.7 days at 4 fs / ~360 ns/day for 4 walkers × 150 ns.
- **Phase 3 — 3D map (oxDNA/LAMMPS).** Blocker first: confirm `fix colvars` sees oxDNA
  ellipsoids at all (untested; `fix colvars` reads positions/forces, not quaternions/torques,
  so orientation CVs are likely unavailable — bias on COM, reweight to base site).
- **Phase 4 — ⟨k⟩ reweighting + authoring UI.**

## Corrections and dead ends — do not repeat

- **⟨k⟩ does NOT need enhanced sampling on the reference system.** An early claim that
  unbiased averaging under-samples the reactive tail was wrong: on the AutoNAMD junction ⟨k⟩
  drifts +2.9% over the last half and 50% of Σk comes from the top 18% of frames — broad, not
  a rare-event tail. US is for the *landscape*, not the rate number. (On 2hb_1xT US **is**
  needed, but because the pair starts 11.4 Å apart, not because of tail statistics.)
- **KIMMDY's `|η − η0|` is not periodic-aware.** At η = −175° it returns 191.7° where the true
  separation is 168.3°, underestimating k ~2×. Only matters in the antiparallel region.
- **AutoNAMD designs are REFERENCE ONLY, never production.** Its KIMMDY off-target hits
  (AN1:T34–BN1:T6 etc.) are not of interest — they are artifacts of that construct.
- **PBC unwrapping is mandatory** before any geometry measurement on these trajectories, and
  per-fragment unwrap is not enough — the strands must also be brought into a common image.
- **Do not hand-roll Kabsch.** A transposed covariance is silent and returns plausible-looking
  large RMSDs. Use `MDAnalysis.analysis.rms.rmsd(..., superposition=True)`.

## Tooling

- `scripts/measure_cpd_coordinates.py` — measures (d_mid, η, k) for a design's declared
  extra-base pairs over any package trajectory. Identifies the extra bases two independent
  ways (WC geometry + the design's insert walk) and refuses to measure if they disagree.
- Gates: `scripts/check_catenation.py` (design), `scripts/check_ring_piercing_frame.py` (built
  structure / trajectory).
- Reference only: `~/Work/AutoNAMD` (window ladder, MBAR via `autonamd/free_energy.py`,
  overlap-index QC), `~/Work/kimmdy-namd-cpd` (the rate model).

## Related

[[project_crossover_catenation]] · [[project_extra_base_4fs_geometric_fixb]] ·
[[project_oxdna_extra_bases]] · [[project_md_job_system]] · [[project_lammps_oxdna]]
