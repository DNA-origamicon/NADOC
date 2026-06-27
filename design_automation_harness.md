# design-automation harness reference (do-not-rebuild)

Extracted from the backlog's `## Next-session handoff` (2026-06-25), which had grown to ~895 lines of
appended `▶ HARNESS NOW AVAILABLE` blocks — re-read every loop for no reason. **This is reference, not a
per-loop read.** Consult ONLY the block for the item you are extending. Each block is the SHIPPED wrapper's
call signature + its validation augment + banked gotchas — so you don't rebuild or re-derive it. The matching
oracle catalog row lives in `design_automation_log.md`; the metrics row in `design_automation_metrics.md`.

## Index (shipped wrappers — do NOT rebuild)

- AF-33 P1 hinge-primitive builder (2x2)
- AF-30 strand end-resize
- AF-32 forced-ligation place/delete
- AF-31 manual crossover place/delete
- AF-29 hinge ssDNA flexible-relax
- AF-27 P1 overhang-linker tie
- AF-12 Phase 2b parametric circle
- AF-22 live steering
- AF-21 live engine
- AF-23 campaign
- AF-20 field sweep
- AF-19 equilibration timeline
- AF-18 field-specimen builder
- AF-12 P2 `from_primitive`
- `polymerize_periodic` straggler
- AF-12 follow-up — file-backed layout
- AF-12 P1
- AF-13 P6
- AF-13 P5
- AF-13 P4
- AF-17
- AF-13 P3
- full-sequencing feature
- AF-13 P1
- AF-13 P2
- AF-16
- AF-14 P3
- AF-14 P2
- AF-11
- AF-10
- AF-9 overhang-bindings
- AF-9 polymerize
- AF-9 belts
- AF-9 gears
- AF-8
- AF-7
- AF-1..AF-6 foundational oracles

---

## Harness reference blocks + archived handoff history

_Below: the verbatim `▶ HARNESS NOW AVAILABLE` blocks, plus the historical handoff narrative
(audit notes, priority-track scoping, Tier-6/7 as-built assessments) that preceded them._


> **■ HARNESS NOW AVAILABLE — AF-33 P1 hinge-primitive builder, 2x2 (2026-06-26).**
> - `from backend.api.headless_hinge_build import build_hinge_primitive` →
>   `build_hinge_primitive(name="2x2_single_hinge_link", *, lattice=LatticeType.SQUARE) -> Design` — recreates a
>   standard hinge primitive FROM SCRATCH (returns a standalone deep copy, runs in a scratch session). Composes the
>   shipped wrappers ONLY — `hb.create_bundle` → `_shift_duplexes(+8)` → per-bridge `hb.resize_strand_end`+`hb.force_ligate`
>   — introduces NO new route (coverage stays flat). `HINGE_PRIMITIVE_NAMES` lists supported names; **P1 ships only
>   `2x2_single_hinge_link`** — 2x4/2x6 raise `KeyError` (AF-33 P2). Builds carry a real `bundle-create` feature-log entry.
> - **Augment — NEW `assert_matches_primitive(design, primitive_name, *, primitives_dir)`** (golden-equality):
>   `canonical_topology` == golden AND `_fl_endpoint_set` == golden (LOAD-BEARING — topology fingerprint is blind to
>   `forced_ligations`) AND `roundtrip_nadoc`-stable (topology + FL-set) AND `validate_design`. `primitives_dir` =
>   `Path("workspace/Primitives")` (tests run from repo root; skip-if-missing — goldens are hand-built, may be absent).
>   Reusable `_fl_endpoint_set(design)` is the canonical order-independent FL comparator.
> - **GOTCHA — replay the golden's feature-log recipe VERBATIM (don't shortcut).** The 2x2 recipe lives in the
>   golden's own log: `create_bundle(len=40, ligate_adjacent=True)` → resize EVERY helix's low-bp end +8 (shift duplex
>   into bp 8…39, derived mechanically from live domain directions) → 2 ASYMMETRIC gap-bridge `(resize, force_ligate)`
>   pairs (`scaf_1_0` 3p −3 / FL→`scaf_4_0`; `scaf_1_1` 5p −16 / FL `scaf_4_1`→). `create-at-40-then-shift` (NOT
>   `create-at-32`) is load-bearing — AF-30 ISSUE-13 axis re-trim means only the same op sequence reproduces the golden's
>   axis floats. The bridge trims are HAND-AUTHORED gap geometry (constant, not re-derived — ASK-FIRST). To extend to
>   2x4/2x6: decode the sibling goldens' `RoutingClusterLogEntry.children` params the same way (the recipe is recorded).
>
> **■ HARNESS NOW AVAILABLE — AF-30 strand end-resize (2026-06-26).**
> - `from backend.api import headless_build as hb` →
>   `hb.resize_strand_end(strand_id, helix_id, end, delta_bp) -> Design` where `end ∈ {"5p","3p"}` and `delta_bp`
>   is SIGNED (positive = toward higher global bp). Single-entry mechanical pass-through over
>   `POST /design/strand-end-resize` (the cadnano drag-arrow); the route also accepts a batch `entries: [...]` but
>   the wrapper exposes the common single-end case. Grows/shrinks the named strand's terminal domain; the helix
>   axis grows/re-trims to the strand-coverage union. Records a `strand-end-resize` minor-log entry.
> - **No new oracle — REUSE two proven ones:** (1) `assert_geometric_length_delta(start, op, δ, helix_id=h)`
>   (AF-3) — the load-bearing pin: a `+δ` resize adds exactly `δ×2` nucleotides on helix `h`. (2)
>   `assert_inverse_pair(start, forward=+δ, inverse=−δ)` (AF-2) — `−δ` exactly undoes `+δ` on the strand bp-range.
> - **GOTCHA — pick a strand whose terminal domain DEFINES the helix extent**, else the geometry count won't move.
>   In a 2hb HC `[[0,0],[0,1]]` each helix carries a scaffold AND a staple both spanning `[0, len-1]`; resize the
>   SCAFFOLD's `3p` end and the union hi-bp grows past the staple → helix grows by δ → +2δ nucs. Use
>   `_scaffold_on_grid(design, grid_pos)` (in `test_headless_build.py`) to grab `(helix_id, scaffold_id)`.
> - **GOTCHA — the inverse pair is NOT clean from a RAW bundle (ISSUE-13).** `create_bundle` sets a helix's
>   `axis_end = length_bp·rise`; `resize_strand_ends`' re-trim uses `(max_index−min_index)·rise` (one rise shorter),
>   so the FIRST resize shifts the convention and `canonical_topology` (fingerprints axis floats) never restores.
>   Capture `start` AFTER one settling resize (`hb.resize_strand_end(...,+10).model_copy(deep=True)`) so both ±δ
>   runs share the re-trim convention. NB the resize DOES change the nucleotide count (that's what
>   `assert_geometric_length_delta` pins); the ISSUE-13 off-by-one is only in the axis-endpoint *float*, not in
>   `length_bp`, so it leaves the count untouched — which is exactly why the geometric oracle stays clean.
>
> **■ HARNESS NOW AVAILABLE — AF-32 forced-ligation place/delete (2026-06-26).**
> - `from backend.api import headless_build as hb` →
>   `hb.force_ligate(three_prime_strand_id, five_prime_strand_id, *, is_periodic_seam=False) -> Design` — connects
>   the 3' end of one strand to the 5' end of another bypassing the crossover lookup tables → ONE multi-domain
>   strand + a `ForcedLigation` record (NO crossover record). The new FL is `design.forced_ligations[-1]`.
>   **SCRIPTED-MANUAL entry only** — forced ligation must NEVER be driven by an autorouter; the wrapper just
>   replays a user's pencil-tool ligation. · `hb.delete_forced_ligation(fl_id) -> Design` (splits the merged
>   strand back at the junction + drops the record).
> - `from tests.automation_harness import assert_forced_ligation` —
>   `(before, after, fl_id, *, three_prime_strand_id, five_prime_strand_id)`. Takes BOTH the pre-ligation `before`
>   (to re-derive the expected 3'/5' endpoints exactly as the route does — 3' = last domain of the 3' strand, 5' =
>   first domain of the 5' strand) AND `after`. Pins: record exists w/ right endpoints + strands merged (count −1 +
>   `_strand_spans_both`) + record survives a `.nadoc` round-trip (load-bearing — FL record lives OFF the strand
>   graph, `canonical_topology` blind).
> - **GOTCHA — the inverse pair is CLEAN force-ligate→delete (unlike AF-31).** Forced ligation introduces NO nicks,
>   so `assert_inverse_pair(start_unligated, lambda: force_ligate(a,b), lambda: delete_forced_ligation(fl_id))`
>   restores `canonical_topology` straight back. Capture `fl_id` inside the inverse closure via
>   `design_state.get_or_404().forced_ligations[-1].id` (forward has already run).
> - **GOTCHA — fixture: a 2hb HC bundle `[[0,0],[0,1]]` has ONE scaffold strand per helix off `create_bundle`** —
>   pick the two by `grid_pos`/`strand_type` and force-ligate them by id (mirrors `test_forced_ligation`).
> - **GOTCHA — the round-trip clause (5) can't be red-tested by stripping the record** (stripping makes clause 2
>   fire first; and the FL record genuinely survives round-trip since it's a real model field). Clause 5 is
>   exercised POSITIVELY by the passing test; the 3rd red-test instead pins clause 3 (re-attach the record to the
>   un-merged `before` strand graph → strand count ≠ before−1).


> **■ HARNESS NOW AVAILABLE — AF-31 manual crossover place/delete (2026-06-26).**
> - `from backend.api import headless_build as hb` →
>   `hb.place_crossover(half_a, half_b, nick_bp_a, nick_bp_b, *, process_id="manual") -> Design` where
>   `half_a`/`half_b` are `(helix_id, index, strand)` triples (`strand` a `Direction`). The new `Crossover` is
>   `design.crossovers[-1]`. MECHANICAL pass-through — caller supplies the half-sites + bow-direction nick bp
>   (mirror `tests/test_crossover_placement._nick_positions`: HC staple bow-right `{0,7,14}`, lower_bp, FWD→lower
>   REV→lower+1). · `hb.delete_crossover(crossover_id) -> Design` (desplices the merged strand back).
> - `from tests.automation_harness import assert_crossover_joins` —
>   `(design, xover_id, *, half_a=(helix_id,index), half_b=(helix_id,index), expect_ligated=True)`. Pins record
>   exists + joins the named sites + (ligated) a single strand spans both + `validate_design`. `expect_ligated=False`
>   = the recorded-but-unligated cycle-avoidance outcome (skips validate — the validator flags terminus-on-crossover
>   by design).
> - **GOTCHA — the inverse pair is delete→place, NOT place→delete.** `place_crossover` introduces nicks that a
>   desplice (`delete_crossover`) does NOT undo, so `place→delete` on a fresh bundle leaves the extra nicks and
>   FAILS `assert_inverse_pair`. Run the inverse from a design that already carries the crossover:
>   `assert_inverse_pair(start_with_xover, lambda: delete_crossover(xid), lambda: place_crossover(...))`.
> - **GOTCHA — a 2-cell HC bundle `[[0,0],[0,1]]` gives col-adjacent valid staple crossovers at bp 6,7 (+21n).**
>   `create_bundle` seeds the staple strands, so you can `place_crossover` directly (no auto_scaffold needed).
>   Manufacturing the UNLIGATED outcome through the route is fiddly (simple bundles produce Holliday junctions or
>   400-reject), so the unligated oracle branch is pinned with a hand-built cycle fixture (mirror
>   `test_crud._cycle_design`), not driven through `place_crossover`.


> **■ LEDGER AUDIT 2026-06-21 (validity + goal-alignment sweep).** Every backlog item was re-checked against
> its REST route / harness fn (all exist — see the probes in `design_automation_log.md`) and against the two
> stated goals (automated validation testing; eventual text-to-design). **Findings:**
> 1. **No item is dead or off-goal.** Every open item still maps to a live route/function AND to a goal.
>    `routes_primitives.py` confirms AF-12's premise (GET-only catalog, no placement route → the gap is real);
>    `periodic_polymer.py` backs the AF-9 straggler; `headless_spec_build.py` has constraints attach+report but
>    NO knob clause yet (AF-13 P5 knob = genuinely open).
> 2. **Stale checkboxes fixed:** AF-14, AF-15, AF-PHOTO were fully shipped but left `[ ]` → now `[x]`. AF-9 has
>    all four sub-ops shipped; only the `polymerize_periodic` straggler is open.
> 3. **Handoff pruned:** ~5 superseded `▶ NEXT`/capstone pointers that directed the next session to
>    ALREADY-SHIPPED work (AF-13 P4, AF-16, the 4-bar capstone, AF-14 P2) were removed — they contradicted the
>    shipped state. The `▶ HARNESS NOW AVAILABLE` do-not-rebuild reference blocks (with banked gotchas) were KEPT.
> 4. **Genuinely-open, validated work, priority order:** (a) **AF-13 P5 KNOB clause** — lower a constraint+knob
>    spec to `iterate_to_constraint`; the constraint-driven text-to-design bridge, highest goal value. (b) **AF-12
>    primitives in the build-spec** (`from_primitive`/`from_file`) — reference saved validated parts by name; the
>    other text-to-design rung. (c) **`polymerize_periodic`** straggler (niche). (d) Assembly-level `constraints`
>    + the `bind_overhangs` spec op — both correctly DEFERRED (no assembly headless-oxDNA path; overhang-binding
>    not yet firmed). Nothing below needs deleting; the loop is healthy and converging on the two goals.

> **★ NEW PRIORITY TRACK 2026-06-22 — Tier 6: time-resolved E-field response (user request).** Scoped this session
> into six ranked loops (see `### Tier 6` below), capstone last. **Goal:** automate build→route→sequence→overhang→
> anchor → subject to an E-field → measure helical alignment + base-pairing *over time* → automatically sweep field
> intensity × direction across many origami, finding which fields align which structures on what timescale WITHOUT
> melting them. **This is the new top priority** — work it ahead of the AF-12/13 stragglers below. **Order + why
> validation-first:** **AF-18** (full-pipeline anchored field-specimen builder) → **AF-19** (equilibration-timeline
> τ + non-melt oracle — the key new physical observable) → **AF-20** (field sweep + |E|↔τ correlation map) → then the
> oxpy *interactive* sub-track **AF-21** (persistent in-process engine — **oxpy ✅ BUILT + venv-wired 2026-06-23**,
> `import oxpy` ready; see the Tier 6 as-built note) → **AF-22** (live field-steering + field-following oracle) →
> **AF-23 CAPSTONE** (cross-design
> automated campaign). **De-risk note:** AF-18→20 + AF-23's batch path ride the ALREADY-SHIPPED field child-job +
> `_FIELD_MOCK_OXDNA` (no GPU, no oxpy) — only AF-21/22 need the oxpy build. Each loop ships one reusable oracle per
> the anti-shovel contract. **TIER 6 CODE + PLUMBING SHIPPED 2026-06-23 (AF-18..AF-23) — but the PHYSICS is NOT yet
> validated on the real engine (see the ★ ASSESSMENT 2026-06-23 below).** Batch spine (AF-18→20→23) + oxpy interactive
> engine (AF-21) + multi-waypoint live steering (AF-22) all exist and pass their suites; AF-21's live-steering plumbing is
> CONFIRMED on real oxpy. The gap: AF-19/20/23's physical observables (τ, |E|↔τ law, melt window, cross-design
> distinguishability) are pinned ONLY against hand-built mocks engineered to emit those signatures — never run on the
> real engine. ▶ START NEXT: **AF-24 — real-engine Tier-6 validation** (the diverted top priority), then the AF-12/13
> text-to-design stragglers. **AF-12 Phase 2b (parametric circle `from_primitive` + params) SHIPPED 2026-06-23.**

> **★ ASSESSMENT + DIVERSION 2026-06-23 (user request: "has the AF ledger completed the live E-field testing?").**
> Verdict: **plumbing yes, physics no.** Evidence gathered this session — (a) `oxpy` imports (`~/oxDNA/build/python`),
> (b) the F0/dir binding patch IS live (`oxpy.forces.BaseForce` exposes `F0` + `dir`), (c) `find_oxdna()` →
> `/home/joshua/oxDNA/build/bin/oxDNA`, (d) an RTX 2080 SUPER is present, (e) **the one gated real-oxpy test
> `test_run_live_field_real_oxpy_steers` RUNS (not skips) and PASSES in 13s** — real relaxation → real `string` field →
> live `F0`/`dir` re-aim → confirmed steering. So the live ENGINE works. **But:** every AF-19/20/23 test uses
> `mock_oxdna_field_traj`/`_sweep`/`_campaign` — hand-built binaries whose τ/melt signatures are coded to match the
> oracle (e.g. campaign `k=clamp((4.5−12·F0)·(540/N))`). The oracles prove the MEASUREMENT CODE is correct given a
> right-shaped trajectory; nothing has confirmed the real engine PRODUCES alignment-τ, τ↓-as-|E|↑, a non-destructive
> window, or distinguishable per-design τ — the user's actual goal. **DIVERSION:** AF-24 (below) ports the AF-19/20/23
> oracles to REAL-engine gated tests (importorskip oxpy + find_oxdna, CUDA where available), staged P1→P3, ahead of the
> AF-12/13 stragglers. De-risked: engine + patch + binary + GPU all confirmed working this session.

_Living pointer — each session overwrites this (step 8). **▶ TIER 7 COMPLETE 2026-06-24 — "job/feature-log sync"
DONE. AF-25 + AF-26 (backend + real e2e leg) all SHIPPED + verified. Full backend suite green (3123 passed / 64
skipped); AF-26 e2e red→green proven in the real browser; smoke + panel vitest green.** Nothing committed (user
hasn't asked). ▶ NEXT (new top of backlog): the AF-24 real-engine Tier-6 stragglers (P2/P3), then the AF-12/13
text-to-design stragglers. Historical detail below.
- AF-25: `seek_features` + `assert_feature_seek` (coverage 37→38). Oracle went RED first run → caught + FIXED a real
  bug: `_topology_substitute` never rolled back the `overhangs` list on a seek (dangling overhang → wrong build
  fingerprint).
- AF-26 backend: `roll_job_to_run_state` + `return_to_latest` wrappers + `assert_roll_return_lifecycle` (full
  simulate→edit→roll→return + 409 guard), pin `test_af26_roll_return_lifecycle_overhang_edit`. Coverage 38→39 + oxDNA 4→5.
- **DIAGNOSIS:** the AF-26 backend oracle stays GREEN with the AF-25 fix reverted (the roll route's snapshot-overlay
  fallback already clears the flag) → the live bug is the manual-seek path, whose fingerprint the AF-25 fix repaired.
  Frontend wiring already refetches on seek (`seekFeatures`→`_syncFromDesignResponse`→`nadoc:design-changed`→panels
  `_fetchJobs`), so the AF-25 one-liner is *likely* the root-cause fix — but UNPROVEN in-app.
- **▶ NEXT (e2e leg, dev servers were up :8000/:5173):** a Playwright spec driving the real oxDNA/MD panel + Feature
  Log rail (load → seed/relax a job → add an overhang → ⚠ appears → manual rail-seek back AND/OR "Roll & run" →
  assert ⚠ clears + cursor/rail-thumb moves + scene rebuilds with the overhang gone). Made to go RED first by
  reverting the `overhangs=snap_design.overhangs` line in `_topology_substitute`. Mirror `frontend/e2e/
  feature_log_revert.spec.js`. GOTCHA: real-app job creation needs a (mock) oxDNA binary or a pre-seeded completed
  job in the workspace — figure out the seeding path. Nothing committed (user hasn't asked).** Prior AF-24 pointer below.
▶ AF-24 P1 SHIPPED 2026-06-23 — real-engine Tier-6
equilibration-τ CONFIRMED; the relaxation-step-count bug is FIXED.** Root cause (full chain in the difficulties
ledger): the AF Tier-6 builders inherited `create_job`'s MOCK-tuned defaults (mc=100/md_relax=100/equil=100 — 10⁴×
too few md_relax steps), so the real engine dropped base-pairing and NEVER re-annealed. The metric, the export
(42/42 at t=0 by oxDNA's own HBList), and the protocol were all fine. THE FIX: `headless_oxdna_build.STANDARD_RELAX_PARAMS`
(mc=1000/md_relax=1e6/equil=1e5/`min_bp_retained=0.5`/`max_relax_retries=3`); a REAL Tier-6 build passes
`**hox.STANDARD_RELAX_PARAMS` explicitly (mock defaults stay default so the GPU-free suite — whose mock cost scales
with step count — stays fast). PROOF + augment: `tests/test_headless_oxdna_build.py::test_field_specimen_reanneals_
and_equilibrates_real_engine` (opt-in `NADOC_RUN_OXDNA_SLOW=1`, `@pytest.mark.slow`, fixture
`tests/fixtures/test343.nadoc`): re-anneal retention ≥ 0.9 → anchored field (pN=2, 20k) → `assert_equilibration_timeline`
UNCHANGED → **PASSED on real CUDA, 252 s** (converged + finite τ + not melted; τ_align < τ_melt). Full suite 3053
passed / 56 skipped (the gated test skips by default). Also fixed the wrong `write_mutual_traps` docstring.
**▶ NEXT — AF-24 P2** (real |E|↔τ sweep: `sweep_field_response` over ≥2 real intensities → `assert_field_sweep_map`
on REAL cells; same `**STANDARD_RELAX_PARAMS` recipe + the pN=2-ish benign / higher-pN destructive bands from this
session's sweep: pN≤2 benign, pN≥4 melts at 20k steps), then **P3** (real cross-design campaign), then the AF-12/13
text-to-design stragglers. GOTCHA for P2/P3: each cell is a field run off ONE relaxed parent (the 219 s relax is
shared — reuse `append_field` on the parent job, as the gated test does); keep them GPU-gated + opt-in. The sparse
`make_minimal_design` duplex hits an oxDNA cell-list overflow at md=1e6 (50 nm box) — use a real-design fixture
(test343) or set `cells_auto_optimisation=false`/`max_density_multiplier` in `render_stage_input` (unfixed, minor).
Repro probes: scratchpad `af24_standard.py`, `af24_field.py`/`af24_field2.py` (the field sweep)._

**▶ NEW (queued 2026-06-24) — Tier 7: AF-25 (headless feature-log SEEK + non-destructive-scrub oracle) and
AF-26 (job-staleness ROLL/RETURN lifecycle oracle: simulate→edit→roll→return incl. the 409 crash-guard).
THESE GUARD A LIVE BUG — the out-of-date-job flow is currently FAILING hand-check (the manual feature-log seek
doesn't clear the ⚠ / the cursor & model don't visibly roll), and the bug has survived several fix rounds that
all shipped green unit tests.** That green-tests-but-broken-app gap is the point: AF-26's oracle must drive the
REAL end-to-end path (incl. a Playwright/integration leg over the actual panel + Feature Log rail, since the
backend slices already pass) and **be made to go RED on the current build first**. The user explicitly asked
for this automation INSTEAD of more manual back-and-forth. AF-25 (the missing headless seek primitive) is the
prerequisite; AF-26 is where the real-flow red lives. Strong "validation-first" pick — arguably ahead of the
AF-24 real-engine stragglers, since it's an active regression, not a caveat-retirement.

**▶ AF-24 — real-engine Tier-6 validation (NEW, the diversion target; staged):**
- **P1 — real equilibration τ:** properly-relaxed specimen → real field stage → `measure_field_equilibration` on the
  real `trajectory.dat` → `assert_equilibration_timeline` green. Gated real-oxpy/GPU test. First real-physics proof.
- **P2 — real |E|↔τ sweep:** `sweep_field_response` over ≥2 real intensities on one specimen → `assert_field_sweep_map`
  (τ monotone-falls + a non-destructive window + a destructive bound) on REAL cells. Confirms the field LAW, not a mock.
- **P3 — real cross-design distinguishability + melt window:** `run_field_campaign` over ≥2 designs (6hb vs 18hb lever)
  → `assert_field_campaign` (per-design surface + distinguishable τ + reproducible) on the real engine. The user's
  stated capstone goal: which fields align which structures, on what timescale, WITHOUT ripping them apart — confirmed
  on real physics, not the design-dependent-k mock. May need real GPU runtime budget; can run as a background campaign.
- **Anti-shovel note:** AF-24 ships NO new wrapper (coverage stays FLAT 37) — its deliverable is the real-engine GATED
  TESTS that retire the "mock-only" caveat on the AF-19/20/23 oracles. The validation gained: the oracles' physical
  claims become engine-confirmed, not mock-asserted. That IS the augment (a green that can go red on real physics).

**▶ HARNESS NOW AVAILABLE (AF-29 hinge ssDNA flexible-relax, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.relax_flexible_segments(*, scope="all", conn_id=None,
  label=None) → Design`. Pulls each flexible-connected cluster pair's smaller leaf in until its unpaired-ssDNA
  scaffold tether is taut at contour length ("free until taut"), commits via `POST /design/flexible-relax` as ONE
  feature-log entry. `scope="one"` relaxes just `conn_id`'s pair. **No-op safe:** nothing overstretched → route NOT
  called (no empty entry). **Display/pose-layer only** (moves `cluster_transforms`, never topology).
- `from backend.core.flexible_relax import relax_cluster_pose, compute_relax_transforms` — the pure solver
  (`relax_cluster_pose(pivot, translation, rotation, tethers, *, translate_only)`) + orchestration. `tethers` =
  `[(moving_anchor_world_pos, fixed_anchor_world_pos, contour_nm), …]`. Faithful Python port of `cluster_gizmo.js`
  `relaxSsdna`/`_projectSsdnaConstraints` (uses scipy `Rotation`); constants `_SS_GAIN`/`_SS_ITERS`/`_SS_RELAX_OUTER`/
  `_SS_RELAX_EPS`/`_SS_RELAX_TOL` mirror the JS exactly.
- `from tests.automation_harness import assert_flexible_segments_relaxed` — `(before, after, *, tol_nm=0.05,
  require_moved=True)`: every connection chord (on POSED geometry) ≤ contour+tol + a pose moved + `canonical_topology`
  unchanged. The contour-constraint clause is solver-INDEPENDENT (measures the result, not the solver) — reuse it for
  any pose-layer constraint solve.
- **JS↔Python PARITY:** the pure JS solver is `frontend/src/scene/flexible_relax_solver.js` (vitest
  `flexible_relax_solver.test.js`); the Python solver is pinned to its asymmetric-fixture golden in
  `tests/test_flexible_relax.py` (pos+rotation to 1e-6). **Shared golden — edit one ⇒ edit the other.**
- **GOTCHA:** `cluster_gizmo.js` STILL has its own inline copy of the solver (the live 3D drag) — NOT yet wired to
  the pure module. The fixture `_overstretched_flexible_hinge` in `test_headless_build.py` (2 single-helix clusters +
  one 6-base ssDNA run, cl_b posed 10 nm away) is the drop-in overstretched hinge; the 3 hinge primitives have EMPTY
  `flexible_segment_marks` so you must `apply_marks` first.

**▶ HARNESS NOW AVAILABLE (AF-27 P1 overhang-linker tie, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.connect_overhangs(overhang_a_id, overhang_b_id, *,
  overhang_a_attach="free_end", overhang_b_attach="free_end", linker_type="ds", length_value, length_unit="bp",
  name=None, bridge_sequence=None) → Design`. Drives `POST /design/overhang-connections`. The new connection is the
  LAST entry of `design.overhang_connections`. It's a REAL topological edit: appends linker complement strand(s) +,
  for `ds`, a virtual `__lnk__` bridge helix (so `any(h.id.startswith("__lnk__"))` after a ds tie). A mismatched
  Watson-Crick polarity combo raises `HTTPException` 400 (the route's rule — see `project_overhang_connections.md`).
- `from tests.automation_harness import assert_linker_connects` — `(design, conn_id, *, overhang_a, overhang_b,
  bridge_bp=None)`: connection exists + joins the two overhangs (order-independent) + bridge bp == `bridge_bp`
  (lowered via the route's own `_length_value_to_bp`), re-checked after `roundtrip_nadoc`. **canonical_topology is
  BLIND to `overhang_connections`** (the cluster/loop-skip/binding blind-spot again) → the round-trip re-read is the
  only proof the tie persisted. Returns the re-imported design.
- **FIXTURE GOTCHA:** the 3 hinge primitives (`workspace/Primitives/2x{2,4,6}_*_hinge_link.nadoc`) have **0
  overhangs** — NOT a drop-in fixture. Use `_seed_two_overhang_leaves()` in `test_headless_build.py` (two real
  extruded-overhang helices, both 5p; free_end/free_end is a valid **ds** polarity, free_end/root is the rejected
  red case). For a primitive-based fixture, `hb.overhang_extrude` two tips first.
- **Polarity cheat-sheet** (from `project_overhang_connections.md`): `comp_first := (5p∧free_end) ∨ (3p∧root)`; **ds
  accepted iff comp_first(A)==comp_first(B)**, **ss iff !=**. Don't reason geometrically — pick a known-valid combo.
- **P2 is the suspicious one:** the relax wrappers must be verified to produce a DISPLAY pose (canonical_topology
  unchanged), not a strand-graph edit. ASK-FIRST on attach-endpoint / ss-vs-ds / bridge-length directionality.

**▶ HARNESS NOW AVAILABLE (AF-12 Phase 2b parametric circle, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_assembly(spec, *, primitives_dir=None)` with a part
  `{"from_primitive": "<circle-name>", "params": {"radius_nm": R}}` builds that catalog circle GENERATIVELY at radius R and
  embeds it INLINE (NOT file-backed). The catalog entry must carry `metadata.primitive_kind == "circle"` (SQUARE). `radius_nm`
  is REQUIRED (omitting → `BuildSpecError`); handing `params` to a STATIC primitive → `BuildSpecError "takes no params"`.
- **Augment = `from tests.automation_harness import assert_part_is_circular_disc`** — `(assembly, instance_id,
  requested_radius_nm, *, max_spread_nm=0.5, radius_tol_nm=0.5)`. Asserts inline-backed + loads embedded design + AF-4
  circularity/radius. Can-go-red: wrong radius → circularity/radius fail; file-backed instance → inline guard.
- **GOTCHAS banked:** (1) the disc instance shares `source.type=="inline"` with any inline DesignSpec part — find it by NAME
  (`add_part` names it the part key, e.g. `"disc"`), not by source type. (2) build the parametric Design by LOWERING to a
  `circle_segment` op through `build_design` (not hand-constructing) → canonical-identical to a clicked disc + free op-parser
  validation + flat coverage. (3) the saved catalog `.nadoc`'s GEOMETRY is irrelevant (only its `primitive_kind` +
  `derive_placement_spec` plane/min_chord_bp are read) — a test fixture can save a default-radius disc + inject
  `metadata.primitive_kind="circle"`. (4) AF-12 P2c (hinge/template primitives) needs a concrete hinge primitive in the
  catalog first; multi-knob `optimize` + assembly `constraints` remain deferred (no assembly headless-oxDNA path).

**▶ HARNESS NOW AVAILABLE (AF-22 live steering, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.steer_field_session(session, waypoints, *,
  steps_per_waypoint=1000) → {"timeline": [{field_dir, steps, proj_before_nm, proj_after_nm, alignment_nm, bp_retention,
  radius_of_gyration_nm, followed}, …], "n_waypoints": N}`. `session` is an UN-entered AF-21 `LiveOxdnaSession`-like object
  (the function enters it via `with session:`); each `waypoints` entry is `{"dir":[x,y,z], "field_pN":<opt>, "steps":<opt>}`.
  Raises `ValueError` on empty `waypoints`. `alignment_nm == proj_after_nm` (deflection along the CURRENT leg's vector).
- **Augment = `from tests.automation_harness import assert_live_field_following`** (signature + clauses above).
- **GOTCHAS banked:** (1) the `_MockFieldStepper` shift is recomputed from the seed each readout (position-based, not
  incremental), so steering through ORTHOGONAL waypoints makes each leg's `proj_before≈0` (the body was aligned to the
  PREVIOUS, orthogonal leg) → `proj_after≈200·F0` → a clean substantial follow; a repeated-direction waypoint would have
  `proj_before≈proj_after` → `followed=False` → fails clause 2 (that IS the intended ignored-waypoint red signal). (2) the
  melt + ignored-waypoint red tests are HAND-BUILT timeline dicts (the no-melt mock translates free beads together → bp
  stays 1.0, can't melt), mirroring AF-19/AF-20's hand-built reds. (3) coverage FLAT 37 — pure composition over the AF-21
  session, no route wrapped. (4) Tier 6 is DONE — do not look for more field work; the next item is the AF-12/13 stragglers.

**▶ HARNESS NOW AVAILABLE (AF-21 live engine, use it — do NOT rebuild):**
- `from backend.physics.oxdna_live import LiveOxdnaSession, _OxpyStepper` — persistent oxpy session. Used as a context
  manager; `set_field(field_oxdna=…, field_dir=…)` mutates the live field between `run(steps)` bursts;
  `equilibrium_observables(field_dir=…)` reads the current equilibrium vs the field-off reference. `_OxpyStepper(rundir)`
  needs a staged field run dir (`input`+`topology.top`+`conf.dat`+`field_forces.txt`) — build it with
  `hox._prepare_field_rundir(design, seed_conf, rundir, *, field_pN, dir, anchors, anchor_stiff, steps)` (reuses the SAME
  `write_topology`/`write_field_forces`/`build_field_stage`/`render_stage_input` writers the batch field stage uses).
- `from backend.api import headless_oxdna_build as hox` → `hox.run_live_field(specimen, ws, *, field_pN, dir,
  total_steps=4000, n_bursts=4, mutate_dir=None, anchor_stiff=DEFAULT_ANCHOR_STIFF, session=None, rundir=None)`. `specimen`
  is an AF-18 `build_field_specimen` result. `session=None` builds a REAL oxpy session (needs the oxpy build); inject a mock
  for GPU-free tests. **AF-22 builds its multi-waypoint steered timeline by calling `session.set_field`/`run`/`observables`
  in a loop — the session already supports it.**
- **Augment = `from tests.automation_harness import assert_oxpy_equilibrium_parity`** (see signature above).
- **GOTCHAS banked (read before AF-22):** (1) the binding patch is in the USER's `~/oxDNA` C++ — a fresh clone/rebuild
  WITHOUT it makes `force.F0`/`force.dir` `AttributeError` and `run_live_field`'s real path dies; the two
  `def_readwrite` lines + `make` must be reapplied (it's `git`-untracked in their tree). (2) the field force is found by
  `f.type == "string"` (NOT an `id`), so don't rely on a forces-file `id`. (3) a uniform field on a FREE (unanchored) body
  streams the COM ballistically — `write_field_forces` REQUIRES anchors; a re-aim test on a free body shows residual
  momentum from the prior direction, so anchor the body (the field deflects the free part against the anchor to a pose).
  (4) F0 in oxDNA units is large: `pn_to_oxdna_force(4 pN)≈0.082`; F0≈0.4 (≈19 pN) blows the integrator up on a tiny system
  — use the realistic `pn_to_oxdna_force(field_pN)` regime. (5) the GPU-free parity test makes live & batch end on the SAME
  final field (re-aim live `+z→+x`, run batch directly at `+x`) so the equilibria are comparable; alignment is along the
  FINAL dir. (6) the gated real test runs a REAL relaxation (`build_field_specimen`, mc/md/equil=100) + real field — it
  RUNS (not skips) wherever oxpy + a binary resolve; `pytest.importorskip("oxpy")` + `find_oxdna() is None` skip elsewhere.
  (7) coverage stays FLAT 37 — `run_live_field` wraps NO route (pure composition + the new engine path).

**▶ HARNESS NOW AVAILABLE (AF-23 campaign, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.run_field_campaign(specimens, intensities_pN, directions, ws,
  *, field_steps=2000, melt_floor=0.5, min_confidence=10, **relax_params) → {"sweeps", "skipped", "names", …}`. Each
  `specimens` entry is the AF-18 `build_field_specimen` kwargs as a dict (`design` + `anchor` + optional `overhang`/`sequence`)
  + a `name`. Reuses the de-risked AF-20 batch path entirely; transparently swaps to the AF-21/22 oxpy fast path once built.
- **Augment = NEW `from tests.automation_harness import assert_field_campaign`** — `(campaign, *, benign_range,
  destructive_range, expect_distinguishable=True, melt_floor=0.5, min_tau_separation_steps=1.0, repro=None)`. Returns
  `{n_designs, n_distinguishing_cells, n_repro_cells, per_design}`. The distinguishability predicate recomputes each design's
  τ signature from raw `aligned ∧ bp_min ≥ melt_floor` (anti-echo, NOT `cell["destructive"]`).
- **GOTCHAS banked (read before AF-21):** (1) the AF-20 `_FIELD_SWEEP_MOCK` has a **design-INDEPENDENT** τ → two designs swept
  through it are IDENTICAL → it CANNOT exercise the distinguishability clause. AF-23 added a NEW
  `_FIELD_CAMPAIGN_MOCK_OXDNA`/`mock_oxdna_field_campaign` where `k = clamp((4.5−12·F0)·(540/N))` — N=particle count, so a
  bigger design → smaller k → shorter τ → DISTINGUISHABLE, while the melt threshold stays design-independent (`s_max=2.0 if
  F0≥0.4`) so the SAME benign/destructive bands hold for every design. (2) distinguishability shows at LOW |E| (2–4 pN): at
  high benign |E| both designs' k floor at 1.0 (shared) → equal τ there; the oracle only needs ONE differing shared cell, so
  this is fine, but a hand-built distinguishability check should read a low-|E| cell. (3) **the distinguishable fixture is 6hb
  vs 18hb** (`make_6hb_design`/`make_18hb_design`, both at `length_bp=42` → N≈528 vs 1536, a clean ~3× lever) each anchored on
  a REAL extruded ssDNA overhang via `_campaign_entry` (mirrors AF-20's `_sweep_specimen`: `extrude_valid_overhang` +
  `_define_overhang_bases`, `sequence=False`). (4) the indistinguishable RED test uses TWO IDENTICAL 6hb (different `name`s,
  same topology→same N→same τ). (5) the skipped RED test uses an anchor id that doesn't resolve → `build_field_specimen`
  raises → recorded in `skipped` (not dropped) → clause 1 fires. (6) coverage stays FLAT 37 — campaign wraps NO route.

**▶ HARNESS NOW AVAILABLE (AF-20 field sweep, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.sweep_field_response(specimen, intensities_pN, directions,
  ws, *, field_steps=2000, melt_floor=0.5, min_confidence=10) → {"map", "skipped", "intensities_pN", "directions",
  "melt_floor"}`. `specimen` = an AF-18 `build_field_specimen` result (`design`+relaxed `job`+`anchor`+`anchor_keys`). Each
  cell keyed `(pN_float, dir_tuple)`. Raises if the specimen's parent job is not `completed`.
- **Augment = NEW `from tests.automation_harness import assert_field_sweep_map`** — `(sweep, *, benign_range,
  destructive_range, melt_floor=0.5, tau_tol_steps=1e-6, min_tau_drop_steps=1.0)`. `*_range` are inclusive `(lo_pN, hi_pN)`.
  Returns `{n_cells, n_benign_safe, n_destructive, n_directions_checked}`. The non-destructive predicate is RECOMPUTED from
  `aligned ∧ bp_min ≥ melt_floor` (do not trust `cell["destructive"]`).
- **GOTCHAS banked (read before AF-21/23):** (1) the AF-19 `_FIELD_TRAJ_MOCK` has a **field-independent k** (flat τ) and
  **never melts** → it CANNOT exercise the AF-20 green path. AF-20 added a NEW `_FIELD_SWEEP_MOCK_OXDNA`/`mock_oxdna_field_sweep`
  where `k = max(1.3, 4.5 − 12·F0)` (stronger field → smaller k → smaller τ) AND, above `F0 ≥ 0.4`, dilates the free cloud
  about its own centroid by `(1+s)` with `s = 2·factor` → every free base-pair separation scales by (1+s) → melt. The dilation
  is centroid-symmetric so it **cancels in the MEAN along-field projection** (alignment still saturates ∝F0 and plateaus) —
  only `bp_min` drops. (2) `F0 = field_pN / 48.63` (`pn_to_oxdna_force`); the `F0≥0.4` melt threshold ≈ **19.5 pN**, so the
  green test uses intensities `[2,4,8,16,32]` → 16 pN benign, 32 pN destructive; `benign_range=(0,20)`,
  `destructive_range=(24,1e9)`. (3) the **flat-τ can-go-red can't use a mock** (a no-melt mock can't satisfy clause 3's
  non-vacuity) → it's pinned on a HAND-BUILT sweep dict with equal τ + one melted cell (mirrors AF-19's hand-built melt test).
  (4) coverage stays FLAT 37 — `sweep_field_response` reuses `append_field`; no route is wrapped. (5) **the sweep fixture
  anchors a REAL extruded ssDNA overhang, not a tagged internal domain** (an internal bundle domain is NOT a valid field
  anchor): `conftest.extrude_valid_overhang(design, length_bp=12)` (delegates to the `overhang_candidate_error` geometry
  oracle — no site reasoning) → `{"kind":"overhang","id":ovhg_id}` resolves to the WHOLE 12-nt overhang domain.
  **`make_6hb_design` is MULTI-scaffold** → `hb.full_sequence` (single active scaffold) leaves ~210 staple bases undefined;
  sequence with `_sequence_for_oxdna` (per-(helix,bp) WC across all scaffolds) instead. The ssDNA overhang has no WC partner
  → fill its bases via a domain-order slice splice (`_define_overhang_bases`, fixed-seed random ACGT); do **NOT** use the
  `POST /design/generate-overhang-sequences` route here — on a `_sequence_for_oxdna`-assigned 5′-overhang strand its resplice
  CORRUPTED the 42-bp body (defined the 12 overhang, undefined the body). `build_field_specimen`'s `overhang=` param can't
  mint the anchor id, so extrude FIRST then pass `overhang=None` + the overhang-id anchor + `sequence=False`.

**▶ HARNESS NOW AVAILABLE (AF-19 equilibration timeline, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import measure_field_equilibration` — PURE `(frames, field_dir, anchor_keys, *,
  design, steps_per_frame=1.0, melt_floor=0.0, plateau_frac=1−1/e, plateau_slope_frac=0.3, min_rise_nm=0.5,
  monotone_tol_frac=0.15) → dict`. `frames` = the list `read_trajectory_frames_full(traj, design)` returns (maps keyed
  by `(helix,bp,dir)` with `backbone_position`+`a1`); frame 0 is the field-off reference. Anchored keys are EXCLUDED from
  the free-body projection. Needs `design` (for `base_pair_retention` per frame). Raises on <2 frames / zero field dir.
- **Augment = `from tests.automation_harness import assert_equilibration_timeline`** — `(job, ws, field_dir,
  anchor_keys, *, design, melt_floor=0.5, min_confidence=10)`. Locates the `kind=="field"` stage's `trajectory.dat`,
  reads frames, confidence-gates, runs the measure, asserts `converged` + finite positive `tau_steps` + `not melted`.
- **GOTCHAS banked (read before AF-20):** (1) `FieldRequest.steps` has a **1000 minimum** (pydantic 422 below it) — the
  field mock writes `max(2, steps//100)` frames, so `field_steps=2000`→20 frames clears `min_confidence=10`; to force an
  INCONCLUSIVE red-path call the oracle with `min_confidence=15` on a 1000-step (10-frame) run, don't pass steps<1000.
  (2) The existing `_FIELD_MOCK_OXDNA` writes ONLY `last_conf.dat` (no trajectory) — AF-19 added a NEW
  `_FIELD_TRAJ_MOCK_OXDNA`/`mock_oxdna_field_traj` fixture in `test_headless_oxdna_build.py` that emits a multi-frame
  field `trajectory.dat` with a SATURATING ramp `shift_i = sc·F0·(1−exp(−i/k))` (sc=100, k=n/4) — plateau ∝ F0 (reuse
  it for AF-20's |E|-sweep). (3) the mock's free beads translate TOGETHER so designed pairs stay formed (no melt) — the
  melt/non-converge can-go-red cases are pinned on HAND-BUILT frames against the pure measure, not the mock. (4) τ in
  STEPS needs `steps_per_frame` = stage.steps / n_frames; the oracle computes it from the field stage; the pure measure
  defaults to 1.0 (τ in frame units). (5) coverage stays FLAT 37 — the oracle reads the field trajectory the shipped
  child-job already writes; no route is wrapped.

**▶ HARNESS NOW AVAILABLE (AF-18 field-specimen builder, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.build_field_specimen(spec_or_design, ws, *, anchor,
  overhang=None, sequence=True, scaffold_name="M13mp18", timeout=30.0, **relax_params) → {design, job, anchor_keys,
  anchor}`. `spec_or_design` = a ready `Design` (deep-copied) OR a build-spec dict (lowered via `hs.build_design` — same
  grammar AF-11/12 use). `anchor` is the SAME descriptor `append_field`/`resolve_anchor_particles` take
  (`{"kind":"overhang","id":…}` / `{"kind":"cluster","id":…}` / `{"kind":"domain","strand_id":…,"domain_index":…}`).
  Raises `ValueError` if the anchor resolves to no nucleotides. Pass `min_bp_retained=0.0` for the mock binary.
- **Augment = NEW `from tests.automation_harness import assert_field_ready_specimen`** — `(result, design, ws, *,
  field_pN=4.0, field_dir=(0,0,1), …)`: composes fully-sequenced + relaxed-geometry-recovered + a PROBE field child
  (branched off `result["job"]`, anchoring `result["anchor"]`) that holds the anchor while the free part deflects along
  the field. Run under the **deflecting** mock (`mock_oxdna_field`/`_FIELD_MOCK_OXDNA`), not the plain `mock_oxdna`.
- **GOTCHAS banked (read before AF-19):** (1) `assert_relaxed_geometry_recovered`'s key-set-equality is EXACT only for
  DENSELY-populated bundles — a routed `auto_scaffold`+`full_autostaple` 6hb has geom 756 ⊃ oxDNA-order 630 (126
  strand-less lattice slots), so the FULL composite oracle is green on `_sequence_for_oxdna(make_6hb)` (504==504) but
  fails on a routed design; prove other build branches with `assert_fully_sequenced` + `canonical_topology` equality and
  skip the geometry clause. (2) tagging a domain `overhang_id` makes `full_sequence` SKIP it (no WC partner → `'N'`) →
  field 400s on undefined; when `sequence=True` use a `domain`/`cluster` anchor (no tag), or tag AFTER sequencing. (3)
  you can't build a specimen from an UNSEQUENCED design (relax 400s on undefined) — exercise the oracle's clause-1
  red-path by handing it a raw design as the `design` arg. (4) coverage is FLAT 37 — `build_field_specimen` is pure
  composition; the value is the chain + composite oracle, not a route.

**▶ HARNESS NOW AVAILABLE (AF-12 P2 `from_primitive`, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_assembly(spec, *, primitives_dir=None)` with a part
  defined as `{"from_primitive": "<catalog name>"}` instances a curated catalog primitive by name. `primitives_dir`
  overrides the catalog folder (default = the live workspace `Primitives` dir); pass an absolute `tmp_path` containing
  `<name>.nadoc` files for tests. Resolves NAME → `.nadoc` via `primitive_catalog.design_path`, then lowers through the
  EXACT `from_file` path (placeable by `add_part` / `place_grid` / `place_ring`; the instance is file-backed). An
  unknown name → `BuildSpecError` at BUILD time (parser is catalog-agnostic).
- **Augment = NEW `from tests.automation_harness import assert_part_from_primitive`** — `(assembly, instance_id,
  primitive_name, primitives_dir)`: independently re-resolves the catalog name through `primitive_catalog.design_path`,
  loads that primitive's `.nadoc`, and delegates to `assert_part_from_file`. The new load-bearing piece over `from_file`
  is the **name→catalog-path RESOLVER** (a name mapped to the wrong/renamed primitive is invisible to
  `canonical_assembly`). Compose with `assert_instances_from_file` + `assert_instances_on_grid` for a from_primitive
  layout. Can-go-red: wrong name → "DIFFERENT topology"; unknown name → "catalog has no primitive".
- **GOTCHAS banked:** (1) the catalog NAME is the file STEM (`6hb_primitive.nadoc` → `"6hb_primitive"`); names must pass
  `primitive_catalog.is_safe_id` (alnum + underscore, leading digit OK). (2) save a catalog `.nadoc` with
  `design.to_json()` (symmetric to the loader's `Design.from_json`). (3) coverage stays FLAT at 37 — `from_primitive`
  folds into `file_paths` and reuses `add_file_instance`/`place_file_*`, wrapping no new route. (4) only STATIC
  (file-backed) catalog primitives — a `metadata.primitive_kind` (parametric, e.g. circle) part is NOT yet supported
  (the resolver returns a static `.nadoc` path; a parametric kind needs a generative build path, deferred).

**▶ HARNESS NOW AVAILABLE (`polymerize_periodic` straggler, use it — do NOT rebuild):**
- `from backend.api import headless_assembly_build as hab` → `hab.polymerize_periodic(instance_id, count, *,
  direction="forward")` grows a periodic polymer from a SINGLE seed instance (no hand-defined mate — the repeat is
  auto-derived from the part's `is_periodic_seam` ligations via `derive_periodic_delta`). Route 422s without a
  resolvable seam, 400s on `count<2`. Seed fixture is light: `make_bundle_design([(0,0),(0,1)], L, HONEYCOMB,
  strand_filter="both")` + `forced_ligations=[_seam_for(h0,L), _seam_for(h1,L)]` (the `_seam_for` helper lives in
  `tests/test_headless_assembly_build.py` and `test_periodic_polymer.py`).
- **Augment = NEW `from tests.automation_harness import assert_periodic_chain_tiles`** — `(assembly, *, tol_nm=0.05,
  step_tol_nm=0.05, angle_tol_deg=0.5, min_step_nm=0.5) → {n_junctions, max_gap_nm, step_nm, angle_deg}`. Over the
  chain's rigid `seam0:*` junctions: (1) ≥1 junction (non-emptiness), (2) seamless tiling — copy-k `seam0:3p` world
  ≈ copy-(k+1) `seam0:5p` world via `_get_connector_world` (the resolver's machinery), (3) single repeat unit —
  every junction's `T_high@inv(T_low)` shares one translation length + rotation angle (magnitudes → direction-
  agnostic, holds for `both`), (4) step>min non-vacuity guard. **Load-bearing because `canonical_assembly` is blind
  to the placed geometry** — it sees the chain's structure survive `.nass` but not whether the derived delta tiles.
  Distinct from `assert_polymer_chain` (mate-seeded). Can-go-red: shove a copy → "open"; lone seed (no chain) →
  "nothing was polymerized".
- **GOTCHAS banked:** (1) the synthesized junctions are `joint_type=="rigid"` with `seam0:3p`/`seam0:5p` labels;
  filter on BOTH the type and the label prefix. (2) `seam0:*` connectors resolve LIVE from the design geometry (the
  frozen-chain fix), so `_get_connector_world` recomputes the seam each call — pass the instance-overridden design.
  (3) the 2-seam HC bundle's delta is a LEAST-SQUARES Kabsch fit, so use `tol_nm=0.05` (route test's atol), not 0.01.
  (4) flipping `polymerize_periodic_assembly` → covered bumps the hardcoded coverage count in THREE tests
  (`test_oxdna_coverage_report...`, `test_cluster_obb::...adds_no_coverage`, `test_headless_spec_build::...adds_no_coverage`)
  36→37 — grep `covered"] == 36` before committing any future coverage flip.

**▶ HARNESS NOW AVAILABLE (AF-12 follow-up — file-backed layout, use it — do NOT rebuild):**
- `from backend.api import headless_assembly_build as hab` → `hab.place_file_grid(path, rows, cols, *, pitch,
  row_pitch=None, plane="XY", center=False, name="Part")` / `hab.place_file_ring(path, n, *, radius, plane="XY",
  start_angle_deg=0.0, center=(0,0,0), name="Part")` — the file-backed twins of `place_grid`/`place_ring`: identical
  per-slot translations, but each slot drives `add_file_instance(path)` (one path reference per copy, not embedded
  designs). Via the grammar: a `{"from_file": …}` part placed by a `place_grid`/`place_ring` op now parses + builds
  (the rejection was removed); the interpreter dispatches on `part in file_paths`.
- **Augment = NEW `from tests.automation_harness import assert_instances_from_file`** — `(assembly, expected_topology,
  *, instance_ids=None)`: loads the design behind EVERY selected slot and asserts each is file-backed and resolves to
  `expected_topology` (pass `canonical_topology(saved)`), with a non-vacuity guard. **Layout-agnostic source pin** —
  compose it with `assert_instances_on_grid`/`_on_ring` (lattice) for the full file-backed-layout proof. It's the
  plural of `assert_part_from_file`: a one-slot check misses a layout that file-backed slot 0 and embedded inline copies
  for the rest. Can-go-red: inline slot anywhere → "not file-backed"; wrong topology → "DIFFERENT topology"; empty
  selection (`instance_ids=[]`) → "selected no instances".
- **GOTCHAS banked:** (1) use an ABSOLUTE `tmp_path` .nadoc — resolves for both the from_file load AND the `.nass`
  round-trip flatten (`_PROJECT_ROOT / abs == abs`). (2) the can-go-red "inline slot" red-test builds a MIXED assembly
  (`place_file_grid` + an `add_inline_instance`) in a scratch session, not via `build_assembly`. (3) coverage stays flat
  — `place_file_*` wrap no new route (they loop the already-covered `add_file_instance`).

**▶ HARNESS NOW AVAILABLE (AF-12 P1, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_assembly(spec)` with a part defined as
  `{"from_file": "<path>"}` in `spec["parts"]` instances a saved validated `.nadoc` by reference. The path resolves the
  way the assembly routes resolve it (`_load_design_from_source`: absolute, or relative to workspace / assembly parent /
  project root); an absolute `tmp_path` file works for both the oracle AND the round-trip flatten (`_PROJECT_ROOT / abs
  == abs`). File parts may be placed by `add_part` (one reference) OR by `place_grid`/`place_ring` (per-slot references,
  AF-12 follow-up above).
- **Augment = NEW `from tests.automation_harness import assert_part_from_file`** — `(assembly, instance_id,
  expected_topology)`: loads the design the file instance actually references and asserts its `canonical_topology` ==
  `expected_topology` (pass `canonical_topology(saved_design)`), after asserting the instance is genuinely file-backed.
  **Load-bearing because `canonical_assembly` keys a file source by `("file", path, sha256)` ONLY — it never loads the
  design** — so `assert_spec_matches_calls` is blind to whether the path resolves to the intended topology. Can-go-red:
  wrong-topology substitute → "DIFFERENT topology"; pointed at an inline instance → "not file-backed".
- **GOTCHAS banked:** (1) discriminate file-vs-inline part by the `from_file` KEY (an inline part is also a dict but
  carries `ops`); a half-inline/half-file dict (`from_file` + `lattice`) is rejected by the `_FILE_PART_KEYS` whitelist.
  (2) `build_assembly` opens its OWN `assembly_scratch_session`, so the augment test calls it directly (no outer
  session); the roundtrip test needs the outer session like the other `assert_assembly_roundtrip_stable` callers.
  (3) save a part with `design.to_json()` (symmetric to the loader's `Design.from_json`). (4) Phase 2 (`from_primitive`
  catalog-by-name) is the remaining text-to-design rung — the design-level catalog has NO headless instancing path yet
  (only the circle disc), so it needs a name→part resolver, not just a grammar branch.

**▶ HARNESS NOW AVAILABLE (AF-13 P6, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_and_optimize_design(spec, workspace, *,
  max_iterations=8, production_steps=6000, tuned=False, **relax_params) →` the `hox.iterate_to_constraint` result
  (`{status, knob, job, iterations, verdict}`). Spec needs an `optimize` block (a spec WITHOUT one → `BuildSpecError`
  at parse time — that's the attach+report path `build_and_check_design`). The optimized op list must build a
  FULLY-SEQUENCED design EACH iteration (e.g. `bundle → bend → auto_scaffold → full_autostaple`; the bend survives the
  routing — it's a geometric overlay). `knob.response` is the spec author's declared monotonicity ("decreasing" = the
  measure FALLS as the knob rises, e.g. bend curvature ↑ → end-to-end ↓), lowered to the bisection direction in
  `_synth_bisection` — the grammar never reasons about bend sign.
- **Augment = reuse `from tests.automation_harness import assert_converges_to_constraint`** (the AF-13 P4 oracle):
  `(result, *, target_nm, tol_nm, min_confidence)`. Load-bearing because `assert_spec_matches_calls` is BLIND both to
  the bend overlay AND to a physical-layer convergence — the fingerprint can't see whether the knob hit target.
  Can-go-red: unreachable target → exhausted ("did not converge"); initial knob on-target → vacuous ("FIRST attempt").
- **GOTCHAS banked:** (1) a 2-helix bundle does NOT fully sequence via `full_autostaple` (84/168 undefined) — use the
  6hb (`SIX_HB_CELLS`) for an optimize fixture, NOT the 2-helix bend fixture. (2) the monotone profile must be checked
  per-landmark-PAIR: a single-helix bp0→bp41 end-to-end on the 6hb is NON-monotone (off-axis swing); `h_XY_1_2`
  bp0-fwd→bp41-rev IS monotone-decreasing (κ 2.0→12.68, 2.5→12.06, 3.0→11.32 nm), so target 12.0/tol 0.5/initial κ=2.0
  converges `2.0→3.0→2.5` in 3 deterministic bisection steps. Probe a candidate profile with
  `measure_end_to_end(_geometry_for_design(build(κ)), a, b)` (mock is identity → geometry == relaxed mean). (3) reuse
  `_MOCK_OXDNA_TRAJ` + the `mock_oxdna_traj` fixture; `production_steps=6000`→60 frames clears `min_confidence=50` in one
  round.

**▶ HARNESS NOW AVAILABLE (AF-13 P5, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_and_check_design(spec, workspace, *, steps=6000,
  tuned=False, **relax_params) → {"design": Design, "verdicts": [verdict,…]}`. Spec must build a FULLY-SEQUENCED
  design for the relaxation (e.g. `bundle → auto_scaffold → full_autostaple`; verified 0 undefined bases). With NO
  `constraints` block → `verdicts == []` and **no oxDNA run** (workspace untouched). `tuned=True` relaxes on the
  benchmarked hardware default (AF-17). Lower-level: `hs.check_design_constraints(design, parsed.constraints, ws, …)`.
- `from tests.automation_harness import assert_spec_constraints_reported` — `(spec_result, hand_verdicts, *,
  measured_tol=1e-6)`: asserts the grammar reports the SAME per-constraint verdict (status + `met` + `measured_nm`) a
  hand-driven `check_relaxed_constraint` yields, with non-vacuity + count-mismatch guards. **Load-bearing because
  `assert_spec_matches_calls` is BLIND to a physical-layer verdict** (the fingerprint can't see a constraint at all).
  Can-go-red: status mismatch, measured divergence (wrong-helix resolution), count mismatch, empty-list vacuity.
- **GOTCHAS banked:** (1) a constraint landmark is `{helix:[r,c], bp_index, direction}` (grid_pos, like nick/ligate),
  NOT a runtime id — the driver resolves it; `radius_of_gyration` takes NO landmarks. (2) The cell is normalised to a
  `(r,c)` TUPLE before handing to `parse_constraint_spec` so the `(hid,bp,dir)` triple stays hashable (it dedups
  landmarks with `set()` — a raw `[r,c]` list would `TypeError`). (3) The mock relaxation is identity, so the relaxed
  mean reproduces the DESIGN geometry → the spec and hand verdicts are deterministic + equal; use wide `tol` to get a
  clean `met` for the augment. (4) Reuse `_MOCK_OXDNA_TRAJ` (multi-frame; `steps=6000`→60 frames clears the
  confidence gate); import the CONSTANT not the fixture (F811).

**▶ NEXT — pick one (design `constraints` + `optimize`/knob loop wired; AF-12 `from_file` + file-backed layout +
`from_primitive` STATIC catalog-by-name shipped; remaining work + stragglers):**
- **AF-12 Phase 2b — `from_primitive` for the PARAMETRIC circle disc — ✅ SHIPPED 2026-06-23.** Grammar
  `{"from_primitive": "<circle>", "params": {"radius_nm": R}}` (user's ASK-FIRST calls: generic `params` dict; `radius_nm`
  REQUIRED for a circle kind). The driver detects `primitive_kind=="circle"`, builds the disc GENERATIVELY by lowering to a
  single `circle_segment` op through `build_design`, and embeds it INLINE (not file-backed). New oracle
  `assert_part_is_circular_disc` (inline guard + AF-4 `assert_circular_disc` on the embedded design). See the
  `▶ HARNESS NOW AVAILABLE (AF-12 Phase 2b …)` block above + the log's metrics row.
- **AF-12 Phase 2c — hinge / assembly-template primitives:** a catalog primitive that is an assembly-level *template*
  (leaves + a revolute mate recipe), not just geometry — parts carrying small mate recipes. Bigger architecture call;
  defer until a concrete hinge primitive exists in the catalog.
- **Multi-knob / richer knob shapes (optional grammar growth):** `optimize` today varies ONE numeric op param via
  bisection. A vector knob (two params) would need a non-bisection `adjust_fn` (e.g. coordinate descent) the grammar
  synthesises — only worth it when a real two-DOF constraint shows up. A `loop_skip count` or `length` knob also works
  today (any numeric op param), only the bend was fixture-proven; pick a monotone landmark pair per the P6 GOTCHA.
- **Assembly `constraints`** — `build_and_check_design`/`build_and_optimize_design` are design-only; an assembly spec's parts could carry
  constraints (parsed today, IGNORED by the assembly driver). Wire an assembly-level relaxed constraint if/when an
  assembly headless oxDNA path exists (none yet).
- **Stragglers:** `polymerize_periodic` SHIPPED 2026-06-22 (`hab.polymerize_periodic` + `assert_periodic_chain_tiles`).
  Remaining: `bind_overhangs` ASSEMBLY spec op (DEFERRED pending overhang-binding firming).

**▶ HARNESS NOW AVAILABLE (AF-13 P4, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.iterate_to_constraint(...)`. `build_fn(knob)→Design`
  must return a FULLY-SEQUENCED design (oxDNA 400s on undefined bases). `adjust_fn(knob, verdict)→next_knob` is the
  caller's domain knowledge of how the knob maps to the measure — only ever called on `unmet`. `constraint` is a raw
  AF-13 P3 spec (validated once up-front via `parse_constraint_spec`, so a malformed spec raises `ConstraintSpecError`
  before any run — pinned by `test_iterate_rejects_bad_constraint`).
- `from tests.automation_harness import assert_converges_to_constraint` — `(result, *, target_nm, tol_nm,
  min_confidence=RMSF_PRELIM_FRAMES)`. Asserts status=="met" + winning verdict confidence-gated + NO step flipped
  `met` below `min_confidence` + final within tol + **first attempt NOT already met** (non-vacuity). Can-go-red:
  exhausted run (`test_iterate_oracle_fires_on_exhaustion`, unreachable target), vacuous (`..._on_vacuous_convergence`,
  initial knob on-target).
- **The augment fixture (reuse this for any mock-binary convergence demo):** a **bend-curvature knob** on a 2-helix
  HONEYCOMB bundle (`_build_bent_bundle`/`_bisect_kappa` in `test_headless_oxdna_build.py`). KEY INSIGHT: the identity
  mock can't move atoms, so the relaxed mean reproduces the DESIGN geometry — therefore a **topology** knob (the bend)
  is what moves the measured end-to-end, *not* the relaxation. Probed monotone profile (deg/bp→nm): 0→13.74, 2.0→12.64,
  2.5→12.04, 3.0→11.33; **landmarks stay stable across curvatures because a bend is a deformation overlay, not a
  topology change** (fixed `(helix_id, bp_index, direction)` keys). Bisection converges in ~3 iterations.
- **GOTCHAS banked:** (1) the inner production-growth loop relies on the rmsf route pooling EVERY production stage's
  frames — `append_production(steps=1000)` adds 10 frames/round (`_MOCK_OXDNA_TRAJ`, `max(1,steps//100)`), so
  `min_confidence=25` needs ≥3 rounds (`test_iterate_grows_production_on_inconclusive`). (2) The oracle's non-vacuity
  guard means a convergence demo MUST start off-target — for the `met`-on-attempt-0 case (the inconclusive test) assert
  on `result` fields directly, NOT via `assert_converges_to_constraint`. (3) NO ASK-FIRST was needed: the loop is
  direction-AGNOSTIC end-to-end — curvature is a magnitude, end-to-end is Euclidean, the bend wrapper is AF-6's cleared
  machinery; zero frame/sign reasoning entered the driver or the fixture.

**▶ REFERENCE (the Tier-5 oxDNA spine is COMPLETE; all four planned `measure_*` kinds — `end_to_end`,
`radius_of_gyration`, `segment_angle`, `inter_helix_spacing` — DONE; the design `constraints` block is now WIRED, AF-13
P5 above — the live ▶ NEXT is the top-of-file handoff):**
- **Adding any further `measure_*` is now fully templated.** Point-landmark measure = name + arity +
  `_dispatch_measure` arm + `assert_relaxed_measurement` branch + analytic pins (reuse segment_angle as template).
  An axis/helix-grouping measure = same tail + a `_fit_helix_axis`-style grouping core (reuse inter_helix_spacing).
  No remaining measure needs new arity machinery.
- **Stragglers:** `polymerize_periodic` SHIPPED 2026-06-22 (`hab.polymerize_periodic` + `assert_periodic_chain_tiles`).
  Remaining: `bind_overhangs` ASSEMBLY spec op (DEFERRED pending overhang-binding firming).

**▶ HARNESS NOW AVAILABLE (AF-17, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox`. **Auto-tune a relaxation:** `hox.run_relaxation_tuned(
  design, ws, *, hostname=None, **relax_params) → terminal OxdnaJob` — resolves `metadata.hardware_defaults[host]`
  → backend/device and relaxes on it (CPU/"0" fallback when none). Explicit `backend=`/`device=` in `**params`
  override. **This is what AF-13 P4 should call per iteration** instead of `run_relaxation` (which is hard-coded
  CPU by the caller). **Run a benchmark headlessly:** `hox.run_oxdna_benchmark(design, ws, *, steps=, configs=,
  runner=) → result dict` (carries `["recommendation"] = {backend, device, steps_per_s, proxy_nucleotides}`,
  `["note"]`, `["state"]`). **Persist it:** `hox.apply_oxdna_benchmark(design, recommendation, *, hostname=) →
  new Design` (a COPY; original untouched). Pure read side: `from backend.core.benchmark import
  resolve_oxdna_relax_config` `(HardwareBenchmark | None) → {backend, device}`.
- `from tests.automation_harness import assert_relax_honors_hardware_default` — `(design, ws, *, backend,
  device="0", **params) → tuned OxdnaJob`: pass a design with NO `hardware_defaults` for this host and a NON-CPU
  config; it proves the baseline falls back to CPU AND the applied default reaches the job's `backend`/`device`.
- **GOTCHAS banked:** (1) `run_oxdna_trials` rmtree's its workdir on exit, so `run_oxdna_benchmark` runs in a
  `ws/benchmark_runs/<id>` SUBDIR — never hand it the bare workspace or it wipes a sibling relaxation's job dir.
  (2) `run_oxdna_trials` calls `find_oxdna()` BEFORE the injected `runner`, so even a stub-runner test needs
  `$OXDNA_BIN` set (the `mock_oxdna` fixture). (3) the per-trial label passed to `runner` is `bench-<id>-<i>`
  (config INDEX, not the config label) — key any stub timing off the trailing index. (4) **this dev box HAS a
  GPU** (RTX 2080 SUPER), so the real `oxdna_config_grid` includes a CUDA trial and `pick_best_oxdna` returns
  CUDA on the mock (tie-break prefers CUDA) — a producer test must be backend-agnostic (`in {"CPU","CUDA"}`), not
  assume CPU. (5) the mock binary ignores the declared backend, so requesting CUDA headlessly completes GPU-free —
  that's what makes the bridge oracle testable without a real device.

**▶ HARNESS NOW AVAILABLE (AF-13 P3, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import parse_constraint_spec, check_relaxed_constraint, ConstraintSpecError`.
  `parse_constraint_spec(spec)` → normalised `{measure, landmarks:[(hid,bp,dir),…], target_nm, tol_nm,
  min_confidence}` (landmarks → tuples, direction enum→str; **idempotent** on its own output; `min_confidence`
  defaults to `RMSF_PRELIM_FRAMES`=50). `check_relaxed_constraint(constraint, relaxed_output)` takes a RAW or
  parsed constraint (it re-parses) + the dict `hox.read_flexibility_map` returns (`{ready, positions,
  confidence:{n_frames,…}}`) → the verdict dict. **It is PURE — `backend/core` takes the already-read dict and
  never imports `headless_oxdna_build`** (the api read-wrapper); the *caller* fetches the map then hands it in.
- **The three statuses:** `met` (n_frames ≥ min_confidence AND |measured−target| ≤ tol), `unmet` (enough frames,
  out of tol), `inconclusive` (too few frames OR no production mean structure yet). `measured_nm` is still
  reported when positions exist (so a loop watches convergence) but `met` follows `status` strictly.
- **GOTCHAS banked:** (1) the confidence gate is the whole point — AF-13 P4's iterate loop MUST branch on
  `status`, never on `measured_nm` alone, or it will converge on a noisy low-frame estimate. (2) tolerance
  boundary is inclusive (`<=`); float-exact test values (target 4.5/tol 0.5 on a 5.0 nm measurement) avoid the
  `4.6 → 0.40000…036 > 0.4` trap. (3) adding the next `measure_*` kind = add a `measure_*` fn next to
  `measure_end_to_end`, add the name to `_CONSTRAINT_MEASURES`, and add a dispatch arm in `check_relaxed_constraint`
  (currently it calls `measure_end_to_end` directly since parse pins the only measure). (4) the checker is now
  wired into `build_spec.py` by AF-13 P5 — a design `constraints` block lowers to `hs.build_and_check_design`.

**▶ HARNESS NOW AVAILABLE (full-sequencing feature, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.full_sequence(scaffold_name="M13mp18", *, custom_sequence=,
  strand_id=)` fully sequences a **routed single-scaffold** origami (assigns the scaffold sequence to every scaffold
  strand, then WC-complements every staple → zero undefined bases, export/oxDNA ready). `hb.assign_staple_sequences()`
  is the bare WC-complement-staples wrapper (422s without a scaffold sequence). **Needs `auto_scaffold` first** on a
  raw bundle (one scaffold strand per helix won't cover the staples — the staple complement is taken from the single
  *active* scaffold). Coverage **35 → 36** (`assign_staple_sequences` flipped).
- `from tests.automation_harness import assert_fully_sequenced` — `(design, *, require_wc=True) → n_WC_checked`:
  zero undefined bases (the `create_oxdna_job` / export gate) AND every scaffold-paired staple base is the WC
  complement of its scaffold base (checked independently of the assignment code). This is the cleaner way to get a
  sequenced design for the AF-13 oxDNA fixture than the `_sequence_for_oxdna` test helper. Can-go-red: unsequenced →
  "undefined"; wrong base → "WC complement".

**▶ HARNESS NOW AVAILABLE (AF-13 P1, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox`. **One-call:** `hox.run_relaxation(design, workspace, *,
  timeout=30.0, min_bp_retained=0.0, backend="CPU", mc_steps/md_relax_steps/equil_steps=100, …) → terminal
  OxdnaJob` (create no-autostart → start → poll). **Lower-level:** `create_job` (returns dict, read `["job_id"]`)
  / `start_relaxation(job_id, ws)` / `append_production(job_id, ws, *, steps)` / `read_relaxed_positions(job_id,
  ws)` (drives the display route → `{ready, positions, n_positions}`) / `wait_for_terminal(job_id, ws, *,
  timeout)`. Each route wrapper temporarily redirects `routes_oxdna._WORKSPACE_DIR` (a `_use_workspace` cm) and
  `create_job` binds the design into a scratch doc (`_scratch_design`) so nothing touches the real workspace /
  active design. Route handlers are `async` → driven via `asyncio.run`.
- `from tests.automation_harness import assert_relaxed_geometry_recovered` — `(job, design, workspace, *,
  expected_count=None)`: status `completed` + display reads back exactly one finite position per design
  nucleotide, every key a real `(helix_id, bp, dir)`. Returns the display dict. Can-go-red: non-completed job →
  "did not reach completed"; wrong count → "expected …".
- **GOTCHAS banked:** (1) **the design must be FULLY SEQUENCED** — `create_oxdna_job` 400s on any undefined base;
  reuse `_sequence_for_oxdna` (M13 + WC complements) from `test_oxdna_relaxation.py`. (2) **The mock binary does
  NOT relax** (it copies conf→last_conf), so pass `min_bp_retained=0.0` or the bp-retention gate fails the job
  (mirrors `test_runner_end_to_end`). Real GPU runs raise it back to ~0.5. (3) `get_oxdna_display` is a **GET**
  (read-only) → correctly absent from the *mutation* coverage audit; it's pinned instead by the
  import-identity test. (4) Reuse the `mock_oxdna` fixture by copying its 6-line body from `_MOCK_OXDNA` (a
  cross-module pytest fixture import trips ruff F811).
- **The Three-Layer Law is the spine of the rest of Tier 5:** oxDNA output is read back as a Physical-layer
  position map and **never written into `Design`**. AF-13 P1 exposes ONLY the read path. Phase 4's iterate loop
  will EDIT topology (a knob) and RE-RELAX — it must never write the relaxed coords back.

**▶ HARNESS NOW AVAILABLE (AF-13 P2, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import measure_end_to_end` — pure `(positions, landmark_a, landmark_b) →
  distance_nm`. `positions` = the per-nucleotide list from `production_rmsf` (mean structure) OR the display
  readback; each landmark = a `(helix_id, bp_index, direction)` tuple (direction may be the `Direction` enum or
  its string value — normalised). Raises on empty map / identical landmarks / absent landmark (no silent 0/NaN).
  This is the reusable `measure_*` primitive — add `measure_radius_of_gyration` / `measure_inter_helix_spacing`
  / `measure_segment_angle` here the same way for the other constraint kinds.
- `from backend.api import headless_oxdna_build as hox` → `hox.read_flexibility_map(job_id, ws)` drives the REAL
  `GET /oxdna/jobs/{id}/rmsf` → `{ready, positions (mean backbone xyz per nuc), confidence:{n_frames, rel_error,
  preliminary}, …}`. **Needs a prior `append_production` run** (returns `{ready:False}` until production frames
  exist). The mean cancels thermal noise; prefer it over `read_relaxed_positions` (single frame) for measurement.
- `from tests.automation_harness import assert_relaxed_measurement` — `(job, measure_spec, target_nm, tol_nm, *,
  workspace, min_confidence=RMSF_PRELIM_FRAMES)`: status-completed + reads the mean structure + **confidence gate**
  (≥ `min_confidence` pooled frames else "INCONCLUSIVE"-raise) + measured ∈ [target±tol]. `measure_spec =
  {"measure":"end_to_end","landmarks":[a,b]}`. Returns `{measured_nm, target_nm, tol_nm, n_frames, confidence}`.
- **GOTCHAS banked:** (1) **The shared `_MOCK_OXDNA` writes NO `trajectory.dat`** → the rmsf route has no frames
  → `{ready:False}`. AF-13 P2's tests use a purpose-built `_MOCK_OXDNA_TRAJ` (in `test_headless_oxdna_build.py`)
  that also emits a multi-frame `trajectory.dat` (frames = `max(1, steps//100)`, the input conf repeated). Reuse
  it for any oxDNA test needing a mean structure. (2) **`ProductionRequest.steps` has a 1000 minimum** — to get a
  *few*-frame (preliminary/low-confidence) run pass `steps=1000` (→10 frames), not <1000 (pydantic 422). (3) The
  mock is identity (last_conf == input conf), so the relaxed mean reproduces the **design's own** end-to-end
  (~0.002 nm gap) — the absolute target in the test is `measure_end_to_end(_geometry_for_design(design), a, b)`;
  a real GPU run moves atoms so the target would be the user's desired distance. (4) `get_oxdna_rmsf` is a GET →
  pinned by `hox._route_get_rmsf is routes_oxdna.get_oxdna_rmsf`, NOT the mutation-coverage count.

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — AF-13 Phase 4" pointer here — P4 SHIPPED 2026-06-19. The
live open work is the top-of-file handoff (P5 knob clause + stragglers).]_

**▶ HARNESS NOW AVAILABLE (AF-16, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.add_cluster(name, helix_ids, *, domain_ids=(), log=False)`.
  `log=True` appends a `ClusterCreateLogEntry` (`feature_type="cluster_create"`, fields `cluster_id`/`name`/
  `helix_ids`/`domain_ids`) to `design.feature_log` with the same cursor-truncation as `update_cluster`'s commit+log.
  Default `log=False` — backward-compatible, so the capstone + all existing cluster tests are unaffected.
- `from tests.automation_harness import assert_cluster_in_feature_log` — `(design, cluster_id, *,
  expect_helix_ids=None)`: exactly one `cluster_create` entry for `cluster_id`, helix set == the live cluster's
  (or `expect_helix_ids`), name matches. **canonical_topology is BLIND to clusters** (the loop/skip / deformation /
  pose blind-spot, 4th time), so this entry is the ONLY proof a grouping persisted — call it on a `roundtrip_nadoc`
  result to pin `.nadoc` survival. Can-go-red: unlogged build → no entry → raises.
- **GOTCHA banked:** `add_cluster` uses `design_state.set_design` (undo-pushing), NOT `mutate_and_validate` — the
  log append rides inside the single `copy_with(...)` that already builds `cluster_transforms`, so it's one undo
  step. The cursor truncation (`feature_log[:cursor+1]`) matters only if a logged `add_cluster` follows an undo;
  mirror `update_cluster` exactly and it's correct.
- **Follow-up (optional):** the capstone `build_parallelogram` clusters its 4 bars with `log=False`; switching to
  `log=True` would make its generated feature log truly complete (the AF-16 motivating use case) — cosmetic, the
  linkage oracle doesn't read the log.

**▶ HARNESS NOW AVAILABLE (AF-14 P3, use it — do NOT rebuild):**
- `from backend.core.cluster_obb import recommend_hinge_joints` — `(design, cluster_id, *, anchor="corner",
  axial_tol_deg=20.0, target_rom_deg=None, …) →` all 12 OBB edges ranked best-first
  (`{edge, edge_length, angle_to_axis_deg, is_axial, rom_deg, axis_origin, axis_direction}`). Priority:
  **non-axial first → longest edge → ROM tiebreak.** `axis_origin` honours `anchor`; axial (`w`) edges demoted
  to the tail but still present (so a caller can see them / a red-test can find one).
- `hull_prism_axis(…, edge=key, anchor="corner")` + `hb.place_cluster_joint(cid, edge=key, anchor="corner")` —
  `anchor` defaults to `"midpoint"` (backward-compatible; the capstone + all existing tests use it). `"corner"`
  stores the edge's `−axis` endpoint as the anchor; **same hinge line** (so `assert_joint_on_hull_corner(…,
  edge=key)` still passes — proven by `test_place_cluster_joint_corner_anchor_stays_on_edge`).
- `from tests.automation_harness import assert_recommended_hinge` — `(design, cluster_id, *,
  recommendations=None, axial_tol_deg=20, tol_nm=0.05, length_tol_nm=0.1)`. Re-measures on the independent OBB
  that the #1 hinge is non-axial + longest-non-axial + corner-anchored; pass `recommendations=` a hand-built
  list to drive the can-go-red guards.
- **GOTCHA banked:** for a real edge a corner and the midpoint are half-an-edge-length apart, so the
  corner-anchor check (`d_corner < tol_nm`) ALSO catches a midpoint anchor (it's far from every corner) — there
  is no separate "is it the midpoint" assertion (it would be unreachable). On a 2×6 SQUARE bar the wide `u`-edge
  (6 cols) is the top hinge; `v` (2 rows) second; the 4 axial `w`-edges last.
- **Follow-up (optional, not blocking):** the capstone's `build_parallelogram` still hinges on the axial
  `w`-edge (`_SIDE_EDGE` in `test_parallelogram_linkage.py`) — a barrel-roll. Re-pointing it at the recommended
  cross-section edge would make the demo use the AF-14-P3 rule, but it's cosmetic (the linkage oracle is
  direction-agnostic).

_[AUDIT 2026-06-21: removed the superseded "▶ AF-16" NEXT pointer here — AF-16 SHIPPED 2026-06-18.]_

**▶ AF-11 P2 design grammar DONE — the bulk-routing + apply_loop_skips ops are built + validated.** 4 new design
ops in `build_spec.py` (`auto_scaffold {op,seamless}` / `auto_crossover {op}` / `full_autostaple
{op,scaffold_name,custom_sequence,strand_id}` / `apply_loop_skips {op}`, all NON-primordial) + 4 dispatch branches
in `headless_spec_build.py` driving the real `hb.*` wrappers. **Oracle split (the AF-11-P2 lesson again):**
`assert_spec_matches_calls` is LOAD-BEARING for the 3 routing ops (they add strands the fingerprint sees — a dropped
op diverges from the hand build) but BLIND to `apply_loop_skips`' baked marks (outside the strand graph), so that op's
load-bearing pin is the AF-3 per-helix `geometric_nucleotide_count` conservation (`Δgeom == 2 × net marks`).
**GOTCHA banked:** `auto_crossover` ALONE leaves staples nicked at crossovers → `validate_design` FAILS → you cannot
`assert_roundtrip_stable` on a scaffold+crossover-only design; the round-trip target must be the COMPLETE
`full_autostaple` build (which breaks+merges into a valid design). `apply_loop_skips` needs SQUARE + crossovers
(`auto_crossover` provides them); a bare-bundle `apply_loop_skips` 400s (pinned by a red-test).

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — pick one" pointer here (recommended AF-13 Phase 4, SHIPPED
2026-06-19). Current open work = top-of-file handoff.]_

**▶ HARNESS NOW AVAILABLE (AF-14 P2, use it — do NOT rebuild):**
- `from backend.core.cluster_obb import obb_sweep_rom, cluster_range_of_motion, rank_joint_candidates`.
  `cluster_range_of_motion(design, cluster_id, axis, *, obstacles=None, min_angle_deg=-180, max_angle_deg=180,
  pad=HELIX_RADIUS, step_deg=2.0) → ROM_deg` — the anchored cluster swings (others static); ROM = total
  two-sided free swing (θ⁺+θ⁻) about the world `axis=(origin,direction)` (use `hull_prism_axis(...,edge=…)`),
  clamped to the limits, OBBs padded by helix radius so contact is rim-to-rim. `obb_sweep_rom(...)` is the pure
  OBB-only core (no design — hand it synthetic `OBB`s). `rank_joint_candidates(design, cluster_id, *,
  target_rom_deg=None)` → the 12 OBB **edges** ranked by ROM desc (door-jamb: interface edge swings least,
  away-facing edge swings free), optional `target_rom_deg` filter.
- `from tests.automation_harness import assert_range_of_motion` — `(design, cluster_id, axis, expected_deg, *,
  tol_deg=2.0, min_angle_deg, max_angle_deg, pad=None, step_deg)`. Direction-AGNOSTIC magnitude; physical-bound
  guard + can-go-red on a wrong angle.
- **GOTCHA banked:** SQUARE bars are LONG+THIN (a 2×3 bar OBB ≈ u-half 2.25 / v-half 1.12 / w-half 5.34 nm).
  Hinging about a vertical `("w",…)` edge sweeps only the small u–v cross-section, so the swing *reach* is ~the
  u-width (~4.5 nm) — an obstacle must be within that to register contact (an 8 nm gap reads 360°). The
  contact-sensitive hinge is the edge **nearest** the neighbour (`_near_w_edge` in the test): one swing sense
  drives A's bulk straight into B, ROM grows monotonically with the gap (≈156°→275° over gaps 1–4 nm).

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — THE CAPSTONE 4-bar parallelogram" pointer — SHIPPED
2026-06-17 (`tests/test_parallelogram_linkage.py`, AF-15 P2 sub-item).]_

**▶ HARNESS (AF-14 P1, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.place_cluster_joint(cluster_id, *, edge=(axis,s1,s2) |
  corner=(su,sv,sw)+face=(axis,sign), name=…, min_angle_deg=…, max_angle_deg=…)` — places a revolute joint
  anchored on a named OBB feature; drives the real `add_joint` route (covered). Read the new id from
  `design.cluster_joints[-1].id`.
- `from backend.core.cluster_obb import hull_prism_axis` — pure `(design, cluster_id, *, edge | corner+face) →
  (origin, direction)`. EDGE mode = hinge along the OBB edge (origin=midpoint, dir=edge line). CORNER mode =
  point pivot at the corner, dir=`OBB.face_normal((axis,sign))` (NEW method on `OBB`). The corner must lie on the
  named face (it validates). REUSES `cluster_obb` so the axis tracks any pose.
- `from tests.automation_harness import assert_joint_on_hull_corner` — `(design, joint_id, *, edge | corner+face,
  tol_nm=0.05, tol_deg=1.0)`. Re-derives the joint's world axis from its cluster-LOCAL storage +
  `_local_to_world_joint` (so it survives the route's world→local→world trip on a POSED cluster — the local-frame
  round-trip test proves this), recomputes the OBB, asserts collinear-with-edge / through-corner.
  Direction-AGNOSTIC. Can-go-red on a different edge/corner.

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — AF-14 Phase 2" and "▶ THEN the capstone" pointers — AF-14 P2
SHIPPED 2026-06-17 and the 4-bar capstone SHIPPED 2026-06-17.]_

**▶ GOTCHAS BANKED from AF-14 Phase 1 (read before Phase 2):**
- `cluster_obb` RAISES on a square footprint (ambiguous u/v, in-plane eigenvalue ratio < 1.10) and on < 2 helices —
  ROM fixtures must be **rectangular** (the tests use a 2×6 SQUARE grid; a single bar clustered whole).
- The OBB `half`/`axes`/`center` bound the helix **axis endpoints**, NOT the DNA surface. Phase 2's swept-OBB
  clearance probably wants a **surface pad** (helix radius) so two bars touching rim-to-rim register contact before
  their axis boxes overlap — decide the pad when you build the SAT.
- A `ClusterJoint` does NOT move helices, so `cluster_obb(before) == cluster_obb(after)` across a joint placement —
  the OBB is stable to anchor against. For ROM, the moving body's OBB is *swept*, the obstacle OBBs are static.

**▶ GOTCHAS BANKED from AF-15 Phase 2 (read before AF-14):**
- The OBB cross-section frame uses **PCA**, NOT `deformation._initial_cross_section_frame` (that one snaps u/v to
  WORLD axes by the dominant tangent → not equivariant → edge keys jump after a pose). The PCA frame is
  equivariant; its sign anchor is **positional** (first sorted-id helix with a clear u-projection), NOT an
  argmax over offsets — a value-argmax ties on the 4 symmetric corners and float-rounding flips the frame after a
  rotation (this bit once; the equivariance test catches it). **`cluster_obb` RAISES on a square footprint**
  (ambiguous u/v, in-plane eigenvalue ratio < 1.10) and on < 2 helices — AF-14 fixtures must be **rectangular**
  (the tests use a 2×3 / 2×6 SQUARE grid).
- `OBB.half`/`axes`/`center` bound the helix **axis endpoints** (not the DNA surface) — fine for edge alignment
  and joint placement; AF-14's ROM may want a surface pad (helix radius) for true clearance — decide then.

**▶ DEFERRED — `bind_overhangs` (AF-11 Phase 2 last sub-op): PENDING FURTHER DEVELOPMENT.**
Per user (2026-06-17): **overhang binding still needs work in general** before it's ready to expose to users
through the build-spec grammar — do NOT add the `bind_overhangs` spec op until the underlying overhang-binding
system is firmed up. The relations cluster (`gear`/`belt`/`polymerize`/`bind_overhangs`) is otherwise COMPLETE:
**`gear` + `belt` + `polymerize` SHIPPED**; `bind_overhangs` parked here. When it's revived, the plan below holds.
Drive `hab.bind_overhangs(inst_a, inst_b, *, overhang_a_id, sub_domain_a_id, overhang_b_id, sub_domain_b_id,
binding_mode=…)` (AF-9 overhang-binding wrapper). **Spec shape (proposed):**
`{"op":"bind_overhangs","instance_a":"<ref>","instance_b":"<ref>","overhang_a":…,"sub_domain_a":…,
"overhang_b":…,"sub_domain_b":…,"binding_mode":…}` — it references two prior `add_part` instance `ref`s (the
*instance* namespace `defined`, NOT the joint `ref` namespace gear/belt/polymerize use — bind couples
overhangs, not joints). **The fixture gotcha (TWO traps):** (1) each part design needs `grid_pos` SET on its
helices (the AF-5 `grid_pos=None` TypeError trap) AND an `OverhangSpec` (which auto-populates one sub-domain) —
the inline `_BEAM_SPEC`/`make_6hb_design()` fixtures have NEITHER, so this sub-op needs a NEW part-spec fixture
carrying overhangs (or a `bundle` + an overhang-extrude design op the grammar does NOT have yet — likely a NEW
part-builder fixture in the test, not a new grammar op). (2) the spec must surface the runtime
`(overhang_id, sub_domain_id)` of each part — these are generated at build time, so the driver must look them up
on the built part design, not hard-code them; decide whether the spec names sub-domains by index/label or the
driver resolves "the part's sole overhang". **Oracle:** `assert_binding_resolves(assembly, binding_id, *,
require_cross_part=True)` is the LOAD-BEARING one — `canonical_assembly` (5-tuple, fingerprints `overhang_bindings`)
catches a dropped/rewired binding, but `canonical_topology` is BLIND to a design's overhangs/sub-domains, so a
round-trip that regenerated a sub-domain id while the binding kept its stale ref slips past the fingerprint —
only `assert_binding_resolves` catches that. So pair `assert_spec_matches_calls` (structural) with
`assert_binding_resolves` (referential integrity, the real proof).
**Discipline:** the driver DRIVES the real `hab.*` wrappers — never re-implement — so coverage stays flat
(composition sugar, 32; `test_spec_build_adds_no_coverage` guards it). **PICK THE ORACLE BY WHAT THE OP CHANGES (the
load-bearing AF-11-P2 lesson, confirmed seven times now):** `assert_spec_matches_calls` is the golden pin ONLY when
`canonical_topology`/`canonical_assembly` can see the op's effect — load-bearing for strand-graph ops AND for
fingerprinted top-level assembly relations (gears/belts/joints/instances/polymer-chains/bindings, since AF-9),
VACUOUS for overlays outside it (`loop_skip`→`geometric_nucleotide_count`, `bend`/`twist`→`assert_deformation_angle`).
For relations ALSO pair it with the kinematic/semantic oracle (`assert_gear_ratio` / `assert_polymer_chain` /
`assert_binding_resolves`) — the fingerprint catches a dropped/rewired relation, the semantic oracle catches one
that's present-but-doesn't-work. **NEW lesson from polymerize:** NOT every relations sub-op needs the revolute gate —
polymerize takes a SINGLE seed mate of ANY joint_type, so its referential-integrity branch omits the gate gear/belt
enforce (`test_assembly_spec_polymerize_allows_rigid_seed` pins that). `bind_overhangs` references the *instance*
namespace, not the joint one — a third referential-integrity shape.
**HOW:** mirror this session — `_ASSEMBLY_OP_KEYS` entry + parse branch + referential-integrity (resolve the right
ref namespace) + dispatch branch + grammar-rejection tests + a driver test using the op's own oracle.

**▶ ~~DEFERRED~~ DONE 2026-06-18 — `apply_loop_skips` (design op).** Shipped alongside the `auto_scaffold`/
`auto_crossover`/`full_autostaple` cluster (as planned): `auto_crossover` now produces the cross-helix domain
transitions its route demands, so a SQUARE `bundle → auto_scaffold → auto_crossover → apply_loop_skips` spec bakes
the periodic-skip pattern, pinned by the AF-3 per-helix `geometric_nucleotide_count == 2×net_marks` conservation
check (`test_apply_loop_skips_spec_honors_marks_per_helix`, mirroring
`test_apply_deformations_geometry_honors_marks_per_helix`). A `test_apply_loop_skips_spec_requires_crossovers`
red-test pins that the op runs the real route (400s on a bare bundle).

**▶ STRAGGLER (still open, its own session) — `polymerize_periodic`.** The SINGLE-part `is_periodic_seam` path
with the `derive_periodic_delta` Kabsch oracle was NOT built: it needs a part carrying `is_periodic_seam=True`
forced ligations the inline `make_6hb_design()` fixtures don't have. Build one headlessly via the
route-for-polymerization op first, then assert each copy sits at `T_seed @ derive_periodic_delta(design)^k`.

**▶ HARNESS NOW AVAILABLE (AF-11, use it):** `from tests.automation_harness import assert_spec_matches_calls`.
`assert_spec_matches_calls(build_from_spec, build_by_hand, *, kind="design"|"assembly")` — the faithful-façade /
golden-pin oracle: asserts a spec build produces the SAME `canonical_topology` (design) / `canonical_assembly`
(assembly) as the equivalent hand-call wrapper sequence, with a non-emptiness guard so it can't pass vacuously.
Builders: `from backend.api import headless_spec_build as hs` → `hs.build_design(spec)` / `hs.build_assembly(spec)`
(both parse → drive real wrappers in a scratch session → standalone deep copy; raise `BuildSpecError` at PARSE
time on a malformed spec). Parser: `from backend.core.build_spec import parse_design_spec, parse_assembly_spec,
BuildSpecError` (pure, HTTP-free — test grammar/rejection here without any build). Design helices are referenced
by `grid_pos` `[row,col]`; assembly instances by spec `ref` key; a part = a nested design spec under `parts`.

**▶ STRAGGLER (still open, its own session) — `polymerize_periodic`.** The SINGLE-part `is_periodic_seam` path
with the `derive_periodic_delta` Kabsch oracle was NOT built: it needs a part carrying `is_periodic_seam=True`
forced ligations the inline `make_6hb_design()` fixtures don't have. Build one headlessly via the
route-for-polymerization op first, then assert each copy sits at `T_seed @ derive_periodic_delta(design)^k`.

**▶ HARNESS NOW AVAILABLE (AF-10, use it):** `from tests.automation_harness import assert_instances_on_grid,
assert_instances_on_ring`. `assert_instances_on_grid(assembly, rows, cols, *, pitch, row_pitch=None, plane="XY",
tol_nm=0.01, instance_ids=None)` — reads the placed instance origins and asserts they form the exact rows×cols
lattice (count, even spacing == pitch on each axis, every cell filled), id-independent, with a `pitch>min_pitch`
non-degeneracy guard. `assert_instances_on_ring(assembly, n, *, radius, plane="XY", center=(0,0,0), tol_nm=0.01,
angle_tol_deg=1.0, instance_ids=None)` — every origin at `radius` from `center` + even angular step `360°/n`,
with a load-bearing `radius>min_radius` guard (radius=0 stacks all at centre → vacuous). Builders:
`hab.place_grid(design, rows, cols, *, pitch, row_pitch=None, plane="XY", center=False)` /
`hab.place_ring(design, n, *, radius, plane="XY", start_angle_deg=0.0, center=(0,0,0))` — pure-translation
placement (identity orientation; radial *facing* deferred as an ASK-FIRST orientation convention). Both are
construction sugar over `add_inline_instance` (NO route wrapped → coverage unchanged). Pure math in
`backend/core/instance_layout.py` (`grid_translations` / `ring_translations`, plane in {XY,XZ,YZ}). Keep layout
counts ≤6 if you round-trip (the >6-'full'→cylinders downgrade still applies).

**▶ HARNESS NOW AVAILABLE (AF-9 overhang-bindings, use it):** `from tests.automation_harness import
assert_binding_resolves`. `assert_binding_resolves(assembly, binding_id, *, require_cross_part=True)` — a
referential-integrity oracle for cross-part `AssemblyOverhangBinding`s: loads each endpoint's part design with
the route's own `_load_design_from_source` and asserts both `(overhang_id, sub_domain_id)` refs resolve, plus a
non-degenerate / cross-part guard. Use it AFTER a round-trip too — it catches the gap `canonical_assembly` can't:
`canonical_topology` doesn't fingerprint a design's overhangs/sub-domains, so a round-trip that regenerated a
sub-domain id while the binding kept its stale ref slips past the structure fingerprint. Builders:
`hab.bind_overhangs(inst_a, inst_b, *, overhang_a_id, sub_domain_a_id, overhang_b_id, sub_domain_b_id,
binding_mode=…, allow_n_wildcard=…)` / `hab.patch_binding(binding_id, *, binding_mode=…)` /
`hab.unbind_overhangs(binding_id)`. `canonical_assembly` now returns a **5-tuple** `(instances, joints, gears,
belts, bindings)` — it fingerprints `overhang_bindings`, so a dropped/rewired binding fails the round-trip oracle.
The overhang fixture needs `grid_pos` set on its helices (the AF-5 `grid_pos=None` TypeError trap) and an
`OverhangSpec` (auto-populates one sub-domain).

**▶ HARNESS NOW AVAILABLE (AF-9 polymerize, use it):** `from tests.automation_harness import assert_polymer_chain`.
`assert_polymer_chain(assembly_before, assembly_after, seed_joint_id, *, count, direction="forward", tol_nm=0.01,
min_delta_nm=0.5)` — the geometric oracle for mate-seeded polymerize. Re-derives the seed mate's repeat
`delta = T_B @ inv(T_A)` from the seed pair's world transforms ALONE (NOT the route's chain helpers → independent,
not a tautology) and asserts the `count−2` new instances form the exact `delta`-power multiset (`delta^k @ T_B`
forward / `inv(delta)^k @ T_A` backward), matched id-independently within `tol_nm`, with a can-go-red guard that
`delta`'s translation > `min_delta_nm` (a stacked seed pair → every copy on the seed → vacuous). Returns the 4×4
`delta`. Builder: `hab.polymerize(joint_id, count, *, direction, additional_instance_ids=…)` — needs a seed mate
between **identical** parts (use the SAME `Design` object for both `add_inline_instance` calls so `_sources_match`
is true, else the route 422s). `canonical_assembly` already fingerprints instances+joints, so a polymerized chain
round-trips through `assert_assembly_roundtrip_stable` unchanged with **no** harness extension (polymerize adds no
new top-level relation list — unlike gears/belts).

**▶ HARNESS NOW AVAILABLE (AF-9 belts, use it):** `hab.define_belt(joint_a_id, joint_b_id, *, radius_a, radius_b,
side_a=…, instance_a_id=…, connector_a_label=…)` (the two joints must already be **revolute** mates, like the gear
fixture). The belt's coupling relation surfaces with the synthetic id `f"__belt__{belt.id}"`; pin it by reusing the
gear oracle — `assert_gear_ratio(before, after, f"__belt__{belt.id}", expected_ratio=radius_a/radius_b)` — which now
searches `_coupling_relations` (gears + belt-derived), so the SAME oracle handles both. `canonical_assembly` now
returns a **4-tuple** `(instances, joints, gears, belts)` — it fingerprints belt_paths, so
`assert_assembly_roundtrip_stable` catches a dropped/rewired belt. When you add the next top-level relation list
(rider chains, polymer groups), extend `canonical_assembly` in the same commit (4th time — see the banked lesson).

**▶ HARNESS NOW AVAILABLE (AF-9 gears, use it):** `from tests.automation_harness import assert_gear_ratio`.
`assert_gear_ratio(assembly_before, assembly_after, rel_id, *, expected_ratio, ratio_tol=0.02, min_angle_deg=2.0)` —
the resolve-invariant for any ratio-coupling relation. Drive ONE side with `hab.drive_joint(joint_id, radians)` (its
PATCH auto-propagates the relation — no separate `resolve()` needed), capture `assembly_state.get_or_404()` as
`after`, and the oracle measures the two coupled bodies' real *instance-transform* rotation magnitudes (via the gear
endpoint sides) and asserts driven/driver = `|expected_ratio|`, with a can-go-red "driver actually rotated" guard.
**Direction-agnostic** (magnitude only — `invert` flips sign not magnitude, so no ASK-FIRST). Builders:
`hab.define_gear(joint_a_id, joint_b_id, *, ratio, invert=False, endpoint_*=…)` (the two joints must already be
**revolute** mates) and `hab.drive_joint(joint_id, value_radians, *, endpoint_side=None, silent=False)`.
`canonical_assembly` now returns a **4-tuple** `(instances, joints, gears, belts)` — it fingerprints gear AND belt
relations, so `assert_assembly_roundtrip_stable` catches a dropped/rewired gear or belt.

**▶ HARNESS NOW AVAILABLE (AF-8, use it):** `from tests.automation_harness import assert_mate_coincident`.
`assert_mate_coincident(assembly, joint_id, *, tol_nm=0.01, min_offset_nm=0.5)` — the two mated connectors are
coincident in world space (uses the SAME `_get_connector_world` machinery resolve uses, on the instance-overridden
design) within tol, with a non-triviality guard (the mated part origins must be separated, else the coincidence is
vacuous — place mate connectors at a non-zero LOCAL offset from their part origins). Builders:
`hab.add_connector(inst_id, label, position, normal)` (LOCAL position/normal) then
`hab.define_mate(child_inst_id, parent_inst_id, *, child_label, parent_label, joint_type="rigid", axis_origin=,
axis_direction=, min_limit=, max_limit=)`. The mate SNAPS the child onto the parent connector at create time
(coincident before resolve too); pass `joint_type="revolute"`+`axis_*` for the AF-9 gear mates. `canonical_assembly`
now keys joints by `(type, conn labels, parent-src, child-src, value)` so a dropped/rewired mate fails the
round-trip fingerprint.

**▶ HARNESS NOW AVAILABLE (AF-7, use it):** `from tests.automation_harness import canonical_assembly,
roundtrip_nass, assert_assembly_roundtrip_stable`. `assert_assembly_roundtrip_stable(build_fn)` = one-line
"assembly validates + survives a real `.nass` import unchanged". `canonical_assembly(a)` = id/order-independent
(instances, joints) fingerprint. `roundtrip_nass(a)` = in-memory `to_json`→`POST /assembly/import` (inline parts
travel inside; no disk). Builder: `from backend.api import headless_assembly_build as hab` →
`hab.assembly_scratch_session()` / `hab.new_assembly()` / `hab.add_inline_instance(design, name=, transform=)` /
`hab.add_file_instance(path, …)` / `hab.resolve()` / `hab.translation(x,y,z)`. Keep test assemblies ≤6 full-rep
instances (import auto-downgrades >6 'full' → 'cylinders', which would change the rep field the fingerprint reads).

**▶ KNOWN GOTCHA found in AF-5 (still relevant if you reuse round-trip):** `make_bundle_deformed_continuation`
(`backend/core/lattice.py:1234`) is the **only** bundle builder that does NOT set `grid_pos` on its new
helix — every other (`make_bundle_design`/`_segment`/`_continuation`) does. So a deformed-continuation helix
has `grid_pos=None`, which (a) makes `canonical_topology` raise `TypeError: '<' not supported between NoneType
and tuple` (it sorts on grid_pos) → **`assert_roundtrip_stable` CANNOT be used on a design with a deformed
continuation** (AF-5 used only the deformed-frame oracle for that reason), and (b) may be *intentional* (a
non-None grid_pos could make the straight-geometry path recompute the helix position from the lattice and
clobber the baked deformed axis coords). **Do NOT just add `grid_pos=(row,col)` — it's a three-layer
directionality question; ASK the user.** Logged as `ISSUE-11` in `issues_ledger.md`.

**▶ HARNESS NOW AVAILABLE (AF-1..AF-6 foundational oracles, use it, don't re-derive):**
`from tests.automation_harness import canonical_topology, roundtrip_nadoc, assert_roundtrip_stable,
assert_inverse_pair, assert_geometric_length_delta, geometric_nucleotide_count, assert_circular_disc,
assert_on_deformed_frame, assert_deformation_angle, headless_coverage_report`.
- `assert_roundtrip_stable(build_fn)` — one-line "build survives save/load".
- `assert_inverse_pair(start, forward, inverse)` (AF-2) — op∘inverse is topology-identity, with a built-in
  "forward must actually mutate" guard. For add↔delete / nick↔ligate pairs.
- **`assert_geometric_length_delta(start, op, expected_bp_delta, *, helix_id=None, strands_per_bp=2)` (NEW,
  AF-3)** — op changes the geometry kernel's nucleotide count by exactly `expected_bp_delta` bp (× strands/bp).
  Direction-AGNOSTIC (counts how many nucs changed, not which way) → safe on bend/twist apply without sign
  reasoning. Pass `helix_id=` for the strong per-helix conservation check. `geometric_nucleotide_count(d, hid=None)`
  is the bare count. **Caveat banked: `canonical_topology` does NOT see loop/skips** (they're on the helix, not
  the strand graph) — so `assert_roundtrip_stable` can't prove a loop/skip persisted; use the geometric count.
- **`assert_circular_disc(design, requested_radius_nm, *, max_spread_nm=0.5, radius_tol_nm=0.5, helix_ids=None)`
  (NEW, AF-4)** — geometric oracle for parametric disc primitives: reads the *placed* helices' axis spans
  (not a stored field), orders by lattice column, asserts `circularity_spread < max_spread_nm` AND `fit_radius`
  within `radius_tol_nm` of the requested R. Pins the whole radius→geometry path. `helix_ids=` filters to the
  disc helices when other DNA is present.
- **`assert_on_deformed_frame(before, after, source_bp, cells, *, ref_helix_id=None, pos_tol_nm=0.02,
  min_deflection_nm=0.5)` (NEW, AF-5)** — geometric oracle for continuations onto a bent/twisted face: reads
  the *placed* helices' `axis_start`, asserts each lies on the independently re-derived deformed cross-section
  frame at `source_bp` AND that the deformed placement is displaced > `min_deflection_nm` from a straight
  extrude (the can-go-red guard, so it won't pass vacuously on an un-deformed design). Direction-agnostic.
  Returns the max deflection observed. **NB: needs a real bend/twist applied first** (now use `hb.add_bend`).
- **`assert_deformation_angle(design_after, plane_a_bp, plane_b_bp, expected_total_deg, *, ref_helix_id=None,
  angle_tol_deg=1.0, step_bp=1, min_angle_deg=5.0)` (NEW, AF-6)** — geometric MAGNITUDE oracle for bend/twist:
  walks the deformed frame in `step_bp` steps and SUMS each step's relative-rotation magnitude (unwraps past
  180°/360° — a 540° twist reads 540°, not folded), asserts total = `κ×(b−a)` (bend) / total twist, plus a
  can-go-red guard (fails on an un-deformed design). **Direction-AGNOSTIC** (no sign/frame reasoning → safe
  per the ASK-FIRST rule; a signed-curvature oracle was deliberately NOT built). `design_after` is the design
  after the deformation is applied.
- `headless_coverage_report()["uncovered_routes"]` IS the live AF backlog (**207 uncovered / 32 covered** after
  AF-9 overhang-bindings; paths carry the `/api` prefix — match with `.endswith()`). Now lists mostly
  `/assembly/*` layout/overhang-connection routes + the design cluster/extension residue (the AF-10+ gap).
- Headless wrappers now exist: `hb.nick/ligate/delete_strand` (AF-2); `hb.loop_skip(h,bp,delta)` +
  `hb.apply_loop_skip_deformations()` (AF-3, delta=0 removes); `hb.circle_segment(radius_nm)` (AF-4, SQUARE);
  `hb.bundle_deformed_continuation(cells, length_bp, *, source_bp, ref_helix_id)` (AF-5);
  `hb.add_bend(a, b, *, curvature_deg_per_bp, direction_deg)` + `hb.add_twist(a, b, *, total_degrees |
  degrees_per_nm)` (AF-6).

**▶ STRUCTURAL FACTS from the audit (don't re-derive these — they're durable):**
- `headless_build.py` exposes ~19 design ops; **`headless_assembly_build.py` now exists (AF-7/8)** with
  create/place/resolve/import + add-connector/define-mate — the AF-9..AF-10 gap is now gears/belts,
  overhang-bindings/polymerize, and layout helpers.
- Remaining design REST routes lacking a wrapper: overhang rotation, cluster ops (`/design/cluster`),
  strand-end-resize, extensions, scaffold-nick — plus the whole `/assembly/*` surface (AF-7+).
- Pixel-drag-only ops (crossover sprite place/move, domain-shift, strand-end-resize, helix-reorder) DO
  have coord-taking REST routes — they're headless-reachable; only the pixel→bp mapping is UI. The *truly*
  UI-only residue (lasso/select state, gizmo intermediate drags) has no coord route → those go to MV, not here.

**Gotchas banked:**
- The `/design/import` route does post-load processing (migrate split-staple domains, autodetect overhangs,
  backfill sub-domains, recompute flexible connections). `roundtrip_nadoc` drives the *real* route, so a
  build that survives the round-trip survives that processing too — but if a future op's output *isn't*
  idempotent under autodetect, `assert_roundtrip_stable` will (correctly) flag it. That's a real bug to fix
  in the op, not a harness false-positive.
- Coverage is matched by **endpoint function identity**, so a wrapper MUST import the exact route handler
  (`create_bundle as _route_create_bundle`), not re-implement it, to register as covered — which is also
  the anti-passthrough discipline. A wrapper that re-implements logic won't show as covered (good signal).

---

