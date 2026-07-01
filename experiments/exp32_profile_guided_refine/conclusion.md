# exp32 — conclusion: profile-guided MIMO secant DIVERGES (2026-06-28)

Ran to `--max-rounds 8` (9 sims, ~9 h, all healthy). **Negative result: the loop diverged.**
None of predictions 1–3 held; only "curvature bounded" (4) held.

## What we set out to test
Close exp31's loop: read the per-position twist PROFILE, and each round add deletions to the
over-wound axial segments / remove from under-wound ones (incremental-gap within the segment),
driven by a per-segment UNDERDAMPED secant (gain 1.3), to drive the whole profile to flat-zero —
ideally at fewer total skips than blindly raising uniform density. Start = analytical period-48.

## Result — runaway oscillation, never converged
| round | total skips | max\|profile\| | net twist | worst bin (del/helix) |
|---|---|---|---|---|
| 0 (seed) | 150 | 52.9° | +47° | 2 |
| 1 | 162 | 75.0° | +67° | 2 |
| 2 | 414 | 95.5° | +89° | **17** |
| 3 | 432 | 53.7° | +50° | 20 |
| 4 | 738 | 56.7° | +52° | 37 |
| 5 | 90  | 71.9° | +70° | 2 |
| 6 | 90  | 108.4°| +99° | 1 |
| 7 | 1367| 12.2° | −0.8° | **67** |
| 8 | 1116| 52.6° | +44° | 53 |

Total skips swing 90 ↔ 1367; bin counts demand up to 67–96 deletions/helix in a single axial sixth.
The lone "good" round (7, 12°) is a controller crossing zero mid-overshoot, not convergence —
round 8 immediately swings back to 52°. The flatness metric ends WORSE than the period-48 seed.

## Root cause — divide-by-noise in an uncoupled MIMO secant
Two compounding structural faults, both already predicted by prior work:

1. **The per-bin secant divides by a noise-dominated local-slope estimate.**
   `secant_targets` (profile_guided_refine.py) computes `slope = Δ(local_twist)/Δ(count)` from a
   SINGLE round pair, then `step = -gain·local_twist/slope`. A one-deletion twist response is
   ~1–3°, but the per-round sampling noise on a local bin twist is ≥ the ±35° established for the
   net twist in `project_regional_autorefine` §5.4. So the denominator is essentially noise (often
   near-zero or wrong-sign) → the step explodes. Worked trace, round 1→2 bin 5: count 1→2, local
   twist 14.8°→13.6° ⇒ slope −1.2°/del ⇒ step −1.3·13.6/−1.2 = **+14.6 ⇒ target 17 del/helix**.
   Round 7 demanded ~96 (capped to 67 by available bp). The scalar loop avoids this by steering on
   ONE well-conditioned pooled scalar (net twist) and NEVER dividing by a single-edit response.

2. **6 bins treated as independent SISO loops on a globally-coupled plant.**
   Cumulative twist at x is the running integral of everything upstream, so editing bin 4 shifts the
   bins-5/6 curve; the next round reads that as fresh error and chases it. A MIMO plant with dominant
   off-diagonal coupling cannot be stabilized by decoupled per-bin secants at any gain — and
   `gain 1.3` (deliberate overshoot) makes the oscillation grow rather than settle.

This is the SAME wholesale-redistribution regime `project_regional_autorefine` §5.4 already declared
non-viable ("net twist is exquisitely sensitive to the exact deletion register; the local-shape
signal is SMALLER than the placement-induced twist disturbance"). exp32 re-instantiated it as a
signed-profile MIMO controller and reproduced the divergence — expensively, on the full 3×6×400.

## Disproven predictions (→ LESSONS A7)
- P1 "profile flattens monotonically" — FALSE (oscillated 53→75→95→54→57→72→108→12→53).
- P2 "flatter at fewer skips than uniform/incremental" — FALSE (worse flatness, far more skips).
- P3 "stalls at the discreteness floor (~15–30°)" — FALSE; it did not stall, it diverged. The
  hypothesis correctly noted tol 5° is below the one-deletion floor (~34°), then ran an
  underdamped controller anyway — which, with the noisy denominator, launched instead of stalling.

## Decision — retire wholesale/MIMO profile control; the viable algorithm is the ≤5-edit fine-tuner
Confirmed (now twice: regional §5.4 + exp32) that any optimizer re-placing a large fraction of the
skip budget is unstable for this plant. The robust path is unchanged from the §5.4 RE-SCOPE:
**uniform count secant to null net twist (validated, period 48→~24), then a SMALL (≤5) discrete
fine-tune** where each edit perturbs net twist <1° by construction and is accepted only if a
high-confidence re-sim improves flatness. exp34 tests exactly that, with two preconditions exp32
skipped (noise-floor characterization + profile-artifact check). See `exp34_finetune_validation/`.

## Carry-forward gotcha for the fine-tuner
The EXISTING `greedy_finetune_skips`/`identify_finetune_edits` still rank WHERE by unsigned
`deviation_by_bp` and ACCEPT by `dev_max` (positional deviation) — the exact objective LESSONS A6
says is wrong for twist. The recommended algorithm needs a SIGNED-twist variant (rank by
|detrended local-twist slope|, accept by Δ max|cumulative-twist profile|). Built for exp34.
</content>
</invoke>
