# ✅ Phase A DONE (2026-07-11) — G1 + G6 + G12, gated behind `material="snupi"` — supporting detail

[Topic head](../../project_snupi_gaps.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
  - **DETERMINISM (2026-07-24): every `eigsh` in `fem_solver.py` now passes a FIXED `v0=_eigsh_v0(n)`**
    (seeded `default_rng(0)` normal draw). Was flaky: no `v0` → ARPACK drew its Lanczos start from
    numpy's global RNG, so identical K gave different eigenvectors inside near-degenerate soft-mode
    subspaces, and RMSF/DCCM/L_p (=Σ φ²/λ over the softest modes) jittered ~1e-2 nm run-to-run.
    `test_g12_salt_ignored_by_cando` failed intermittently (cando cross-salt drift 0.0137 > 0.01 bound);
    now cando drift is exactly 0.0. Don't remove `v0` — it makes the whole NMA family reproducible.
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
