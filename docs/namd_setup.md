# NAMD 3 Setup Guide (incl. WSL + GPU)

This document covers getting **NAMD 3** installed so NADOC's Molecular Dynamics
sidebar stops reporting "NAMD 3 is missing" and can run atomistic jobs. It also
covers the WSL2 + NVIDIA GPU story, which is the most common point of confusion.

NADOC runs NAMD as the production MD engine. It does **not** ship NAMD (the
license requires each user to register and accept it), so every user installs
it once on their own machine.

---

## TL;DR

1. **GPU under WSL2** = install/keep the **Windows** NVIDIA driver only. Do not
   install a Linux NVIDIA driver inside WSL — it breaks the passthrough. Verify
   with `nvidia-smi` *inside* WSL.
2. Download the prebuilt **`Linux-x86_64-multicore-CUDA`** build of NAMD 3
   (license-gated — see below). This is the GPU build NADOC's launch flags expect.
3. Extract to `~/Applications/` and NADOC auto-detects it (the folder name is
   already a recognized path). Or point `$NADOC_NAMD_BIN` at any `namd3` binary.
4. To use NADOC's current **GBIS implicit-solvent** protocol, also install the plain
   `Linux-x86_64-multicore` build. GBIS does not support NAMD GPU-resident mode, and
   NADOC currently routes this protocol to the CPU build.

---

## How NADOC finds NAMD

`find_namd()` in [backend/core/namd_runner.py](../backend/core/namd_runner.py)
resolves the binary in this order:

1. **`$NADOC_NAMD_BIN`** — explicit override. Absolute path to a `namd3` binary,
   or a name resolvable on `$PATH`. Use this for non-standard install locations.
2. **`namd3`** on `$PATH`.
3. Conventional installs under `~/Applications/`. The path is **globbed**
   (`~/Applications/NAMD_*/namd3`), so any NAMD version matches — no code change
   needed to upgrade — and a CUDA/GPU build sorts ahead of a CPU-only build:
   - `~/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3`  ← GPU build (preferred)
   - `~/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3`        ← CPU build
   - …a newer `~/Applications/NAMD_3.0.3…/namd3` would be picked up automatically.

If none resolve, the MD sidebar reports NAMD missing and job creation refuses
early (before the expensive solvation step).

See [external_tools.md](external_tools.md) for the full environment-variable
reference shared across all simulation back-ends.

For surface-deposited oxDNA seeds, graphene nanopores, membrane-only controls,
ion-transport production, and current/crossing analysis, see
[NAMD nanopore ion transport](namd_nanopore_transport.md).

## Sequence gate and deferred preparation

Creating a NAMD job records the intended protocol and is allowed before sequences are
assigned. Such a job is marked as waiting for sequence rather than being atomized through
the implicit poly-T fallback. Pressing **Run** while any non-reference scaffold or staple
strand is unassigned or under-sequenced is rejected with a popup naming the affected
strand and missing nucleotide count.

After sequence assignment, NADOC automatically prepares the deferred job without starting
NAMD. Base identity changes the exact CHARMM atom count, so the sequenced topology is rebuilt
first and its PSF/manifest count is propagated to disk, VRAM, throughput, and cluster/RunPod
resource projections. Once preparation completes, **Run** launches that prepared package.

## Minimization progress

The pre-dynamics minimization is tracked separately from the relaxation segments. While
NAMD is minimizing, NADOC reads the latest complete `ENERGY:` timestep from the live log
every disk-guard tick (normally 15 seconds) and persists `step / configured steps` in the
job record. The timeline therefore starts at 0%, advances during minimization, and reaches
100% only after NAMD writes the completed minimization coordinates. The same tracking is
used when NADOC adopts a minimization process that survived an application restart.

Minimization does not yet produce trajectory-based health samples; those begin with the
first dynamics segment. A moving minimization percentage, a growing log, and an active
NAMD process indicate forward progress during this stage.

### Which build do I need?

NADOC launches NAMD as:

```
namd3 +p<threads> +setcpuaffinity +devices <gpu_ids> <segment>.conf
```

- The **`Linux-x86_64-multicore-CUDA`** build uses `+devices` for GPU offload.
  **This is the build you want** — origami atomistic systems are large and the
  GPU is ~1–2 orders of magnitude faster than CPU.
- The plain **`Linux-x86_64-multicore`** (CPU-only) build also works with NADOC:
  it is used for explicit-solvent CPU runs and is currently required by NADOC's
  GBIS implicit-solvent protocol. It is fine for small systems or smoke-testing,
  but is usually impractically slow for large explicit-solvent production runs.

### Solvent and memory policy

Every newly prepared explicit-solvent job contains a complete periodic water box.
NADOC does not carve the water down to a finite hydration shell to make an oversized
job fit: doing so leaves vacuum in the cell, changes the ensemble to constant volume,
removes bulk-solution conditions, and turns the run into a different protocol.

Before a local GPU launch, NADOC estimates the fully solvated atom count and memory
requirement. A system that exceeds the selected target is stopped before preparation.
The supported choices are:

- use a GPU with enough VRAM (or a CPU target with enough host memory);
- reduce the construct or choose a defensible smaller periodic cell/padding setting;
- use GBIS when an approximate continuum solvent is scientifically acceptable.

GBIS eliminates the explicit water box, but it is not a route to GPU-resident NAMD.
NAMD 3 supports implicit solvent in its classic CUDA GPU-offload path, while its
GPU-resident path explicitly rejects GBIS and LCPO/SASA. NADOC currently uses the
multicore CPU build for GBIS; CUDA-offloaded GBIS would require separate validation.
See the NAMD 3.0.2 documentation for
[GPU acceleration](https://www.ks.uiuc.edu/Research/namd/3.0.2/ug/node102.html) and
[GBIS](https://www.ks.uiuc.edu/Research/namd/3.0.2/ug/node30.html).

---

## WSL2 + GPU: the one thing people get wrong

On WSL2, the GPU is projected into Linux by the **Windows-side NVIDIA driver**
through `/usr/lib/wsl/lib/libcuda.so`. The rules:

- ✅ Install/update the **NVIDIA driver on Windows**.
- ❌ Do **not** `apt install` a Linux NVIDIA driver inside WSL. It overwrites the
  WSL stub and breaks `nvidia-smi`.
- ❌ You do **not** need the CUDA toolkit (`nvcc`) for prebuilt NAMD — the
  binary bundles its own CUDA runtime. (`nvcc` is only needed if you compile
  NAMD or Charm++ from source.)

Verify the GPU is visible from inside WSL:

```bash
nvidia-smi                       # must list your GPU
ls /usr/lib/wsl/lib/libcuda.so   # the WSL CUDA stub must exist
```

If `nvidia-smi` works in WSL, GPU access is already done — no further setup.

**VRAM note:** fully solvated origami boxes can be large. An 8 GB card (for example,
a GeForce RTX 2080) handles modest explicit-solvent systems, but a large box can exceed
VRAM. NADOC will not trim away water to make it fit; choose a larger-memory target,
reduce the system or defensibly reduce its cell, use a sufficiently large CPU host, or
select GBIS when its approximation is appropriate.

The local preflight distinguishes GPU memory from available host RAM. It reserves
15% of GPU capacity and 4 GiB of host RAM, subtracts other live reservations, and
blocks launch when the required reserve cannot be maintained. Unknown requirements
also block launch. The popup identifies the limiting resource and shows preparation
separately from simulation plus concurrent health analysis.

Sizing includes the selected bounding/rotation box, explicit dimensions, salt
recipe, worker count and per-stage allocation overrides. Before preparation, the
atom number is a conservative upper estimate including water and DNA hydrogens;
after preparation, the PSF count and actual configurations determine the budgets.
The solvation-profile cache includes geometry and salt choices, so changing an
explicit box cannot reuse the smaller box's estimate.

CUDA also has a per-patch shared-memory limit independent of total VRAM. The tested
NAMD kernel needs `128 * ceil(max_patch_atoms / 32)` bytes and exposes at most
12,288 atoms per patch on the tested 48 KiB devices. Generated periodic configurations
select unspecified `twoAwayX/Y/Z` controls when necessary, before any integration
command. Explicit user controls are preserved; a layout that cannot satisfy the
occupancy allowance is refused. Admission queries the selected local device's
capacity and accounts for discrete grid/thread transitions. The operational policy
allows 0.20 atoms/Å³ per patch and uses at most 75% of the kernel atom capacity.
This empirical density allowance is not a mathematical bound on arbitrary future
coordinates or a 99% statistical guarantee.

Outside the compact preparation domain described below, the explicit-DNA
preparation budget is `1024 + 1600*N/1e6 + 192*B/2^20` MiB,
where `N` is the atom upper estimate and `B` is the restraint allowance (up to
2.6 million). It is reserved before solvent/topology preparation. Simulation
reserves the largest planned stage plus one concurrent health evaluation until the
workflow exits. Prepared inputs with unresolved allocation settings remain blocked;
the exact application-generated adaptive minimizer is recognized, while modified
Tcl controllers require separate qualification. These budgets cover the tested
explicit-solvent DNA domain; other materials and solvent models need separate data.

### Resource uncertainty audit (2026-11-01)

The follow-up audit is retained in
`.development-artifacts/namd-resource-uncertainty-20261101/`. Its `report.json`
and `state.json` connect each uncertainty to implementation, measurements and
remaining limits. The operational envelopes remain engineering upper budgets;
these measurements do not establish a 99% statistical guarantee.

| Uncertainty | Change and evidence | Remaining allowance or restriction |
| --- | --- | --- |
| Atom/topology counts before preparation | Canonical DNA uses the actual CHARMM residue and terminal-patch atom sets. Dry counts matched all 20 archived pilot preparations exactly. The API exposes solute, solvent and ion components. Prepared stages still read the actual PSF and restraint files. | Solvent uses bulk density without subtracting solute exclusion. Total upper estimates remained 3.5–22.7% above the prepared counts, down from 4.0–27.4%. Modified/unresolved DNA retains the previous allowance. Restraint counts remain conservative before preparation. |
| Neighbor buffers and PME | Forecasts expose allocation components. Source-matched PME dimensions agreed with 41 retained engine logs. CUDA allocation-event traces attributed about 788 MiB of the wide-neighbor-list increase to tile lists and about 208 MiB of the fine-grid increase to PME/FFT. | Discrete buffer growth and FFT workspace remain build/plan dependent. The qualified numerical engine budgets, including the padded PME allowance, were retained. The exact grid is diagnostic, not an exact total-memory claim. |
| Profile and stage | Eighteen new 480-step probes covered three repetitions of six early/late, fast/Aksimentiev and neighbor/PME variants on the same 313,861-atom 6hb system. Within each variant, RSS spread was at most 0.88% and sampled process VRAM spread at most 2.09%. All passed below frozen budgets (maximum ratios 0.716 RAM, 0.843 VRAM). | Configuration effects are distinct from identical-run randomness. Older four-family probes lack engine hashes; failed long runs are excluded. The current successful short replacements are described below and do not qualify long-run completion. |
| Concurrent work | Bulk trajectory analysis, metric/CPD jobs and background precomputation share a cross-process scheduling lease. They wait for managed local NAMD simulation/preparation; new simulations cannot overlap an active heavy analysis. Queue cancellation and cross-process exclusion are tested. | The lease serializes work; it does not assert an analysis RAM bound. Required health analysis keeps its separate workflow reservation. Bounded playback remains available. External applications and unmanaged simulations are outside this scheduler. |
| Provenance and measurement scope | Offline normalization separates engine/workflow RSS, process/device VRAM and cgroup memory including file cache. Stage launches now save binary/configuration hashes, GPU/driver identity and forecasts beside the log in `.resources.json`. Missing identities remain explicit. | Measurements with missing build provenance are not cross-build calibration evidence. A recorded identity does not certify another engine, CUDA library, driver or GPU. Retest allocation thresholds when those change. |

The normalized current audit accepts 77 engine observations and excludes 25
records with missing provenance or superseded host implementations. Of the observations with applicable
forecasts, none exceeded its RAM/VRAM budget: maximum workflow RSS/budget was
0.941 and process VRAM/budget 0.832. These maxima have different denominators and
scopes from the new repeatability probes. Another 27 pre-fix attempts, including
17 failed/skipped/censored observations, are preserved separately; an early failure
must never be treated as a low successful peak. No independent component peaks are
added together and described as a simultaneous workflow measurement.

The detailed allocation traces cover the NAMD Git-2025-12-04 executable with SHA-256
`2fda225c5f8838e5dbcb6a4e6a3e7e337f498df61cae2e6e320f994cb7c8b9bf`,
an RTX 3080 Ti and driver 580.178.04. Retained boundary evidence also covers the
RTX 6000 Ada with driver 595.91.07. The trace records selected CUDA runtime allocation
lifetimes, not every driver allocation or physical residency; instrumented runs had
about 12 MiB more sampled GPU usage and are kept separate from ordinary runs.
The optional tracer is used only for diagnostics and is not loaded by production.

To reproduce the offline evidence processing without running simulations:

```bash
.venv/bin/python scripts/validation/namd_resource_evidence.py \
  --output .development-artifacts/namd-script-scheduling-20261102
.venv/bin/python scripts/validation/namd_allocation_report.py \
  --root .development-artifacts/namd-resource-uncertainty-20261101 \
  --binary /path/to/the/recorded/namd3
```

### Allocation refinements and spike measurements

The subsequent refinement is retained in
`.development-artifacts/namd-resource-refinement-20261101/`. Admission now uses
the resolved PME grid with the existing 48-byte/extra-point allowance, removing
the previous 20% padding on each grid axis. The 31 nm comparison budget falls
from 23,902 to 22,244 MiB at otherwise identical inputs. The original replay has
been superseded by the strictly filtered audit below; failed parent chains and
unprovenanced probes no longer contribute to current checks. The other admission
allowances remain in place.

Prepared configurations also expose an **expected engine usage** estimate, which
is separate from admission. `GET /api/md/jobs/{job_id}/resource-estimate` returns
each planned stage, expected engine maxima, and the conservative workflow ceiling
including health RAM. Missing expected values remain null. Future checkpoints use
the prepared initial geometry explicitly as a proxy; an existing checkpoint uses
its own coordinates. Stage resource receipts include this information. A detailed
forecast exceeding its ceiling blocks admission rather than silently accepting
the conflict. These fields describe memory, not a guarantee of scientific or
numerical completion.

The PME component uses workspace-only forward/reverse cuFFT plans linked with
the same static archive as the qualified NAMD build. Both the initial PME solver
and the resident solver remain allocated in this build: both sets of grids and
plan workspaces must be counted. Source-based accounting predicted two traced PME
allocations (38.179 and 245.692 MiB) within 0.01 MiB, excluding small metadata.
The helper allocates no grids or FFT workspaces, runs in a separate process with
a 512 MiB context reservation, and validates executable/library identity. A
missing or mismatched helper keeps the conservative forecast available and marks
the detailed workspace as unavailable.

Neighbor features count coordinate-bin occupancy, 32-atom tiles, their spatial
bounding boxes and sampled tile-pair proximity. They account for retained 2x
growth capacity. They approximate NAMD's hydrogen-group patch assignment and
sample tile pairs, so they are descriptive features, not exact future capacities.
The residual model uses atom/restraint counts, tile-pair capacity, neighbor radius,
timestep regime and harmonic-constraint settings. Timestep coefficients capture
an observed profile effect whose full allocation cause is not yet isolated.
Coordinate analysis reserves 512 MiB and does not construct a full atom-pair list.

Validation holds out entire geometry groups when fitting the remaining engine
overhead. Current filtered counts and errors are given below. These are
descriptive cross-validation errors from correlated simulation stages, not 95%
or 99% coverage guarantees. Expected residual coefficients are currently enabled
only for the qualified binary, RTX 3080 Ti/580.178.04 and 16/32 workers. Inputs
outside the fitted feature ranges are labeled as extrapolation.

Six retained 20,000-step probes lack a contemporaneous run-time engine hash;
eight earlier long runs ended with an `outputtiming` script error. Their raw
records remain available for diagnosis, but none contributes to current usage
averages, spike counts, fit coefficients or pass/fail totals. New standalone
spike/startup/allocation reports require a matching launch-time resource receipt,
validated outputs and clean termination. Missing GPU samples stay missing;
allocation traces require a recorded end timestamp, never a clock conversion
using the current boot. Explicit experimental-engine reports remain separate.

NAMD's inspected device allocator frees an undersized buffer, allocates a larger
one and retains that capacity. This is often a lasting increase, rather than an
intermittent spike. Pausing execution does not release those live buffers. Current
NAMD allocations use `cudaMalloc`; automatic host-memory spill is not enabled by
an application-level setting. Any oversubscription design would require an
engine-supported offload/managed-memory path and separate performance and
correctness qualification.

Other systems illustrate the available approaches:

- [LAMMPS](https://docs.lammps.org/neigh_modify.html) grows neighbor storage in
  pages while retaining configured per-atom/page limits. Dynamic growth still
  requires space for the resulting live lists.
- [PyTorch](https://docs.pytorch.org/docs/2.15/notes/cuda.html#memory-management)
  caches and reuses allocations and can release unused cached blocks. Cache
  eviction cannot free live tensors; those must be discarded, recomputed or
  explicitly moved elsewhere.
- [GROMACS](https://manual.gromacs.org/current/user-guide/mdrun-performance.html)
  lets users place PME/FFT work on CPU or GPU. This is an execution-layout choice,
  not automatic recovery from an allocation that already failed.
- [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html) provides
  `memory.high` reclaim/throttling and `memory.max` containment. Reclaim and swap
  can help pageable RAM; hard containment protects the desktop by sacrificing
  the job if necessary, so it cannot be advertised as completion assurance.

For NADOC, the useful existing controls are analysis serialization, bounded
playback/cache reclamation, and explicit CUDA offload. Further headroom recovery
should target allocation lifetimes and duplicate PME storage, or a qualified
checkpoint/restart fallback. A polling-only monitor is too late to guarantee
protection against an instantaneous device allocation, and the observed absence
of recurring spikes does not authorize admitting a job below its live memory
requirement.

Build the optional matching helper with:

```bash
.venv/bin/python scripts/validation/build_namd_cufft_probe.py \
  --engine /path/to/qualified/namd3 --cuda /path/from/its/Make.config
```

It installs under `~/.cache/nadoc/namd-cufft-probe/`; another manifest can be selected
with `NADOC_CUFFT_PROBE_MANIFEST`. The build refuses an unqualified binary or
changed cuFFT archive. `scripts/validation/fit_namd_expected.py --root <artifact-dir>`
replays the stored feature fit and group validation without installing its
candidate model. `scripts/validation/namd_spike_report.py --root <artifact-dir>`
rebuilds the spike report without launching simulations.

### Experimental sharing of PME storage

`scripts/validation/namd_shared_pme.patch` changes the reviewed NAMD
Git-2025-12-04 source so the offload and resident solvers can share their real
grid, complex grid and forward/reverse FFT plans. Forward and reverse transforms
still have separate workspaces. The solvers execute in different script tasks;
reference counts retain storage across solver reconstruction, and the offload
path restores its FFT stream when minimization resumes. Resident activation
synchronizes prior GPU work. No force, integration or PME resolution parameters
are changed.

Sharing requires `NADOC_SHARED_PME=1`, one process, one replica, one GPU, a single
PME pencil and no alchemical calculation. Other modes use the original allocation
path. This is an isolated experimental executable, not the installed default.
Build it from the existing qualified source/build tree:

```bash
.venv/bin/python scripts/validation/build_namd_shared_pme.py \
  --source /path/to/NAMD_Git-2025-12-04_Source --output /new/experiment-directory
NADOC_SHARED_PME=1 /new/experiment-directory/build/namd3 \
  +p16 +setcpuaffinity +devices 0 simulation.conf
```

The build helper checks the original executable and edited source identities,
copies the build, and records a candidate hash and patch hash. It never overwrites
the installed engine. Setting `NADOC_SHARED_PME=0` provides a control using the
same rebuilt executable. Existing expected-resource qualification remains bound
to the original binary; the candidate cannot silently inherit its forecast.

Measurements and paired controls are retained under
`.development-artifacts/namd-pme-sharing-20261101/`. CUPTI traces measured PME
savings of 14.897 MiB for 56×60×288, 118.652 MiB for 112×120×576, 38.271 MiB for
the deliberately odd 55×63×289 grid, and 1,231.611 MiB for the 432³ stress grid.
The last case reduced process VRAM from 3,722 to 2,488 MiB. Offload-only usage was
unchanged. Total VRAM savings in small-grid runs can be masked by independent
neighbor-capacity variation: one fast-profile pair saved 14.9 MiB in PME but
allocated 25 MiB more neighbor storage. RAM savings are not established.

Short comparisons include both origami profiles, odd and fine grids, repeated
minimization/dynamics transitions, and matching rebuilt-binary controls. For the
20-step standard/fine comparisons, coordinate RMS differences were approximately
0.000008 Å and relative force differences 0.0043–0.0068%, comparable to repeated
unmodified runs. These are tolerance comparisons, not bitwise trajectory equality.
An additional `run norepeat` transition failed in the original executable with
`Bad global atom count`; that baseline failure is retained separately and was not
counted as a successful qualification. Regular `run` transitions completed.
Multi-GPU, replica and alchemical sharing are deliberately disabled and unqualified.

The completed campaign contains 29 successful runs plus that preserved baseline
failure, consuming 483 seconds of engine wall time in total. It includes full
coordinate/velocity checkpoint restarts and two uninstrumented 20,000-step runs.
For the latter pair, process VRAM fell from 2,270 to 2,148 MiB; wall time was
129.5 versus 131.9 seconds, so no speed improvement is established. Output and
restart checks passed. Late-run mean temperatures differed by 0.49 K. The four
distinct-grid allocation savings exactly matched the independent static-cuFFT
workspace formula: one real grid plus one complex grid plus one forward/reverse
workspace pair removed. `report.json` retains measurements and numerical
differences; `verification.json` records the passing checks and scope limits.
Runs used a 4 GiB RAM cgroup with swap disabled and the existing resource lease.
Eight allocation-model regression tests passed. No cloud spending or production
admission-limit change was made.

### Startup rise versus a temporary memory peak

Follow-up measurements are in `.development-artifacts/namd-startup-20261102/`.
The PME-sharing candidate still allocates much of its memory during startup.
No startup-only RAM or VRAM excess above the later running peak was observed in
the four corrected, 2,000-step probes. The measurements cover 313,861-atom 6hb
with standard, fine/wide-list and 432³ PME grids, plus an original-binary 432³
control. They do not qualify every atom count or preparation stage.

| Case | VRAM at startup peak (MiB) | Peak during dynamics (MiB) |
|---|---:|---:|
| Shared PME, standard grid | 1,270 | 1,296 |
| Shared PME, fine grid / wide list | 2,160 | 2,160 |
| Shared PME, 432³ grid | 2,488 | 2,514 |
| Original, 432³ grid | 3,722 | 3,748 |

Startup ends at the first observed `TIMING` line. The running comparison starts
one second later and ends at the last `ENERGY` line, before process exit.
Shutdown memory disappearing is never treated as the running baseline. Polling
requested 5 ms intervals; observed maximum gaps were approximately 16 ms for RAM
and 14 ms for VRAM. Successful CUDA allocation/free callbacks independently
record requested device and pinned-host lifetimes. These do not measure all
driver allocations or guarantee absence of shorter physical-memory peaks.
Pinned-host bytes are already included in RSS and must not be added again.

For the fine/wide-list case, all 1,842.0 MiB of tracked device allocations present
at startup remained live through the running observation. Neighbor-tile storage
accounted for 1,407.3 MiB, versus 127.0 MiB for PME/FFT. The two exclusion-mask
buffers alone occupied about 1,266.9 MiB. `CudaTileListKernel.cu` uses both buffers
when repacking neighbor lists, so they cannot simply be discarded after startup.
Further reduction requires changing candidate-tile counts, capacity growth or
the exclusion-storage algorithm, followed by separate correctness validation.
Slowing the initial allocation ramp or freeing/reallocating these buffers does
not reduce their required simultaneous peak. Current admission limits remain.

`backend/core/resource_spikes.py` now reports startup overshoot, continued growth
and no distinct overshoot separately, using explicit observed windows. The report
retains raw excess as well as the classification threshold. Reproduce it with:

```bash
.venv/bin/python scripts/validation/namd_startup_report.py \
  --root .development-artifacts/namd-startup-20261102 --results v2_results.json
```

The optional CUDA tracer accepts `NADOC_CUDA_HOST_TRACE` for a separate pinned-host
log. The first probe batch exposed an accounting race: one thread can reuse a
freed address before another thread's free-return callback runs. The recorder
now tracks allocation generations and reconciles proven reuse; the offline
report rejects unexplained reuse. The initial host traces are preserved and
excluded, while their independent RAM/VRAM measurements remain usable. Four
replacement runs passed allocation replay and output checks. Fourteen Python
regressions and a native callback-order regression passed. The engine binary
was not changed for this follow-up; no additional cloud spending was used.
See `startup_report.json`, `measurement_correction.json` and `startup_memory.png`.

### Host RAM peaks across preparation, simulation and analysis

The 2026-11-02 audit is retained in
`.development-artifacts/namd-ram-audit-20261102/report.html`, with machine-readable
evidence in `report.json`, `archive_inventory.csv` and `verification.json`.
It inventories 604 archived stage/case records and adds 14 bounded local workers
(276 seconds of worker wall time). All fresh workers completed within 8 GiB
cgroups, without swap or memory-limit events. No additional dynamics or cloud
jobs were needed. These observations characterize causes and opportunities;
they do not replace admission envelopes with new universal upper bounds.

| Source of RAM demand | Observed peak | Interpretation / next opportunity |
|---|---:|---|
| Engine, largest archived standalone case | 10.76 GiB RSS | Live state and retained capacities need an engine allowance. An engine component reached 11.16 GiB in an overlap run. |
| Preparation, fresh 2.93M-atom cube | 3.72 GiB RSS | Largest sampled stack is HMR PSF output while full-system text and atom/bond objects coexist. Stream and compact these representations. Historical 18hb preparation reached 4.23 GiB. |
| Reference rebuilding after minimization | 0.14–0.87 GiB RSS | Archived isolated phases; stream PDB rewrites and bound ENM pair generation. Parent preparation can have additional live data. |
| Health, fresh repeated 3x6hb | 2.42 GiB RSS | Largest sampled stack is MDAnalysis reference-PDB parsing. Reuse compact reference coordinates and base-pair metadata. Historical optimized 18hb checks reached 3.29 GiB. |
| Atomistic average/model plus JSON response | 0.42 / 0.57 / 0.82 GiB RSS | Direct calculation / cold cache / warm cache on the same eight frames. JSON cache packing, decoding and response copies are optimization candidates. |
| Occupancy plus density, 32 / 128 frames | 1.02 / 1.26 GiB RSS | Sampled coordinates and display-frame objects are retained; full-trajectory mode remains a growth dimension. |
| Streaming RMSF, 128 frames | 0.22 GiB RSS | Bounded-coordinate path; its memory behavior differs from occupancy. |
| Photoproduct likelihood, 32 frames | 0.97 GiB RSS | Full context setup remains relevant even with bounded frame sampling. |
| Solvent display, one frame / 5,000 waters | 0.67 GiB RSS | Selected output is small, but context construction is a separate cost. |
| Mean surface, 0.20 / 0.10 nm grid | 0.61 / 1.24 GiB RSS | 2.08M / 16.22M voxels; the fine response is 138 MiB. Normal subprocess plus parent peaked at 1.28 GiB. Budget mesh/serialization as well as voxels. |
| Browser playback after retention limits | 0.95–0.96 GiB renderer RSS | Archived 800-frame tests; browser trees reached 1.33–1.34 GiB. The 512 MiB payload allowance is not a browser-process cap. |
| Engine plus optimized health | 8.31 / 14.24 GiB simultaneous RSS | Actual 3x6hb local / 18hb cloud overlap observations. Scheduling can remove overlap; simply suspending the engine retains its allocations. |

The health fixture has 1,936,696 atoms; the archived production fixture used for
the fresh trajectory/analysis probes has 1,410,263 atoms and 149,666 displayed
heavy atoms. These are different jobs within the 3x6hb family. The complete report
preserves source paths, subphase events, sampled Python stacks, RSS/PSS traces,
cgroup counters, response sizes and observed time near each peak. Short probes
are not completion qualification for unlimited trajectories or arbitrary shapes.

After the two health checks, RSS was 519 and 675 MiB. Garbage collection left
519 and 673 MiB; a worker-local glibc trim reduced those to 225 and 243 MiB.
This identifies allocator retention after the computation, not a way to lower
its working peak. Dedicated worker exit is a stronger lifetime boundary than
relying on GC or applying a global allocator policy. A normal playback worker
plus multiprocessing helper retained approximately 222 MiB after its response
was released; idle worker pools must remain part of application accounting.

Separate file-cache accounting is essential. The 128-frame occupancy cgroup
peaked at 4.84 GiB while process highwater was 1.26 GiB. A near-peak snapshot
contained 3.65 GiB of file pages with negligible dirty data. Preparation instead
had about 529 MiB dirty file pages near its peak. CUDA runs can also report
substantial `shmem` within `memory.stat`'s `file` field. Do not subtract that whole
field as reclaimable disk cache, add cgroup usage to RSS, or sum independently
observed process maxima as if simultaneous. Shared mappings and page ownership
also mean cgroup charge can be smaller than process RSS.

The normal in-flight health cadence is first eligible after 30 seconds, then
300 seconds after the preceding check finishes, subject to available frames and
configured overrides. Bulk analysis already queues behind simulation; health
and permitted playback still need overlapping allowances. Reference-coordinate
reuse, streaming HMR/topology I/O, and compact analysis caches are the clearest
next implementation targets. Engine RSS limits remain unchanged: the shared
PME/FFT experiment established VRAM savings, and the corrected startup probes
did not identify a temporary engine RAM excess that could simply be released.

Validation reproduced the prepared PDB byte-for-byte. Both PSFs differed only
in the force-field path in a title remark; their scientific records and the
referenced force-field file contents were identical. Both fresh health results
equaled the prior optimized result, and all repeated binary playback hashes
matched. The first playback probe populated the normal job-local analysis cache;
subsequent direct probes bypassed it and runner probes used isolated caches.

### RAM optimizations enabled after paired qualification

The high-priority candidates above are now implemented and measured against a
frozen copy of the preceding code. Evidence, source hashes, the incremental patch,
and plots are in `.development-artifacts/namd-ram-optimization-20261102/report.html`
and `report.json`. The final comparison contains 13 paired cases, with 39
successful bounded worker executions across development and verification.

| Work | Before → after peak RSS (MiB) | Before → after operation time |
|---|---:|---:|
| HMR alone, 2.93M atoms | 2,827 → 108 | 9.30 → 7.97 s |
| Full preparation, fast profile | 3,809 → 1,914 | 65.30 → 49.38 s |
| Full preparation, Aksimentiev profile | 3,809 → 1,913 | 51.79 → 50.28 s |
| Health, 6hb / 2hb | 515 → 255 / 619 → 293 | 4.80 → 1.81 / 5.01 → 2.11 s |
| Health, 3x6hb / 18hb | 2,445 → 765 / 3,371 → 1,038 | 29.00 → 12.25 / 39.72 → 14.04 s |
| Atomistic cache, cold, 3x6hb / 18hb | 563 → 456 / 1,017 → 802 | 5.49 → 2.68 / 10.32 → 4.59 s |
| Atomistic cache, warm, 3x6hb / 18hb | 762 → 409 / 1,383 → 709 | 1.57 → 0.45 / 3.04 → 0.88 s |

RAM is the larger of worker highwater and sampled process-tree RSS; the cache
probes include subsequent response serialization in their memory measurement.
Operation timing excludes imports, response serialization and verification.
Cache cold/warm refers to the application artifact, not flushed OS file caches.
The roughly 3% Aksimentiev preparation timing difference is not a strong speed
claim; its approximately 50% RAM reduction is the reason to retain the change.

Implemented changes:

- HMR reads and writes PSFs in streaming passes, stores masses in a compact
  array, and keeps adjacency only for eligible solute hydrogens. Fixed-width
  bond parsing, sequential mass updates, water exclusions, optional heavy
  residues and non-mass fields are preserved. Output publication is atomic.
  A receipt verifies both source and HMR hashes before preparation reuses the
  already generated default HMR file instead of writing it a second time.
- Charge auditing consumes atom records incrementally. Solvent PSF/PDB assembly
  uses compact text buffers and packed index tables instead of millions of
  independent Python strings and bond/angle tuples. Preparation releases its
  extracted ZIP payload before the later phases.
- Health readers retain MDAnalysis atom/residue/charge semantics while omitting
  unused bonded connectivity from their private topology. Reference coordinates
  stream into float32 arrays once per evaluation; each reader receives a private
  coordinate copy. The cache is context-local and released on every exit path.
  This remains usable by the standalone remote health worker.
- Analysis cache schema 2 stores ordinary JSON dictionaries directly, uses
  lossless typed storage for arrays and long homogeneous numeric lists, and
  decodes containers in place. Tuple keys, dtypes, shape, large integers and
  nonfinite values are preserved without pickle. Array byte counts are checked
  before allocation. Atomic writes and cross-process single-flight locks remain.
  Old cache keys/precompute markers invalidate; existing files are not deleted.

Validation: 432 targeted tests passed (four slow tests deselected), plus lint and
diff checks. All four families' health results match exactly; full-frame 6hb and
18hb checks also match. Cold and warm response hashes match for both playback
models. Isolated HMR is byte-identical, and both complete prepared packages have
identical scientific records, forcefields, restraint files and simulation
configurations. Differences are explicit provenance paths and the added HMR
receipt. Two intermediate warm-cache failures from a NumPy header-helper
compatibility mistake are preserved separately; corrected replacement probes and
the regression suite passed. No failed probe contributes to the final table.

These optimizations are enabled in the normal code paths. No new dynamics or
cloud jobs were needed; worker runtime totaled approximately 10.5 minutes.
No successful worker hit its 8 GiB cgroup limit or used swap. Existing admission
envelopes remain conservative: these paired measurements do not establish a new
universal upper bound. Engine RAM/VRAM, global allocator policy, public response
formats and scientific simulation settings are unchanged.

### Estimator recalibration after the RAM optimizations

The current review is in
`.development-artifacts/namd-script-scheduling-20261102/report.html`. It compares
442 eligible local engine observations: 426 fitting stages from completed
chains, seven separate margin-boundary checks, and nine fresh smoke tests.
The latter cover fast/Aksimentiev for 6hb, 2hb, 3x6hb and 18hb, plus a regular
minimize/run/minimize/run transition. Another 22 eligible cloud cases retain
their separate hardware scope and do not train the local residual model.

The report distinguishes elapsed-time-weighted process usage from the mean of
per-stage peaks and the largest recorded peak. Startup is included in the time
average, which makes short probes look much smaller than sustained requirements.
The 52 exclusion records include 21 successful prefixes of failed parent chains,
22 probes lacking contemporaneous engine identity, eight failed long runs and
one cloud overlap with a superseded analysis implementation/configuration mismatch.
These contribute neither current averages nor pass counts. Experimental shared-PME
builds are excluded from the default-engine model. Raw archives remain unchanged.

Eight fresh preparations cover all four families and both profiles. Together
with the prior two cube preparations and six compact health checks, these support
the following formulas, with `n` in millions of atoms and `b` in millions of
extra bonds. All results are rounded up to MiB:

| Work | Expected process peak | Admission allowance |
|---|---:|---:|
| Compact preparation | `128 + 600*n + 152*b` | `512 + 700*n + 192*extra_bonds/1048576` |
| Compact health | `160 + 303*n` | `256 + 400*n` |

Preparation defaults to a 2.6M restraint allowance before the exact count exists.
Its compact formula applies up to a 3.3M atom upper estimate, including solvent
count headroom, and up to 2.6M restraints; health applies up to 3M atoms. Outside
these domains, expected values are null and the preceding admission allowances
remain. Application/OS reserves are additional. The health budget propagates
through workflow reservations and preflight; preparation receipts and preflight
also expose the descriptive expected peak and its assumed restraint allowance.

Fresh 18hb preparation reached 2,335.9 MiB; its exact-count expected peak is
2,324 MiB and its allowance falls from 6,339 to 3,088 MiB. The 3x6hb allowance
falls from 4,674 to 2,361 MiB against a 1,696.7 MiB peak. For health, 18hb's
allowance falls from 4,087 to 1,448 MiB against a 1,072.2 MiB full-frame peak.
The rounded expected formulas differ from measured host-stage peaks by at most
3.9%; leaving a whole family out of the small fits gives maximum errors of 3.9%
for preparation and 5.5% for health. These are pilot validation errors, not
statistical confidence bounds for arbitrary chemistry or trajectory lengths.

Expected engine model v3 refits both modes using only the 426 eligible stages.
Patch count remains an **offload** feature. Whole-geometry holdout maximum errors
are 12.08% RAM / 22.75% VRAM for the 409 resident stages and 8.78% / 6.16% for
the 17 offload stages. Seven separate boundary cases have maximum errors of
1.38% RAM / 2.22% VRAM. The API explicitly labels these as
`expected_process_peak`; they are not time-average predictions. Model feature
length mismatches now make the detailed forecast unavailable instead of silently
truncating it. An unqualified model engine identity also disables the detailed
forecast. The offline fit script revalidates source provenance and reproduces
every installed coefficient exactly.

The nine fresh short runs remain independent of fitting. Expected RAM is
0.89–8.91% below their measured peaks; VRAM ranges from 13.31% below to 6.73%
above. Scheduling cannot remove these intrinsic engine residuals. Default engine
admission envelopes are unchanged: no overrun appears in 928 qualified RAM/VRAM
comparisons or the compact host checks. Correlated stages are not independent
statistical trials, and successful smoke tests do not establish long-run completion.

All eight fresh preparations completed without swap or cgroup limit events,
using 581.7 seconds of local worker time and no cloud spending. The targeted
estimator, admission, sampling, reservation and integration suite passed 195
tests. Reproduce the review with:

```bash
.venv/bin/python scripts/validation/namd_estimator_audit.py \
  --output .development-artifacts/namd-script-scheduling-20261102
```

### Script preflight and trajectory scheduling

Static NAMD settings must precede the first `run` or `minimize`. Resource preflight
rejects misplaced settings before reading large inputs. Literal repeated execution
commands are supported; `run norepeat`, `run upto` and arbitrary Tcl require
separate qualification. The trusted generated adaptive minimizer retains its
existing exact-template check. Probe rewrites insert settings before execution,
resume directives are replaced case-insensitively, and completion requires a clean
`End of program` marker; checkpoint writes followed by a fatal error are failures.
All nine replacement engine tests completed and validated checkpoint/DCD outputs.

Health checks, playback and bulk trajectory work share a cross-process activity
queue. Waiting creates no worker and does not consume its execution timeout.
Queued health has priority; equal-priority work is FIFO. In-flight probes retry
after five seconds if playback is active, leaving the engine/disk monitor free to
poll. Cancelling a native health call retains its slot until the call actually
finishes. Bulk work still waits behind managed simulations. Idle playback retention
is reduced from three workers to one per API process, with no idle retention during
a managed simulation; health, bulk analysis and memory reclamation close local
idle workers before allocating their contexts.

Paired tests used identical current algorithms, immutable trajectories and 10 ms
process-tree sampling. No NAMD engine ran during these analysis-only probes.
Ordinary simultaneous arrivals changed peak RAM by only about ±21 MiB. Deliberately
requesting eight playback pages during a health-memory peak gave:

| Model | Concurrent → scheduled peak RSS | Reduction | Batch time |
| --- | ---: | ---: | ---: |
| 3x6hb | 1,047.8 → 775.9 MiB | 271.9 MiB (26.0%) | 12.66 → 14.38 s |
| 18hb | 1,381.4 → 1,111.9 MiB | 269.4 MiB (19.5%) | 14.58 → 18.35 s |

All four pairs produced byte-identical playback and equal health results without
swap or memory-limit events. These are host-overlap savings, not a reduction in
NAMD's RAM/VRAM requirements or a universal bound. The fresh engine traces showed
no post-warmup episode above `median + max(64 MiB, 5%)`; their short durations do
not establish a long-run spike rate. Live engine buffers and browser GPU allocations
remain outside this CPU-work queue, so the engine admission ceilings remain intact.

---

## Install (prebuilt CUDA binary — recommended)

1. Get the binary from the NAMD download page
   (https://www.ks.uiuc.edu/Research/namd/) — register (free) and accept the
   license, then download **NAMD 3.0.2, Linux-x86_64 (multicore CUDA)**. The
   download is license-gated, so it can't be a blind `wget`.

2. Extract into `~/Applications/`:

   ```bash
   mkdir -p ~/Applications
   tar xf NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz -C ~/Applications/
   ```

   The tarball unpacks to a folder named exactly
   `NAMD_3.0.2_Linux-x86_64-multicore-CUDA/`, which matches a recognized NADOC
   path — no further config needed.

3. Smoke-test (prints the banner and reports the GPU it sees):

   ```bash
   ~/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3 +p4 +devices 0
   ```

   (It exits non-zero because no `.conf` was given — that's expected; you only
   care that it starts and lists your GPU.)

4. Restart the NADOC backend (`just dev`) and reopen the MD sidebar — the
   "missing" warning should be gone.

### Let NADOC finish the install for you

You still have to do the license-gated download by hand, but NADOC can take it
from there. In the app, **Help ▸ MD Engines** → NAMD row → **Download…** → after
you've downloaded the tarball, click **Check download & install**: NADOC scans
`~/Downloads`, verifies the file is the right package (correct build, and that it
actually contains `namd3`), extracts it to `~/Applications/`, and confirms
detection — no manual `tar`/path setup. psfgen comes with it. A freshly-installed
NAMD is detected without restarting the backend.

### Non-standard location

If you keep NAMD somewhere else, set the override before launching the backend:

```bash
export NADOC_NAMD_BIN=/path/to/namd3
just dev
```

To persist it, add the `export` to your shell profile (e.g. `~/.bashrc`) so the
backend process inherits it.

### psfgen (topology builder) comes free

NADOC builds all-hydrogen CHARMM topology with **`psfgen`**, which ships *inside*
the NAMD tarball (top level, next to `namd3`). Once you extract NAMD to
`~/Applications/...`, NADOC finds `psfgen` there automatically — no separate
install. For a non-standard location, set `$NADOC_PSFGEN_BIN=/path/to/psfgen`.
If a job fails with "psfgen not found", it's the same missing-NAMD situation as
above.

### Thread / core control

- `+p<threads>` is chosen by NADOC from the job config.
- `NADOC_NAMD_CORES` (e.g. `0-7`) pins NAMD to specific CPU cores via `taskset`.
  Leave unset to auto-bind to the first N cores.

### Automatic declash selection for crossover extra bases

NADOC chooses the declash relaxation tier from the longest insertion at any
single crossover or forced-ligation junction. The count is **per junction**, not
summed over the design:

| Design feature | Automatic declash? |
|---|---|
| No crossover extra bases | No |
| One extra base at a junction (`1xT`) | No |
| Two or more extra bases at one junction (`2xT`, `3xT`, …) | Yes |
| Sequence-bearing strand extension | Yes |
| Job submitted with `declash=true` | Yes |

A design may therefore contain many independent `1xT` crossovers without
automatically entering declash. Those single-stranded residues are still omitted
from the elastic network, so the standard ladder can relax them instead of
pinning their initial geometry. A pre-relaxed oxDNA seed (`pre_declashed=true`)
suppresses the extra-base automatic trigger, but does not override an explicit
declash request or the strand-extension trigger.

The automatic threshold controls protocol selection only. Ring-piercing, clash,
and bond-validation gates still inspect every extra base. Catenation/winding is no
longer computed or used as a seed metric. A covalent bond intersecting a nucleotide
ring remains a permanent defect and is refused by default; the Job Wizard's **Build
despite a ring piercing** option (`allow_ring_pierced_seed`) is the explicit override,
recorded as `ring_piercing_check` in the package manifest.

The outward bow used to separate reciprocal scaffold crossover linkers is limited to
the fast atomistic display and surface paths. NAMD seeds retain the exact minimized
bridge construction and the calibrated `1xT` extra-base placement.

---

## Building from source (only if you can't use a prebuilt binary)

The prebuilt CUDA binary is strongly preferred. Building NAMD 3 from the
`NAMD_3.0.2_Source.tar.gz` for GPU is a multi-step compile (build Charm++, then
configure NAMD `--with-cuda` against an installed CUDA toolkit with `nvcc`) and
takes a long time. Only go this route if no prebuilt binary fits your platform.
The output `namd3` then goes in any recognized path or is pointed at via
`$NADOC_NAMD_BIN`.

### On the Alpine cluster you have no choice — there is no CUDA NAMD module

CURC ships only CPU NAMD modules, and the local binary cannot be uploaded (Alpine is
glibc 2.28, our desktop build is 2.38). So NADOC builds its own GPU-resident NAMD 3 on
the cluster. `backend/core/cluster_build.py` drives it end to end — tarball the source,
submit an `acompile` job, verify the binary — via `POST /api/cluster/build/namd`.

The settings that are not obvious, each of which cost a failed build:

| Setting | Why |
|---|---|
| `--with-single-node-cuda` | The only flag that sets `-DNODEGROUP_FORCE_REGISTER`. Without it you get a CUDA build with **no** GPU-resident mode, which is the entire point. |
| `--with-tcl` + `tcltk/8.6.11` | `run` and `minimize` are **Tcl** commands, not native NAMD ones. Every conf ends in `run N`, so `--without-tcl` produces a binary that dies with `NOT VALID / run`. |
| `-ltcl8.6 -lz` | Alpine ships a *static* `libtcl8.6.a`, which does not pull zlib in transitively the way Ubuntu's `.so` does. |
| `cmake/3.27.7` | Absent from the default environment; without it the build silently falls back to `buildold`. |
| default gencodes | Leave NAMD's curated arch list alone. The sm_90 binary PTX-JITs onto sm_89 (al40) — measured — so one build covers the fleet. |

Modules: `gcc/11.2.0 cuda/12.1.1 cmake/3.27.7 fftw/3.3.10 tcltk/8.6.11`. Point the
cluster profile's `gpu_namd_bin` at the result.

**Probe with `module spider`, never `module load`.** Alpine's Lmod is hierarchical, so a
login node refuses loads that succeed on a compute node — a pre-flight built on `module
load` reports confident false negatives. See LESSON L14.

---

## Troubleshooting

Trajectory playback retains at most **512 MiB of numerical payloads per browser
tab**, shared across coordinate pages, atom/surface/solvent caches, downloads and
prepared clips. Array views are charged for their full backing buffer; sharing a
buffer does not double-charge it. Old pages are evicted and reloaded exactly from
the saved trajectory. Whole-range consumers must fit the shared allowance, and
at most two completed preparation sessions are retained. Closing or cancelling
a trajectory releases its buffer ownership.

Binary trajectory/model downloads reject bodies above **128 MiB per response**.
NAMD atom and solvent extraction also checks a **128 MiB working allowance** that
includes output/packing copies; the viewer requests smaller batches accordingly.
Oversized requests return HTTP 413 with a smaller-range instruction. Surface
responses check mesh size before expanding it into Python/JSON arrays; this does
not bound the surface generator's own temporary mesh allocations.

These are payload limits, not total browser RAM/VRAM limits. Static topology,
render geometry, JS objects, network/decode scratch, other tabs and garbage
collection need additional headroom. Changing playback retention does not change
NAMD forces, integration, DCD output or saved-frame precision. Qualification
measurements and the exact-frame reload checks are in
`.development-artifacts/trajectory-retention-20261101/`.

| Symptom | Cause / fix |
|---------|-------------|
| Sidebar: "NAMD 3 is missing" | Binary not on any recognized path. Set `$NADOC_NAMD_BIN` or install to `~/Applications/...`. Restart the backend after. |
| `nvidia-smi` fails inside WSL | Windows NVIDIA driver missing/old, or a Linux driver was installed inside WSL. Fix on the Windows side; never install a Linux GPU driver in WSL. |
| `WARNING: +devices ... not parsed by the RTS` | You're running the **CPU-only** build. It still runs (on CPU). Install the `multicore-CUDA` build for GPU. |
| Fully solvated system does not fit / NAMD aborts allocating GPU memory | Use a larger-memory GPU, a sufficiently large CPU host, a smaller construct or defensible cell, or GBIS if continuum solvent is acceptable. NADOC does not carve away water. |
| GBIS is unavailable | Install the plain `Linux-x86_64-multicore` NAMD build. GBIS cannot use GPU-resident mode and NADOC currently routes it to this CPU build. |
| Override ignored | `$NADOC_NAMD_BIN` must point at an **executable** file (or PATH-resolvable name). A bad path is silently skipped and resolution falls through. |


### Runtime and cost comparison (2026-11-02)

The Job Wizard compares local, Alpine and Runpod using the same planned stage
counts, timesteps, execution modes and box. It separates simulation throughput
from preparation, engine startup, boundary health checks, uploads, downloads and
local trajectory processing. A production continuation uses its prepared parent
size and skips full preparation. Intended production is counted once alongside
relaxation. Transfer rates can be edited in the comparison.

Local 16-thread timing uses 322 qualified resident stage observations and 14
minimization observations, grouped by geometry for holdout validation. These
are correlated measurements, not 336 independent jobs. Four long offload phases
supply a separate estimate only for the matching 786,194-atom, fine-PME cube with
32 threads. Other thread/mode/geometry combinations use explicitly broader
priors; unmatched local GPUs/engines have no quote. Recent wall TIMING windows
replace startup Benchmark lines when learning throughput or updating a live ETA.
GPU learning is scoped by model, not shared blindly across an architecture.

The displayed low/high values are planning scenarios, not 99% intervals or
completion guarantees. Remote performance still needs matched target measurements.
Alpine's fallback now shares Runpod's per-step hardware priors instead of
extrapolating the old 63k-atom MIG production point to every whole GPU. Queue
waits remain unknown for the actual request; a QoS walltime cap never truncates
full-job duration or cost. Costs are local rental fee (electricity excluded),
Alpine SU, and Runpod USD respectively.

Runpod S3 uploads happen before rental and result downloads after termination;
SSH transfers keep the pod billing. The budget check uses the selected GPU's
upper planning bill, including setup/startup/checks and container storage.
Network-volume rent is shown separately for the forecast window and per month;
it persists after the run and is outside the per-pod kill switch. Standard-tier
rates and the 30 GB container default are used, with live GPU prices when
connected. Premium storage, tax, retries and physical convergence extensions are
not priced. Billing references checked on 2026-11-02:
[Pod pricing](https://docs.runpod.io/pods/pricing) and
[network-volume tiers](https://docs.runpod.io/storage/network-volumes).

`POST /md/runtime-preview` is read-only. The same completion accounting feeds
Runpod job previews and Alpine sizing/review. Reproduce the geometry timing fit
with `.venv/bin/python scripts/validation/fit_namd_timing.py`; detailed evidence
and qualification replay are in
`.development-artifacts/namd-runtime-estimator-20261102/`.

The remote geometry prior was replayed against 22 qualified RTX 6000 Ada boundary
probes. A linear scaling with allocation volume overpredicted the median step
cost by 2.23x. Sublinear neighbor/PME scaling reduced that ratio to 1.12x; CPU
offload startup is accounted separately from resident GPU FFT startup. These
same probes informed the adjustment, so this is calibration replay, not a new
independent performance qualification.
