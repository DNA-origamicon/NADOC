---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---

# MD job system

Remote result controls use termination wording only for active jobs or pending
Alpine cancellation (2026-11-10). Terminal RunPod jobs show download/retry wording,
honor persisted verification, and expose local verification failures. An explicit
`runpod_pod_connected: false` disables the download action: historical pod IDs do
not establish access. The finish endpoint still requires a reachable pod; this UI
fix does not provision recovery pods or alter saved jobs.

The generic “Inputs changed” job-row label was removed at user request (2026-11-10).
Prepared-input evidence and execution guards remain intact; the list no longer
shows this advisory for expected runtime package changes such as resource reports
and the minimized settle-restraint reference.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Production promotion remains deferred where native qualification failed or plateau criteria remain false. The electrode/PEG evidence and current-state details below retain those limits. Focused development checks are authorized by the task; broad suites and scientific campaigns follow current [repository policy](../CLAUDE.md), superseding the older blanket heavy-test sentence in the retained invariants.

## Zoom Volume inset magnification (2026-11-10)

The +/− pair beside the inset changes its camera magnification in 1.25× steps
(±8 steps from the automatic fit). Controls follow the inset on the side with
more viewport room and hide with it. Magnification persists across rotation,
playback, resizing and representation rebuilds; Clear/document changes reset it.
The main camera and selected volume bounds are unchanged. `main.js` LOC delta: 0.
Validation: frontend 10,256 passed / 1 skipped; inset browser regression and lint
passed. Smoke: 22 passed / 2 skipped / 1 failed in the unrelated Square-lattice
New Part request assertion; isolated rerun also fails (tracked in issues ledger).
Test parts, revision stores, playback scratch, reports and bridge credentials
were cleaned and checked after validation.

## Zoom Volume trajectory synchronization (2026-11-10)

Zoom subscribes to the main design renderer's physical-display updates and applies
the latest frame before drawing its inset. This includes interpolated frames from
the shared NAMD/oxDNA playback path, without a separate clock or per-frame network
requests. Existing Full/bead meshes and crossover connections move in place;
selection bounds follow the selected bases while an assigned box stays fixed.
Stopping the physical display rebuilds the native inset. `main.js` LOC delta: 0.

Atomistic insets copy exact live main-viewport atom coordinates by nucleotide/name
when available; with a coarse main viewport they instead carry reference atoms by
rigid nucleotide poses. Independent surfaces use the existing playback skinning
approximation. The representation tooltip states these distinctions. Reference-axis
cylinders switch to Full during physical display rather than showing static axes.

Real completed Submodel_tests NAMD playback: 163 selected bases matched the main
viewport at 25 sampled smooth updates with zero position difference; scrubbing
and non-smooth playback also passed. The inset and main view were inspected
visually. Evidence and reusable isolated runner:
`.development-artifacts/zoom-trajectory-20261110/`; regression:
`frontend/e2e/zoom_trajectory.spec.js`. No simulation or source-design changes.
Full frontend: 10,208 passed / 1 skipped; focused: 84 passed; isolated smoke:
25 passed. The additional atomistic app check remains unverified: its main-view
NAMD `atomistic-model` analysis worker died without a result before the inset
could be compared. Exact live-atom copying at intermediate positions passes unit
tests; do not claim atomistic end-to-end verification from those tests. Both
failed atomistic attempts are retained in the evidence logs. Temporary job copies
and captures were removed, with original source hashes verified unchanged.

## Show submodel only (2026-11-10)

The checkbox above Define/Edit submodel filters omitted source nucleotides using
prepared NAMD residue identities or oxDNA source indices. Retained shell and
bonded-support nucleotides stay visible even outside the geometric shell; water
and ions retain their independent display controls. It is enabled after preparation
establishes exact membership, never guessed from current deformed positions.
Selection is remembered per job in the current UI session; switching job/engine
or document restores the appropriate mask. No molecular or persisted Hide/Show
state changes. The visibility controller composes the temporary mask with user
visibility, while atomistic instance alpha hides matching atoms and crossing bonds
through representation rebuilds. Membership is invalidated by region edits.

Verified in an isolated app session using completed Submodel_tests NAMD output:
408 retained and 726 omitted nucleotides; Full, VDW and ball-and-stick renderings
hide omitted context, and switching off restores it. Screenshots were visually
inspected; source files remained unchanged and disposable copies were removed.
Evidence: `.development-artifacts/submodel-only-20261110/`. Broad smoke remains
deferred while the user's native NAMD simulation is active.

## Box and Solvent visualization controls (2026-11-10)

Water, Ions and Periodic box live in the Box and Solvent card, above preparation
settings and Define submodel. They retain the existing live Display MD/trajectory
transports: water uses Display MD snapshots, while ions and actual cell outlines
also work in trajectory playback. The actual periodic cell is independent of the
submodel box/shell overlay. Preparation edits respond only to their own inputs;
changing display toggles or submodel controls must not clear saved-job context.
VR mirrors the relocated solvent group without exposing preparation controls.
Verification: 10,200 frontend tests passed (one skipped), and two isolated real-job
browser checks passed with visual inspection for full and submodel snapshots.
Toggles off remove solvent/cell while preserving the submodel shell. Copies and
images removed; source files unchanged. Broad smoke was blocked by the existing
active-NAMD guard, which was not overridden.

## NAMD execution admission and analysis contention (2026-11-10)

`namd_runner.run_job` holds foreground demand through admission and execution,
so disposable trajectory backfill yields as it already does for preparation.
`WorkloadBusy` at workflow reservation is a cancellable wait, not a failed job.
Explicit analysis finishes normally; the reservation rechecks host/GPU capacity
before launching. Actual memory/unsupported-configuration failures still fail
admission. Cancellation releases foreground demand and records a clean user stop.
No reservation records are forcibly removed and no native simulation is needed
for the regression: runner tests use actual scheduling leases plus a real
interruptible analysis subprocess and a stubbed engine. All 20 focused runner
tests passed; FAST 20,703 passed / 90 skipped with the pre-existing CPD packet
contract failure. Aggregate 192 s, no individual timing violators; FULL deferred.
No user job inputs changed and no native dynamics launched.

## Launch estimates and confirmations (2026-11-10)

Duration alone never opens a launch confirmation: relaxation stages can be skip
accelerated. The shared NAMD/oxDNA confirmation now triggers only for predicted
output above 10 GiB, titled “Large output”. RAM/VRAM admission and low-disk checks
remain independent. ETA is still descriptive wherever displayed.

NAMD relaxation captures and saves the selected submodel before either estimator
runs. Sizing uses the preparation crop, including whole residues and bonded
support; solvent, ions and fixed-shell buffers count toward resource budgets.
Cache identity includes box pose and shell width. Submodels quote offload, and
preparation RAM also budgets the full source topology transient. Production
forecasts use the prepared PSF/cell and expose saved-package memory ceilings;
actual production admission is checked again at launch.

Read-only R1 comparison: full 505,099 vs cropped 172,522 solvated atom upper bound,
with cropped RAM 1,705 MiB, VRAM 1,171 MiB and output 1.592 GiB. These are planning
budgets, not measured usage; no dynamics were run for this estimator check.
Verification: five focused backend tests, 10,199 frontend tests, one isolated
Run-button browser check and 25 smoke tests passed. FAST: 20,699 passed /
90 skipped, with the pre-existing CPD packet-contract failure. Aggregate 194 s,
zero individual budget violators; FULL remains deferred. Browser and scratch
artifacts were removed; source unchanged.

## Job wizard identification (2026-11-10)

NAMD and oxDNA wizard headers show `Job ID: <full ID>` for existing jobs,
including editable copies and read-only settings. NAMD seeded-draft setup also
shows its existing ID. Fresh-job dialogs omit the label until an ID exists; a
production parent ID must never be presented as the new job’s own ID. Shared
rendering lives in `frontend/src/ui/job_wizard_identity.js`.

## NAMD submodels (2026-11-10)

Copied relaxation jobs must take `design_source_path` from the source job before
falling back to `prep_params`: older prepared jobs can have a valid job path but
null/stale request metadata. Losing that path lets a background list refresh
switch the active submodel editor to another job and abandon a drag. Preserve
explicitly selected pathless legacy jobs during refresh; document switches still
clear selection. Both job lists recover pathless NAMD records by matching the
active project ID, so existing copies remain accessible after reopening. A
conflicting nonempty path or unknown project never matches this fallback. Regression: `tests/test_md_job_copy.py`, `preferredMdSelection`
unit coverage, and opt-in `frontend/e2e/submodel_edit.spec.js` (real wizard,
copy menu, mouse transforms, shell input, refresh during drag, switch/reopen).

New production requests (including continuations/submodels) default to 1 ps⁻¹;
do not inherit an old parent's custom damping unless explicitly requested anew.
Editing a frozen job's submodel geometry starts a fresh setup, clears selection,
and preserves the old job's box. NAMD creation already saves the box atomically:
the controller adopts the persisted result instead of issuing a second PUT.
Shell input typing must survive unrelated paints until change/commit. Job status
updates refresh the editor's mutability even when selection has not changed.
The central damping pilot completed 2×50 ps at 4 fs for full/fixed/buffer
0.1/1/5 ps⁻¹. Buffer 1 brought RMSF closer to full (0.684 vs 0.712 Å;
fixed 0.605 Å), but pairing remained lower and RMSD drifted. Do not promote an
optimal buffer/default from this short, differently prepared full/crop comparison.
Protocol/results: `experiments/namd_submodel_damping/README.md`.

The 3 nm gradient follow-up uses a shared full-relax DNA checkpoint, solvent-only
crop preparation, smoothstep NAMD k=0→0.5 over 0–2.7 nm, and a fixed outer 0.3 nm
plus cut support. Two 50 ps seeds each for fixed/uniform/gradient completed at
4 fs. Gradient core RMSF 0.697 Å vs full 0.712 Å; pairing 94.76% vs 96.14%; RMSD
still drifts. The user selected uniform k=0.1 kcal/mol/Å² heavy-atom restraints and a 3 nm
default for new jobs. The outer 0.3 nm plus cut-support residues remain fixed.
No width-convergence claim. Metrics include shell-depth/per-residue profiles and
sampled RAM/VRAM. See `experiments/namd_submodel_gradient/README.md`.

Explicit-solvent DNA preparation now crops the CHARMM topology to whole mobile
nucleotides plus a user-sized restrained shell and mandatory bonded support. Native
fixed atoms require NVT and CPU/GPU offload; production retains 4 fs HMR.
Submodel edits invalidate unstarted prepared inputs; production inherits the
frozen region. Source designs remain intact. Short native relax/production trials
passed for duplex and Submodel_tests; managed production and atomistic playback
also passed. These establish execution, not equilibration or shell convergence.
The four completed trial copies are now published in normal workspace jobs,
associated with their source filenames; original evidence remains isolated.
Submodel controls sit at the bottom of the box cards. Use as zoom volume copies
the current inner box and rotation to the existing independent zoom inset; no
shell or molecular document edits are involved.
Submodel controls open on Define/Edit, guidance is a button tooltip, and active
NAMD submodels suppress the solvent-cell overlay in favor of mobile-box dimensions.
Water and ions remain mobile everywhere. Version-2 packages record the uniform
shell recipe; version-1 jobs and descendants keep their legacy fixed shell.
Production shell references use the parent checkpoint, preserving restart velocities.
The managed uniform-shell pilot completed 42 ps relaxation plus 20 ps at 4 fs
HMR; marker audits and browser views passed. Atomistic scalar-map snapshots now
preserve the zero-color fallback, including NAMD T–T propensity maps.
See [implementation and evidence](../docs/simulation_submodel.md#namd-submodels-2026-11-10).

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
