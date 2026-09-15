# cube_pore cavity investigation — isolated local experiments

The user authorized local simulations to determine why the cavity forms and to prepare a change for review. Application code and existing simulation jobs must not be changed. This directory contains research scripts, experimental configurations, diagnostics, and local outputs only. Source inputs are read from parent job `60e854232e8c`; production job `a4cb52583c26` is unchanged.

## Questions and controls

1. Was solvent omitted or forcibly excluded from the opening? Reproduce the solvation census; inspect topology, constraints, extra bonds, and actual trajectory coordinates.
2. Does the solvated electrolyte begin at its equilibrium density? Compare a 6 nm periodic 150 mM NaCl box at NVT and NPT with identical initial structures and chemistry.
3. Can the current wall remain hydrated? Run an 8 nm open graphene pore at the existing interaction parameters; compare full solvation and random whole-water removal (96% and 92% of the fully solvated water count).
4. Does compatible pressure equilibration help? Branch the open-pore 100% run at step 30000 into constant lateral area / constant normal pressure (NPzAT). The membrane coincides with the cell origin, so the normal dilation leaves its reference plane invariant.
5. Does this intervention work on the actual DNA system? Run the entire original dry checkpoint on CPU with NPzAT; keep the original force field, coordinates, velocities, topology, wall restraints, 4 fs timestep and 8 fs PME interval. The full system exceeds local CUDA pinned-memory allocation limits in both resident and offload modes. CPU/GPU differences are a limitation to account for; do not claim a quantitatively matched dynamical trajectory.

The reduced open-pore systems are mechanism controls, not conductance predictions for cube_pore. Their NaCl is neutral 150 mM; they do not contain the original DNA counterion excess. No field is used during these equilibration tests.

## Reproduction and analysis

Run scripts from the repository root using `PYTHONPATH=. .venv/bin/python ...`. Preparation scripts overwrite their own experiment inputs and are **not intended to be rerun while those simulations are active**. The source job directories are never output destinations.

- `prepare_full_probe.py`, `full_static_pressures.py`: full-system force/pressure probes.
- `build_controls.py`, `run_controls.py`: open pore, 100%/96%/92% water counts.
- `prepare_bulk.py`, `run_bulk.py`: bulk electrolyte density controls.
- `prepare_npzat.py`: snapshot/branch of the ongoing open-pore control, followed by NAMD using its generated `run.conf`.
- `prepare_full_npzat.py`: whole-system dry-state NPzAT intervention, followed by CPU NAMD using its generated `run.conf`.
- `resolvation_census.py`: reconstruct original and relaxed-geometry solvent site counts in the same box.
- `analyze_original.py`: parent DCD geometry/water diagnostics. Stage 01 is 240 ps; stages 02–04 are 480 ps each.
- `analyze_controls.py`: available complete DCD frames, pore hydration, bulk volume, pressure.
- `analyze_full_npzat.py`: full-system pore-plane counts, local void volume, wall geometry, box height.

Water-void estimates use a 0.4 nm grid and distance to the nearest water oxygen; they are geometric diagnostics, not a thermodynamic phase definition. `analyze_controls.py` excludes grid sites within 0.35 nm of graphene. The original whole-system diagnostic can include DNA excluded volume. The reported accessible-void values from `accessible_void.py` additionally exclude sites within 0.35 nm of DNA heavy atoms and graphene; both diagnostics are retained and labeled. Instantaneous pressure is noisy; block averages and normal-pressure components matter. A single static pressure evaluation is not an equilibrium measurement.

## Primary references checked

- NAMD 3.0 pressure controls: https://www.ks.uiuc.edu/Research/namd/3.0b3/ug/node39.html — `useFlexibleCell` + `useConstantArea` permits z-only volume equilibration; group pressure is required with rigid bonds.
- Li et al., *Ionic Conductivity, Structural Deformation and Programmable Anisotropy of DNA Origami in Electric Field*, ACS Nano (2015), author manuscript: https://api.repository.cam.ac.uk/server/api/core/bitstreams/75e87e28-cbcc-4e24-ace0-b8e6275a92d3/content — Methods describe reservoir contraction as origami hydrates and constant-area pressure equilibration for a restrained solid/origami hybrid, followed by fixed-volume current simulations. This supports the protocol rationale but does not establish the cause in this dataset.
- Cavitation mechanism: https://pmc.ncbi.nlm.nih.gov/articles/PMC5137690/ — background on vapor cavity formation in water under tension.

## Findings and review status

- Reproduced the original package count exactly: GROMACS 519616 waters; near-wall exclusion removes 4778; replacing 6619 waters with ions leaves 508219.
- Re-solvating the relaxed DNA/wall geometry with the same procedure would yield 505866 waters after ion replacement, so there is no evidence of an accidental missing-water list or a need to simply rerun the same solvation procedure.
- Source commit `4719cd999` disables barostats for fixed periodic graphene. `md_protocols.py` also sets `npt_allowed` false for graphene. This preserved the wall seam but leaves solvent density unequilibrated unless a separate compatible stage is provided.
- No application change has been implemented. The evidence and limitations are consolidated in [FINDINGS.md](FINDINGS.md); [REVIEW_PROPOSAL.md](REVIEW_PROPOSAL.md) specifies the proposed change. The final fixed-volume continuation completed 344 ps; the paired comparison uses the common +200 ps endpoint.

Additional direct evidence: the original parent `output/live_metrics.json` records step 116000 of stage 04 at 297.8581 K, instantaneous pressure −288.7402 bar and averaged group pressure **−462.3781 bar**. The archived run itself was under large negative pressure; this is not merely an inference from the local controls or a CPU-only diagnostic. CPU evaluation of its endpoint gives comparable negative pressure. Local full-system NPzAT starts with normal group pressure −374.493 bar and keeps the original lateral cell vectors fixed.

`hydration_transfer.json` measures water redistribution in the original trajectory: water oxygens within 0.4 nm of a DNA heavy atom increase from 42088 after minimization to 52076 after stage 04; water in the fixed pore-region cylinder (r<5 nm, −6<z−z_pore<1 nm) decreases from 15386 to 4436. These are spatial membership counts, not a claim that the same molecules all moved directly between the two regions.

Pressure analysis uses NAMD's `GPRESSAVG` interval-average column for run comparisons. Instantaneous `GPRESSURE` at an output cadence commensurate with the multiple-time-step force interval can alias the even/odd pressure oscillation; static snapshots and `GPRESSURE` tensors are labeled instantaneous; the separately printed `GPRESSAVG` tensors are interval averages. See the NAMD pressure-control documentation above. Early monitoring output used instantaneous samples; the current analyzer uses the interval-average column.

## Additional completed controls and independent-engine feasibility check

`bulk_statistics.py` summarizes the four completed 200 ps bulk controls after 50 ps, with 20 ps block means. The 4 fs / 4 fs-PME and 4 fs / 8 fs-PME equilibrated volumes differ little from the 2 fs result. `reservoir_clearance.py` measures the original DNA extents and axial periodic-image separations directly from coordinates.

`openmm_validation/` is an optional, isolated feasibility/energy check for longer full-system GPU dynamics. It does not change the application's engine. The open-pore static check reproduces NAMD's switched LJ energy within 0.1 kcal/mol and total energy within 0.013%; PME interpolation differs between engines. Two importer details were handled in the experimental script: an extra blank line is needed after the empty PSF NNB section, and parameters are reread after all atom types exist so permissive parsing does not skip NGRC's zero self-NBFIX. The uncorrected importer result is not physical evidence and was never used for dynamics. The experiment reproduces NAMD's r² switching function explicitly and disables OpenMM's dispersion correction. Full-system component energies and wall-restraint energy passed the documented validation before dynamics were used as evidence. Both 50 ps full-system branches completed; their engine differences and quantitative checks are recorded in `openmm_full/VALIDATION.md`.

Primary implementation references: [NAMD LJ switching source](https://www.ks.uiuc.edu/Research/namd/doxygen/ComputeNonbondedAlch_8h_source.html), [OpenMM CHARMM system API](https://docs.openmm.org/latest/api-python/generated/openmm.app.charmmpsffile.CharmmPsfFile.html), and [NAMD velocity units](https://www.ks.uiuc.edu/Research/namd/2.9/ug/node11.html). Binary NAMD velocities are multiplied by 20.45482706 to obtain Å/ps, or 2.045482706 to obtain nm/ps.

The original input hashes are in `input_hashes.json`; `application_diff.sha256` records the pre-existing tracked application diff. The tracked diff was checked unchanged during this investigation.

For NPzAT, only **normal pressure** is targeted; fixed-area lateral stresses can remain nonzero. A scalar average over all three directions need not equal 1 atm. The bulk NPT/NVT table concerns isotropic bulk pressure and should not be conflated with membrane lateral stress.

`prepare_wet_static.py` and the `full_wet_static*` directories compare the original 8 ps snapshot with all stage forces, without ENM, and without ENM or wall restraints. Original frame velocities are unavailable; all three static evaluations initialize the same 300 K velocities. Results are in `early_pressure_comparison.json`. They are not actual runtime pressure measurements. `plot_recovery.py` compares the available whole-system recovery traces, labeling the independent engine separately.

`accessible_void.py` excludes DNA/graphene-near grid sites before measuring local empty regions, and records connected components. `enm_virial.py` evaluates only the explicit network contribution across all saved restrained-stage frames; stage files were checked to have identical pairs and reference distances with the expected spring constants. Its 8 ps energy matches the NAMD force-toggle difference, and its direct virial agrees within 0.3% (the NAMD comparison also includes force/constraint coupling).

`namd_normal_pressure.py` reads the **GPRESSAVG tensor** where `outputPressure` was enabled. This is distinct from aliased instantaneous `GPRESSURE` tensors. The full NAMD run has mean averaged normal pressure −0.99 bar over 4–10 ps (15 intervals; interval SD 8.27 bar), while lateral stresses remain negative. Its cavity still persists. The earlier observation that instantaneous pressure tensors can alias does not prevent use of these explicit averaged tensors.

`branch_depleted_npzat.py` captured a consistent immutable 92% water restart at step 80000 (156 ps after minimization), then completed a 200 ps NAMD fixed-area/normal-pressure branch. The original GPU-resident fixed-volume segment failed at step 96012. `run_depleted_offload.py` restarts the fixed-volume comparison from the exact same immutable 156 ps checkpoint, using GPU force offload with CPU integration. Both branches use a 4 Å patch margin. Coordinates, velocities, cell, composition, wall force field and restraints match at branching; new-process stochastic continuations and execution-mode differences are documented limitations. Input hashes and parent time are in `open_pore/fill_92_npzat/meta.json`.

`depleted_comparison.py` compares the branches at equal +200 ps and verifies the initial binary file hashes. `plot_depletion.py` plots the complete available traces; `plot_depletion_density.py` displays the matched +200 ps spatial slices. The total void diagnostic avoids interpreting disconnected non-periodically-stitched component labels as separate physical bubbles. `wall_geometry.py` checks final wall position, pore rim and lateral cell vectors.

`audit_runs.py` requires an end-of-program marker, the intended final step, and no fatal error; exit status alone was not reliable for failed NAMD starts. `verify_preservation.py` checks 14 original input hashes and the pre-existing tracked application diff. Failed local attempts are retained and explicitly distinguished from completed scientific controls.
