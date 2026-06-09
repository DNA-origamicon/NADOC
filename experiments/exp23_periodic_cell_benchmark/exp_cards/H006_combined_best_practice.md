---
id: H006
title: Combined best practice (rigidBonds all + langevinDamping 1) for production
status: pending
date_opened: 2026-05-10
literature:
  - "Pan et al. (2014) JCTC 10:2906 — DNA origami: rigidBonds all, damping 1 ps⁻¹"
  - "Yoo & Aksimentiev (2016) PNAS 113:4954 — same parameter set validated for channel DNA"
parameter_change:
  key: rigidBonds + langevinDamping
  from: rigidBonds water; langevinDamping 5
  to: rigidBonds all; langevinDamping 1
baseline_run: ramp_v2_03
test_duration_ns: 2.0
---

## Hypothesis

The combined change of `rigidBonds all` + `langevinDamping 1` will produce a production
configuration that (a) achieves > 90% C1'–C1' pairing fraction and (b) produces
physically correct torsional dynamics. This is the parameter set recommended by the
primary DNA origami MD literature and should become the new default for all generated
NAMD configs.

**Prerequisite:** Run after H001 and H003 are complete. If either is rejected, revise
this card before running H006.

## Method

1. Copy `production_iso_npt.conf`, apply both changes.
2. Run 1,000,000 steps (2 ns) from `ramp_v2_03` restart.
3. `metrics_extract.py` + `base_pairing.py` → `metrics/H006_metrics.json` + `H006_bp.json`.
4. Compare: ns_per_day vs baseline, pairing fraction vs H001 alone.

## Expected Outcome

- `bp_fraction_final` ≥ 0.90
- `temperature.max` < 340 K  
- ns_per_day ≥ 16 (< 30% penalty from combined changes)
- Confirms that both changes are compatible and sufficient for production

If ns_per_day drops > 30%: profile whether SHAKE (`rigidBonds all`) or damping
is responsible; may need to accept one change only.

---

## Result

*(Fill after run.)*

## Conclusion

*(If confirmed: update `namd_solvate.py` defaults. Record the accepted protocol in
`periodic_md.md`.)*
