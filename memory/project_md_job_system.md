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
- Copying a relaxation job (including a failed Alpine job) creates an editable draft with
  `autostart=False`; copying never starts preparation or submits to a remote executor.
  Native copies retain their source's frozen `design.json`, which Run uses instead of the
  currently open document. Ordinary wizard drafts still freeze the live design at Run.
- Draft launch controls use the saved execution target: Alpine drafts show “Submit to Alpine”
  with the connection gate, while retaining preparation before submission. Saving target edits
  on the selected job also refreshes the execution-target radio and cluster pane.

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

## R1 graphene force-field correction (2026-09-04)

R1 `0a2aaa5638ff` / Slurm `32088967` failed at k=0.1 step 14: unbonded
graphene CA sites experienced enormous mutual LJ repulsion at 1.42 Å. New
packages use dedicated NGRC sites with CA cross LJ and zero NGRC–NGRC NBFIX
in `par_np_thiol.prm`. Geometry, anchor stiffness and 4 fs timestep are unchanged.
`namd_graphene.validate_graphene_wall_package` blocks legacy wall packages before
Alpine submit/resume, local execution and RunPod provisioning. Copy + Run must
rebuild and minimize; old graphene checkpoints are not reusable. Copy remains an
editable draft and does not prepare or submit. See `docs/namd_graphene_wall_failure_audit.md`.

Graphene UI default: the nanopore checkbox starts off and resets off on workspace
file changes and job deselection/removal. Selecting a job restores its inherited
`prep_params.graphene_nanopore`; empty-list polling does not erase a user's manual
choice while configuring a new job.

## Restrained graphene NPT and Alpine verification (2026-09-05)

Restrained graphene NPT uses a minimum piston period/decay of 10000/5000 fs across
relaxation and appended/replica production, preserving slower choices and NVT.
This prevents the k=0.1 recovery's gentler piston from resetting at k=0.01. Local
piston-only controls completed 5000 steps at 4 fs; full-ladder stability is unverified.
The user-created Alpine copy `e75ffd56c6f8` / SLURM `32108809` was observed RUNNING
with all 75 inputs successfully transferred and all 22 NPT configurations corrected.
See [barostat diagnosis and validation](../docs/namd_graphene_barostat_failure_audit.md).
