---
id: H001
title: rigidBonds all eliminates N-H/C-H resonance and fixes C1' pairing loss
status: complete
date_opened: 2026-05-10
date_closed: 2026-05-10
literature:
  - "Pan et al. (2014) JCTC 10:2906 — NAMD/CHARMM36 DNA origami; uses rigidBonds all at 2 fs"
  - "Yoo & Aksimentiev (2016) PNAS 113:4954 — membrane DNA channels; rigidBonds all"
  - "Galindo-Murillo et al. (2016) JCTC 12:4114 — CHARMM36 DNA assessment; rigidBonds all 2 fs"
parameter_change:
  key: rigidBonds
  from: water
  to: all
baseline_run: ramp_v2_03
test_duration_ns: 0.5
---

## Hypothesis

Changing `rigidBonds water` to `rigidBonds all` will raise the final C1'–C1' base-pair
fraction from the 47.8% observed in the previous 10 ps unrestrained smoke test to > 90%
after 500 ps of unrestrained NVT from the same `ramp_v2_03` restart.

## Mechanism

With `rigidBonds water`, only O–H bonds in TIP3P water are constrained. All hydrogen
bonds in the DNA — N–H (ω ≈ 3300 cm⁻¹, T ≈ 10 fs) and C–H (ω ≈ 2950 cm⁻¹, T ≈ 11 fs)
in bases and sugar — are integrated with a 2 fs timestep, which is below the half-period
of these oscillations. The Verlet integrator accumulates phase error quadratically in
these fast modes; this manifests as local energy injection into the bases (not the
backbone, which is constrained via water-rigidBonds + PME forces). The result is
transient C1' displacement beyond the 12 Å threshold without actual strand separation —
consistent with stable total energy in the 50 ns production run alongside a poor smoke
pairing fraction.

`rigidBonds all` constrains every bond involving a hydrogen atom (SHAKE on H-bonds),
removing the fast oscillatory DOF entirely. This is standard for 2 fs CHARMM36 DNA MD
as documented in all three cited papers.

## Method

1. Copy `ramp_v2_03.conf`, change `rigidBonds water` → `rigidBonds all`.
2. Run 250,000 steps (500 ps) NVT from `ramp_v2_03` restart, no constraints, no minimize,
   velocity continuation. Output: `output/H001_rigidBonds_all.dcd` + `.log` + `.xst`.
3. Run `metrics_extract.py --log ... --xst ... --id H001 --out metrics/H001_metrics.json`.
4. Run `base_pairing.py --dcd output/H001_rigidBonds_all.dcd --out metrics/H001_bp.json`.

## Expected Outcome

- `bp_fraction_final` ≥ 0.90 (vs 0.478 baseline): **confirms hypothesis**
- `temperature.max` < 350 K: should never approach DNA Tm
- `fatal_errors` = []
- `ns_per_day` ≥ 18 (< 5% penalty from SHAKE on DNA H-bonds vs water-only)

If `bp_fraction_final` < 0.75: `rigidBonds all` is not the primary cause; proceed to H004/H005.

---

## Result

Run: 500 ps (250,000 steps) unrestrained NVT from `ramp_v2_03` restart, locked Z = 70.14 Å.

| Metric              | Value        | Target        |
|---------------------|-------------|---------------|
| bp_fraction_final   | **0.323**   | ≥ 0.90        |
| temperature.mean    | 309.47 K    | 308–312 K ✓   |
| temperature.max     | 311.40 K    | < 350 K ✓     |
| pressure.mean       | **−124.9 bar** | ≈ 0 bar    |
| ns_per_day          | 23.78       | ≥ 18 ✓        |
| fatal_errors        | []          | [] ✓          |
| mean C1'–C1' final  | 13.74 Å     | < 12 Å        |
| p90 C1'–C1' final   | 19.06 Å     |               |

DNA pairing worsened relative to the 47.8% baseline (32.3% final). Temperature is
well-controlled (no overheat). The −124.9 bar mean pressure is the diagnostic: the system
under NVT at Z = 70.14 Å is under significant axial tension (it wants to contract to the
NPT equilibrium ~67.8 Å). This tension is pulling base pairs apart throughout the run.

`rigidBonds all` alone is **not** the primary cause of pairing loss in this locked-Z setup.

## Conclusion

**REJECT hypothesis as framed.** `rigidBonds all` is correct and should be kept (literature
standard, zero performance penalty), but it cannot fix pairing loss caused by Z-lock
tension. The −124.9 bar pressure directly implicates H004 (accept NPT equilibrium Z ≈ 67.8 Å)
as the primary variable. H004 must be run before H001 can be revisited in a relaxed box.
