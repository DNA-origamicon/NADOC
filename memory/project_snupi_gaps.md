---
name: project_snupi_gaps
description: "Gap analysis — our SNUPI mimic vs the full published SNUPI (Lee/Kim ACS Nano 2021, SI Notes S1–S15). Every modeling difference + a phased implementation plan + a fresh-session kickoff prompt."
metadata:
  node_type: memory
  type: project
---

# SNUPI mimic — gap analysis vs the full publication + build plan

## ✅ Phase D DONE (2026-07-12) — G4 + G5 + G11 (full corotational Newton; opt-in, shape-only)
- **G4 corotational 3D beam** — `backend/physics/snupi_corotational.py`. Element-independent corotational
  (EICR): wraps the STANDARD 12×12 linear beam (`local_beam_stiffness_12`) as the local core and adds the
  corotational filter (CR frame `_cr_frame` z=chord + Battini mean-rotation aux vector; reference offsets
  so rest/rigid motion → zero deformation; SO(3) `exp_so3`/`log_so3`). `element_force_tangent` returns the
  CONSISTENT internal force `f_g=T·K₁₂·d_local` — the piece the earlier naive Newton lacked. Pins
  `tests/test_snupi_corotational.py`: rigid-body ⇒ zero force; small load ⇒ EXACT linear-EB `δ=FL³/3EI`
  (ratio 1.000); large load ⇒ converges with elastica foreshortening.
- **G5 Newton–Raphson** — `solve_corotational`: load-stepped global Newton, tracks node positions + triads
  (triads via exp-map), step-capped. **Uses the analytic MATERIAL tangent `T·K₁₂·Tᵀ` (`geometric=False`)**
  in the integration — a modified Newton that converges robustly WITHOUT the O(12·n_el) finite-difference
  geometric tangent (which is far too slow at bundle scale; the exact numerical tangent is kept for the
  benchmark tests). Convergence comes from the consistent internal force, not the exact tangent.
- **G11 electrostatic consistent tangent** — the inter-helix Debye–Hückel force + **FULL** tangent
  (`axial_only=False`, the indefinite perpendicular term a real Newton tolerates) enters each iteration via
  the `extra_ft` hook, ramped with the load; ssDNA springs too.
- **Wired opt-in**: `predict_shape(material="snupi", corotational=True)` → `_solve_snupi_corotational`
  (fem_solver). Default (`corotational=False`) = the validated fixed-point predictor, unchanged; cando
  untouched. **6HB/84 (1260 nodes) converges in ~47 s** (≈ the fixed-point's 52 s), finite + physically
  bounded (span 37.6 vs 44.9 nm — the geometric foreshortening). Pin
  `test_corotational_integration_on_real_design_converges` (small 2HB, ~4 s).
- **Scope/caveats (documented):** the local element uses the SNUPI DIAGONAL rigidities (EA,GJ,EIy,EIz); the
  15 couplings (incl. twist–stretch) are NOT yet in the corotational local element — a refinement. Eigenstrain
  + field are dead loads (not co-rotated). **Verdict unchanged: Phase D improves only the Fine SHAPE, not the
  validated RMSF/DCCM metrics (separate NMA).** ALL gaps G1–G12 now closed except the couplings-in-corotational
  refinement + G9/G10 (situational) + G7's MI-based generalized correlation.

## ✅ Phase C DONE (2026-07-12) — G7 + G8 (new observables, no impact on the RMSF verdict)
- **G7 BP–BP cross-correlation matrix (DCCM, S11).** `compute_correlation_matrix(K, n, M)` — the
  Pearson correlation of per-bp displacement fluctuations from the free-free NMA modes
  (`C_ij = <Δr_i·Δr_j>/√(<|Δr_i|²><|Δr_j|²>)`, k_BT cancels). Valid corr matrix (symmetric, unit diag,
  [−1,1]); nearest-neighbor ~1, decays with separation. Shared modes helper `_nma_modes`. Pins `test_g7_*`.
  - **MD comparator** `scripts/snupi_dccm_compare.py` (→ `experiments/exp42.../dccm.json`): builds the MD
    DCCM from per-frame bp-center C1' (reusing the md_trajectory ctx), compares FE-vs-MD off-diagonal
    entries. **HC 6hbx100_noT: snupi→MD 0.491 vs cando 0.454 — SNUPI captures the motion TOPOLOGY better**
    (a second, independent validation channel confirming the RMSF verdict). SQ 3x4SQ: tie (0.387/0.393).
- **G8 bending persistence length from NMA frequencies (S12).** `persistence_length_from_nma(K,mesh,design,M)`
  — treats the bundle as a free-free Euler-Bernoulli beam, inverts the fundamental bending frequency ω₁
  (β₁L=4.730) with the bundle length + mass/length → EI_eff → L_p = EI_eff/k_BT. **6HB: L_p_bend ≈ 2.6 µm
  (105bp) / 4.5 µm (210bp), EI_eff ~46–80× a single helix — physical (≫ dsDNA 50 nm).** Self-consistency:
  the degenerate bending pair agrees (ratio ≈ 1.00). Pins `test_g8_*`.
  - **Caveats (documented in the docstring):** (1) TORSION L_p = None — these short/thick bundles have NO
    separable low-frequency pure-twist mode (twist ≫ bending stiffness, so twist modes sit high + mix;
    verified). (2) The full E-B OVERTONE series (β₂L=7.853…) does NOT cleanly appear at these aspect ratios
    (observed ω-ratios 1,1,1.72,1.97… ≠ E-B 1,2.76,5.40…), so only the fundamental is used. (3) L_p shows
    some length sensitivity (2.6→4.5 µm) — end effects on short beams; longer bundles give cleaner L_p.
- **Verdict unchanged (G7/G8 are [+] observables):** SNUPI ≥ CanDo, now confirmed on TWO channels (RMSF
  magnitude + DCCM motion topology). Remaining: Phase D (full corotational Newton) — deferred, high-risk,
  shape-only; **needs an explicit go.**

## ✅ Phase B DONE (2026-07-12) — G3 + G2, gated behind `material="snupi"`
- **G3 single/double crossover classification (S4).** `_classify_crossovers` (adjacency rule,
  confirmed w/ user): crossovers between the same helix pair in an adjacent-bp cluster (≥2) →
  `double_co`; a lone crossing (helix ends/seams) → `single_co` (much softer — EA ~8%, bending/torsion
  ~40% of double). `FEMRigidLink.co_type` → the assembler uses `family_mean_D(co_type)` (both means PD,
  sidesteps single_co per-motif indefiniteness). On 6hbx100_noT: 56 double / 10 single (all at ends).
  The **angle correction** (S4.2) is a documented NO-OP for our mimic: SNUPI applies it to CO *rest
  geometry* (Θ) which it itself calls mechanically negligible, and we use NADOC geometry for the initial
  config. Pins `test_g3_*`.
  - **exp42 (snupi vs MD): G3 is the biggest single win.** HC 6hbx100_noT pearson **0.604→0.620**
    (+0.015), spearman +0.006; SQ 3x4SQ pearson **0.743→0.761** (+0.019), spearman **0.620→0.643**
    (+0.023). Physical: softening the single COs at the floppy helix ends fixes the known end-RMSF
    under-prediction. cando byte-identical.
- **G2 bp-frame registration (S3.3 / eq 3.18). KEPT ON per user (fidelity over metric).** Each element's
  transverse frame registered so the soft bending axis EIy(Roll,158) lies along the base-pair long axis =
  the **C1'–C1' cross-strand direction** (NADOC's locked `base_normal`; convention confirmed w/ user,
  mechanically pinned `test_g2_*`). `FEMElement.R_bp`; `assemble_global_stiffness(bp_registered_frame=)`
  scoped to the RMSF NMA (shape solve keeps reframed frames); cando byte-identical.
  - **exp42: a WASH-to-slightly-negative (as the memory predicted — anisotropy self-cancels over a turn).**
    pearson HC +0.0035 / SQ +0.0017; spearman HC **−0.0146** / SQ −0.0022. Net ~neutral; kept ON for
    fidelity to the published model, not because it improves the RMSF pattern. Note: C1'–C1' is tilted
    ~15° from the true 3DNA dyad (150° groove) — a small approximation the user accepted.
- **Cumulative (pre-Phase-A → post-Phase-B, snupi vs MD):** HC pearson 0.598→0.623 (+0.025), spearman
  0.423→0.420 (~flat, G2 ate the G1/G3 rank gains); SQ pearson 0.742→0.763 (+0.021), spearman
  0.623→0.641 (+0.018). SNUPI still ≥ cando on both lattices; **G3 the standout, G1 modest, G6/G2 washes.**
- **Next: Phase C** (G7 BP–BP correlation matrix; G8 persistence length from NMA — needs G6's frequencies).
  Both are new observables, no bp-frame/topology risk.

## ✅ Phase A DONE (2026-07-11) — G1 + G6 + G12, gated behind `material="snupi"`
- **G1 sequence-specific stiffness.** `build_fem_mesh` now resolves each intra-helix `regular_bp`
  element's dinucleotide from the design's FORWARD-strand sequence (`_forward_base_map` +
  `snupi_material.motif_key_for_step`) → `FEMElement.motif`; the assembler uses `motif_D(fam, motif)`
  when set, else `family_mean_D`. **Only `regular_bp` is sequence-addressable** — nicked_bp (its 'n'
  token grammar) + crossover beams keep the family mean (documented deferral; nick-strand mapping = a
  Phase-B follow-up). Unsequenced/N → mean (byte-identical to pre-G1). Pins in `test_snupi_element.py`
  (`test_g1_*`).
- **G6 mass matrix + generalized eigenproblem (S10).** `assemble_mass_matrix` (diagonal, SPD): bp
  translational mass = (fwd+rev base molar mass)/N_A; rotational DOFs get `m·r_g²`, r_g²=0.5 nm² (bp
  ≈ flat disk R≈1 nm) so **M is NOT ∝ I** (r_g²=1 would make it ∝I → a literal no-op). `compute_rmsf_nma`
  takes `M=None` (cando, K-only) or `M` (snupi, generalized `eigsh(K, M=M, sigma=…)`, M-orthonormal φ).
  Pins `test_g6_*`.
- **G12 salt param.** `mgcl2_M` (default 0.02) threaded request→job→runner→`predict_shape`→both the
  shape solve (`_solve_snupi_nonlinear`) and the NMA ES tangent; `_snupi_es_params(mgcl2_M)` cached per
  molarity. Pins `test_g12_*`. `CreateSnupiJobRequest.mgcl2_M` (0≤·≤1), `SnupiJob.mgcl2_M`.
- **Verification:** `just test-smart` → FULL (foundational; fem_solver) 4739 pass; snupi file 19 green.
- **exp42 re-run (per-bp NMA RMSF vs MD; cando byte-identical, Δ=0.0000 both designs — gating verified):**
  | design | metric | snupi pre-A → post-A | Δ |
  |---|---|---|---|
  | HC 6hbx100_noT (20ns) | pearson | 0.5982 → **0.6043** | **+0.0061** |
  | HC 6hbx100_noT | spearman | 0.4233 → **0.4291** | **+0.0058** |
  | SQ 3x4SQ (5ns) | pearson | 0.7419 → 0.7427 | +0.0008 |
  | SQ 3x4SQ | spearman | 0.6228 → 0.6205 | −0.0023 |
  Small consistent GAIN on the well-sampled honeycomb; neutral (noise-level) on the under-sampled
  square. SNUPI still ≥ cando on both lattices, gap widened slightly on HC.
- **Ablation (HC, G1 vs G6):** the entire HC gain is **G1** (seq-only Δpearson +0.0058), **G6 is a
  near-no-op** (+0.0005) — because every bp mass ≈ 654 g/mol regardless of sequence, so mass-weighting
  barely reselects modes. G6 is still faithful (SPD M, generalized modes) and its real payoff is
  **unlocking G8** (persistence length from NMA frequencies). Verdict: sequence-specific stiffness is
  the load-bearing Phase-A win; the mass matrix is scaffolding for G8.
- **Next: Phase B** (G3 CO single/double + angle; G2 bp-frame — ASK before touching bp frames).

Source: `Literature/SNUPI_SI.pdf` (local-only), read in full 2026-07-11 (text at scratchpad
`snupi_si.txt`). Our implementation: `backend/physics/{fem_solver,snupi_material,snupi_electrostatics}.py`
+ `backend/data/parameters/snupi_params.json`. Baseline verdict already reached: our params reproduce the
SI exactly, and with electrostatics SNUPI ≥ CanDo vs MD on both lattices (see [[snupi-mimic]], exp42).
This file catalogs what still differs from the *full* SNUPI and how to close each gap.

## What we already match
- Intrinsic 6×6 motif properties (S3/S4): transcribed EXACTLY (GJ 313.83, EIy 158.33, EIz 245.79,
  g(Δx,Θx) −277.39; 74 motifs). `snupi_params.json` + `motif_D`/`family_mean_D`.
- Inter-helix Debye–Hückel electrostatics (S6/S7): q=0.7 e @ 20 mM MgCl₂, λ_D=1.24 nm, r_cut=2.5 nm.
- Free-free NMA RMSF via equipartition, 200 modes, 300 K (S11). **[G6 done: snupi now uses the
  generalized mass-weighted eigenproblem; cando stays K-only mass-independent.]**
- Compliant CO-step crossover beams; loop/skip eigenstrain; anchors (Dirichlet) + uniform E-field.

## The gaps (SNUPI SI ⟶ ours)

Impact key: **[R]** changes the NMA operator/modes → moves the validated RMSF-vs-MD metric (exp42);
**[S]** shape-display only (Fine mode); **[+]** new observable/capability (doesn't change existing numbers).

| ID | Area | SNUPI (SI) | Ours now | Impact | Effort / risk |
|----|------|-----------|----------|--------|---------------|
| G1 ✅ | Sequence-specific stiffness (S3.2) | per-BP-step 6×6 from the actual dinucleotide sequence (k = kBT·F⁻¹ of the step-parameter covariance) | ~~`family_mean_D`~~ → **DONE: per-element `motif_D` for regular_bp; nicked/CO keep mean** | **[R]** | **Low** — DONE 2026-07-11. Drove the HC exp42 gain (+0.006). |
| G2 ✅ | bp-frame registration (S3.3) | 3DNA BP triad MODIFIED to the beam nodal triad (minor-groove dir); middle triad = CR triad → anisotropic bending axes EIy≠EIz correctly oriented per bp | **DONE: `R_bp` = local-y ∥ C1'–C1' cross-strand (eq 3.18), RMSF-NMA-scoped; KEPT ON** | **[R]** | **DONE 2026-07-12.** Wash on RMSF (self-cancels over a turn, as predicted); kept for fidelity. |
| G3 ✅ | Crossover single/double (S4.1–4.3) | each DX classified single_co vs double_co + an ANGLE correction; single-CO drops one rotational rigidity | **DONE: adjacency classifier → `co_type`; family-mean single/double D. Angle corr = no-op (rest geometry, we use NADOC geom)** | **[R]** | **DONE 2026-07-12. Biggest single win** (+0.015–0.019 pearson both lattices). |
| G4 ✅ | Full corotational element (S1.4/S2.5) | Crisfield CR beam: 7×7 local Kl + geometric tangent **Kh** + a consistent internal-force vector | **DONE: EICR (wraps the 12×12 linear beam) + consistent internal force; `snupi_corotational.py`** | **[S]** | **DONE 2026-07-12.** Benchmarks: rigid⇒0, small=linear-EB, large-defl converges. |
| G5 ✅ | Full Newton–Raphson solve (S9.6) | global Newton with tangent tKG + internal-force residual tFG at each Δt | **DONE: `solve_corotational` load-stepped Newton (material tangent); opt-in `corotational=True`** | **[S]** | **DONE 2026-07-12.** Converges (the consistent internal force fixed the old divergence). |
| G6 ✅ | Generalized eigenproblem + mass matrix (S10) | K·Φ = M·Φ·Λ with a sequence-dependent nodal MASS matrix M (Σ of the two base masses / N_A) | **DONE: `assemble_mass_matrix` (SPD) + generalized `eigsh(K,M=M,σ)` for snupi; cando K-only** | **[R]** | **DONE 2026-07-11.** Near-no-op on RMSF (bp mass ~seq-independent); kept for **G8**. |
| G7 ✅ | BP–BP cross-correlation matrix (S11) | Pearson PC_ij + generalized (MI-based) GC_ij correlation MATRIX, MD vs FE | **DONE: `compute_correlation_matrix` (Pearson DCCM) + MD comparator (`snupi_dccm_compare.py`)** | **[+]** | **DONE 2026-07-12.** snupi→MD 0.491 > cando 0.454 (HC) — 2nd validation channel. (MI-based GC deferred.) |
| G8 ✅ | Persistence length from NMA (S12) | bend + torsion L_p from NMA natural FREQUENCIES (Euler-Bernoulli fit βₖLc=4.733,7.853…) | **DONE (bending): `persistence_length_from_nma` fundamental ω₁ → EI_eff → L_p ≈ 2.6–4.5 µm** | **[+]** | **DONE 2026-07-12.** Torsion=None + no clean overtone series (short/thick bundles) — documented. |
| G9 | Short-ssDNA model (S5) | equilibrated end-to-end distance for SHORT ssDNA (gaps) + nonlinear FJC/WLC, Pb=0.74 nm | translational Marko–Siggia WLC spring for extra-base crossovers only | **[S]**/**[R]** for gapped designs | **Med** — matters only for designs with ssDNA gaps/linkers; add the finite-Ree short-chain stiffness. |
| G10 | Canonical initial config (S8) | build from caDNAno: straight helices, 0.34 nm rise, **2.25 nm initial CO distance**, gradual ω=34.29°/33.75° twist, major-groove angle | NADOC's own helix-axis geometry (`deformed_helix_axes`) | **[R]** (sets ES engagement + initial strain) | **Med-High** — a parallel initial-config path; risks diverging from NADOC's geometric layer (Three-Layer). Prefer to keep NADOC geometry; only adopt SNUPI's 2.25 nm CO spacing if exp42 shows it matters. |
| G11 ✅ | Electrostatic consistent tangent (S6.2/S9) | full nonlinear-spring tangent inside the Newton solve | **DONE (in the corotational Newton): FULL tangent `axial_only=False` via the `extra_ft` hook** | **[R]** minor | **DONE 2026-07-12.** The fixed-point NMA path still uses PD axial-only (correct there). |
| G12 ✅ | Salt as a parameter (S7) | q=0.7 e @ 20 mM, 1.5 e @ 100 mM MgCl₂ (λ_D from ionic strength) | **DONE: `mgcl2_M` job param (default 0.02) → `ESParams.for_conditions`, cached per molarity** | **[R]** minor | **DONE 2026-07-11.** |

## Prioritization (by expected effect on the VALIDATED RMSF-vs-MD metric, low risk first)

**Phase A — cheap [R] wins (most likely to improve exp42 correlation, low risk). ✅ DONE 2026-07-11 (see top of file):**
- **G1** sequence-specific stiffness (wire `motif_D` + design sequence) — biggest bang/effort; the sequence
  signal is exactly what MD sees.
- **G6** generalized eigenproblem + mass matrix — changes the 200-mode selection to SNUPI's; also unlocks G8.
- **G12** salt parameter — trivial, lets us match each MD run's actual buffer.

**Phase B — medium [R] (anisotropy the mean washes out). ✅ DONE 2026-07-12 (see top of file):**
- **G3** crossover single/double — DONE, biggest win. Angle correction = no-op (rest geometry, we use NADOC geom).
- **G2** bp-frame registration — DONE, kept ON per user; a wash on RMSF (self-cancels over a turn, as predicted).

**Phase C — new observables (validation depth, no risk to existing numbers). ✅ DONE 2026-07-12 (see top):**
- **G7** BP–BP cross-correlation matrix — DONE (Pearson DCCM + MD comparator); snupi→MD > cando→MD on HC.
- **G8** persistence length from NMA — DONE (bending L_p ≈ 2.6–4.5 µm); torsion + overtone-series deferred.

**Phase D — the big shape solver (high effort/risk, shape-display only). ✅ DONE 2026-07-12 (see top):**
- **G4** corotational element (EICR) → **G5** Newton (+ **G11** full ES tangent). DONE — benchmark-validated,
  opt-in `corotational=True`, 6HB converges ~47 s. Does NOT move the validated RMSF/DCCM (Fine SHAPE only).

**Phase E — situational:**
- **G9** short-ssDNA (only for gapped/linker designs); **G10** canonical initial config (only if exp42 shows
  the 2.25 nm CO spacing matters — otherwise keep NADOC geometry, respect the Three-Layer Law).

Every phase is gated behind `material="snupi"` (CanDo stays byte-identical) and pinned with a mechanical
unit test; re-run `scripts/snupi_cross_compare.py` after each [R] phase to measure the exp42 delta.

## Kickoff prompt for a fresh session

> **Close the SNUPI-mimic gaps toward the full published model (Lee/Kim, ACS Nano 2021).** Read
> `memory/project_snupi_gaps.md` (the gap table + phasing) and `memory/project_snupi_mimic.md` (built
> state, verdict, the S9/full-Newton finding) FIRST. Our FEM already reproduces SNUPI's intrinsic params
> exactly and, with electrostatics, beats CanDo vs MD on both lattices (exp42). Now implement the gaps in
> the documented phase order, **Phase A first**, gated behind `material="snupi"` so the CanDo path stays
> byte-identical:
>
> 1. **G1 — sequence-specific stiffness.** In `assemble_global_stiffness(material="snupi")`, replace
>    `family_mean_D(el.motif_family)` with the per-element sequence 6×6 via the EXISTING
>    `snupi_material.motif_D(family, motif)`, where `motif` is the element's actual dinucleotide from the
>    design sequence (map each beam element → its bp-step sequence; handle unassigned sequence → fall back to
>    family mean). Pin: a test that a sequence-varying helix produces per-element-varying K (not uniform).
> 2. **G6 — generalized eigenproblem + mass matrix (S10).** Assemble a nodal mass matrix M (each bp mass =
>    sum of its two complementary base molar masses / N_A) and switch `compute_rmsf_nma` to the generalized
>    `eigsh(K, M=M, sigma=…)` for `material="snupi"` (keep K-only for cando). RMSF stays the equipartition
>    Σ kBT φ²/λ but over the 200 lowest-FREQUENCY (mass-weighted) modes. Pin: M is SPD, generalized modes
>    finite, cando path unchanged.
> 3. **G12 — salt parameter.** Thread `mgcl2_M` (default 0.02) from the SNUPI job request →
>    `ESParams.for_conditions(mgcl2_M=…)`.
>
> After Phase A, **re-run `scripts/snupi_cross_compare.py`** and record the exp42 delta (does sequence +
> mass-weighted modes improve the SNUPI-vs-MD pearson/spearman on 6hbx100_noT / 3x4SQ?). Then proceed to
> Phase B (**G3** single/double crossovers + angle correction; **G2** bp-frame registration — ASK the user
> before touching bp frames, per the CLAUDE.md DNA-topology rule) and Phase C (**G7** BP–BP correlation
> matrix; **G8** persistence-length from NMA). Defer **Phase D** (G4 full corotational element + G5 Newton +
> G11 full ES tangent) — it's high-risk and only improves the Fine-mode SHAPE, not the validated RMSF metric;
> confirm with the user before starting it. Each gap: a mechanical unit test + `just test-smart` (foundational
> → FULL) + the exp42 re-run for [R] gaps. Three-Layer Law: FEM output is display-only.

## References
- Element/solver: `fem_solver.py` (`assemble_global_stiffness`, `compute_rmsf_nma`, `_solve_snupi_nonlinear`,
  `_snupi_element_stiffness`). Material: `snupi_material.py` (`motif_D`, `family_mean_D`).
  Electrostatics: `snupi_electrostatics.py`. Params: `snupi_params.json`.
- Validation harness: `scripts/snupi_cross_compare.py` → `experiments/exp42_snupi_cross_compare/`.
- SI map: S1/S2 element, S3 BP step (+3.2 sequence, +3.3 triad/frame), S4 crossover, S5 ssDNA, S6/S7
  electrostatics, S8 initial config, S9 nonlinear solve (+9.6 Newton–Raphson), S10 NMA (+mass matrix),
  S11 RMSF+correlation matrices, S12 persistence length, S13 analytic L_p scaling, S14 MD, S15 rendering.
- Related: [[snupi-mimic]], [[project_cando_fem]], [[snupi-frontend-tab]].
