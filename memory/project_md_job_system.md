---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---
# MD job system

## Bare gold qualification (2026-09-14)

Neutral INTERFACE 12–6 Au has shared model/geometry/package modules and the
`gold_qualification_v1` managed protocol. `/api/md/gold/jobs` prepares a bare slab
or particle; ordinary Start dispatches to the gold adapter, and the gold continuation
endpoint preserves complete checkpoint state. No gold frontend controls were added.
Generic production/settings changes and remote launch are rejected while physical
qualification is incomplete. Native resident execution uses GPU atom migration off
after observed patch-limit/exclusion failures. Gold–S, polarization and constant
potential are unsupported. See [selection and capabilities](../docs/namd_gold_model_selection.md)
and [native results](../workspace/gold_validation_20260914/RESULTS.md), including the
strict split-run precision residual and unresolved density/statistical validation.

## Box and solvent sidebar (2026-09-13)

`md_box_solvent.js` owns preparation controls shared with the live relaxation wizard;
metadata `namd_box_solvent` persists current document choices, while named setup presets
remain workspace-global. Explicit cell dimensions bypass geometry estimation for blank
parts. Production inherits its source preparation. `md_preparation_details.js` is a
setup-only overlay with compact green offset dimensions with edge extension lines, a green-bordered
conditions callout and camera-following 45-degree leader, margin/solvent volume, approximate bulk ion counts,
temperature and periodic/slab face colors. Two-electrode dimensions follow the paired
surface settings, including 3× normal vacuum padding; the experimental Electrode relaxation protocol now owns managed preparation;
native qualification remains pending. See `docs/namd_box_solvent.md`.


Canonical current-state guide for managed NAMD jobs, the Job Wizard, local/remote execution,
queueing, production spawning, health reporting, and resume behavior. Historical implementation
narratives are in [the archive](project_md_job_system_archive.md).

## Current state

- Two-electrode system is a new mutually exclusive setup mode with inline Settings:
  normal, gap (10 nm default), lateral spans (10 × 10 nm), and signed working
  charge (−0.0413 C/m²); equal-area countercharge is derived. Workspace presets
  capture it. Hard surface, charge and nanopore are exclusive with it; PEG can
  coexist and grafts to the working electrode. An isolated two-wall package builder and neutral-cell EW3DC Tcl correction now
  exist, with a prepared 95,208-atom control and guarded native qualification
  harness. The electrode wizard preset now routes managed preparation through
  shared ENM/HMR/chunks, with separate bulk NPT and fixed-cell NVT. User-requested native validation is authorized independently of the heavy-test-session gate. Four current DNA/PEG cases are prepared under
  `workspace/electrode_relax_validation_20260913_v2`. Native solvent-only job `89af63c3abb7` (6,232 atoms, bounded 4 nm liquid control) finished 7.2 ns with normal engine exits after a passing matched bulk reference. Final density/confinement pass, but Na/Cl cumulative drift 0.1367/0.1167 exceeds 0.10: job remains unqualified and production is blocked. A 6 ns passing checkpoint does not override the final failure. Full-size 10 nm relaxation remains unvalidated. Solvent-only playback supports an empty DNA selection. Electrode completion, including worker recovery, requires the same health gate; Fix can extend a convergence-only failure from the final checkpoint without rebuilding. See `docs/namd_electrode_protocol.md` and `workspace/2electrode_solvent_only_validation/README.md` for the current campaign.
  Older protocols trigger a cancellable warning and continue unchanged only on confirmation.
  See `docs/namd_electrode_protocol.md` for limits and convergence thresholds. Gold and
  constant-potential controls are not represented as supported options. Toggling
  this mode now renders two schematic planes and external charge signs, with camera
  framing, independently of job selection; it cannot alter/export molecular geometry.
- NAMD Setup presets above Benchmark create/select/overwrite/delete workspace-wide
  snapshots of all lower-card configuration fields plus PEG, anchors and occupancy
  scope. Stored under `workspace/namd_setup_presets`; revision checks reject stale
  writes. No wizard salt/protocol override or execution action. Cross-design anchor
  and scope references require reselection. See [setup presets](../docs/namd_setup_presets.md).
- PEG now has its own toggle and inline collapsible Settings, with document metadata
  autosave and inline review. No popup or new PEG surface-library save. Disabled
  coating values and both repeat-unit/segment parameter sets are preserved.


- Hard surface uses five toggle rows (Hard surface on / Add surface charge /
  Graphene nanopore / Two-electrode system / PEG coating), each with collapsed Settings. PEG has its own layout and chain settings; charge and open pore are mutually exclusive. Surface
  rendering requires an explicit selected job with saved surface inclusion, and
  follows its snapshot rather than editable inputs. Auto-selection and document
  loading stay hidden; deselection/non-surface jobs clear all NAMD surface channels.
  Native PEG review additionally matches the selected job ID after asynchronous loads.
  Coating intent lives in `metadata.namd_peg_coating`; removal retains the library
  draft. Draft parameters and review remain in inline settings, outside the scene. Arbitrary draft
  molecular incorporation remains a gap. Box sizing, water margin, NaCl/Mg and surface-control temperature now live in the collapsible Box and solvent card; ordinary DNA temperature remains protocol-controlled.

- Surface ions and screening opens an interactive parameter/graph popup with
  Calculate and JSON export. Ion transport uses Generate → Display / Export
  (PNG/CSV), with generated results scoped to the selected job.
  Surface profiles measure closed-wall NaCl
  controls (including production children): per-face mM profiles, ionic charge,
  pooled compensation, finite-slit diagnostic fit, bulk Debye reference and block
  estimates. Per-job JSON persists; the native monitor saves periodic snapshots.
  See [method and validation](../experiments/charged_surface/README.md). Ion-only
  screening excludes water polarization and does not certify equilibration.

- Charged closed-wall controls now support blank documents: editable sheet charge and
  reservoir padding with Box and solvent-owned NaCl and surface-control temperature; exact counterions and PSF charge audit;
  standard NVT relaxation and production inheritance. See
  [charged-surface scope and qualification](../docs/namd_charged_surface.md).
  Prepared review: `NAMD_charged_wall_control.nadoc`, job `6ed2945c805e`, native relaxation running with periodic profile snapshots.
  This is a periodic carbon-like surrogate, not a silica/slab-corrected literature
  reproduction. Initial native concentration bins match an independent reader; Debye recovery remains unvalidated.

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

- 2026-09-14 short electrode volume screen: 4/6/8 nm lateral sides at fixed 4 nm
  gap, 240 ps each, 10/22/39 ions. Larger counts lower short-window drift, but both
  larger jobs fail density; see `workspace/electrode_volume_screen_20260914/README.md`.
  GPU-resident one-worker timing is ~1.46x faster than offload at 24,677 atoms;
  CPU/Tcl coordinate and force handling remains ~70% of step time. Long resident
  qualification and physical-time/correlation-aware profile windows remain open.

- User preference (2026-09-14): future local NAMD electrode experimental dynamics
  should use GPU-resident mode; use one CPU worker based on measured timings.
  Explicit offload is reserved for requested comparisons or documented engine
  compatibility issues. Electrode preparation now maps `auto` to `on`, preserving
  explicit `off`; minimization retains its established offload startup path.
- Isolated direct-array NAMD prototype built at `workspace/electrode_native_bridge_v2/namd3`:
  bypasses per-atom Tcl conversion, ~6.6x faster than the compiled Tcl callback in
  resident mode at 24,677 atoms. Three-axis force/energy audits match exactly; 40 ps
  finite/confined dynamics passed. Still experimental: no long/DNA/PEG qualification,
  no installed engine replacement, matching bridge callback required. See
  `experiments/electrode_relax/native_bridge/README.md` and
  `workspace/electrode_native_bridge_validation_v2/README.md`.

- Completed resident Debye diagnostic (2026-09-14): 2.64 ns, 8 × 4 × 8 nm liquid,
  25,839 atoms/41 Na-Cl pairs. Jobs c6d0bcfc861d/e04b05b6df8a/df270bd5872a retained
  against `2electrode_solvent_only.nadoc`; all native/density/confinement/profile
  checks pass. Equilibrated solvent + experimental 0.22 nm oxygen clearance passes
  this empty control; default 0.32 nm still underfills it. Pooled λ=0.573 nm versus
  classical 0.536–0.605 nm looks promising but chunk fits 0.405/1.745 nm disagree:
  not quantitative Debye convergence, despite passing profile gates. Full ladder,
  DNA/PEG, dielectric, salt scaling and finite-gap checks remain open. Details:
  `workspace/electrode_debye_validation_20260914_v2/README.md`.
- Explicit experimental engine path/hash now survives adoption and restart, verified
  against package provenance (`namd_experimental_engine.py`). Callback remains an
  explicit experimental package choice. Installed NAMD remains unchanged.

- Larger-gap comparison completed (2026-09-14): 6 nm gap, 8×8 nm area, 38,644 atoms,
  64 Na-Cl pairs, same 300 mM target/300 K/2 fs, 2.64 ns GPU-resident. Jobs
  bf1562116993/f4bbd57fbd5b/2fb3c67ae5d9 retained and completed; density 33.17 nm^-3,
  confinement/profile gates pass. λ fits 0.580/0.819 nm across chunks, pooled
  0.685 vs classical 0.551–0.623: better constrained than 4 nm but central salt
  still changes 343→269 mM and microscopic field remains noisy. Not Debye convergence.
  `workspace/electrode_gap6_validation_20260914/README.md` and `PERFORMANCE.md`.
  Runtime 86.3 min; sustained ~44–45 ns/day and sampled GPU util ~28%. Remaining
  CPU gather/correction/scatter + padded PME limit speed, despite native-array
  bridge. Archived local DNA reference ~392 ns/day at 4 fs is not a matched benchmark.

- GPU correction prototype (2026-09-14): `experiments/electrode_relax/gpu_correction/`
  implements EW3DC moment, wall repulsion and harmonic anchors via NAMD's existing
  dynamic CUDA client API, without replacing the installed engine. No ordinary
  atomic position/force host transfers; scalar energy and server synchronization
  remain. Three-axis stressed and normal force/energy audits match CPU/NumPy;
  isolated configuration tests guard ordering and double application. Final build
  and source hashes: `workspace/electrode_gpu_plugin_final/provenance.json`.
  Longer performance/post-migration audits: `workspace/electrode_gpu_benchmark_final/`.
  Explicit experimental fixed-cell path only; managed plugin restart provenance,
  full ladder/minimization, DNA/PEG, virials, multi-GPU and long screening are open.

Final matched GPU benchmark: 254 ns/day without tuning, 291–297 ns/day with
GPU atom migration + twoAwayZ, versus 43.1 ns/day CPU at the same 2 fs (6.8–6.9×).
Four 120 ps GPU endpoints pass force/energy audits; these do not establish Debye
convergence. Details: `workspace/electrode_gpu_benchmark_final/README.md`.


- Managed GPU electrodes (2026-09-14): the local runner now auto-selects the
  registered CUDA correction for a matching engine ABI and resident, single-GPU
  electrode job. `namd_electrode_gpu.py` pins package-local library/parameter/PSF
  checksums and reference forces; restart writer orders client creation last;
  accepted offload restores CPU forces. Registry: `workspace/runtime/electrode_gpu`.
  Missing/mismatched registry retains a documented reference path. Canonical source:
  `backend/core/native/electrode_gpu.cu`; no installed NAMD replacement.
- Real Start-API 4 fs solvent pilot passed, followed by longer retained sampling
  against `2electrode_solvent_only.nadoc`; campaign
  `workspace/electrode_gpu_screening_4fs_20260914/`. It uses unchanged rigid-water
  masses, 2 ps frames and a fixed 4 fs PME-update interval across 2/4 fs comparisons.
  Native stability does not establish timestep-independent dielectric/screening.
  Separate physical-time blocks and water-mode diagnostics are retained.
- Screening analysis no longer hardcodes 2 fs; it checks DCD headers and respects
  restart lineage. Electrode stationarity now retains 600 ps, not 60 frames.
  Native PID matching now excludes shell text that merely mentions a NAMD config.
  Managed scope, verification and remaining barriers: `docs/namd_electrode_gpu.md`.

- Managed campaign completed: all ten jobs retained/visible, 9.84 ns at 4 fs plus
  1.20 ns at 2 fs, all runtime gates passed; ~475 vs ~294 ns/day. Pooled λ values
  0.519/0.597 nm (4 fs series) and 0.604 nm (2 fs), not converged by window fits.
  Water rotational temperature ~294.18 K at 4 fs versus ~298.93 K at 2 fs;
  quantitative screening remains timestep-sensitive/unqualified. Native 20-step
  resume proof passes. Final campaign README and comparison/native_summary retain
  evidence. Existing screening popup still rejects two-electrode jobs (409);
  finite-gap graphs are standalone artifacts pending UI integration.
- User-requested 40 ns 4 fs continuation launched 2026-09-14: job `4eb7176339e4`
  under `2electrode_solvent_only.nadoc`, source `548581d231f7`, unchanged 6 nm gap,
  salt/charges/masses, 2 ps output. Native GPU-resident/GPU plugin launch verified.
  Campaign `workspace/electrode_gpu_screening_40ns_20260914/`; persistent standalone
  `monitor.py` writes live progress, cumulative 5/10/20/30/40 ns analyses and final
  separate 10 ns windows. Check progress/completion files before reporting outcome.
  Initial throughput ~425–440 ns/day (~2.2 hours). This tests time averaging only;
  it does not resolve known 4 fs water-mode bias. No extra simulations authorized
  by this launch beyond the one 40 ns continuation.
- Remote duplicates of the 40 ns 4 fs electrode validation (2026-09-14 10:52 MDT):
  Alpine `b2b224bcb96d`, Slurm `32557806`, RTX PRO 6000: force/energy/restart probes
  pass, 40 ns running (~850 ns/day after startup). Isolated glibc loader bundle fixes
  old Alpine runtime; exact local engine/plugin preserved. Prior probe allocations
  32557480 (missing dl/pthread/rt companions) and 32557606 (probe timestep numbering)
  failed before any 40 ns dynamics; retained evidence. RunPod `4665025e7158` uses
  PRO 4500 Blackwell at $0.72/h after user changed GPU preference and capped total
  job spend at $5. Pod `q1qt7czydiaa15`, five-hour provider expiry + independent
  systemd watchdog. Check campaign `electrode_remote_40ns_20260914` for actual current
  validation/status; do not assume completed. Controllers retain ordinary job-list
  metadata, exact initial checkpoint/seed, and all fetched bytes on archive storage.
  Global remote engine defaults remain unchanged; generic remote resume/requeue GPU
  initialization is a remaining integration gap, documented in namd_electrode_gpu.md.

- Remote campaign update: initial RunPod PRO 4500 pod terminated after tar ownership
  failure ($0.035398); fixed `--no-same-owner` and reused verified archive. Current
  pod `smsmj10f1fr4p4` is RTX 4090 at $0.74/hour, force/energy/restart probes pass,
  40 ns running (~750 ns/day). User $5 total cap includes prior attempt; provider
  expiry 2026-09-14T22:02:58Z + independent watchdog. Alpine remains running ~850
  ns/day. Both hardware duplicates' input/config equality audited against local run.
  Proof logs fetched onto Archive. Campaign README has current platform/budget details.
- Electrode cleanup (2026-09-14): 24 previous jobs / 3.53 GB moved to
  `/media/jojo/Archive/NADOC_electrode_history/2026-09-14/jobs`. All data preserved.
  Eight ancestors remain in the archive index; 16 other trial entries retired from
  the catalogue (restore script/catalogue manifest in that archive). Three current
  40 ns jobs remain under workspace/md_jobs and running. 199 probe/benchmark
  symlinks and 16 analysis job lists repointed; gpu_screening.py source resolution
  is now archive-aware. Historical raw snapshots/log paths remain provenance; use
  archive move_manifest.json for translation. See docs/namd_electrode_archive.md.

- 2026-09-14 remote 40 ns result processing: both Alpine and RunPod native runs
  completed normally at 10M steps. User configured podless S3; RunPod 9.32 GB/36
  files retrieved, 20k DCD frames verified, job outputs marked verified. Compute
  total $1.074943 including cancelled transfer pod. Screening fit 0.551 nm vs
  central-salt classical 0.539 nm (ε=78.3); local reference 0.553 nm. Window/block
  sensitivity and limitations in electrode_remote_40ns_20260914/RESULTS.md.
  Alpine trajectory retrieval + cached analysis + job/report publication continue
  via process_results.py, resume_cached_analysis.py, publish_alpine_results.py.
  Missing local campaign status fixed; corrupted Alpine job.json trailing brace
  backed up/repaired and old overlapping monitor stopped. No broad save-lock fix.

- Alpine result processing subsequently completed: 47 files/9.344 GB SHA256 verified,
  20k frames analyzed, job download state verified. Full fit 0.575 nm versus
  classical 0.541; last 20 ns 0.547 nm, with a decreasing 10 ns-window trend.
  docs/namd_debye_assessment.md summarizes campaigns, literature and remaining
  timestep/dielectric/metal-response validation. No new dynamics in this assessment.
