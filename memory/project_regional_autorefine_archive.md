---
name: project_regional_autorefine_archive
description: History of the regional-autorefine investigation (Phases 5.0-5.4, the wholesale-placement refutation, the re-scope to a 1-5 edit fine-tuner). Head is project_regional_autorefine.md — do not read this in a routine loop.
metadata:
  type: project
---

# Regional autorefine — ARCHIVE (history only)

Split out of the head 2026-07-30 during the plan audit. The head
(`project_regional_autorefine.md`) carries the current state; this file is the
reverse-chronological work log that produced it. **Do not read this in a routine loop.**

> **MEASUREMENT CAVEAT — read before citing ANY number below.** Every twist/deviation
> figure in this archive was measured with the pre-exp34 protocol (8M production,
> `equil_steps=100_000`). exp34 (2026-06-29) showed the 3x6x400 SQ bundle has a **~5M-step
> twist equilibration transient**, so all of these are biased mid-transient reads with
> ~+/-9 deg scatter. The qualitative conclusions (placement moves net twist a lot; wholesale
> redistribution diverges) survived independent re-derivation in exp32/34/35, but the
> specific degree values did not. See `project_skip_twist_curvature_sweep.md` + LESSONS A8.

# Regional autorefine (Phase 5) — non-uniform skip placement

Extends [[project_skip_twist_selfconsistency]] (uniform-period secant) to place individual
deletions where the simulation says they're needed, instead of one-skip-every-N-bp.

## EMPIRICAL EVIDENCE FOR LOCAL REFINEMENT — exp31 baseline twist profile (2026-06-27)

Direct proof, from a real oxDNA mean structure, that twist accumulates **spatially non-
uniformly** along a square bundle — i.e. a uniform skip density is mismatched to where the
over-winding actually is, so local refinement is warranted. From [[project_skip_twist_curvature_sweep]]
(exp31), the 3×6×400 SQ bundle at the analytical baseline (period 48, uniform staggered skips,
150 skips): the cumulative twist-vs-position profile (24-bp bins, differential sim−analytic;
`results/profiles/uniform_d+0.csv`) is **flat over the front half and ramps in the back half**:

  - position 0→200 bp: cum twist stays ≤ 6° (essentially zero) — front half carries **~10%**.
  - position 200→400 bp: cum twist ramps 6°→58° — back half carries **~90%** of the 57.7° total.

So the bundle is locally near-untwisted in front and strongly over-wound in back, despite a
spatially-uniform deletion pattern. A uniform-density correction over-corrects the front and
under-corrects the back; the actionable fix is to concentrate added deletions in the bp~200–400
over-wound region. This is the concrete signal the per-bp twist profile (`measure_bundle_twist_
profile`) was built to expose, and it is the evidence base for resuming local refinement.

**Reconciliation with the "not viable" verdict below:** that conclusion was specifically about
*wholesale* redistribution of the FULL budget (moving ~all skips → ±30–45° net-twist swings from
register alone). It is NOT contradicted here: the LOCAL twist signal is real and large (~50° of
spatial imbalance), it's the control authority of mass re-placement that was the problem. The
right tool remains a small number of LOCALIZED edits (the re-scoped greedy fine-tuner) targeting
the profile's high-slope region — but exp31 shows the target may be a sustained gradient over a
whole half, not just 1–5 isolated hotspots, so the edit budget / placement may need to scale with
the integrated profile slope. Revisit when exp31 completes (compare uniform vs incremental vs
deviation profiles across Δ; see exp31 `conclusion.md`).

## Scope (user, 2026-06-26)

- **Objective: twist only, regional.** Keep the SAME net-twist gate (`bundle_twist`→0);
  regional placement does NOT change the net-twist number — its value is redistributing
  the SAME per-helix deletion count to match the LOCAL twist profile + spread strain.
- **Placement signals: geometric deviation + local mechanical strain** (NOT sequence
  masks, NOT manual keep-out — deferred).
- **Interactive (few sims):** placement is solved from already-computed fields (a
  surrogate), so it costs ZERO extra simulations; re-sim only to verify. (Rules out
  per-candidate-sim SA/evolutionary and differentiable-oxDNA.)
- **Deletions only, square lattice.** Insertions + honeycomb deferred.
- **HARD anti-clustering constraint (user):** forbid degenerate "6 skips clustered at the
  ends → correct net twist but the middle deviates." Placement must match the local
  accumulation, not just the endpoint.

## Literature verdict (deep-research, 2026-06-26 — 25/25 claims verified)

The del/ins twist/bend mechanism is canonical (Dietz/Douglas/Shih *Science* 2009; Ke et al.
2009 square lattice 33.75°/bp underwound → compensatory global RH twist). The uniform-period
rule = the textbook heuristic = our current secant. Regional/gradient placement was shown in
2009 but **manually, no optimizer**. oxDNA2 is a validated FORWARD twist predictor (Snodin et
al. *NAR* 2019) — **use oxDNA2** (oxDNA1 has a nick over-twist artifact); **bend magnitude runs
~4× stiff** vs cryo-EM (trust twist direction, treat bend as a guard not a target). mrdna,
MagicDNA 2.0, DNAxiS, CanDo/COSM all only PREDICT or are sim-informed; **none closes the loop
from a deviation field.** Closest prior art = Benson/Högberg *ACS Nano* 2019 (closed oxDNA-in-loop
discrete-edit evolutionary/SA/CNN) — but optimizes a SCALAR (rigidity), not a per-nucleotide
deviation field for shape. **Verdict: a regional, deviation+strain-field-driven sim-in-the-loop
deletion placer for twist/shape is genuinely novel** (composes validated ingredients never
combined this way). Pitfalls to design against: non-uniqueness, overfitting to one stochastic
mean, twist↔bend coupling.

## Chosen route: decompose COUNT + PLACEMENT

- **Count (net twist):** keep the existing global secant → per-helix deletion budget
  (`budget_from_uniform_period(design, period)` = exactly what `sq_lattice_periodic_skips`
  would place per helix). Preserves the net-twist gate AND keeps the A/B comparison equal-count.
- **Placement (where):** `place_regional_skips` redistributes that fixed budget using the
  per-(helix,bp) deviation + strain fields from the SAME mean structure (no extra sims).
  - deviation ATTRACTS (correct where the local error is); strain REPELS (a deletion adds
    tensile strain — don't pile onto already-stressed sites). Fields min-max normalised per
    helix; `score = w_dev·dev − w_strain·strain`. Defaults `w_dev=1.0, w_strain=0.25`
    (deviation-dominant; calibrate in 5.4).
  - **Anti-clustering GUARANTEE:** budget spread over EVENLY-SIZED slots, exactly ONE
    deletion per slot → the cumulative-deletion staircase tracks the linear ideal; the
    "all-at-the-ends" degeneracy is impossible by construction. Fields only bias the position
    WITHIN a slot, with `min_spacing` (default 4 bp).

## Built + green (Phase 5.0 + 5.1, 2026-06-26) — pure, no GPU

- `oxdna_health.backbone_strain_field(design, full_map) → {(helix,bp): strain_units}`:
  per-bond `|len − R0|` (reuses `backbone_bond_pairs`/`oxdna_backbone_site`), attributed to
  each touched (helix,bp) by MAX, strands collapsed by MAX.
- `backend/core/regional_skip_placer.py`: `place_regional_skips`, `budget_from_uniform_period`,
  `aggregate_deviation_per_bp`, `core_candidates`. Pure; returns `{helix:[LoopSkip(bp,-1)]}` for
  `apply_loop_skips`.
- Pins: `tests/test_regional_skip_placer.py` (10) — budget=count preservation, core-only,
  anti-clustering one-per-slot, deviation-attracts, strain-repels, min-spacing, determinism,
  non-square guard, strain-field aggregation. All green.

## Built + green (Phase 5.2 + 5.3, 2026-06-26) — integration, CPU-verified vs mock

- `skip_twist_tuning.build_regional_skip_design(base, period, deviation_by_bp, strain_by_bp, …)`
  — regional analog of `build_sq_skip_from_design`: budget from `budget_from_uniform_period`
  (count = uniform density), `place_regional_skips`, re-sequence. Empty fields => uniform-equivalent.
- `skip_twist_tuning.measure_skip_fields(job, ws, design, reference)` — harvests the next round's
  fields from the SAME job (deviation from the pooled mean vs `reference`; strain from the final
  production `last_conf`). Best-effort (returns `({},{})` on read failure → uniform fallback).
- `iterate_to_constraint` gained a generic `on_measure(design, reference, job, workspace)` hook
  (post-verdict); `autorefine_sq_design(regional=True, w_dev, w_strain, min_spacing)` uses a
  closure: secant sets the period (count/net-twist gate), `on_measure` updates the field closure
  AND captures the converged design.
- Result now carries `placement` ("regional"/"uniform") and, for regional, `converged_skips`
  ({helix:[bp]}) — the EXACT non-uniform pattern.
- **Apply path:** `build_explicit_skip_from_design(base, {helix:[bp]})` lays a verbatim pattern +
  re-sequences; the apply route applies `converged_skips` on the completion call (period=None) for
  a regional run, else the uniform period path (unchanged).
- Route request: `regional` + `w_dev`/`w_strain`/`min_spacing`, threaded route→`_run`→`autorefine_sq_design`.
- Pins (all green): `test_regional_skip_placer.py` (build_regional preserves count + resequences;
  build_explicit lays exact pattern), `test_skip_twist_tuning.py::test_autorefine_apply_regional_
  lands_explicit_pattern`, `test_headless_oxdna_build.py::test_autorefine_regional_runs_end_to_end_
  and_reports_pattern` (mock engine). Field BIASING itself needs a real engine → 5.4.

## 5.4 PROXY A/B — the one-shot decomposition premise is REFUTED (2026-06-26)

Proxy 2×3×40, period 24, uniform vs regional placed from uniform's deviation+strain fields:
- UNIFORM: twist −8.7°, bend 13.0°, dev mean 1.13 / max 3.50 / std 0.63 nm, 11 skips.
- regional w_dev=1 w_strain=0: **production BLEW UP** (deviation-only clustering destabilised it).
- regional w_dev=1 w_strain=0.25: twist **+36.6°** (Δ +45.4° vs uniform!), dev max 5.22 (worse),
  bend +2.8°. Same 11 skips.

**Diagnosis (confirmed, not a bug):** per-helix counts ARE preserved, but the within-slot freedom
lets the deviation field shift ALL skips COHERENTLY toward one end (e.g. mean bp 12→29). That
reshapes the cumulative-deletion staircase away from linear → and **net twist is the endpoint of
that profile**, so it swings drastically. CONCLUSION: count and placement are **NOT separable** —
position strongly determines net twist (same mechanism as the user's "6-at-the-ends" concern). The
cheap ONE-SHOT surrogate route (place once from a prior run's field, assume twist preserved) is
**wrong**: it (a) doesn't preserve net twist, (b) overfits one stochastic deviation field, (c) can
destabilise. The 5.0–5.3 substrate (placer, fields, build helpers, route flag, bend metric) is fine;
it's the LOOP STRATEGY that must change.

**Corrected route (proposed, pending user decision):** iterative PROFILE-matching — gate on the
per-position cumulative twist-deviation profile (not just net twist), make GENTLE bounded placement
nudges each round (tight within-slot displacement), re-simulate, converge (net twist stays on target
as the profile endpoint). More sims than the scalar secant but bounded ("few" iterations). Alt:
constrain regional to tiny twist-preserving nudges (limited benefit), or keep uniform + use the
fields only as a diagnostic.

## 5.4 iterative prototype #1 — DIVERGED; two root causes identified (2026-06-26)

First iterative profile-matcher prototype (proxy 2×3×40, fixed count = period-24 budget, gain
0.5, base 1.0, production 1M/round, NON-detrended error signal): twist 26→14→33→**−116°** over
4 rounds — diverged. Built: `measure_bundle_twist_profile` (per-slab cumulative twist; endpoint
== `measure_bundle_twist`), `redistribute_by_twist_profile` (inverse-CDF density ∝ local
over-twist + uniform base floor), `detrend_error_profile`, `measure_bundle_bend`. 17 pins green.

Two root causes (both fixable):
1. **Non-detrended signal (primary).** The controller acted on the slope of e(x) which INCLUDES
   the global net-twist component → it coherently shifted all deletions to chase the net
   over-twist (the COUNT's job), violently moving net twist with no count feedback to
   compensate (fixed count) → divergence. FIX = `detrend_error_profile`: redistribute only on
   the LOCAL shape residual (net-neutral, ~twist-preserving), already implemented + pinned but
   NOT yet GPU-tested. This makes redistribution the principled form of "tiny twist-preserving
   nudges."
2. **Per-round sampling noise.** A FIXED uniform design read twist −8.7° (A/B, 2M) vs +26.2°
   (proto, 1M) — ±35° run-to-run. At 1M production the per-position twist signal is
   noise-dominated; the controller chases noise. The scalar loop pools to min_confidence=400
   (8M+) for exactly this reason — the profile-matcher needs comparable per-round confidence,
   which is expensive (high-confidence × several iterations).

STATUS: iterative profile-matcher NOT working yet. Substrate + pins in place. Open decision:
(a) GPU-test the detrended + low-gain + high-confidence version (one more ~30-min proxy run,
uncertain — sampling noise may still block), (b) accept detrended-redistribution as a single
gentle net-neutral pass (cheaper, modest benefit), or (c) ship fields as diagnostic-only. The
violent placement↔net-twist coupling means count + placement may need to co-adapt (count secant
re-running as placement shifts twist) — a bigger coupled loop.

## 5.4 CONCLUSION — regional twist optimization is NOT viable for this system (2026-06-26)

After four proxy prototypes the verdict is definitive and NEGATIVE:
- one-shot deviation placement: net twist swung +45° at equal count.
- naive iterative (non-detrended): diverged to −116°.
- corrected iterative (detrended net-neutral + high-confidence 300-frame pooling + net-twist
  secant + modest gain): from a proper uniform round 0 (+4°), the FIRST redistribute step
  jumped to +27° and then WANDERED worse (shape 0.2→6.6°). Round 0 was the best every time.
- staggering bug found + fixed (regional placers didn't offset deletions across helices like
  `sq_lattice`'s `offset_i`; pinned `test_redistribute_staggers_across_helices`). But the fix
  exposed the ROOT issue: two "uniform" placements (sq_lattice stagger vs phase stagger) differ
  by **+30° net twist from the register alone** (sq_lattice uniform +4° vs regional-uniform +35.8°).

ROOT CAUSE (robust across all runs): **net twist is exquisitely sensitive to the exact deletion
register** — ~±30° swing from the placement scheme/positions alone (physical register sensitivity
AND the bp-midpoint twist measure's sensitivity to WHICH nucleotides are skipped). The local-shape
signal regional placement would correct is only ~2–20° — i.e. SMALLER than the placement-induced
twist disturbance. The control authority's side-effect (net-twist swing) exceeds and is less
predictable than the target (local profile), so any regional optimizer chases its own placement
artifacts. Confirmed cheaply on the proxy; the 3×6×400 would reproduce it (NOT run — would waste
~3–4 h).

**Practical upshot:** the uniform staggered pattern (current production `sq_lattice_periodic_skips`
+ the scalar-twist secant) is near-optimal AND robust for twist-only; an automated regional twist
optimizer is not. The deviation/strain/twist-profile fields are best used as a DIAGNOSTIC (show
where a design deviates / is strained) for MANUAL regional exceptions, not as an optimizer signal.

KEPT (built + pinned, reusable substrate, 18 fast pins): `backbone_strain_field`,
`geometry_deviation_map` aggregation, `measure_bundle_twist_profile`, `measure_bundle_bend`,
`regional_skip_placer` (placer + redistribute + detrend + stagger), `build_regional/explicit_skip_
from_design`, the route `regional` flag. These power a diagnostic even though the optimizer is shelved.

## RE-SCOPE (2026-06-26): wholesale redistribution was the WRONG SCALE — it's a 1–5 edit fine-tuner

User clarified the intended scope (never pinned down originally): regional refinement is **fine-tuning
AFTER the uniform optimizer converges** — **1–5 added/removed skips across an ENTIRE full-scale
origami**, not re-placing all ~300. This INVALIDATES the "not viable" conclusion above, which was for
WHOLESALE redistribution (re-placing the full budget → ±30–45° register swings). At 1–5 edits the
coupling vanishes: one skip ≈ 0.2° of a ~50° full-scale correction, so 1–5 edits perturb net twist
**<1°** — net-twist-safe BY CONSTRUCTION. The earlier divergence was an artifact of moving everything.

CORRECTED design = greedy discrete fine-tuner (Benson-style, but tiny):
1. Converge uniform + scalar-twist secant (existing, unchanged).
2. High-confidence sim → per-bp deviation field + detrended twist-shape profile.
3. `skip_finetune.identify_finetune_edits` → top ≤max_edits LOCAL hotspots (deviation > mean+σ·std,
   so a flat/noise field yields 0 edits = does no harm); op = ADD a deletion in a locally over-wound
   hotspot, REMOVE the nearest in an under-wound one (sign from `_signed_overtwist_slope`).
4. `greedy_finetune_skips` (skip_twist_tuning): apply each edit, re-sim high-confidence, ACCEPT only
   if dev_max drops ≥ dev_improve_nm AND |net twist| ≤ tol; else revert. ≤max_edits sims.

BUILT + green (this checkpoint, CPU/stubbed-engine): `backend/core/skip_finetune.py`
(`identify_finetune_edits`, `apply_finetune_edit`, `current_skips_by_helix`, `_signed_overtwist_slope`),
`skip_twist_tuning.greedy_finetune_skips` + `_finetune_measure`. Pins: `tests/test_skip_finetune.py`
(10 — hotspot ranking, add/remove sign, cap+spacing, no-harm, greedy accept/revert/error). The
wholesale redistribution code (`redistribute_by_twist_profile`, `place_regional_skips`) is SHELVED
(wrong scale; kept dormant/diagnostic). NOTE: the mock engine can't pool a production rmsf mean, so
`_finetune_measure` is engine-tested via stubs + the real-GPU run below.

STEP SIZING — gentle was WRONG for square; corrected to ADAPTIVE (2026-06-27). First attempt made
`PeriodAdjuster` gentle (explore 0.1 fixed, directed) on the premise "analytical is close." LIVE
MONITORING of a SQUARE 3x6x400 run DISPROVED it: at the analytical density (period ~50) the
DIFFERENTIAL twist (sim − analytic; analytic read ~0° here → good keying) was **+69–80°**, far out of
the 5° tol. Square lattice is underwound enough to need ~period **24** (≈2× the skips, the validated
optimum) — so analytical-48 is NOT close for square; it needs a BIG global correction (the "doubling"
the user disliked was actually correct for square). Gentle 0.1 stalled (dithered near period 50,
never drove to 24); low-confidence early-reject (100-frame) twist noise also made a tiny-step secant
slope unreliable. FIX = ADAPTIVE step (`_explore_step`): `frac = clamp(|residual|·explore_gain,
explore_min, explore_max)` (`explore_max=0.5, explore_gain=0.015, explore_min=0.03`) — large residual
(square +70°) → near-halving (48→~24), near-converged → gentle nudge; directed by sign
(d(twist)/d(period)>0 → over-twisted residual>0 → smaller period). A big first step also lifts the
secant slope above per-round twist noise. So: BIG when far (square), gentle when close, then the
local fine-tune. Pin: `test_period_adjuster_step_scales_with_residual_and_is_directed`.
MONITORING NOTE: to read the steering signal use the DIFFERENTIAL (`_dispatch_measure("bundle_twist",
…, reference)` or sim−analytic), NOT raw `measure_bundle_twist` (the offset; here it was ~0 so they
matched, but don't rely on that).
**Fine-tune is now ALWAYS ON** — no UI toggle; the ✦ Autorefine button always runs gentle global +
fine-tune (`AutorefineStartRequest.finetune=True` default; the checkbox was removed 2026-06-27). The
old from-scratch behavior is gone; a no-skip design still starts from the analytical seed (48).
AUTO-PREPARE (2026-06-27): clicking Autorefine on a design that lacks the default skips / sequences
threw "undefined bases" (the baseline measure ran on the raw snapshot). `autorefine_sq_design` now
calls `prepare_design_for_autorefine(base)` first: if the design has no skip marks OR any undefined
'N' base, it applies the analytical seed period + `full_sequence` (via `build_sq_skip_from_design`);
an already-skipped+sequenced design is untouched (hand-tuning preserved). Emits a `phase="prepared"`
progress event. Pin: `test_prepare_design_for_autorefine_applies_skips_and_sequences`.
Pin: `test_period_adjuster_first_step_is_small_and_directed`. NOTE: a live run already in its daemon
thread keeps the OLD adjuster instance until it ends — stop + restart to get the gentle behavior.

WIRED INTO THE APP (2026-06-26): the fine-tuner runs as a post-convergence pass of the existing
autorefine. Backend: `AutorefineStartRequest.finetune`/`finetune_max_edits` → `autorefine_sq_design`
runs `greedy_finetune_skips` after the uniform secant converges (emits `phase="finetune"` progress
events with `ft_phase`=baseline/candidates/edit; threads `on_job` so fine-tune sims get tracked/
selected/stoppable), sets `placement="finetuned"` + `converged_skips` (the explicit final pattern).
Apply route generalised: lays `converged_skips` verbatim whenever present (regional OR finetuned),
else the uniform period. Frontend (`oxdna_jobs_panel.js` + index.html): a "Fine-tune (≤5 local skip
edits after converge)" checkbox (`oxdna-jobs-finetune-toggle`) → `startAutorefine({finetune})`; poll
loop shows fine-tune edit progress; result panel shows edits-kept + worst-dev before→after
(`_finetuneBlock`); completion applies the explicit pattern (period=None) for finetuned/regional.
Reuses the existing status spinner, [AR] job tagging, deviation-map toggle (visual monitoring), and
feature-log apply/seek/revert. Verified: backend `just test` 3250 pass; autorefine e2e 4/4 (mocked).
LIVE fine-tune run NOT yet exercised end-to-end in-app (user will run it; it needs a real GPU pass).

NEXT: GPU-validate `greedy_finetune_skips` on a converged 3×6×400 (does it find real local hotspots
above noise and reduce dev_max with ≤5 edits while net twist stays in tol? on a homogeneous design it
should make 0 edits). Then wire into the autorefine route (a post-convergence "fine-tune" pass) + the
apply path (converged_skips already supports explicit patterns) + frontend.

## Next (was 5.4 — superseded by the finding above)

- **5.4 GPU validation (the crux):** on the 2×3×40 proxy then 3×6×400 — at EQUAL net twist,
  regional reduces the (deviation+strain) cost vs uniform (non-vacuity), does NOT worsen net bend,
  converges in a few sims. Calibrate `w_dev`/`w_strain`. Use oxDNA2. **Add the bend-guard metric
  here** (deferred from 5.2 — currently the only shape guard is the existing `geometry_rmsd` in the
  verdict steering; a dedicated axis-curvature metric is a 5.4 task).
- **5.5 frontend:** "regional" toggle + weights; reuse the deviation-map display to show where
  skips landed. **KNOWN v1 gap to fix here:** the panel's live per-iteration apply passes an
  explicit `period` → previews UNIFORM during a regional run; the EXACT regional pattern only lands
  on the completion apply (period=None). Also the completion call currently passes
  `converged_period` (not None) and is deduped by `_autorefineLastAppliedPeriod` — for regional the
  frontend must call apply with period=None (and bypass the dedup) so `converged_skips` lands.
