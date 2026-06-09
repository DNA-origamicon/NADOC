---
id: H002
title: fullElectFrequency 1 removes MTS resonance artifacts from backbone torsions
status: pending
date_opened: 2026-05-10
literature:
  - "Batcho & Schlick (2001) JCP 115:4003 — MTS resonance for nucleic acids begins at outer step >= 4 fs"
  - "Shan et al. (2005) JCTC 1:1096 — resonance artifact in PME MTS; DNA phosphate charges most affected"
  - "Pan et al. (2014) JCTC 10:2906 — uses fullElectFrequency 1 for DNA origami"
parameter_change:
  key: fullElectFrequency
  from: 2
  to: 1
baseline_run: ramp_v2_03
test_duration_ns: 2.0
---

## Hypothesis

With `fullElectFrequency 2` (outer PME timestep 4 fs), multiple-time-step resonance
systematically distorts DNA backbone torsion angle dynamics. Changing to
`fullElectFrequency 1` will produce backbone torsion autocorrelation functions consistent
with published CHARMM36 DNA simulations, without affecting energy stability or pairing.

This is a **dynamics quality** hypothesis, not a stability one. The simulation may be
energetically stable with `fullElectFrequency 2` while still producing wrong torsion
distributions.

## Mechanism

NAMD's MTS scheme evaluates short-range nonbonded forces every `nonbondedFreq` steps and
full PME electrostatics every `fullElectFrequency` steps. With `fullElectFrequency 2` and
timestep 2 fs, the outer step is 4 fs. Batcho & Schlick (2001) showed that outer steps
≥ 4 fs create resonance artifacts in nucleic acids because the phosphate backbone charges
(partial charges −0.5 to −1.0 e per atom) experience strongly correlated long-range
Coulomb forces that are updated too infrequently to track rapid torsional motion (α, β,
γ, δ, ε, ζ dihedral periods ~ 0.3–2 ps). The artifact is subtle: energies remain stable
but torsion distributions are shifted relative to single-step integration.

## Method

1. Copy `ramp_v2_03.conf`, change `fullElectFrequency 2` → `fullElectFrequency 1`,
   and increase `stepspercycle` from `10` to `20` (neighbour list covers 2 outer steps).
2. Run 1,000,000 steps (2 ns) NVT from `ramp_v2_03` restart, velocity continuation.
   Output: `output/H002_fullElect_1.dcd` + `.log`.
3. Run `metrics_extract.py` — compare ns_per_day, temperature, pressure.
4. Run `base_pairing.py` for pairing fraction.
5. Compare ε/ζ torsion distribution vs H001 (or baseline) using `scripts/torsion_compare.py`
   if written; otherwise report ns_per_day + pairing as preliminary result.

## Expected Outcome

- `ns_per_day` decreases ~10–15% relative to baseline (electrostatics dominates large-system cost)
- `bp_fraction_final` unchanged relative to H001 (pairing is not affected by MTS)
- Torsion distributions tighter / closer to CHARMM36 reference: confirms hypothesis
- If ns_per_day drop > 25% and dynamics identical: insufficient benefit, keep `fullElectFrequency 2`

---

## Result

*(Fill after run.)*

## Conclusion

*(Adopt / Reject / Needs more data.)*
