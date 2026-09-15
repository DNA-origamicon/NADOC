# Managed GPU electrode corrections

NADOC's local runner now selects the validated GPU correction automatically for
resident two-electrode dynamics when the installed NAMD binary matches the plugin
ABI checksum. This applies to newly prepared relaxation, production children and
restarts through the shared runner. Minimization retains the existing CPU callback.
Explicit offload remains available with the same force model.

The canonical CUDA source is `backend/core/native/electrode_gpu.cu`; package
conversion, validation and fallback live in `backend/core/namd_electrode_gpu.py`.
The registered local build is `workspace/runtime/electrode_gpu/`. Its binary is a
copy of the audited `workspace/electrode_gpu_plugin_final` library; no installed
NAMD executable was replaced. Build for a different engine/host before registering
it; copying the current library to an arbitrary NAMD build is not supported.

```bash
uv run python experiments/electrode_relax/gpu_correction/build.py \
  --source /path/to/NAMD_Source --output workspace/new_gpu_build
# After the force/energy and native validation described in the prototype README:
uv run python -c "from backend.core.namd_electrode_gpu import install_build; install_build('workspace/new_gpu_build')"
```

`NADOC_ELECTRODE_GPU_DIR` can select another validated registry directory. Registry
location is host configuration, not a `.nadoc` part setting. Hosts without a matching
registered plugin retain the reference callback and record the reason in the
package manifest. The current registration/build script targets the local CUDA
12.0/GCC 12/sm_86 installation; it does not auto-compile inside a job launch.

## Package and restart contract

- Each job receives its own `electrode_gpu.so` and `electrode_gpu.params`.
- Manifest `electrode_gpu` pins the engine, plugin, parameters, reference callback
  and stage topology checksums. HMR topologies must retain identical atom charges
  and ordering. Changed/missing inputs fail before launch with a named cause.
- Reference CPU configs are retained as `.conf.cpu-reference`. GPU configs remove
  the CPU callback so forces are applied exactly once. Unknown Tcl callbacks,
  unsupported barostats and ambiguous initialization are rejected.
- NAMD dynamically loads `./electrode_gpu.so`: the explicit relative directory is
  required by the dynamic loader. Parameters are package-local and survive copies.
- `gpuGlobalCreateClient` initializes NAMD. It belongs immediately before `run`,
  after all restart, output and integrator settings. The ordinary continuation
  writer reorders it after adding new restart settings.
- The native plugin checks neutrality, atom count, finite parameters, resident
  mode and fixed-cell operation. The runner validates a single-GPU target and the
  recorded engine ABI on resume. An accepted resident-to-offload fallback restores
  the reference callback and archives GPU configuration/provenance before the
  existing integrator fallback runs; it cannot silently discard surface forces.
- The selected tuning is `GPUAtomMigration on`, `twoAwayZ on`, default margin.
  NAMD labels GPU atom migration experimental. Multiple GPUs/distributed operation
  and variable-cell virials are not qualified by this implementation.

The force model remains fixed-charge EW3DC slab correction, repulsive walls and
harmonic anchors. It is not a constant-potential gold-electrode model. Long-time
DNA/PEG qualification and remote-host installation remain separate work.

## Managed 4 fs screening validation

The campaign in `workspace/electrode_gpu_screening_4fs_20260914/` starts each job
through `/api/md/jobs/{id}/start`, rather than launching an unmanaged NAMD process.
Jobs are retained against `2electrode_solvent_only.nadoc` and visible through the
ordinary jobs API. The 38,644-atom 6 nm gap checkpoint has unchanged coordinates,
charges, water/ion masses, salt inventory, temperature, cutoff and PME spacing.

A 240 ps 4 fs pilot passed, followed by two separately seeded trajectories targeting
4.8 ns each and a 1.2 ns 2 fs control. The trajectories share an initial prepared
state; they are not independently equilibrated replicas. The pilot precedes series
A, which therefore ends at 5.04 ns of additional time; series B ends at 4.8 ns.
No water HMR is applied: the existing HMR policy only repartitions non-water H,
and this solvent-only system has none. Rigid water is retained. PME updates every
4 fs in both cases (`fullElectFrequency 1` at 4 fs, `2` at 2 fs), and frames/energies
are saved every 2 ps. Pilot throughput was ~477 ns/day on the RTX 3080 Ti.

The analysis cross-checks segment timesteps against DCD headers, preserves restart
lineage and uses physical-time windows. NADOC's stationarity gate now retains the
last 600 ps regardless of output cadence; the old 60-frame gate would have shrunk
to only 120 ps with denser output. Separate 300/600/1,200 ps block fits, central salt,
ionic compensation, descriptive autocorrelation/effective-frame counts, bootstrap
uncertainty and explicit-water planar potentials are saved. More saved frames are
not counted as independent samples. Matched 0.24–1.20 ns comparisons are separate
from full-series pooled fits.

Water translation/rotation temperatures are monitored from complete NAMD restart
velocities using the engine's internal energy units and water molecular centers of
mass. They are a timestep diagnostic, not a local dielectric measurement.
[Asthagiri et al.](https://arxiv.org/abs/2412.03448) report timestep-dependent rigid-water
volume, dielectric and hydration behavior; thus normal native exit at 4 fs does not
establish unbiased Debye screening. The matched control and physical-time sampling
must be considered before making that claim.

Current numerical results and plots: the campaign README and `comparison.json`.
This does not silently redefine global timestep defaults or promote a screening
fit to a production qualification criterion.

## Verification and encountered barriers

- Force/energy equivalence and CUDA memory/race audits are retained from the GPU
  prototype. Managed jobs use the same plugin and parameter SHA-256.
- Unit tests cover GPU ownership, initialization ordering, checksum failures,
  unknown callbacks, CPU fallback and unavailable-plugin reporting.
- A real managed launch found the missing `./` loader prefix; it was fixed before
  scientific dynamics. The failed probe evidence is retained.
- Native process adoption could match shell command text mentioning a NAMD config.
  `namd_process.py` now recognizes executable/config arguments, preventing the
  controller itself from being mistaken for NAMD. A regression covers that case.
- Backend FAST verification: 8,397 passed, 110 skipped, nine known missing-fixture
  failures (`BigO.nadoc` and `smallO-poly.nass`). Full-suite deferral is recorded in
  the campaign report. Nine analysis tests additionally pass. Repository lint
  retains two existing oxDNA findings; scoped changed-code lint passes. No frontend
  code changed in this task (`main.js` delta 0).

The existing interactive Surface ions/screening popup still supports only its
single-wall model and returns 409 for two-electrode jobs. This was verified against
a completed managed job. Finite-gap validation graphs are retained as campaign
artifacts; porting that analysis into the popup is a separate UI gap, not silently
approximated by folding the two interfaces into the old normalization.


## Completed managed screening campaign

All ten Start-API jobs completed and remain in the jobs list for
`2electrode_solvent_only.nadoc`: 9.84 ns at 4 fs and a 1.20 ns 2 fs control.
All native/confinement/density/runtime-stationarity gates passed. Throughput is
~475 ns/day at 4 fs versus ~294 ns/day at 2 fs. The ordinary restart writer also
passed an isolated 20-step native checkpoint-resume test.

Pooled screening fits at 0.6 nm exclusion are 0.519 and 0.597 nm for the two 4 fs
series and 0.604 nm for the short 2 fs control. Window variability remains too large
to claim convergence. Water translation/rotation temperatures average 300.18/294.18 K
at 4 fs and 300.25/298.93 K at 2 fs; velocity-derived kinetic energies agree with
NAMD logs to 1.02e-8 relative error. This timestep diagnostic does not quantify the
screening bias. Extend the 2 fs control before claiming quantitative equivalence.

Final evidence: `workspace/electrode_gpu_screening_4fs_20260914/README.md`,
`comparison.{json,png,pdf}`, `native_summary.json`; restart evidence:
`workspace/electrode_gpu_managed_resume_validation/result.json`.

## Remote hardware validation (2026-09-14)

The 40 ns local validation was duplicated onto Alpine and RunPod using the exact
checksum-pinned local executable/plugin, packaged with an isolated Linux loader and
runtime libraries. This avoids replacing the default engines used by unrelated jobs.
Alpine's glibc 2.28 required libdl/pthread/rt companions in addition to the libraries
reported by `ldd`; omission initially surfaced as a misleading CUDA driver-version
failure. With those supplied, Blackwell's driver JIT runs the existing PTX.

Each remote validation executes an 80 ps GPU-resident probe, independent arithmetic
force/energy audit, and 20-step checkpoint restart before its 40 ns segment. Alpine
RTX PRO 6000 passed (force error ~1.2e-15, energy error ~4.5e-13; final restart step
20020) and started production. The first probe-only restart test omitted firsttimestep;
that generator was fixed and the failed probe evidence retained before production.

RunPod PRO 6000 and 4090 were unavailable against the existing network volume. The
user changed RunPod selection to an available comparable-price GPU with a $5 cap;
an initial PRO 4500 rental hit a tar ownership error and was terminated for $0.0354.
Extraction now uses `--no-same-owner`, and a retry obtained an RTX 4090 at $0.74/hour.
It passed force/energy (1.42e-15/0 error) and restart-to-step-20020 probes, then started
the 40 ns run at ~750 ns/day. The earlier spend is deducted from its $5 deadline.
Qualification/running status lives
in `workspace/electrode_remote_40ns_20260914/`. The provider deadline and independent
watchdog bound this single rental, and terminal detection reaps it without waiting
for a full DCD transfer. Results remain on the existing persistent volume.

These are explicit runtime-bundle validation submissions. Ordinary remote engine
selection and general Slurm requeue/RunPod resume conversion are not yet promoted to
this engine; do not infer qualification for arbitrary remote jobs from these runs.
The exact configurations, initial checkpoints, provenance, probes and remaining
barriers are documented in the campaign README. No water masses, salt, surface
charges, geometry or timestep were changed between the three 40 ns duplicates.

## Historical data location

On 2026-09-14, 24 earlier electrode job folders were moved out of the active
workspace into `/media/jojo/Archive/NADOC_electrode_history/2026-09-14/jobs`.
Their complete data remain available; eight checkpoint ancestors stay indexed,
while 16 other historical catalogue entries are retired/restorable. Analysis job
lists and benchmark links were updated. The three active 40 ns jobs remain in place.
See [archive inventory and recovery](namd_electrode_archive.md).


## Completed 40 ns remote validation and screening analysis (2026-09-14)

Both remote runs completed 10,000,000 steps with normal native exits and 20,001
finite energy records. The user configured podless S3 access; RunPod's 36 selected
output files (9.32 GB) were retrieved to Archive media without a running compute
pod. Remote sizes and the complete 20,000-frame DCD time axis were checked; local
SHA256 hashes are recorded. Total RunPod compute spend including failed staging
and the cancelled transfer attempt is $1.074943, below the $5 budget.

RunPod's 40 ns ion-ratio screening fit is 0.551 nm (0.528–0.580 nm conditional
300 ps block bootstrap interval), versus a classical 0.539 nm using central ionic
strength 319.8 mM and assumed dielectric 78.3. The local 40 ns fit is 0.553 nm.
Separate RunPod 10 ns fits span 0.527–0.572 nm; last-20-ns fit is 0.556 nm.
Block-duration sensitivity through 2.4 ns supports the broad comparison. This is
encouraging Debye-like ion screening, not complete validation of the near-wall
microscopic potential, water-model dielectric, or the known 4 fs water-mode bias.

Alpine's trajectory is fully downloaded and SHA256-verified (47 files, 9.344 GB).
Its separate-window analysis and job/report publication are complete. Current
report, plots and detailed limitations:
[40 ns screening results](../workspace/electrode_remote_40ns_20260914/RESULTS.md).
The report updates automatically after Alpine processing. The private cached
analysis was checked against the original calculation and cached replay: all
scientific JSON values matched exactly on a 2,500-frame reference window.

Processing also exposed two bookkeeping barriers: a missing completed status in
the local analysis manifest, and overlapping non-atomic Alpine monitor writes
that left a trailing brace in job.json. Both affected records were repaired;
the obsolete monitor was stopped and corrupt evidence retained. General concurrent
job-save hardening remains separate application work.

The complete experiment history and literature assessment are in
[Debye screening assessment](namd_debye_assessment.md). Alpine full-40-ns fit is
0.575 nm, with a decreasing 10 ns-window trend and last-20-ns fit 0.547 nm.
