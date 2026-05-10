# Exp21 — OpenMM GBNeck2 Verification Baseline

**System:** Two designs:
1. Single 42 bp B-DNA duplex helix along +Z (no crossovers, minimal complexity)
2. 6-helix bundle (6HB) honeycomb design, 42 bp (real multi-helix system)

**Force field:** AMBER14+OL15+GBNeck2 (igb=8), 150 mM NaCl implicit solvent, 300 K  
**Protocol:** 500-step steepest-descent minimisation, then NVT Langevin MD at 2 fs/step;
drift measured as time-averaged C1' RMSD vs NADOC geometric prediction over the last 50%
of frames. NVT durations tested: 2 ps (1 000 steps), 10 ps (5 000 steps), 50 ps (25 000 steps).

---

## Hypothesis

After 10 ps of implicit-solvent MD (the production default), NADOC's B-DNA geometric
construction produces C1' positions with:

| Metric | Predicted value |
|--------|----------------|
| Single helix global RMSD | < 0.15 nm (thermal motion at 300 K, no structural drift) |
| Single helix max deviation | < 0.3 nm (worst-case single nucleotide) |
| 6HB global RMSD | < 0.3 nm (more degrees of freedom, still near energy min) |
| 6HB max deviation | < 0.5 nm (pass threshold) |
| 6HB inter-helix COM drift | < 0.2 nm (without explicit Mg²⁺, expect slight overestimate) |

Both designs should **pass** the built-in threshold (max_deviation < 0.5 nm AND
global_rmsd < 0.3 nm) at 10 ps.

At 50 ps we expect slightly higher drift (longer time for thermal exploration) but
still within threshold for the single helix. For 6HB, the implicit-solvent Mg²⁺
limitation may cause inter-helix COM drift > 0.2 nm at 50 ps.

---

## Rationale

This is the **first quantitative validation** of NADOC's geometric construction against
an atomistic energy landscape. The three-layer architecture assumes that the geometric
layer (derived from B-DNA constants) is close to the AMBER14+OL15 energy minimum. This
experiment tests that assumption directly.

The single helix (no crossovers, no multi-helix interactions) is the simplest possible
test and should show minimal drift — mostly B-DNA bending flexibility at 300 K. If drift
is large for a single helix, the AMBER14 atom name conversion or template matching is wrong.

The 6HB tests whether crossover geometry and multi-helix packing also pass. The known
limitation is the absence of explicit Mg²⁺: in reality, divalent cations neutralise
inter-helix phosphate repulsion. Without them, GBNeck2 may overestimate inter-helix
distances. The `inter_helix_com_drift_nm` field in `VerificationResult` quantifies this.

---

## Known limitations

- No explicit Mg²⁺ ions (implicit solvent omits divalent cations).
  Expected systematic effect: inter-helix distances overestimated by ~0.2–0.3 nm.
- 5'-terminal residues lose P/OP1/OP2 in AMBER14 conversion. This introduces a
  slight force-field boundary effect at strand termini.
- 42 bp designs are short enough that end-fraying can contribute to max_deviation
  even when the bulk structure is stable.

---

## Expected outcome

- Single helix: `passed = True` at all NVT durations tested.
- 6HB: `passed = True` at 2 and 10 ps; may fail at 50 ps due to implicit-Mg²⁺ drift.
- `inter_helix_com_drift_nm` values for 6HB at 10 ps: < 0.2 nm each.
