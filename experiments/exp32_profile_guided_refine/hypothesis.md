# exp32 — profile-guided adaptive skip refinement (3×6×400 SQ)

**Date:** 2026-06-28. Follows exp31 (see its `conclusion.md`).

## Question
exp31 showed the square bundle's residual twist is back-loaded and structural, uniform density
can't flatten it, deviation-field placement is worst (unsigned signal), and incremental-gap
placement is the one that drives a region to zero. Can an adaptive loop that reads the twist
PROFILE (signed local over-twist per axial segment) and fills the over-wound segments with
incremental-gap drive the WHOLE profile to flat-zero — efficiently (fewer total skips than blindly
raising uniform/incremental density)?

## Method
Single iterative refinement (not a grid), starting from the analytical baseline (period 48):

1. Build current design → relax + 8M production → twist profile (24-bp cumulative), curvature,
   end-of-run health check (reused from exp31).
2. Split the axis into `--n-bins` segments (default 6 — coarse on purpose: one deletion/helix
   removes ~34°, so a segment must accrue ≳34° for integer control to engage; finer bins can't be
   corrected — the discreteness floor).
3. Per segment, the SIGNED local twist (profile slope) sets the target deletions-per-helix via an
   UNDERDAMPED secant (gain 1.3 > 1, deliberate overshoot to bracket zero fast); ADD to over-wound
   segments / REMOVE from under-wound, placed by incremental-gap WITHIN the segment's per-helix bp
   range (axial→bp via helix geometry, same sign convention as the twist measurement).
4. Re-simulate; repeat until max|cumulative twist| < `--tol` (default 5°) or `--max-rounds`
   (default 8).

## Predictions
1. **The profile flattens monotonically** over rounds: each round adds deletions to the over-wound
   back half, lowering its local twist, so max|cumulative twist| falls round over round.
2. **It reaches a flatter profile at FEWER total skips than uniform/incremental** at matched count
   (exp31: uniform 53°, incremental 64° at ~186 skips; incremental needed 222 skips for 5°). If
   profile-guided beats those at the same skip count, the adaptive targeting is the win.
3. **It will likely NOT reach tol=5°** — that's below the per-segment discreteness floor (each
   correction is a whole deletion/helix ≈ 34°). Expect convergence to a floor (~15–30° max|profile|)
   then stall; the floor itself is a result. (tol/max-rounds are user-tunable to probe it.)
4. **Curvature stays bounded** (adding deletions symmetrically across the cross-section per segment
   shouldn't induce net bend) and **all rounds pass the health gate**.

## Validated before launch
- Round-1 controller plan on the REAL exp31 baseline profile adds **34 skips, all to the back half**
  (mean axial frac 0.76 = the over-wound region) — orientation + targeting correct.
- Loop mechanics dry-run end-to-end (build → measure+health → controller → archive → plot → stop).
- Controller pins green (`tests/test_profile_guided_refine.py`, 7).

## Disproven-expectation policy
Any prediction the data contradicts → `conclusion.md` + `LESSONS.md`.
