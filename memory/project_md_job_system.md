---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---

# MD job system

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Production promotion remains deferred where native qualification failed or plateau criteria remain false. The electrode/PEG evidence and current-state details below retain those limits. Focused development checks are authorized by the task; broad suites and scientific campaigns follow current [repository policy](../CLAUDE.md), superseding the older blanket heavy-test sentence in the retained invariants.

## Unattended oxDNA chains (2026-10-02)

Local production children auto-start inside `unattended_chain_spawn`; ordinary
interactive production creation still queues for Run. The prior queue-only
production endpoint stranded chains after their first completed stage. The real
three-stage orchestration regression (mock engine only) now completes all stages.

<a id="solvent-padding-default-2026-09-30"></a>
- [Solvent padding default (2026-09-30)](details/project_md_job_system/01-solvent-padding-default-2026-09-30.md#solvent-padding-default-2026-09-30)

<a id="bare-gold-qualification-2026-09-14"></a>
- [Bare gold qualification (2026-09-14)](details/project_md_job_system/01-solvent-padding-default-2026-09-30.md#bare-gold-qualification-2026-09-14)

<a id="box-and-solvent-sidebar-2026-09-13"></a>
- [Box and solvent sidebar (2026-09-13)](details/project_md_job_system/01-solvent-padding-default-2026-09-30.md#box-and-solvent-sidebar-2026-09-13)

<a id="current-state"></a>
- [Current state](details/project_md_job_system/01-solvent-padding-default-2026-09-30.md#current-state)

- [Current state — continued detail](details/project_md_job_system/01-solvent-padding-default-2026-09-30.md)

## Replica duration metadata (2026-11-03)

Production replicas record their resolved timestep on each manifest segment as
well as on the job. Resource planning sums per-segment timesteps; leaving the
segment default at 2 fs understated 4 fs production duration by half. The emitted
NAMD configuration and integrator choice are unchanged.

## CPD fast-integrator qualification (2026-11-04)

Startup follow-up: the initial direct-NAMD smoke bypassed managed memory
admission. The user's cis-anti production child `949886d10003` failed before
NAMD because `namd_resources.configuration_memory` did not recognize the
builder's `reinitvels` directive. It now accepts this existing velocity-array
operation while retaining the static-order and dynamic-Tcl refusals. Actual
create/start HTTP handler validation is in `scripts/check_cpd_managed_start.py`;
the earlier builder-only smoke is not evidence for job-manager admission.

The four provisional MVP CPD models can use 4 fs/HMR with rigidBonds all, gated
by exact native-tested asset hashes. Untested/changed force fields retain their
ordinary-mass <=2 fs policy. Preparation, export, production children, appended
production and wizard plans share the qualification. A CPD mass switch redraws
velocities and is recorded/shown explicitly; equal-mass continuations preserve
them. Failed CPD HMR preparation refuses the requested launch without a timestep
downgrade. Historical mixed I10/I8 PSFs now repartition correctly. See
`docs/audits/cpd_hmr_validation_20261104.json` for the paired numerical panel,
retained short-window failure, bounded confirmation and independent audit.

## External restart display reconciliation (2026-11-04)

A selected terminal job must refresh its detail panel when a list update observes
its status change. Otherwise an API/other-tab restart updates the list and Pause
control but leaves a failed timeline and no status subscription. `_fetchJobs`
now reopens the selected detail on status transitions; a request version prevents
an older terminal REST response from repainting over the new run. The regression
checks failed → running timeline recovery and exactly one socket across refreshes.

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

<a id="r1-graphene-force-field-correction-2026-09-04"></a>
- [R1 graphene force-field correction (2026-09-04)](details/project_md_job_system/02-r1-graphene-force-field-correction-2026-09-04.md#r1-graphene-force-field-correction-2026-09-04)

## Restrained graphene NPT and Alpine verification (2026-09-05)

Restrained graphene NPT uses a minimum piston period/decay of 10000/5000 fs across
relaxation and appended/replica production, preserving slower choices and NVT.
This prevents the k=0.1 recovery's gentler piston from resetting at k=0.01. Local
piston-only controls completed 5000 steps at 4 fs; full-ladder stability is unverified.
The user-created Alpine copy `e75ffd56c6f8` / SLURM `32108809` was observed RUNNING
with all 75 inputs successfully transferred and all 22 NPT configurations corrected.
See [barostat diagnosis and validation](../docs/namd_graphene_barostat_failure_audit.md).

<a id="graphene-display-controls--2026-09-05"></a>
- [Graphene display controls — 2026-09-05](details/project_md_job_system/03-graphene-display-controls--2026-09-05.md#graphene-display-controls--2026-09-05)

<a id="direct-namd-peg-surface-drafts-2026-09-11"></a>
- [Direct NAMD PEG surface drafts (2026-09-11)](details/project_md_job_system/03-graphene-display-controls--2026-09-05.md#direct-namd-peg-surface-drafts-2026-09-11)

- [Direct NAMD PEG surface drafts (2026-09-11) — continued detail](details/project_md_job_system/03-graphene-display-controls--2026-09-05.md)

- [Direct NAMD PEG surface drafts (2026-09-11) — continued detail](details/project_md_job_system/04-direct-namd-peg-surface-drafts-2026-09-11.md)

## Saved box display (2026-10-25)

Box and solvent now separates selected prepared jobs from new preparation intent.
Selected jobs use `getMdSolventMeta` for initial package dimensions and actual ion
counts, label their source and creation date, and do not recompute clearance using
the current design. Unavailable package dimensions never fall back to defaults.
View settings also uses the saved cell rather than estimating from the open design.
New relaxation restores document setup; production still inherits its package.
See `docs/namd_box_sizing.md`. This fixes a misleading historical-job preview;
it does not change any existing simulation box or ionic composition.
