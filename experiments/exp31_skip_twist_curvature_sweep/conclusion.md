# exp31 — conclusion (interrupted at 22/27 sims, 2026-06-28)

Interrupted in favour of exp32 once the strategy verdict was unambiguous. All 22 completed sims
passed the structural-integrity gate (bp-retention 0.92–0.99, FENE-safe, backbone stretch ~1.5 nm),
so every conclusion below is on intact structures. See `hypothesis.md` for predictions, `FINDINGS.md`
for the detailed diagnostics.

## What we set out to test
Map total-skips → global twist around the analytical baseline (period 48) for a 3×6×400 square
bundle, with a new integrated-curvature guard and per-position twist profiles, across three
placement strategies (uniform restagger / incremental largest-gap / deviation-guided), to learn
why autorefine can't optimize past the analytical spacing and whether placement matters.

## Key results
1. **The analytical baseline is far from corrected.** Differential twist at period 48 is ~58°
   (not ~0), and the twist-zero density is well beyond the ±4 window (square needs ~2× the
   analytical skip count). Confirms the prior `project_skip_twist_selfconsistency` finding.
2. **The residual twist is back-loaded, and that's structural — not a placement, measurement, or
   bend artifact** (ruled out by axial skip-density uniformity, flat-zero analytic profile, and
   no bend correlation; FINDINGS §F2). The front half relaxes to design; the back half holds the
   over-twist — asymmetric torsional boundary conditions. Proof that **uniform skip density is the
   wrong tool**; the correction must be local.
3. **Placement strategy is decisive (objective = max |cumulative twist| along the profile):**
   - **Incremental largest-gap — winner.** The ONLY strategy to reach flat-zero: 222 skips →
     endpoint −3°, max|profile| **5°** (uniform 46/53°, deviation 59/68° there). Most linear
     skips→twist trend. Keeping baseline marks + filling the widest gaps perturbs the register
     least, so the profile flattens instead of swinging.
   - **Uniform restagger — robust but never flat** (46/53° even at 222 skips; the back-loaded
     shape persists).
   - **Deviation-guided — WORST despite being the "adaptive" arm** (68–95° flatness). It steers on
     the UNSIGNED positional-deviation field, which conflates bend / end-fraying / twist and so
     adds skips in the wrong places — it does not track signed local over-twist.

## Disproven prediction (→ LESSONS)
We expected the deviation-guided (adaptive) arm to at least match uniform. It was consistently the
WORST. The lesson: for twist correction the steering signal must be the SIGNED local twist (the
twist-profile slope), not an unsigned positional-deviation magnitude. Logged in `LESSONS.md` and
[[project_regional_autorefine]].

## Decision
The data points straight at the next method: drive placement from the twist PROFILE (signed local
over-twist per axial segment) and fill the over-wound segments with incremental-gap (the proven
placement). That is **exp32** (`experiments/exp32_profile_guided_refine/`).

## Objective metric (carry forward)
Judge "straightness" by **max |cumulative twist| along the profile** (flatness), not the endpoint —
the endpoint hides front/back cancellation. Curvature is a co-equal constraint (flat twist AND a
straight axis). Realistic target is the discrete-skip floor, not literal zero.
