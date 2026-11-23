# SNUPI and mrDNA on Alpine and RunPod

The SNUPI and mrDNA **Clusters** cards select Local, Alpine or RunPod for the
existing Coarse/Fine launch buttons. The same cards and solver options apply to
parts and whole assemblies. Assembly preparation uses the existing simulation
materializer; this change does not resolve the deferred periodic-strand issue
(ISSUE-163) or change molecular geometry.

The cards follow the shared Jobs → Clusters → Advanced order, with the same
header, provider radio row, connection controls and GPU picker as NAMD/oxDNA.
Expand **Solver settings** under Alpine or RunPod to edit environment paths and
resource limits. Unavailable solver time/cost predictions display as dashes.

## Software preparation

Alpine and custom RunPod Python environments must already exist. Use an absolute
executable path, not an activation command. They need the NADOC worker dependencies;
mrDNA also needs its package and an executable named `arbd`.
Follow [mrDNA setup](mrdna_setup.md) for its external dependencies. ARBD must be
built for the allocated GPU and have its runtime libraries available. The card
checks Python dependencies before submission; compute-node GPU behavior still
requires execution validation. No private local binary is uploaded as a portable
cluster installation.

For Alpine, create the environment in persistent project storage, then enter its
Python path in the card. **Check Alpine environment** is read-only and does not
submit a job. Static SNUPI uses CPU partitions; linear/Stokes SNUPI dynamics
can accelerate on a GPU partition when its Python environment has CUDA-enabled
PyTorch. mrDNA requires a GPU partition.
CPU cores, RAM, QoS, account and walltime are explicit. Hydrodynamics preflight
uses 80% of requested RAM, leaving allocation headroom. Large-job estimates are
not convergence guarantees.

For RunPod, select a network volume through the existing account setup. SNUPI
automatically provisions Python 3.12, pinned core dependencies and PyTorch 2.9.1
CUDA 12.8 wheels at the
default `/workspace/nadoc-solver-env/bin/python` path, then reuses that environment
on later pods. Setup is serialized on the volume and included in the pod budget.
Custom Python paths are checked without modification. mrDNA still requires its
installed environment and ARBD on the volume. Choose a GPU from a live price query. Host RAM and vCPU minima are separate
from GPU VRAM. Supported SNUPI dynamics selects float64 CUDA automatically when
runtime VRAM admission succeeds. Static calculations, hydrodynamics, modified GJF,
nonlinear forces and simulated tails retain the CPU implementation. Missing CUDA
or insufficient VRAM also selects CPU, with the reason recorded in job `execution`
metadata. Mandatory RAM admission is retained for this fallback; CUDA is optional.

`NADOC_SNUPI_BACKEND=cpu|cuda|auto` controls the managed worker (default `auto`).
Explicit `cuda` fails rather than silently changing an unsupported model. Device
state and random generation remain on GPU; only sampled translations are returned.
Precision is float64, and timestep/force/sampling rules remain unchanged. GPU random
streams differ from NumPy; backend, RNG and Torch version are recorded. Local and
custom Alpine environments must install compatible CUDA-enabled PyTorch themselves.
Managed RunPod setup is automatic only at the default interpreter path. Dependency
preflight allows up to 180 seconds for cold imports on the network volume;
missing dependencies still deny startup. Packaging large native result archives
allows up to 900 seconds. The paid-pod budget/watchdog remains active throughout.
The provider GraphQL deployment supports explicit RAM/CPU minima:
[RunPod deployment documentation](https://github.com/runpod/docs/blob/main/sdks/graphql/manage-pods.mdx).

RunPod's compute budget includes startup, environment checks, simulation and result
transfers. Network-volume charges are separate. The controller rechecks the live
rate, records spend from pod creation, requests provider expiry, and installs an
independent exact-pod watchdog using the matching key stored in `~/.runpod_key`. It refuses
to proceed if the watchdog cannot start. There are no automatic retries. The
watchdog survives the API/editor exiting, but is a local user service and does not
survive a host shutdown. Keep the host available during a paid run.

## Job lifecycle and evidence

The adapter uploads the current backend implementation plus the job's existing
simulation snapshot and options. `submission-manifest.json` records their hashes.
Source part/assembly files are not modified. Result coordinates remain physical
simulation/display data, not topology edits.

Alpine submission receipts and scheduler IDs are persisted. A lost submission
response is resolved from the remote receipt; it never triggers an automatic
second submission. Disconnects retain the last observed state. Polling resumes
when jobs are read after reconnecting. A scheduler success alone does not mark a
job completed: the native solver must report success, match the submitted job
identity, and supply its display result, which is downloaded first.

Stop sends `scancel` on Alpine or destroys the exact RunPod pod. Active or
uncollected remote jobs cannot be deleted or archived. Timed-out jobs do not
resume automatically. Creating a new run restarts from its initial snapshot;
SNUPI/mrDNA checkpoint continuation is not implemented by these adapters.

If the RunPod controller exits, its watchdog bounds the remaining rental and the
job reports interruption after restart. It is not automatically re-rented. Remote
files remain on the selected network volume; recovering interrupted output from
that volume is currently a manual operation. Successful runs download their
native output and enter the existing local result-viewing flow.

## Current BigO-poly limits

- SNUPI NMA completed on Alpine at approximately 46 GiB RSS; 64 GiB is a provisional
  allocation, not a measured minimum.
- Historical dynamics/hydrodynamics pilots timed out during setup. Bounded timestep
  selection subsequently completed the 2-mer and 10-mer Stokes runs; dense
  hydrodynamic matrix capacity remains a separate limit.
- mrDNA Fine model preparation advances beyond the old clustering memory barrier,
  but its external PDB writer rejects residue 100000 (ISSUE-223).
- Linear/Stokes GPU dynamics and cached result reconstruction are installed as of
  November 19; full same-host validation is recorded in `memory/project_snupi_dynamics.md`.

## Part/assembly parity

| Contract | Implementation |
| --- | --- |
| Controls, defaults, validation, Coarse/Fine options | Shared cards and request models for both hosts. |
| Target and history | Current part or whole assembly; existing assembly simulation projection preserves source ownership. No authoring changes. |
| Start, stop, reconnect, errors | Shared provider adapters and persisted receipts; no local PID inference for remote jobs. |
| Results, export, downstream consumers | Downloaded into the original native job directory; existing viewing/export paths retained. |
| Persistence and cleanup | Saved execution target/settings; active or uncollected remote receipts block archive/delete. |
| Progress | Provider startup, mesh, stiffness, timestep, integration, analysis and download stages. Integration percentage uses actual completed dynamics steps; unknown startup durations remain indeterminate. |
| Resume | No checkpoint continuation on either host; new jobs start from the initial snapshot. |
| Scale exceptions | Existing periodic-strand materialization issue and mrDNA Fine PDB identifier limit remain explicit above; bounded timestep selection replaces the former unbounded dynamics setup. |

The browser contract test exercises both engines and both providers on each host
with provider/job submissions intercepted. Backend tests exercise scheduler and
provider success/failure, receipt uncertainty, cancellation, result acceptance,
and paid-pod cleanup without allocating hardware. Live SNUPI deployment is verified by BigO-poly coarse + RMSF job `b958e97feeae`
(November 18, 2026): 18.8 minutes, 424,144 finite nucleotide positions, results
downloaded and readable through NADOC, pod termination independently confirmed.
Live mrDNA deployment through these adapters remains unverified.

## CUDA RunPod benchmark — November 19–20, 2026

Normal managed submissions of `BigO-poly-2monomer.nass`, `BigO-poly-10monomer.nass`
and the independently replayed `BigO-poly-30monomer.nass` completed with actual
float64 CUDA execution, native results collected, and every pod automatically
destroyed. Each used 60,000 steps at 0.13 ps, 1,200 samples and 40 output frames,
an A100 80GB PCIe, 80 GiB requested host RAM and eight requested vCPUs.

| Assembly | Solver time | Fold vs 2-mer | Paid pod lifetime | Compute cost |
| --- | ---: | ---: | ---: | ---: |
| 2-mer | 41.75 s | 1.00× | 6.74 min | $0.235 |
| 10-mer | 179.84 s | 4.31× | 10.81 min | $0.376 |
| 30-mer | 485.80 s | 11.64× | 37.53 min | $1.307 |

For 10→30 monomers, three times the FEM nodes required 2.70× total solver time
and 2.87× integration time (23→66 s). Solver time includes setup and analysis/save;
paid lifetime additionally includes startup/imports, staging, compression,
transfer and cleanup. The 30-mer archive is 838 MB; transfer now dominates
end-to-end time. These are single observed cloud runs, not a controlled
CPU-versus-GPU speedup: 2-mer CPU host EPYC 9374F, 10/30-mer hosts EPYC 7543.

Coarse, Flexibility and trajectory views pass for all three sizes, including
frame-21 scrubbing and Off cleanup. The completed 30-mer clears spinner/Stop and
shows all stages Done with RunPod selected. Cosmetic stale-sync wording on
terminal receipts remains tracked as ISSUE-255.

Every delivered trajectory/display is finite and RMSF is nonnegative. Source and
input hashes match submission. An on-pod matched-noise CPU/CUDA kernel control
has maximum state difference 2.0e-15 with deployed Torch 2.9.1+cu128. Short runs
benchmark execution and do not establish physical equilibration.

Validation exposed cold-import and result-packaging timeouts (ISSUE-253/254),
now bounded at 180/900 seconds respectively. One earlier 30-mer solved in
693.43 s on EPYC Genoa but failed collection; its receipt remains retained.
Total compute including that failure and the failed cold-import attempt: $2.629;
network-volume storage is separate. Detailed receipts and test limitations:
[SNUPI dynamics notes](../memory/project_snupi_dynamics.md).

## Validation — November 18, 2026

- Browser: both engines × both providers × both hosts passed; saved part and
  assembly construction independently replayed. Temporary browser workspace removed.
- Frontend: 984 files; 10,706 passed, 1 skipped. Smoke: 24 passed, 2 skipped.
- Focused backend: 95 passed. Lint passed. `main.js` LOC delta: 0.
- `test-smart`: FAST; 21,117 passed, 19 skipped, one existing ISSUE-221 gesture
  failure. FULL deferred by the session guard. Aggregate timing threshold exceeded
  (530 seconds); no individual test exceeded 5 seconds (maximum 4.73 seconds).
- Evidence: `.development-artifacts/solver-cluster-cards-20261118/final-review.json`.
  These checks do not establish live provider/native-solver deployment success.

### Resource selection before launch

With Alpine or RunPod selected, Coarse/Fine now opens a resource wizard before
creating a job. It estimates the current part or complete assembly using the
selected solver options, disables insufficient RAM/VRAM choices, and requires a
review confirmation. Cancel leaves no job. RAM allocations retain 20% headroom;
GPU eligibility retains 15% of nominal VRAM. These planning envelopes are not
measured peak guarantees.

Alpine offers whole-card partitions from the cluster profile, with RAM limited by
allocated cores and QoS walltime. `gpu_vram_gb` records whole-card nominal capacity;
unknown capacities are ineligible for mrDNA. MIG selection is not exposed here.
RunPod filters live GPU stock/quotes to the selected network volume's datacenter
and requested host RAM/vCPUs. It checks again before review and rental, including
GPU memory and price. Capacity can still change before deployment; a supply
failure reports that no pod was rented and requires a new explicit choice.
Wizard fields and navigation buttons use NADOC's standard themed controls. Local launches continue to
use the existing admission popup and available-memory checks.


### Resource comparison list

The resource wizard shows a scrollable, keyboard-selectable list with memory,
availability, estimated wait and estimated completion columns, plus an explicit
availability refresh. Ineligible rows remain visible with the reason they cannot
be selected. RunPod refreshes stock and price for the current RAM/CPU allocation
at the selected volume's datacenter; confirmation still rechecks before rental.

Alpine wait is the shared general partition forecast, not a placement test for
this solver allocation. Whole-card resource forecasts exclude MIG slices. CPU
partitions currently have no queue forecast from that endpoint. Maintenance and
later scheduler starts are shown alongside the list.

Completion combines a known Alpine wait with the existing SNUPI/mrDNA reference
runtime heuristic. Without a known wait, it displays runtime plus unknown wait
or pod startup. These are rough solver estimates, not calibrated speed rankings
across hardware; they exclude transfers and environment checks and can be
inaccurate for large systems. The requested maximum time remains a separate cap.

### SNUPI dynamics progress

RunPod polls the worker's bounded progress receipt alongside process status;
Alpine retrieves it during scheduler refresh. Telemetry lives separately from
job metadata so polling cannot overwrite cancellation or completion. Missing or
partial telemetry does not abort the solve.

Dynamics percentage is completed integrator steps divided by planned steps
(default 60,000), independent of the static load-step setting. Setup shows an
indeterminate bar with the worker's current phase. During integration the UI
shows completed/total steps, steps remaining and a measured integration ETA.
Setup time is excluded from the rate; a retry resets the counter and rate.
A receipt not retrieved for 30 seconds is labelled last known and loses its ETA.
Integration at 100% can still be analyzing or downloading results; the job state
and phase remain visible until completion. No timestep or physics changes were
made for this progress update.

The SNUPI dynamics timeline separates remote preparation, mesh, stiffness, stable
timestep calculation, optional hydrodynamic friction, integration, analysis/save
and download. The dynamics counter belongs to integration. Stage completion is
derived from subsequent worker phases, not elapsed time or an equal division of
the percentage bar. Unknown phases leave scientific stages pending. The current
phase becomes last-known when transport is stale, and terminal jobs stop showing
a running stage. Existing workers supply these phases without redeployment.
