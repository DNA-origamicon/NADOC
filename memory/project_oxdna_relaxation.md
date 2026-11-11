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
