---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---
# MD job system

Canonical current-state guide for managed NAMD jobs, the Job Wizard, local/remote execution,
queueing, production spawning, health reporting, and resume behavior. Historical implementation
narratives are in [the archive](project_md_job_system_archive.md).

## Current state

- The Job Wizard is both creator and read-only settings viewer. It owns execution target,
  protocol/stage parameters, SLURM resources, RunPod GPU choice, anchors, production settings,
  and safety overrides.
- The run queue replaces Chain Simulations. Local queue occupancy is target-aware: a remote run
  must not block local work.
- Relaxation and production share the same parameter provenance and cell lineage. Production
  inherits the prepared cell rather than resizing it.
- Throughput and cost must come from measured runs for the same engine, hardware, system scale,
  integrator, and stage type; never infer production speed from relaxation.
- Job snapshots and package metadata are immutable inputs for downstream metrics and display.
- Resume/reconcile treats completed outputs as the strongest evidence and distinguishes work that
  never launched from an unrecoverable segment failure.
- Preparation heartbeat liveness continues until the background coroutine is explicitly finished,
  not merely until its progress tracker reaches 100%. A queued job with a completed manifest heals
  the legacy false "Preparation was interrupted" verdict during reconciliation.

## Binding invariants

- `job_is_running` answers whether a job can be stopped; queue occupancy is the narrower,
  target-aware question.
- Wizard-selected RunPod GPU wins over legacy picker state. Non-RunPod targets clear that key.
- A billing pod must remain visible and terminable even when RunPod is not the selected target.
- RunPod credentials are memory-only; after backend restart the UI must request reconnection and
  recovery rather than silently displaying frozen job state.
- Production timestep is 4 fs. Fix invalid geometry or constraints; do not silently lower the
  scientific production timestep.
- GPU-resident compatibility is probed from the emitted configuration. Fixed atoms, carved-water
  cases, pinned-memory limits, and tile-list failures must route through their explicit gates.
- Heavy integration tests remain test-session-only; ordinary changes use `just test-smart`.

## Open work

1. Retire the duplicate legacy RunPod GPU picker after confirming no remaining caller depends on it.
2. Surface cluster build/module/probe remediation in the UI where the wizard reports module issues.
3. Make archived-job deletion fail safely when its archive volume is unavailable instead of
   dropping the index record and orphaning the directory.
4. Continue removing dead MD parameter modules only after proving zero live consumers.

## Verification

Use fast job/queue/wizard tests through `just test-smart`. Real NAMD, remote cluster, and rented-GPU
checks require their dedicated runbooks and user-authorized environments.
