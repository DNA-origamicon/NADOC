# Generalizing the CanDo-FEM autorefine — plan

exp37 wired a **twist-nulling** objective for **solid square** bundles (the `fem_refine` SQUARE
branch: density sweep by twist-error + fractional per-helix bumps, authority measured in-loop).
This maps what it takes to generalize to *any* design and *any* intended shape.

## The core generalization: a coupled (twist, bend) objective vs the INTENDED shape

The user's framing is the crux: **bend induces twist and twist induces bend** (off-diagonal elastic
coupling; strongest for asymmetric cross-sections). So the objective is NOT "null twist" — it is
**drive the FEM-predicted (twist, bend) to the design's intended (twist, bend)**, which for a
straight strut is (0, 0) but for a programmed design is whatever the DeformationOps encode. Deviation
RMSD stays a secondary tiebreak (it trades off against hitting the shape — exp37).

The lever is the **per-helix loop/skip count vector** `c = (c_1…c_H)`. exp37 measured, for solid
square, the Jacobian column **∂twist/∂c_h** (the "authority" map — middle-row helices dominate).
Generalizing = also measure **∂bend/∂c_h** and solve the small linear inverse problem

    J · Δc = (twist_target − twist_now,  bend_target − bend_now),   J = [∂twist/∂c ; ∂bend/∂c]

for an integer Δc (skips −1 / loops +1), off crossovers/ends, verified by real FEM solves. This is a
strict superset of the current square path (which is the twist-only row of `J` with bend held ~0).
Honeycomb bend designs are the first consumer (they currently use the deviation-greedy fallback).

**Why it's tractable:** the FEM is fast, deterministic, and (exp37) placement-independent + ~linear
in count near the operating point, so `J` is a stable small matrix and the solve is a few real
verifications, not a stochastic search.

## Answers to the three scoping questions

### 1. Hollow square tubes of various diameters — YES (authority-vs-geometry law)
Purpose is not the tube per se but to learn whether the authority columns of `J` are **predictable
from cross-section geometry** (moment arm `r_h` of each helix about the bundle neutral axis) instead
of needing a per-design in-loop probe. Prediction to test: `∂twist/∂skip_h ∝ r_h²` (torsional) and
`∂bend/∂skip_h ∝ r_h` about the bending axis. A diameter sweep (hollow SQ tubes d = 2,3,4,5,6…, plus
solid vs hollow at matched d) directly fits `authority(r_h, d)`.
- **If it fits a closed form** → seed `J` analytically, skip the O(H) probe → the optimizer scales to
  large designs cheaply (the probe is the current cost bottleneck).
- **If it doesn't** → keep the in-loop probe, but the tables tell us how much symmetry to exploit.
Hollow tubes also stress the twist measure (all helices on a thin annulus — near-degenerate for the
cross-section frame at small wall thickness); worth confirming `measure_bundle_twist` stays robust.

### 2. Odd / asymmetric cross sections — YES (the coupling stress test)
Asymmetric sections (L-shape, triangle, single off-lattice helix, 2×N vs N×2) have an **off-center
neutral axis**, so a *uniform* density change induces **bend as well as twist** — exactly the
coupling the scalar twist objective ignores. These are where the separable "twist-only" or
"bend-only" heuristics fail hardest and the full 2×H Jacobian solve is mandatory. Priority set: one
L-section, one triangular, one "solid block minus a corner", each straight and with a programmed
bend+twist, to prove the 2D solve hits both targets where a 1D one can't. This validates the general
objective more than any symmetric case can.

### 3. 1×N (single-layer) origami — YES, as a degenerate special case (guard, don't optimize twist)
A single row of helices is **colinear in cross-section** → there is no 2D cross-section to rotate, so
end-to-end *twist* is ill-defined (`measure_bundle_twist` needs ≥2 non-colinear helices; a 1×N gives a
degenerate frame). 1×N shape is **bend-dominated** (a ribbon). So the generalization must:
- detect the twist-degenerate case (rank of the cross-section point cloud) and **drop the twist row**
  of `J`, optimizing bend (and deviation) only;
- treat 2×N / N×1 as the boundary where twist authority is small and noisy — clamp/guard it.
Cheap to map and important for robustness: many real origami are 1–2 layers.

## Phased plan + STATUS

- **G1 — coupled (twist,bend) objective. ✅ DONE + WIRED.** `_solve_shape_targets` (in
  `backend/core/cando_autorefine.py`) builds the measured 2×H authority Jacobian (∂twist, ∂bend per
  helix, multi-skip probe), ridge-least-squares solves toward (twist_target, bend_target), realizes
  integer per-helix deltas (skips/loops), keeps a step only if it lowers the combined shape error.
  Wired into `fem_refine`'s HONEYCOMB branch (`objective="shape"`) when the design carries a real
  shape target (bend > noise floor OR twist beyond tol); else falls back to the deviation greedy.
  Validated: under-realized 60° bend → bend 25.7°→54.0° (target 53.6°). exp38.
- **G2 — authority-vs-geometry law. ✅ DONE.** Twist authority ∝ ~1/(N·r); bend ∝ moment arm but
  noise-limited on symmetric tubes → geometry is a SEED, keep the in-loop measured Jacobian for
  accuracy. exp39. Also surfaced: `auto_scaffold` leaves disjoint scaffolds on some sections → audit
  every generated bundle.
- **G3 — asymmetric sections. ✅ DONE (plan-refining).** Strong-asymmetry cases (L, triangle) don't
  auto-route (→ separate handoff); on the routable notch, register→bend coupling is weak → coupled
  solve gated on intended-bend > ~3° (the `BEND_TARGET_FLOOR_DEG` in the wiring). exp40.
- **G4 — 1×N & few-layer. ✅ DONE — no guard needed.** 1×N is rank-1 colinear but the twist estimator
  tracks the ribbon helicoid twist fine and the autorefine works (68°→1.5°). exp41.
- **G5 — scale. OPEN.** Symmetry-orbit grouping (equivalent helices share an authority column) to cut
  the probe from O(H) to O(orbits) on 100s-of-helix designs — the geometry law (G2) sets which helices
  are equivalent.

Each phase reused the exp37 harness (parallel FINE solves, checkpoint + watchdog) to generate the
validation tables the same way this one did.
