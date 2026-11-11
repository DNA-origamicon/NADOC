# Central NAMD shell-damping pilot

User-requested experiment, 2026-11-10. No molecular document is authored or changed.
The exact input document is captured as `source-design.json`; simulation exports,
selection/source-index receipts, masks, native inputs, seeds and logs are retained.

Run, sequentially under the resource guard:

```sh
just validate-safe .venv/bin/python -m experiments.namd_submodel_damping.run SOURCE NEW_OUTPUT --binary NAMD
just validate-safe .venv/bin/python -m experiments.namd_submodel_damping.analyze OUTPUT
```

`--resume-production` reuses both completed preparation packages, requires an
unchanged source snapshot and production length, and skips recorded completed
trials. An existing failed trial's input/log are retained under `failed_attempts`.
The first campaign's initial production launch failed at configuration startup
because `reinitvels` does not replace NAMD's initial-temperature requirement.
The corrected pilot supplies `temperature 300` with no velocity file so the
configured seed draws velocities using the production HMR masses. The first
per-atom launch also rejected `langevinHydrogen off` alongside `langevinFile`;
the corrected file-based inputs omit both global coefficient/hydrogen options.

The box is centered on the source DNA bounds and measures 6.4 × 6.4 × 4.76 nm.
The surrounding retained DNA shell is 2 nm. The experiment compares a full-model
reference, a wholly fixed DNA shell, and a mobile DNA buffer at 0.1, 1 and 5 ps⁻¹.
All buffer conditions retain a fixed outer boundary containing every retained
residue involved in a bonded term crossing the extraction boundary. Buffer heavy
atoms have constant harmonic restraints of 0.1 kcal/mol/Å². This stiffness is an
experimental choice, not a validated DNA boundary parameter. The restraint
reference is the shared cropped-system relaxation checkpoint.

Core, water and ion heavy atoms use 1 ps⁻¹. Hydrogens and fixed atoms receive zero
in the per-atom Langevin file. Water and ions remain mobile, including those in
the geometric shell. Per-atom runs omit `langevinDamping` and `langevinHydrogen`;
this native build rejects mixing those global options with the file. Damping a fixed shell cannot
change its motion; the restrained mobile buffer makes this comparison meaningful.

Each package is minimized and relaxed for 20 ps at 2 fs. Production uses HMR,
rigid bonds, 4 fs steps, 300 K NVT, explicit TIP3P water and 150 mM NaCl (no Mg).
Two velocity seeds (77, 177) are run for 50 ps per condition. Every cropped
production condition starts at the same coordinates; full-model solvation and
preparation are independent. Therefore the full/cropped comparison also includes
preparation and solvent differences. This is a short screening pilot, not a test
of equilibrium equivalence or kinetic fidelity. Frame samples are correlated;
reported ranges are between seed-level means, not confidence intervals.

The as-built rectangular cells are not sized for arbitrary global rotation.
Analysis requires the DNA bounding-box gap to its periodic image to remain above
20 Å (twice the 10 Å cutoff) throughout every saved trajectory. This is a bounded
short-run check, not approval of these cells for long unrestrained simulations.

Analysis uses identical source-mapped core heavy atoms and topology-defined base
pairs. It reports aligned RMSD to the common ideal source and to each package's
initial checkpoint, aligned RMSF, core radius of gyration, base-pair contact and
angle metrics, paired C1′ distances, core-involving heavy-bond strain, local water
counts, temperature, finite-coordinate checks and exact fixed-atom drift. Means
and RMSF use the last 25 ps. Inputs and failed native attempts must be retained;
never lower the production timestep to conceal instability.

Native pressure is recorded as a preparation diagnostic. These packages have no
NPT density equilibration, and the cropped cases use `fixedAtomsForces off`;
their reported virial pressure is not an ambient-pressure validation or a
directly equivalent thermodynamic observable across boundary treatments.

## Pilot results (2026-11-10)

All ten 50 ps production runs completed at 4 fs. Analysis compares 3,457 identical
core heavy atoms and 84 designed base pairs. The table shows the mean across two
seeds of the last-25-ps mean; brackets give the two seed-level extremes, not
confidence intervals. RMSD is relative to the shared ideal source, after core
alignment. Pairing means all expected WC heavy-atom contacts are at most 3.6 Å.

| Shell treatment | Core RMSD (Å) | Core RMSF (Å) | WC contact fraction |
| --- | --- | --- | --- |
| Full reference | 3.072 [2.889, 3.254] | 0.712 [0.712, 0.712] | 0.961 [0.957, 0.966] |
| Fixed shell | 3.144 [3.117, 3.172] | 0.605 [0.590, 0.620] | 0.926 [0.925, 0.926] |
| Buffer 0.1 ps⁻¹ | 3.443 [3.414, 3.472] | 0.656 [0.633, 0.679] | 0.912 [0.908, 0.917] |
| Buffer 1 ps⁻¹ | 3.425 [3.390, 3.459] | 0.684 [0.667, 0.701] | 0.924 [0.917, 0.931] |
| Buffer 5 ps⁻¹ | 3.448 [3.432, 3.463] | 0.669 [0.657, 0.682] | 0.925 [0.922, 0.928] |

The 1 ps⁻¹ buffer's mean RMSF is about 4% below the full reference, versus 15%
below for the fixed shell. Buffer coefficients have overlapping seed ranges for
RMSF; these two seeds do not establish a unique optimum. The fixed shell's closer
ideal-reference RMSD is not evidence of better dynamics: it suppresses motion.
The buffer does not restore full-reference pairing, and all RMSD traces continue
to drift. The initial relaxed core already differs: 2.134 Å RMSD for the full
package versus 2.431 Å for the crop. Differences cannot be assigned solely to
production damping. All crop conditions share exactly the same initial coordinates.

Core RMSD relative to its own relaxation checkpoint averages 1.906 Å for full,
1.550 Å for fixed, and 1.873–1.893 Å for buffers. Paired C1′ means are
10.713 Å (full) versus 10.787–10.810 Å (crop). Core-involving bond strain p99 is
0.116–0.117 Å in all conditions. Local water counts are 3,297–3,314 compared with
3,302 for full. Mean temperatures are 296.99–297.73 K. These are comparable short
run diagnostics, not proof of equilibrium sampling. The stricter central
hydrogen-bond angle/distance fraction is recorded separately in `summary.json`.

All 500 saved frames contain finite coordinates. The smallest conservative DNA
periodic-image gap is 25.30 Å, above the predefined 20 Å threshold. Maximum fixed
atom displacement at the final native checkpoints is 1.59e-14 Å (numerical roundoff). Full production took
266–269 s per seed; crops took 74–81 s in the same GPU-offload mode. Atom counts
including solvent are 427,610 full and 138,871 cropped. These timings exclude
preparation and are not a general hardware ETA calibration.

**Decision:** keep production's general default at 1 ps⁻¹. A restrained buffer
at 1 ps⁻¹ is a reasonable candidate for longer validation, but this pilot does not
qualify replacing the managed fixed-shell boundary. The next controlled study
should first improve/match preparation and then vary restraint strength or shell
width, rather than optimize damping against a drifting 50 ps RMSD trace.

Evidence: `.development-artifacts/namd-submodel-damping-20261110/native/` contains
`experiment.json`, `execution.jsonl`, `analysis.json`, `summary.json`, per-frame
traces, RMSF profiles and `comparison.png`/`.pdf`, plus native packages and failed
startup attempts. The source SHA256 is
`ed66edb4eadd0475c174113cd139faaa214381907ca171026cab56ca8cb6be26`.

Software verification: 140 focused backend checks, 404 focused frontend checks,
10,190 full frontend tests (883 files; one skipped), the real browser save/create/
reopen/central-box visual check, all 25 smoke checks, and lint passed. Browser
scratch and reports were removed; source files remained unchanged. `main.js` LOC
delta is zero. Backend `test-smart` chose FAST: 20,685 passed, 90 skipped, two
failures outside these checks (the prior CPD contract failure and a VR-tour
subprocess-mock race that passed alone). The full suite remains deferred in
`.nadoc-slow-pending`. Aggregate FAST wall time was 198 s with no individual
five-second violator; timing evidence was reviewed without raising limits.
See the parent evidence directory's `verification.json` and validation logs.
