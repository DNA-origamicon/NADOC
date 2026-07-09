# Periodic MD Memory

## Scope

Periodic MD is the explicit-solvent, axial-PBC workflow for reducing DNA origami
simulation cost by simulating one or more honeycomb crossover-repeat periods
instead of the full design. The main implementation is:

- `backend/core/periodic_cell.py` — slices the design, builds the atomistic
  model, adds wrap bonds, solvates, places ions, and emits a NAMD package.
- `backend/core/namd_solvate.py` — provides periodic GROMACS solvation and
  renders the periodic NAMD configuration.
- ~~`frontend/src/ui/periodic_md_panel.js` and
  `frontend/src/scene/periodic_md_overlay.js`~~ — **REMOVED 2026-07-08** (Simulate-panel
  overhaul, see [[project_simulate_panel_overhaul]]). This was a *client-only* PSF/PDB/DCD
  file-preview panel (no backend route); the sidebar "Periodic MD" section was deleted. The
  BACKEND periodic-cell workflow (`periodic_cell.py`, `namd_solvate.py`) is untouched — only
  the standalone frontend previewer went. If a periodic-cell preview UI is revived, rebuild
  it inside the unified Simulate section, not as a separate panel-section.
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

## Literature Audit Findings (2026-05-10)

Audit against published DNA origami MD protocols (Pan et al. 2014 JCTC 10:2906;
Yoo & Aksimentiev 2016 PNAS 113:4954; Galindo-Murillo et al. 2016 JCTC 12:4114;
Batcho & Schlick 2001 JCP 115:4003; Dans et al. 2016 PLoS CB 12:e1004974).

### Root cause of 47.8% C1'–C1' pairing in unrestrained smoke (5k steps)

Three additive causes, ordered by impact:

1. **`rigidBonds water` (now fixed → `rigidBonds all`)** — C–H (ω ≈ 2950 cm⁻¹,
   T ≈ 11 fs) and N–H bonds (ω ≈ 3300 cm⁻¹, T ≈ 10 fs) in nucleobases were below
   half-period at 2 fs. Energy accumulated in bases → transient C1' displacement
   beyond the 12 Å threshold without actual strand separation. All literature protocols
   for DNA use `rigidBonds all` at 2 fs. **Fixed in `namd_solvate.py` 2026-05-10.**

2. **`minimize 2000 + reinitvels 310` per ramp stage (old ramp)** — velocity
   re-initialization disrupted momentum and caused transient spikes. v2 ramp series
   already removed this.

3. **10 ps observation window** — too short; C1'–C1' thermal fluctuations require
   >100 ps to converge.

Evidence that catastrophic melting did NOT occur: the 50 ns `production_iso_npt` run
shows stable energy (−652 to −653 kcal/mol), temperature 309–311 K, and pressure ≈ 0 bar.

### Parameters still under investigation (open hypotheses in EXPERIMENTS.md)

- `fullElectFrequency 2` (4 fs outer PME) — MTS resonance in nucleic acid torsions;
  literature recommends 1. Hypothesis H002.
- `langevinDamping 5 ps⁻¹` — overdamps backbone torsional dynamics; literature
  uses 1 ps⁻¹ for production. Default in `namd_solvate.py` changed to 1.0 for
  locked-NVT/benchmark phases; NPT equilibration retains 5.0. Hypothesis H003.
- Z-lock tension (NPT equilibrium Z ≈ 67.8 Å vs design Z = 70.14 Å, 3.4% axial
  strain). Hypothesis H004.
- NPT temperature spike fix (from v2 restart, not raw solvation box). Hypothesis H005.

### Known-good parameters

- Timestep 2 fs + `rigidBonds all`: consistent with all cited literature.
- TIP3P water: correct pairing for CHARMM36 DNA.
- PME `PMEGridSpacing 1.0`: fine.
- `pairlistdist 16.0`: conservative and correct.
- Isotropic NPT (`useFlexibleCell no`) for production: isotropic NPT equilibrates at Z = 70.14 Å
  (tail mean = 70.144 Å, std = 0.026 Å from 17888-frame production_iso_npt XST). Design Z IS
  the equilibrium — the original "Z ≈ 67.8 Å" claim in earlier memory was wrong.
- Anisotropic NPT confirmed fatal (Z runaway 70→93 Å) for production.
- Anisotropic NPT for equilibration with restraints: anisotropic, Z drifts to 76.9 Å (not
  67.8 Å as previously recorded). This represents anisotropic barostat instability, not
  equilibrium. Use isotropic NPT for equilibration going forward.

## Critical Findings from H001 (2026-05-10) and production_iso_npt Analysis

**`ramp_v2_03` starting structure is damaged.** Frame 0 of production_iso_npt (starting from
ramp_v2_03 coords) shows only 56% C1'–C1' pairing (mean 11.62 Å). The damage accumulated
during the locked-Z ramp stages due to `rigidBonds water`. All hypothesis tests starting from
ramp_v2_03 are testing a broken structure.

**production_iso_npt is actively deteriorating** (rigidBonds water, 17.8 ns): 56% → 14.5%
bp_fraction, mean C1'–C1' 11.6 → 19.7 Å, p90 = 29.7 Å. Energy stable at −652 kcal/mol,
temperature 307–310 K. Structural rearrangement (likely helix-helix XY separation), not
simple base-pair melting.

**Next required action (H007):** Redo the full ramp pipeline with `rigidBonds all` from the
initial PDB. The `namd_solvate.py` fix (rigidBonds all) must propagate to all equilibrate_npt
and ramp conf files, not just production. Tests H003/H004/H006 are blocked until H007
establishes a clean starting structure.

## Things Still Unclear

- Whether `fullElectFrequency 1` is worth the ~15% speed penalty for this system.
- Whether 21 bp periodic-cell generation should be rejected for non-honeycomb
  designs, designs with loop/skip changes inside the selected window, or windows
  with non-modal crossover counts.
- Whether a different topology representation (duplicated/image atoms for
  boundary bonded exclusions) is worth exploring for GPUresident compatibility.

## Testing Framework

See `experiments/exp23_periodic_cell_benchmark/EXPERIMENTS.md` for the full
hypothesis registry. H001–H007 with literature citations, methods, and expected outcomes.
Run with:
```
python experiments/exp23_periodic_cell_benchmark/scripts/run_hypothesis.py H001
```

## Single 21 bp dsDNA Periodic Helix Scope (2026-05-14)

New active goal: simulate a minimal periodic DNA system consisting of one
21 bp dsDNA helix whose backbone strands are ligated end-to-end across the
axial periodic boundary. This is a reduction from the B_tube origami cell and
should be treated as a separate diagnostic system, not as a B_tube production
replacement.

Intended purpose:

- Isolate whether the atomistic B-DNA geometry, wrap-bond topology, CHARMM36
  parameters, NAMD PBC handling, solvation, and restraint/ramp protocol are
  individually sound before adding multi-helix origami packing.
- Provide a small, fast regression test for periodic wrap bonds across a 21 bp
  repeat.
- Determine whether the exact `70.140 Å` axial repeat is compatible with a
  relaxed CHARMM36 dsDNA helix when there are no crossovers or neighboring
  helices.

System definition to keep explicit:

- One helix.
- 21 base pairs.
- Two complementary strands.
- Each strand has one O3'->P wrap bond across axial PBC:
  - forward strand: O3' at bp 20 to P at bp 0,
  - reverse strand: O3' at bp 0 to P at bp 20.
- Exact starting Z should be `21 * 0.334 nm = 7.014 nm = 70.140 Å` unless the
  experiment intentionally sweeps axial length.
- This is dsDNA, not a single-stranded 21-mer. If someone says "single DNA
  strand" in this context, clarify whether they mean one dsDNA helix object or
  literally one ssDNA strand.

Lessons from previous periodic-MD attempts that apply:

- `rigidBonds all` is required for 2 fs DNA simulations. The older
  `rigidBonds water` setting damaged DNA/ramp structures and invalidated some
  early B_tube structural conclusions.
- Standard CUDA is currently the production path. GPUresident was slower on the
  RTX 2080 SUPER and has wrap-bond exclusion issues; brute-force pairlist
  enlargement caused CUDA shared-memory/OOM failures.
- `wrapNearest on` should remain enabled because the DNA backbone is bonded
  across the periodic boundary.
- The wrap-bond image trick is still relevant: boundary O3'/P/O5' geometry must
  be minimized in the nearest periodic image, then shifted back, so NAMD sees a
  chemically plausible minimum-image bond.
- Do not trust an energy-only pass. Earlier damaged systems showed stable
  energy/temperature while base-pair and helix geometry deteriorated.
- Base-pair metrics must be PBC-aware. C1' distance checks can be confused by
  wrapping unless minimum-image/unwrap handling is correct.

Lessons from previous attempts that may not apply directly:

- B_tube has multiple helices, crossovers, and only four free wrap bonds in the
  one-period package because many boundary atoms are already connected by
  crossover topology. A one-helix dsDNA periodic test should have exactly two
  backbone wrap bonds.
- B_tube restraint ramps were partly about preserving origami packing and
  helix-helix spacing. A single dsDNA helix should need little or no heavy-atom
  restraint after initial solvation/minimization if the topology and cell length
  are correct.
- B_tube pressure/box behavior is entangled with multi-helix packing. The
  single-helix system should be used to measure whether exact 21 bp axial
  periodicity is intrinsically strained for canonical B-DNA.

Known-good protocol pieces to start from:

- Generate atomistic CHARMM36 dsDNA with mixed or controlled sequence.
- Solvate with explicit TIP3P and ions in a periodic box whose Z is initially
  exact `70.140 Å`.
- Use `rigidBonds all`, PME, `pairlistdist 16.0`, standard CUDA, and
  `wrapNearest on`.
- Start with conservative minimization before dynamics.
- Prefer isotropic NPT for a diagnostic equilibrium-Z measurement, because the
  later B_tube audit found isotropic NPT held Z near `70.144 Å` while
  anisotropic NPT produced runaway/drift artifacts.
- For exact-Z tests, use fixed-cell NVT at `Z = 70.140 Å` and report axial
  stress/pressure as diagnostic output rather than trying to force all pressure
  tensor components to target.

Known-bad protocol pieces to avoid:

- `rigidBonds water` at 2 fs for DNA.
- Anisotropic/flexible-cell NPT as a production default; previous B_tube tests
  saw Z drift/runaway behavior.
- Directly interpreting early, very short (<100 ps) C1' pairing changes as
  melting without checking PBC wrapping and trajectory unwrapping.
- Reinitializing velocities at every restraint/ramp stage unless deliberately
  testing that choice; earlier ramp notes indicate repeated reinitialization can
  inject transients.
- GPUresident as a default path for wrap-bond systems.

Recommended first single-helix experiment matrix:

1. Vacuum/topology sanity:
   - Build dry 21 bp dsDNA with two PBC wrap bonds.
   - Verify exactly two wrap bonds and chemically plausible minimum-image
     O3'--P distances.
   - Verify no missing P/O3'/O5' atoms at boundaries.

2. Short solvated fixed-Z NVT:
   - Minimize.
   - Run 10-100 ps at fixed `Z = 70.140 Å`.
   - Check no sentinel energies, no fast-atom errors, stable temperature,
     PBC-aware base-pair retention, and stable helical rise/twist.

3. Isotropic NPT diagnostic:
   - Run with isotropic NPT from the same minimized system.
   - Measure equilibrium Z mean/std and compare with exact `70.140 Å`.
   - If isotropic NPT stays near 70.14 Å, exact-Z NVT is likely physically
     reasonable for canonical B-DNA.

4. Axial Z sweep if needed:
   - Test `Z = 69.0`, `69.5`, `70.140`, `70.5 Å`.
   - Compare base pairing, twist/rise, pressure/stress, and wrap-bond geometry.

Acceptance checks for this minimal system:

- NAMD exits zero.
- No sentinel energies.
- No fatal low-exclusion/CUDA/OOM errors.
- Exact fixed-Z runs keep `c_z = 70.140 Å` within `0.001 Å`.
- Exactly two wrap bonds exist and remain plausible under minimum image.
- PBC-aware base-pair retention remains high; initial target `>= 95%` for a
  canonical 21 bp duplex over short validation windows.
- Mean helical rise and twist should remain close to B-DNA expectations, while
  allowing thermal fluctuations.

Open questions for the single-helix scope:

- What sequence should be used: poly-AT/GC control, B_tube consensus segment,
  or a balanced random 21 bp sequence?
- Does "single DNA strand" mean one dsDNA helix object or literally one ssDNA
  strand circularized by PBC? These are different physical systems.
- Should the first implementation live as a new experiment directory, e.g.
  `experiments/exp24_periodic_dsdna_helix/`, or as a mode inside exp23?

Implementation start (2026-05-14):

- User clarified the target is one 21 bp dsDNA helix, end-to-end periodic.
- Reused existing control script:
  `experiments/exp23_periodic_cell_benchmark/scripts/build_single_helix.py`.
- Script-rot fix: `build_single_helix.py` imported
  `_complete_psf_from_stub` from `backend.core.namd_package`; the function now
  lives in `backend.core.namd_helpers`, so the import was patched.
- Build output directory:
  `experiments/exp23_periodic_cell_benchmark/results/single_helix_control/`.
- Dry geometry check before solvation:
  C1'--C1' distances at sampled terminal base pairs were `~9.666-9.667 Å`.
  Internal copy-junction and wrap O3'--P distances were `~2.066 Å`, longer
  than the script's `1.60 Å` target. This should be watched during minimization
  and may indicate the template-copy helix transform needs a local bridge
  minimization pass.
- Built solvated system:
  `single_helix.psf`, `single_helix.pdb`, `restraints.pdb`, `sh_npt.conf`,
  and `sh_npt_prod.conf`. The build reported 5,281 TIP3P waters, 58 Na+, 16 Cl-,
  and a `50.1 x 50.1 x 70.1 Å` box. Exactly two wrap bonds were added:
  `STRA O3'(res21)-P(res1)` and `STRB O3'(res21)-P(res1)`.
- Started and completed the scripted restrained isotropic NPT stage:
  `output/sh_npt.log`, `output/sh_npt.dcd`, `output/sh_npt.xst`.
  It completed with finite energies and no fatal NAMD errors. Base-pair analysis
  found 21/21 pairs, `100%` paired mean/final over `~0.505 ns`, mean C1'--C1'
  `10.51 Å` mean and `10.45 Å` final. However, isotropic NPT shrank Z from
  `70.140 Å` toward `~69.09 Å` by the end of the restrained phase.
- Started and completed the scripted unrestrained isotropic NPT continuation:
  `output/sh_npt_prod.log`, `output/sh_npt_prod.dcd`, `output/sh_npt_prod.xst`.
  It completed with finite energies and no fatal NAMD errors, but base-pair
  analysis deteriorated to `63.3%` mean and `42.9%` final paired over `~0.495 ns`;
  mean C1'--C1' was `11.99 Å` mean and `13.09 Å` final. Final Z was about
  `68.75 Å`. Conclusion: unrestrained isotropic NPT is not a good production
  mode for this minimal periodic helix as currently built.
- Manual exact-Z fixed-cell branch was started from the same solvated PDB:
  `sh_fixed_z_relax.conf` disabled the piston, kept heavy-atom restraints, and
  ran fixed-Z NVT at `Z = 70.140 Å` for `50,000` dynamics steps after
  minimization. It completed with finite energies and no fatal NAMD errors.
  Base-pair analysis remained `100%` paired mean/final over `~0.105 ns`, mean
  C1'--C1' `10.61 Å` mean and `10.60 Å` final.
- Manual unrestrained fixed-Z continuation `sh_fixed_z_prod.conf` restarted
  from the fixed-Z restrained run and held `Z = 70.140 Å`. It completed with
  finite energies and no fatal NAMD errors, but base-pair analysis deteriorated
  rapidly: `28.1%` mean and `28.6%` final paired over `~0.095 ns`, mean
  C1'--C1' `12.81 Å` mean and `13.52 Å` final. Conclusion: exact-Z fixed NVT
  prevents box shrink but does not by itself stabilize the current unrestrained
  single-helix topology/geometry.
- Current best diagnosis for the single-helix failure is geometry/topology
  rather than NAMD crash/ensemble mechanics. The dry constructed helix has
  O3'--P distances of `~2.066 Å` at copy junctions and the PBC wrap bond before
  minimization, versus the script's intended `1.60 Å`. The next fix should
  focus on applying the same local backbone bridge/image minimization used in
  `periodic_cell.py` to every copy junction and both wrap bonds, then rerun the
  unrestrained fixed-Z test.

Iteration notes (2026-05-14):

- H008 added bridge minimization to
  `experiments/exp23_periodic_cell_benchmark/scripts/build_single_helix.py`.
  The script now resolves `_SCRIPT` and `--out-dir` to absolute paths so
  generated NAMD configs are robust to the launch directory. This fixed a
  failure where NAMD could not open `single_helix.psf` after a variant was built
  with relative paths.
- H008 dry geometry after bridge minimization:
  all adjacent and PBC O3'--P links reached `1.600 Å`.
- H008 fixed-Z restrained NVT:
  `output/H008_fixed_z_relax.*` completed with no fatal errors and remained
  `100%` paired over `~0.105 ns`.
- H008 abrupt unrestrained fixed-Z continuation:
  `output/H008_fixed_z_prod.*` completed mechanically but failed structurally.
  Base pairing was `45.0%` mean and `47.6%` final over `~0.095 ns`; the first
  DCD frame was already `66.7%` paired. Temperature was stable
  (`308.4 ± 2.0 K`) and `Z = 70.140 Å` exactly, so bridge minimization is a
  partial improvement but not a full solution.
- Next active hypothesis is H009: keep the H008 bridge-minimized system and test
  a staged fixed-Z restraint release (`0.5`, `0.25`, `0.10`, `0.03`, `0.01`,
  then off). If H009 fails immediately after constraints off, the likely next
  branches are: rebuild the helix from a continuous canonical generator rather
  than copied B_tube frames; run a much longer/softer equilibration; or accept a
  weak production restraint as part of the reduced periodic model.
- H009 completed: full release is not stable. Pairing stayed `100%` through
  `constraintScaling 0.10`, fell at `0.03` (`81.0%` final), reached `66.7%`
  final at `0.01`, and was `42.9%` final with constraints off.
- H010 completed: `constraintScaling 0.10` is only a short-window/marginal pass.
  The 100 ps continuation had `95.2%` final pairing, but the 500 ps extension
  dropped to `85.7%` final pairing.
- H011 completed and is the first working interim single-helix production
  protocol. Use the H008 bridge-minimized build, fixed-Z NVT at `Z = 70.140 Å`,
  and retain DNA heavy-atom positional restraints with
  `constraintScaling 0.20`. The 500 ps validation run
  `output/H011_weak020_ext500.*` had no fatal NAMD errors, `99.5%` mean paired,
  `100.0%` final paired, final mean C1' distance `10.52 Å`, final p90 `11.21 Å`,
  temperature `309.1 ± 2.7 K`, fixed Z std `0.0 Å`, and `~231 ns/day`.
- The current best interpretation: bridge minimization is necessary, but the
  copied B_tube single-duplex model still lacks enough context or has residual
  construction strain to survive fully unrestrained. For now, `constraintScaling
  0.20` is a pragmatic restraint floor. Future tuning should try `0.15` for
  500 ps and/or rebuild the 21 bp duplex from a continuous canonical generator
  rather than three copied 7 bp B_tube segments.

B_tube 21 bp segment implementation (2026-05-14):

- The single-helix H011 lesson was applied back to the full B_tube 21 bp
  periodic cell, but B_tube needs a stronger restraint floor than the isolated
  duplex. Re-analysis of H007 fixed-Z stages showed:
  - `constraintScaling 1.00`: `96.6%` final paired over `~0.098 ns`
  - `constraintScaling 0.50`: `93.5%` final paired over `~0.198 ns`
  - `constraintScaling 0.25`: `88.5%` final paired
  - `constraintScaling 0.10`: `78.0%` final paired
  - `constraintScaling 0.03`: `61.3%` final paired
- H012 was created as the stability-first B_tube implementation:
  `experiments/exp23_periodic_cell_benchmark/exp_cards/H012_btube_k1_retained_prod.md`.
- H012 config:
  `experiments/exp23_periodic_cell_benchmark/results/hyp_runs/H012/H012_k1_prod.conf`.
  It starts from the clean H007 fixed-Z restrained restart
  `results/hyp_runs/H007/output/H007_relax.restart.*`, keeps fixed
  `Z = 70.140 Å`, uses standard CUDA and `rigidBonds all`, preserves restart
  velocities, and retains DNA heavy-atom positional restraints with
  `constraintScaling 1.0`.
- H012 result:
  `output/H012_k1_prod.*` completed 500 ps fixed-Z NVT with no fatal errors.
  Pairing was `96.6%` mean and `96.0%` final over `~0.498 ns`; final mean C1'
  distance was `10.44 Å`, final p90 `11.50 Å`. Temperature was
  `309.5 ± 0.8 K`, `Z = 70.140 Å` with std `0.0 Å`, and performance was
  `~24.7 ns/day`.
- Adopt H012 as the first stable B_tube 21 bp periodic-segment protocol.
  It is deliberately conservative. Next experiments should tune downward from
  the working point: `constraintScaling 0.75` for 500 ps, then `0.60`/`0.50`
  only if the final C1' pairing remains `>= 95%`.

No-restraint B_tube iteration results (2026-05-14):

- H013 tested abrupt constraints-off fixed-Z NVT from the stable H012 restart.
  It completed mechanically but failed structurally: first saved frame was
  already `81.2%` paired, mean paired `56.4%`, final paired `49.2%` over
  `~0.098 ns`. Temperature was stable and `Z = 70.140 Å`.
- H014 tested staged release from H012:
  - `0.75`: `94.8%` final paired
  - `0.50`: `93.3%` final paired
  - `0.25`: `89.7%` final paired
  - `0.10`: `80.2%` final paired
  - `0.05`: `72.2%` final paired
  - off: `51.8%` final paired
  This rules out abrupt release as the only failure mode; loss begins as soon as
  the restraint floor drops below roughly `0.75`.
- H015 tested constraints off with `timestep 1.0` and `fullElectFrequency 1`.
  It still failed: `62.9%` final paired after `~0.019 ns`. This argues against a
  simple 2 fs/MTS integration artifact.
- H016 tested constraints off under isotropic NPT from H012. It still failed:
  first saved frame `79.6%`, final `56.2%` after `~0.048 ns`. This argues
  against fixed-Z/fixed-volume stress as the sole cause.
- Working interpretation: the current B_tube 21 bp reduced periodic segment is
  not self-supporting under unrestrained all-atom dynamics. The MD engine is
  stable; the architecture relaxes away from the C1' pairing reference when
  positional restraints are removed. Plausible causes include residual
  atomistic construction strain, insufficient crossover/connectivity constraints
  inside a single 21 bp repeat, loss of longer-range origami context, or the C1'
  metric detecting helix/strand registry relaxation that positional restraints
  had been suppressing.
- Recommendation: keep H012 (`constraintScaling 1.0`) as the only validated
  B_tube periodic production protocol for now. To pursue fully unrestrained
  production, change the model rather than only the MD protocol: audit crossover
  topology/connectivity in the 21 bp package, inspect per-helix/per-segment
  displacement modes, consider a longer repeated cell (2x or 3x periods), and
  consider architecture-level restraints or canonical rebuild/relaxation before
  removing atom positional support.

2-period B_tube setup (2026-05-14):

- Added reproducible builder:
  `experiments/exp23_periodic_cell_benchmark/scripts/build_btube_periodic_variant.py`.
  Usage:
  `python experiments/exp23_periodic_cell_benchmark/scripts/build_btube_periodic_variant.py --periods 2`.
- Patched `backend/core/periodic_cell.py` to import
  `_complete_psf_from_stub` from `backend.core.namd_helpers`; the old
  `backend.core.namd_package` import had rotted.
- Built `experiments/exp23_periodic_cell_benchmark/results/periodic_cell_2x_run/`.
  Stats: `bp_start=21`, `bp_end=63`, `Z=140.280 Å`, `4` wrap bonds,
  `120` crossovers, `41,328` DNA atoms, `96,309` waters, `2,336 Na`,
  `320 Cl`, `332,911` total atoms, box about
  `161.061 x 156.614 x 140.280 Å`.
- H017 2x retained-restraint baseline:
  `results/hyp_runs/H017/H017_k1_relax_100ps.conf` ran fixed-Z NVT from the
  generated 2x PDB with `constraintScaling 1.0`. It completed with no fatal
  errors. Pairing: `95.3%` mean, `97.0%` final over `~0.100 ns`.
  Performance was `~9.9 ns/day`.
- H018 2x abrupt constraints-off release:
  `results/hyp_runs/H018/H018_off_100ps.conf` started from the H017 final
  checkpoint. It completed mechanically but failed structurally: first saved
  frame at `10 ps` was only `52.4%` paired, mean paired `42.3%`, final paired
  `37.7%` by `90 ps`. This is not an improvement over 1x H013.
- Configured but not yet run:
  - H019 staged 2x release (`0.75`, `0.50`, `0.25`, `0.10`, `0.05`, off)
  - H020 2x constraints off with `1 fs` and `fullElectFrequency 1`
  - H021 2x constraints off under isotropic NPT
- Early interpretation: simply doubling axial context to 42 bp does not rescue
  abrupt unrestrained production. Because H017 is stable with retained
  restraints but H018 fails within 10 ps, the missing ingredient is likely not
  just repeat length; topology/connectivity, construction strain, or necessary
  architecture-level restraints remain suspect.

MD-derived atomistic CAD references (2026-05-14):

- Problem addressed: the default NADOC all-atom view/export is template-built
  from hand-tuned sugar/base coordinates in `backend/core/atomistic.py`. That
  is useful for deterministic CAD preview, but it is a questionable MD starting
  pose and can hide the difference between analytic CAD geometry and relaxed
  all-atom coordinates.
- Added persistent `Design.atomistic_reference` in `backend/core/models.py`.
  When present, `backend/core/atomistic.py::build_atomistic_model()` now returns
  this stored heavy-atom model instead of regenerating template coordinates
  (unless a CG position override is explicitly requested). The reference stores
  a topology hash; if the design topology/geometry/sequence changes, the
  reference is ignored and the normal template builder is used.
- Added extractor:
  `experiments/exp23_periodic_cell_benchmark/scripts/extract_atomistic_reference.py`.
  It keeps NADOC atom identity/bonds, replaces coordinates with a selected MD
  frame, stores the result in a `.nadoc`, and can also export a reference PDB.
- Important extraction detail: for periodic trajectories, use nearest-image
  placement against the CAD/template coordinates with the package CRYST1 box.
  Do not apply whole-structure centroid translation to wrapped periodic DCDs;
  H017 showed that this can introduce a false ~half-period displacement. The
  working mode was `--align none --box-pdb <periodic package pdb>`.
- Generated references:
  - `results/H012_btube_1x_relaxed_reference.nadoc`
  - `results/H012_btube_1x_relaxed_reference.pdb`
  - `metrics/H012_atomistic_reference_report.json`
    - `20,664` DNA atoms, `23,171` bonds
    - nearest-image box `[16.1027, 15.6614, 7.014] nm`
    - template→reference RMSD `0.156 nm`, mean displacement `0.095 nm`,
      max displacement `1.541 nm`
  - `results/H017_btube_2x_relaxed_reference.nadoc`
  - `results/H017_btube_2x_relaxed_reference.pdb`
  - `metrics/H017_atomistic_reference_report.json`
    - `41,328` DNA atoms, `46,343` bonds
    - nearest-image box `[16.1061, 15.6614, 14.028] nm`
    - template→reference RMSD `0.126 nm`, mean displacement `0.084 nm`,
      max displacement `1.571 nm`
- These are still restrained references (`constraintScaling 1.0`), not evidence
  of unrestrained stability. They are, however, more honest CAD starting poses
  than the raw hand-tuned template construction. Use the 2x reference first for
  follow-up periodic-model debugging because it has more axial context and a
  smaller relaxed displacement from the template.

Full-origami early relaxation probes (2026-05-14):

- New experiment area:
  `experiments/exp25_full_origami_relaxation/`.
- Motivation: use the whole B_tube topology, not the reduced periodic cell, to
  see how the raw atomistic CAD/template pose relaxes in the first minimization
  and tiny dynamics windows. These runs are diagnostic and intentionally short.
- Source package: Exp22 full B_tube NAMD GBIS package
  `experiments/exp22_btube_md_benchmark/results/namd_run/`.
  The old benchmark (`500` minimization steps then `reinitvels 310`) failed
  immediately after velocity assignment. The new Exp25 probes test gentler
  startup and extract atomistic CAD references.
- F001 (`F001_min_only_5k`) completed: 5000-step minimization, finite accepted
  energies, restart written. Displacement from raw template:
  RMSD `0.0504 nm`, mean `0.0384 nm`, p90 `0.0724 nm`, p99 `0.1911 nm`,
  max `0.4237 nm`.
- F002 (`F002_cold_10ps_k5`) failed: 50 K, 0.5 fs, strong restraints to the
  original raw template while starting from F001 minimized coordinates. Temp
  jumped to `438 K` at step 100 and NAMD reported atoms moving too fast. This
  showed that restraints must reference the current relaxed pose, not the
  high-strain raw template.
- F002b (`F002b_cold_1ps_minref_k1`) completed: generated a restraint PDB from
  the F001 minimized coordinates, ran 1 ps at nominal 10 K, 0.25 fs,
  `constraintScaling 1.0`. The system settled around `55-60 K`, indicating
  residual relaxation energy even under restraints. Displacement from raw
  template: RMSD `0.1004 nm`, mean `0.0890 nm`, p90 `0.1404 nm`, p99
  `0.2704 nm`, max `0.5659 nm`.
- F003b (`F003b_cold_50K_1ps_minref_k1`) completed: continued from F002b for
  1 ps at nominal 50 K, same minimized-coordinate restraint reference. It heated
  sharply early (`~271 K` at step 200) and cooled to `~139 K` final; bounded but
  not production-ready. Displacement from raw template: RMSD `0.1026 nm`, mean
  `0.0911 nm`, p90 `0.1428 nm`, p99 `0.2740 nm`, max `0.7357 nm`.
- Generated full-origami atomistic references:
  - `experiments/exp25_full_origami_relaxation/results/B_tube_full_F001_minimized_reference.nadoc`
  - `experiments/exp25_full_origami_relaxation/results/B_tube_full_F002b_cold_1ps_reference.nadoc`
  - `experiments/exp25_full_origami_relaxation/results/B_tube_full_F003b_50K_1ps_reference.nadoc`
- Current best use: adopt F001 as the cleanest improved CAD atomistic starting
  pose for reducing initial minimization needs. F002b/F003b are useful to study
  early dynamic relaxation modes, but they have temperature/strain transients
  and should not yet be treated as production-equilibrated structures.
- CAD integration checkpoint: `workspace/B_tube_relaxed_atomistic_F001.nadoc`
  is the workspace-level improved CAD model. It contains the same B_tube
  topology plus a persisted `Design.atomistic_reference` from the F001 minimized
  full-origami coordinates. `backend/core/atomistic.py::build_atomistic_model()`
  reuses this reference when the stored topology hash still matches and no
  coarse-grained coordinate override is requested.
- Added live full-origami base-pair monitor:
  `experiments/exp25_full_origami_relaxation/scripts/basepair_monitor.py`.
  It identifies C1' partners from a reference PDB/PSF, polls a growing DCD,
  writes JSONL metrics, and can launch/terminate NAMD through `--namd-cmd`.
  The monitor exits nonzero if paired fraction falls below the configured
  threshold after the grace-frame count.
- Monitor calibration for Exp25 full-origami GBIS: do not use the earlier
  `12 Å`/`95%` setting. The F001 reference baseline is only `93.45%` paired at
  `12 Å`, `97.71%` at `12.5 Å`, and `100%` at `13 Å`. Current validation uses
  `--paired-max-ang 13.0 --min-paired 0.90`.
- F004 (`310 K`, `0.5 fs`, 5 ps, k=1 restraints to F001 from F003b restart)
  failed before the first useful DCD frame with margin/fast-atom errors near
  local DNA atoms around residues `A3972` and `A3673`.
- F005 (`150 K`, `0.25 fs`, 5 ps, k=1) was killed by the monitor, but this run
  used the miscalibrated `12 Å`/`95%` cutoff and should not be interpreted as a
  true structural failure. It also heated substantially above the target.
- F006 repeated the `150 K` test with calibrated `13 Å`/`90%` monitoring. The
  first analysed frame was above threshold (`92.74%` paired), but NAMD failed
  around step 400 with a high-velocity local sugar atom near `DT b 10`. This is
  a local dynamics/geometry failure rather than a base-pair-threshold trip.
- F007 (`nominal 50 K`, `0.25 fs`, 5 ps, k=1, calibrated monitor) completed
  cleanly. Pairing stayed around `91.7-92.5%` with the `13 Å` cutoff; the last
  analysed frame was `92.19%` paired, mean C1' `12.04 Å`, p90 `12.90 Å`.
  Final displacement from the F001 minimized reference was RMSD `0.0743 nm`,
  mean `0.0661 nm`, p90 `0.1040 nm`, p99 `0.1728 nm`, max `0.8282 nm`.
  Caveat: although the Langevin target was `50 K`, inherited hot velocities
  kept the reported temperature near `240-250 K` at the end. Treat F007 as a
  bounded restrained validation, not a production protocol.
- F008 tried the first explicit ramp to 310 K from F001 minimized coordinates,
  discarding inherited velocities. It used `0.25 fs`, k=1 restraints,
  `langevinDamping 5`, target steps `50/100/150/200/250/310 K`, and a final
  5 ps 310 K block. It completed mechanically and structurally, ending at
  `91.22%` paired with the calibrated `13 Å` monitor, but failed thermally:
  final-tail temperature averaged `507.36 K` and final `TEMPAVG` was
  `499.10 K`.
- F009 tried the second 310 K ramp with stronger heat removal:
  `langevinDamping 20` and `reinitvels` at each 0.5 ps plateau from `25 K` to
  `310 K`, followed by 5 ps at 310 K. It is the best bounded warm attempt so
  far: no fatal errors, no monitor trip, final `92.06%` paired, final RMSD from
  F001 `0.0756 nm`. It still failed as a true 310 K production protocol because
  the final-tail temperature averaged `353.83 K` and final `TEMPAVG` was
  `351.32 K`.
- After F008/F009, stop simple temperature-ramp knob tuning. Two attempts show
  the structure can remain base-pair bounded under k=1 restraints while
  releasing enough stored energy to overwhelm the intended thermostat target.
  The broader issue is likely residual high-energy bonded/nonbonded strain in
  the F001 atomistic pose and/or the GBIS/restraint setup, not only bad
  velocity inheritance. Next diagnostics should audit energy sources: longer
  restrained minimization, per-term/per-residue high-energy localization,
  restraint-reference/force sensitivity, and explicit-solvent or smaller-domain
  comparisons before trying more production-length 310 K runs.
- Established-practice remediation checkpoint:
  - `backend/core/namd_solvate.py` now supports explicit NaCl + MgCl2 package
    generation (`mg_conc_mM`), writes Mg2+ ions, uses the CUFIX water/ion
    stream by default, uses `rigidBonds all`, and defaults explicit-solvent
    Langevin damping to `1 ps^-1`.
  - `experiments/exp25_full_origami_relaxation/scripts/generate_enm_restraints.py`
    builds NAMD `extraBonds` local-order restraints for base-pair registry and
    base stacking. Current B_tube artifact:
    `results/runs/F010_established_practice_gbis_enm/local_order_enm.extrabonds`
    with `61,186` restraints.
  - `experiments/exp25_full_origami_relaxation/scripts/watson_crick_monitor.py`
    adds a Watson-Crick heavy-atom proxy monitor. It reports strict absolute
    retention and reference-relative retention because F001 itself only passes
    `24.21%` under a strict `3.6 Å` all-H-bond proxy. F009 final is only
    `0.39%` absolute and `15.10%` reference-relative, despite looking acceptable
    by the older C1' distance monitor. Conclusion: the C1' monitor is a useful
    tripwire, not a chemical base-pair validation metric.
  - `experiments/exp25_full_origami_relaxation/scripts/setup_established_practice_protocol.py`
    generated `F010_established_practice_gbis_enm`: k=1 positional startup,
    ENM+weak positional stage, then ENM-only stage. This closes the restraint
    and monitoring gaps before launching a larger explicit-solvent Mg run.
  - `experiments/exp25_full_origami_relaxation/scripts/build_explicit_mg_package.py`
    provides the explicit-solvent Mg package path. Use `--stats-only` first for
    whole B_tube because the package will be large. Remaining gap: the current
    implementation places Mg2+ ions directly with CUFIX parameters; it does not
    yet place MGH hexahydrate clusters even though the forcefield defines them.
- F011 quick B-tube smokes tested immediate 310 K startup with the new
  established-practice pieces:
  - Corrected an important ENM bug: NAMD `extraBonds` atom indices are
    zero-based. The initial 1-based ENM file produced artificial bond energy
    around `1,014,952`; the corrected file brings initial energy back in line
    with the positional-only control. Regenerate any old ENM files before use.
  - `F011A_positional_310K_smoke` (k=1 positional, 5000 min + 2 ps) kept C1'
    pairing high (`99.58%`) but failed with low CUDA exclusion count at step
    `5400`; minimization produced thousands of GBIS sentinel-energy lines.
  - `F011C_positional_enm_zeroidx_310K_smoke` (corrected ENM + k=1 positional)
    tripped C1' at `76.34%` paired and overheated to `606 K`.
  - `F011D_enm_zeroidx_no_min_310K_smoke` (corrected ENM, no extra minimization)
    tripped C1' at `89.36%` paired and overheated to `988 K`.
  - Watson-Crick monitor again showed C1' is too forgiving: F011A final
    available frame was `99.6%` by C1' but only `78.7%` reference-relative
    Watson-Crick; F011C/D were near `11.7%`/`4.5%` reference-relative.
  - Do not run F010's immediate 310 K stages as written. Next test should use
    corrected ENM only through a cold/weak ramp: start `25-50 K`, scale ENM
    force constants to `0.05-0.10` of the current values, keep k=1 positional
    restraints at first, then warm gradually. The alternative is to test ENM in
    explicit solvent/Mg on a smaller subdomain because GBIS direct 310 K is
    still releasing too much heat.
- F012 attempted that cold/weak-ENM production path. It should be treated as a
  halted production attempt, not a production success:
  - `F012_00_25K_weak_enm` (`5%` ENM, k=1 positional, 25 K, 2 ps) completed
    mechanically with no sentinel energies and C1' around `93%`, but temperature
    settled near `70 K` and Watson-Crick reference-relative retention was only
    `20.46%`.
  - `F012_00b_25K_enm020` (`20%` ENM) also completed mechanically, but did not
    improve Watson-Crick retention (`20.82%`) and still ran around `69 K`.
  - `F012_00c_25K_enm100` (full ENM at 25 K) failed at step `600` with
    `Low global CUDA exclusion count`.
  - Decision: do not continue F012 to 50/100/150/310 K. Weak ENM is too weak to
    preserve chemical base geometry; full ENM is too stiff for the current
    starting pose/GBIS dynamics. The next credible production branch is
    explicit-solvent/Mg, preferably first on a smaller B_tube subdomain, or a
    better atomistic base-pair rebuild because F001 is not Watson-Crick-clean
    under strict heavy-atom criteria.
- F013 full B-tube explicit-solvent/Mg checkpoint:
  - Built a full explicit package from
    `workspace/B_tube_relaxed_atomistic_F001.nadoc` in
    `experiments/exp25_full_origami_relaxation/results/runs/F013_explicit_mg_full/B_tube_namd_solvated`.
    Final system size is `2,314,212` atoms after ion replacement
    (`668,498` waters, `16,400` Na, `190` Mg, `2,658` Cl).
  - Fixed explicit package scaling bugs: direct script import path, water/ion
    segment overflow for large systems, and stats overcounting waters before
    ion replacement.
  - The bundled CUFIX stream contains NBFIX rows for protein/lipid atom types
    missing from the DNA-only force-field bundle. Use
    `filter_cufix_for_package.py` to generate
    `forcefield/toppar_water_ions_cufix_dna_only.str`; the F013 package filtered
    `95` undefined rows.
  - Direct early NPT is invalid: the first 25 K dynamics attempt tripped
    `Periodic cell has become too small for original patch grid` because the
    initial pressure was about `-433 kbar`. Start with fixed-volume NVT.
  - Conservative restrained NVT ramp to 310 K succeeded, then restrained NPT
    succeeded. The short unrestrained 310 K NPT smoke also completed
    numerically. Throughput on the local RTX 2080 SUPER was roughly
    `0.47 ns/day` for NVT and `0.41 ns/day` for NPT.
  - Structural gate still failed after restraints were removed. In
    `F013_08_310K_NPT_unrestrained_monitor_1ps`, final C1' pairing was
    `56.72%` at `13 Å`; Watson-Crick reference-relative retention was only
    `9.97%`. Conclusion: explicit solvent/Mg fixes warmup numerics but not
    base-pair stability from the current atomistic starting pose.
- F014 explicit-solvent/Mg restraint ladder found the first stable full B-tube
  simulation mode:
  - Branch all tests from `F013_06_310K_NPT_2ps`, the last good restrained NPT
    state before unrestrained geometry loss.
  - k=1 DNA heavy-atom positional restraints: numerically stable and C1'
    `94.84%`, but Watson-Crick reference-relative only `38.26%`.
  - k=3: C1' `98.68%`, Watson-Crick reference-relative `76.24%`.
  - k=4: C1' `99.15%`, Watson-Crick reference-relative `85.72%`; marginal.
  - k=5: C1' `99.20%`, Watson-Crick reference-relative `92.17%`; passes the
    short-run gate.
  - Longer k=5 continuation `F014_10_k5_310K_NPT_4ps` completed, giving 5 ps
    total after the F013 warmup. Final temp `309.84 K`, pressure average
    `8.85 bar`, C1' `99.45%`, Watson-Crick reference-relative `94.12%`.
  - Treat this as a stable restrained-equilibration/prototype-production mode,
    not as an unrestrained physical production protocol. The next goal is to
    replace or reduce k=5 positional restraints with chemistry-aware
    base-pair/stacking restraints in explicit solvent.
- F014/F015/F016/F017 longer/literature-aligned update:
  - `F014_20_k5_310K_NPT_20ps` is the current best full B-tube explicit
    solvent/Mg run. It completed 20 ps at 310 K NPT with DNA heavy-atom
    positional restraints at `constraintScaling 5`. Final temp `309.85 K`,
    pressure average `19.31 bar`, throughput `0.400 ns/day`, C1' `99.48%`,
    Watson-Crick reference-relative `96.12%`.
  - Literature check: Maffeo/Yoo/Aksimentiev use NAMD, CHARMM36, TIP3P, PME,
    300 K Langevin with damping `1 ps^-1`, NVT production after box setup,
    Mg-hexahydrate-containing solvent, an initial DNA non-hydrogen positional
    restraint stage at `k=1`, then a dense intra-helical ENM at `k=0.1`
    between nearby non-hydrogen DNA atoms within `0.5 nm`; later explicit
    solvent restart used weak Watson-Crick restraints at `k=0.1`.
  - Current NADOC explicit package still uses direct `MG` ions. The forcefield
    defines `MGH` and comments that Mg-water stability needs extraBonds, so
    MGH placement/extrabonds remain a meaningful gap.
  - `F015_01_enm_k0p5_300K_NVT_2ps` tested the existing sparse local-order ENM
    at 300 K, NVT, damping `1`, piston off. It ran numerically but failed
    immediately by structure: C1' `68.51%`, Watson-Crick reference-relative
    `20.97%`.
  - Added `generate_dense_enm_restraints.py` and
    `setup_dense_literature_enm_protocol.py`. The first dense ENM attempt
    duplicated PSF covalent bonds and NAMD rejected it; the generator now
    filters topology bonds. Filtered dense ENM: `3,483,488` restraints at
    `k=0.1`, 5 A cutoff.
  - `F016_01_dense_enm_k0p1_300K_NVT_2ps` completed at `0.451 ns/day` and
    improved gross C1' retention to `90.94%`, but Watson-Crick retention was
    only `42.24%`. Dense ENM is better than sparse ENM but still not enough.
  - Added `generate_wc_restraints.py` and `setup_wc_literature_protocol.py`.
    `F017_01_wc_k0p1_300K_NVT_2ps` used `15,597` Watson-Crick heavy-atom
    extraBonds at `k=0.1`; it completed at `0.470 ns/day` but failed with C1'
    `68.28%` and Watson-Crick reference-relative `19.19%`.
  - Conclusion: weak published-style ENM/WC restraints are not a direct
    replacement for k=5 positional restraints on the current starting geometry.
    Keep k=5 as the stable restrained baseline. Next serious branches are
    MGH-hexahydrate package support, a smaller fully literature-faithful test,
    and/or a slow k=5 -> k=1 -> dense-ENM ramp over tens of ps instead of an
    abrupt release.

## Literature Audit — Production Protocol (2026-05-18)

Second literature audit against Aksimentiev group standard protocols
(Yoo & Aksimentiev 2013 PNAS 110:20099; Maffeo, Yoo & Aksimentiev 2016 NAR
44:3013; Shi et al. 2019 ACS Nano 13:12443; Galindo-Murillo et al. 2016
JCTC 12:4114).

### Critical finding: "unrestrained" Aksimentiev production uses permanent ENM

The published Aksimentiev DNA origami NAMD productions are NOT truly
unrestrained. Their standard protocol:
1. 10 ns restrained equilibration at k=1 kcal/mol/Å² (positional, all non-H DNA atoms)
2. Transition to dense intra-helical ENM: k=0.1 kcal/mol/Å², all non-H DNA atom
   pairs within 5 Å cutoff (~3.5 M restraints for B_tube scale), filtering PSF bonds
3. ~15 ns under ENM (with optional weak WC restraints at k=0.1)
4. "Production" at 200+ ns — ENM retained throughout

The ENM is a permanent production scaffold, not a temporary equilibration tool.
The published "unrestrained" 200 ns runs start from a different, much more
equilibrated coordinate set and retain ENM. Achieving F020_16-style zero-restraint
stable production from a template-built structure at CHARMM36 is not demonstrated
in the published literature.

Decision (2026-05-18): adopt ENM-permanent production as the project standard.
This is the correct physics for template-built origami MD and matches published
practice. Hypothesis F022 implements this.

### MGH extrabond force constant is 500x the literature value

F018/F019/F020 MGH extrabonds use k ≈ 500 kcal/mol/Å². The Aksimentiev protocol
uses k=1 kcal/mol/Å² for MGH during equilibration and drops to ~0 in production.
At k=500, Mg2+-water ligands cannot reorient during any F020 stage, preventing
the 10 ns Mg2+ equilibration described in the literature. This does not explain
the structural collapse (DNA fails before Mg2+ mispositioning matters) but is a
systematic deviation to correct in any future system rebuild.

Implementation update (2026-05-19): `backend/core/namd_solvate.py` now generates
new `mgh_extrabonds.txt` files with `k=1 kcal/mol/A^2` and `r0=1.94 A`. Existing
F018/F019/F020 artifacts remain historical and should not be used as the basis
for a new production package.

## Full B_tube Production Direction (2026-05-19)

The active production target is now `F027_literature_aligned_enm_production`.
It supersedes zero-restraint F020-style production as the main long-run path.
The required shape is:

- Fresh explicit-solvent B_tube rebuild so the corrected MGH restraints are in
  the generated package.
- CHARMM36/CUFIX + TIP3P + PME with about 1 A grid spacing.
- `rigidBonds all`, `fullElectFrequency 1`, and 1 fs timestep for the first
  production candidate.
- Nanosecond-scale DNA non-hydrogen positional equilibration at k=1 before any
  handoff.
- Dense intra-helical ENM at k=0.1, 5 A cutoff, non-hydrogen DNA atoms only,
  covalent PSF bonds filtered, retained through the first production run.
- Health gates based on both C1' pairing and Watson-Crick reference-relative
  retention. C1' alone is not sufficient.

Hardware note: the full B_tube benchmark on the tested workstation gives roughly
`0.97 ns/day` for standard CUDA at `+p8`, `fullElectFrequency 1`. GPU-resident
did not produce usable full-system `ns/day` values and remains a benchmark-only
mode until it passes health-checked science runs.

## F028 Exact Aksimentiev Tutorial Trial (2026-05-21)

User requested trying the public Aksimentiev DNA-origami tutorial protocol as
directly as possible on full B_tube.

Setup:

- Script:
  `experiments/exp25_full_origami_relaxation/scripts/setup_f028_aksimentiev_exact_protocol.py`
- Run directory:
  `experiments/exp25_full_origami_relaxation/results/runs/F028_aksimentiev_exact_btube/B_tube_namd_solvated`
- Source system: existing explicit-solvent/MGHH F027 B_tube package.
- Tutorial-style stages:
  - `equil_min`: ENM k=0.5 + MGHH, `minimize 4800`
  - `equil_k0.5`: ENM k=0.5 + MGHH, `run 2400000`
  - `equil_k0.1`: ENM k=0.1 + MGHH, `run 2400000`
  - `equil_k0.01`: ENM k=0.01 + MGHH, `run 2400000`
  - `equil_k0`: MGHH only, `run 2400000`
- Tutorial-style settings: 2 fs timestep, `rigidBonds all`, PME grid spacing
  1.5 A, 8/10/12 A switching/cutoff/pairlist, Langevin damping 5, NPT piston
  period/decay 1000/500, output/restart every 9600 steps.
- ENM implementation update: replaced the first dense non-hydrogen 5 A network
  with a Python port of the tutorial `cadnano2pdb2enm.pl` behavior:
  base-ring atoms only (`N1,C2,N3,C4,C5,C6,N7,C8,N9`), no phosphate/sugar/H
  atoms, residue COM prefilter 30 A, atom-pair cutoff 8 A, and NAMD zero-based
  extraBonds.  The resulting B_tube k=0.5 ENM has 1,625,191 restraints.

Initial result:

- `equil_min` completed 4800 minimization steps successfully with `namd3 +p4`.
  Wall clock was about 676 s. Total energy at step 4800 was `-1.008e7`
  kcal/mol; no fatal NAMD error.
- The dense 3.48M-restraint ENM only ran reliably at `+p4`; after replacing it
  with the tutorial-like base-ring cut=8 ENM, `+p12` starts correctly.
- `equil_k0.5` was relaunched detached with:
  `setsid bash -c 'cd .../F028.../B_tube_namd_solvated && namd3 +p12 equil_k0.5.namd > equil_k0.5.log 2>&1'`
- Startup passed, `READ 1626397 EXTRA BONDS`, and NAMD entered
  `TCL: Running for 2400000 steps`.
- Early benchmark speed is about `0.56 days/ns` (`~1.8 ns/day`), so a 4.8 ns
  ladder stage is roughly 2.7 wall-clock days at `+p12` on this workstation.

### CHARMM36 B-form stability ceiling

CHARMM36 ε/ζ backbone torsion imbalance causes B-DNA drift at long timescales
(Galindo-Murillo et al. 2016 JCTC). OL15/bsc1 (AMBER) substantially outperform
CHARMM36 on free-B-form retention. The published Aksimentiev origami simulations
use ENM specifically to compensate for this. OL15/AMBER is the correct choice if
truly unrestrained production is required (F024, deferred).

### F020 vs. published equilibration timescale

F020 uses 10–50 ps per k-level (~800 ps total). The published Aksimentiev
protocol uses 10 ns before the first restraint transition. The ~10–25× timescale
gap is likely a significant contributor to the collapse at low k.

## F020 and F022 Status (2026-05-18)

- F020 pipeline (F020_03 through F020_16, k=20 ramp): running autonomously via
  `run_f020_pipeline.sh` (PID 210847). Started from 100K checkpoint, progressing
  through full k-release ladder. Expected to fail at or near F020_16 (unrestrained).
  Pipeline documents the failure point for the researcher record.
- F022 ENM-permanent setup: being built by executor agent. Will branch from the
  last stable F020 checkpoint. Consists of:
  - Dense ENM: k=0.1, 5 Å cutoff, filtering topology bonds
  - WC restraints: k=1.0, canonical H-bond donor/acceptor pairs
  - Transition conf (50 ps): both positional k=0.05 + ENM to equilibrate ENM
  - Production conf (100 ns target): ENM-only, 310K NPT, 2 fs + fef 2
- RTX 3080 Ti throughput estimate: ~0.6–0.8 ns/day for 2.3M atoms at 2 fs.
  100 ns production ≈ 125–170 wall-clock days on local hardware.
