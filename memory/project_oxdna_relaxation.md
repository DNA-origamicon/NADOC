---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---
# oxDNA relaxation and display

Canonical current state for local oxDNA relaxation, health gates, display, surfaces, and
CG-to-atomistic handoff. Historical phases and experiments are in
[the archive](project_oxdna_relaxation_archive.md).

## Current state

- Torque job selection restores the saved card settings for running and finished
  jobs as well as queued jobs. Non-editable jobs keep the values visible with
  disabled simulation controls. The saved axis arrow remains visible and its size
  slider stays active as a per-job session display preference; completed-job size
  changes never write simulation settings. Axis manipulation remains limited to editable jobs.
  Driven sites reuse the anchor scope picker and halo renderer with cyan instead
  of purple. Highlight-all defaults on; row focus and empty-space reset remain
  display-only and usable on finished jobs. The independent layer follows geometry
  rebuilds and playback. Empty drive sets highlight all unanchored particles.
  Real-app evidence: `.development-artifacts/torque-driven-glow/` (completed job
  and a queued managed copy, deleted after validation).

- Hybrid research closed out (2026-11-21): experimental prototype only, no
  production Tm feature or precision certification. User-authorized cleanup
  removed `.development-artifacts/oxdna-hybrid/` (554,338,810 logical bytes).
  Retained notes/metrics: `docs/benchmarks/oxdna_hybrid/`; status and next-session
  prompt: `docs/oxdna_equilibrium_tm_research.md`. References below to raw hybrid
  artifacts are historical and no longer resolvable. Local prototype source is
  retained uncommitted; native candidates must be rebuilt and revalidated.

- Hybrid longer-training follow-up (2026-11-21): see
  `docs/oxdna_hybrid_training_benchmark.md`. Same v3 engine, four walkers,
  2M production; training 2M/6M/12M gives 1/5/4 q=0↔q>=6 passages in
  4.11/7.95/13.73min. Last-500k bias drift improves 0.623/0.267/0.129 kBT RMS,
  but initial-state gaps remain 0.994/0.227/0.681; no q=0↔q=8 round trips or
  bracketed Tm. Both new campaigns completed; no reliable +/-1 C claim or
  application/default changes. Evidence: `.development-artifacts/oxdna-hybrid/training-duration-20261121/`.

- Hybrid metadynamics/frozen-bias research CLI (2026-11-20):
  `tools/oxdna_hybrid/`, report `docs/oxdna_hybrid_benchmark.md`, evidence
  `.development-artifacts/oxdna-hybrid/`. No wizard/job integration or CPD
  promotion; existing engine symlink and managed jobs unchanged. Persistent oxpy
  GPU walkers learn a shared well-tempered bias, then fresh bound/unbound starts
  run fixed equilibration/production with a hashed frozen bias. Exact native
  temperature-energy reevaluation, concentration correction, autocorrelation,
  state-disagreement checks, raw energies/trajectories and ordered hill replay.
  Isolated native patches repair coordination GPU base-site derivatives/grid
  bounds, radial cutoff smoothing, base-site PBC, and stale CPU step-keyed CV
  caching. Nonlinear force/torque and CPU/CUDA checks pass on final candidate.
  Six 8-bp GPU campaigns, 100.8M MD steps total, ~23min sampling: initial mixed
  coordinate increased q=0/1 crossings to84, but produced0 q=0↔q>=6 passages;
  final-engine narrow/broad trials produced1/0 such passages. All retain severe
  starting-state dependence. No replica Tm bracket in60–80C for evaluated mixed
  trials, no +/-1C claim. Broader contact radius did not help this short pilot.
  Native bias energies avoid four-decimal COM-coordinate rounding errors.
  These are inconclusive sampling pilots, not evidence metadynamics generally
  fails or that additional independent replicas alone would solve the problem.

- Sampling/variability follow-up (2026-11-20): continued the four VMMC replicas
  with unchanged conditions/weights for23.72min, +10M sweeps/replica. Total
  warm-start active time55.10min, production110M (27.5M/replica), all16 new blocks
  passed. Replica Tm70.76/66.68/73.37/71.21C; provisional replica95% half-width
  **±4.45C**, versus±3.87C at17.5M. Long-batch bootstrap remains unresolved;
  transitions24/30/16/18, longest category dwell10.94M. Across correlated prefixes,
  descriptive slope−0.10, recent slope+1.02: no reliable inverse-square convergence
  forecast. Conditional ±1C per-design planning envelope94–543M sweeps/replica,
  ~3–18h/four workers; NOT an approved budget or confidence-bound forecast.
  Original job remains stopped, no benchmark children left. Tools now support
  checked continuation (`--continue-campaign`, identical frozen weights, new seed),
  `sampling_trend`, and native `binding_states` audit. 7,000 original frames matched
  native q exactly; only22/923 q=0 frames had any non-native interstrand HB, so
  widespread off-register binding does not explain q=0 sampling. Frame counts are
  biased, not equilibrium populations. Plots/data in
  `.development-artifacts/vmmc-sampling-trend-extended/`; source native outputs in
  `vmmc-sampling-extension/`, pairing audit in `vmmc-pairing-audit/`. Original warm
  campaign is a retained dependency. Focused5 passed; tools lint/diff passed.

- Bounded VMMC precision benchmark completed (user follow-up 2026-11-20).
  `c795362c46bc` is now **stopped**, not running: API cancellation was explicitly
  authorized when remaining time exceeded one hour (~29h current replica/~190h
  series). Original scientific outputs preserved. Research CLI
  `tools.oxdna_vmmc.benchmark` runs four independent CPU replicas with opposite
  starts, fixed blocks, exact native histogram output and a wall cap; precision
  analysis is `backend/core/oxdna_vmmc_precision.py`. Existing wizard protocols
  are unchanged. Fresh short tuning failed; a warm start with flat-occupancy
  weights learned from the old 569M-sweep histogram produced 70M new production
  sweeps in31.37min; all attempts together48.74min. No old production samples
  were pooled into this estimate. Replica Tm:69.43,67.36,73.17,70.74C; mean70.18C,
  diagnostic Student-t95%66.30–74.05C (±3.87C), pooled69.84C. Only22/18/10/14
  recorded transitions and insufficient long bootstrap batches: **inconclusive**,
  ±0.7C per-design/roughly±1C difference target not reached. Do not claim a
  validated sub-hour ±1C method or CPD support. All native benchmark processes
  ended; ~67MB useful evidence retained under `.development-artifacts/vmmc-precision-hour*`.
  `train_weights` and `report_benchmark` reproduce bias preparation and exports.
  FAST20994 passed/90 skipped, focused5 passed, lint passed; FULL deferred.
- Smooth EM integration (2026-11-25): the display exposes its actual interpolation
  endpoints, fraction and coordinates to EM. A detachable field-readiness hook
  participates in saved-frame and interpolation preparation and invalidates the
  player's preparation key. With EM attached, smooth segments last 500 ms; other
  playback retains its existing rate. The shared oxDNA/NAMD player holds saved
  endpoints until the next calculated field pair is ready, without catch-up.

- EM scope (2026-11-24): trajectory readiness means playable, not all coordinate
  pages resident. EM confirmation uses the stable selected trajectory length;
  its reader ensures missing pages without changing the displayed frame or
  reconstructing DNA meshes. Only optical particle inputs accumulate. The
  100-frame sparse-loader test verifies reading frame 50 leaves display at zero
  and issues no extra atomistic reconstruction. Scope/stride remain respected.

- Trajectory load reuse (2026-11-24): streamed first-frame preparation now warms
  the bounded heavy-frame cache once, paints CG without a second heavy launch,
  then applies the cached exact frame. Playback preparation reuses it. Interactive
  previews copy resident six-value or nine-value oxDNA frames into their existing
  six-value preview layout and request only missing samples; owned copies do not
  retain coordinate pages. Twelve-value NAMD layouts retain the existing fallback.
  Focused coverage: 193 frontend tests; initial-frame request counts, loop-boundary
  reuse, both coordinate layouts, memory ownership and missing-page behavior.
  The real-backend EM/trajectory browser flow passes with current nine-value
  pages and asserts zero extra preview-download requests for its loaded frames.
  This removes duplicate work; no hardware-independent load-time claim is made.

- Plasmonic mobile-gold startup (2026-11-22): direct CUDA MD from the CAD seed
  diverged on both `Plasmonic_test` and the existing two-attached-particle part.
  The MC replacement now uses a 10k-step overdamped startup (dt 1e-5,
  diffusion 1e-4); subsequent MD retains diffusion 2.5 and dt ≤ .002.
  Model configuration preserves explicit diffusion on repeated calls. Consecutive
  MD relaxation stages defer the FENE handoff gate until the last stage; retries
  target the latest relaxation and cannot increase an already smaller timestep.
  Managed job `3171c01b5e56` on `Plasmonic_two_NPs_attached.nadoc` completed
  1M relaxation steps with 96.58% geometric pair retention, maximum FENE distance
  .935713 units and no retries. The 100k unrestrained equilibration also passed.
  Its 5M-step uncapped production was launched and checked at 150k steps:
  96.47% geometric pair retention, all four attachment duplexes 10/10 paired,
  zero over-limit backbone bonds and positive DNA/core clearance. Production was
  still running at handoff; this is not a completed-production/convergence claim.
  Focused validation: 14 passed / 1 skipped across three commands.
  Evidence: `.development-artifacts/plasmonic-oxdna/validation.json`.
  Existing source geometry/history is unchanged. A fresh complete document audit
  timed out at its unchanged 180-second limit; no new part was published.

- New thermal ramps default to native-HB melt termination at 100% unpaired DNA bases: complete the current fixed dwell, then skip later temperatures after any sampled crossing. Saved legacy ramps remain unchanged; evidence and pruning persist across restart. See `oxdna_melt_stop.py`.

- Thermal ramps default to 100,000,000 fixed steps per temperature (2026-11-18); explicit values and saved jobs retain their recorded steps.

- DNA concentration (2026-11-18): wizard temperature/salt section accepts µM
  total DNA strands (not nucleotides or complexes). Explicit values resize only
  the configuration box; blank retains auto/inherited sizing. Actual exported
  strand count and volume persist as `box_conditions`; copies/ramps preserve
  the box. Geometry-fit/boundary checks reject unsafe resizing without scaling
  coordinates. See `docs/oxdna_setup.md` for convention and literature links.

- Manual thermal skip (2026-11-17, ISSUE-210): parent and child context menus
  target the current plateau, with expected-stage guard. Detached controller stops
  the old owner, validates/recovers its checkpoint, persists `skipped`, then
  transfers the idle lease to a fresh worker generation. Never inherits the old
  stop signal or skips a newly advanced temperature. Later Stop cancels pending
  skip. Raw samples and prior gate decisions remain; final temperature disabled.
  Local running/stopped/failed ramps only. No actual user stage skipped for testing.

- Energy metrics card (2026-11-17): Potential energy Generate/Display/Export reads
  full production/field energy histories without loading geometry. Live snapshots
  refresh on Generate. PNG and display annotate thermostat setpoints at stage
  boundaries; CSV preserves per-sample temperature/stage/job identity. Separate
  oxDNA-unit metadata prevents NAMD kcal/mol labels leaking into oxDNA plots.
  `oxdna_energy_series.py` owns read-only assembly; shared graph/card own rendering.

- Fixed-duration ramps (2026-11-17, ISSUE-211) supersede the earlier adaptive
  behavior. Subsequent literature preset (ISSUE-237) sets new ramps to 2B steps,
  sequence-dependent DNA2, Brownian/100 steps, dt .005, diffusion 2.5; salt inherits the continued stage (ISSUE-242).
  uniform physics edits are available in the wizard. Legacy specs stay unchanged.
  Wizard exposes
  only start/end/increment and Steps per temperature. No gating, automatic
  extension, exponential fitting or stationarity pass is used during execution
  or manual skip. Complete energies and descriptive statistics are saved;
  protocol v4 reports `not_assessed`. Legacy adaptive fields are accepted for
  reading but omitted on new serialization and cannot enable gating. Retired
  extension requests reject without changing a plan. Existing workers and saved
  durations are not silently restarted/resized. Historical fits remain available
  through the explicit offline analysis script only.

- Historical fixed-dwell reporting (ISSUE-207, superseded by v4): computed
  stability; `gate_enabled: false` advances after numerical health checks even
  when `stability_status` is `not_demonstrated`. Never substitute a fake stability
  pass for gate-off mode. Real cis-anti GPU job 60694a597e17 completed 13 × 5M-step
  plateaus, 25–85°C, with zero numerical retries. Only 60°C passed its energy
  diagnostic; 83% endpoint pair retention at 85°C means no observed bulk melt.
  Event-driven stage/failure/stall monitor: `scripts/watch_oxdna_ramp.py`.
  Evidence: `.development-artifacts/cpd-melt-ramp-20261117/fixed-dwell/`.

- CPD CUDA execution (2026-11-16, ISSUE-206): custom DNA2 CUDA kernels preserve
  the fitted CPD springs, retain adjacent backbone FENE, replace reacted-pair
  interactions, and evaluate nonadjacent welds independently of neighbor lists.
  Stable-ID mapping survives sorting; edge strand-end charges refresh after sorting.
  MC remains CPU; MD/production/thermal plateaus retain selected CUDA. Frozen
  packages carry separately checked CUDA plugin/build hashes. Legacy CPU parents
  can seed GPU production; idle CPD jobs can change remaining stages through
  `/cpd-backend` with checkpoint/gate preservation and recorded old specifications.
  The wizard exposes production backend selection. See `docs/oxdna_cpd.md`.

- Historical thermal gate recovery (ISSUE-205, superseded by v4): fixed-tail checks previously
  discarded accumulated evidence on every extension. Version 2 grows trailing
  windows with completed blocks (bounded at 1,000 samples/window), preserving
  drift/mean/ESS thresholds and resetting old-version pass streaks. Explicit
  `POST /start` body `thermal_max_steps` extends only an exhausted gate, records
  the prior verdict/cap and resumes the next block without resetting outputs.

- Thermal ramps (2026-11-16): Production wizard toggle and copied-job editor;
  local full-system heating/cooling with a fixed step count per temperature.
  Runner resumes checkpoints; copies/retries reset evidence and
  reconciliation retains numerical health checks. `backend/core/oxdna_thermal_ramp.py` owns
  schedule/decisions; per-attempt seeds prevent repeated noise across blocks.
  Native CPD gated heating and fixed-dwell cooling completed. See [workflow and limitations](../docs/oxdna_setup.md#temperature-ramps-and-fixed-stage-duration).
  Stability is not thermodynamic equilibration; CPD Tm ranking remains unvalidated.
  Job lists label ramps `Tm Run N` (production numbering per design). The shared
  `oxdna_thermal_job` model/renderer expands real temperature stages with live
  completed/running/queued and interruption states; expansion survives polling.
  ISSUE-204 fixes dropped thermal settings at wizard submission. Selectable
  `25C - Run N` children use `thermal:<stage>` scope; the parent uses `thermal`
  scope, excluding ancestors. All metadata, preview and streamed-frame requests
  share that selection. Previously created ordinary jobs need editing/recreation.
  Playback markers carry recorded target temperatures and inclusive displayed-frame
  ranges in both oxDNA and animation scrubbers. `oxdna_temperature_markers.py`
  reads executed inputs; resumed attempts preserve `input.rN.txt`. Unknown legacy
  archives and the design seed remain unlabeled. Metadata and sampled payload
  boundaries are tested together; tooltips support hover and keyboard focus.

- Fixed-shell production startup (2026-11-10): job 52d968f5e2cc inherited an
  immutable 1.037145-unit bond (native 129–130, source 720–721) from capped relax;
  uncapped FENE rejected it. Installer v2 adds SubmodelDNA2: omit fixed–fixed
  backbone-spring energy only, preserving topology and every mobile-involving
  force/validation. MD/MC/DNAnalysis use the same plugin. Exact user input now
  completes a managed 10k-step check (50% mobile pair retention); negative control
  with endpoint mobile still fails. MD/MC particle rows exactly unchanged in
  matched controls. Error-log API reports the actual adapter, with pre-launch
  binary/plugin receipts. Original failed job is available for user retry; no
  five-million-step rerun was launched. Validation: 13 focused passed; FAST
  20,673 passed/90 skipped, one pre-existing CPD failure; FULL deferred.
  Evidence: docs/simulation_submodel.md and
  .development-artifacts/oxdna-submodel-fixed-bond-20261110/.

- Managed CPU submodels (2026-11-10): normal Run now crops native inputs, freezes
  shell particles and projects frames into full source order for visualization.
  Production inherits the frozen mask; existing full relaxations can seed cropped
  children. Local DNA2 + Brownian MD only; adapter installer:
  `uv run python -m scripts.build_oxdna_submodel`. See docs/simulation_submodel.md.
  Matched 3×20k-step benchmark: 182/1134 particles, 6.94× speedup versus fully
  mobile full model, 10× versus same-mask full model, ~21% less native RSS.
  Box card reports counts, reference CPU MD ETA, conservative host budget and
  zero simulation VRAM; display/context memory remains source-sized.
  Browser: all seven visualization modes active; native stop/resume preserves
  velocities and mask (2k + 198k steps). Final frontend 10,185 passed; focused
  backend 282 passed. FAST has two unrelated part-transform failures after the
  submodel fixture correction; FULL deferred. Original source/job hashes intact.
  Current managed planner uses actual displayed backbone sites (104 mobile/182 retained
  on specimen; pilot benchmark mask was 102). Earlier bullets below are historical.


- Submodel_tests verification (2026-11-10 UTC): source job 093c7b60f98e,
  saved 2 nm shell selects 102 mobile + 80 fixed / 1,134 source nts.
  Shared btn/btn--sm styling now used for Define/Edit submodel and Retry save.
  Isolated cropped native runs complete, but pairing is not preserved:
  downhill→100k MD: 18→2 mobile-touching pairs; 1M restrained MD ends at 7,
  then 100k unrestrained (backbone-capped) MD ends at 6. Fixed poses/momenta
  remain unchanged. At that earlier pilot stage Run ignored submodels; full-order display
  readers reject 182-particle topology against 1,134 source nts. All visual
  controls exist, but cropped jobs need managed execution and index mapping
  before claiming display/trajectory/RMSF/strain/occupancy support.
  Evidence: .development-artifacts/oxdna-submodel-specimen-20261110/.

- Submodel fixed-shell UI (2026-11-09): both engines persist radius, default 3 nm;
  oxDNA has Show box and shell; NAMD uses box/solvent visibility. Before managed integration Run did not apply submodels. Experimental export-only cropping removes particles
  outside the shell, retaining direct mobile backbone neighbours at radius zero.
  Existing-relaxation duplex pilot: 0 nm = 32 particles / 4 fixed, ~3.1× faster;
  3 nm = 69 / 41 fixed, smallest tested radius matching full-model mobile forces
  and torques at six-significant-digit precision across 11 poses. Two 100k-step
  runs/radius; not general shell convergence. See docs/simulation_submodel.md and
  .development-artifacts/oxdna-submodel-shell-20261109/summary.json.

- Live oxDNA has an upper-left Smooth checkbox (off by default). Four queued
  snapshots fill/refill a jitter buffer; one future knot remains reserved for the
  same Catmull–Rom interpolation as trajectories. The queue caps at eight frames
  and coalesces overflow while preserving upcoming knots. Arrival cadence is
  low-pass filtered; polling runs start-to-start without overlapping requests.
  Packed snapshots are reused and the next curve is prepared on receipt rather
  than at a renderer boundary. Live display ownership cleanup runs once on entry.
  The popup's Timing details distinguish request, simulation burst, capture,
  source age, curve preparation, scene update, render gaps and buffer stalls.
  Frame IDs, burst counts and coordinates are published atomically (ISSUE-179),
  preventing a reader from labeling old positions as a new frame. Live holds the
  existing foreground-work lease so resumable background trajectory-cache work
  yields until Live ends. Stop cancels
  interpolation and rejects responses from older sessions. This remains a CG
  display preview; no topology or stored trajectory is changed.

- Copy Job retains the job-owned sequence-parameter file byte-for-byte (ISSUE-95).
  Missing legacy files remain absent; this is not complete physical provenance.

- The local upstream physics-v3 builder adapts thermostat rigidity masks to upstream's
  packed particle IDs (2026-10-02); adaptive-memory builds retain their explicit ID buffer.
  The managed CUDA engine and project oxpy were rebuilt. Native John/Langevin checks
  preserve point-versus-rigid identity through sorting; lifecycle, fixed-gold force-response
  and live-steering checks pass. This is software validation, not convergence qualification.
- Managed jobs persist their topology, initial configuration, design snapshot, stage plan,
  progress, health, and final display state.
- Relaxation uses staged minimization/MD with base-pair retention, backbone stretch, and energy
  convergence checks. Headless production defaults must be scientifically scaled, not mock-sized.
- Absolute-coordinate forces such as surfaces and anchors require `fix_diffusion = false`.
- The NAMD seed is a pure function of oxDNA coordinates and orientation; design transforms must not
  be applied a second time. Unpaired ssDNA is rigid-stamped during backmapping. Synthetic crossover
  inserts must be read with `include_extra_bases=True` and flow through the same
  `_frame_atomistic_overrides` used by the atomistic display, so their simulated CM/a1/a3 pose
  replaces the native placement. The seed's final global recenter preserves relative coordinates.
- Atomistic display uses vectorized stamping and compact binary transport. Fine molecular surfaces
  are generated per strand to preserve geometric separation rather than only coloring one fused mesh.
- The three-tab job wizard has a pure validation oracle and a reusable Playwright driver. Regression
  coverage traverses every engine variant plus Local, Alpine, and RunPod UI paths using a disposable
  two-helix design. Local prepared-job creation is wired; Alpine and RunPod selection/preview are wired,
  but remote creation is still deliberately blocked by the frontend launch boundary.
- Alpine adaptive-memory oxDNA was built and compute-node verified on 2026-08-27 (SLURM
  `31744722`, CUDA architectures 80/90). Remote submission should use
  `/projects/jojo6687/nadoc_jobs/nadoc_builds/oxdna-adaptive/install/bin/oxDNA` and set
  `LD_LIBRARY_PATH=/projects/jojo6687/nadoc_jobs/nadoc_builds/oxdna-adaptive/install/lib`.
  `DNAnalysis` is installed beside `oxDNA`; both binaries were verified against the bundled GCC
  runtime on an Alpine `acpu` compute node.
- RunPod validation on 2026-08-27 established both capability and correctness for the adaptive
  CUDA lists. Upstream allocated 140,997.86 MB and completed no step in 373 seconds for the
  451,584-nt nonuniform BigO assembly, while adaptive initialized at about 219 MB and ran at
  2.56054 ms/step. On a 597-nt control that forced capacity growth from 8 to 110, one-step
  energies/positions/orientations matched upstream exactly and velocity differences were at
  mixed-precision scale (maximum `2.98e-8`). Both completed a deterministic 10,000-step smoke
  test with about 1.7% adaptive overhead. The isolated validation spent $1.14834 of a $2 cap.

## Binding invariants

- Relaxed physical coordinates are display/simulation state and never write back to topology.
- Preserve the frozen job design for every downstream map, metric, export, and child job.
- Inserted/extra nucleotides need a disambiguating copy/index convention; a bare
  `(helix, bp, direction)` key is insufficient.
- Surface and field coordinates are absolute; do not enable diffusion removal for those runs.
- CUDA availability and WSL driver/toolkit problems are environment findings, not reasons to alter
  the scientific protocol silently.

## Open work

- The high-quality surface path is shipped; further ChimeraX matching would require a deliberate
  solvent-excluded/Connolly or adaptive-mesh project, not another coarse-bead tuning pass.
- Verify any remaining live/headless default disparity before using relaxation quantitatively.
- Keep oxDNA and NAMD child-package artifact propagation in parity.

## Verification

Use fast unit/integration tests for protocol rendering, health, mapping, and binary formats. Exercise
display changes in the running app. Run the wizard path regression with
`cd frontend && npx playwright test e2e/oxdna_job_wizard_paths.spec.js --reporter=list`; it intercepts
job creation and paid-provider calls and removes its generated design. Real oxDNA simulation tests are
heavy and test-session-only.

## Shared surface / PEG handoff update (2026-09-11)

Hard-wall and PEG setup, run and Live writers accept explicit `plane_point_nm`
and `tangent_u` descriptors through `physics/oxdna_surface_geometry.py`; oblique
planes no longer use a dominant-axis position approximation. Offset-only deposition
walls are frozen before moving the probe. Shared rigid transforms retain surface,
pore, graft and coating registration through seed recentering and graphene clearance.

`POST /api/oxdna/peg/namd-seed` is a read-only checkpoint inventory with explicit
DNA/PEG identities, graft references, source hashes and periodic make-whole handling.
Normal NAMD seeding rejects PEG until its target chemistry, mapping and assets are
provided; it must not silently yield DNA-only input. The unwrapped configuration
reader now accepts `n_trailing_extra` to keep DNA indexing correct. Rotated
orthorhombic graphene cells have an explicit geometry adapter; stock solvated-job
creation does not silently rotate a user's existing cell or external fields.
Implementation and remaining scientific/test-session prerequisites are tracked in
[shared surface transforms](../docs/surface_transforms.md).

## Submodel selection UI (2026-11-09)

oxDNA Box and NAMD Box and solvent now offer a job-owned oriented region through
the shared View Volumes editor. Draft selections transfer on normal relaxation /
production creation; later edits persist in `submodel_selection.json` alongside
the job. This is selection-only: Run does not yet apply a mobile/frozen partition.
Native boundary/production experiments are recorded below and in
[simulation_submodel](../docs/simulation_submodel.md); ordinary Run remains whole-model.

### 2026-11-09 — native submodel pilot

User authorized testing central 14 bp of existing `duplex.nadoc`. Reusable isolated
pilot: `experiments/oxdna_submodel/{prepare,build_plugins,run,analyze,check_visual}.py`;
results and reproduction in `docs/simulation_submodel.md`. Headless actual job-sidecar
PUT/GET and real-app box restore/raycast verified. CPU MC2 plugins restrict both
translation and rotation IDs while retaining complete duplex interactions; no engine
installation changes. Downhill-only relaxation preserved 42/42 pairs, mobile RMS
0.1429 nm, exact zero fixed position/orientation drift. Thermal MC retained only 4/14
mobile pairs, so sampling remains unresolved. Ordinary Run remains whole-model.
Old document receipts needed schema-default compatibility (folding_order=None): raw
receipt hashes plus independently replayed structural equality, never snapshot authoring.
The thermal continuation after downhill relaxation retained 8/14 mobile pairs rather
than 4/14 from the seed; still inadequate and not a convergence result. Native evidence
is under `.development-artifacts/oxdna-submodel-duplex-20261109/`. Phase validation:
20,650 FAST tests passed, 90 skipped, existing CPD display-contract failure persisted;
FULL deferred. Browser check and lint passed; no per-test timing violators.

### 2026-11-09 — submodel MD production

Two 1,000,000-step CPU MD continuations completed: local downhill endpoint and
existing duplex job c49058f52282/3_equil. Actual parent now has a persisted oriented
box selecting bp 14–27 in aligned relaxed display coordinates. Its 41 earlier files
are byte-identical. Isolated executable masks both Verlet half-steps and supplies only
28 mobile particles to Brownian thermostat; all 56 fixed poses and momenta remain
exactly invariant. All-mobile control reproduces stock engine exactly with matched
compiler flags. Existing full-relaxation start retained 13–14/14 mobile pairs (final14,
RMS displacement0.185nm); local-start transiently dropped to3 then recovered14 (final
RMS0.638nm). Single-seed exploratory results, not convergence. Outputs/source linkage:
.development-artifacts/oxdna-submodel-production-20261109/. Scripts: build_md.py,
production.py, analyze_md.py under experiments/oxdna_submodel. Normal Run integration
and managed production-child display are still pending; do not imply these experimental
outputs are ordinary managed jobs. Focused4 tests, real-app headless review and lint
passed; source snapshots independently replay. See docs/simulation_submodel.md.

- 2026-11-18: Local CPU VMMC duplex workflow in `oxdna_vmmc.py` / `oxdna_vmmc_runner.py`; wizard toggle mutually exclusive with ramp. Native-pair umbrella tuning → frozen-weight independent replicas → finite-size-corrected histogram analysis, CSV/JSON and explicit inconclusive diagnostics. Scope undamaged complementary linear DNA duplex only; no CPD VMMC validation. Interrupted stages replay whole-stage inputs/seeds; completed stages retained. Native browser/API validation of existing duplex completed all 8 short stages; not a convergence study. See `docs/oxdna_setup.md` and `.development-artifacts/vmmc-development/validation.json`.

- VMMC guide alignment: new production defaults 2e9 steps/replica, output 1e6 trajectory/1e5 energy, moves 0.1/0.2. RNA-specific weights/temperatures are not DNA defaults; short tuning remains unvalidated. Unified and legacy job menus both expose View results. Results include replica curves/conditions/transition counts and new analyses persist pair-count distributions. Old analyses display available fields without migration.

- VMMC compact-box root cause c795362c46bc: earlier maxclust=12 / preserve_topology=true
  mitigation failed again at 22,655,761 sweeps (first failure 8,637,171). Native fresh-pair
  audit reproduced an accepted rotation changing an internal Debye–Hückel energy at
  sweep 1,056,435 because the minimum-image pair vector changed by one box length.
  `tools/oxdna_vmmc/periodic-clusters.patch` rejects image-inconsistent rotations with
  a symmetric geometric predicate; absolute energy discrepancy check retains 1e-4
  tolerance/every10 sweeps. Build installs `-vmmc-v1`; controller requires native
  signature and revisions stage receipts. Incompatible completed stages and suffix
  rerun with old outputs/analysis archived, never mixed. maxclust12 retained;
  preserve_topology=false removes the ineffective displacement mitigation. No changes
  to concentration, salt or force field. Details/reproduction in tools/oxdna_vmmc/README.md
  and .development-artifacts/vmmc-root-cause/. Numerical correctness is not convergence.
  Validation: three independent 2M-sweep fresh-pair native audits passed at 1e-8;
  actual installed engine completed all14 short workflow stages, correctly
  inconclusive. Two compiled predicate tests passed; FAST20,986 passed/90skipped,
  FULL deferred (no dedicated session), lint passed. Corrected user job restarted
  from tuning, first5 stages completed; production still running, not certified
  complete/converged. Event-driven30M observer: .development-artifacts/vmmc-root-cause/watch_production.py;
  check production_validation.json for actual milestone evidence, never assume it exists.

- 2026-11-19 GPU umbrella investigation: experimental CLI `tools/oxdna_umbrella/`
  uses fixed periodic COM-distance MD windows and unbinned WHAM/MBAR at one T,
  with overlap/correlation/block-bootstrap diagnostics. Not integrated into the
  managed wizard; no Tm or CPD validation claimed. Native LTCOMTrap CUDA ignored
  PBC; `gpu-com-periodic.patch` corrects the minimum image and zero-distance guard.
  Candidate engine suffix `-umbrella-v1` remains isolated while benchmarking;
  build script reproduces it and writes a checked library-hash receipt. One-step
  boundary-frame CPU/GPU max velocity error fell from 5.96e-4 to 4.49e-8.
  Two-sided restraint reports double energy: analysis correctly uses one pair
  potential. Compact cells need max_density_multiplier10. MPS helper owns/cleans
  its service; copied source structures are existing native exports only.
  Short bound/unbound-start pilots disagree severely; do not treat their narrow
  bootstrap intervals as convergence. Extended fixed-budget trials and size
  benchmarks are under .development-artifacts/gpu-umbrella/. User authorized
  canceling VMMC c795362c46bc only if a credible improvement is demonstrated.
  Completed evidence: two 12-window pilots (100k equil +500k production/window)
  and two continued campaigns (1M equil +2M production/window). Extended72M MD
  steps finished in433s combined under MPS, but p(bound) at70C was0.817 vs0.107
  for bound/unbound starts (VMMC reference0.709). No credible sampling improvement;
  VMMC remains running. Native MD GPU/CPU loop speedups:16nt0.45x,100nt2.60x,
  404nt20.15x,504nt39.99x. Existing30849-particle DNANM surface job91.90x,
  preserving all original parameters/forces; not a controlled pure-DNA N series.
  The32768-nt upstream DNA1 example failed DNA2 preparation and was excluded.
  `scaling.py` defaults to the four working DNA cases; `scaling_job.py` handles
  existing completed MD jobs. All experimental processes/MPS/scratch directories
  cleaned; retained compact provenance and data under gpu-umbrella/ (summary.json).
  FAST20989 passed/90skipped; focused4 passed; lint and native parity passed;
  FULL deferred because no dedicated session. Current engine symlink unchanged.
