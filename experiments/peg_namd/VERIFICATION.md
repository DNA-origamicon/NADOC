# Infrastructure verification — 2026-09-10

- `bash scripts/test_guard.sh peg-namd-unit 0 0 -- .venv/bin/python -m pytest tests/test_peg_namd.py -q`: **17 passed**, 0.34 seconds test execution. No native simulations are invoked by these tests.
- `.venv/bin/ruff check experiments/peg_namd tests/test_peg_namd.py`: all checks passed.
- Python compilation and Slurm entry-point Bash syntax checks passed.
- Real VMD/psfgen/solvate/autoionize execution on a **nonphysical software fixture**:
  `workspace/peg_namd/software_fixture_v2_20260910/package`.
  Completed with 6,560 atoms, 2,185 water molecules, one harmonic graft mask,
  two fixed-site masks and zero total charge. `verify_inputs.py --seal` and the
  subsequent hash verification both passed. No NAMD force evaluation or dynamics
  was run on this synthetic fixture. It cannot support any physical conclusion.
- The first fixture exposed an invalid VMD `P*` selection. The renderer now emits
  explicit chain segment identifiers; the second end-to-end fixture passed.
- Default physical plan generated at `workspace/peg_namd/brush_plan_v1`:
  27 cases / 540 ns pilot allocation. `--check-assets` correctly reports missing
  chain/slab chemistry and compatibility evidence. Missing assets create no
  partially staged physical package.

Tests cover achieved density, unit conversion, reproducible site generation,
invalid inputs, rigid-coordinate transformations, preservation of PSF interaction
sections and charges, atom-identity checks, overlong conformers, missing assets,
no-overwrite behavior, NAMD timestep/restart rendering, provenance, mask ordering,
and detection of modified built inputs.

Outstanding physical checks are explicit in README/GAPS: actual parameter and
GPU-feature coverage, solvated periodic-image contacts, density/electrolyte
conditions, PEG and surface validation, and convergence. No live oxDNA validation
process, scheduler lease, production force-field file or unrelated QM campaign
was changed.
