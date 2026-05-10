# Periodic MD Memory

## Scope

Periodic MD is the explicit-solvent, axial-PBC workflow for reducing DNA origami
simulation cost by simulating one or more honeycomb crossover-repeat periods
instead of the full design. The main implementation is:

- `backend/core/periodic_cell.py` — slices the design, builds the atomistic
  model, adds wrap bonds, solvates, places ions, and emits a NAMD package.
- `backend/core/namd_solvate.py` — provides periodic GROMACS solvation and
  renders the periodic NAMD configuration.
- `frontend/src/ui/periodic_md_panel.js` and
  `frontend/src/scene/periodic_md_overlay.js` — load PSF/PDB/DCD output,
  preview the periodic cell, and tile frames onto periodic 21 bp windows.
- `frontend/src/scene/md_segmentation_overlay.js` — classifies 21 bp windows as
  `periodic`, `deviant`, or `end` based on crossover-count agreement with the
  modal interior window.
- `experiments/exp23_periodic_cell_benchmark/` — current B_tube benchmark and
  health-monitor scripts.

## Current Pipeline Facts

- Honeycomb period: `HC_CROSSOVER_PERIOD = 21`; one-period axial cell length is
  `21 * BDNA_RISE_PER_BP = 7.014 nm`.
- `_detect_periodic_start()` chooses the first 21 bp-aligned bulk window at
  least one period away from both global ends. For B_tube, the benchmark summary
  records bp range `[21, 42)`.
- `_slice_to_bp_range()` clips helices/strands/crossovers to the chosen window
  and clears heavier UI/physical state such as deformations, clusters,
  overhangs, feature logs, and animations.
- `assign_consensus_sequence()` assigns the sliced cell by majority vote across
  full-design periods. Forward bases vote directly; reverse bases are forced to
  Watson-Crick complements of the forward consensus. Uncovered positions fall
  back to A/T.
- `_build_wrap_bonds()` adds O3' to P bonds only when both ends are free. The
  B_tube one-period package currently reports 4 wrap bonds, not 48, because
  most boundary O3'/P pairs are already connected by crossover backbone bonds.
- `_apply_wrap_bond_geometry()` uses an image trick: shift the destination
  nucleotide by one axial period along the helix axis, minimize the local
  O3'/P/O5' bridge, then shift it back so minimum-image geometry is canonical.
- `_gmx_solvate_periodic()` computes XY from the dry PDB bounding box plus
  padding and forces GROMACS `editconf -box` Z to the exact periodic length.
- The rendered NAMD config uses `wrapNearest on` because DNA is bonded across
  the periodic boundary.
- GPU-resident NAMD is slower than standard CUDA for the current wrap-bond cell
  on the tested RTX 2080 SUPER. Both modes log low global CUDA exclusion counts
  during minimization, which NAMD labels as not unusual during minimization; both
  completed 5,000-step MD benchmark phases without fatal exclusion errors.

## Pressure And Box-State Notes

There is an unresolved mismatch between generator code, generated artifacts, and
the active experiment:

- `backend/core/namd_solvate.py::_render_periodic_namd_conf()` still renders a
  semiisotropic NPT config with `useFlexibleCell yes` and `useConstantArea yes`,
  and its comments claim this makes XY flexible while Z is fixed.
- The generated experiment config at
  `experiments/exp23_periodic_cell_benchmark/results/periodic_cell_run/namd.conf`
  has been manually changed to fixed-box NVT. Its comments state that
  `useConstantArea` locked XY and allowed Z to shrink from `70.14 Å` to
  `65.4 Å`, compressing helical rise by about `6.7%` and disrupting the double
  helix within about `10 ps`.
- The benchmark summary still says "semiisotropic NPT (XY breathes, Z fixed)",
  so result docs and current run config disagree.
- The user intent as of 2026-05-08 is to lock Z after running an NPT preliminary
  run. The exact desired production protocol is not yet captured in code or
  memory.

Decision update from 2026-05-08:

- No strong preference for NPT-vs-NVT production yet; choose the protocol that
  keeps DNA intact, then tune from there.
- Use a restrained preliminary NPT phase to discover the box, then derive X/Y
  from the stable tail average rather than the final instantaneous frame.
- Keep phases in separate NAMD config files rather than one large config.
- Expect restraints to be needed at first because unrestrained starts can blow
  up immediately. After restraints are removed, origami breathing is expected
  and should be evaluated rather than suppressed by default.
- Try to make NAMD GPU-resident mode work, but trust it only after benchmarking
  against standard CUDA and checking that it does not produce exclusion/error
  warnings.

Implementation update from 2026-05-08:

- The generated periodic package now emits `equilibrate_npt.conf`,
  `production_locked_nvt.template.conf`, `benchmark_standard_cuda.conf`, and
  `benchmark_gpu_resident.conf`; `namd.conf` remains an alias of the NPT phase
  for compatibility.
- The package includes `{name}_restraints.pdb` with DNA heavy atoms restrained
  through the B-factor column and water/ions unrestrained.
- `scripts/lock_box_from_xst.py` reads an NPT `.xst`, averages the stable tail
  X/Y vectors, patches the production template, and restores exact Z.
- The NPT-to-locked-NVT handoff intentionally restarts from coordinates and
  not the NPT `.xsc`, because that can override the patched cell vectors and
  lose the exact-Z lock.
- As of the B_tube smoke test on 2026-05-08, do not carry NPT velocities into
  the Z-restored production cell. The stable handoff is:
  `binCoordinates` from restrained NPT restart, patch X/Y from stable-tail XST,
  preserve XST origin, restore exact Z, minimize in the locked cell, then
  `reinitvels 310` and run NVT.
- The generated package now separates the locked fixed-cell phase into
  `relax_locked_nvt.template.conf` (DNA heavy-atom restraints retained) and
  `production_locked_nvt.template.conf` (unrestrained, restarting from the
  locked relaxation phase).
- Implementation checkpoint: the package also emits four default ramp templates,
  `ramp_locked_nvt_00.template.conf` through `ramp_locked_nvt_03.template.conf`,
  with restraint scalings `0.5`, `0.25`, `0.10`, and `0.03`. The production
  template restarts from `ramp_locked_nvt_03`.
- `experiments/exp23_periodic_cell_benchmark/run.py --ramp-smoke` runs a short
  automated NPT -> locked relaxation -> ramp -> production workflow and writes
  `experiments/exp23_periodic_cell_benchmark/results/periodic_md_ramp_smoke_summary.json`.
  A very short local smoke (`1000/1000/500/1000` steps) completed all stages
  with zero NAMD exits, no sentinel energies, and locked `Z = 70.140 Å`; the
  NPT temperature warning is retained as a warning rather than a fatal smoke
  failure because the NPT phase was intentionally too short to equilibrate.
- `scripts/lock_box_from_xst.py` writes a `*.conf.lock.json` sidecar recording
  XST source, tail-frame count, patched X/Y/Z, preserved origin, and source
  tail mean Z.
- Failure mode found on `B_tube.nadoc`: direct fixed-NVT continuation at the NPT
  final box (`Z ~= 67.235 Å`) is healthy, but expanding straight to exact
  `Z = 70.140 Å` without locked-cell minimization produces NAMD sentinel
  energies (`-99999999999.9999`) within about 10 steps. A 5,000-step smoke run
  with locked-cell minimization completed with finite energies and fixed
  `Z = 70.140 Å`.
- The 5,000-step locked restrained smoke run completed with finite energies,
  fixed `Z = 70.140 Å`, and the current C1' distance monitor reported `95.8%`
  pairing in the single DCD frame. The analogous unrestrained 5,000-step smoke
  was energy-stable but the same monitor reported `47.8%` pairing, so restraint
  release needs more careful ramping/validation before calling it physically
  production-ready.
- `scripts/lock_box_from_xst.py` should preserve the averaged XST origin rather
  than recomputing origin as half the patched box. Recomputing the origin did
  not by itself cause the sentinel-energy failure, but it is the wrong frame for
  restart coordinates.
- The four wrap bonds are about `69-71 Å` apart in real coordinates. Attempting
  to solve this only by increasing GPUresident pairlist is not viable:
  `32 Å` hit a CUDA shared-memory patch limit and `80 Å` hit out-of-memory on
  the 8 GB RTX 2080 SUPER. A normal `16 Å` pairlist with 500 minimization steps
  did complete MD, but did not speed up the run.
- A local 5,000-step standard-vs-GPU benchmark on 2026-05-08 found:
  standard CUDA `22.66 ns/day`; GPUresident `15.40 ns/day`. Hardware was
  verified as AMD Ryzen 9 9950X + RTX 2080 SUPER, driver `580.142`, CUDA `13.0`
  reported by `nvidia-smi`, NAMD 3.0.2 CUDA build.

## Things That Were Unclear From Context

- Whether the current restrained NPT -> averaged-X/Y -> locked-Z NVT sequence is
  sufficient, or whether a true pressure-controlled locked-Z production ensemble
  is still needed later.
- Which NAMD settings are known-correct for "XY flexible, Z locked". The current
  use of `useConstantArea yes` appears contradicted by the experiment comment.
- Whether the NPT restraint strength and release schedule should remain
  `k=1 kcal/mol/Å² for 500 ps`, ramp down gradually, or be user-tunable.
- Whether water/ion count should be rebuilt after the NPT-derived XY box is
  chosen, or whether positions should simply be continued from the equilibrated
  NPT restart.
- Whether 21 bp periodic-cell generation should be rejected for non-honeycomb
  designs, designs with loop/skip changes inside the selected window, or windows
  with non-modal crossover counts.
- Whether a different topology representation, such as duplicated/image atoms
  for boundary bonded exclusions, is worth exploring. A simple pairlist tuning
  approach does not make NAMD GPUresident faster for the current wrap-bond cell.

## Desired Future Memory Entries

When this workflow is resolved, capture:

- The exact NAMD protocol for preliminary pressure equilibration and locked-Z
  production, including every relevant cell-control setting.
- A small table of tested bad protocols and observed failure modes, especially
  the `useConstantArea` Z-shrink behavior.
- The source of truth for final box dimensions: generated box, NPT final frame,
  NPT averaged X/Y, or explicit user input.
- The accepted health metrics and thresholds: Z cell drift, X/Y convergence,
  pressure averaging window, base-pair retention, wrap-bond distance, energy
  stability, and water density.
- The expected files in a periodic package and which ones the frontend Periodic
  MD panel can consume.
- Whether benchmark summaries are performance-only or also protocol-validating;
  currently the comments and artifacts are not aligned.
