# exp38 — G1: coupled (twist, bend) authority Jacobian for honeycomb bend designs

First phase of the autorefine generalization (see `../exp37_cando_skip_twist_map/GENERALIZATION.md`).
Goal: drive the FEM-predicted (twist, bend) to the design's INTENDED (twist, bend) jointly, via a
measured per-helix authority Jacobian J (2×H) — the coupled objective the square twist path is the
twist-only row of.

## Grounding result (2026-07-05, `probe.py`) — coupling is REAL and STRUCTURED
6HB honeycomb, 210 bp, programmed bend 60° (realized to 24 loop/skips). FEM baseline reproduces
bend 50.2° / twist −1.8° vs intended bend 53.8° / twist −1.3°. Per-helix single-skip authority:

| helix | Δtwist/skip (°) | Δbend/skip (°) |
|---|--:|--:|
| 0_1 | +1.83 | −2.12 |
| 1_1 | +2.34 | −2.15 |
| 1_2 | +1.53 | +0.34 |
| 1_3 | +1.56 | +2.62 |
| 0_3 | +1.87 | +2.37 |
| 0_2 | +1.77 | +0.03 |

**Finding:** twist authority is ~uniform across helices (total density → twist); bend authority
varies −2.15…+2.62 with cross-section position (gradient across the section → bend, the bimetallic
mechanism). The two rows are near-orthogonal ⇒ the 2×H Jacobian is well-conditioned ⇒ a linear solve
can hit (twist_target, bend_target) simultaneously. Validates the coupled objective.

## Next (G1 implementation)
1. `jacobian.py` — map the full 2×H Jacobian (single-skip AND single-loop authority per helix) on an
   UNDER-realized bend design (big residual), solve least-squares for the per-helix mark deltas Δn
   toward (twist_target, bend_target) with an L2 penalty (fewest marks / least deviation), verify with
   real FINE solves. Prove it hits both targets where a twist-only or bend-only pass cannot.
2. Wire `_solve_shape_targets` into `cando_autorefine.fem_refine`'s honeycomb branch (replacing the
   deviation greedy); deviation RMSD becomes the tiebreak. Regression-gate on the square twist result.

## VALIDATED (2026-07-05, `jacobian.py`) — coupled solve hits both targets
Under-realized 60° bend (half marks stripped): baseline bend 25.7° (err 28.1°), twist −0.72°.
One ridge-least-squares Jacobian iteration → bend **49.7°** (err 4.1°), twist −1.76° (err 0.45°),
solving `x = [−3,−3,0,+3,+3,0]` = loops on the −bend-authority helices (0_1,1_1) + skips on the
+bend side (1_3,0_3). The bimetallic inner-loops/outer-skips pattern emerged FROM THE JACOBIAN, no
geometric reasoning. The 4° residual is the FEM's intrinsic under-realization limit (fully-realized
design itself reaches only ~50.2°), not a solver miss. `results/jacobian_validation.json`.

**⇒ Ready to wire `_solve_shape_targets` into `cando_autorefine.fem_refine`'s honeycomb branch**
(deviation greedy → coupled twist+bend solve; deviation as tiebreak). Square twist path = the
twist-only row (regression-gate it). Then G2 (hollow-tube authority law), G3, G4, G5.
