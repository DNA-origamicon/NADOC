# exp34 — validate the corrected autorefine: count-secant + incremental-gap placement, noise-bounded (3×6×400 SQ)

**Date:** 2026-06-28. Follows exp31 (`conclusion.md`) and exp32 (`conclusion.md` — DIVERGED, see
LESSONS A7). Tests the algorithm those two point to, and characterizes the one quantity both
prior experiments acted without: the per-run noise floor.

## What exp31/exp32 settled (so we don't re-test it)
- The square bundle's residual twist is large (~+50° net at the analytical period-48 seed) and the
  count must roughly DOUBLE (period 48→~24) to null it.
- **Placement, not a smarter controller, is the lever.** At a MATCHED 222 skips (delta +4/helix
  over the period-48 baseline), exp31 measured:
  - **incremental-gap: net twist −3.2°, max|cumulative-twist profile| 5.2°** — flat AND net-null.
  - uniform-restagger: net twist 46°, max|profile| 52° — not converged at the same count.
  - deviation-guided: 59°/68° — worst (unsigned signal; LESSONS A6).
- A per-segment MIMO controller that re-places the budget off the twist profile DIVERGES — it
  divides a one-deletion response by sub-noise sampling scatter, and treats coupled bins as
  independent (exp32; LESSONS A7). So the budget must be set by ONE global count secant and the
  placement must be incremental-gap; do NOT optimize per-segment.

**Conclusion carried in:** the recommended autorefine = the existing scalar net-twist count secant,
but with production placement switched from uniform-restagger (`sq_lattice_periodic_skips`) to
**incremental largest-gap**. The open questions below decide whether that is sufficient and whether
any discrete fine-tune is warranted on top.

## The single thing neither exp31 nor exp32 measured: the NOISE FLOOR
exp31's "5.2°" is ONE 8M-pooled sim. exp32 diverged precisely because it acted on per-segment
signals SMALLER than the per-run scatter. Before we certify "incremental-gap converges flat" or
design any fine-tuner, we must know σ(max|profile|) and σ(net twist) for an IDENTICAL design across
independent seeds. This gate alone would have killed exp32 at round 0.

## Questions (ordered cheap→expensive, each a kill-gate for the next)

### Gate 0 — NOISE FLOOR (keystone, ~4 sims)
Re-simulate the IDENTICAL incremental-gap delta-+4 design (222 skips) K=4 times with independent
seeds; full relax + 8M-pooled production each. Report mean ± σ of `max|profile|`, `net twist`,
`curvature`. Define the minimum detectable improvement **δ_min = 2σ(max|profile|)**.
- **Predicted:** σ(max|profile|) ≈ 3–8° (the scalar loop pools to ~400 frames precisely to get
  net twist to a few °; the profile max is noisier than net twist but same order).
- **KILL:** if σ(max|profile|) ≳ 15°, "5.2°" is not distinguishable from "back-loaded" and NO
  ≤5-edit fine-tune can ever be validated on this system → final recommendation becomes
  "count-secant + incremental-gap, no fine-tuner," and Gates 2 is skipped.

### Gate 1 — does the LIVE count secant land flat with incremental placement? (~3 sims)
Confirm the result is a stable convergence target, not a single lucky delta. Re-measure incremental
delta +3, +4, +5 (204 / 222 / 240 skips). Predicted from exp31: +3 ≈ 25°/+21°, +4 ≈ 5°/−3°,
+5 overshoots net twist negative. So the net-twist secant brackets zero at +4±1 and `max|profile|`
bottoms there. **PASS:** the incremental converged point sits at `max|profile| ≤ δ_min` (genuinely
flat within noise) at the same delta the net-twist secant selects. **FAIL:** the net-twist-null
delta and the flat-profile delta disagree by >1 step — then count alone doesn't co-optimize both and
a fine-tune (Gate 2) is genuinely needed.

### Gate 2 — signed-twist ≤5-edit fine-tuner (CONDITIONAL: only if Gate 1 leaves residual > δ_min)
From the incremental-converged design, greedily propose ≤5 SINGLE-skip edits, each at the worst
SIGNED-local-twist location (add where over-wound, remove where under-wound — the A6-correct signal,
NOT the shipped fine-tuner's unsigned `dev_max`). Accept an edit only if a fresh 8M-pooled re-sim
reduces `max|profile|` by **> δ_min** AND keeps |net twist| ≤ 5°.
- **No-harm control:** if Gate 1 already converged flat, expect **0 accepted edits** (every edit's
  improvement is within noise) — the fine-tuner must do nothing when there is nothing to fix.
- **Distributed-gradient watch:** if many edits each help a little but the residual is a sustained
  back-half ramp (not 1–5 isolated hotspots), the ≤5-edit budget is under-powered — report it and
  recommend scaling the edit budget with the integrated profile slope (the open issue flagged in
  `project_regional_autorefine`), rather than silently stopping at 5.

### Gate 3 — ARTIFACT guard (independent, ~2 sims; can run anytime)
Is the residual profile SHAPE a real local target or a boundary artifact of the seamless route's
buried nick? Rebuild the converged design with the nick relocated (seamed route, or the seamless
route closed at the opposite helix) and re-measure the profile. **If the back-loading flips/moves
with the nick → it is route-anchored (an artifact); do NOT fine-tune it.** If it is invariant → it
is structural and a legitimate (if small) fine-tune target.

## Predictions summary
1. Gate 0: σ(max|profile|) a few °; incremental+4 mean stays single-digit (flat is real).
2. Gate 1: net-twist secant and flat-profile minimum coincide at delta +4 → count-secant +
   incremental placement is sufficient; **no fine-tuner needed.**
3. Gate 2 (if reached): 0–1 accepted edits; never a sustained-gradient case at the converged count.
4. Gate 3: the residual shape is at least partly nick-anchored (the back-loading is an end effect).

If 1–2 hold, the deliverable is a one-line production change (placement → incremental-gap) plus the
recommendation to RETIRE the regional/profile-MIMO optimizer entirely. Any prediction the data
contradicts → `conclusion.md` + `LESSONS.md`.

## Reuses (do-not-rebuild)
- `exp31_skip_twist_curvature_sweep/run.py::measure` — relax + 8M-pooled production → net twist,
  `twist_profile_max`, curvature, health, archive. (Same Cfg / CUDA / archive plumbing.)
- `backend.core.skip_sweep_strategies.{baseline_skips, place_incremental}` — the placement.
- `backend.core.profile_guided_refine.{bin_layout, local_twist_per_bin}` — axial→bp mapping +
  signed local twist for the Gate-2 single-edit proposer (NOT the divergent `secant_targets`).
- Launch mirrors exp31/32: `--backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7`.
</content>
