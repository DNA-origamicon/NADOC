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

- PEG qualification/fast-relax visualization now routes the shared Display MD, RMSF,
  trajectory, solvent/cell and atomistic representation controls to saved PEG atom
  indices. Active-stage frames and continuation rollback are supported. Production-only
  occupancy and DNA-specific analyses expose applicability limits; see
  [PEG visualization](../docs/namd_peg_visualization.md).

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

An isolated PEG-only repulsive-wall qualification now lives in
`experiments/peg_wall/`, with shared force logic in `backend/core/namd_peg_wall.py`.
It uses pinned additive ether/TIP3P assets, native harmonic graft restraints and
Tcl wall forces with explicit GPU-resident MD. Native 1,000-iteration minimization
and 1 ps resident qualification passed on 2026-09-12 (9,092 atoms). Persistent
`workspace/NAMD_PEG8_wall_review.nadoc` and completed jobs `94d4b96fd8d7` /
`654049290521` provide dedicated atomistic playback. The review now creates managed `peg_fast_relax` child jobs: 25 ps at 2 fs, then
one 4.8 ns 4 fs/HMR NVT rung with p10/p50/p100 chunks and PEG-aware skip decisions.
Permanent grafts/walls persist; DNA health and ENM release are inapplicable.
A full shortened 125 ps lifecycle passed (`ab217dbdf612`); full-length job
`48c1995afbd5` completed native p10 (480 ps) but was falsely marked failed:
continuation ENERGY rows before ETITLE were dropped by the parser. The new
strict PEG evidence reader fixes delayed/headerless parsing and pairs samples by
restart epoch (numeric suffix order, rollback truncation). Untouched native p10
now passes all 30 frames, but does not plateau. Two-window per-chain convergence
and precise failed-check messages are covered by positive/negative runner tests.
See `docs/namd_peg_skip_validation.md`. Native inputs remain unchanged. The ordinary
API resumed the job into p50; resident mode and a new trajectory frame were verified.
The full job has since completed all chunks (25 ps + 4.8 ns), with saved safety
checks passed and no job error. No chunk was skipped; energy/polymer plateau
criteria remain false. See `docs/namd_dna_peg_readiness.md` for the covalent-junction,
mixed-system preparation, health and visualization gaps. Production promotion remains deferred.
See `docs/namd_peg_fast_relax.md`; MC seeding is assessed but not implemented. See
`docs/namd_peg_wall_validation.md` for the parameter contract and barriers.

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

## Graphene display controls — 2026-09-05

The NAMD Hard surface card has a display-only **Show nanopore** checkbox and
**Simple plane / Ball / Stick** dropdown, separate from **Add graphene nanopore**.
Browser preferences (`nadoc.grapheneDisplay`) apply to the setup preview and actual
MD carbon coordinates, including paused frames. These controls never alter job
parameters, force fields, or simulation inclusion. MD display continues to suppress
the design preview; hiding graphene persists through frame updates and returning
to the preview.

`graphene_display_controls.js` owns preferences; `graphene_representation.js` owns
carbon rendering. Sticks infer nearest-neighbor visual edges with a 0.19 nm cutoff,
without adding simulation bonds or drawing periodic edges across the cell. The MD
plane fills complete carbon hexagons, preserving the pore and transformed membrane
position. Visual adjacency is retained between frames and reset on clear/new data.

## Direct NAMD PEG surface drafts (2026-09-11)

File → NAMD PEG Surfaces and the NAMD sidebar now open a standalone surface draft
editor, usable without DNA or an oxDNA source. It saves workspace-level definitions
under `namd_surfaces`, with support/plane/patch, density/seed, PEG representation,
chain length and chemistry/asset notes. Review uses shared plane geometry and a
schematic graft preview. The API is `/api/md/peg-surfaces`; create/list/update/review
never invoke engine preparation. Drafts are not attached to ordinary NAMD jobs yet.
Target assets, graft/cross interactions, molecular construction and engine validation
remain explicit blockers. See [direct PEG surface setup](../docs/namd_peg_surfaces.md).
