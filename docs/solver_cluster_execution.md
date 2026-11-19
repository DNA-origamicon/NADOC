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
submit a job. Select a CPU partition for SNUPI, or a GPU partition for mrDNA.
CPU cores, RAM, QoS, account and walltime are explicit. Hydrodynamics preflight
uses 80% of requested RAM, leaving allocation headroom. Large-job estimates are
not convergence guarantees.

For RunPod, select a network volume through the existing account setup. SNUPI
automatically provisions Python 3.12 and pinned CPU-worker dependencies at the
default `/workspace/nadoc-solver-env/bin/python` path, then reuses that environment
on later pods. Setup is serialized on the volume and included in the pod budget.
Custom Python paths are checked without modification. mrDNA still requires its
installed environment and ARBD on the volume. Choose a GPU from a live price query. Host RAM and vCPU minima are separate
from GPU VRAM. SNUPI uses CPU even though this provider flow rents a GPU pod.
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
- Dynamics and hydrodynamics pilots timed out during setup; the remote terminal
  stack was not captured, so hydrodynamic matrix capacity remains unmeasured.
- mrDNA Fine model preparation advances beyond the old clustering memory barrier,
  but its external PDB writer rejects residue 100000 (ISSUE-223).
- No production GPU implementation of SNUPI was introduced here.

## Part/assembly parity

| Contract | Implementation |
| --- | --- |
| Controls, defaults, validation, Coarse/Fine options | Shared cards and request models for both hosts. |
| Target and history | Current part or whole assembly; existing assembly simulation projection preserves source ownership. No authoring changes. |
| Start, stop, reconnect, errors | Shared provider adapters and persisted receipts; no local PID inference for remote jobs. |
| Results, export, downstream consumers | Downloaded into the original native job directory; existing viewing/export paths retained. |
| Persistence and cleanup | Saved execution target/settings; active or uncollected remote receipts block archive/delete. |
| Progress | Scheduler/provider state, with no invented percentage or ETA; live native phase streaming is not implemented. |
| Resume | No checkpoint continuation on either host; new jobs start from the initial snapshot. |
| Scale exceptions | Existing periodic-strand materialization issue, slow dynamics setup, and mrDNA Fine PDB identifier limit remain explicit above. |

The browser contract test exercises both engines and both providers on each host
with provider/job submissions intercepted. Backend tests exercise scheduler and
provider success/failure, receipt uncertainty, cancellation, result acceptance,
and paid-pod cleanup without allocating hardware. Live SNUPI deployment is verified by BigO-poly coarse + RMSF job `b958e97feeae`
(November 18, 2026): 18.8 minutes, 424,144 finite nucleotide positions, results
downloaded and readable through NADOC, pod termination independently confirmed.
Live mrDNA deployment through these adapters remains unverified.

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
