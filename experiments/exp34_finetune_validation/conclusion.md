# exp34 — conclusion: the binding constraint is SAMPLING, not the algorithm (2026-06-29)

Ran to COMPLETE (Gate 0 ×4 + Gate 1 ×3 + Gate 2 ×5 edits). The recommended autorefine
(count-secant + incremental-gap placement) is sound, but every twist evaluation carries a ±9°
ensemble noise that dwarfs the signals a fine-tuner would act on. The per-frame τ-diagnostic
(added this session) is what made the cause legible.

## Gate 0 — the noise floor, explained
Per-frame twist diagnostic on the identical 222-skip (incremental+4) design (rep3):
**τ_int ≈ 101 frames, N_eff = 3.9 / 400.** An 8M production holds ~4 effectively-independent
samples of the global twist; per-frame std 20°, correlation-corrected SEM ±10°.

The **same 222-skip design measured 5× (g0 rep0–3 + g1_d+4): net twist = 19.5, 7.4, 32.3, 18.0,
10.3 → 17.5 ± 9.4°.** The between-seed σ (±9°) matches rep3's within-run corrected SEM (±10°) —
the autocorrelation analysis correctly predicts the ensemble scatter. The noise is real and
physical (a slow collective twist mode, τ ≈ ¼ of the whole run), NOT a measurement artifact:
twist-on-the-time-average-structure (18.03°) ≈ per-frame mean (18.41°), so the position-averaging
"shrinkage" is negligible (~0.4°). → Measuring per-frame instead of on the mean does not reduce
the noise; it correctly *diagnoses* it.

## The treacherous subtlety — a single run's SEM is not trustworthy
The IDENTICAL 222-skip design gave τ=101 / N_eff=4 / SEM 10° in one run (g0_rep3) but
τ=3.4 / N_eff=116 / SEM 1° in another (g1_d+4). A low τ does NOT certify good sampling — it can
mean the slow twist mode sat FROZEN at a random offset for the whole 8M, so only the fast
fluctuations decorrelate and the SEM reads falsely tight. g1_d+4's ±1° is ~9× too optimistic vs
the ±9° ensemble truth. **Only the between-seed σ is honest.** (This is the exact trap exp32 fell
into — it trusted single-run signals smaller than this.)

## Gate 1 — the algorithm works, at delta +5 (240 skips), not +4
Means (each ±9°): d+3 → +47°, d+4 → ~+15°, **d+5 (240 skips) → −3°, profmax 8°.** Net-twist zero
and the flat-profile minimum coincide at +5. exp31's "−3°/flat at +4" was a favourable draw; the
real +4 is ~+15°. So **count-secant + incremental-gap placement reaches net≈0 AND flat-within-
noise at 240 skips** — no MIMO controller, no fine-tuner. Caveat: 8° profmax is BELOW the ±18°
(2σ) noise floor, i.e. "flat as far as we can measure," not provably zero.

## Gate 2 — fine-tuner futile, quantified
**0 of 5 single-skip edits accepted** (finetune_summary: kept=[], start=final profmax 24.18,
delta_min 17.8). A single skip moves profmax ~1°; the accept bar (2σ=17.8°) is ~18× larger. The
per-edit profmax readings (23 → 51° for one-skip differences) are pure noise. The fine-tuner
correctly does no harm — but can do no good: the per-edit signal is ~18× below the measurement
noise. Not a tuning failure; fundamental. (Experiment bug, immaterial to the verdict: Gate 2
started from the +4 design (residual 24°), not the Gate-1 +5 winner — but no single edit can move
18° from any start.)

## Verdict
- **Algorithm:** count-secant + incremental-gap placement is the right method; lands net≈0 and
  flat-within-noise at delta +5. RETIRE the per-segment/profile MIMO optimizer (exp32) and the
  ≤5-edit fine-tuner for this system — confirmed futile (signal ≪ noise).
- **Binding constraint = SAMPLING.** N_eff ≈ 4 per 8M ⇒ ±9° per evaluation. To certify flatness
  to ±3° (or to fine-tune at ~1°/edit) needs ~(20/3)² ≈ 44 independent samples ≈ **~10× the
  sampling per point** (≈10 seeds/point, OR a single run ~10× longer IF longer runs raise N_eff).
  Until the measurement error is below the resolved quantity, any fine-tuner/regional optimizer
  steers on noise — exactly exp32's divergence mechanism.

## SUPERSEDED by the 80M run — it is an EQUILIBRATION transient, not a slow mode (2026-06-29)
The "binding constraint = sampling, need ~10× / ~10 seeds" verdict above is WRONG; the 80M run
refuted it. The per-frame trace starts at +90° (built/relaxed seed badly over-wound) and RELAXES
monotonically to ~−21° over the first ~80 frames (~8M steps), then rattles around −21° with NO
autocorrelation beyond one 100k-step frame. So the global twist has a long **~8M-step
EQUILIBRATION transient**, and AFTER it the twist is FAST (τ_int=1 frame). Dropping the first
~8M (burn-in) collapses τ 52→1, N_eff 15→720, **SEM 3.8°→0.4°, equilibrated mean −21.2 ± 0.4°.**
The "slow mode / N_eff≈4" was a monotonic DRIFT the autocorrelation estimator misread as a long τ.

**Consequences (correcting the verdict):**
- The fix is CHEAP: a ~10M burn-in (longer equilibration / discard first ~10M of production),
  NOT 10× compute or ensembles. After equilibration a short production gives SEM <1°.
- ALL prior twist numbers (exp31 "flat at +4", Gate 0/1) were measured ENTIRELY inside the ~8M
  transient → biased toward the positive start AND scattered ±9°. The standard 8M autorefine
  production never equilibrates the twist. **This is the real bug to fix in the autorefine.**
- Equilibrated d+5 (240 skips) = −21° (over-corrected), not the −3° its under-equilibrated 8M
  read claimed. Net-zero is below 240 skips; the ±18° integer-per-helix discreteness floor means
  uniform steps straddle zero by ~±18° (sub-step placement needed to land tighter).
- **The ≤5-edit fine-tuner is back on the table:** at ±0.4° resolution a ~1°/edit effect is
  measurable; its "futility" was an equilibration artifact.

## exp34c RESULT — burn-in hypothesis VALIDATED; net-zero is at d+4 (222 skips) (2026-06-29)
Warm-started (append_production to the unarchived Gate jobs) + d+5 reuse, `detect_equilibration`
burn-in discard. EQUILIBRATED twist vs count (`results/equilibrated_twist_vs_count.png`):

| design | skips | EQUILIBRATED twist | burn-in | post-burn-in |
|---|---|---|---|---|
| d+3 | 204 | +35.7 ± 0.6° | 2.3M | τ=3.5, N_eff 314/1200 |
| **d+4** | **222** | **−0.6 ± 0.6°** | 4.3M | τ=3.1, N_eff 314/1200 |
| d+5 | 240 | −19.8 ± 0.4° | 3.2M | τ=1, N_eff 768 |

**(a) Burn-in generalises:** every d+x shows a ~2–4M-step transient then FAST decorrelation (τ≈3,
SEM ±0.4–0.6°). Confirmed across designs — it's the bundle, not one structure.
**(b) Net-twist zero is at d+4 = 222 skips (−0.6 ± 0.6°), NOT d+5.** This OVERTURNS the
under-equilibrated count claim: the 8M Gate runs read d+4 = +17° → "needs d+5"; equilibrated, d+4
is statistically ZERO. The analytical-ish incremental+4 placement was right all along — the count
was never the problem, only the equilibration. exp31's lucky −3°@+4 was nearer truth than +17°.
**(c) Fine-tuner re-opened:** at ±0.5° resolution a ~1°/edit effect is resolvable; the "futility"
was an equilibration artifact. And d+4 already sits at zero, so no sub-step placement is needed for
net twist here.

**ROOT CAUSE PINNED:** the relax `equil_steps` default is **100,000** (`STANDARD_RELAX_PARAMS`)
— ~50× shorter than the ~5M twist-equilibration time — so production starts badly unequilibrated and
measures a biased, drifting twist. This is the real autorefine bug; the fix is to equilibrate
~10M before the measured production (or discard the first ~5M of production via
`detect_equilibration`). Implemented in `autorefine_sq_design`; validated by the exp35 test.

## (superseded — see exp34c above) Next (was) — exp34c burn-in validation, WARM-STARTED
`run_burnin.py`: validate the ~8M transient + equilibrated twist for d+3 / d+4 / d+5, reusing
the already-simulated runs as JUMP POINTS (`append_production` to the unarchived g1_d+3 / g0_rep3
d+4 jobs continues their trajectories past equilibration; d+5 reuses the 80M frames). Auto
burn-in via `detect_equilibration`. Goals: (a) confirm the transient generalises across d+x,
(b) equilibrated twist-vs-count curve at ±0.4°, (c) inform sub-step placement / re-assess the
fine-tuner. THEN: extend the autorefine production's equilibration (the actual fix).

## New tooling kept (reusable)
- `oxdna_health.twist_series_stats` (τ_int / N_eff / corrected SEM) + `production_twist_series`
  (per-frame twist vs twist-on-mean) + headless `read_twist_series`. Pins in
  `test_oxdna_relaxation.py`. These are the honest sampling-error estimator for ANY oxDNA
  observable, not just this experiment — wire into the autorefine accept gate so it never again
  certifies a knob on a single under-sampled run.
</content>
