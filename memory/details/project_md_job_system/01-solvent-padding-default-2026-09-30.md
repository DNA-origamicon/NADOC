# Solvent padding default (2026-09-30) — supporting detail

[Topic head](../../project_md_job_system.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Solvent padding default (2026-09-30)

New explicit-solvent jobs, the Recommended box control, hardware estimates, and
all built-in explicit-solvent relaxation presets now default to 6 nm per face.
The field is labeled “Initial solvent padding (nm per face)”; preparation preserves
the selected value, while subsequent pressure equilibration can change cell dimensions.
This is NADOC's safety margin, deliberately larger than the literature's initial
4 nm inter-image gap; it is not a claim that the reference used 6 nm per face.
Explicit user values, saved setup choices and existing production cells retain
their settings. The archive envelope audit is in
`.development-artifacts/padding-envelope-20260930/`; reusable analysis is
`tools/trajectory_padding_audit.py`. It reads only the final 20 ns of each selected
trajectory and distinguishes aligned deformation from motion in the cell axes.
Six eligible 24HB trajectories (related restarts, not independent replicas)
required 5.68–5.97 nm per face from the prepared shape to enclose the aligned
3σ envelope plus a 4 nm inter-envelope gap; retaining rotation reached 6.05 nm.
Use 6.5 nm as a provisional allowance for this family, then verify equilibrated
clearance. The user selected 6 nm per face as the application default based on this audit. Existing tight cells
and one sparse 13-frame window limit this estimate; it is not a general guarantee.

## Bare gold qualification (2026-09-14)

Neutral INTERFACE 12–6 Au has shared model/geometry/package modules and the
`gold_qualification_v1` managed protocol. `/api/md/gold/jobs` prepares a bare slab
or particle; ordinary Start dispatches to the gold adapter, and the gold continuation
endpoint preserves complete checkpoint state. No gold frontend controls were added.
Generic production/settings changes and remote launch are rejected while physical
qualification is incomplete. Native resident execution uses GPU atom migration off
after observed patch-limit/exclusion failures. Gold–S, polarization and constant
potential are unsupported. See [selection and capabilities](../../../docs/namd_gold_model_selection.md)
and the [restart diagnosis](../../../experiments/gold_interfaces/evidence/gold_restart_diagnosis_20260915/RESULTS.md).
The historical native report at `.development-artifacts/gold_validation_20260914/RESULTS.md`
is unavailable in this checkout (checked October 17); do not treat it as accessible
validation evidence. Its recorded strict split-run precision residual and unresolved
density/statistical qualification are retained here. The linked restart diagnosis
above remains available; it is a separate report, not a replacement for missing bytes.

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
narratives are in [the archive](../../project_md_job_system_archive.md).

## Current state

- Two-electrode system is a new mutually exclusive setup mode with inline Settings:
  normal, gap (10 nm default), lateral spans (10 × 10 nm), and signed working
  charge (−0.0413 C/m²); equal-area countercharge is derived. Workspace presets
  capture it. Hard surface, charge and nanopore are exclusive with it; PEG can
  coexist and grafts to the working electrode. An isolated two-wall package builder and neutral-cell EW3DC Tcl correction now
  exist, with a prepared 95,208-atom control and guarded native qualification
  harness. The electrode wizard preset now routes managed preparation through
  shared ENM/HMR/chunks, with separate bulk NPT and fixed-cell NVT. User-requested native validation is authorized independently of the heavy-test-session gate. Four current DNA/PEG cases are prepared under
  `.development-artifacts/electrode_relax_validation_20260913_v2`. Native solvent-only job `89af63c3abb7` (6,232 atoms, bounded 4 nm liquid control) finished 7.2 ns with normal engine exits after a passing matched bulk reference. Final density/confinement pass, but Na/Cl cumulative drift 0.1367/0.1167 exceeds 0.10: job remains unqualified and production is blocked. A 6 ns passing checkpoint does not override the final failure. Full-size 10 nm relaxation remains unvalidated. Solvent-only playback supports an empty DNA selection. Electrode completion, including worker recovery, requires the same health gate; Fix can extend a convergence-only failure from the final checkpoint without rebuilding. See `docs/namd_electrode_protocol.md` and `.development-artifacts/2electrode_solvent_only_validation/README.md` for the current campaign.
  Older protocols trigger a cancellable warning and continue unchanged only on confirmation.
  See `docs/namd_electrode_protocol.md` for limits and convergence thresholds. Gold and
  constant-potential controls are not represented as supported options. Toggling
  this mode now renders two schematic planes and external charge signs, with camera
  framing, independently of job selection; it cannot alter/export molecular geometry.
- NAMD Setup presets above Benchmark create/select/overwrite/delete workspace-wide
  snapshots of all lower-card configuration fields plus PEG, anchors and occupancy
  scope. Stored under `workspace/namd_setup_presets`; revision checks reject stale
  writes. No wizard salt/protocol override or execution action. Cross-design anchor
  and scope references require reselection. See [setup presets](../../../docs/namd_setup_presets.md).
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
  See [method and validation](../../../experiments/charged_surface/README.md). Ion-only
  screening excludes water polarization and does not certify equilibration.

- Charged closed-wall controls now support blank documents: editable sheet charge and
  reservoir padding with Box and solvent-owned NaCl and surface-control temperature; exact counterions and PSF charge audit;
  standard NVT relaxation and production inheritance. See
  [charged-surface scope and qualification](../../../docs/namd_charged_surface.md).
  Prepared review: `NAMD_charged_wall_control.nadoc`, job `6ed2945c805e`, native relaxation running with periodic profile snapshots.
  This is a periodic carbon-like surrogate, not a silica/slab-corrected literature
  reproduction. Initial native concentration bins match an independent reader; Debye recovery remains unvalidated.

- PEG qualification/fast-relax visualization now routes the shared Display MD, RMSF,
  trajectory, solvent/cell and atomistic representation controls to saved PEG atom
  indices. Active-stage frames and continuation rollback are supported. Production-only
  occupancy and DNA-specific analyses expose applicability limits; see
  [PEG visualization](../../../docs/namd_peg_visualization.md).

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
