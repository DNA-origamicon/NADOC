# Streptavidin CPU/GPU remote validation campaign

Authorized September 13, 2026: GPU on RunPod (prefer RTX 4090), CPU on Alpine,
**$15 cumulative RunPod limit**, including failed attempts. This is the initial
nine-case validation suite, not the extended million-step suite.

## Frozen inputs

`workspace/validation/strep_remote_20260913/manifest.json` records input SHA-256
hashes, three geometries (5 nm adsorbed gold, 10 nm adsorbed gold, 10 nm
biotin-tethered gold), and three seeds (101, 202, 303) per geometry. Every case
has one 484-residue tetramer and one 16-base biotinylated DNA strand.

Each backend runs an activated-force NVE probe, 100 CPU Monte Carlo sweeps,
100,000 MD relaxation steps and 100,000 uncapped equilibration steps. MD dt is
0.0001. The portable worker rejects nonfinite coordinates, incorrect bead
counts and core penetration in both final configurations and saved trajectory
frames. The final CPU/GPU statistical and force-response comparison requires
both sets of results; merely finishing a job is not that comparison.

CPU and GPU engines are compiled from the same frozen source archive, including
the local NADOC changes. Alpine uses GCC 14.2.0 and CMake 3.31.0; RunPod compiles
CUDA for the 4090 architecture. Engine hashes and logs remain with each run.

## Alpine

- Login: `jojo6687@login.rc.colorado.edu`.
- Shared SSH socket: `~/.ssh/nadoc-alpine.sock` (password/Duo authenticated by user).
- Directory: `/projects/jojo6687/nadoc_jobs/strep_validation_20260913`.
- Successful build submission: **32530050**.
- Current CPU array: **32530094**, `acpu`, `cpu-normal`, `ucb-general`.
- Nine array tasks, maximum three concurrent; 1 CPU, 2 GiB, 1-hour wall limit each.
- Earlier build 32530004 compiled successfully but failed its post-build checksum
  assumption about shared-library layout. Dependent array 32530009 was cancelled.
  Array 32530061 encountered an Alpine `/etc/profile` variable under `set -u`;
  it was cancelled, the wrapper corrected, and 32530094 submitted.

## RunPod

Live Secure Cloud quote and actual accepted price: RTX 4090, **$0.74/hour**.
Existing network volume `77pnhye88p` in EU-RO-1 retains all outputs under
`/workspace/nadoc_validation/strep_remote_20260913`.

The controller uses a durable cumulative ledger capped at $15, reserves an
extra $0.10/hour plus $1 margin, and installs RunPod-owned expiration at creation.
Each attempt is additionally limited to 90 minutes, rather than spending the
entire budget. A separate watchdog terminates the campaign pod if the launcher
exits, a terminal state is reported or the deadline approaches. The controller
also terminates on completion/failure and checks that its pod is gone. It never
terminates unrelated account pods.

Initial pod `q2l48pm6n90xk7` was terminated after a network-volume tar extraction
problem (ownership preservation and option syntax); reserved cost approximately
$0.074. Corrected retry pod: **o60f8nkjn3aoib**, confirmed RTX 4090 with 24 GiB; engine build finished and the GPU validation worker is running. For authoritative current state,
read `workspace/validation/strep_remote_20260913/remote_state.json` and
`spend_ledger.json`; do not infer completion from this static submission note.

Full RunPod outputs remain on the network volume. The saved preferred local
archive path `/media/jojo/Archive` is absent in this WSL session; a destination
question is pending. No bulk result download to the system drive is configured.

## Local control and recovery files

Under `workspace/validation/strep_remote_20260913/`:

- `prepare.py`, `add_probes.py`, frozen `cases/`, `manifest.json`, source archive.
- `worker.py`: standard-library-only worker compatible with Alpine Python 3.6+.
- `alpine_submission.json`, build/array sbatch scripts.
- `launch_runpod.py`, `watch_budget.py`, `remote_state.json`, `spend_ledger.json`.
- `build_gpu.sh`, provider lifecycle audit logs.

The preparation scripts reproduce inputs; they are not required on either
remote host. Do not rerun a launcher while its recorded pod is live.

## Completion audit and census correction

Checked SLURM accounting and actual stage outputs after unexpectedly quick
completion was reported. Array 32530094 tasks 0–2 finished successfully in
7m43s–7m44s each; both MD relaxation and uncapped equilibration final
configurations report `t = 100000`. Tasks 3–5 were running and 6–8 pending.
Build job 32530050 completed separately in 31 seconds. Earlier array 32530061
failed within seconds because `/etc/profile.d/debuginfod.sh` referenced an unset
`DEBUGINFOD_URLS` under `set -u`; the current submission already fixes this.

The RunPod worker subsequently stopped at `biotin10_s101/probe` and its pod
was terminated. Local reproduction identified a campaign manifest bug:
preparation hardcoded 500 particles, while the biotin-tether topology contains
501 (484 protein residues, one retained biotin bead, and 16 DNA nucleotides).
The local one-step output is finite and clears the gold core. Preparation now
reads the count from the topology; the worker checks manifest/topology agreement
before launching and distinguishes census errors from nonfinite output errors.
A deliberately incorrect count is still rejected. Corrected manifest and worker
were installed atomically on Alpine while tasks 6–8 were still pending; original
files were retained. Running adsorption cases and all physical inputs are
unchanged. No duplicate Alpine jobs were submitted. GPU validation remains
incomplete: six adsorption cases finished, but the remaining biotin cases need
a resumed run with the corrected census before CPU/GPU parity can be concluded.

## Extended default-enablement gate (in progress)

All nine initial CPU and GPU cases completed 100,000 relaxation plus 100,000
uncapped steps. Stressed linear/rotational force responses, two timestep sizes,
and translated reference frames passed a 0.1% relative gate on RTX 2080 SUPER
and RTX 4090. Straight-handle torques nearly cancel, so their relative-only error
was ill-conditioned; the stressed check explicitly rotates/displaces a DNA bead,
checks DNA linear response separately from the much larger protein forces, and
retains the original tolerance. Regression tests exercise the application's
adaptive CUDA neighbour-list settings too.

Three-seed trajectory means passed energy and protein geometry margins but did
not establish equivalence for tether distance and DNA tip radius. The small mean
differences were accompanied by wide confidence intervals; the GPU guard remains
in place until the longer comparison passes.

Extended campaign `strep_extended_20260913` uses nine seeds per geometry (27
paired cases), 100,000 relaxation steps and 1,000,000 uncapped steps. Independent
seed means, not correlated saved frames, are the replicas for paired 95% Student
confidence intervals. Margins set before examining the short-suite results:
anchor RMS 0.2 nm, tether distance 0.25 nm, ANM extension RMS 0.05 nm, protein
radius of gyration 0.1 nm, DNA tip radius 0.5 nm, potential energy 0.05 and kinetic
energy 0.03 oxDNA energy units per particle. This is an engineering backend
comparison, not experimental calibration or a claim of exhaustive equilibration.

Both providers exposed host-CPU portability issues with cached `-march=native`
binaries. The extended CPU build is `32530996`; its resumed array is `32531277`
(27 concurrent single-CPU cases). Array `32530948` failed on older nodes;
`32531001` completed relaxation and was resumed with a 6000-second stage timeout
for longer sampling. Cached RunPod builds now disable native compilation and use
a new cache directory to exclude existing nonportable binaries. The GPU uses the
same source snapshot and a portable RTX 4090 build, pod `ptrhhog9los0u2`.
All retries share the original $15 cumulative ledger and provider expiration.

Portable collection and comparison helpers are checked in under
`scripts/validation/`; numerical force/movement regressions live in
`tests/test_gold_strep_dna.py`. Raw remote trajectories remain on Alpine and the
existing RunPod volume; only derived metrics are persisted locally.

## Thermostat defect discovered during extended validation

The original nine-case suite and the 27-case million-step suite completed on
both backends. Numerical force checks passed, but DNA-position confidence
intervals did not meet the predeclared equivalence margins. Investigation found
an upstream thermostat defect; these runs must not be treated as a valid
reference for enabling CUDA.

ANM protein points were initialized with fictitious angular momentum. Bussi
counted their nonexistent rotational degrees of freedom. CPU included their
energy but rescaled only rigid particles, while CUDA rescaled all particles.
For example, a 5 nm CPU replica had DNA rotational energy 0.000002927 per
nucleotide versus the expected 0.148 at 296 K. Another replica reached 0.525.
The aggregate kinetic energy concealed this subsystem failure.

A force-free control reproduced the defect. With 484 protein points and 16 DNA
monomers, old CPU rotational energy was 33–66% below the canonical expectation
for two tested seeds. The corrected CPU and CUDA values were within 0.25%,
with exactly zero protein rotational energy. Removing fictitious protein
rotation also exposed CUDA's zero-angular-momentum orientation divide-by-zero;
both mixed and single precision paths are patched.

The maintained patch is `tools/oxdna_thermostat/rigid-body-bussi.patch`. Local,
Alpine and RunPod build paths apply it and version their cached installations.
Protein-DNA preflight rejects old local/Alpine installations. Regression tools
check subsystem thermometry rather than only total energy.

Fresh corrected campaign: `workspace/validation/strep_bussi_fixed_20260913`.
Alpine build **32534188**, CPU array **32534189**, analyzer **32534218**.
RunPod RTX 4090 **8lh0om9swyni0i**, $0.74/hour, same cumulative $15 ledger and
90-minute provider expiry. All 27 cases restart from the original physical
inputs; point-protein angular momentum in the force probe is explicitly zero.
The position/force equivalence margins remain unchanged. New thermometry gates
require CPU/GPU DNA kinetic-energy agreement within 0.03 per nucleotide, zero
protein rotational energy, and a group 95% confidence interval for DNA
rotational energy wholly within 0.148 ± 0.03. These gates were added before
inspecting corrected full-model results. GPU default remains disabled pending
the corrected comparison.

### Corrected GPU completion

All 27 corrected GPU cases completed and their outputs were verified. Pod
`8lh0om9swyni0i` was terminated and confirmed absent. The cumulative campaign
estimate, including all failed attempts and the $0.10/hour reserve, is **$1.667**
against the $15 cap. Raw results remain on the existing RunPod volume.

The median corrected GPU million-step stage took **68.32 seconds**. The largest
relative CPU/CUDA force/torque discrepancy over nine relaxed configurations was
**5.7833e-5 (0.0058%)**, below the 0.1% gate. The deliberately stressed force
checks also passed, with maximum relative discrepancy about 0.0291%.

GPU mean DNA rotational energies per nucleotide were 0.14882 (5 nm adsorption),
0.14876 (10 nm adsorption), and 0.14831 (10 nm biotin tether), versus the expected
0.148. All group confidence intervals passed the absolute-temperature gate, and
all protein rotational energies were exactly zero.

Local validation passed 12 CPU/mixed-CUDA ideal-gas cases plus six single-
precision CUDA cases, the three full force/translation audits, two full CPU
fixed-gold builds, and the old-engine rejection test. The broader oxDNA
regression suite passed 322 tests. CPU trajectories are still required for the
final paired statistical gate; GPU default has not yet changed.

## Matched random-stream follow-up

All 27 corrected CPU jobs (32534189) and analyzer 32534218 completed successfully.
The corrected force, thermometry, tether, protein and energy gates passed. The
DNA-tip-radius intervals remained too wide to establish the original ±0.5 nm
bound: 5 nm adsorption delta +0.635 nm, CI [-0.255, 1.526]; 10 nm adsorption delta
-0.242 nm, CI [-2.099, 1.615]; biotin tether delta -0.474 nm, CI [-1.732, 0.785].
GPU default was not enabled on these results.

CUDA initialization consumed an extra host random draw to seed a device RNG that
Bussi does not use. `cuda-bussi-rng.patch` removes this offset specifically for
Bussi, preserving its probability law while aligning paired CPU/CUDA streams.
The complete force-free kinetic-energy histories then agreed within 2.02e-7
relative error. In a 100,000-step full-model diagnostic, the DNA-tip radius
pair difference fell from 0.5169 nm to 0.0010 nm; the starting MC structures
were identical. This improves the controlled comparison, rather than asserting
that one stochastic trajectory is physically preferable.

A new 27-case GPU campaign, `strep_rng_matched_20260913`, uses the same inputs,
seeds, durations, replica counts and margins. Its source archive differs from
the CPU reference in exactly `src/CUDA/Backends/MD_CUDABackend.cu`; every CPU source
file is unchanged, verified by archive member hashes. The completed Alpine CPU
reference is therefore reused. RunPod pod `7hoq4n8u33y77q` is a new RTX 4090 attempt
at $0.74/hour, with the same cumulative $15 ledger, watchdog and 90-minute expiry.
The local and remote build caches now use `bussi-v2` and record both patch markers.
The application checks for the validated CUDA initialization before protein GPU
jobs. The fixed-gold GPU default remains blocked pending the new comparison.


### Interim precision assessment (matched-stream campaign)

The first two completed nine-replica groups give DNA-tip-radius CPU/CUDA
mean differences and paired 95% confidence intervals of:

| Geometry | Difference (nm) | 95% interval (nm) |
| --- | ---: | --- |
| 5 nm adsorption | +0.0552 | [-0.5183, +0.6286] |
| 10 nm adsorption | -0.1330 | [-2.0492, +1.7832] |

Neither establishes the additional ±0.5 nm free-end precision bound. Small
observed differences with wide intervals are inconclusive; they do not establish
equivalence or demonstrate a backend bias. This bound was an engineering choice,
not an experimentally derived tolerance supplied by the user. A clarification is
pending on whether it is required for the default change, or whether numerical
physics, thermometry and attachment-geometry parity are sufficient while this
free-end sampling uncertainty is reported separately. The original gate remains
unchanged pending that decision and the remaining runs.


## Final matched-stream results

All 27 CPU and 27 CUDA cases completed their full 100,000-step MD relaxation and
1,000,000-step production stages (29.7 million MD steps per backend). All 108
stage input pairs passed the protocol audit. The source compatibility audit
confirmed unchanged CPU source; only CUDA Bussi initialization changed between
the CPU reference and final GPU build.

Numerical force/torque parity, anchor and DNA attachment geometry, protein shape,
ANM extension, total potential/kinetic energy and rotational thermometry passed.
The largest relaxed-configuration force discrepancy was
2.09348e-05 relative (0.0021%), below the 0.1% gate.
The original overall statistical gate **did not pass**:

| Geometry / metric | CUDA − CPU mean | Paired 95% interval | Allowed margin |
| --- | ---: | --- | ---: |
| ads5 / dna_tip_radius_nm | +0.055170 | [-0.518253, +0.628593] | ±0.5 |
| ads5 / dna_translational_per_particle | +0.007554 | [-0.016039, +0.031147] | ±0.03 |
| ads10 / dna_tip_radius_nm | -0.132981 | [-2.049179, +1.783218] | ±0.5 |
| biotin10 / dna_tip_radius_nm | -0.971421 | [-2.416019, +0.473176] | ±0.5 |

Distances are in nm; energy is in oxDNA reduced units per DNA nucleotide.
These intervals are inconclusive for equivalence. All include zero; that alone
is not evidence of equivalence. The observed biotin-tethered mean difference also
exceeds the chosen distance margin, so a precision claim cannot be made from
these runs. No margins or replica windows were changed after inspecting results.

**Fixed-gold GPU default remains disabled.** The relaxed acceptance question did
not receive a reply, and translational-energy precision would still need attention
under that proposed alternative. Additional independent sampling is required to
establish the existing gates; this report does not claim experimentally validated
coating physics or equilibrium sampling.

Median million-step runtime was 3218.52 seconds on one Alpine CPU core and
115.00 seconds on this RTX 4090 host (28.0× ratio). Host/platform
conditions differ, so this is an observed workload timing, not a controlled
hardware-only speedup. RunPod pod `7hoq4n8u33y77q` was automatically terminated
and confirmed absent. The cumulative ledger, including earlier attempts and
hourly reserve, records **$2.557**, within the $15 cap. Existing network-volume
storage is retained separately; raw trajectories were not bulk-downloaded.

Both maintained engine fixes are installed locally and integrated into Alpine
and RunPod build/cache paths. Unpatched protein engines are rejected. The seven
direct full-model/force engine tests passed; all 13 API/model/guard tests passed
after adapting the pending-default assertions to the retained CPU gate. Earlier
broader validation passed 323 tests, alongside the thermostat controls and build
checks described above. Derived results are in
`strep_cpu_gpu_2026-09-13_results.json`; detailed per-case metrics remain in
`workspace/validation/strep_rng_matched_20260913/comparison.json`.

## Subsequent physical-validation failures

The follow-up [physical checks](strep_physical_checks_2026-09-13.md) found a
factor-of-two CUDA protein–DNA repulsion error, a shared Bussi weak-coupling
failure, incorrect native CUDA energy accounting, and DNA translational
equipartition failures on both backends. Earlier force passes covered only the
sampled configurations and missed the active protein–DNA contact. They must not
be interpreted as complete backend validation. Fixed-gold GPU default remains
disabled; the completed CPU reference also has a thermostat defect.
