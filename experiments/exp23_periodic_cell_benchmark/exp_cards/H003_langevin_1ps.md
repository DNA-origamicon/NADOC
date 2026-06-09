---
id: H003
title: langevinDamping 1 ps⁻¹ for production preserves DNA torsional dynamics
status: pending
date_opened: 2026-05-10
literature:
  - "Pan et al. (2014) JCTC 10:2906 — langevin damping 1 ps⁻¹ for DNA origami production"
  - "Yoo & Aksimentiev (2016) PNAS 113:4954 — Langevin damping 1 ps⁻¹"
  - "Dans et al. (2016) PLoS Comput. Biol. 12:e1004974 — DNA backbone torsion autocorrelations 0.1–1 ns"
parameter_change:
  key: langevinDamping
  from: 5
  to: 1
baseline_run: ramp_v2_03
test_duration_ns: 2.0
---

## Hypothesis

At `langevinDamping 5 ps⁻¹`, the Langevin friction damps DNA backbone torsional motion
with a relaxation time of 1/5 = 200 ps. Since backbone dihedral autocorrelation times
are 0.1–1 ns (Dans et al. 2016), the thermostat artificially shortens these by up to 5×,
causing non-physical distributions in twist, writhe, and groove-width fluctuations.
Reducing to 1 ps⁻¹ will produce physically correct torsional dynamics while maintaining
thermal stability.

## Mechanism

The Langevin equation adds a friction force −γ × m × v to each atom. For γ = 5 ps⁻¹,
the velocity autocorrelation decays with e-folding time 1/γ = 200 ps. DNA backbone
torsion angles couple to atom velocities; when γ >> 1/τ_torsion, the thermostat
artificially overdamps the torsional fluctuations. For twist (τ ~ 0.5–1 ns) and writhe
(τ ~ 0.2–0.5 ns), γ = 5 ps⁻¹ suppresses fluctuations to ~10% of their physical amplitude.
This does not prevent simulations from being stable or useful for structural equilibration,
but it invalidates studies of DNA mechanical properties or kinetics.

Note: γ = 5 ps⁻¹ is appropriate for NPT box discovery (fast response to pressure changes)
but should be reduced for production.

## Method

1. Copy `production_iso_npt.conf` (or `ramp_v2_03`), change `langevinDamping 5` → `1`.
2. Run 1,000,000 steps (2 ns) from `ramp_v2_03` restart, velocity continuation.
3. `metrics_extract.py` — temperature stability is the key check: does T drift or spike
   with weaker thermostat coupling?
4. `base_pairing.py` for pairing fraction.

## Expected Outcome

- Temperature mean stays 308–312 K (confirm thermostat still adequate)
- Temperature std slightly larger (expected: less damping = more fluctuation)
- `bp_fraction_final` unchanged (pairing does not depend on thermostat strength)
- ns_per_day unchanged (damping is not performance-critical)
- If temperature becomes unstable (max > 330 K): γ = 1 ps⁻¹ insufficient; try 2 ps⁻¹

---

## Result

*(Fill after run.)*

## Conclusion

*(Adopt / Reject / Needs more data.)*
