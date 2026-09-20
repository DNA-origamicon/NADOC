# Portable scientific integration fixtures

Current test policy (2026-09-20): normal commands validate software only. Production,
equilibrium sampling and physical convergence campaigns require explicit
`just test-scientific TARGET`; see [inventory](scientific_validation.md).
Historical full-run commands/results below predate this split; the legacy
`NADOC_RUN_OXDNA_SLOW` flag no longer enables campaigns.

The full suite runs only inside a user-opened `just test-session`. The current maintenance
run excludes CPD/photoproduct work, which is being validated on the other computer:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  PYTEST_XDIST_AUTO_NUM_WORKERS=1 NADOC_RUN_OXDNA_SLOW=1 NADOC_TEST_CONFIRM=1 \
  PYTEST_ADDOPTS="--ignore-glob=tests/test_photoproduct* --ignore-glob=tests/test_cpd* --ignore=tests/test_local_qm_fragment_campaign.py -k 'not cpd and not photoproduct' -ra" \
  just test-smart
```

One xdist worker serializes native GROMACS jobs. One numerical thread per worker
avoids nested BLAS oversubscription; this does not
change test selection, tolerances, or the repository's time budgets.

## Generated inputs

- `tests/periodic_assembly_fixture.py`: headless routing, autostapling, sequence assignment,
  and three-copy polymerization from committed bundle cell/length recipes. Tests verify
  nucleotide/strand conservation, seam families, FEM connectivity, and atomistic piercing.
- `tests/md_trajectory_fixture.py`: real CHARMM/psfgen topology, native GROMACS package
  preparation/minimization, real solvation/ionization, and controlled DCD/XTC frames. The
  many-strand fixture crosses the 62-character PDB-chain limit; the large fixture retains
  the 18HB × 200 bp display workload. Generated motion tests coordinate readers, periodic
  imaging, alignment, mapping, RMSF plumbing, and websocket readiness. It is not dynamics,
  diffusion, equilibrium, or a force-field validation result.
- `tests/peg_protocol_fixture.py`: small PSF/PDB plus explicitly constructed restart epochs,
  DCD frames, and energy logs. Tests exercise real restart pairing, safety verdicts, mass
  repartitioning, and sealed-input validation. Native-looking completion strings are test
  input, not a claim that NAMD executed or that this synthetic molecule is simulation-ready.

All generated files live in pytest temporary directories. These replacement fixtures require no
user job ID, archive mount, or pre-existing `/tmp` file. Historical SNUPI census and manual-hinge
regressions still await their original design inputs; they must not be reported as covered by an
arbitrary generated replacement. The maintenance report tracks those remaining gaps.

## Immutable references

`8scp.pdb.gz` preserves the public RCSB structure used by the conjugation census/performance
regression. Its provenance file records the source URL and decompressed SHA-256.
`voltroncore_surface_input.json.gz` preserves the exact original input for the locked surface
regression; its provenance file records its hash. Neither the geometry nor its baseline
values were regenerated. These inputs cannot be replaced with arbitrary synthetic structures
without losing the original structural/performance oracle.

## Native dependencies

Native tests need their actual engines/toolchains: GROMACS, NAMD/psfgen,
oxDNA/oxpy, mrDNA/ARBD, and a Tcl interpreter/SDK where applicable. Missing-engine
skips remain distinguishable from generated-input validation; an installed engine
does not imply its test passed.

CPD/photoproduct tests and edits are excluded from this maintenance pass at the
user's request; that validation is running on another computer.
