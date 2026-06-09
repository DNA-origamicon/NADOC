---
id: H007
title: Full pipeline redo with rigidBonds all throughout — clean starting structure
status: pending
date_opened: 2026-05-10
literature:
  - "Pan et al. (2014) JCTC 10:2906 — rigidBonds all throughout, including equilibration"
  - "Galindo-Murillo et al. (2016) JCTC 12:4114 — CHARMM36 DNA at 2 fs; rigidBonds all mandatory"
  - "Yoo & Aksimentiev (2016) PNAS 113:4954 — membrane DNA channels; all equilibration stages use rigidBonds all"
parameter_change:
  key: rigidBonds (all stages: equilibrate_npt + ramp_v2_00–03 + production)
  from: water (all current ramp confs)
  to: all
baseline_run: initial_minimized_pdb  # restart from the PSF/PDB before any MD
test_duration_ns: 2.0
---

## Hypothesis

Redoing the entire equilibration and ramp pipeline with `rigidBonds all` from the initial
minimized PDB (before any MD) will produce a starting structure with > 90% C1'–C1' pairing
after the ramp, and that structure will remain > 90% paired in subsequent unrestrained NVT
or isotropic NPT production.

## Mechanism

`rigidBonds water` was used throughout ALL ramp stages (ramp_v2_00 through ramp_v2_03).
Over 4 × ~100 ps = 400 ps of restrained NVT, the N-H and C-H bonds in DNA bases vibrated
below the half-period threshold (C-H T ≈ 11 fs, N-H T ≈ 10 fs << 2 fs timestep half-period
= 1 fs). This accumulated local energy in the bases, progressively displacing C1' atoms
beyond 12 Å without separating strands — but by the end of ramp_v2_03, 44% of base pairs
were already open.

Once the production phase starts from this damaged structure, the damage cannot self-repair
in either NVT (H001: 56% → 32% in 500 ps) or NPT (production_iso_npt: 56% → 14.5% in 17.8 ns).

`rigidBonds all` removes the vibrational degree of freedom entirely. Starting from the
initial PDB (C1'–C1' = 9.67 Å for all 504 pairs) and applying rigidBonds all throughout
should preserve the starting geometry through the ramp.

## Evidence supporting this hypothesis

- Initial PDB: all 504 C1'–C1' pairs at exactly 9.67 Å (100% paired)
- ramp_v2_03 starting structure: 56% paired, mean 11.62 Å — damaged during ramp
- H001 (rigidBonds all, 500 ps, from ramp_v2_03): 32.3% final — cannot repair damage
- production_iso_npt (rigidBonds water, 17.8 ns, from ramp_v2_03): 14.5% final — worsening
- Total energy stable (−652 kcal/mol) throughout production_iso_npt — structural rearrangement,
  not melting to single strands; helix-helix XY separation is the likely mechanism

## Method

1. Start from the existing PSF/PDB (initial model, pre-ramp) which has perfect pairing.
2. Check that `namd_solvate.py` has `rigidBonds all` (done: fixed 2026-05-10).
3. Re-generate the equilibrate_npt.conf with `rigidBonds all` and run 1 ns restrained
   anisotropic NPT.
4. Run lock_box_from_xst.py on the new NPT XST to get stable XY; restore Z = 70.14 Å.
5. Re-run relax_locked_nvt.conf (restrained NVT, rigidBonds all) → ramp_v2_00–03 (rigidBonds all).
6. From the new ramp_v2_03 restart, run 500 ps unrestrained NVT (rigidBonds all, locked-Z).
7. Run base_pairing.py on the result DCD.

Key metric: C1'–C1' pairing fraction at frame 0 of production (after ramp). If > 90%, the
starting structure is clean. If still < 80%, the ramp itself is insufficient.

## Expected Outcome

- ramp_v2_03 new: > 90% C1'–C1' pairing at frame 0 of production
- 500 ps unrestrained NVT (H001-style): > 90% pairing maintained
- If < 70% at ramp completion: need longer ramp or lower final restraint scaling

## Notes

- The existing `ramp_locked_nvt_00–03.conf` files in the run directory use `rigidBonds water`.
  They must be regenerated or manually patched to `rigidBonds all`.
- The `namd_solvate.py::_periodic_cell_header()` now generates `rigidBonds all` by default.
  Next `build_periodic_cell_package()` call will produce correct confs.
- The ramp conf files on disk need to be updated manually or by running the package builder.
- Do NOT use the existing `ramp_v2_03.restart.coor` for this test — it is the damaged structure.
- This test blocks H003, H004, H006 which are meaningless on the damaged structure.

---

## Result

*(Fill after run.)*

## Conclusion

*(Adopt / Reject / Needs more data.)*
*(Critical: if H007 succeeds, update all downstream conf templates to rigidBonds all and
discard all results from runs using rigidBonds water as their primary scientific data.)*
