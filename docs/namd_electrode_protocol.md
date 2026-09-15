# Electrode relaxation protocol

The wizard offers **Electrode relaxation (fixed cell)** (`electrode`, engine protocol
`electrode_equilibration_namd`). New relaxation wizards select it when Two-electrode
system is enabled. Existing jobs retain their saved protocol. Starting, queuing or
resuming an older-protocol job with the electrode setup enabled asks for confirmation;
Continue runs the saved job unchanged, including its original surface configuration.

## Shared stages and physical controls

1. Prepare the fixed electrode compartment with full CHARMM DNA topology when DNA
   is present, optional methyl-capped CHARMM ether PEG, explicit water, ions and exact
   charge-neutrality audit. Rigid centering preserves internal DNA coordinates.
2. Calibrate a separate 5 nm cubic bulk electrolyte reference at the same salt and
   temperature: minimization, 25 ps NVT, then 500 ps NPT at 1.01325 bar. Require at
   least 100 late volume samples, <=1% relative drift and <=2% fluctuation. These
   are initial engineering thresholds, not universal equilibration guarantees.
3. Minimize the actual compartment. With DNA, run the shared restrained-solute settle
   stage at NVT before the normal ENM release ladder. DNA-free controls use one
   solvent/PEG equilibration rung. Standard p10/p25/p50/p75/p100 checkpoints remain.
4. Preserve fixed-volume PME + EW3DC, confinement and harmonic electrode/PEG graft
   restraints through every rung. Electrode site spring k=10 and PEG graft k=5
   kcal/mol/Å² use U=½kΔr². The barostat acts only on the separate bulk reference.

Default dynamics use 2 fs; existing fast/HMR settings remain selectable but require
native qualification with this new force implementation. A 4 fs PEG result from
another wall implementation does not establish this protocol's 4 fs validity.

## Skip and completion checks

Existing energy/WC criteria remain necessary where applicable. Electrode skips also
require >=20 paired trajectory samples, cumulative water/ion-profile stationarity
(0.10 maximum fraction difference, >=200 observations per present species per half), confinement,
a bulk-like water density within 5% of the measured NPT reference, and PEG radius-of-
gyration stationarity when PEG is present. The bulk-like region is at least 1 nm from
walls and solute heavy atoms; its accessible volume is estimated on a 0.3 nm grid and
must be >=5 nm³. Missing evidence prevents skipping. These numerical criteria need
native sensitivity testing before treating a pass as scientific validation.

Reports are written to `output/*.electrode-health.json`; the NPT reference and its
logs/results live in `bulk_reference/`. Finishing the allotted dynamics without passing
the compartment checks produces an explanatory failure, not a false equilibration pass.
Ion-profile stationarity is not itself a fitted Debye length or proof of correct screening.

## Current boundaries

- DNA and PEG must fit with clearance; overlapping initial PEG/DNA is rejected.
- PEG supports a square patch, 1–64 chains, 1–100 EO repeat units, and the pinned
  methyl-capped CHARMM ether chemistry. It grafts to the lower/working electrode.
  Other shapes, chemistry notes/references and coarse-grained PEG are rejected.
- Set `NADOC_PEG_ETHER_ASSETS` to the pinned ether asset directory if the local
  `workspace/peg_wall_validation/assets/toppar_ether` installation is absent.
- An extended PEG seed that does not fit must be shortened or given more space;
  randomized/MC seeding is not implemented.
- Vacuum/BLADE coordinate seeds are explicitly rejected by this adapter.
- Walls are surrogate fixed-charge sites, not gold or constant-potential electrodes.
- Native qualification remains pending. Successful package generation is not a
  demonstrated relaxation, GPU-resident pass, or proven skip acceleration.

## Local comparison campaign

`experiments/electrode_relax/validate.py` prepares four matched cases: no solute,
a 12-bp duplex, PEG only, and DNA plus PEG. Current prepared artifacts are under
`workspace/electrode_relax_validation_20260913_v2`. This duplex is a bounded DNA
integration check; it does not establish convergence for a full origami.

After a user opens `just test-session`, native execution goes through:

```
scripts/test_guard.sh electrode-relax-validation 0 1 -- uv run python -m experiments.electrode_relax.validate --output workspace/electrode_relax_validation_20260913_v2 --run
```

The campaign uses the managed runner with skip acceleration enabled, records native
job IDs/statuses/skipped chunks in `validation.json`, and retains native job artifacts.

## Validation status (2026-09-13)

Four approximately 49,000-atom packages were prepared with real solvation/topology
builders: solvent only, DNA, PEG, and DNA plus PEG. Native execution was refused by
`scripts/test_guard.sh` because the user-opened test session was expired. None of
these packages establishes successful dynamics or skip acceleration yet.

Frontend unit tests: 6,400 passed. Focused browser checks: four passed, followed by
one passing wizard recheck after exposing the bulk-reference stage. Smoke: 22 passed;
one assembly console-error assertion failed on `/api/mrdna/jobs` HTTP 500, traced to
the existing concurrent mrDNA job-file save race. Prefixed browser documents and
exact electrode draft jobs were removed by teardown.

Remaining native qualification includes callback force/energy checks, GPU-resident
compatibility, paired with/without-DNA convergence, skip-on versus skip-off agreement,
4 fs/HMR stability, vacuum-padding sensitivity, and interrupted bulk-reference
recovery. A 500 ps reference or allotted confined trajectory may require extension.
Production retains the fixed-cell forces and reports health without requiring a
stationary profile, since externally driven production can intentionally evolve.

Final fast backend selection: FAST; 8,329 passed, 110 skipped, nine failures from
missing BigO/smallO workspace fixtures in assembly flattening/CanDo tests. The seven
focused electrode protocol tests passed. Lint has zero new findings (two existing
oxDNA findings remain); `git diff --check` passes. This task adds zero main.js lines.

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

### Solvent-only launch repair

Job `8395d215579b` exposed duplicate `outputEnergies` and `XSTfreq` startup directives
in the separate bulk reference. NAMD rejected its configuration before dynamics.
The renderer now replaces the template directives; the persisted job configuration
was repaired with a backup. Reference failures expose NAMD ERROR/FATAL details.
The GPU probe passed on the original launch; this does not validate reference or
confined dynamics. The subsequent native campaign below exercised the repaired reference and confined dynamics.

### Native validation loop repairs

- Bulk minimization, NVT heating and NPT now run in separate NAMD processes.
  `rigidBonds` and the barostat are startup controls, not changes within a running
  Tcl script. Restart coordinates/velocities link the phases.
- Electrode force directives precede adaptive Tcl minimization loops as well as
  ordinary `run` commands. The earlier GPU probe omitted these forces and was
  invalidated; the corrected probe passed.
- Water clearance is applied to TIP3P oxygen centers while retaining whole waters.
  Applying the same carbon/oxygen exclusion to hydrogens over-carved the solvent;
  a native control caught a central density outside the existing 5% tolerance.
- An optional compiled Tcl extension evaluates the same EW3DC, confinement and
  harmonic site/graft forces. It uses CPU callbacks with CUDA dynamics; this is
  not a GPU-resident qualification. `g++` and a Tcl 8.6 SDK enable compilation.
  `NADOC_TCL_SDK` can identify the SDK prefix; without one the reference Tcl callback
  remains available. Prepared packages include the library, and production copies
  retain it. Runtime load failure falls back to the reference callback.
- Compiled/reference force tests cover all axes, penetration and harmonic springs.
  A perturbed 6,005-atom test had zero maximum force difference and ~2.6e-13 kcal/mol
  energy difference. A short NAMD comparison matched initial energies and reduced
  callback cost. Long stochastic trajectories are not expected to match pointwise.

The 10 nm liquid case `8395d215579b` completed the bulk reference but was paused
because the full per-atom callback is expensive. Bounded 4 nm liquid controls use
identical salt, temperature, timestep and convergence tolerances. Underfilled case
`7cadeb7e6724` is stopped and retained as diagnostic evidence; corrected case
`89af63c3abb7` is the active completion validation. See the persistent record at
`workspace/2electrode_solvent_only_validation/README.md` for final status.

Solvent-only Display MD now handles an empty DNA selection by centering the periodic
cell rather than attempting a DNA pose fit. Real-job Playwright playback passed:
1,804 water molecules and 10 Na / 10 Cl render between the signed planes, with
the vacuum-padded cell visible. Source document bytes remained unchanged.

Solvent-only electrode stages no longer advertise DNA ENM restraints. Production
requires a completed run and a passing electrode checkpoint report, including for
legacy manifests whose empty DNA stage inherited an ENM scale. Failed convergence
messages identify the measured species drift or density mismatch.

Remaining analysis barrier: the existing Surface Ions and Screening calculator
currently accepts only the single-wall geometry. Two-electrode relaxation health
profiles are recorded, but the interactive Debye-fit/export calculator needs a
two-electrode adapter before it can be used for this control.

Electrode stationarity now compares the halves of the latest 60 saved frames of
one physical rung, using preceding chunks where needed. This matches the standard
energy check's recent-window semantics: an initial transient must not permanently
prevent a later equilibrated state from qualifying. Reports retain total/discarded
frame counts and source segments. The minimum 20 samples, 0.10 profile drift and
5% density tolerances are unchanged; density and PEG size use the same recent
window. Confinement still checks every sampled frame. No Debye fit is implied.

Completed dynamics with unmet electrode criteria now has failure kind
`electrode_equilibration`. The job's Fix popup can append 2.4 ns from the final
coordinates, velocities and cell through
`POST /api/md/jobs/{id}/extend-electrode-equilibration` (`duration_ns`, 0–100 ns).
The endpoint queues at most 1.2 ns per chunk; Start launches it normally. It retains
the original topology, salt, temperature, integrator and force directives, and
records independent thermostat seeds and prior validation in `electrode_extensions`.
It refuses running jobs, missing checkpoints, confinement failures and density
mismatches. Production stays gated. Normal exit and worker-recovery completion
both recompute the same electrode check, so recovery cannot bypass qualification.

Playwright verified solvent playback in full, ball-and-stick and VDW modes and the
continuation popup with a display-only failure example. The actual primary run control was then exercised on the retained failed job: it
appended and launched 2.4 ns through the main backend without preparation or
minimization. All seven chunks finished normally at 7.2 ns, but final Na/Cl cumulative drift (0.1367/0.1167) exceeds 0.10. Density and confinement pass; no chunks were skipped. The job remains failed for equilibration, and production is blocked. The passing 6 ns checkpoint is retained without substituting it for the final verdict. The latest full backend selection
has 8,349 passes, 618 skips, one expected failure and nine baseline missing-fixture
failures; frontend has 6,402 passes. All 23 smoke checks passed during the earlier idle
interval. A subsequent smoke run passed 22/23: the assembly-exit console gate caught
an unrelated mrDNA job-state temporary-file rename HTTP 500. Temporary workspace
objects were removed.

### Sparse-ion stationarity correction

A seeded null-control experiment (1,000 independent stationary profiles, 10 ions
per species, 60 frames, 20 bins) exposed a 99.6% rejection rate for the original
binwise total-variation gate. The full-size 164-ion control did not suffer this
problem. The gate now uses the maximum difference of cumulative species fractions
from the wall to each bin edge, retaining total variation as a separate diagnostic.
The cumulative-distance definition follows the statistic described by
[SciPy's two-sample KS documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html).
We do not use an independent-sample p-value: trajectory frames are correlated.
This remains a stationarity heuristic, not proof of equilibrium or Debye screening.

The numerical cutoff remains 0.10, but the statistic changed; the old TV reports
and new cumulative-profile reports are not interchangeable. The new null-control
acceptance was 905/1000, while deliberately shifted controls were rejected. Each
present species also needs at least 200 observations per half-window; fewer are
reported as insufficient evidence and can be addressed by extending equilibration.
Density (5%), confinement and PEG checks remain independent and unchanged.

Saved-trajectory playback was also exercised on the retained control: 38 sampled
frames across seven segments loaded, with 20 ions rendered inside the signed
electrodes. Water is intentionally available in Display MD only; the trajectory
mode currently loads ions and the cell. Browser artifacts were removed and the
source document was unchanged.

The focused assembly-exit retry reproduced the same unrelated mrDNA temporary-file
rename HTTP 500; the latest smoke gate is not green. All prefixed workspace
artifacts were cleaned. Native continuation is prepared but remains unlaunched
because the user-opened session marker expired at 23:11.

### Short lateral-volume screening (2026-09-14)

User-requested native screening ran without a test-session marker, under the clarified
CLAUDE.md distinction between simulation tasks and automated heavy test suites.
Three 240 ps controls used 4/6/8 nm lateral sides, fixed 4 nm gap, 300 mM NaCl,
300 K, 2 fs, and identical realized electrode charge density. They contain
10/22/39 ions per species. All exited normally. Retained jobs are `f6eb2e7aba9b`,
`435c4334ce18`, and `222963230bfc`, associated with the user's original document.

Last-120-ps Na/Cl cumulative drift decreased from 0.093/0.080 to 0.053/0.064 to
0.044/0.056. Subsampling the 39-ion case to 10 fixed ion identities raises median
drift to 0.117/0.128, supporting a count benefit within this trajectory. This is
one seed per size, not an equilibrium or independent-replicate result.

Remaining barriers: the larger cases fail density (6.54% and 5.65% below reference),
while the small case barely passes (4.99%). A 60-frame gate spans 120 ps at this
screen's cadence versus 2.4 ns previously; qualification needs physical-time and
correlation-aware sampling semantics before short-screen passes are reused.
The completed small job represents only its explicitly shortened screen, not full
relaxation. No production or longer continuation was launched.

Seven isolated 1,000-step timings from the 8 nm checkpoint exited normally. Standard
GPU offload takes about 24 ms/step; GPU-resident with one worker takes 16.36 ms/step
(~1.46x faster). More CPU workers did not help. Coordinate conversion and compiled
force submission through Tcl account for roughly 70% of step time. Long resident
validation remains open; larger speedups require reducing this callback overhead
or an engine-native/GPU force implementation, preserving EW3DC and wall forces.

Detailed profiles, count-subset diagnostics, timings, logs and reproducible scripts:
`workspace/electrode_volume_screen_20260914/README.md`.

### Resident default and direct-array prototype

New electrode preparations resolve GPU mode `auto` to `on`; explicit `off` remains
available for comparisons. The native experimental driver uses one CPU worker.
Minimization keeps the established offload startup path. Existing saved jobs are
not rewritten. Runtime resident compatibility probing and fallback decisions remain.

An isolated custom NAMD build now provides `nadoc_native_electrode`, reading gathered
coordinate arrays and writing native force arrays without per-atom Tcl objects.
At 24,677 atoms, resident timing improves from 17.721 to 2.674 ms/step. Three-axis
force/energy checks with active wall repulsion and a displaced spring match exactly
for every atom. A 40 ps resident trajectory exits normally, with finite energies and
coordinates, confinement retained, and mean temperature 299.32 K. The installed
engine hash is unchanged. This is a CPU native-array bridge, not a GPU force kernel.

Prototype and reproducible build/validation scripts:
`experiments/electrode_relax/native_bridge/README.md`.
Explicit experimental jobs can now record an engine path and SHA-256 in matching
job/package provenance; adoption and restart verify and use that binary. Callback
selection remains explicit in the experimental package. Remaining barriers:
long-run/statistical validation, DNA/PEG qualification, distributed/multi-GPU use,
and any native GPU reduction/kernel implementation. The existing density and
physical-time stationarity-window concerns are unchanged.

Verification for the resident-default change: `just test-smart` selected FAST;
8,371 passed, 110 skipped, nine known missing BigO/smallO fixture failures. Lint
retains only the two existing oxDNA findings. `git diff --check` passes. Main.js Δ0.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

No heavy automated suite was launched; user-requested native experiments are
separately authorized under the clarified test-session rule.


## Longer resident Debye diagnostic (2026-09-14)

`workspace/electrode_debye_validation_20260914_v2/README.md` records the completed
2.64 ns solvent-only campaign: 8 × 4 × 8 nm liquid, 25,839 atoms, 41 Na/Cl pairs,
±16 e electrodes, 300 K, 2 fs, direct-array experimental NAMD and one resident worker.
All three retained jobs (`c6d0bcfc861d`, `e04b05b6df8a`, `df270bd5872a`) complete with
finite energy, confinement, density 33.13–33.17 nm^-3 and passing profile gates.
An equilibrated bulk-water seed plus explicit experimental oxygen clearance 0.22 nm
resolves the density failure in this geometry. Default 0.32 nm still fails the
matched control; the general preparation default remains unchanged.

Pooled ion-ratio length 0.573 nm is close to classical 0.536–0.605 nm from measured
central 324 mM and assumed dielectric 78.3–100. It is not converged: separate chunks
fit 0.405 and 1.745 nm, and the final chunk is sensitive to exclusion/bounds.
The current 10% stationarity gate is insufficient to establish Debye agreement.
Exact all-charge planar potentials, finite-inventory PB, physical-time windows and
block diagnostics are retained by `experiments/electrode_relax/debye_analysis.py`.
The full electrode ladder, DNA/PEG, salt scaling, dielectric and finite-gap/padding
sensitivity remain unqualified. Frontend two-electrode screening analysis remains
separate work. This campaign does not authorize production from the earlier failed
jobs or replace the installed NAMD binary.

Experimental engine adoption now checks matching job/package path and SHA-256 via
`namd_experimental_engine.py`; an incompatible installed-engine probe can no longer
silently substitute for an explicitly recorded candidate. Verification: FAST
8,378 passed, 110 skipped, nine known missing-fixture failures; FULL deferred as
quoted above. Five focused screening-analysis tests and two engine-provenance tests
pass. Lint retains two existing oxDNA findings; main.js Δ0.


## Larger gap control (2026-09-14)

The matched 6 nm gap control completed 2.64 ns with the same 8 × 8 nm electrode
area, ±16 e, 300 mM target, 300 K and 2 fs resident direct-array engine. It has
38,644 atoms/64 pairs and an 8 × 18 × 8 nm padded cell. Jobs bf1562116993,
f4bbd57fbd5b and 2fb3c67ae5d9 are retained under `2electrode_solvent_only.nadoc`.
All native/density/confinement/profile gates pass (density 33.170–33.179 nm^-3).

Fit identifiability improves, not full convergence: chunk λ=0.580/0.819 nm versus
4 nm control 0.405/1.745; pooled 0.685 nm versus classical 0.551–0.623 nm from
measured central concentration and assumed εr 78.3–100. Central concentration
falls 343→269 mM between chunks. The all-charge central field remains too noisy
to establish negligible overlap; ionic compensation above 100% is not yet an
overscreening claim. See `workspace/electrode_gap6_validation_20260914/README.md`
for graphs, physical-time diagnostics, remaining controls and performance limits.

Dynamics took 86.3 minutes (~44–45 ns/day sustained). GPU utilization sampled
27–29%; the native bridge still gathers coordinates and evaluates corrections on
CPU each step, and PME includes the padded vacuum. The archived local DNA
31,790-atom/4 fs benchmark reports 392 ns/day but is not a matched control.
A GPU-native correction remains the major implementation direction. This campaign
changes no installed engine or production defaults. Six focused analysis tests pass.

## GPU correction implementation (2026-09-14)

The CPU gather/correction/scatter bottleneck above now has an explicit experimental
GPU replacement: `experiments/electrode_relax/gpu_correction/`. It uses the existing
NAMD dynamic CUDA client interface for the slab moment, repulsive walls and harmonic
anchors; coordinates/forces stay on device. The installed engine is unchanged.
Scalar energy output and the NAMD server's per-step stream synchronization remain.

Three-axis active-wall/tether and normal-system audits agree with independent
NumPy and direct CPU calculations. Configuration tests prevent duplicate CPU/GPU
corrections and enforce initialization ordering. Native benchmarks retain the
38,644-atom 6 nm gap checkpoint, 2 fs timestep, PME grid spacing and vacuum padding.
See the module README and `workspace/electrode_gpu_benchmark_final/results.json`
for longer matched timings and post-migration force audits. GPU atom migration and
patch splitting are explicit experimental tuning choices; more CPU workers and
fused kernels did not provide a consistent gain in the first screen.

This qualifies a fixed-cell solvent benchmark path, not the complete relaxation
ladder or Debye convergence. GPU plugin/parameter provenance in managed application
continuations, minimization, DNA/PEG, variable-cell virials, multi-GPU and long-time
transport remain separate barriers. No ordinary production default is changed.

Final matched GPU benchmark: 254 ns/day without tuning, 291–297 ns/day with
GPU atom migration + twoAwayZ, versus 43.1 ns/day CPU at the same 2 fs (6.8–6.9×).
Four 120 ps GPU endpoints pass force/energy audits; these do not establish Debye
convergence. Details: `workspace/electrode_gpu_benchmark_final/README.md`.

## Managed GPU adoption and denser 4 fs validation

The prototype is now integrated into the local job runner, including package-local
plugin/parameter checksums, restart initialization ordering and force-preserving
explicit offload fallback. See [managed GPU electrode corrections](namd_electrode_gpu.md).
The ordinary Start API is running retained 4 fs solvent screening jobs with 2 ps
frames, independent Langevin streams and a 2 fs control. Analysis now uses actual
DCD/manifest timing and physical-time blocks; the electrode health gate retains
600 ps rather than a cadence-dependent 60 frames. Native stability is distinct
from Debye agreement and timestep-independent solvent response.
