# exp37 FOLLOW-UP — twist objective WIRED INTO autorefine (2026-07-05) — supporting detail

[Topic head](../../project_cando_fem.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## exp37 FOLLOW-UP — twist objective WIRED INTO autorefine (2026-07-05)
Acting on exp37, changed `cando_autorefine.fem_refine` so the **SQUARE** path optimises end-to-end
TWIST relative to the design's INTENDED twist (`_twist_error` = |FEM twist − target["twist_deg"]|,
differential so the lattice offset cancels + it generalises to programmed-twist designs), NOT the
deviation RMSD (which bottoms at a lower density → floored twist at ~10-15°).
- `fem_measure` now returns `twist_deg`/`bend_deg` (off the cached solve).
- `sweep_skip_period(cost_fn=…)` — pluggable objective; default RMSD (back-compat), square passes a
  twist-error cost → sweeps to the twist-nulling density.
- `_fractional_twist_bump` — fractional per-helix density: measures ∂twist/∂skip authority per helix,
  bumps highest-authority helices by ±1 skip toward target until |twist−target|<`TWIST_TOL_DEG`(=1°).
  Mirrors the exp37 "spread" winner (bump the middle row). Placement even/off-forbidden; no geometric
  reasoning (authority MEASURED, bumps empirically kept — [[feedback_crossover_no_reasoning]]).
- `fem_refine` result gained `objective` ("twist"|"deviation"), `twist_target/before/after`,
  `twist_tol`, `authority` (per-helix map). HONEYCOMB path UNCHANGED (deviation greedy) — full
  coupled twist+bend objective for honeycomb is the generalisation plan.
- **`cando_runner` apply gate FIXED**: was `after_rmsd < before_rmsd` → would REJECT the twist-optimal
  program (rmsd RISES as twist→0). Now square gates on twist-error improvement; note shows
  twist before→after. New job fields `refine_twist_before/after/target`.
- Tests updated to the twist contract: `test_cando_autorefine.py` (square strut nulls twist +
  authority map), `automation_harness.assert_fem_autorefine_relieves_twist` (asserts twist relief for
  square, rmsd relief for honeycomb), `test_cando_autorefine_validation.py`. Smoke (200bp 6HB SQ):
  twist 58.1°→0.67°, 37 skips, off-forbidden, authority for 6 helices.
- **Generalisation plan** (coupled twist+bend Jacobian objective; hollow-tube authority-vs-geometry
  law; asymmetric-section coupling stress test; 1×N twist-degeneracy guard; symmetry-orbit scaling):
  `experiments/exp37_cando_skip_twist_map/GENERALIZATION.md`.

## Generalization progress (2026-07-05) — G1 done, G2 done
- **G1 (exp38, `experiments/exp38_coupled_shape_jacobian/`) — coupled (twist,bend) Jacobian VALIDATED.**
  On honeycomb bend designs a per-helix skip moves BOTH twist and bend; bend authority varies by
  cross-section position (bimetallic: inner vs outer bend opposite), twist authority ~uniform → the
  2×H Jacobian is well-conditioned. Ridge least-squares solve recovered an under-realized 60° bend
  25.7°→49.7° (err 28°→4°, twist err <0.5°) in ONE iter, discovering inner-loops/outer-skips from the
  Jacobian alone. Algorithm validated; NOT yet wired into `fem_refine` honeycomb path (deviation greedy
  still live). Next code step: `_solve_shape_targets` replacing the honeycomb branch.
- **G2 (exp39, `experiments/exp39_hollow_tube_authority/`) — authority-vs-geometry law.** Hollow SQ
  tubes d3–d6 route CLEANLY (single scaffold, no across-hollow crossovers, full mesh); audit flagged a
  mis-routed solid 3×3 (2 scaffolds). Twist authority ∝ ~1/(N·r) (steers less as section grows); bend
  authority ∝ moment arm but noise-limited on symmetric/large tubes (scalar arc-bend ~0.6° floor).
  VERDICT: geometry predicts the trend, not accurate per-helix numbers → keep the in-loop Jacobian for
  accuracy, use geometry as a seed; symmetry-orbit grouping (G5) for scale. **Autostaple caveat: basic
  auto_scaffold can leave DISJOINT scaffolds (solid 3×3 → 2); auto_break nicks land on crossovers on
  ALL square bundles — audit every headless-generated bundle before trusting its FEM numbers.**
- Remaining: wire G1 `_solve_shape_targets` into honeycomb `fem_refine`; G3 asymmetric sections
  (bigger/cleaner bend signal + multi-skip bend probe); G4 1×N twist-degeneracy guard; G5 scale.

## Generalization G3 + G4 (2026-07-05) — both plan-refining (partly negative)
- **G3 (exp40) — coupled objective's domain narrowed.** auto_scaffold FAILED to route strong-asymmetry
  cross-sections (L→2 scaffolds, staircase triangle→10; audit flagged+skipped). Only notch_4x4 routed.
  On the notch (straight strut) register→bend coupling is weak (~0.9° bend, near noise) → 1D twist-null
  already suffices; forcing the 2D coupled solve on a sub-noise bend row makes it slightly WORSE.
  ⇒ **Use the coupled (twist,bend) solve only when the design has an intended bend above the ~0.6°
  arc-bend noise floor (i.e. programmed-shape designs, per G1); twist-only for straight struts.**
  Strong-asymmetry study is BLOCKED on the auto-scaffold routing bug → handoff prompt at
  `experiments/exp40_asymmetric_coupling/ASYMMETRIC_SCAFFOLD_HANDOFF.md` (asymmetric shapes route to
  disjoint scaffolds; seamed_router Hamiltonian path fails; read project_autoscaffold_single_strand).
- **G4 (exp41) — 1×N twist-degeneracy hypothesis REFUTED (no guard needed).** 1×N is rank-1 colinear
  (SVD sv2=0) BUT measure_bundle_twist tracks the ribbon helicoid twist fine and the autorefine drives
  68°→1.5° correctly. Pipeline is more robust than the plan assumed. Only caveat (untested): sign
  ambiguity for an INTENDED-nonzero-twist symmetric ribbon; nulling to 0 unaffected. 2×N fully fine.
- **Net generalization status:** G1 coupled solve validated (programmed bend+twist). G2 authority∝geometry
  trend (seed only). G3 → coupled solve gated on intended-bend>noise; asymmetric auto-routing is the
  blocker. G4 → no 1×N guard needed. **Still unwired: G1 `_solve_shape_targets` into honeycomb fem_refine**
  (the one live-code step); G5 (symmetry-orbit scaling) open.
- **G3 asymmetric-auto-routing blocker CHARACTERIZED + GUARDED (2026-07-05).** Why some asymmetric SQ
  sections gave the FEM disjoint scaffolds = garbage authority: the SEAMED router silently fragments TWO
  shape classes. (A) **odd helix group** — the step-2 pairing `(0,1)(2,3)…`+`(1,2)(3,4)…` orphans `path[n-1]`
  (3×3→8+1, L→6+1); a Ham path EXISTS, it's a parity bug. (B) **no Hamiltonian path** in the *crossover*-
  adjacency graph (staircase triangle → `brute_ham=False`) → whole group skipped → every helix its own
  scaffold. Predictor = Hamiltonicity of the *crossover* graph + helix-count parity — NOT cell-grid
  cut-vertices (red herring: L has 5 yet its xover graph is a clean path). **SEAMLESS handles odd fine**
  (zig-zag pairing) → guard is seamed/matched-only. **Shipped guard:** `seamed_router.seamed_routability_errors`
  (pure; skips forced-ligation + multisection = out of scope) → `routes_scaffold_routing._guard_seamed_routable`
  raises 422 BEFORE any mutation on the seamed+matched endpoints → frontend toasts it (picker already wired,
  no FE change). For the CanDo battery: **route asymmetric sections SEAMLESS, or keep even-helix Hamiltonian
  sections.** Detail in [[project_autoscaffold_single_strand]].

## G1 WIRED into fem_refine honeycomb path (2026-07-05)
`_solve_shape_targets` (cando_autorefine.py) — the exp38 coupled solve, productionized: measured 2×H
authority Jacobian (∂twist,∂bend per helix; multi-skip probe ÷count), ridge least-squares toward
(twist_target, bend_target), integer per-helix deltas (skips x>0 / loops x<0), keep-if-combined-error-
drops. `fem_refine` HONEYCOMB branch now: `objective="shape"` via the coupled solve WHEN the design
has a real shape target (`use_bend_target`: |intended bend| > `BEND_TARGET_FLOOR_DEG`=3° — the exp40
G3 gate — OR twist beyond tol); else falls back to the deviation greedy (`objective="deviation"`,
straight/weak-target, unchanged). Square path unchanged (`objective="twist"`).
- Result gained `bend_target/before/after`, `bend_tol`; `authority` for shape = `{helix:[∂tw,∂bd]}`.
- `cando_runner` apply-gate handles "shape" (combined twist+bend error; RMSD rises as shape is hit);
  note shows twist AND bend before→after. Job fields `refine_bend_before/after/target`.
- Constants: `BEND_TOL_DEG`=3, `BEND_TARGET_FLOOR_DEG`=3.
- Verified: honeycomb under-realized 60° bend → bend 25.7°→54.0° (target 53.6°), objective=shape,
  28 marks, authority for 6 helices; STRAIGHT honeycomb → objective=deviation, 0 edits (no harm).
  Tests: `test_refine_honeycomb_shape_hits_bend_and_places_marks_off_forbidden` (replaces the old
  rmsd-never-rises test); affected suite 27 green. **NOT hand-verified in the CanDo panel** (the note
  carries twist+bend; frontend shows refine_note unchanged — bend-specific UI is optional follow-up).
- Generalization: G1 wired, G2/G3/G4 done, **G5 (symmetry-orbit probe scaling) still open**.

## ANCHORS — Dirichlet BC (2026-07-06, sim-coverage task C1)
The FEM shape solve can now be run with **anchors** (a physical tether held fixed), the CanDo
analogue of a boundary condition. Backend-only; anchors are a JOB-REQUEST annotation, never a
`Design`/topology edit (Three-Layer Law).
- `apply_boundary_conditions(K, f, mesh, fixed_nodes=None)` — pins all 6 DOF of each `fixed_nodes`
  index (Dirichlet); `None` **or an empty list** falls back to the legacy centroid pin (an anchor
  selection that resolved to nothing never makes the system singular).
- `solve_prestress_shape(..., fixed_nodes=None)` clamps them at every corotational load step → the
  anchored region stays exactly at rest while the rest deflects under the loop/skip eigenstrain.
- `resolve_anchor_nodes(design, mesh, anchors)` — reuses the **shared oxDNA scope resolver**
  (`oxdna_interface.resolve_anchor_particles`: overhang/cluster/domain/strand/base) → per-nucleotide
  `(helix,bp,dir)` keys, collapsed onto the single duplex-core axis node per bp (both strands → one
  node). Out-of-core nts (ssDNA ends, extra-base inserts) drop silently.
- `predict_shape(design, *, anchors=None)` threads anchors through both the nonlinear and linear
  paths and returns `anchor_keys: [[helix_id, bp], …]`. RMSF stays the free-free NMA regardless
  (intrinsic flexibility; anchoring the RMSF is a possible later refinement, not needed by C1).
- Oracle `tests/test_cando_anchors.py` (10 fast): synthetic beam pins held & free tip moves under a
  test load; resolver maps base/cluster scopes & drops stale; prestress solve holds the anchored node
  exactly while the rest deflects; unresolved anchor is a no-op (positions identical, free-free RMSF
  preserved). Anchors are the substrate for **C2** (E-field deflection needs an anchor to hold against).

> **History.** Derivations, the superseded bend-gap diagnosis + rigid-link MPC investigation live in [project_cando_fem_archive.md](../../project_cando_fem_archive.md). Read on demand only.
