# The gaps (SNUPI SI ⟶ ours) — supporting detail

[Topic head](../../project_snupi_gaps.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
| G9 ✅ | Short-ssDNA model (S5) | equilibrated end-to-end distance for SHORT ssDNA (gaps) + nonlinear FJC/WLC | **CLOSED 2026-07-13** — `snupi_material.ssdna_element`, MEASURED from the SNUPI binary's `PROP` array (n = 1…24), one isotropic EB beam per bridging run | done | See [[project_snupi_ssdna]] SS-1. Extra-base crossovers now use the `extra_base_co` motif (SHIPPED 2026-07-19: MD-derived compliant CO-beam replacing the old spring) — see [[snupi-mimic]] STATUS. |
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
- ~~**G9** short-ssDNA~~ — **CLOSED 2026-07-13** by SS-1 ([[project_snupi_ssdna]]). Not situational after all:
  it also fixed two real structural bugs (rigid beams through vacuum; 33 of VoltronCore's 35 ssDNA hops
  entirely uncoupled). exp42 flat (≤0.004), cando byte-identical.
- **G10** canonical initial config (only if exp42 shows the 2.25 nm CO spacing matters — otherwise keep
  NADOC geometry, respect the Three-Layer Law).

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
