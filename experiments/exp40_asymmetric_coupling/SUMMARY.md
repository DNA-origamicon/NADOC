# exp40 (G3) — asymmetric cross-sections: coupling stress test

Hypothesis: an asymmetric section (off-center neutral axis) makes uniform skip density induce BOTH
twist and bend, so a 1-D (twist-only) objective leaves a residual bend that only the coupled 2-D
Jacobian solve can null.

## Findings (nuanced / partly negative)
1. **Routing is the real barrier.** auto_scaffold FAILED to route the strong-asymmetry cases:
   `L_4x4` → 2 disjoint scaffolds, `triangle` (staircase) → 10 scaffolds (total failure). The audit
   flagged + skipped them (garbage-in guard worked). Only `notch_4x4` (solid 4×4 minus a 2×2 corner)
   routed to a single scaffold. → handoff: `ASYMMETRIC_SCAFFOLD_HANDOFF.md`.
2. **On the routable notch, register→bend coupling is WEAK.** Straight strut (intended twist 0,
   bend ~0.6°); bare FEM twist 37.7°, bend only 0.92°. The current 1-D twist-null already lands
   twist 0.76° AND bend 0.51° (bend err 0.09°) — no residual bend to fix. The 2-D coupled solve did
   slightly WORSE (twist 1.37°, bend 1.39°): with the bend signal near the estimator noise floor
   (G2), the Jacobian's bend row is noise and the ridge solve chases it.

## Conclusion
The coupled (twist, bend) objective is validated + NECESSARY for designs with a PROGRAMMED bend/twist
target — proven in G1 (honeycomb 60° bend: coupled solve 25.7°→49.7° bend at twist err <0.5°). For a
straight strut, even an asymmetric one, the register over-twist couples only weakly to bend, so
twist-only suffices; forcing the 2-D solve on a sub-noise bend signal hurts. **Practical rule for the
generalized autorefine: use the coupled solve when the design has an intended non-zero bend (target
bend above the ~0.6° noise floor); else twist-only.** Strong-asymmetry validation is blocked until the
auto-scaffold routing failure (handoff) is fixed OR user-routed asymmetric fixtures are supplied.
