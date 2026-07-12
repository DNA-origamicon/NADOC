---
name: snupi-mimic
description: "Plan — recreate base SNUPI \"for free\" (transcribe published params into the existing CanDo FEM + validate vs on-disk atomistic MD). Extra-crossover-base extension = the only paid MD."
metadata: 
  node_type: memory
  type: project
  originSessionId: 50fa1bce-741d-4cbe-a62f-7e750db8c0f9
---

# SNUPI mimic — get base SNUPI for free

**Goal:** Test whether *base* SNUPI can be recreated at ~$0 new MD by (1) transcribing SNUPI's
published per-motif parameters (`Literature/SNUPI_SI.pdf`, Tables S1–S5) into a param DB and
(2) wiring them into NADOC's existing corotational beam FEM (`backend/physics/fem_solver.py`),
then validating against on-disk full-atomistic MD (6hbx100_noT). If it holds, the
extra-crossover-base extension (the only part needing GPU MD) plugs into the same param DB.

## Why this is cheap (established 2026-07-11)
- SNUPI (Lee/Kim, ACS Nano 2021) ran **almost no new MD**: regular+nicked BP steps = published
  3DNA values (SI Tables S1–S2); CO motifs = **reused** Bathe-2012 trajectories (the 32-hb
  honeycomb bundles, Fig S2) + a few additions (SI Note S14). All **74-motif** params are
  printed in **SI Tables S1–S5**; Figure S1 plots them.
- SNUPI's model = the **same corotational per-bp beam FE as CanDo**, plus three deltas. NADOC's
  `fem_solver.py` is already a CanDo-replica **validated** vs CanDo (RMSF 0.8–0.97, twist
  ~10–30%, bend ~0.9 — see [[project_cando_fem]]). So this is a small delta on validated code,
  not a rebuild.

## The three deltas (CanDo → SNUPI)
1. **Anisotropic per-motif 6×6 stiffness**, sequence-dependent (6 rigidities EA/GAy/GAz/GJ/EIy/EIz),
   74 motif types — vs the current isotropic scalar EA=1100 / EI=230 / GJ=460. Transcribe S1–S5.
2. **15 coupling coefficients** per motif (trans–rot, incl. twist–stretch ≈ −277 pN·nm) — currently none.
3. **Debye–Hückel inter-helix electrostatic elements** (SI Notes S6/S7) — the one genuinely new
   solver piece; today inter-helix coupling is via crossover links only. **Deferrable to P3.**

## Validation data — ON DISK, no new MD
- **6hbx100_noT** — standard 6-helix honeycomb, no extra bases; complete set at
  `workspace/md_jobs/892ad3d12d4f/package/6hbx100_noT_namd_solvated/` → psf + pdb +
  **20 ns k=0 production DCD (1.96 GB)**. **Primary base-SNUPI target.**
- **3x4SQ** — square lattice, k=0 DCD (`workspace/md_jobs/93cdbbd3a3f1/...`) → validates SQ params.
- 6hbx100_1xT / 2xT, 6hb_2xT — extra-base variants → the EXTENSION targets (base SNUPI can't
  predict these; use after the Δbase extra-base motifs are added).
- ⚠ **18hb trajectory is NOT on this machine** (job `e29d1e5d5ace` absent; only exp30 summary
  docs in `experiments/exp30_18hb_production/`). The 39 GB DCD lives on the work computer —
  sync it if you want 18hb as an extra target; **not needed to start**.
- ⚠ **`Literature/SNUPI_SI.pdf` is gitignored (local only)** — run this plan ON THIS MACHINE,
  or re-copy the SI + main paper on the other computer first.

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
- **P3 — Electrostatics (SI S6/S7, 1 session, optional for a first result).** Debye–Hückel repulsion
  spring elements between near helices (scaffolding exists: `FEMSpring`, `assemble_field_force`).
  Defer until P4 shows inter-helix spacing / lattice is wrong without it.
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

**Verdict test:** "SNUPI for free" = YES if transcribed params + the existing FEM reproduce MD
(and SNUPI's published) shape/RMSF within a stated tolerance. Then the extra-base extension is the
only GPU spend (~$3–8k — [[project_bundle_stiffness_params]] / [[project_crossover_parameterization]]),
plugging into the same param DB. ✅ Verdict reached (snupi ≥ cando both lattices, at $0).

- **P5 — Frontend SNUPI engine tab (NEXT, fresh session, 2026-07-11).** Surface the mimic in the app as
  a first-class structure-prediction engine tab (sibling to CanDo FEM / mrDNA / oxDNA / NAMD). Backend
  is READY: `predict_shape(design, material="snupi", anchors=, field=)` — no new solver work; this is a
  UI/route wiring task. Scope: unified jobs card + live progress bar + advanced-params card + visualization
  card with the standard rep toggles (RMSF coloring, axis/cylinder, backbone), and an INVESTIGATION into
  wiring anchors + E-fields + surfaces (predict_shape already accepts `anchors=`/`field=`; how does CanDo
  FEM surface them today, and can SNUPI reuse that path + a "surface" scope). Since SNUPI == a material flag
  on the SAME FEM as CanDo, strongly prefer EXTENDING the existing CanDo-FEM job/route/panel with a
  material selector over a parallel stack — decide in the fresh session after reading the panel architecture.
  Module-first law applies (no main.js growth). Detailed build prompt handed to the fresh session (see
  session handoff / the prompt generated 2026-07-11).

## Risks / rules
- **Convention conversions** (3DNA vs beam element; SNUPI's own co-rotated local triad). The
  `bundle_stiffness.json` cross-check catches gross errors. Transcribe SNUPI's OWN convention —
  do NOT reuse the Euler-ZYZ extraction pipeline (gimbal-locked K_q3/K_q5; see
  [[feedback_bundle_param_extraction]]).
- **Three-Layer Law:** FEM output is PHYSICAL/display only, never writes topology.
- Don't touch `_PHASE_*`. Concurrent sessions share this tree — never git stash/reset/restore/checkout;
  forbid git in subagent prompts.

## Handoff
**P1 + P2 + P2b + P4 DONE (2026-07-11). FINAL VERDICT: "SNUPI for free" = YES** — snupi ≥ cando on
both lattices at $0 (robustly better on the well-sampled 20ns honeycomb; a tie/slight snupi rank-edge
on the under-sampled 5ns square). The mimic is built and validated. Next best (only if pursued):
longer square-lattice MD to firm up SQ; single-vs-double-CO classification; bp-frame registration;
then **P3** (Debye–Hückel electrostatics) — the extra-base extension is the only GPU spend.
Everything to run the mimic exists:
- Params: `backend/data/parameters/snupi_params.json` (74 motifs). Pin `tests/test_snupi_params.py`.
- Material: `backend/physics/snupi_material.py` → `family_mean_D(fam)` 6×6. Pin `tests/test_snupi_material.py`.
- FEM: `predict_shape(design, material="snupi")` / `assemble_global_stiffness(mesh, material="snupi")`
  / `compute_rmsf_nma`. Pin `tests/test_snupi_element.py`. cando path unchanged.
- Informal first data point: on `6hbx100_noT`, cando RMSF mean 0.411 nm vs snupi 0.398 nm (630 nodes,
  624 beams, 66 crossover rigid links). Comparable magnitude (shared crossover model); P4 tests
  RMSF-*pattern* correlation + shape vs the MD DCD, which is where couplings/anisotropy show.

**P4 to-do:** from `workspace/md_jobs/892ad3d12d4f/package/6hbx100_noT_namd_solvated/` (psf+pdb+20ns
k=0 DCD), compute per-bp RMSF (bp-center = mean both-strand C1'; reuse `local_crossover_extract.py`
/ `build_p_gro_order`) + equilibrium shape/twist/bend/L_p. Correlate snupi vs cando vs MD.
Success = snupi ≥ cando at matching MD, at $0.

**Open P2b/P3 (only if P4 says so):** (P2b) crossovers as compliant double-CO/single-CO beams
(replace rigid links; single-CO needs PD-projection — 7/16 non-PD); bp-frame registration for EIy≠EIz;
snupi prestress force. (P3) Debye–Hückel electrostatics.

Key references: `backend/physics/fem_solver.py`, `Literature/SNUPI_SI.pdf` Tables S1–S5,
[[project_cando_fem]] (FEM scorecard), [[feedback_bundle_param_extraction]] (why NOT Euler-ZYZ).
