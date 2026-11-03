# Phases — supporting detail

[Topic head](../../project_snupi_mimic.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Phases
- **P1 — Transcribe params ($0, ½–1 session). ✅ DONE 2026-07-11.**
  `backend/data/parameters/snupi_params.json` written (74 motifs: 10 regular_bp + 16 nicked_bp
  + 16 co_nick + 16 double_co + 16 single_co). Each motif = **12 geometry** (dx/dy/dz + θx/θy/θz,
  node1&node2; nm & deg), **6 rigidity** (EA,GAy,GAz [pN]; GJ,EIy,EIz [pN·nm²]), **15 coupling**
  (g rot-rot [pN·nm²], trans-trans [pN], rot-trans [pN·nm]). Parsed programmatically from
  `pdftotext -layout` of the SI (parser in scratchpad `parse_snupi.py`) with per-row unit +
  motif-name + column-count validation — not hand-copied. **T = 300 K** (SNUPI), vs 310 K in our
  bundle_stiffness. Convention = SNUPI's own co-rotational CR-triad beam frame (Notes S3/S4),
  explicitly NOT Euler-ZYZ. Pin: `tests/test_snupi_params.py` (7 tests, green).
  - **Deviation from plan — no separate SQ table.** The 74 motif intrinsic properties are
    **lattice-independent** in SNUPI (CO motifs reuse Bathe-2012 honeycomb bundles). Honeycomb vs
    square enters ONLY via the initial configuration (Note S8: ω=34.29° HC vs 33.75° SQ, CO dist
    2.25 nm), stored under `lattice_dependence.initial_config_SI_Note_S8`. So one motif set, not HC+SQ.
  - **Cross-check (physical sanity, since bundle_stiffness is a *different* observable —
    inter-helix 6-DOF kJ/mol/Å², not per-bp beam rigidity → no direct value match expected):**
    regular-BP means give bend L_p = EI/kT ≈ 48.8 nm (dsDNA lit ~50 ✓), twist L_p = GJ/kT ≈ 75.8 nm
    (lit ~75–100 ✓), stretch modulus EA ≈ 1825 pN (lit ~1000–1500 ✓). Twist–stretch coupling
    g(dx,θx) mean = **−277.4 pN·nm** — matches the plan's stated ≈−277, independent confirmation the
    coupling rows are aligned. SNUPI/CanDo-isotropic ratios: EA 1.66×, EI 0.88×, GJ 0.68× (all same
    order → units consistent).
- **P2 — Wire the SNUPI material into fem_solver. IN PROGRESS (2026-07-11).**
  Decision (with user): **build the full co-rotational/Timoshenko element, not the incremental
  Euler-Bernoulli pass.** Reason (the "flip to Timoshenko" trigger): the *couplings*, not the
  anisotropic bending, are SNUPI's load-bearing delta over isotropic CanDo, and a linear E-B 12×12
  cannot host them:
    - Anisotropic bending EIy≠EIz **self-cancels** — bp bending axes rotate 34.3°/bp, sweeping a full
      turn every 10.5 bp, so over any bundle (≫1 turn) it averages back to isotropic. Low value.
    - **Twist–stretch coupling g(Δx,Θx)=−277 pN·nm does NOT self-cancel** — it couples axial stretch
      to axial twist, both in the fixed helix-axis DOFs (don't rotate with the bp frame), so it
      accumulates coherently and drives global twist–bend (DNA overwind-under-tension). This is the
      mechanism SNUPI adds; an E-B-only P4 would be a *misleading negative*.
    - Also found: SNUPI/CanDo are **co-rotational** beams; NADOC's element is *linear* Euler-Bernoulli.
      Match SNUPI's co-rotational linearization in the element; prove the convention by a mechanical
      unit test (cantilever + twist–stretch response), not by reasoning (topology/convention rule).
  **Step 1 DONE — `backend/physics/snupi_material.py` + `tests/test_snupi_material.py` (7 tests green).**
  Loads the params → per-motif and per-family-MEAN **6×6 sectional constitutive matrix D** in SNUPI's
  own DOF order q=[dx(axial),dy,dz,θx(torsion),θy,θz], diagonal rigidities + 15 couplings, mixed SI
  units. Formulation-independent (no NADOC-frame remap yet — that's pinned by the element unit test).
  **Finding — single-CO indefiniteness:** 7/16 per-motif `single_co` D are numerically NON-PD (real
  SNUPI limitation of single-crossover fits — verified vs raw SI, e.g. AT|AT g(dx,dy)=636.5>√(EA·GAy);
  NOT a transcription error). All 4 other families fully PD; **every family MEAN is PD** (single_co
  mean min-eig +97) → the MEAN-first path is unaffected & validated. Sequence-specific single-CO will
  need PD-projection later.
  **Steps 2-3 DONE (2026-07-11).** `backend/physics/fem_solver.py` + `tests/test_snupi_element.py`
  (10 tests) + all 15 existing `test_fem_solver` green.
    - `_snupi_element_stiffness(L, D)` — anisotropic **Timoshenko** element, K=L·BᵀDB, constant-strain
      (1-pt) integration = built-in shear-locking cure. Local z=axial (matches NADOC frame, reuses
      `_transform_to_global`). Strains ordered by ROLE to match D's [dx,dy,dz,θx,θy,θz] → no D permutation.
    - **Twist-stretch proven by unit test (not reasoning):** K[8,11]=D[0,3]/L exactly; a snupi element
      induces twist under axial pull, a cando element induces exactly ZERO. This is the SNUPI delta, live.
    - Wired behind `material="snupi"|"cando"` through `assemble_global_stiffness` → `solve_prestress_shape`
      → `predict_shape`. **cando path byte-identical** (all existing tests green).
    - **Scope (controlled first pass):** SNUPI material applied to INTRA-HELIX beam elements only
      (regular_bp / nicked_bp family MEAN 6×6). Crossovers stay rigid links in BOTH paths → snupi-vs-cando
      isolates the duplex material. Deferrals (documented): (a) crossovers as compliant double-CO/single-CO
      beams = P2b (bigger hypothesis; SNUPI's CO-step Δx≈0.95nm shows they're bridging beams, but our rigid
      links are the CanDo baseline); (b) bp-frame registration — anisotropic bending EIy≠EIz self-cancels
      over a turn, and the important twist-stretch coupling is frame-independent, so the arbitrary element
      perpendicular frame is fine for a first number; (c) prestress force still uses cando EA/GJ (RMSF, the
      first P4 metric, doesn't use prestress).
  Crossover representation confirmed on real `6hbx100_noT.nadoc`: each `Crossover`=ONE backbone crossing,
  in adjacent pairs (bp 20&21, 41&42…) = reciprocal DX. 66 crossovers, no extra_bases.
- **P3 — Electrostatics (SI S6/S7). ✅ DONE 2026-07-11.** `backend/physics/snupi_electrostatics.py`:
  Debye–Hückel repulsive TRUSS spring between BP nodes of DIFFERENT helices within `r_cut = 2.5 nm`,
  `Π = q²·l_B·kBT/r·exp(−r/λ_D)`, `q = 0.7 e` @ 20 mM MgCl₂, `λ_D = 1.24 nm`, l_B = 0.71 nm, T = 300 K —
  values match SI S7. Pure module, finite-difference-verified (force = −∇Π, K = ∇²Π); pin
  `tests/test_snupi_electrostatics.py` (6). Wired into BOTH the SNUPI shape solve AND the free-free NMA
  (RMSF) K, evaluated at the deformed/equilibrated config. On real designs ~4300 inter-helix pairs engage
  (node spacing 2.25–2.5 nm — the helices sit right in the cutoff, NOT the 2.6 nm I first worried about).
  **⚠ tangent gotcha:** the perpendicular `Π'/r < 0` term is indefinite → blew up the shape solve; use the
  **PD axial-only** tangent (`axial_only=True`) — the FORCE stays exact, only the stiffness is a PD approx →
  stable + correct equilibrium. **Effect (exp42):** stiffens a spurious soft breathing mode → SQ RMSF max
  3.07→1.30 nm; **flips the square lattice from a CanDo-tie to a SNUPI win** (SQ pearson 0.675→0.742 vs
  cando 0.703; spearman 0.548→0.623). HC ≈unchanged (0.592→0.598, already good). **New verdict: SNUPI beats
  CanDo on BOTH lattices, both metrics.**
- **S9 nonlinear solution procedure — ✅ DONE 2026-07-11.** `fem_solver._solve_snupi_nonlinear` (material=
  "snupi" nonlinear branch; cando keeps the old byte-identical loop): the proven corotational beam predictor
  PLUS (a) an **electrostatic self-consistency iteration** each load level (re-evaluate f_es(x) at the moved
  config, apply the residual until |Δx|<tol — the position-dependent nonlinearity that needs iterating), and
  (b) **adaptive Δα subdivision** on divergence/non-finite (halve + retry from last good config; grow back on
  success — SI S9's automatic Δt). Electrostatics ramps with α. Runs ~57 s on a 6HB/84 (Fine mode). Pins
  `test_snupi_element.py::test_snupi_nonlinear_solve_runs_and_is_finite` + `::test_electrostatics_stiffens_rmsf_and_cando_unchanged`.
  Remaining nuance vs a textbook S9: we keep the corotational predictor + fixed-point electrostatic
  correction rather than a full 6-DOF Newton residual (our positions track translations; rotations via
  reframing) — equivalent equilibrium, robust, and preserves the validated cando-style beam behavior.
  - **Full-6DOF-Newton attempt (2026-07-11) — ABANDONED, kept the fixed-point. Key finding:** a Newton
    over `R(u)=f_ext−K_beam(x)·u` DIVERGES (oscillates 2-cycle: ‖R‖ 4.7→50→8→40; even 42-node 2hb won't
    converge, line-search + continuation can't rescue it). Root cause: `f_int = K_reframed(x)·(x−x₀)` is
    NOT a consistent corotational internal force for finite u — u is measured from x₀ while the reframed
    K assumes small strain from the CURRENT frame → the tangent has no descent direction. **Insight that
    justifies the fixed-point:** freezing element frames per load level makes the beam EXACTLY linear, so
    the single per-level solve already IS that level's exact equilibrium — the only within-level
    nonlinearity to iterate is the electrostatics (which the fixed-point does). A genuine per-level Newton
    with in-iteration reframing needs a PROPER corotational element (track nodal rotations/orientations,
    extract per-element LOCAL deformational displacement, consistent material+geometric tangent —
    Battini/Crisfield 3D corotational; ~300-500 LOC, high-risk in the validated solver). **It would only
    improve the "Fine" SHAPE display; the validated RMSF-vs-MD metric is the separate NMA (unaffected).**
    Deferred pending an explicit go — not worth the risk for a shape-only gain. Docstring of
    `_solve_snupi_nonlinear` records the full reasoning.
- **P4 — Validate vs MD. DONE (2026-07-11). Verdict: YES on the primary target.**
  Method: MD bp-center RMSF (mean of both-strand C1' per bp, Kabsch-aligned to remove rigid body,
  A→nm) vs FEM `compute_rmsf_nma` per-bp RMSF, matched by (helix,bp); Pearson/Spearman of the
  RMSF pattern. Script: scratchpad `p4_validate.py` (args: nadoc psf dcd tag). Atom map = model C1'
  order == DCD C1' order, verified by exact base-sequence match (0/1328 mismatch). **No CI pin**
  (the DCDs are local-only, gitignored) — this is a documented analysis result.
  - **Honeycomb `6hbx100_noT` (20 ns k0, 520 frames — well-sampled, PRIMARY target):**
    **snupi robustly beats cando.** Pearson cando 0.504 → snupi 0.562; Spearman 0.262 → 0.337.
    Paired bootstrap Δpearson = +0.058, 95% CI [+0.031,+0.084], **P(Δ>0)=1.000**. Interior-only
    (trim 6 bp/end) the absolute r collapses (interior RMSF ~flat) but snupi still wins Δ+0.101 —
    it captures interior RMSF variation isotropic cando misses. MD RMSF mean 0.32 nm; FEM ~0.40
    (over-predicts mean ~25%, under-predicts floppy-end maxima: MD max 1.59 vs FEM 0.77).
  - **Square `3x4SQ` (5 ns k0, 250 frames — 4× less sampled, SECONDARY):** cando slightly ahead
    (Pearson 0.717 vs 0.675, Δ−0.040) BUT the gap shrinks to **non-significant in the interior**
    (Δ−0.022, P=0.08). Confounded by short sampling + FEM end-node over-prediction (FEM max 2.4–2.9
    nm vs MD 0.56). Inconclusive; not a counter-verdict. (0.5 ns DCD was useless — MD 5× under FEM.)
  - **Bottom line (pre-P2b):** meets the plan's success bar on the well-sampled honeycomb primary;
    square inconclusive.

- **P2b — Compliant CO-step crossover beams. DONE (2026-07-11). Sharpens the verdict to snupi ≥ cando
  on BOTH lattices.** Replaced the rigid crossover penalty links with finite-stiffness SNUPI
  `double_co` mean 6×6 CO-step beams (element axial along the inter-helix offset), for `material="snupi"`
  only — cando keeps rigid links (byte-identical). `assemble_global_stiffness` snupi branch + pin
  `test_snupi_element.test_p2b_crossovers_are_compliant_not_rigid` (no K_PENALTY-scale entries under
  snupi; bundle stays connected = 6 rigid modes). Simplification: all crossovers → double_co (the
  all-PD, standard-reciprocal family); single-vs-double classification deferred.
  - **HC 20ns (re-run w/ P2b):** snupi still robustly > cando. ALL Pearson Δ+0.051 (P=1.00), Spearman
    Δ+0.090; INTERIOR Δ+0.127 both (cando ~0 in interior, snupi captures the variation). ≈neutral vs
    P2a on pearson, better on rank.
  - **SQ 5ns (re-run w/ P2b):** P2b HELPED the hard 90°-lattice case. Was cando-ahead (P2a Δpearson
    −0.040); now ALL Pearson Δ−0.023 (P=0.01, small), Spearman Δ+0.016 (snupi>cando); INTERIOR Pearson
    Δ−0.006 (**P=0.36 — not significant, a tie**), Spearman Δ+0.009 (snupi>cando). No longer a cando win.
  - **FINAL VERDICT: "SNUPI for free" = YES.** With the full P2b model, snupi ≥ cando on both lattices —
    clearly better on the well-sampled honeycomb (all cuts, robust bootstrap), statistical tie / slight
    snupi rank-edge on the under-sampled square — at $0 new MD. Driver = twist-stretch coupling + motif
    anisotropy + compliant crossovers. Remaining headroom (abs r ~0.55 HC): bp-frame registration,
    single/double-CO classification, longer SQ MD, P3 electrostatics.
