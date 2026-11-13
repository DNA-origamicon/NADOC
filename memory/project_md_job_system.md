---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---

# MD job system

## Alpine late stderr inventory race (2026-11-12)

Gerling WITHOUT_EXTRA_T production created November 5 12:47 MST reached Alpine's
168-hour limit with 62.08/100 ns. All 18 local files match a fresh remote inventory
(79,007,422,950 bytes); the DCD has 1,552 complete frames with no trailing partial
frame and passes sampled structural checks. The initial inventory recorded an
empty Slurm stderr before its 106-byte TIMEOUT message arrived, incorrectly
leaving the transfer interrupted despite playable trajectory data. Retried through
the normal worker fetch: verified, still paused/resumable, no new simulation.
`md_executor` now refreshes remote inventory on a downloaded-size mismatch and
accepts only an exact match to the refreshed remote size. Failed remote checks or
continued mismatches remain interrupted. Existing detached workers require their
next normal restart to load the code; this job was repaired without restarting one.

## Submodel full-reference binding and pose investigation (2026-11-12)

`namd_submodel_reference.py` freezes actual whole-production config + PSF ion
census, and registers per-design bindings in `workspace/submodel_reference_profiles.json`.
24hb_2xT new submodel preparations now bind to `fc12195d0636`: 300 K,
1 ps⁻¹ damping, 4 fs HMR and matching nonbonded/PME settings; neutralizing
Mg(H₂O)₆ only, no added MgCl₂/NaCl. User explicitly chose matching this recipe,
not total Mg concentration. `ion_counts(counterion='mg')` supports zero added
Mg independently of counterion identity; default auto behavior stays unchanged.
Fixed-shell NVT/offload, cell geometry, boundary forces and staged ENM remain
recorded exceptions. Profile stored in submodel receipt survives production
inheritance; legacy unbound submodels cannot start a new comparison production
without fresh ion preparation. Historical settings views use saved receipts.
New-job wizard previews now include their actual region and source design path.

`boundary_pose.py` compares existing observed trajectories only. Late-sample
outer-P medoid: full-model DCD frame 16864 / 168.65 ns. Shell-only endpoint
transplant would create up to 20.17 Å connecting-bond distances; coherent crop
initialization from one full frame is the candidate to investigate next.
Current boundary bond D00P:59 O3′–D00P:60 P is 1.439 Å initially, 2.326 Å in
the pilot final frame, 1.532 Å in the observed medoid. No molecular candidate
was authored/promoted and no new simulation launched. Evidence and plots:
`.development-artifacts/submodel-reference-20261112/pose-02/`; native input audit
matched all 12,373 retained atom types/charges/HMR masses and 24 config templates.

## Offline submodel/full-model metrics (2026-11-12)

`experiments/namd_shell_calibration/comparison.py` provides `recipe` and `run`
commands for reprocessing explicit frames into fresh, hash-audited reports,
per-residue and observable CSVs, and a comparison SVG. It reconstructs actual
stage clocks from config overrides, keeps short-window RMSF separate from
long-window heterogeneity, and globally bounds direct-seek reads to 2 GiB.
Current selection pilot `ddea66693a54` versus whole production `fc12195d0636`:
core-heavy 50 ps RMSF 0.475 Å versus 0.638–0.793 Å across eight late windows;
late mean outer-P pose mismatch 9.649 Å after rigid alignment. Thermostat damping
differs (5 versus 1 ps⁻¹), so short relaxation variance cannot identify spring
corrections. Prioritize a representative relaxed boundary/start-pose experiment,
then damping-matched longer sampling. No native coefficients or molecular poses
changed. Detailed methodology and caveats are in the experiment README; evidence
is under `.development-artifacts/submodel-comparison-20261112/`.

## Fractional-charge selection submodels (2026-11-12)

Job `b7e7cf6ab7f1` failed before rental: its whole-residue crop retained three
5TER and two 3TER residues, giving −386.47 e although the full PSF is integer
charged. `namd_submodel_charge.py` now records a hash-bound charge policy after
validating the full source. Counterions use the cropped PSF charge rounded to
the nearest integer; dry/final audits enforce the recorded charge and residual.
DNA parameters remain unchanged. This is an explicit approximate periodic-PME
boundary for screening, not exact neutrality; whole-model audits remain strict.
The final manifest carries the residual instead of claiming required neutrality.
See `docs/simulation_submodel.md` and the charge regression tests.

RunPod pilot `ddea66693a54` preserves the exact failed-job snapshot and box
(2 nm shell, 6 nm solvent padding): 38 core nucleotides / 1,212 core atoms,
12,373 retained DNA atoms, 846,428 total atoms. All four targeted extra Ts are
mobile. Explicit stage overrides produced 4,800 minimization steps plus 205 ps
of dynamics, including the final 50 ps at 4 fs without DNA ENM restraints.
All 22 native logs have finite energies and normal exits; all checkpoints pass
fixed-boundary displacement (<1e-5 Å), and final core positional-restraint weights
are zero while heavy-shell weights remain 0.1. All 201 output files (4.12 GB)
were downloaded and verified. This validates execution, not equilibration or a
calibrated shell. Total campaign GPU spend $0.53844, both pods confirmed absent.
The first pilot `1af0b54ca8a9` was deliberately stopped when automatic atom-count
scaling expanded minimization to 84,660 steps; the retry records a `minimize`
stage override. Standard minimization sizing was not changed. No local NAMD jobs
were started. Backend FAST: 20,808 passed / 90 skipped; FULL deferred without a
full-suite session; focused charge/submodel/RunPod/gradient tests and lint passed.
Evidence: `.development-artifacts/selection-submodel-runpod-20261112/`.

## Selection-derived submodel volume (2026-11-12)

Both NAMD and oxDNA now show **Define submodel from selection** below Define/Edit
submodel, using shared `btn btn--sm` controls. `scene/submodel_selection.js`
resolves canonical DNA selections (including extra crossover bases) and assembly
instances/groups/clusters into a world-space AABB with 1 nm padding. The existing
shell setting, editor, persistence and immutable-job/new-draft behavior are reused.
This captures a box once; persistent base-identity simulation membership remains
future work. Selected bounds include other DNA lying inside the box.

Verification: 34 focused tests; frontend 10,419 passed / one skipped; isolated
browser exercise of both engines passed, with visual confirmation of matching
32 px button heights and 14 px text. Lint passed. Smoke refused by the active
native-simulation guard; no override and no NAMD jobs launched. Source design
hash unchanged, scratch/captures/bridge credentials cleaned. `main.js` LOC delta: 0.
Evidence: `.development-artifacts/submodel-from-selection-20261112/`.

## Offline shell calibration (2026-11-12)

`experiments/namd_shell_calibration/` prepares verified mappings, bounded DCD
profiles and unvalidated scalar parameter proposals for control `85c3dc72dc59`
versus full 24hb_2xT production `fc12195d0636`. The saved 2 nm box contains a
reciprocal crossover pair/four extra Ts. Read its README before follow-up work:
outer-shell preparation/reference shape mismatch and ionic recipe differences
preclude claiming a calibrated boundary. Native candidate installation is not
implemented. No jobs launched or modified; the user prohibits local NAMD starts
in this task. Eleven small software tests pass; broad suites deferred while
local production runs. Evidence: `.development-artifacts/namd-shell-calibration-20261112/`.

User clarification: submodels are intended for inexpensive candidate screening,
including deliberate changes in local ionic conditions using an approximate
reference boundary. Do not require matched-salt whole-model simulations for
every candidate or treat imperfect ensemble fidelity as a blocker. Distinguish
transfer limitations from actual implementation failures. Shape follow-up finds
initial full/control agreement at 0.063 Å outer-P RMSD, increasing to 6.181 Å
at the full equilibrated checkpoint and 9.668 Å for the late mean: the large
mismatch developed through whole-model relaxation, not initial registration.

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

## Transfer fields and Alpine submission review (2026-11-11)

Tab 1 transfer-rate inputs now use standard dark numeric controls with visible
values and valid 0.1 Mbps increments. The Alpine submission review shows ETA,
allocation cost (SU) and estimated speed by default. Its collapsed Settings section
retains partition/resource edits and re-sizing; estimate assumptions, hardware,
walltime and successful clearance checks are in the question-mark tooltip.
Clearance decisions requiring acknowledgment and submission errors remain visible.
The review has dialog semantics so number shortcuts stay blocked while it is open.
10,308 frontend tests passed / 1 skipped; 36 focused tests passed; live UI check passed; 25 smoke checks passed; lint and diff checks passed.
Source unchanged, scratch cleanup verified, no jobs submitted. `main.js` LOC delta: 0.
Evidence: `.development-artifacts/submit-review-20261111/` (ISSUE-183).

## Job-wizard temperature controls (2026-11-10)

Temperature now lives in the NAMD and oxDNA wizard settings panels (tab 2 for
new relaxation jobs; production uses its existing run-settings panel), with a
Kelvin input and Celsius equivalent. The Box and Solvent sidebar no longer owns
or overrides temperature. Existing defaults remain unchanged until edited.

The shared `frontend/src/ui/job_temperature.js` uses the existing persisted stage
override paths. NAMD edits target-temperature thermostat/barostat/initialization
values while retaining colder preparation stages and read-only reseed stages.
Surface-only/two-electrode preparation retains its native
`graphene_temperature_K` request path so bulk reference inputs also receive the
chosen temperature; stale thermal overrides are cleared on this edit. oxDNA
updates all applicable job stages, including production. Stage tables remain
individually editable and show the effective temperatures.

Verified 293.15 K (20 °C) in both live wizard flows, with no job creation or
simulation. Frontend suite: 10,265 passed / 1 skipped; final focused checks:
86 passed. Isolated smoke: 25 passed; lint passed. Source designs unchanged;
temporary workspaces, project revisions, caches, reports and bridge credentials
were removed and verified. Evidence and cleanup verification:
`.development-artifacts/job-temperature-20261110/`. `main.js` LOC delta: 0.

## Wizard keyboard entry (2026-11-10)

The global shortcut registry blocks number commands while dialogs/popovers are
open or a form/contenteditable field has focus, including retargeted events.
The NAMD temperature control remains attached during asynchronous plan refreshes,
so a pending response does not replace the input or erase an unfinished edit.
A regression reproduced that failure before the fix. Default relaxation temperature
remains 300 K, confirmed against the Aksimentiev tutorial's step3 NAMD files
([source](https://bionano.physics.illinois.edu/node/277)); 293.15 K remains an editable
experimental choice. Direct live typing of 293.15 K and popup shortcut blocking
passed, with no job creation. 10,272 frontend tests passed / 1 skipped; 115 focused checks passed; live typing/popup checks passed; 25 smoke checks passed; lint and diff checks passed.
Source hash unchanged and scratch cleanup verified. `main.js` LOC delta: 0.
Evidence: `.development-artifacts/wizard-keyboard-20261110/`.

## Wizard numeric defaults (2026-11-10)

NAMD and oxDNA numeric settings use standard input styling, including temperature;
Kelvin values and Celsius equivalents are readable in tab 2. Stage-cell editors
start with their current value, and unchanged edits do not create overrides.
Numeric step increments align with the allowed minima and displayed precision.
The NAMD integrator pin now reads the selected preset before the first plan:
untouched literature uses 2 fs and ordinary hydrogen masses, while explicit user
choices remain authoritative. Previously the global fast default pinned 4 fs/HMR
before the backend could apply the preset.

Direct app checks covered all six available NAMD presets and oxDNA settings,
including native numeric validity, populated values, literature plan payloads,
and stage-editor values. Literature and oxDNA were also visually inspected.
No jobs were created; the source design hash and scratch cleanup were verified.
Frontend: 10,267 passed / 1 skipped; final focused: 260 passed; direct app audit: passed; smoke: 25 passed; lint and diff checks passed.
Evidence: `.development-artifacts/wizard-numbers-20261110/` (ISSUE-181).

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Production promotion remains deferred where native qualification failed or plateau criteria remain false. The electrode/PEG evidence and current-state details below retain those limits. Focused development checks are authorized by the task; broad suites and scientific campaigns follow current [repository policy](../CLAUDE.md), superseding the older blanket heavy-test sentence in the retained invariants.

## Zoom Volume inset magnification (2026-11-10)

Each entry in the Zoom Volumes list has a +/− pair beside its inset that changes
only that camera’s magnification in 1.25× steps
(±8 steps from the automatic fit). Controls follow the inset on the side with
more viewport room and hide with it. Magnification persists across rotation,
playback, resizing and representation rebuilds; Clear/document changes reset it.
The main camera and selected volume bounds are unchanged. `main.js` LOC delta: 0.
List integration after pull `84227195`: 10,261 frontend tests passed / one skipped;
15 focused checks and the multiple-inset browser regression passed. Lint passed.
Smoke repeated the pre-pull assembly readiness and Close Session progress failures
(21 passed / two skipped / two failed). Test artifacts were cleaned and checked.
Evidence: `.development-artifacts/zoom-volume-pull/validation.json`.

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
the current inner box and rotation to a dedicated entry in the zoom-volume list;
repeated assignments update that entry and preserve the other entries. No
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
